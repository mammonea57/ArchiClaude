"""Diagnose ControlNet+MPS black-output bug.

Tests progressively :
  1. SD 1.5 text2image alone — should work (no ControlNet)
  2. SD 1.5 + ControlNet with a SYNTHETIC depth (gradient, not mostly black)
  3. SD 1.5 + ControlNet on CPU only — slow but shouldn't have MPS bug

Goal : isolate which combination fails so we can apply the right workaround.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
from PIL import Image

from src.config import CONFIG

OUT = Path.home() / "Library/Application Support/ArchiClaude/renders/diag"
OUT.mkdir(parents=True, exist_ok=True)


def make_gradient_depth() -> Image.Image:
    """A synthetic depth = vertical gradient, white at top → black at bottom."""
    h, w = 512, 512
    arr = np.zeros((h, w), dtype=np.uint8)
    for y in range(h):
        arr[y, :] = int((1 - y / h) * 255)
    return Image.fromarray(arr, mode="L").convert("RGB")


def test_1_text2img_only():
    """SD 1.5 text2image alone — must work (no ControlNet involvement)."""
    import torch
    from diffusers import StableDiffusionPipeline

    print("\n=== test 1 : SD 1.5 text2image only (no ControlNet) ===")
    pipe = StableDiffusionPipeline.from_pretrained(
        "runwayml/stable-diffusion-v1-5",
        torch_dtype=torch.float16,
        safety_checker=None,
        requires_safety_checker=False,
    )
    pipe.to(CONFIG.DEVICE)
    pipe.enable_attention_slicing()
    image = pipe("a modern brick residential building, photorealistic", num_inference_steps=20, generator=torch.Generator(CONFIG.DEVICE).manual_seed(42)).images[0]
    p = OUT / "test1_sd15_text2img.png"
    image.save(p)
    print(f"  → {p.name} {p.stat().st_size} bytes")
    return p.stat().st_size > 10_000


def test_2_controlnet_synthetic():
    """SD 1.5 + ControlNet with gradient depth (not mostly black)."""
    import torch
    from diffusers import (
        ControlNetModel,
        StableDiffusionControlNetPipeline,
    )

    print("\n=== test 2 : SD 1.5 + ControlNet on MPS, gradient depth ===")
    cn = ControlNetModel.from_pretrained(
        "lllyasviel/control_v11f1p_sd15_depth", torch_dtype=torch.float16
    )
    pipe = StableDiffusionControlNetPipeline.from_pretrained(
        "runwayml/stable-diffusion-v1-5",
        controlnet=cn,
        torch_dtype=torch.float16,
        safety_checker=None,
        requires_safety_checker=False,
    )
    pipe.to(CONFIG.DEVICE)
    pipe.enable_attention_slicing()
    depth = make_gradient_depth()
    image = pipe(
        "a modern brick residential building, photorealistic",
        image=depth,
        num_inference_steps=20,
        guidance_scale=7.5,
        generator=torch.Generator(CONFIG.DEVICE).manual_seed(42),
    ).images[0]
    p = OUT / "test2_sd15_controlnet_mps.png"
    image.save(p)
    print(f"  → {p.name} {p.stat().st_size} bytes")
    return p.stat().st_size > 10_000


def test_3_controlnet_cpu():
    """SD 1.5 + ControlNet on CPU — slow but bypasses any MPS bug."""
    import torch
    from diffusers import (
        ControlNetModel,
        StableDiffusionControlNetPipeline,
    )

    print("\n=== test 3 : SD 1.5 + ControlNet on CPU, gradient depth (slow) ===")
    cn = ControlNetModel.from_pretrained(
        "lllyasviel/control_v11f1p_sd15_depth", torch_dtype=torch.float32
    )
    pipe = StableDiffusionControlNetPipeline.from_pretrained(
        "runwayml/stable-diffusion-v1-5",
        controlnet=cn,
        torch_dtype=torch.float32,
        safety_checker=None,
        requires_safety_checker=False,
    )
    pipe.to("cpu")
    depth = make_gradient_depth()
    image = pipe(
        "a modern brick residential building, photorealistic",
        image=depth,
        num_inference_steps=15,  # fewer for CPU speed
        guidance_scale=7.5,
        generator=torch.Generator("cpu").manual_seed(42),
    ).images[0]
    p = OUT / "test3_sd15_controlnet_cpu.png"
    image.save(p)
    print(f"  → {p.name} {p.stat().st_size} bytes")
    return p.stat().st_size > 10_000


if __name__ == "__main__":
    results = {}
    try:
        results["1_t2i"] = test_1_text2img_only()
    except Exception as e:
        print(f"  test 1 FAILED : {e}")
        results["1_t2i"] = False
    try:
        results["2_cn_mps"] = test_2_controlnet_synthetic()
    except Exception as e:
        print(f"  test 2 FAILED : {e}")
        results["2_cn_mps"] = False
    try:
        results["3_cn_cpu"] = test_3_controlnet_cpu()
    except Exception as e:
        print(f"  test 3 FAILED : {e}")
        results["3_cn_cpu"] = False
    print(f"\n=== summary ===\n{results}\n→ files in {OUT}")
