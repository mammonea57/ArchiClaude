"""SDXL Lightning pipeline — lazy-loaded singleton.

Day 1: text-to-image only (validates the stack).
Day 3+: ControlNet depth/canny will plug in here.
"""
from __future__ import annotations

import logging
import threading
from typing import Optional

from .config import CONFIG

logger = logging.getLogger(__name__)

_pipe = None
_pipe_lock = threading.Lock()


def get_pipeline():
    """Return the lazy-loaded SDXL Lightning pipeline (singleton, thread-safe).

    First call downloads weights (~7 GB) and warms the device — can take
    several minutes. Subsequent calls return the cached instance.
    """
    global _pipe
    if _pipe is not None:
        return _pipe
    with _pipe_lock:
        if _pipe is not None:  # double-checked locking
            return _pipe
        logger.info("loading SDXL Lightning pipeline on device=%s …", CONFIG.DEVICE)
        import torch
        from diffusers import StableDiffusionXLPipeline, EulerDiscreteScheduler
        from huggingface_hub import hf_hub_download
        from safetensors.torch import load_file

        # SDXL Lightning is a UNet only — must be loaded on top of SDXL base.
        # We use the 4-step distilled UNet for fastest inference on M3.
        unet_filename = "sdxl_lightning_4step_unet.safetensors"
        dtype = torch.float16 if CONFIG.DEVICE in ("cuda", "mps") else torch.float32
        pipe = StableDiffusionXLPipeline.from_pretrained(
            CONFIG.BASE_MODEL_ID,
            torch_dtype=dtype,
            variant="fp16" if CONFIG.DEVICE != "cpu" else None,
            use_safetensors=True,
        )
        # Replace the UNet with the Lightning 4-step distilled version.
        unet_path = hf_hub_download(CONFIG.MODEL_ID, unet_filename)
        pipe.unet.load_state_dict(load_file(unet_path, device=CONFIG.DEVICE))
        # Lightning needs sigmas trailing (per ByteDance guidance).
        pipe.scheduler = EulerDiscreteScheduler.from_config(
            pipe.scheduler.config, timestep_spacing="trailing"
        )
        pipe.to(CONFIG.DEVICE)
        # Memory optimisations on Apple Silicon.
        if CONFIG.DEVICE == "mps":
            pipe.enable_attention_slicing()
            pipe.enable_vae_slicing()
        logger.info("pipeline ready (model=%s)", CONFIG.MODEL_ID)
        _pipe = pipe
        return _pipe


def render_text2image(
    prompt: str,
    negative_prompt: Optional[str] = None,
    seed: Optional[int] = None,
):
    """Run a single text→image inference and return a PIL Image."""
    import torch

    pipe = get_pipeline()
    generator = (
        torch.Generator(device=CONFIG.DEVICE).manual_seed(seed)
        if seed is not None
        else None
    )
    image = pipe(
        prompt=prompt,
        negative_prompt=negative_prompt or "",
        num_inference_steps=CONFIG.NUM_INFERENCE_STEPS,
        guidance_scale=CONFIG.GUIDANCE_SCALE,
        width=CONFIG.WIDTH,
        height=CONFIG.HEIGHT,
        generator=generator,
    ).images[0]
    return image
