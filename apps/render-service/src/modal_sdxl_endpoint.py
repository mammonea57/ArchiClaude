"""Cloud SDXL + ControlNet-depth inference on Modal A10G.

Why : SD 1.5 + Realistic Vision V6 + hires-fix on M3 CPU plafonne à ~8.5/10
and takes 4-5 min per render. SDXL native 1024 on Modal A10G produces
9-9.5/10 in ~30s for ~$0.05.

Trade-offs vs the local SD 1.5 stack :
  - Pro : native 1024×1024, way more detail, photoreal magazine quality.
  - Pro : 30s/render vs 4-5 min on CPU.
  - Con : per-render cost (~$0.05).
  - Con : LoRA we trained is SD 1.5 only — would need a separate SDXL retrain.
    For now we skip the LoRA — the BM-grounded prompt does the heavy lifting,
    and SDXL's photoreal baseline is already very strong.

Usage from the local backend :
    from .modal_sdxl_endpoint import render_sdxl_remote
    image = render_sdxl_remote.remote(prompt, depth_png_bytes, ...)

Or as a one-shot CLI test :
    .venv/bin/modal run src/modal_sdxl_endpoint.py
"""
from __future__ import annotations

import io
from typing import Optional

import modal

SDXL_BASE = "SG161222/RealVisXL_V4.0"
# ControlNet-depth for SDXL — locks the L geometry from the depth map.
SDXL_CONTROLNET_DEPTH = "diffusers/controlnet-depth-sdxl-1.0"
# ControlNet-tile : preserves the structure/colours of an input image while
# letting diffusion add sharp high-frequency detail. The standard tool for
# "magazine-quality upscale" of an existing render. Used in Path E to
# sharpen the local Phase 5d output without losing its faubourg materials.
SDXL_CONTROLNET_TILE = "xinsir/controlnet-tile-sdxl-1.0"

app = modal.App("archfr-sdxl-inference")

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "torch==2.5.1",
        "torchvision==0.20.1",
        "diffusers==0.32.0",
        "transformers>=4.46,<5.0",
        "pillow>=10.4",
        "safetensors>=0.4.5,<0.6",
        "accelerate>=1.0,<2.0",
        "huggingface_hub>=0.26,<1.0",
        # spandrel : torch-2.5 compatible model loader for Real-ESRGAN.
        # Replaces the basicsr+realesrgan stack that wouldn't pip-install
        # against modern torchvision.
        "spandrel==0.4.1",
        "opencv-python-headless",
    )
)

# Persistent volume so SDXL weights are cached across runs (~7 GB once).
hf_cache = modal.Volume.from_name("archfr-hf-cache", create_if_missing=True)


@app.cls(
    image=image,
    gpu="A10G",
    timeout=600,
    volumes={"/root/.cache/huggingface": hf_cache},
    scaledown_window=300,
)
class SDXLPipeline:
    @modal.enter()
    def load(self):
        """Load SDXL : ControlNet-depth pipe + img2img refiner + ControlNet-tile (Path E)."""
        import torch
        from diffusers import (
            ControlNetModel,
            DPMSolverMultistepScheduler,
            StableDiffusionXLControlNetPipeline,
            StableDiffusionXLControlNetImg2ImgPipeline,
            StableDiffusionXLImg2ImgPipeline,
        )

        print(f"loading {SDXL_BASE} + ControlNet-depth + ControlNet-tile on A10G …")
        controlnet = ControlNetModel.from_pretrained(
            SDXL_CONTROLNET_DEPTH,
            torch_dtype=torch.float16,
            use_safetensors=True,
        )
        tile_controlnet = ControlNetModel.from_pretrained(
            SDXL_CONTROLNET_TILE,
            torch_dtype=torch.float16,
            use_safetensors=True,
        )
        # Use the fp16 VAE fix to avoid black output at fp16 precision.
        from diffusers import AutoencoderKL
        vae = AutoencoderKL.from_pretrained(
            "madebyollin/sdxl-vae-fp16-fix", torch_dtype=torch.float16
        )
        pipe = StableDiffusionXLControlNetPipeline.from_pretrained(
            SDXL_BASE,
            controlnet=controlnet,
            vae=vae,
            torch_dtype=torch.float16,
            use_safetensors=True,
            variant="fp16",
        )
        pipe.scheduler = DPMSolverMultistepScheduler.from_config(
            pipe.scheduler.config, use_karras_sigmas=True
        )
        pipe.to("cuda")
        pipe.enable_attention_slicing("auto")
        self.pipe = pipe

        # img2img refiner — shared weights, no extra GPU memory.
        refiner = StableDiffusionXLImg2ImgPipeline(
            vae=pipe.vae,
            text_encoder=pipe.text_encoder,
            text_encoder_2=pipe.text_encoder_2,
            tokenizer=pipe.tokenizer,
            tokenizer_2=pipe.tokenizer_2,
            unet=pipe.unet,
            scheduler=pipe.scheduler,
        )
        refiner.to("cuda")
        refiner.enable_attention_slicing("auto")
        self.refiner = refiner

        # ControlNet-tile pipeline — for sharp upscale via tile conditioning.
        # Uses the SAME UNet/VAE as the depth pipeline → no extra weights.
        tile_pipe = StableDiffusionXLControlNetImg2ImgPipeline(
            vae=pipe.vae,
            text_encoder=pipe.text_encoder,
            text_encoder_2=pipe.text_encoder_2,
            tokenizer=pipe.tokenizer,
            tokenizer_2=pipe.tokenizer_2,
            unet=pipe.unet,
            controlnet=tile_controlnet,
            scheduler=pipe.scheduler,
        )
        tile_pipe.to("cuda")
        tile_pipe.enable_attention_slicing("auto")
        self.tile_pipe = tile_pipe
        print("✓ SDXL pipeline + img2img refiner + tile-upscale ready")

    @modal.method()
    def refine(
        self,
        init_png: bytes,
        prompt: str,
        prompt_2: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        denoise: float = 0.55,        # stronger detail synthesis (less of source blur)
        steps: int = 60,
        target_size: int = 2048,      # native 2K — 4× pixel count vs 1024
    ) -> bytes:
        """Img2img refine an existing render at higher resolution.

        Strategy : the local input PNG carries the correct composition (validated
        Phase 5d). We upscale to 1536×1536 via LANCZOS *as the init latent* then
        run SDXL img2img with denoise=0.35 — strong enough to synthesise sharp
        textures (window mullions, brick joints, foliage) at the higher
        resolution that SD 1.5 couldn't reach natively.
        """
        import torch
        from PIL import Image

        init = Image.open(io.BytesIO(init_png)).convert("RGB")
        if init.size != (target_size, target_size):
            init = init.resize((target_size, target_size), Image.LANCZOS)

        # VAE tiling avoids OOM on A10G (24 GB) when going past 1024.
        try:
            self.refiner.enable_vae_tiling()
        except Exception:
            pass

        generator = torch.Generator(device="cuda").manual_seed(seed) if seed is not None else None
        kwargs = dict(
            prompt=prompt,
            negative_prompt=negative_prompt or "",
            image=init,
            strength=denoise,
            num_inference_steps=steps,
            guidance_scale=7.5,
            generator=generator,
        )
        if prompt_2:
            kwargs["prompt_2"] = prompt_2
            kwargs["negative_prompt_2"] = negative_prompt or ""
        out = self.refiner(**kwargs).images[0]

        buf = io.BytesIO()
        out.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    @modal.method()
    def esrgan_upscale(
        self,
        init_png: bytes,
        scale: int = 4,
        target_size: int = 2048,
    ) -> bytes:
        """Real-ESRGAN x4 upscale + downsample to target_size.

        Purpose-built for sharp texture synthesis — adds real high-frequency
        detail (window mullions, brick joints, foliage edges) that img2img
        denoise can't reproduce because img2img preserves source blur.

        Pipeline : 1024 → x4 → 4096 → LANCZOS → 2048 = crisp 2K.
        """
        import io
        import numpy as np
        import torch
        from PIL import Image

        if not hasattr(self, "_esrgan"):
            print("loading Real-ESRGAN x4plus via spandrel …")
            from huggingface_hub import hf_hub_download
            from spandrel import ModelLoader
            # Use a publicly-hosted ESRGAN checkpoint
            model_path = hf_hub_download(
                repo_id="ai-forever/Real-ESRGAN",
                filename="RealESRGAN_x4.pth",
            )
            self._esrgan = ModelLoader().load_from_file(model_path).cuda().eval()

        init = Image.open(io.BytesIO(init_png)).convert("RGB")
        # Tensor in [0,1] CHW float
        arr = np.asarray(init, dtype=np.float32) / 255.0
        t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).cuda()
        with torch.no_grad():
            up = self._esrgan(t)
        up = up.clamp(0, 1).squeeze(0).permute(1, 2, 0).cpu().numpy()
        big = Image.fromarray((up * 255).astype("uint8"))

        # Downsample to target if 4x went past it
        if max(big.size) > target_size:
            from PIL import Image as PILImage
            big = big.resize((target_size, target_size), PILImage.LANCZOS)

        buf = io.BytesIO()
        big.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    @modal.method()
    def tile_upscale(
        self,
        init_png: bytes,
        prompt: str,
        prompt_2: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        denoise: float = 0.5,
        steps: int = 50,
        controlnet_conditioning_scale: float = 0.7,
        target_size: int = 2048,
    ) -> bytes:
        """Path E : ControlNet-tile sharpen-upscale.

        Takes a blurry-but-correctly-composed source render (typically the
        local Phase 5d output) and synthesises sharp facade detail at
        target_size, while ControlNet-tile preserves the structure +
        materials + colours of the source. This is the standard SD community
        technique for "magazine quality upscale".
        """
        import torch
        from PIL import Image

        init = Image.open(io.BytesIO(init_png)).convert("RGB")
        if init.size != (target_size, target_size):
            init = init.resize((target_size, target_size), Image.LANCZOS)

        try:
            self.tile_pipe.enable_vae_tiling()
        except Exception:
            pass

        generator = torch.Generator(device="cuda").manual_seed(seed) if seed is not None else None
        kwargs = dict(
            prompt=prompt,
            negative_prompt=negative_prompt or "",
            image=init,
            control_image=init,           # tile controlnet sees the same image
            strength=denoise,
            num_inference_steps=steps,
            guidance_scale=7.5,
            controlnet_conditioning_scale=controlnet_conditioning_scale,
            generator=generator,
        )
        if prompt_2:
            kwargs["prompt_2"] = prompt_2
            kwargs["negative_prompt_2"] = negative_prompt or ""
        out = self.tile_pipe(**kwargs).images[0]

        buf = io.BytesIO()
        out.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    @modal.method()
    def render(
        self,
        prompt: str,
        depth_png: bytes,
        prompt_2: Optional[str] = None,
        negative_prompt: Optional[str] = None,
        seed: Optional[int] = None,
        controlnet_conditioning_scale: float = 0.8,
        steps: int = 30,
        width: int = 1024,
        height: int = 1024,
        upscale: bool = False,
    ) -> bytes:
        """Run a single SDXL render from depth — locks composition to depth geometry."""
        import torch
        from PIL import Image

        depth = Image.open(io.BytesIO(depth_png)).convert("RGB")
        if depth.size != (width, height):
            depth = depth.resize((width, height), Image.LANCZOS)

        generator = torch.Generator(device="cuda").manual_seed(seed) if seed is not None else None

        kwargs = dict(
            prompt=prompt,
            negative_prompt=negative_prompt or "",
            image=depth,
            num_inference_steps=steps,
            guidance_scale=7.5,
            controlnet_conditioning_scale=controlnet_conditioning_scale,
            width=width,
            height=height,
            generator=generator,
        )
        # Dual-encoder : pass material details to the OpenCLIP-bigG side,
        # doubling effective token budget to ~150.
        if prompt_2:
            kwargs["prompt_2"] = prompt_2
            kwargs["negative_prompt_2"] = negative_prompt or ""
            print(f"prompt_2 (bigG): {prompt_2}")
        # VAE tiling for high-res renders (>1024) to avoid OOM on A10G.
        if width > 1024 or height > 1024:
            try:
                self.pipe.enable_vae_tiling()
            except Exception:
                pass
        out = self.pipe(**kwargs).images[0]

        if upscale:
            out = self._upscale_2k(out)

        buf = io.BytesIO()
        out.save(buf, format="PNG", optimize=True)
        return buf.getvalue()

    def _upscale_2k(self, img):
        """Real-ESRGAN x4 → downsample to 2K. Adds sharp synthesised detail."""
        import numpy as np
        from PIL import Image
        try:
            from realesrgan import RealESRGANer
            from basicsr.archs.rrdbnet_arch import RRDBNet
        except Exception as e:
            print(f"!! ESRGAN import failed ({e}) — skipping upscale")
            return img

        # Lazy-init the upscaler once per container — kept on the instance.
        if not hasattr(self, "_upscaler"):
            print("loading Real-ESRGAN x4plus …")
            model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64,
                            num_block=23, num_grow_ch=32, scale=4)
            self._upscaler = RealESRGANer(
                scale=4,
                model_path="https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth",
                model=model,
                tile=512, tile_pad=10, pre_pad=0, half=True, gpu_id=0,
            )
        arr = np.array(img.convert("RGB"))
        upscaled, _ = self._upscaler.enhance(arr, outscale=4)
        # Downsample 4096 → 2048 (2K, crisp)
        big = Image.fromarray(upscaled)
        return big.resize((big.width // 2, big.height // 2), Image.LANCZOS)


@app.function(image=image, timeout=900, volumes={"/root/.cache/huggingface": hf_cache})
def render_orbit_frames(
    bm_payload: dict,
    angles_deg: list,
    target_size: int = 2048,
    seed: int = 42,
) -> list:
    """Render orbit frames at evenly-spaced camera angles around the building.

    For each angle θ, computes a CameraPreset placed at distance D, height h
    around the building's centroid, generates a depth map, and runs SDXL
    ControlNet at native target_size × target_size.

    Returns a list of PNG bytes, one per angle.
    """
    import io
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    # NOTE : the depth_map module reads CONFIG which expects torch — Modal
    # container has it. We import lazily at function call time.
    from src.depth_map import (
        Camera,
        camera_from_preset,
        depth_to_pil,
        render_depth_map,
    )
    from src.prompt_context.synthesizer import synthesize_dual_prompts

    model = bm_payload.get("model_json", bm_payload)
    fp = model["envelope"]["footprint_geojson"]["coordinates"][0]
    fp_xy = [(float(p[0]), float(p[1])) for p in fp]
    h_total = float(model["envelope"].get("hauteur_totale_m", 17.0))

    # Build a centroid + bbox for the orbit camera math.
    xs = [p[0] for p in fp_xy]
    ys = [p[1] for p in fp_xy]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    bbox_diag = ((max(xs) - min(xs))**2 + (max(ys) - min(ys))**2)**0.5
    distance = bbox_diag * 1.5  # camera ~1.5x the diagonal away
    cam_height = h_total * 0.5

    # Synthesize one prompt for the building (re-used for every frame).
    prompt, prompt_2, neg = synthesize_dual_prompts(bm_payload, preset="rue_se_eloignee")

    sdxl = SDXLPipeline()
    out_pngs = []
    import math
    for angle in angles_deg:
        rad = math.radians(angle)
        cam_x = cx + distance * math.cos(rad)
        cam_y = cy + distance * math.sin(rad)
        cam = Camera(
            position=(cam_x, cam_y, cam_height),
            target=(cx, cy, h_total * 0.4),
            fov_deg=45.0,
        )
        depth = render_depth_map(fp_xy, h_total, cam)
        depth_pil = depth_to_pil(depth)
        buf = io.BytesIO()
        depth_pil.save(buf, format="PNG")

        png = sdxl.render.remote(
            prompt=prompt,
            prompt_2=prompt_2,
            depth_png=buf.getvalue(),
            negative_prompt=neg,
            seed=seed,
            controlnet_conditioning_scale=0.9,
            steps=40,
            width=target_size,
            height=target_size,
        )
        out_pngs.append(png)
    return out_pngs


@app.local_entrypoint()
def main(project_id: str = "e9a960c8-081f-4c42-a65b-619610a61134",
         preset: str = "rue_se_eloignee",
         seed: int = 42,
         init_png: str = "",
         mode: str = "tile"):
    """Render via Modal A10G.

    Args :
        init_png : if set, refines an existing render rather than freshly rendering.
        mode : "tile" (Path E, ControlNet-tile) or "refine" (Path C, plain img2img)
            or empty/depth for fresh ControlNet-depth render.
    """
    import json
    import urllib.request
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from src.depth_map import (
        camera_from_preset,
        depth_to_pil,
        render_depth_map,
    )
    from src.prompt_context.synthesizer import synthesize_prompt

    with urllib.request.urlopen(f"http://localhost:8000/api/v1/projects/{project_id}/building_model") as r:
        bm = json.load(r)
    model = bm.get("model_json", bm)
    fp = model["envelope"]["footprint_geojson"]["coordinates"][0]
    fp_xy = [(float(p[0]), float(p[1])) for p in fp]
    h = float(model["envelope"].get("hauteur_totale_m", 17.0))

    cam = camera_from_preset(fp_xy, h, preset)
    depth = render_depth_map(fp_xy, h, cam)
    depth_pil = depth_to_pil(depth)
    buf = io.BytesIO()
    depth_pil.save(buf, format="PNG")
    depth_png = buf.getvalue()

    # Use the Phase 5d layered-facade synthesizer (BM + PLU + voisinage +
    # tendances 2025) — this produces a stratified prompt with RDC pierre +
    # courant enduit + attique retrait that JuggernautXL can render correctly.
    # Dual-encoder : prompt 1 = scene + composition (CLIP-L)
    #                prompt 2 = materials + accents (OpenCLIP-bigG)
    # → ~150 effective tokens vs the 77-token single-encoder cap.
    from src.prompt_context.synthesizer import synthesize_dual_prompts
    prompt, prompt_2, negative = synthesize_dual_prompts(
        bm, preset, project_id=project_id
    )
    print(f"prompt: {prompt}")
    print(f"negative: {negative}")

    sdxl = SDXLPipeline()
    print(f"prompt 1 (CLIP-L): {prompt}")
    print(f"prompt 2 (bigG):   {prompt_2}")

    if init_png:
        init_bytes = Path(init_png).expanduser().read_bytes()
        if mode == "tile":
            # Path E : ControlNet-tile sharp upscale at 2048 — best of both worlds.
            print(f"→ TILE UPSCALE 2048 {init_png} ({len(init_bytes):,} bytes) …")
            png = sdxl.tile_upscale.remote(
                init_png=init_bytes,
                prompt=prompt,
                prompt_2=prompt_2,
                negative_prompt=negative,
                seed=seed,
                denoise=0.5,
                steps=50,
                controlnet_conditioning_scale=0.7,
                target_size=2048,
            )
        elif mode == "esrgan":
            # Path F : Real-ESRGAN sharp upscale (no diffusion, dedicated
            # detail-synthesis model — sharper than tile diffusion).
            print(f"→ ESRGAN x4 SHARP UPSCALE {init_png} ({len(init_bytes):,} bytes) …")
            png = sdxl.esrgan_upscale.remote(init_png=init_bytes, target_size=2048)
        elif mode == "tile_then_esrgan":
            # Path G : tile-upscale FIRST (composition + medium sharpness)
            # then ESRGAN x4 → downsample (final crisp 2K). Best of both.
            print(f"→ TILE UPSCALE 1024 then ESRGAN x4 → 2K …")
            tile_out = sdxl.tile_upscale.remote(
                init_png=init_bytes,
                prompt=prompt,
                prompt_2=prompt_2,
                negative_prompt=negative,
                seed=seed,
                denoise=0.5,
                steps=50,
                controlnet_conditioning_scale=0.7,
                target_size=1024,           # keep tile pass at native SDXL
            )
            png = sdxl.esrgan_upscale.remote(init_png=tile_out, target_size=2048)
        else:
            print(f"→ REFINING {init_png} ({len(init_bytes):,} bytes) on Modal A10G …")
            png = sdxl.refine.remote(
                init_png=init_bytes,
                prompt=prompt,
                prompt_2=prompt_2,
                negative_prompt=negative,
                seed=seed,
                denoise=0.55,
                steps=60,
                target_size=2048,
            )
    else:
        prompt = ("modern contemporary 2024 newly-built apartment building, "
                  "no medieval, no ivy, no fantasy, " + prompt)
        print("→ FRESH 2048 RENDER (stratified depth) on Modal A10G …")
        png = sdxl.render.remote(
            prompt=prompt,
            prompt_2=prompt_2,
            depth_png=depth_png,
            negative_prompt=negative,
            seed=seed,
            # CN=0.9 now safe : the depth map encodes RDC + courant + attique
            # setback so the model can't drift to medieval / minimalist cube.
            controlnet_conditioning_scale=0.9,
            steps=50,
            width=2048,
            height=2048,
        )
    out = Path(f"/tmp/sdxl_{preset}_{seed}.png")
    out.write_bytes(png)
    print(f"✓ saved {len(png):,} bytes → {out}")
