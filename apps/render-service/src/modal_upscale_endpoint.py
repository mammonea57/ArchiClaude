"""Real-ESRGAN upscale endpoint — VRAI upscale net (interpole le détail, ne
RÉGÉNÈRE pas l'image, donc rien de perdu : opposé du refine FLUX qui aplatit).

Étape finale de la qualité "magazine/Pinterest" : prend un rendu MIR-tier 1024²
et le monte en 2048/4096² avec une netteté réelle (joints de pierre, tuiles,
ferronneries croustillants) sans toucher à la composition / lumière / personnages.

Usage local :
    .venv/bin/modal run src/modal_upscale_endpoint.py::upscale_cli \\
        --input-path refs/.../mir/xxx.png --out-path refs/.../xxx_4k.png --outscale 4
"""
from __future__ import annotations

import io
from pathlib import Path

import modal

app = modal.App("archfr-upscale")

# RealESRGAN_x4plus : modèle x4 généraliste, excellent sur l'architecture.
ESRGAN_URL = ("https://github.com/xinntao/Real-ESRGAN/releases/download/"
              "v0.1.0/RealESRGAN_x4plus.pth")

image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch==2.4.1",
        "torchvision==0.19.1",
        "spandrel==0.4.1",
        "pillow>=10.4",
        "numpy>=1.26,<2.0",
        "requests>=2.31",
    )
)

model_cache = modal.Volume.from_name("archfr-upscale-cache", create_if_missing=True)


@app.cls(
    image=image,
    gpu="A100-80GB",
    timeout=900,
    scaledown_window=120,
    volumes={"/cache": model_cache},
)
class Upscaler:
    @modal.enter()
    def load(self):
        import requests
        import torch
        from spandrel import ModelLoader

        weights = Path("/cache/RealESRGAN_x4plus.pth")
        if not weights.exists():
            print("→ downloading RealESRGAN_x4plus.pth …")
            r = requests.get(ESRGAN_URL, timeout=300)
            r.raise_for_status()
            weights.write_bytes(r.content)
            model_cache.commit()
        self.model = ModelLoader().load_from_file(str(weights)).cuda().eval()
        self.torch = torch
        print(f"✓ Real-ESRGAN loaded (scale x{self.model.scale})")

    def _tile_infer(self, t, tile=512, overlap=32):
        """Inférence par tuiles avec recouvrement (évite OOM + coutures)."""
        torch = self.torch
        _, _, H, W = t.shape
        s = self.model.scale
        out = torch.zeros((1, 3, H * s, W * s), device=t.device)
        wsum = torch.zeros_like(out)
        step = tile - overlap
        ys = list(range(0, max(1, H - overlap), step))
        xs = list(range(0, max(1, W - overlap), step))
        for y in ys:
            for x in xs:
                y2, x2 = min(y + tile, H), min(x + tile, W)
                y1, x1 = max(0, y2 - tile), max(0, x2 - tile)
                patch = t[:, :, y1:y2, x1:x2]
                with torch.no_grad():
                    up = self.model(patch).clamp(0, 1)
                out[:, :, y1 * s:y2 * s, x1 * s:x2 * s] += up
                wsum[:, :, y1 * s:y2 * s, x1 * s:x2 * s] += 1
        return out / wsum.clamp(min=1)

    @modal.method()
    def upscale(self, image_bytes: bytes, outscale: float = 4.0) -> bytes:
        import numpy as np
        import torch
        from PIL import Image

        im = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        arr = np.asarray(im).astype("float32") / 255.0
        t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0).cuda()
        print(f"→ upscaling {im.size} x{self.model.scale} (tiled) …")
        up = self._tile_infer(t)
        up = up.squeeze(0).permute(1, 2, 0).clamp(0, 1).cpu().numpy()
        out = Image.fromarray((up * 255).round().astype("uint8"))
        # outscale < model scale : redescendre proprement (ex. x4 modèle -> x2 voulu)
        target = (round(im.width * outscale), round(im.height * outscale))
        if out.size != target:
            out = out.resize(target, Image.LANCZOS)
        buf = io.BytesIO()
        out.save(buf, "PNG")
        print(f"✓ {im.size} → {out.size}")
        return buf.getvalue()


@app.local_entrypoint()
def upscale_cli(input_path: str, out_path: str, outscale: float = 4.0):
    src = Path(input_path)
    print(f"→ Real-ESRGAN upscale {src.name} x{outscale}")
    png = Upscaler().upscale.remote(src.read_bytes(), outscale=outscale)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(png)
    print(f"✓ saved {out} ({len(png):,} bytes)")
