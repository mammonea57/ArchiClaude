#!/usr/bin/env python3
"""DATASET render→photo (ControlNet R&D) — étape 1 du chantier
`refs/render_engine_rd/CHANTIER_controlnet_render2photo.md`.

But : à partir du corpus refs/style_dataset, ne garder que les VRAIES PHOTOS
d'archi/rue (CLIP zero-shot, rejet des rendus 3D/CGI/illustrations/watermark),
puis dériver pour chacune sa carte canny (cv2) + sa depth map (DPT Intel/dpt-large)
→ paires (structure ↔ photo) prêtes à l'entraînement.

Sortie :
  refs/render_engine_rd/dataset/{images/, canny/, depth/}
  refs/render_engine_rd/dataset/manifest.jsonl
  refs/render_engine_rd/dataset_preview.png   (12-16 vignettes photo|canny)

Réutilise la mécanique CLIP de scripts/build_lora_v4_moodboard.py :
  open_clip ViT-B-32 laion2b_s34b_b79k, cache d'embeddings (clé path:mtime).

Lance avec le venv render-service (torch+open_clip+transformers+cv2) :
  apps/render-service/.venv/bin/python scripts/build_render2photo_dataset.py [--limit N] [--no-depth]
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REFS = ROOT / "refs"
SD = REFS / "style_dataset"

# Sources PRIMAIRES full-res uniquement. On exclut : thumbs (basse-déf dupliquées),
# _filtered_out (déjà rejetées), v4_moodboard_candidates (copies), smoke_test/*
# (sous-ensembles & rejets). Dédoublonnage par hash de contenu ensuite.
SRC_DIRS = [
    SD / "curate_pool" / "full",
    SD / "curate_pool" / "_filtered_photos" / "full",
    SD / "manual_refs",
    SD / "lora_dataset_full" / "images",
    # Scrape Wikimedia Commons (licence propre CC0/CC-BY/CC-BY-SA/PD) —
    # vraies photos archi/rue Paris/IDF, cf. scripts/scrape_wikimedia_commons.py.
    # Le filtre CLIP en aval écarte les non-photos/historiques/non-archi.
    SD / "commons_idf",
]
EXTS = {".jpg", ".jpeg", ".png", ".webp"}

OUT = REFS / "render_engine_rd" / "dataset"
EMB_CACHE = REFS / "render_engine_rd" / ".clip_r2p_cache.pt"
PREVIEW = REFS / "render_engine_rd" / "dataset_preview.png"

# ---- CLIP prompts (zero-shot, multi-gate) -----------------------------------
# Gate 1 : VRAIE PHOTO vs synthèse. On veut battre TOUTES les classes "non-photo".
PHOTO_PROMPTS = [
    "a real photograph of a building",
    "a real photograph of a street with buildings",
    "real architectural photography of a facade",
]
NONPHOTO_PROMPTS = [
    "a 3D render of a building",
    "a CGI architectural visualization",
    "an architectural rendering, archviz",
    "a digital illustration of a building",
    "an oil painting of a building",
    "an impressionist or post-impressionist painting",
    "a watercolor painting, an artwork in a museum",
    "a pencil drawing or sketch",
    "a video game screenshot",
    "a poster or image with text and a watermark and a user interface",
    # rejet sépia / N&B / scan archival (cible = photo moderne couleur)
    "an old sepia or black-and-white archival photograph",
    "a scanned document with a white border and inventory text",
    "a vintage monochrome photograph from the 19th or early 20th century",
]
# Gate 2 : c'est bien de l'archi/rue (pas un intérieur, portrait, objet, plan).
ARCHI_PROMPTS = [
    "the exterior facade of a building",
    "an urban street scene with buildings",
]
NONARCHI_PROMPTS = [
    "an indoor interior room with furniture",
    "a living room or bedroom interior",
    "an office or kitchen interior",
    "a portrait of a person",
    "a close-up of an object or product",
    "a floor plan or technical drawing",
    "a landscape with no buildings",
    "a map or diagram",
]


def iter_unique_sources():
    """Liste les sources primaires, dédoublonnées par hash de contenu."""
    seen = {}
    files = sorted(p for d in SRC_DIRS if d.exists()
                   for p in d.rglob("*") if p.suffix.lower() in EXTS)
    for p in files:
        try:
            h = hashlib.md5(p.read_bytes()).hexdigest()
        except Exception:
            continue
        # garde la 1re occurrence (ordre = curate_pool d'abord, déterministe)
        if h not in seen:
            seen[h] = p
    return list(seen.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="ne traiter que les N premières images (test sample)")
    ap.add_argument("--no-depth", action="store_true",
                    help="sauter DPT (canny seulement, pour itérer vite)")
    ap.add_argument("--min-side", type=int, default=512,
                    help="résolution mini (côté court) pour le gate qualité")
    ap.add_argument("--long-side", type=int, default=768,
                    help="côté de sortie (center-crop carré). 768 = compromis: "
                         "médiane corpus 576px, n'upscale pas massivement")
    ap.add_argument("--photo-margin", type=float, default=0.01,
                    help="marge cosinus : photo doit battre non-photo de cette marge "
                         "(durcit le rejet peintures/illustrations borderline)")
    ap.add_argument("--min-sat", type=float, default=0.12,
                    help="saturation HSV moyenne mini (0-1). En dessous = image "
                         "quasi-grise (sépia/N&B/scan archival) → rejet. Cible = "
                         "photo COULEUR moderne, pas scan d'archive.")
    args = ap.parse_args()

    import numpy as np
    import torch
    import cv2
    import open_clip
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    print(f"[r2p] device={device}", flush=True)

    print("[r2p] load CLIP ViT-B-32 …", flush=True)
    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="laion2b_s34b_b79k")
    tokenizer = open_clip.get_tokenizer("ViT-B-32")
    model.eval().to(device)

    all_prompts = (PHOTO_PROMPTS + NONPHOTO_PROMPTS
                   + ARCHI_PROMPTS + NONARCHI_PROMPTS)
    n_photo = len(PHOTO_PROMPTS)
    n_nonphoto = len(NONPHOTO_PROMPTS)
    n_archi = len(ARCHI_PROMPTS)
    i_photo = slice(0, n_photo)
    i_nonphoto = slice(n_photo, n_photo + n_nonphoto)
    i_archi = slice(n_photo + n_nonphoto, n_photo + n_nonphoto + n_archi)
    i_nonarchi = slice(n_photo + n_nonphoto + n_archi, len(all_prompts))
    with torch.no_grad():
        te = model.encode_text(tokenizer(all_prompts).to(device))
        te = te / te.norm(dim=-1, keepdim=True)

    srcs = iter_unique_sources()
    if args.limit:
        srcs = srcs[:args.limit]
    print(f"[r2p] {len(srcs)} images uniques (dédoublonnées) à scorer", flush=True)

    cache = {}
    if EMB_CACHE.exists():
        try:
            cache = torch.load(EMB_CACHE, weights_only=False)
            print(f"[r2p] cache embeddings : {len(cache)} entrées", flush=True)
        except Exception:
            cache = {}

    def mean_saturation(im_rgb):
        """Saturation HSV moyenne (0-1). Sépia/N&B → proche de 0.
        Calcul vectorisé sur une vignette pour rester rapide."""
        small = im_rgb.resize((128, 128))
        a = np.asarray(small).astype(np.float32) / 255.0
        mx = a.max(axis=2)
        mn = a.min(axis=2)
        sat = np.where(mx > 1e-6, (mx - mn) / (mx + 1e-6), 0.0)
        return float(sat.mean())

    kept = []           # (src_path, score_photo, score_margin)
    rej_synth = rej_archi = rej_qual = rej_err = rej_sepia = 0
    dirty = 0
    for i, p in enumerate(srcs):
        try:
            with Image.open(p) as im:
                im = im.convert("RGB")
                w, h = im.size
                # gate qualité : résolution mini sur le côté court
                if min(w, h) < args.min_side:
                    rej_qual += 1
                    continue
                # gate sépia/N&B : image quasi-grise → pas une photo couleur moderne
                if mean_saturation(im) < args.min_sat:
                    rej_sepia += 1
                    continue
                key = f"{p}:{p.stat().st_mtime_ns}"
                if key in cache:
                    e = cache[key]
                else:
                    with torch.no_grad():
                        e = model.encode_image(
                            preprocess(im).unsqueeze(0).to(device))
                        e = (e / e.norm(dim=-1, keepdim=True)).cpu()
                    cache[key] = e
                    dirty += 1
        except Exception as ex:
            print(f"  !! {p.name}: {ex}", flush=True)
            rej_err += 1
            continue
        with torch.no_grad():
            sims = (e @ te.cpu().T).squeeze(0)
        s_photo = float(sims[i_photo].max())
        s_nonphoto = float(sims[i_nonphoto].max())
        s_archi = float(sims[i_archi].max())
        s_nonarchi = float(sims[i_nonarchi].max())
        # Gate 1 : vraie photo bat la meilleure interprétation synthèse
        if s_photo < s_nonphoto + args.photo_margin:
            rej_synth += 1
            continue
        # Gate 2 : façade/rue bat intérieur/portrait/plan/etc.
        if s_archi < s_nonarchi:
            rej_archi += 1
            continue
        kept.append((p, s_photo, s_photo - s_nonphoto))
        if (i + 1) % 200 == 0:
            print(f"  {i+1}/{len(srcs)} | gardées {len(kept)} "
                  f"synth {rej_synth} sepia {rej_sepia} "
                  f"non-archi {rej_archi} qual {rej_qual}",
                  flush=True)
        if dirty and dirty % 300 == 0:
            torch.save(cache, EMB_CACHE)
    if dirty:
        torch.save(cache, EMB_CACHE)

    n_in = len(srcs)
    n_kept = len(kept)
    print(f"\n[r2p] === FILTRE CLIP ===", flush=True)
    print(f"  départ (uniques)   : {n_in}", flush=True)
    print(f"  rejet qualité      : {rej_qual}", flush=True)
    print(f"  rejet sépia/N&B    : {rej_sepia}", flush=True)
    print(f"  rejet synthèse/CGI : {rej_synth}", flush=True)
    print(f"  rejet non-archi    : {rej_archi}", flush=True)
    print(f"  rejet erreur       : {rej_err}", flush=True)
    print(f"  VRAIES PHOTOS      : {n_kept}  ({100*n_kept/max(n_in,1):.1f}%)",
          flush=True)

    # ---- Dérivation des paires ----------------------------------------------
    (OUT / "images").mkdir(parents=True, exist_ok=True)
    (OUT / "canny").mkdir(parents=True, exist_ok=True)
    (OUT / "depth").mkdir(parents=True, exist_ok=True)
    manifest_path = OUT / "manifest.jsonl"

    dpt = dpt_proc = None
    if not args.no_depth:
        from transformers import DPTForDepthEstimation, DPTImageProcessor
        print("[r2p] load DPT Intel/dpt-large …", flush=True)
        dpt = DPTForDepthEstimation.from_pretrained("Intel/dpt-large").eval().to(device)
        dpt_proc = DPTImageProcessor.from_pretrained("Intel/dpt-large")

    def resize_square(im_pil, side):
        """Resize proportionnel (côté long = side) puis center-crop carré."""
        w, h = im_pil.size
        scale = side / min(w, h)
        nw, nh = round(w * scale), round(h * scale)
        im_r = im_pil.resize((nw, nh), Image.LANCZOS)
        left = (nw - side) // 2
        top = (nh - side) // 2
        return im_r.crop((left, top, left + side, top + side))

    side = args.long_side
    written = 0
    preview_items = []  # (img_path, canny_path) pour la planche
    with manifest_path.open("w") as mf:
        # tri par score photo décroissant → les meilleures d'abord
        for rank, (p, s_photo, s_margin) in enumerate(
                sorted(kept, key=lambda t: -t[1])):
            try:
                with Image.open(p) as im:
                    im = resize_square(im.convert("RGB"), side)
            except Exception as ex:
                print(f"  !! resize {p.name}: {ex}", flush=True)
                continue
            stem = f"{rank:05d}_{p.stem}"[:80]
            img_out = OUT / "images" / f"{stem}.jpg"
            canny_out = OUT / "canny" / f"{stem}.png"
            depth_out = OUT / "depth" / f"{stem}.png"

            im.save(img_out, quality=95)

            arr = np.array(im)
            gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY)
            # seuils canny : médiane-adaptatifs (robustes selon le contraste)
            v = np.median(gray)
            lo = int(max(0, 0.66 * v))
            hi = int(min(255, 1.33 * v))
            edges = cv2.Canny(gray, lo, hi)
            cv2.imwrite(str(canny_out), edges)

            depth_rel = None
            if dpt is not None:
                with torch.no_grad():
                    inp = dpt_proc(images=im, return_tensors="pt").to(device)
                    pred = dpt(**inp).predicted_depth.cpu()  # bicubic non impl. MPS
                    pred = torch.nn.functional.interpolate(
                        pred.unsqueeze(1), size=(side, side),
                        mode="bicubic", align_corners=False).squeeze().numpy()
                dmin, dmax = pred.min(), pred.max()
                dnorm = (pred - dmin) / (dmax - dmin + 1e-8)
                cv2.imwrite(str(depth_out), (dnorm * 255).astype(np.uint8))
                depth_rel = str(depth_out.relative_to(REFS))

            mf.write(json.dumps({
                "image": str(img_out.relative_to(REFS)),
                "canny": str(canny_out.relative_to(REFS)),
                "depth": depth_rel,
                "source": str(p.relative_to(ROOT)),
                "clip_photo": round(s_photo, 4),
                "clip_photo_margin": round(s_margin, 4),
            }) + "\n")
            written += 1
            if len(preview_items) < 16 and rank % max(1, n_kept // 24) == 0:
                preview_items.append((img_out, canny_out))
            if written % 100 == 0:
                print(f"  paires écrites {written}/{n_kept}", flush=True)

    print(f"[r2p] ✓ {written} paires → {OUT}", flush=True)

    # ---- Planche de contrôle ------------------------------------------------
    if not preview_items:
        preview_items = [(OUT / "images" / f.name, OUT / "canny" / (f.stem + ".png"))
                         for f in sorted((OUT / "images").glob("*.jpg"))[:16]]
    build_preview(preview_items[:16])
    print(f"[r2p] ✓ preview → {PREVIEW}", flush=True)


def build_preview(items):
    from PIL import Image, ImageDraw
    if not items:
        return
    cell = 256
    cols = 4          # 4 paires (photo|canny) par ligne = 8 vignettes/ligne
    pad = 6
    rows = (len(items) + cols - 1) // cols
    pair_w = cell * 2 + 2
    W = cols * (pair_w + pad) + pad
    H = rows * (cell + pad) + pad
    canvas = Image.new("RGB", (W, H), (20, 20, 20))
    for idx, (img_p, canny_p) in enumerate(items):
        r, c = divmod(idx, cols)
        x = pad + c * (pair_w + pad)
        y = pad + r * (cell + pad)
        try:
            ph = Image.open(img_p).convert("RGB").resize((cell, cell))
            cn = Image.open(canny_p).convert("RGB").resize((cell, cell))
        except Exception:
            continue
        canvas.paste(ph, (x, y))
        canvas.paste(cn, (x + cell + 2, y))
    canvas.save(PREVIEW)


if __name__ == "__main__":
    sys.exit(main())
