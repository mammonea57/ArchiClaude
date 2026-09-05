"""SDXL ControlNet + LoRA endpoint — geometric fidelity guaranteed.

Compared to plain img2img (`modal_img2img_endpoint.py`), this endpoint uses
ControlNet to LOCK the input scene structure (silhouette, building shape,
roads, voisinage) and only restyle materials/lighting.

Two ControlNet variants are supported :
- "tile" : preserve input structure tightly (best for our Cycles renders),
  uses `xinsir/controlnet-tile-sdxl-1.0`.
- "canny" : extract edges from input then guide diffusion — useful when the
  Cycles render is too noisy and we want a cleaner outline (uses
  `diffusers/controlnet-canny-sdxl-1.0`).
- "depth" : monocular depth estimation (DPT) from the input — best for
  preserving 3D structure when input has good lighting (uses
  `diffusers/controlnet-depth-sdxl-1.0`).

Usage from local Mac :
    .venv/bin/modal run src/modal_controlnet_endpoint.py::sweep_cli \\
        --input-path refs/renders/.../cycles_render.png \\
        --controlnet-type tile \\
        --controlnet-scale 0.8 \\
        --lora-name archfr_brick_v2/epoch_1
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Optional

import modal

app = modal.App("archfr-controlnet")

SDXL_BASE = "stabilityai/stable-diffusion-xl-base-1.0"
SDXL_REFINER = "stabilityai/stable-diffusion-xl-refiner-1.0"

CONTROLNET_MODELS = {
    "tile": "xinsir/controlnet-tile-sdxl-1.0",
    "canny": "diffusers/controlnet-canny-sdxl-1.0",
    "depth": "diffusers/controlnet-depth-sdxl-1.0",
}

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
        "opencv-python-headless>=4.9",     # Canny edge detection
        "controlnet-aux>=0.0.7",           # depth & other preprocessors
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
class ControlNetPipeline:
    @modal.enter()
    def load(self):
        import torch
        from huggingface_hub import login

        token = os.environ.get("HF_TOKEN")
        if token:
            login(token=token, add_to_git_credential=False)

        print("[load] SDXL base + tile controlnet → A100")
        from diffusers import StableDiffusionXLControlNetPipeline, ControlNetModel
        self._cn_cache = {}
        # Pre-load the tile controlnet (cheapest first hit)
        cn_tile = ControlNetModel.from_pretrained(
            CONTROLNET_MODELS["tile"], torch_dtype=torch.bfloat16,
        )
        self._cn_cache["tile"] = cn_tile
        self.pipe = StableDiffusionXLControlNetPipeline.from_pretrained(
            SDXL_BASE, controlnet=cn_tile, torch_dtype=torch.bfloat16,
        ).to("cuda")
        self.pipe.set_progress_bar_config(disable=True)
        self.current_cn = "tile"
        self.loaded_lora = None
        self.dtype = torch.bfloat16
        self.SDXL_BASE = SDXL_BASE
        self.refiner = None   # lazy-loaded on first use

    def _ensure_controlnet(self, cn_type: str):
        """Swap the pipeline to use the controlnet `cn_type` (single CN).

        For multi-CN see `_ensure_multi_controlnet`. We keep the two paths
        separate so the existing single-CN sweep stays a fast path with
        a fp16 SDXL+1 CN footprint.
        """
        if self.current_cn == cn_type:
            return
        import torch
        from diffusers import StableDiffusionXLControlNetPipeline, ControlNetModel
        if cn_type not in self._cn_cache:
            print(f"[cn] loading {CONTROLNET_MODELS[cn_type]}")
            self._cn_cache[cn_type] = ControlNetModel.from_pretrained(
                CONTROLNET_MODELS[cn_type], torch_dtype=torch.bfloat16,
            )
        # Rebuild the pipeline with the new controlnet (cheap when SDXL is cached)
        prev_lora = self.loaded_lora
        self.pipe = StableDiffusionXLControlNetPipeline.from_pretrained(
            SDXL_BASE, controlnet=self._cn_cache[cn_type], torch_dtype=self.dtype,
        ).to("cuda")
        self.pipe.set_progress_bar_config(disable=True)
        self.current_cn = cn_type
        self.loaded_lora = None
        if prev_lora:
            self._ensure_lora(prev_lora)

    def _ensure_multi_controlnet(self, cn_types: list[str]):
        """Swap the pipeline to use MultiControlNetModel with `cn_types`.

        The pipeline accepts the same StableDiffusionXLControlNetPipeline
        class — only the controlnet arg becomes a MultiControlNetModel.
        At inference time `image` and `controlnet_conditioning_scale` are
        passed as parallel lists of length len(cn_types).
        """
        key = ",".join(cn_types)
        if self.current_cn == key:
            return
        import torch
        from diffusers import (
            StableDiffusionXLControlNetPipeline,
            ControlNetModel,
        )
        # In diffusers 0.30.3, MultiControlNetModel is not exposed at the
        # top level — import it from its actual module path.
        from diffusers.pipelines.controlnet.multicontrolnet import MultiControlNetModel
        cns = []
        for t in cn_types:
            if t not in self._cn_cache:
                print(f"[multi-cn] loading {CONTROLNET_MODELS[t]}")
                self._cn_cache[t] = ControlNetModel.from_pretrained(
                    CONTROLNET_MODELS[t], torch_dtype=torch.bfloat16,
                )
            cns.append(self._cn_cache[t])
        multi = MultiControlNetModel(cns)
        prev_lora = self.loaded_lora
        self.pipe = StableDiffusionXLControlNetPipeline.from_pretrained(
            SDXL_BASE, controlnet=multi, torch_dtype=self.dtype,
        ).to("cuda")
        self.pipe.set_progress_bar_config(disable=True)
        self.current_cn = key
        self.loaded_lora = None
        if prev_lora:
            self._ensure_lora(prev_lora)

    def _ensure_lora(self, lora_name: str):
        if self.loaded_lora == lora_name:
            return
        from peft import PeftModel
        lora_dir = Path("/cache/lora") / lora_name
        if not lora_dir.exists():
            raise FileNotFoundError(f"No LoRA at {lora_dir}")
        print(f"[lora] loading {lora_dir}")
        wrapped = PeftModel.from_pretrained(self.pipe.unet, str(lora_dir))
        self.pipe.unet = wrapped
        self.loaded_lora = lora_name

    def _ensure_refiner(self):
        """Lazy-load the SDXL refiner pipeline once. Shares VAE +
        text_encoder_2 with the base pipe to avoid duplicating weights.
        """
        if self.refiner is not None:
            return
        import torch
        from diffusers import StableDiffusionXLImg2ImgPipeline
        print("[refiner] loading SDXL refiner → A100")
        self.refiner = StableDiffusionXLImg2ImgPipeline.from_pretrained(
            SDXL_REFINER,
            text_encoder_2=self.pipe.text_encoder_2,
            vae=self.pipe.vae,
            torch_dtype=self.dtype,
            use_safetensors=True,
            variant="fp16",
        ).to("cuda")
        self.refiner.set_progress_bar_config(disable=True)

    def _preprocess(self, pil_img, cn_type: str):
        """Convert RGB input to the conditioning image expected by the chosen ControlNet."""
        from PIL import Image
        import numpy as np
        if cn_type == "tile":
            return pil_img
        if cn_type == "canny":
            import cv2
            arr = np.array(pil_img.convert("L"))
            edges = cv2.Canny(arr, 100, 200)
            rgb = np.stack([edges, edges, edges], axis=-1)
            return Image.fromarray(rgb)
        if cn_type == "depth":
            # Lightweight DPT via controlnet_aux
            from controlnet_aux import MidasDetector
            if not hasattr(self, "_midas"):
                self._midas = MidasDetector.from_pretrained("lllyasviel/Annotators")
            return self._midas(pil_img)
        raise ValueError(f"Unknown cn_type {cn_type}")

    @modal.method()
    def render(
        self,
        init_image_bytes: bytes,
        prompt: str,
        negative_prompt: str = "",
        lora_name: str = "archfr_brick_v2/epoch_1",
        controlnet_type: str = "tile",
        controlnet_scale: float = 0.8,
        guidance_scale: float = 7.5,
        num_inference_steps: int = 30,
        seed: int = 42,
        n_samples: int = 1,
        use_refiner: bool = False,
        refiner_high_noise_frac: float = 0.8,
        upscale_2x: bool = False,
    ) -> list[bytes]:
        import torch
        from PIL import Image
        self._ensure_controlnet(controlnet_type)
        self._ensure_lora(lora_name)
        if use_refiner:
            self._ensure_refiner()
        init = Image.open(io.BytesIO(init_image_bytes)).convert("RGB")
        if init.size != (1024, 1024):
            init = init.resize((1024, 1024), Image.LANCZOS)
        cond = self._preprocess(init, controlnet_type)
        if cond.size != (1024, 1024):
            cond = cond.resize((1024, 1024), Image.LANCZOS)

        results: list[bytes] = []
        for i in range(n_samples):
            gen = torch.Generator(device="cuda").manual_seed(seed + i)
            if use_refiner:
                # Ensemble pattern : base does 80% of denoising in latent
                # space, then refiner takes over for the last 20%.
                base_latents = self.pipe(
                    prompt=prompt,
                    negative_prompt=negative_prompt or None,
                    image=cond,
                    controlnet_conditioning_scale=controlnet_scale,
                    guidance_scale=guidance_scale,
                    num_inference_steps=num_inference_steps,
                    denoising_end=refiner_high_noise_frac,
                    generator=gen,
                    output_type="latent",
                ).images
                out = self.refiner(
                    prompt=prompt,
                    negative_prompt=negative_prompt or None,
                    image=base_latents,
                    num_inference_steps=num_inference_steps,
                    denoising_start=refiner_high_noise_frac,
                    generator=gen,
                ).images[0]
            else:
                out = self.pipe(
                    prompt=prompt,
                    negative_prompt=negative_prompt or None,
                    image=cond,
                    controlnet_conditioning_scale=controlnet_scale,
                    guidance_scale=guidance_scale,
                    num_inference_steps=num_inference_steps,
                    generator=gen,
                ).images[0]
            if upscale_2x:
                # 1024 → 2048 via LANCZOS resample. For brochure-grade
                # detail we'd want Real-ESRGAN ; LANCZOS is the cheap
                # honest upscale that doesn't hallucinate (no fake details).
                out = out.resize((2048, 2048), Image.LANCZOS)
            buf = io.BytesIO()
            out.save(buf, "PNG")
            results.append(buf.getvalue())
        return results


    @modal.method()
    def render_multi(
        self,
        init_image_bytes: bytes,
        prompt: str,
        negative_prompt: str = "",
        lora_name: str = "archfr_brick_v2/epoch_1",
        cn_types: list[str] = ("tile", "canny"),
        cn_scales: list[float] = (0.4, 0.4),
        guidance_scale: float = 7.5,
        num_inference_steps: int = 30,
        seed: int = 42,
        n_samples: int = 1,
        use_refiner: bool = False,
        refiner_high_noise_frac: float = 0.8,
        upscale_2x: bool = False,
    ) -> list[bytes]:
        """Multi-ControlNet pass : Tile preserves materials/lighting, Canny
        preserves crisp edges (mullions, balcony rails, doors). 50/50 mix
        at cn=0.4/0.4 is the standard archviz starting point.
        """
        import torch
        from PIL import Image
        if len(cn_types) != len(cn_scales):
            raise ValueError("cn_types and cn_scales must have same length")
        self._ensure_multi_controlnet(list(cn_types))
        self._ensure_lora(lora_name)
        if use_refiner:
            self._ensure_refiner()
        init = Image.open(io.BytesIO(init_image_bytes)).convert("RGB")
        if init.size != (1024, 1024):
            init = init.resize((1024, 1024), Image.LANCZOS)

        # Preprocess one conditioning image per CN type.
        conds = []
        for t in cn_types:
            c = self._preprocess(init, t)
            if c.size != (1024, 1024):
                c = c.resize((1024, 1024), Image.LANCZOS)
            conds.append(c)

        results: list[bytes] = []
        for i in range(n_samples):
            gen = torch.Generator(device="cuda").manual_seed(seed + i)
            if use_refiner:
                base_latents = self.pipe(
                    prompt=prompt,
                    negative_prompt=negative_prompt or None,
                    image=conds,
                    controlnet_conditioning_scale=list(cn_scales),
                    guidance_scale=guidance_scale,
                    num_inference_steps=num_inference_steps,
                    denoising_end=refiner_high_noise_frac,
                    generator=gen,
                    output_type="latent",
                ).images
                out = self.refiner(
                    prompt=prompt,
                    negative_prompt=negative_prompt or None,
                    image=base_latents,
                    num_inference_steps=num_inference_steps,
                    denoising_start=refiner_high_noise_frac,
                    generator=gen,
                ).images[0]
            else:
                out = self.pipe(
                    prompt=prompt,
                    negative_prompt=negative_prompt or None,
                    image=conds,
                    controlnet_conditioning_scale=list(cn_scales),
                    guidance_scale=guidance_scale,
                    num_inference_steps=num_inference_steps,
                    generator=gen,
                ).images[0]
            if upscale_2x:
                out = out.resize((2048, 2048), Image.LANCZOS)
            buf = io.BytesIO()
            out.save(buf, "PNG")
            results.append(buf.getvalue())
        return results


@app.local_entrypoint()
def multi_cli(
    input_path: str,
    prompt: str = ("masterpiece photorealistic archviz render, modern apartment "
                   "building with DOMINANT RED CLAY BRICK MASONRY facade, exposed "
                   "brick wall, every wall in red brick texture, balconies with "
                   "green plants, golden hour warm sunlight, contemporary French "
                   "residential architecture, eye-level street view, two people "
                   "walking, dramatic warm sky, brochure quality"),
    negative_prompt: str = ("blurry, low quality, distorted, deformed, watermark, "
                            "signature, low resolution, ugly, oversaturated, "
                            "cartoon, white facade, beige facade, plaster facade, "
                            "stucco, white wall, painted wall"),
    lora_name: str = "archfr_brick_v2/epoch_1",
    cn_tile_scale: float = 0.4,
    cn_canny_scale: float = 0.4,
    guidance_scale: float = 7.5,
    seed: int = 42,
    use_refiner: bool = True,
    upscale_2x: bool = True,
    out_dir: str = "refs/renders/multi_cn",
):
    """Multi-CN (Tile + Canny) + Refiner + Upscale 2x on one input."""
    import time
    src = Path(input_path)
    init_bytes = src.read_bytes()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    print(f"→ Multi-CN (tile {cn_tile_scale} + canny {cn_canny_scale}) "
          f"refiner={use_refiner} upscale={upscale_2x} on {src.name}")
    pipeline = ControlNetPipeline()
    ts = time.strftime("%Y%m%d_%H%M%S")
    pngs = pipeline.render_multi.remote(
        init_image_bytes=init_bytes,
        prompt=prompt,
        negative_prompt=negative_prompt,
        lora_name=lora_name,
        cn_types=["tile", "canny"],
        cn_scales=[cn_tile_scale, cn_canny_scale],
        guidance_scale=guidance_scale,
        seed=seed,
        n_samples=1,
        use_refiner=use_refiner,
        upscale_2x=upscale_2x,
    )
    path = out / f"{ts}_multi_t{int(cn_tile_scale*100):03d}_c{int(cn_canny_scale*100):03d}_s{seed}.png"
    path.write_bytes(pngs[0])
    print(f"✓ saved {path}")


@app.local_entrypoint()
def sweep_cli(
    input_path: str,
    prompt: str = ("a photorealistic 3D archviz render of a modern apartment "
                   "building with red brick facade, balconies with green plants, "
                   "golden hour lighting, contemporary residential architecture, "
                   "eye-level street view, with people walking, dramatic warm "
                   "sky, brochure quality"),
    negative_prompt: str = ("blurry, low quality, distorted, deformed, watermark, "
                            "signature, low resolution, ugly, oversaturated, cartoon"),
    lora_name: str = "archfr_brick_v2/epoch_1",
    controlnet_type: str = "tile",
    cn_scales: str = "0.4,0.6,0.8,1.0",
    guidance_scale: float = 7.5,
    seed: int = 42,
    out_dir: str = "refs/renders/controlnet_sweep",
    use_refiner: bool = False,
    upscale_2x: bool = False,
):
    """Run ControlNet sweep on `input_path` across a list of conditioning scales."""
    import time
    src = Path(input_path)
    init_bytes = src.read_bytes()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    print(f"→ ControlNet ({controlnet_type}) sweep on {src.name}")
    print(f"  LoRA      : {lora_name}")
    print(f"  cn_scales : {cn_scales}")
    print(f"  guidance  : {guidance_scale}")

    pipeline = ControlNetPipeline()
    ts = time.strftime("%Y%m%d_%H%M%S")
    for s_str in cn_scales.split(","):
        s = float(s_str.strip())
        print(f"  → cn_scale {s} refiner={use_refiner} upscale={upscale_2x} …")
        pngs = pipeline.render.remote(
            init_image_bytes=init_bytes,
            prompt=prompt,
            negative_prompt=negative_prompt,
            lora_name=lora_name,
            controlnet_type=controlnet_type,
            controlnet_scale=s,
            guidance_scale=guidance_scale,
            seed=seed,
            n_samples=1,
            use_refiner=use_refiner,
            upscale_2x=upscale_2x,
        )
        for i, png in enumerate(pngs):
            path = out / f"{ts}_{controlnet_type}_cn{int(s*100):03d}_s{seed + i}.png"
            path.write_bytes(png)
            print(f"    saved {path}")
    print("✓ sweep done.")
