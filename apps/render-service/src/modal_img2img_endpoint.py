"""SDXL img2img endpoint with a trained LoRA — the "style upgrade" stage.

Use case:
    Input: a structurally-correct render (e.g. Blender Cycles output of the
    IGN-context scene for a project) — geometry is right but visually mid.
    Output: same scene, but restyled to match our Pinterest-trained
    `archfr_brick_v2/epoch_1` (or any other LoRA). Geometry preserved if
    strength stays in ~0.3-0.5 range.

This decouples geometry (Blender Cycles) from style (SDXL + LoRA), which
is the standard archviz pipeline pattern (V-Ray render → Photoshop style
pass at the studios).

Usage from local Mac :
    .venv/bin/modal run src/modal_img2img_endpoint.py::sweep_cli \
        --input-path /Users/.../init.png \
        --lora-name archfr_brick_v2/epoch_1 \
        --prompt "..."

The script writes the styled outputs to `refs/renders/img2img_sweep/`.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Optional

import modal

app = modal.App("archfr-img2img")

SDXL_BASE = "stabilityai/stable-diffusion-xl-base-1.0"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch==2.4.1",
        "torchvision==0.19.1",
        "triton==3.0.0",
        "diffusers==0.30.3",
        "transformers==4.44.2",
        "tokenizers>=0.19.1,<0.20",
        "peft==0.13.0",
        "accelerate==1.0.1",
        "safetensors>=0.4.5",
        "huggingface_hub>=0.25,<0.27",
        "pillow>=10.4",
        "sentencepiece>=0.2",
        "protobuf>=3.20",
        "numpy>=1.26,<2.0",
    )
)

hf_cache = modal.Volume.from_name("archfr-hf-cache", create_if_missing=True)
lora_cache = modal.Volume.from_name("archfr-lora-cache", create_if_missing=True)


@app.cls(
    image=image,
    gpu="A100-80GB",
    timeout=900,
    scaledown_window=120,
    volumes={
        "/root/.cache/huggingface": hf_cache,
        "/cache": lora_cache,
    },
    secrets=[modal.Secret.from_name("huggingface")],
)
class Img2ImgPipeline:
    @modal.enter()
    def load(self):
        import torch
        from diffusers import StableDiffusionXLImg2ImgPipeline
        from huggingface_hub import login

        token = os.environ.get("HF_TOKEN")
        if token:
            login(token=token, add_to_git_credential=False)

        print("[load] SDXL img2img base → A100")
        self.pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(
            SDXL_BASE, torch_dtype=torch.bfloat16,
        ).to("cuda")
        self.pipe.set_progress_bar_config(disable=True)
        self.loaded_lora = None
        self.dtype = torch.bfloat16

    def _ensure_lora(self, lora_name: str):
        """Attach a PEFT LoRA adapter on top of the SDXL UNet."""
        if self.loaded_lora == lora_name:
            return
        if self.loaded_lora is not None:
            # Unload prior — clear PEFT wrapper by reloading base UNet ref.
            from diffusers import StableDiffusionXLImg2ImgPipeline
            import torch
            print(f"[lora] unloading prior {self.loaded_lora}")
            self.pipe = StableDiffusionXLImg2ImgPipeline.from_pretrained(
                SDXL_BASE, torch_dtype=torch.bfloat16,
            ).to("cuda")
            self.pipe.set_progress_bar_config(disable=True)

        from peft import PeftModel
        lora_dir = Path("/cache/lora") / lora_name
        print(f"[lora] loading {lora_dir}")
        if not lora_dir.exists():
            raise FileNotFoundError(f"No LoRA at {lora_dir}")
        wrapped = PeftModel.from_pretrained(self.pipe.unet, str(lora_dir))
        self.pipe.unet = wrapped
        self.loaded_lora = lora_name

    @modal.method()
    def render(
        self,
        init_image_bytes: bytes,
        prompt: str,
        negative_prompt: str = "",
        lora_name: str = "archfr_brick_v2/epoch_1",
        strength: float = 0.4,
        guidance_scale: float = 6.0,
        num_inference_steps: int = 30,
        seed: int = 42,
        n_samples: int = 1,
    ) -> list[bytes]:
        import torch
        from PIL import Image

        self._ensure_lora(lora_name)
        init = Image.open(io.BytesIO(init_image_bytes)).convert("RGB")
        # SDXL canonical resolution
        if init.size != (1024, 1024):
            init = init.resize((1024, 1024), Image.LANCZOS)

        results: list[bytes] = []
        for i in range(n_samples):
            gen = torch.Generator(device="cuda").manual_seed(seed + i)
            out = self.pipe(
                prompt=prompt,
                negative_prompt=negative_prompt or None,
                image=init,
                strength=strength,
                guidance_scale=guidance_scale,
                num_inference_steps=num_inference_steps,
                generator=gen,
            ).images[0]
            buf = io.BytesIO()
            out.save(buf, "PNG")
            results.append(buf.getvalue())
        return results


@app.local_entrypoint()
def sweep_cli(
    input_path: str,
    prompt: str = ("a modern apartment building exterior with brick facade, "
                   "balconies with plants, golden hour lighting, contemporary "
                   "design, residential apartment building, eye-level street "
                   "view, with people walking"),
    negative_prompt: str = ("blurry, low quality, distorted, deformed, watermark, "
                            "signature, low resolution, ugly, oversaturated, cartoon"),
    lora_name: str = "archfr_brick_v2/epoch_1",
    strengths: str = "0.25,0.35,0.45,0.55",
    guidance_scale: float = 6.0,
    seed: int = 42,
    out_dir: str = "refs/renders/img2img_sweep",
):
    """Run img2img on `input_path` across a sweep of strengths."""
    import time
    src = Path(input_path)
    if not src.exists():
        raise FileNotFoundError(input_path)
    init_bytes = src.read_bytes()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    print(f"→ img2img sweep on {src.name}")
    print(f"  LoRA      : {lora_name}")
    print(f"  strengths : {strengths}")
    print(f"  guidance  : {guidance_scale}")

    pipeline = Img2ImgPipeline()
    ts = time.strftime("%Y%m%d_%H%M%S")
    for s_str in strengths.split(","):
        s = float(s_str.strip())
        print(f"  → strength {s} …")
        pngs = pipeline.render.remote(
            init_image_bytes=init_bytes,
            prompt=prompt,
            negative_prompt=negative_prompt,
            lora_name=lora_name,
            strength=s,
            guidance_scale=guidance_scale,
            seed=seed,
            n_samples=1,
        )
        for i, png in enumerate(pngs):
            path = out / f"{ts}_str{int(s*100):03d}_s{seed + i}.png"
            path.write_bytes(png)
            print(f"    saved {path}")
    print("✓ sweep done.")
