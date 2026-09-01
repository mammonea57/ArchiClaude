"""ControlNet-canny SDXL fine-tuning endpoint for ArchiClaude on Modal A100-80GB.

Chantier : "render exact -> photo" (refs/render_engine_rd/CHANTIER_controlnet_render2photo.md).

But : fine-tuner le ControlNet-canny SDXL PRÉ-ENTRAÎNÉ
(`diffusers/controlnet-canny-sdxl-1.0`) sur NOTRE domaine (vraies photos
archi/rue Paris-IDF, dataset 768²→1024 paires canny↔photo) pour qu'à
l'inférence il pose une VRAIE PHOTO sur la géométrie exacte de nos canny
issus du rendu Cycles. On ne part PAS de zéro : on continue l'entraînement
du ControlNet public.

Stratégie : on emballe le script OFFICIEL diffusers
`examples/controlnet/train_controlnet_sdxl.py` (v0.32.0) dans l'image Modal
et on le lance via `accelerate launch`. C'est l'impl de référence amont
(loss SDXL + add_time_ids + validation intégrés) — on ne ré-implémente rien.

Dataset attendu sur le Volume `archfr-r2p-dataset` (layout FIXÉ 2026-06-30) :
    /data/
      train/
        *.jpg                 (photos couleur — SEULES images scannées)
        metadata.jsonl        format imagefolder diffusers :
          {"file_name": "xxx.jpg",
           "conditioning_image": "/data/conditioning/xxx.png",
           "text": "a real photograph of a Parisian ... facade ..."}
      conditioning/*.png      (cartes canny appariées — HORS dossier scanné)

POURQUOI ce layout : `load_dataset(train_data_dir)` utilise le builder
`imagefolder` qui scanne RÉCURSIVEMENT toutes les images sous train_data_dir
et exige une ligne metadata (clé `file_name`) pour CHACUNE. Si les canny sont
dans le même arbre scanné, il réclame une metadata pour eux aussi →
`ValueError: image at canny/xxx.png doesn't have metadata`. On met donc :
  - `--train_data_dir /data/train` = SEULEMENT les .jpg principaux + metadata,
  - les canny dans `/data/conditioning/` (hors scan), référencés par chemin
    ABSOLU dans `conditioning_image`. Le patch ArchiClaude de
    train_controlnet_sdxl.py caste cette colonne en feature Image() qui décode
    le chemin absolu en PIL.

Workflow :
    cd apps/render-service

    # 1) upload dataset (images + canny + metadata.jsonl) -> Volume Modal
    .venv/bin/modal run src/modal_controlnet_train_endpoint.py::upload_cli

    # 2) SMOKE TEST (50 steps, ~$2-4) — valide la chaîne de bout en bout
    .venv/bin/modal run src/modal_controlnet_train_endpoint.py::smoke_cli

    # 3) RUN COMPLET (voir train_cli + rapport)
    .venv/bin/modal run src/modal_controlnet_train_endpoint.py::train_cli \
        --max-train-steps 15000 --output-name r2p_canny_sdxl_v1
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import modal

app = modal.App("archfr-controlnet-train")

SDXL_BASE = "stabilityai/stable-diffusion-xl-base-1.0"
VAE_FP16_FIX = "madebyollin/sdxl-vae-fp16-fix"
CONTROLNET_BASE = "diffusers/controlnet-canny-sdxl-1.0"

# Chemins locaux (côté Mac) bundlés dans l'image Modal.
# NB : ce module est aussi importé DANS le conteneur Modal où __file__=/root/...
# → parents[3] n'existe pas (IndexError). REPO ne sert qu'en local (upload),
# donc on retombe sur un chemin bidon dans le conteneur sans casser l'import.
try:
    REPO = Path(__file__).resolve().parents[3]
except IndexError:
    REPO = Path("/root")   # conteneur Modal : REPO non utilisé ici
DATASET_LOCAL = REPO / "refs" / "render_engine_rd" / "dataset"
TRAIN_SCRIPT_LOCAL = (
    REPO / "refs" / "render_engine_rd" / "train_scripts" / "train_controlnet_sdxl.py"
)

# --- Image Modal : pins compatibles avec train_controlnet_sdxl.py v0.32.0 ----
image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .pip_install(
        "torch==2.4.1",
        "torchvision==0.19.1",
        "diffusers==0.32.0",
        "transformers==4.46.0",
        "accelerate==1.2.0",
        "datasets==3.0.1",
        "safetensors>=0.4.5",
        "huggingface_hub>=0.25,<0.27",
        "pillow>=10.4",
        "opencv-python-headless==4.10.0.84",
        "numpy>=1.26,<2.0",
        "ftfy",
        "tensorboard",
        "Jinja2",
    )
    # Le script officiel diffusers, embarqué dans l'image.
    .add_local_file(
        str(TRAIN_SCRIPT_LOCAL),
        "/root/train_controlnet_sdxl.py",
        copy=True,
    )
)

# Volumes persistants
hf_cache = modal.Volume.from_name("archfr-hf-cache", create_if_missing=True)
dataset_vol = modal.Volume.from_name("archfr-r2p-dataset", create_if_missing=True)
ckpt_vol = modal.Volume.from_name("archfr-r2p-ckpt", create_if_missing=True)


# =============================================================================
# 1. UPLOAD DATASET -> Volume
# =============================================================================
@app.function(
    image=modal.Image.debian_slim(python_version="3.11"),
    volumes={"/data": dataset_vol},
    timeout=3600,
)
def _list_dataset() -> dict:
    """Inspecte le Volume dataset (debug)."""
    root = Path("/data")
    out = {}
    train = root / "train"
    out["train_jpg"] = len(list(train.glob("*.jpg"))) if train.exists() else 0
    cond = root / "conditioning"
    out["conditioning_png"] = len(list(cond.glob("*.png"))) if cond.exists() else 0
    meta = train / "metadata.jsonl"
    out["metadata_lines"] = sum(1 for _ in meta.open()) if meta.exists() else 0
    return out


@app.local_entrypoint()
def upload_cli(limit: int = 0):
    """Upload le dataset vers le Volume archfr-r2p-dataset dans le layout FIXÉ :

        /data/train/<basename>.jpg     (images principales — seules scannées)
        /data/train/metadata.jsonl     {"file_name": "<basename>.jpg",
                                         "conditioning_image": "/data/conditioning/<basename>.png",
                                         "text": "..."}
        /data/conditioning/<basename>.png   (canny — HORS dossier scanné)

    Le metadata.jsonl LOCAL utilise des chemins relatifs au dataset
    (`images/xxx.jpg`, `canny/xxx.png`). On le RÉÉCRIT ici au format Volume :
    `file_name` = basename de l'image, `conditioning_image` = chemin ABSOLU
    `/data/conditioning/<basename>.png`. Ainsi `imagefolder` ne voit que les
    .jpg de /data/train, et le patch du script décode le canny via son chemin
    absolu.

    --limit N : sous-échantillon (utile pour itérer vite). 0 = tout.
    """
    import json

    meta_path = DATASET_LOCAL / "metadata.jsonl"
    if not meta_path.exists():
        raise SystemExit(
            f"metadata.jsonl introuvable : {meta_path}\n"
            "Lance d'abord : python3 scripts/gen_controlnet_captions.py"
        )

    rows = [json.loads(l) for l in meta_path.open() if l.strip()]
    if limit:
        rows = rows[:limit]
    print(f"→ upload de {len(rows)} paires vers archfr-r2p-dataset (layout train/+conditioning/) …")

    vol = modal.Volume.from_name("archfr-r2p-dataset", create_if_missing=True)

    # Construit le metadata.jsonl côté Volume : file_name = basename du .jpg,
    # conditioning_image = chemin ABSOLU vers le canny dans /data/conditioning.
    vol_rows = []
    for r in rows:
        img_base = Path(r["file_name"]).name          # ex. 00000_..._Par.jpg
        cond_base = Path(r["conditioning_image"]).name  # ex. 00000_..._Par.png
        vol_rows.append({
            "file_name": img_base,
            "conditioning_image": f"/data/conditioning/{cond_base}",
            "text": r["text"],
        })

    tmp_meta = DATASET_LOCAL / f".metadata_volume_{limit or 'all'}.jsonl"
    with tmp_meta.open("w") as f:
        for vr in vol_rows:
            f.write(json.dumps(vr, ensure_ascii=False) + "\n")

    with vol.batch_upload(force=True) as batch:
        batch.put_file(str(tmp_meta), "/train/metadata.jsonl")
        for r in rows:
            img_base = Path(r["file_name"]).name
            cond_base = Path(r["conditioning_image"]).name
            batch.put_file(
                str(DATASET_LOCAL / r["file_name"]),
                f"/train/{img_base}",
            )
            batch.put_file(
                str(DATASET_LOCAL / r["conditioning_image"]),
                f"/conditioning/{cond_base}",
            )
    tmp_meta.unlink(missing_ok=True)
    print("✓ upload terminé.")
    info = _list_dataset.remote()
    print(f"  Volume contient : {info}")


# =============================================================================
# 2. TRAINING (wrap accelerate launch train_controlnet_sdxl.py)
# =============================================================================
@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=24 * 3600,
    # Préemption-résilient : Modal relance la fonction (jusqu'à 10×) et, grâce
    # au commit périodique du Volume + --resume_from_checkpoint latest, ça
    # REPREND du dernier checkpoint au lieu de repartir de zéro.
    retries=modal.Retries(max_retries=10, backoff_coefficient=1.0, initial_delay=5.0),
    volumes={
        "/root/.cache/huggingface": hf_cache,
        "/data": dataset_vol,
        "/ckpt": ckpt_vol,
    },
    secrets=[modal.Secret.from_name("huggingface")],
)
def train_controlnet(
    output_name: str,
    max_train_steps: int = 15000,
    resolution: int = 1024,
    train_batch_size: int = 4,
    grad_accum: int = 4,
    lr: float = 1e-5,
    lr_scheduler: str = "constant_with_warmup",
    lr_warmup_steps: int = 500,
    checkpointing_steps: int = 1000,
    validation_steps: int = 1000,
    proportion_empty_prompts: float = 0.05,
    seed: int = 42,
    run_validation: bool = True,
) -> str:
    """Lance le script officiel diffusers via accelerate.

    Fine-tune À PARTIR de `diffusers/controlnet-canny-sdxl-1.0`
    (--controlnet_model_name_or_path), base SDXL + VAE fp16-fix, bf16,
    gradient checkpointing. Checkpoints -> Volume /ckpt/<output_name>.
    """
    import json

    out_dir = Path("/ckpt") / output_name
    out_dir.mkdir(parents=True, exist_ok=True)

    # Validation : on prend 1 canny du dataset + une caption type.
    val_image_arg = []
    val_prompt_arg = []
    if run_validation:
        meta = Path("/data/train/metadata.jsonl")
        first = json.loads(meta.open().readline())
        # conditioning_image est déjà un chemin ABSOLU (/data/conditioning/xxx.png).
        val_canny = first["conditioning_image"]
        if not os.path.isabs(val_canny):
            val_canny = "/data/" + val_canny
        val_image_arg = ["--validation_image", val_canny]
        val_prompt_arg = [
            "--validation_prompt",
            "a real photograph of a Parisian apartment building facade, "
            "stone and brick, balconies, daylight, street, photorealistic",
        ]

    cmd = [
        "accelerate", "launch",
        "--mixed_precision", "bf16",
        "/root/train_controlnet_sdxl.py",
        "--pretrained_model_name_or_path", SDXL_BASE,
        "--pretrained_vae_model_name_or_path", VAE_FP16_FIX,
        "--controlnet_model_name_or_path", CONTROLNET_BASE,
        "--output_dir", str(out_dir),
        "--train_data_dir", "/data/train",
        "--image_column", "image",
        "--conditioning_image_column", "conditioning_image",
        "--caption_column", "text",
        "--resolution", str(resolution),
        "--train_batch_size", str(train_batch_size),
        "--gradient_accumulation_steps", str(grad_accum),
        "--gradient_checkpointing",
        "--max_train_steps", str(max_train_steps),
        "--learning_rate", str(lr),
        "--lr_scheduler", lr_scheduler,
        "--lr_warmup_steps", str(lr_warmup_steps),
        "--checkpointing_steps", str(checkpointing_steps),
        "--resume_from_checkpoint", "latest",   # reprise auto après préemption
        "--proportion_empty_prompts", str(proportion_empty_prompts),
        "--mixed_precision", "bf16",
        "--seed", str(seed),
        "--dataloader_num_workers", "4",
    ]
    if run_validation:
        cmd += val_image_arg + val_prompt_arg
        cmd += ["--validation_steps", str(validation_steps)]
        cmd += ["--num_validation_images", "2"]

    env = os.environ.copy()
    env["HF_HUB_ENABLE_HF_TRANSFER"] = "0"

    print("=== LANCEMENT ENTRAÎNEMENT ===")
    print(" ".join(cmd))
    sys.stdout.flush()

    t0 = time.time()
    # Popen + commit périodique : persiste les checkpoints de /ckpt toutes les
    # ~3 min, pour qu'une préemption (puis retry + resume) reprenne du dernier
    # checkpoint au lieu de tout reperdre.
    import threading
    proc = subprocess.Popen(cmd, env=env)
    _stop = threading.Event()

    def _periodic_commit():
        while not _stop.wait(180):
            try:
                ckpt_vol.commit()
                print("  [vol] commit checkpoint périodique", flush=True)
            except Exception as _e:
                print(f"  [vol] commit warn: {_e}", flush=True)

    _th = threading.Thread(target=_periodic_commit, daemon=True)
    _th.start()
    proc.wait()
    _stop.set()
    elapsed = (time.time() - t0) / 60
    ckpt_vol.commit()

    if proc.returncode != 0:
        raise RuntimeError(
            f"accelerate launch a échoué (code {proc.returncode}) après {elapsed:.1f} min"
        )
    print(f"✓ entraînement terminé en {elapsed:.1f} min — sortie : {out_dir}")
    return str(out_dir)


# =============================================================================
# 3. SMOKE TEST — 50 steps + récupération de l'image de validation
# =============================================================================
@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=2 * 3600,
    volumes={
        "/root/.cache/huggingface": hf_cache,
        "/data": dataset_vol,
        "/ckpt": ckpt_vol,
    },
    secrets=[modal.Secret.from_name("huggingface")],
)
def smoke_test(
    max_train_steps: int = 50,
    resolution: int = 1024,
    train_batch_size: int = 2,
) -> dict:
    """Run court : valide chargement dataset, descente de loss, checkpoint,
    et inférence de validation. Retourne le PNG de validation + métriques.

    On lance le même script officiel mais avec validation_steps == max_steps
    pour forcer UNE validation à la fin, puis on relit l'image générée.
    """
    import glob
    import json
    import re

    out_dir = Path("/ckpt") / "smoke"
    if out_dir.exists():
        import shutil
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    meta = Path("/data/train/metadata.jsonl")
    n_pairs = sum(1 for _ in meta.open())
    first = json.loads(meta.open().readline())
    val_canny = first["conditioning_image"]  # chemin ABSOLU /data/conditioning/xxx.png
    if not os.path.isabs(val_canny):
        val_canny = "/data/" + val_canny

    cmd = [
        "accelerate", "launch",
        "--mixed_precision", "bf16",
        "/root/train_controlnet_sdxl.py",
        "--pretrained_model_name_or_path", SDXL_BASE,
        "--pretrained_vae_model_name_or_path", VAE_FP16_FIX,
        "--controlnet_model_name_or_path", CONTROLNET_BASE,
        "--output_dir", str(out_dir),
        "--train_data_dir", "/data/train",
        "--image_column", "image",
        "--conditioning_image_column", "conditioning_image",
        "--caption_column", "text",
        "--resolution", str(resolution),
        "--train_batch_size", str(train_batch_size),
        "--gradient_accumulation_steps", "1",
        "--gradient_checkpointing",
        "--max_train_steps", str(max_train_steps),
        "--learning_rate", "1e-5",
        "--lr_scheduler", "constant_with_warmup",
        "--lr_warmup_steps", "5",
        "--checkpointing_steps", str(max_train_steps),   # 1 checkpoint à la fin
        "--validation_steps", str(max_train_steps),      # 1 validation à la fin
        "--validation_image", val_canny,
        "--validation_prompt",
        "a real photograph of a Parisian apartment building facade, stone "
        "and brick, balconies, daylight, street, photorealistic",
        "--num_validation_images", "2",
        "--proportion_empty_prompts", "0.05",
        "--mixed_precision", "bf16",
        "--seed", "42",
        "--dataloader_num_workers", "2",
    ]

    print(f"=== SMOKE TEST — {n_pairs} paires, {max_train_steps} steps ===")
    print(" ".join(cmd))
    sys.stdout.flush()

    t0 = time.time()
    # Capture stdout/stderr pour extraire la loss.
    proc = subprocess.run(cmd, capture_output=True, text=True)
    elapsed = (time.time() - t0) / 60
    log = proc.stdout + "\n" + proc.stderr
    print(log[-6000:])  # tail des logs dans la sortie Modal
    ckpt_vol.commit()

    result: dict = {
        "returncode": proc.returncode,
        "elapsed_min": round(elapsed, 2),
        "n_pairs": n_pairs,
    }

    # Extraction des valeurs de loss depuis les logs (progress bar diffusers).
    losses = re.findall(r"loss=([0-9.]+)", log)
    if losses:
        result["loss_first"] = float(losses[0])
        result["loss_last"] = float(losses[-1])
        result["n_loss_points"] = len(losses)

    # Checkpoint écrit ?
    ckpts = glob.glob(str(out_dir / "checkpoint-*"))
    result["checkpoints"] = [Path(c).name for c in ckpts]

    # Image de validation : le script log via tensorboard/wandb si dispo,
    # sinon on génère nous-mêmes une validation post-entraînement à partir
    # du checkpoint pour être SÛR de récupérer un PNG.
    val_png = _generate_validation_png(out_dir, val_canny)
    result["validation_png_b64_len"] = len(val_png) if val_png else 0
    result["_validation_png"] = val_png  # bytes
    result["returncode_ok"] = proc.returncode == 0
    return result


def _generate_validation_png(ckpt_dir: Path, canny_path: str) -> Optional[bytes]:
    """Charge le ControlNet entraîné (dernier checkpoint) + SDXL et génère
    une image de validation à partir d'un canny. Retourne les bytes PNG."""
    import glob

    import torch
    from diffusers import (
        ControlNetModel,
        StableDiffusionXLControlNetPipeline,
        AutoencoderKL,
    )
    from PIL import Image

    # Cherche le ControlNet entraîné : soit à la racine output_dir (sauvegarde
    # finale du script), soit dans le dernier checkpoint-*/controlnet.
    cn_path = None
    if (ckpt_dir / "config.json").exists():
        cn_path = str(ckpt_dir)
    else:
        ckpts = sorted(
            glob.glob(str(ckpt_dir / "checkpoint-*")),
            key=lambda p: int(p.split("-")[-1]),
        )
        for c in reversed(ckpts):
            if (Path(c) / "controlnet").exists():
                cn_path = str(Path(c) / "controlnet")
                break
    if cn_path is None:
        print("WARN : aucun ControlNet entraîné trouvé pour la validation")
        return None

    print(f"validation : ControlNet chargé depuis {cn_path}")
    controlnet = ControlNetModel.from_pretrained(cn_path, torch_dtype=torch.float16)
    vae = AutoencoderKL.from_pretrained(VAE_FP16_FIX, torch_dtype=torch.float16)
    pipe = StableDiffusionXLControlNetPipeline.from_pretrained(
        SDXL_BASE, controlnet=controlnet, vae=vae, torch_dtype=torch.float16,
    )
    pipe.to("cuda")
    canny = Image.open(canny_path).convert("RGB").resize((1024, 1024))
    gen = torch.Generator(device="cuda").manual_seed(42)
    out = pipe(
        prompt=(
            "a real photograph of a Parisian apartment building facade, stone "
            "and brick, balconies, daylight, street, photorealistic"
        ),
        image=canny,
        num_inference_steps=30,
        controlnet_conditioning_scale=0.8,
        generator=gen,
    ).images[0]
    buf = io.BytesIO()
    out.save(buf, format="PNG")
    return buf.getvalue()


@app.local_entrypoint()
def smoke_cli(max_train_steps: int = 50, out_dir: str = "refs/render_engine_rd/smoke"):
    """SMOKE TEST de bout en bout. Sauve l'image de validation en local."""
    print("→ Smoke test ControlNet-canny SDXL sur Modal A100-80GB …")
    res = smoke_test.remote(max_train_steps=max_train_steps)
    png = res.pop("_validation_png", None)
    print("\n=== RÉSULTAT SMOKE ===")
    for k, v in res.items():
        print(f"  {k}: {v}")
    if png:
        outp = REPO / out_dir
        outp.mkdir(parents=True, exist_ok=True)
        path = outp / f"smoke_validation_{int(time.time())}.png"
        path.write_bytes(png)
        print(f"\n✓ image de validation sauvée : {path}")
    else:
        print("\n⚠ pas d'image de validation récupérée — voir logs ci-dessus")


@app.local_entrypoint()
def train_cli(
    output_name: str = "r2p_canny_sdxl_v1",
    max_train_steps: int = 15000,
    train_batch_size: int = 4,
    grad_accum: int = 4,
    lr: float = 1e-5,
    checkpointing_steps: int = 500,
    validation_steps: int = 1000,
):
    """Lance le RUN COMPLET. NE PAS lancer sans intention (coûte plusieurs heures A100)."""
    print(f"→ RUN COMPLET ControlNet-canny SDXL : {output_name}")
    print(f"  steps={max_train_steps} bs={train_batch_size} grad_accum={grad_accum} "
          f"eff_batch={train_batch_size * grad_accum} lr={lr} "
          f"ckpt={checkpointing_steps} val={validation_steps}")
    out = train_controlnet.remote(
        output_name=output_name,
        max_train_steps=max_train_steps,
        train_batch_size=train_batch_size,
        grad_accum=grad_accum,
        lr=lr,
        checkpointing_steps=checkpointing_steps,
        validation_steps=validation_steps,
    )
    print(f"✓ terminé : {out}")
