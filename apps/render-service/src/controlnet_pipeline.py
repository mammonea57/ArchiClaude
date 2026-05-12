"""SDXL Lightning + ControlNet-depth pipeline.

Day 3 of SP2-v2b. Combines :
  - SDXL base + Lightning UNet (4-step distilled, fast)
  - ControlNet-depth (constrains the geometry to match the BM building)

Flow : depth_map (1024x1024 grayscale, white=near, black=far)
     + text_prompt (architectural style)
     + camera angle (informs the prompt template)
     → photo-realistic render of THE actual building.

Memory note : on M3 16 GB this loads ~10 GB into RAM (SDXL base + Lightning
UNet + ControlNet). Tight but works with attention slicing + VAE slicing.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from PIL import Image

from .config import CONFIG

logger = logging.getLogger(__name__)

# ControlNet-depth weights for SDXL — open-source, Apache 2.0.
CONTROLNET_DEPTH_ID = "diffusers/controlnet-depth-sdxl-1.0"

_pipe = None
_pipe_lock = threading.Lock()


def get_controlnet_pipeline():
    """Lazy-load the SDXL Lightning + ControlNet-depth pipeline (singleton).

    First call downloads weights (~2.5 GB ControlNet on top of the existing
    SDXL base + Lightning) and warms the device. Subsequent calls reuse.
    """
    global _pipe
    if _pipe is not None:
        return _pipe
    with _pipe_lock:
        if _pipe is not None:
            return _pipe
        logger.info("loading SDXL Lightning + ControlNet-depth on device=%s …", CONFIG.DEVICE)
        import torch
        from diffusers import (
            AutoencoderKL,
            ControlNetModel,
            EulerDiscreteScheduler,
            StableDiffusionXLControlNetPipeline,
        )

        dtype = torch.float16 if CONFIG.DEVICE in ("cuda", "mps") else torch.float32

        # 1) ControlNet model
        controlnet = ControlNetModel.from_pretrained(
            CONTROLNET_DEPTH_ID,
            torch_dtype=dtype,
            variant="fp16" if CONFIG.DEVICE != "cpu" else None,
            use_safetensors=True,
        )

        # 2) FP16-fix VAE — corrects NaN/black output on Apple Silicon.
        # Standard SDXL VAE in fp16 produces NaN on MPS ; this drop-in
        # replacement (Madebyollin) is finetuned to be numerically stable.
        vae = AutoencoderKL.from_pretrained(
            "madebyollin/sdxl-vae-fp16-fix",
            torch_dtype=dtype,
        )

        # 3) SDXL base + ControlNet pipeline (standard SDXL — no Lightning
        # for stability ; 25 steps + CFG=7.5 sur M3 prend ~4-5 min mais
        # produit un rendu propre).
        pipe = StableDiffusionXLControlNetPipeline.from_pretrained(
            CONFIG.BASE_MODEL_ID,
            controlnet=controlnet,
            vae=vae,
            torch_dtype=dtype,
            variant="fp16" if CONFIG.DEVICE != "cpu" else None,
            use_safetensors=True,
        )
        # Standard scheduler — no Lightning override.
        pipe.scheduler = EulerDiscreteScheduler.from_config(pipe.scheduler.config)

        pipe.to(CONFIG.DEVICE)

        # Aggressive memory savings on Apple Silicon — 16 GB is tight.
        if CONFIG.DEVICE == "mps":
            pipe.enable_attention_slicing("max")
            pipe.enable_vae_slicing()
        logger.info("controlnet pipeline ready")
        _pipe = pipe
        return _pipe


def render_with_controlnet(
    prompt: str,
    depth_map: Image.Image,
    negative_prompt: Optional[str] = None,
    seed: Optional[int] = None,
    controlnet_conditioning_scale: float = 0.6,
):
    """Run depth-conditioned SDXL Lightning inference.

    `depth_map` : PIL grayscale image (white=near, black=far). Will be resized
    automatically if not 1024x1024.
    `controlnet_conditioning_scale` : 0..1, how strongly to follow the depth
    (0.6-0.8 is a sweet spot for archi — too high = stiff, too low = drifts).
    """
    import torch

    pipe = get_controlnet_pipeline()
    if depth_map.size != (CONFIG.WIDTH, CONFIG.HEIGHT):
        depth_map = depth_map.resize((CONFIG.WIDTH, CONFIG.HEIGHT), Image.LANCZOS)
    if depth_map.mode != "RGB":
        # ControlNet expects 3-channel input ; replicate the L channel.
        depth_map = depth_map.convert("RGB")
    generator = (
        torch.Generator(device=CONFIG.DEVICE).manual_seed(seed)
        if seed is not None
        else None
    )
    # Standard SDXL + ControlNet recipe : 25 steps + CFG=7.5 — stable output
    # avec le VAE fp16-fix. Sur M3 ~4-5 min ; en cloud GPU (Phase B) ~15 s.
    image = pipe(
        prompt=prompt,
        negative_prompt=negative_prompt or "",
        image=depth_map,
        num_inference_steps=25,
        guidance_scale=7.5,
        controlnet_conditioning_scale=controlnet_conditioning_scale,
        width=CONFIG.WIDTH,
        height=CONFIG.HEIGHT,
        generator=generator,
    ).images[0]
    return image
