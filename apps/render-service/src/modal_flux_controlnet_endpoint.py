"""FLUX + ControlNet-Depth — géométrie VERROUILLÉE + photo à fond.

Le probleme : FLUX img2img basse-strength preserve la geometrie MAIS garde le
look CGI ; haute-strength casse le look CGI MAIS reinvente la geometrie.
Solution : ControlNet-depth tient la geometrie EXACTE de notre rendu comme un
gabarit rigide, et FLUX GENERE une vraie photo (txt2img guide par depth) ->
realisme photo maximal SANS aucune invention de forme.

Pipeline : rendu 3D -> depth map (DPT) -> FluxControlNetPipeline(depth, prompt
photo, LoRA pierre v5) -> sortie photo, geometrie locked par le depth.

Usage local :
    .venv/bin/modal run src/modal_flux_controlnet_endpoint.py::cn_cli \\
        --input-path refs/.../base.png \\
        --prompt "a real photograph of an existing Paris apartment building ..." \\
        --cn-scale 0.6 --out-dir refs/.../cn_depth
"""
from __future__ import annotations

import io
from pathlib import Path

import modal

app = modal.App("archfr-flux-controlnet")

FLUX_DEV = "black-forest-labs/FLUX.1-dev"
# ControlNets purpose-built pour FLUX.1-dev (diffusers FluxControlNetModel)
CN_DEPTH = "jasperai/Flux.1-dev-Controlnet-Depth"   # masse (lock lache)
CN_CANNY = "InstantX/FLUX.1-dev-Controlnet-Canny"   # lignes exactes (lock serre)
DEPTH_MODEL = "Intel/dpt-large"   # estimateur de profondeur robuste (transformers)

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
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
        "opencv-python-headless>=4.9",
    )
)

hf_cache = modal.Volume.from_name("archfr-hf-cache", create_if_missing=True)
lora_cache = modal.Volume.from_name("archfr-lora-cache", create_if_missing=True)


@app.cls(
    image=image,
    gpu="A100-80GB",
    timeout=1200,
    scaledown_window=120,
    volumes={"/root/.cache/huggingface": hf_cache, "/cache": lora_cache},
    secrets=[modal.Secret.from_name("huggingface")],
)
class FluxDepthCN:
    @modal.enter()
    def load(self):
        import torch
        from diffusers import FluxControlNetModel, FluxControlNetPipeline
        from transformers import pipeline as hf_pipeline

        self.torch = torch
        print("→ loading FLUX ControlNet (depth + canny) …")
        self._cn = {
            "depth": FluxControlNetModel.from_pretrained(CN_DEPTH, torch_dtype=torch.bfloat16),
            "canny": FluxControlNetModel.from_pretrained(CN_CANNY, torch_dtype=torch.bfloat16),
        }
        self.pipe = FluxControlNetPipeline.from_pretrained(
            FLUX_DEV, controlnet=self._cn["depth"], torch_dtype=torch.bfloat16)
        self.pipe.to("cuda")
        self._cn["canny"].to("cuda")
        self.cur_cn = "depth"
        self.depth = hf_pipeline("depth-estimation", model=DEPTH_MODEL, device=0)
        self.loaded_lora = None
        print("✓ FLUX + ControlNet(depth+canny) + DPT loaded")

    def _control_image(self, im, control_type):
        from PIL import Image
        import numpy as np
        if control_type == "canny":
            import cv2
            arr = np.asarray(im.convert("L"))
            edges = cv2.Canny(arr, 80, 180)
            rgb = np.stack([edges] * 3, -1).astype("uint8")
            return Image.fromarray(rgb)
        # depth
        d = self.depth(im)["depth"]
        a = np.asarray(d).astype("float32")
        a = (a - a.min()) / (a.ptp() + 1e-6)
        return Image.fromarray((np.stack([a] * 3, -1) * 255).astype("uint8"))

    def _ensure_lora(self, lora_name: str):
        if self.loaded_lora == lora_name:
            return
        if self.loaded_lora is not None:
            try:
                self.pipe.unload_lora_weights()
            except Exception:
                pass
        if lora_name and lora_name.lower() not in ("none", "null", "skip"):
            self.pipe.load_lora_weights(str(Path("/cache/lora") / lora_name))
            print(f"[lora] loaded {lora_name}")
        self.loaded_lora = lora_name

    @modal.method()
    def render(self, image_bytes: bytes, prompt: str,
               control_type: str = "canny",
               lora_name: str = "archfr_flux_style_conditional_v5/epoch_1",
               cn_scale: float = 0.6, guidance_scale: float = 3.5,
               num_inference_steps: int = 30, seed: int = 1810,
               resolution: int = 1024) -> tuple[bytes, bytes]:
        import torch
        from PIL import Image

        if control_type != self.cur_cn:
            self.pipe.controlnet = self._cn[control_type]
            self.cur_cn = control_type
        self._ensure_lora(lora_name)
        init = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        if init.size != (resolution, resolution):
            init = init.resize((resolution, resolution), Image.LANCZOS)
        ctrl = self._control_image(init, control_type)

        gen = torch.Generator(device="cuda").manual_seed(seed)
        print(f"→ FLUX-CN {control_type} génération (cn_scale={cn_scale}, {resolution}²) …")
        out = self.pipe(
            prompt=prompt,
            control_image=ctrl,
            controlnet_conditioning_scale=cn_scale,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale,
            height=resolution, width=resolution,
            generator=gen,
        ).images[0]

        b1 = io.BytesIO(); out.save(b1, "PNG")
        b2 = io.BytesIO(); ctrl.save(b2, "PNG")   # carte de contrôle (visuel)
        return b1.getvalue(), b2.getvalue()


@app.local_entrypoint()
def cn_cli(input_path: str, prompt: str, control_type: str = "canny",
           lora_name: str = "archfr_flux_style_conditional_v5/epoch_1",
           cn_scale: float = 0.6, guidance_scale: float = 3.5,
           seed: int = 1810, resolution: int = 1024,
           out_dir: str = "refs/renders/flux_cn_depth"):
    import time
    src = Path(input_path)
    out = Path(out_dir); out.mkdir(parents=True, exist_ok=True)
    print(f"→ FLUX+ControlNet-{control_type} on {src.name} (cn_scale={cn_scale})")
    png, ctrl = FluxDepthCN().render.remote(
        src.read_bytes(), prompt=prompt, control_type=control_type,
        lora_name=lora_name, cn_scale=cn_scale, guidance_scale=guidance_scale,
        seed=seed, resolution=resolution)
    ts = time.strftime("%Y%m%d_%H%M%S")
    p = out / f"{ts}_{control_type}_cn{int(cn_scale*100):03d}_s{seed}.png"
    p.write_bytes(png)
    (out / f"{ts}_{control_type}_cn{int(cn_scale*100):03d}_s{seed}_CTRL.png").write_bytes(ctrl)
    print(f"✓ saved {p}")
