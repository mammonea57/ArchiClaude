"""FLUX img2img endpoint with style-conditional LoRA.

Cycles render input → FLUX img2img with archfr_flux_style_conditional_v1 LoRA
+ explicit style tags → output. Best-of-both:
- Cycles preserves geometry (the building shape/scale/balconies)
- FLUX + LoRA applies the style mode chosen via tags

The LoRA was trained on 903 imgs with 10-axis taxonomy tags ; at inference
the user passes the tag combination they want (region, tier, material, etc.)
and the LoRA activates the corresponding visual mode.

Usage from local Mac :
    .venv/bin/modal run src/modal_flux_img2img_endpoint.py::sweep_cli \\
        --input-path refs/renders/.../cycles_photoreal.png \\
        --tags "tier-mir,region-european-parisian,scale-mid-rise-r3-r7,material-brick-red-warm,material-wood-louvers-vertical,lighting-blue-hour-warm-interior-glow,composition-human-eye-corner-3-4,foreground-tree-branches,story-couple-walking,atmosphere-light-haze,era-contemporary-2010s-2020s" \\
        --description "a Parisian brick infill apartment, blue-hour with warm interior glow" \\
        --strengths "0.35,0.5,0.65"

The output goes to refs/renders/flux_style_img2img/.
"""
from __future__ import annotations

import io
import os
from pathlib import Path
from typing import Optional

import modal

app = modal.App("archfr-flux-img2img")

FLUX_DEV = "black-forest-labs/FLUX.1-dev"

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        # NB : training was on diffusers 0.30.3 with FLUX img_ids 3D fix.
        # For inference we bump to 0.32.1 because FluxImg2ImgPipeline was
        # only added in 0.31. The LoRA weights are API-agnostic so they
        # load fine in 0.32.
        "torch==2.4.1",
        "torchvision==0.19.1",
        "triton==3.0.0",
        "diffusers==0.32.1",
        "transformers==4.46.3",
        "tokenizers>=0.20.0,<0.21",
        "peft==0.13.2",
        "accelerate==1.1.1",
        "safetensors>=0.4.5",
        "huggingface_hub>=0.26,<0.28",
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
class FluxImg2ImgPipeline:
    @modal.enter()
    def load(self):
        import torch
        from huggingface_hub import login

        token = os.environ.get("HF_TOKEN")
        if token:
            login(token=token, add_to_git_credential=False)

        print("[load] FLUX-dev img2img → A100")
        from diffusers import FluxImg2ImgPipeline
        self.pipe = FluxImg2ImgPipeline.from_pretrained(
            FLUX_DEV, torch_dtype=torch.bfloat16,
        ).to("cuda")
        self.pipe.set_progress_bar_config(disable=True)
        self.loaded_lora = None
        self.dtype = torch.bfloat16

    def _ensure_lora(self, lora_name: str):
        if self.loaded_lora == lora_name:
            return
        # Skip LoRA if name is "none"/"null"/"skip" → pure base FLUX-dev (photoreal, no archviz bias)
        if not lora_name or lora_name.lower() in ("none", "null", "skip"):
            print(f"[lora] SKIPPED — using base FLUX-dev (no archviz LoRA bias)")
            self.loaded_lora = lora_name
            return
        from peft import PeftModel
        lora_dir = Path("/cache/lora") / lora_name
        if not lora_dir.exists():
            raise FileNotFoundError(f"No LoRA at {lora_dir}")
        print(f"[lora] loading {lora_dir}")
        wrapped = PeftModel.from_pretrained(self.pipe.transformer, str(lora_dir))
        self.pipe.transformer = wrapped
        self.loaded_lora = lora_name

    @modal.method()
    def render(
        self,
        init_image_bytes: bytes,
        prompt: str,
        lora_name: str = "archfr_flux_style_conditional_v1/epoch_1",
        strength: float = 0.5,
        guidance_scale: float = 3.5,
        num_inference_steps: int = 30,
        seed: int = 42,
        n_samples: int = 1,
        resolution: int = 1024,
    ) -> list[bytes]:
        import torch
        from PIL import Image
        self._ensure_lora(lora_name)
        init = Image.open(io.BytesIO(init_image_bytes)).convert("RGB")
        # resolution > source = upscale-refine : LANCZOS up puis FLUX ajoute la
        # vraie haute fréquence (à strength bas la compo est préservée).
        if init.size != (resolution, resolution):
            init = init.resize((resolution, resolution), Image.LANCZOS)

        results: list[bytes] = []
        for i in range(n_samples):
            gen = torch.Generator(device="cuda").manual_seed(seed + i)
            out = self.pipe(
                prompt=prompt,
                image=init,
                height=resolution,
                width=resolution,
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
    tags: str = ("tier-mir,region-european-parisian,scale-mid-rise-r3-r7,"
                 "material-brick-red-warm,material-wood-louvers-vertical,"
                 "material-metal-black-steel-mullions,"
                 "lighting-blue-hour-warm-interior-glow,"
                 "composition-human-eye-corner-3-4,foreground-tree-branches,"
                 "story-couple-walking,story-pedestrian-motion-blur,"
                 "atmosphere-light-haze,era-contemporary-2010s-2020s"),
    description: str = ("a MIR-tier dusk render of a Parisian R+5 brick infill "
                        "apartment with vertical wood louvers, warm interior glow "
                        "at blue-hour, couple walking on sidewalk, foreground tree "
                        "branches framing the corner view"),
    lora_name: str = "archfr_flux_style_conditional_v1/epoch_1",
    strengths: str = "0.35,0.5,0.65",
    guidance_scale: float = 3.5,
    seed: int = 42,
    out_dir: str = "refs/renders/flux_style_img2img",
):
    """Sweep FLUX img2img on `input_path` with our style-conditional LoRA."""
    import time
    src = Path(input_path)
    init_bytes = src.read_bytes()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    prompt = f"{tags}, {description}"

    print(f"→ FLUX img2img sweep on {src.name}")
    print(f"  LoRA      : {lora_name}")
    print(f"  strengths : {strengths}")
    print(f"  tags head : {tags[:80]}...")

    pipeline = FluxImg2ImgPipeline()
    ts = time.strftime("%Y%m%d_%H%M%S")
    for s_str in strengths.split(","):
        s = float(s_str.strip())
        print(f"  → strength {s} …")
        pngs = pipeline.render.remote(
            init_image_bytes=init_bytes,
            prompt=prompt,
            lora_name=lora_name,
            strength=s,
            guidance_scale=guidance_scale,
            seed=seed,
            n_samples=1,
        )
        for i, png in enumerate(pngs):
            path = out / f"{ts}_flux_str{int(s*100):03d}_s{seed + i}.png"
            path.write_bytes(png)
            print(f"    saved {path}")
    print("✓ sweep done.")


# 5 region presets sharing the same canonical SDXL+CN brick foundation —
# only region tag varies + 1-2 lighting/material co-vary tags (per Phase 7
# lesson : pure region-only switching collapses to prototype).
PRESETS = {
    "parisian": {
        "tags": ("tier-mir,region-european-parisian,scale-mid-rise-r3-r7,"
                 "material-brick-red-warm,material-metal-black-steel-mullions,"
                 "lighting-blue-hour-warm-interior-glow,"
                 "composition-human-eye-corner-3-4,foreground-tree-branches,"
                 "story-couple-walking,story-pedestrian-motion-blur,"
                 "atmosphere-light-haze,era-contemporary-2010s-2020s"),
        "desc": ("a MIR-tier dusk render of a Parisian R+5 brick infill "
                 "apartment, black steel mullions, warm interior glow at "
                 "blue-hour, couple walking on sidewalk"),
    },
    "nordic": {
        "tags": ("tier-mir,region-nordic,scale-mid-rise-r3-r7,"
                 "material-brick-aged-mottled,material-wood-louvers-vertical,"
                 "lighting-overcast,composition-human-eye-corner-3-4,"
                 "foreground-vegetation-planter,story-cyclist,"
                 "atmosphere-clean-clear,era-contemporary-2010s-2020s"),
        "desc": ("a Copenhagen-style mottled aged brick apartment with vertical "
                 "wood louvers under soft overcast daylight, cyclist passing"),
    },
    "nyc-brooklyn": {
        "tags": ("tier-mir,region-american-nyc-brooklyn,scale-mid-rise-r3-r7,"
                 "material-brick-red-warm,material-metal-black-steel-mullions,"
                 "lighting-golden-hour-warm,composition-human-eye-corner-3-4,"
                 "foreground-tree-branches,story-cars-parked,"
                 "atmosphere-clean-clear,era-contemporary-2010s-2020s"),
        "desc": ("a Brooklyn brick infill brownstone-style at golden hour with "
                 "black steel mullions and warm street-level retail glow, "
                 "parked sedan, mature street tree"),
    },
    "tehran": {
        "tags": ("tier-mir,region-mena-tehran-iranian,scale-mid-rise-r3-r7,"
                 "material-brick-terracotta-warm,"
                 "material-metal-perforated-screens,"
                 "lighting-midday-harsh,composition-human-eye-corner-3-4,"
                 "foreground-vegetation-planter,story-empty,"
                 "atmosphere-clean-clear,era-contemporary-2010s-2020s"),
        "desc": ("a Tehran townhouse with sandy terracotta brick, projecting "
                 "bay windows and perforated brick screens, vine planters, "
                 "harsh midday sun"),
    },
    "mediterranean": {
        "tags": ("tier-mir,region-mediterranean,scale-mid-rise-r3-r7,"
                 "material-stone-warm-limestone,material-wood-shutters-vernacular,"
                 "lighting-golden-hour-warm,composition-human-eye-corner-3-4,"
                 "foreground-vegetation-planter,story-cafe-diners,"
                 "atmosphere-light-haze,era-contemporary-2010s-2020s"),
        "desc": ("a warm limestone mid-rise residential block with timber "
                 "shutters at golden hour, café diners spilling onto sidewalk"),
    },
}


@app.local_entrypoint()
def multi_preset_cli(
    input_path: str,
    presets: str = "parisian,nordic,nyc-brooklyn,tehran,mediterranean",
    lora_name: str = "archfr_flux_style_conditional_v3/epoch_1",
    strength: float = 0.45,
    guidance_scale: float = 3.5,
    seed: int = 42,
    out_dir: str = "refs/renders/multi_preset_sv",
):
    """Multi-preset style switching on a single Streetview-like input.

    All presets share the same source image (SDXL+CN brick foundation) — only
    the region/material/lighting tag combo changes. Validates the LoRA's
    style-conditional switching capability.
    """
    import time
    src = Path(input_path)
    init_bytes = src.read_bytes()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    preset_keys = [p.strip() for p in presets.split(",") if p.strip()]
    unknown = [k for k in preset_keys if k not in PRESETS]
    if unknown:
        raise ValueError(f"Unknown preset(s) : {unknown}. Choose from {list(PRESETS)}.")

    print(f"→ multi-preset FLUX img2img on {src.name}")
    print(f"  LoRA     : {lora_name}")
    print(f"  presets  : {preset_keys}")
    print(f"  strength : {strength}")

    pipeline = FluxImg2ImgPipeline()
    ts = time.strftime("%Y%m%d_%H%M%S")
    for key in preset_keys:
        p = PRESETS[key]
        prompt = f"{p['tags']}, {p['desc']}"
        print(f"  → preset={key} …")
        pngs = pipeline.render.remote(
            init_image_bytes=init_bytes,
            prompt=prompt,
            lora_name=lora_name,
            strength=strength,
            guidance_scale=guidance_scale,
            seed=seed,
            n_samples=1,
        )
        for i, png in enumerate(pngs):
            path = out / f"{ts}_{key}_str{int(strength*100):03d}_s{seed + i}.png"
            path.write_bytes(png)
            print(f"    saved {path}")
    print(f"✓ multi-preset done : {len(preset_keys)} renders.")


# ---------------------------------------------------------------------------
# Minimal single-image CLI for the L building Blender→FLUX pipeline.
# Used by the Nogent 80 Héros 6 options × 6 POVs fan-out.
# ---------------------------------------------------------------------------
@app.local_entrypoint()
def infer_cli(
    init_image_path: str,
    prompt: str,
    lora_name: str = "archfr_flux_style_conditional_v3/epoch_1",
    strength: float = 0.45,
    guidance_scale: float = 3.5,
    seed: int = 42,
    resolution: int = 1024,
    out_dir: str = "refs/renders/flux_img2img_one",
):
    """Render ONE FLUX img2img sample with the given prompt + strength on init_image_path.

    Used as the second stage of the Blender → FLUX pipeline for L building Nogent.
    """
    import time
    src = Path(init_image_path)
    init_bytes = src.read_bytes()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    print(f"→ FLUX img2img single on {src.name}")
    print(f"  LoRA     : {lora_name}")
    print(f"  strength : {strength}")
    print(f"  prompt   : {prompt[:120]}…")
    pipeline = FluxImg2ImgPipeline()
    pngs = pipeline.render.remote(
        init_image_bytes=init_bytes,
        prompt=prompt,
        lora_name=lora_name,
        strength=strength,
        guidance_scale=guidance_scale,
        seed=seed,
        n_samples=1,
        resolution=resolution,
    )
    ts = time.strftime("%Y%m%d_%H%M%S")
    for i, png in enumerate(pngs):
        path = out / f"{ts}_str{int(strength*100):03d}_s{seed + i}_r{resolution}.png"
        path.write_bytes(png)
        print(f"  ✓ saved {path}")
