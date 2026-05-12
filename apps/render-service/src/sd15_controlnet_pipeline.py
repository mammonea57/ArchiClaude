"""SD 1.5 + ControlNet-depth pipeline with photoreal fine-tune + hires-fix.

Quality stack (3 levers vs the bare SD 1.5 baseline) :
  1. Base model = SG161222/Realistic_Vision_V6.0_B1_noVAE — SD 1.5 fine-tune
     specialised for magazine-quality photoreal output ; drop-in compatible
     with our ControlNet + LoRA.
  2. VAE = stabilityai/sd-vae-ft-mse — improved decoder colour stability.
  3. Hires-fix : ControlNet at 512 (locks the L geometry) → img2img refine
     pass at 1024 with denoise=0.35 (synthesises sharp facade details).

CPU still preferred over MPS due to the classifier-free-guidance NaN bug
(tests/test_sd15_minimal.py confirmed). When cloud GPU is available, switch
to the SDXL Modal endpoint for ~3× quality at ~10× speed.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Optional

from PIL import Image

from .config import CONFIG

logger = logging.getLogger(__name__)

SD15_BASE = os.environ.get("SD15_BASE", "SG161222/Realistic_Vision_V6.0_B1_noVAE")
SD15_VAE = "stabilityai/sd-vae-ft-mse"
SD15_CONTROLNET_DEPTH = "lllyasviel/control_v11f1p_sd15_depth"

# Hires-fix : refine the 512 ControlNet output at this target resolution.
HIRES_W = 1024
HIRES_H = 1024
# Denoise strength of the img2img refine pass — too low = blurry, too high =
# loses the geometry locked by ControlNet. 0.35 is the safe sweet spot.
HIRES_DENOISE = float(os.environ.get("HIRES_DENOISE", "0.35"))
HIRES_ENABLED = os.environ.get("HIRES_FIX", "1") == "1"

# Path to the trained "archfr_idf_modern" LoRA. When present and ARCHFR_LORA=1,
# we fuse it into the UNet at pipeline load time. The file is the safetensors
# output of training/train_lora_modal.py.
_HERE = Path(__file__).resolve().parent
ARCHFR_LORA_PATH = _HERE.parent / "training" / "lora_weights" / "archfr_idf_modern.safetensors"
ARCHFR_LORA_ENABLED = os.environ.get("ARCHFR_LORA", "1") == "1"
ARCHFR_LORA_SCALE = float(os.environ.get("ARCHFR_LORA_SCALE", "0.3"))

# SD 1.5 native resolution. Output is 512x512 ; for 1024x1024 the frontend
# can upscale via Pillow LANCZOS or a fast SR pass.
SD15_W = 512
SD15_H = 512

_pipe = None
_refine_pipe = None  # img2img refine pass — shares components with _pipe
_pipe_lock = threading.Lock()


# MPS has a NaN bug with CFG > 0 → fall back to CPU on Apple Silicon.
# Override only when device is mps ; on cuda/cpu use the configured device.
SD15_DEVICE = "cpu" if CONFIG.DEVICE == "mps" else CONFIG.DEVICE


def get_sd15_pipeline():
    """Lazy-load Realistic Vision V6 + ControlNet-depth + img2img refine pipelines.

    Both pipelines share the same UNet / VAE / text-encoder weights via
    diffusers' explicit-component constructor — so the LoRA loaded on the
    ControlNet pipe is automatically active in the refine pass too.
    """
    global _pipe, _refine_pipe
    if _pipe is not None:
        return _pipe
    with _pipe_lock:
        if _pipe is not None:
            return _pipe
        logger.info("loading %s + VAE + ControlNet-depth on device=%s …", SD15_BASE, SD15_DEVICE)
        import torch
        from diffusers import (
            AutoencoderKL,
            ControlNetModel,
            DPMSolverMultistepScheduler,
            StableDiffusionControlNetPipeline,
            StableDiffusionImg2ImgPipeline,
        )

        dtype = torch.float16 if SD15_DEVICE == "cuda" else torch.float32

        # Improved VAE — sharper colour reproduction than the V6 default.
        vae = AutoencoderKL.from_pretrained(SD15_VAE, torch_dtype=dtype)

        controlnet = ControlNetModel.from_pretrained(
            SD15_CONTROLNET_DEPTH,
            torch_dtype=dtype,
            use_safetensors=True,
        )
        pipe = StableDiffusionControlNetPipeline.from_pretrained(
            SD15_BASE,
            controlnet=controlnet,
            vae=vae,
            torch_dtype=dtype,
            safety_checker=None,
            requires_safety_checker=False,
            # Note: Realistic Vision V6 ships .bin weights only — leave the
            # safetensors flag off so diffusers picks up whichever format is
            # available per file.
        )
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(
            pipe.scheduler.config, use_karras_sigmas=True
        )
        pipe.to(SD15_DEVICE)

        # Build the img2img refine pipeline reusing all loaded components — no
        # extra RAM/VRAM cost, and any LoRA loaded on `pipe` is shared via the
        # underlying UNet reference.
        refine = StableDiffusionImg2ImgPipeline(
            vae=pipe.vae,
            text_encoder=pipe.text_encoder,
            tokenizer=pipe.tokenizer,
            unet=pipe.unet,
            scheduler=pipe.scheduler,
            safety_checker=None,
            feature_extractor=pipe.feature_extractor,
            requires_safety_checker=False,
        )
        refine.to(SD15_DEVICE)

        # LoRA loading (lives on the shared UNet)
        global _lora_loaded
        _lora_loaded = False
        if ARCHFR_LORA_ENABLED and ARCHFR_LORA_PATH.exists():
            try:
                logger.info("loading archfr_idf_modern LoRA from %s …", ARCHFR_LORA_PATH.name)
                pipe.load_lora_weights(str(ARCHFR_LORA_PATH.parent),
                                       weight_name=ARCHFR_LORA_PATH.name)
                _lora_loaded = True
                logger.info("LoRA loaded — scale tunable per request (default %.2f)", ARCHFR_LORA_SCALE)
            except Exception as e:
                logger.warning("LoRA load failed (%s) — proceeding without", e)
        elif ARCHFR_LORA_ENABLED:
            logger.info("no LoRA weights at %s — proceeding without", ARCHFR_LORA_PATH)

        logger.info("pipeline ready (hires_fix=%s, denoise=%.2f)", HIRES_ENABLED, HIRES_DENOISE)
        _pipe = pipe
        _refine_pipe = refine
        return _pipe


# Tracks whether the LoRA was successfully loaded — used to decide whether
# to pass cross_attention_kwargs at inference time.
_lora_loaded = False


def render_with_sd15_controlnet(
    prompt: str,
    depth_map: Image.Image,
    negative_prompt: Optional[str] = None,
    seed: Optional[int] = None,
    controlnet_conditioning_scale: float = 0.8,
    lora_scale: Optional[float] = None,
):
    """Run SD 1.5 + ControlNet-depth at native 512x512.

    Args:
        prompt: positive prompt (under 77 tokens — SD 1.5 limit).
        depth_map: PIL grayscale image (auto-resized to 512x512).
        seed: optional reproducibility seed.
        controlnet_conditioning_scale: 0..2, how strictly to follow geometry.
        lora_scale: 0..1 strength of the archfr_idf_modern LoRA. Defaults to
            ARCHFR_LORA_SCALE env var (0.3). Pass None to use the default.
    """
    import torch

    pipe = get_sd15_pipeline()
    if depth_map.size != (SD15_W, SD15_H):
        depth_map = depth_map.resize((SD15_W, SD15_H), Image.LANCZOS)
    if depth_map.mode != "RGB":
        depth_map = depth_map.convert("RGB")
    generator = (
        torch.Generator(device=SD15_DEVICE).manual_seed(seed)
        if seed is not None
        else None
    )

    # Pass 1 — ControlNet at 512×512 locks the L geometry. We use 25 steps on
    # CPU (still photoreal, gives the refine pass a clean canvas).
    cn_steps = 25 if SD15_DEVICE == "cpu" else 35
    effective_scale = lora_scale if lora_scale is not None else ARCHFR_LORA_SCALE
    cross_kwargs = {"scale": effective_scale} if _lora_loaded else None
    if _lora_loaded:
        logger.info("pass1 (CN 512): cn=%.2f lora=%.2f steps=%d",
                    controlnet_conditioning_scale, effective_scale, cn_steps)
    image_512 = pipe(
        prompt=prompt,
        negative_prompt=negative_prompt or "",
        image=depth_map,
        num_inference_steps=cn_steps,
        guidance_scale=7.5,
        controlnet_conditioning_scale=controlnet_conditioning_scale,
        width=SD15_W,
        height=SD15_H,
        generator=generator,
        cross_attention_kwargs=cross_kwargs,
    ).images[0]

    # Pass 2 — hires-fix img2img refine at 1024 (no ControlNet, the geometry
    # is already baked in). LANCZOS upscale provides the initial latent; the
    # diffusion pass then synthesises sharp facade textures, window grids,
    # leaves, etc. that pure interpolation cannot.
    if not HIRES_ENABLED:
        if (image_512.width, image_512.height) != (CONFIG.WIDTH, CONFIG.HEIGHT):
            return image_512.resize((CONFIG.WIDTH, CONFIG.HEIGHT), Image.LANCZOS)
        return image_512

    upscaled = image_512.resize((HIRES_W, HIRES_H), Image.LANCZOS)
    refine_steps = 30 if SD15_DEVICE == "cpu" else 40
    logger.info("pass2 (hires-fix 1024): denoise=%.2f steps=%d", HIRES_DENOISE, refine_steps)
    image_1024 = _refine_pipe(
        prompt=prompt,
        negative_prompt=negative_prompt or "",
        image=upscaled,
        num_inference_steps=refine_steps,
        strength=HIRES_DENOISE,
        guidance_scale=7.5,
        generator=generator,
        cross_attention_kwargs=cross_kwargs,
    ).images[0]
    if (image_1024.width, image_1024.height) != (CONFIG.WIDTH, CONFIG.HEIGHT):
        image_1024 = image_1024.resize((CONFIG.WIDTH, CONFIG.HEIGHT), Image.LANCZOS)
    return image_1024
