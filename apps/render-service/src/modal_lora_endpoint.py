"""LoRA fine-tuning endpoint for ArchiClaude archviz on Modal A100-80GB.

Trains a "Brick-tier signature" archviz LoRA on FLUX.1-dev (or SDXL as
fallback) using the style dataset built by
`photogrammetry/style_dataset.py`.

Why FLUX-dev base :
  - 12B params + DiT architecture → better fine-grain texture transfer
    than SDXL UNet
  - Matches the existing inference endpoint (`modal_flux_endpoint.py`)
    so a trained adapter slots in without re-architecting
  - License caveat : FLUX.1-dev is "non-commercial" until BFL releases
    a commercial variant. For internal POC + non-commercial mockup
    rendering this is fine. For commercial deployment, switch to
    SDXL (FLUX_FALLBACK env var) which is straight Apache 2.0.

Why A100-80GB :
  - FLUX-dev in bf16 takes ~24 GB ; with PEFT LoRA adapters,
    activations, optimizer states (8-bit AdamW) + a batch of 1 at
    1024², we sit around 60-70 GB. 40GB A100 OOMs. 80GB has headroom
    for gradient accumulation and rank-32 LoRAs later.

Pipeline :
  1. Mount `archfr-style-dataset` (read-only) — the curated dataset
     from `style_dataset.py`
  2. Mount `archfr-lora-cache` (read-write) — HF model cache +
     output LoRA checkpoints
  3. Load FLUX-dev (or SDXL) in bf16
  4. Attach PEFT LoraConfig to transformer (FLUX) or UNet (SDXL)
  5. Train with HF Accelerate, AdamW8bit, grad accumulation 4
  6. Save adapter every 100 steps + final to
     /cache/lora/<output_name>/adapter.safetensors

Usage :
    cd apps/render-service
    .venv/bin/modal run src/modal_lora_endpoint.py::train_cli \
        --dataset-path /archfr-style-dataset/combined_v1 \
        --output-name archfr_brick_v1 \
        --epochs 10 --lr 1e-4 --rank 16

    .venv/bin/modal run src/modal_lora_endpoint.py::infer_cli \
        --prompt "modern apartment building in Nogent-sur-Marne ..." \
        --lora-name archfr_brick_v1
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Optional

import modal

app = modal.App("archfr-lora-train")

# Base model — FLUX-dev by default ; switch with FLUX_FALLBACK=1 env var
# to use SDXL (Apache 2.0, commercial-OK) if FLUX license blocks us.
FLUX_BASE = "black-forest-labs/FLUX.1-dev"
SDXL_BASE = "stabilityai/stable-diffusion-xl-base-1.0"


image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        # Known-good FLUX LoRA training combo (Q1 2025) :
        #   torch 2.4 → triton 3.0 (still has triton.ops)
        #   transformers 4.44 (no finegrained_fp8 / float8_e8m0fnu requirement)
        "torch==2.4.1",
        "torchvision==0.19.1",
        "triton==3.0.0",
        "diffusers==0.30.3",
        "transformers==4.44.2",
        "tokenizers>=0.19.1,<0.20",          # compatible with transformers 4.44
        "peft==0.13.0",
        "accelerate==1.0.1",
        "bitsandbytes==0.43.3",
        "safetensors>=0.4.5",
        "huggingface_hub>=0.25,<0.27",
        "pillow>=10.4",
        "datasets>=3.0",
        "sentencepiece>=0.2",
        "protobuf>=3.20",
        "numpy>=1.26,<2.0",
    )
)

# Persistent volumes
# - hf_cache : reused with the inference endpoint to avoid re-downloading
#   the 24GB FLUX checkpoint
# - dataset_vol : mounted read-only at train time, holds combined_v1 etc
# - lora_cache : where trained adapters land + intermediate checkpoints
hf_cache = modal.Volume.from_name("archfr-hf-cache", create_if_missing=True)
dataset_vol = modal.Volume.from_name("archfr-style-dataset", create_if_missing=True)
lora_cache = modal.Volume.from_name("archfr-lora-cache", create_if_missing=True)


# -- Loss helpers (inlined from training/lora_archviz/train_loop.py for Modal) ------


def _pack_latents_inline(latents):
    """FLUX latent packing : (B, C, H, W) -> (B, (H/2)*(W/2), C*4).

    Mirrors `FluxPipeline._pack_latents`. The transformer is a DiT that
    operates on 2x2 patches of the latent grid flattened into tokens,
    each token carrying C*4 channels.
    """
    b, c, h, w = latents.shape
    latents = latents.view(b, c, h // 2, 2, w // 2, 2)
    latents = latents.permute(0, 2, 4, 1, 3, 5)
    return latents.reshape(b, (h // 2) * (w // 2), c * 4)


def _make_img_ids_inline(height, width, batch_size, device, dtype):
    """FLUX RoPE position-IDs for the *packed* image latent grid.

    Mirrors `FluxPipeline._prepare_latent_image_ids` shape conventions
    used by `transformer_flux.py` in diffusers 0.30.3 : the transformer
    `forward` calls `torch.cat((txt_ids, img_ids), dim=1)` and
    `text_ids` from `encode_prompt` is 3D `(B, seq, 3)`, so img_ids
    must ALSO be 3D `(B, seq, 3)` with the same leading batch dim.
    Height/width are the post-pack grid dims (latent H/2, latent W/2).
    """
    import torch
    ids = torch.zeros(height, width, 3, device=device, dtype=dtype)
    ids[..., 1] = ids[..., 1] + torch.arange(height, device=device)[:, None]
    ids[..., 2] = ids[..., 2] + torch.arange(width, device=device)[None, :]
    flat = ids.reshape(height * width, 3)
    return flat.unsqueeze(0).expand(batch_size, -1, -1).contiguous()


def _compute_loss_flux_inline(pipe, batch):
    """FLUX rectified-flow (flow-matching) training loss.

    Reference : `examples/dreambooth/train_dreambooth_lora_flux.py` in
    diffusers + the inference impl in `pipeline_flux.py`.

    Critical pieces vs the previous broken impl :
      - Pack latents (B, 16, H, W) -> (B, (H/2)*(W/2), 64) before the
        transformer call ; the original passed unpacked latents and
        the patch-embedding projection then failed with
        `mat1 (Bx4096, 128) @ mat2 (64, 3072)` because the in_proj
        expects 64-channel tokens, not 128.
      - img_ids has shape (seq_len, 3) using the post-pack grid
        (H/2, W/2), not (H, W).
      - FLUX-dev needs `guidance` (set to 1.0 during training, vanilla
        convention from the diffusers training example). FLUX-schnell
        has `guidance_embeds=False` so we pass None.
      - timestep is the sigma in [0,1] — no x1000 multiplier here,
        the transformer's `time_text_embed` already scales internally
        (see `transformer_flux.py` line 467 : `guidance.to(...) * 1000`
        and timestep scaling at the same site).
    """
    import torch
    device = pipe.transformer.device
    dtype = pipe.transformer.dtype
    pixel_values = batch["pixel_values"].to(device, dtype=dtype)
    captions = batch["caption"]

    # 1. VAE encode -> (B, 16, H/8, W/8). At 1024² : (B, 16, 128, 128).
    with torch.no_grad():
        latents = pipe.vae.encode(pixel_values).latent_dist.sample()
        latents = (latents - pipe.vae.config.shift_factor) * pipe.vae.config.scaling_factor

    bsz, c_lat, h_lat, w_lat = latents.shape

    # 2. Pack to (B, (H/2)*(W/2), C*4). At 1024² : (B, 4096, 64).
    latents_packed = _pack_latents_inline(latents)

    # 3. Flow-matching noise + interpolation IN PACKED SPACE.
    #    `t` is the sigma in [0, 1]. Convention from
    #    train_dreambooth_lora_flux.py : noisy = sigma * noise + (1 - sigma) * x
    #    and the velocity target is `noise - x`.
    t = torch.rand(bsz, device=device, dtype=dtype)
    noise = torch.randn_like(latents_packed)
    sigmas = t.view(-1, 1, 1)
    noisy = sigmas * noise + (1.0 - sigmas) * latents_packed
    target = noise - latents_packed

    # 4. Encode prompts. `text_ids` shape is (T5_seq_len, 3) — 2D.
    with torch.no_grad():
        prompt_embeds, pooled_embeds, text_ids = pipe.encode_prompt(
            prompt=captions, prompt_2=captions,
        )

    # 5. Build img_ids on the *packed* grid (h_lat // 2, w_lat // 2).
    #    text_ids from encode_prompt is 3D (B, T5_seq, 3) so img_ids
    #    must match with the same batch dim.
    img_ids = _make_img_ids_inline(
        h_lat // 2, w_lat // 2, bsz,
        device=device, dtype=prompt_embeds.dtype,
    )

    # 6. Guidance — FLUX-dev requires it (guidance_embeds=True). Standard
    #    training value is 1.0 (no CFG conditioning during training).
    if getattr(pipe.transformer.config, "guidance_embeds", False):
        guidance = torch.full([bsz], 1.0, device=device, dtype=torch.float32)
    else:
        guidance = None

    # 7. Forward. timestep is sigma in [0, 1] — the inference loop in
    #    pipeline_flux.py passes `timestep / 1000`, so during training
    #    we mirror that scale (already in [0, 1]).
    pred = pipe.transformer(
        hidden_states=noisy,
        timestep=t,
        guidance=guidance,
        pooled_projections=pooled_embeds,
        encoder_hidden_states=prompt_embeds,
        txt_ids=text_ids,
        img_ids=img_ids,
        return_dict=False,
    )[0]

    return torch.nn.functional.mse_loss(pred.float(), target.float())


def _compute_loss_sdxl_inline(pipe, batch, resolution: int = 1024):
    """SDXL DDPM noise-prediction loss.

    `resolution` flows into the add_time_ids conditioning so that we don't
    confuse the model when training at a non-1024 size (would be a quality bug).
    """
    import torch
    device = pipe.unet.device
    dtype = pipe.unet.dtype
    pixel_values = batch["pixel_values"].to(device, dtype=dtype)
    captions = batch["caption"]
    with torch.no_grad():
        latents = pipe.vae.encode(pixel_values).latent_dist.sample()
        latents = latents * pipe.vae.config.scaling_factor
    noise = torch.randn_like(latents)
    bsz = latents.shape[0]
    timesteps = torch.randint(
        0, pipe.scheduler.config.num_train_timesteps, (bsz,), device=device,
    ).long()
    noisy = pipe.scheduler.add_noise(latents, noise, timesteps)
    with torch.no_grad():
        prompt_embeds, neg, pooled, neg_pooled = pipe.encode_prompt(
            prompt=captions, do_classifier_free_guidance=False,
        )
    # FIX: build time_ids from the actual training resolution
    # (orig_h, orig_w, crop_top, crop_left, target_h, target_w)
    add_time_ids = torch.tensor(
        [[resolution, resolution, 0, 0, resolution, resolution]] * bsz,
        device=device, dtype=dtype,
    )
    added_cond = {"text_embeds": pooled, "time_ids": add_time_ids}
    pred = pipe.unet(
        noisy, timesteps,
        encoder_hidden_states=prompt_embeds,
        added_cond_kwargs=added_cond,
    ).sample
    return torch.nn.functional.mse_loss(pred.float(), noise.float())


# -- Training -----------------------------------------------------------------


@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=6 * 3600,                  # 6 hours wall-clock cap
    volumes={
        "/root/.cache/huggingface": hf_cache,
        "/archfr-style-dataset": dataset_vol,
        "/cache": lora_cache,
    },
    secrets=[modal.Secret.from_name("huggingface")],   # HF_TOKEN for FLUX
)
def train_lora(
    dataset_path: str,
    output_name: str,
    epochs: int = 8,
    lr: float = 5e-5,
    rank: int = 32,
    lora_alpha: int = 16,
    batch_size: int = 1,
    grad_accum: int = 4,
    resolution: int = 1024,
    seed: int = 42,
    save_every: int = 0,           # 0 = save once per epoch (anti-divergence)
    use_sdxl: bool = False,
    max_grad_norm: float = 1.0,    # gradient clipping (anti-divergence)
    lr_scheduler: str = "cosine",
    warmup_ratio: float = 0.1,
) -> str:
    """Fine-tune a LoRA adapter on FLUX-dev (or SDXL) for archviz style.

    Returns the absolute path inside the `archfr-lora-cache` volume
    where the final adapter is saved.

    Arguments :
      dataset_path : path inside the dataset volume, e.g.
          '/archfr-style-dataset/combined_v1'. Must contain a
          `captions.jsonl` and an `images/` subfolder (the format
          emitted by `style_dataset.build_combined_dataset`).
      output_name : final adapter folder name under /cache/lora/
      use_sdxl : if True, train against SDXL instead of FLUX-dev
          (slower but commercial-friendly license)

    Implementation note : this function intentionally keeps the actual
    training loop in a helper module that imports diffusers'
    `train_dreambooth_lora_flux.py` / `train_text_to_image_lora_sdxl.py`
    examples — they're the upstream reference impl. We DO NOT
    re-implement the forward + loss from scratch here ; we wrap the
    HF Diffusers training script with our dataset adapter.
    """
    import json
    import logging
    import sys
    import time

    logging.basicConfig(level=logging.INFO)
    log = logging.getLogger("train_lora")
    log.info("starting LoRA training : dataset=%s output=%s rank=%d epochs=%d",
             dataset_path, output_name, rank, epochs)

    import torch
    from huggingface_hub import login

    token = os.environ.get("HF_TOKEN")
    if token:
        login(token=token, add_to_git_credential=False)

    # Validate dataset
    ds_root = Path(dataset_path)
    captions_jsonl = ds_root / "captions.jsonl"
    images_dir = ds_root / "images"
    if not captions_jsonl.exists():
        raise FileNotFoundError(
            f"Expected captions.jsonl at {captions_jsonl}. "
            "Run `style_dataset.py --full` first to build it."
        )
    n_images = sum(1 for _ in captions_jsonl.open())
    log.info("dataset : %d images at %s", n_images, ds_root)

    # Output folder
    out_root = Path("/cache/lora") / output_name
    out_root.mkdir(parents=True, exist_ok=True)

    base_model = SDXL_BASE if use_sdxl else FLUX_BASE
    log.info("base model : %s", base_model)

    # -- Build dataset ---------------------------------------------------
    from datasets import load_dataset
    from PIL import Image
    from torch.utils.data import DataLoader, Dataset
    from torchvision import transforms

    captions_data = [json.loads(line) for line in captions_jsonl.open()]

    class StyleDataset(Dataset):
        def __init__(self, rows, resolution):
            self.rows = rows
            self.transform = transforms.Compose([
                transforms.Resize(resolution, interpolation=transforms.InterpolationMode.BILINEAR),
                transforms.CenterCrop(resolution),
                transforms.ToTensor(),
                transforms.Normalize([0.5], [0.5]),
            ])

        def __len__(self): return len(self.rows)

        def __getitem__(self, idx):
            row = self.rows[idx]
            img_path = ds_root / row["file_name"]
            img = Image.open(img_path).convert("RGB")
            return {
                "pixel_values": self.transform(img),
                "caption": row["text"],
            }

    train_ds = StyleDataset(captions_data, resolution)
    log.info("train dataset built : %d samples, resolution=%d", len(train_ds), resolution)

    # -- Load base + attach LoRA -----------------------------------------
    if use_sdxl:
        from diffusers import StableDiffusionXLPipeline
        pipe = StableDiffusionXLPipeline.from_pretrained(
            base_model, torch_dtype=torch.bfloat16,
        )
        target_modules = ["to_q", "to_k", "to_v", "to_out.0"]
        unet_or_transformer = pipe.unet
    else:
        from diffusers import FluxPipeline
        pipe = FluxPipeline.from_pretrained(
            base_model, torch_dtype=torch.bfloat16,
        )
        # FLUX DiT block attention modules — names verified against
        # diffusers 0.32 FluxTransformer2DModel source.
        target_modules = [
            "to_q", "to_k", "to_v", "to_out.0",
            "add_q_proj", "add_k_proj", "add_v_proj", "to_add_out",
        ]
        unet_or_transformer = pipe.transformer

    from peft import LoraConfig, get_peft_model

    lora_cfg = LoraConfig(
        r=rank,
        lora_alpha=lora_alpha,
        target_modules=target_modules,
        lora_dropout=0.0,
        bias="none",
    )
    unet_or_transformer = get_peft_model(unet_or_transformer, lora_cfg)
    unet_or_transformer.print_trainable_parameters()
    if use_sdxl:
        pipe.unet = unet_or_transformer
    else:
        pipe.transformer = unet_or_transformer

    pipe.to("cuda")
    pipe.vae.requires_grad_(False)
    pipe.text_encoder.requires_grad_(False)
    if hasattr(pipe, "text_encoder_2") and pipe.text_encoder_2 is not None:
        pipe.text_encoder_2.requires_grad_(False)

    # -- Optimizer + scheduler ------------------------------------------
    import bitsandbytes as bnb

    trainable_params = [p for p in unet_or_transformer.parameters() if p.requires_grad]
    optimizer = bnb.optim.AdamW8bit(trainable_params, lr=lr, weight_decay=1e-2)

    from accelerate import Accelerator
    accelerator = Accelerator(
        mixed_precision="bf16",
        gradient_accumulation_steps=grad_accum,
    )
    train_loader = DataLoader(
        train_ds, batch_size=batch_size, shuffle=True,
        num_workers=2, pin_memory=True,
    )

    # Cosine LR scheduler with warmup — anti-divergence, smoother convergence
    total_optimizer_steps = (len(train_loader) // grad_accum) * epochs
    warmup_steps = int(total_optimizer_steps * warmup_ratio)
    log.info("scheduler : %s | total_steps=%d | warmup=%d",
             lr_scheduler, total_optimizer_steps, warmup_steps)
    from diffusers.optimization import get_scheduler
    scheduler = get_scheduler(
        name=lr_scheduler,
        optimizer=optimizer,
        num_warmup_steps=warmup_steps,
        num_training_steps=total_optimizer_steps,
    )

    unet_or_transformer, optimizer, train_loader, scheduler = accelerator.prepare(
        unet_or_transformer, optimizer, train_loader, scheduler,
    )

    # -- Training loop ---------------------------------------------------
    total_steps = (len(train_loader) // grad_accum) * epochs
    log.info("total steps : %d (%d epochs)", total_steps, epochs)

    global_step = 0
    t_start = time.time()
    for epoch in range(epochs):
        for batch in train_loader:
            with accelerator.accumulate(unet_or_transformer):
                # The actual forward+loss differs FLUX vs SDXL ; for
                # scaffolding we leave the canonical impl in a helper
                # that mirrors diffusers' reference training scripts.
                # See `examples/dreambooth/train_dreambooth_lora_flux.py`
                # and `examples/text_to_image/train_text_to_image_lora_sdxl.py`
                # in the diffusers repo — both compute :
                #   1. encode pixel_values via VAE → latents
                #   2. add noise per scheduler timestep
                #   3. encode captions via text encoder(s)
                #   4. predict noise with the model + LoRA
                #   5. MSE loss against added noise
                # We re-import that loop here on first call to keep the
                # diff small for this scaffolding PR.
                if use_sdxl:
                    loss = _compute_loss_sdxl_inline(pipe, batch, resolution=resolution)
                else:
                    loss = _compute_loss_flux_inline(pipe, batch)
                accelerator.backward(loss)
                # Gradient clipping — critical anti-divergence
                if accelerator.sync_gradients and max_grad_norm > 0:
                    accelerator.clip_grad_norm_(
                        unet_or_transformer.parameters(), max_grad_norm,
                    )
                optimizer.step()
                scheduler.step()
                optimizer.zero_grad()

            if accelerator.sync_gradients:
                global_step += 1
                if global_step % 10 == 0:
                    current_lr = scheduler.get_last_lr()[0]
                    log.info("step %d / %d : loss=%.4f lr=%.2e",
                             global_step, total_steps, float(loss), current_lr)
                # Step-based checkpoint (only if user explicitly enables save_every>0)
                if save_every > 0 and global_step % save_every == 0:
                    unet_or_transformer.save_pretrained(out_root / f"step_{global_step}")
                    log.info("checkpoint saved at step %d", global_step)

        # End-of-epoch checkpoint — easier to identify best LoRA window
        epoch_ckpt = out_root / f"epoch_{epoch + 1}"
        unet_or_transformer.save_pretrained(epoch_ckpt)
        log.info("epoch %d/%d done : checkpoint → %s",
                 epoch + 1, epochs, epoch_ckpt)

    # Final save
    final_path = out_root / "adapter.safetensors"
    unet_or_transformer.save_pretrained(out_root)
    elapsed = time.time() - t_start
    log.info("training done in %.1f min — final adapter at %s", elapsed / 60, final_path)

    lora_cache.commit()
    return str(final_path)


# -- Inference ----------------------------------------------------------------


@app.function(
    image=image,
    gpu="A100-80GB",
    timeout=600,
    volumes={
        "/root/.cache/huggingface": hf_cache,
        "/cache": lora_cache,
    },
    secrets=[modal.Secret.from_name("huggingface")],
)
def inference(
    prompt: str,
    lora_name: str,
    n_samples: int = 4,
    seed: Optional[int] = None,
    guidance_scale: float = 5.0,
    steps: int = 30,
    width: int = 1024,
    height: int = 1024,
    use_sdxl: bool = False,
) -> list[bytes]:
    """Sample n_samples images from a fine-tuned LoRA.

    Loads the base model + the adapter at
    /cache/lora/<lora_name>/adapter.safetensors, runs vanilla text2img
    inference, returns the PNG bytes of each sample.
    """
    import torch
    from huggingface_hub import login
    from PIL import Image

    token = os.environ.get("HF_TOKEN")
    if token:
        login(token=token, add_to_git_credential=False)

    base_model = SDXL_BASE if use_sdxl else FLUX_BASE
    lora_dir = Path("/cache/lora") / lora_name
    if not lora_dir.exists():
        raise FileNotFoundError(f"No LoRA adapter at {lora_dir}")

    if use_sdxl:
        from diffusers import StableDiffusionXLPipeline
        pipe = StableDiffusionXLPipeline.from_pretrained(
            base_model, torch_dtype=torch.bfloat16,
        )
    else:
        from diffusers import FluxPipeline
        pipe = FluxPipeline.from_pretrained(
            base_model, torch_dtype=torch.bfloat16,
        )
    pipe.to("cuda")

    # Load adapter — our training saves PEFT format (adapter_config.json +
    # adapter_model.safetensors with "base_model.model." prefix), which
    # diffusers' load_lora_weights cannot parse directly. We attach via PEFT.
    from peft import PeftModel
    target = pipe.unet if use_sdxl else pipe.transformer
    target = PeftModel.from_pretrained(target, str(lora_dir))
    if use_sdxl:
        pipe.unet = target
    else:
        pipe.transformer = target

    results: list[bytes] = []
    for i in range(n_samples):
        gen = torch.Generator(device="cuda").manual_seed((seed or 0) + i)
        out = pipe(
            prompt=prompt,
            num_inference_steps=steps,
            guidance_scale=guidance_scale,
            width=width,
            height=height,
            generator=gen,
        ).images[0]
        buf = io.BytesIO()
        out.save(buf, format="PNG", optimize=False)
        results.append(buf.getvalue())
    return results


# -- Local entrypoints --------------------------------------------------------


@app.local_entrypoint()
def train_cli(
    dataset_path: str = "/archfr-style-dataset/combined_v1",
    output_name: str = "archfr_brick_v1",
    epochs: int = 8,
    lr: float = 5e-5,
    rank: int = 32,
    lora_alpha: int = 16,
    max_grad_norm: float = 1.0,
    use_sdxl: bool = False,
):
    """Launch training from local machine.

    Example :
        .venv/bin/modal run src/modal_lora_endpoint.py::train_cli \\
            --dataset-path /archfr-style-dataset/lora_dataset_full \\
            --output-name archfr_brick_v2 --use-sdxl
    """
    print(f"→ Submitting LoRA training job to Modal A100-80GB …")
    print(f"  dataset       : {dataset_path}")
    print(f"  output        : /cache/lora/{output_name}")
    print(f"  base model    : {'SDXL' if use_sdxl else 'FLUX-dev'}")
    print(f"  rank          : {rank}  lora_alpha : {lora_alpha}")
    print(f"  epochs        : {epochs}  lr : {lr}  grad_clip : {max_grad_norm}")
    final_path = train_lora.remote(
        dataset_path=dataset_path,
        output_name=output_name,
        epochs=epochs,
        lr=lr,
        rank=rank,
        lora_alpha=lora_alpha,
        max_grad_norm=max_grad_norm,
        use_sdxl=use_sdxl,
    )
    print(f"✓ Training done. Final adapter : {final_path}")


@app.local_entrypoint()
def infer_cli(
    prompt: str,
    lora_name: str = "archfr_brick_v1",
    n_samples: int = 4,
    seed: int = 42,
    use_sdxl: bool = False,
    out_dir: str = "refs/renders/lora_eval",
):
    """Sample images from a trained LoRA and save them locally."""
    print(f"→ Running inference on Modal with LoRA={lora_name} …")
    pngs = inference.remote(
        prompt=prompt,
        lora_name=lora_name,
        n_samples=n_samples,
        seed=seed,
        use_sdxl=use_sdxl,
    )
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    import time
    ts = time.strftime("%Y%m%d_%H%M%S")
    for i, png in enumerate(pngs):
        safe_name = lora_name.replace("/", "__")
        path = out / f"{ts}_{safe_name}_s{seed + i}.png"
        path.write_bytes(png)
        print(f"  → {path}")
    print(f"✓ Saved {len(pngs)} samples.")
