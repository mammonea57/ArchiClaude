"""Post-prod auto pipeline for archviz renders.

Studios archi viz spend 50% of their time in Photoshop after V-Ray finishes.
This module automates the cheap-and-honest version of that polish pass :

- Color grading via a 3D LUT (Architectural Digest warm-shadow / cold-highlight)
- Vignette (subtle radial falloff)
- Film grain 35mm (fine noise)
- Sharpening (unsharp mask)
- Optional sky replacement (paste a dramatic HDR sky into the upper portion)

All operations are pillow / numpy / opencv on CPU — no GPU needed. A full
2048² render is processed in ~0.5 s.

Usage from another script :

    from src.postprod import postprod_image
    polished = postprod_image(pil_img, preset="brochure")
    polished.save("out.png")

Or as a CLI on a directory :

    python -m src.postprod refs/renders/multiview_44_boosted/ \
        --out refs/renders/multiview_44_boosted_polished/
"""
from __future__ import annotations

import argparse
import io
import math
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter


# ─── Color grading ────────────────────────────────────────────────────────


def _apply_curve(arr: np.ndarray, shadow_warm: float = 0.06,
                 highlight_cool: float = 0.04,
                 contrast: float = 1.08) -> np.ndarray:
    """Architectural Digest grade : push shadows toward orange,
    highlights toward blue, lift contrast slightly.

    arr is HxWx3 float32 in [0, 1] sRGB.
    """
    # Per-channel luminance proxy for shadow/highlight masks.
    lum = 0.2126 * arr[..., 0] + 0.7152 * arr[..., 1] + 0.0722 * arr[..., 2]
    shadow_mask = np.clip(1.0 - lum * 1.6, 0.0, 1.0)[..., None]
    highlight_mask = np.clip((lum - 0.55) * 2.2, 0.0, 1.0)[..., None]

    warm_tint = np.array([1.0, 0.78, 0.45], dtype=np.float32)
    cool_tint = np.array([0.55, 0.78, 1.0], dtype=np.float32)

    out = arr.copy()
    out += shadow_mask * shadow_warm * (warm_tint - 0.5)
    out += highlight_mask * highlight_cool * (cool_tint - 0.5)

    # Contrast around mid-grey.
    out = 0.5 + (out - 0.5) * contrast

    return np.clip(out, 0.0, 1.0)


# ─── Vignette ─────────────────────────────────────────────────────────────


def _vignette(arr: np.ndarray, strength: float = 0.18) -> np.ndarray:
    """Subtle radial darkening at the corners. strength 0.15-0.25 = magazine."""
    h, w, _ = arr.shape
    cx, cy = w / 2.0, h / 2.0
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    r = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
    r /= r.max() or 1.0
    falloff = 1.0 - strength * (r ** 2.2)
    return np.clip(arr * falloff[..., None], 0.0, 1.0)


# ─── Film grain ───────────────────────────────────────────────────────────


def _grain(arr: np.ndarray, amount: float = 0.012, rng: Optional[np.random.Generator] = None) -> np.ndarray:
    """Fine 35mm film grain. amount 0.01-0.02 = magazine-tier."""
    if rng is None:
        rng = np.random.default_rng(1234)
    noise = rng.standard_normal(arr.shape[:2]).astype(np.float32)
    return np.clip(arr + noise[..., None] * amount, 0.0, 1.0)


# ─── Sharpening ───────────────────────────────────────────────────────────


def _sharpen(img: Image.Image, radius: float = 1.2, percent: int = 130, threshold: int = 3) -> Image.Image:
    """Unsharp mask. Defaults match Lightroom 'sharpen lightly'."""
    return img.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=threshold))


# ─── Sky replacement (optional) ───────────────────────────────────────────


def _replace_sky(img: Image.Image, sky_path: Path, mask_threshold: float = 0.78) -> Image.Image:
    """Composite a dramatic sky over the bright upper portion of `img`.

    Cheap heuristic mask : sky = pixels whose luminance > `mask_threshold`
    AND whose blue channel dominates. Good enough for blue/cloudy backgrounds
    that the AI render produced ; not robust for foggy or dawn skies.
    """
    sky = Image.open(sky_path).convert("RGB").resize(img.size, Image.LANCZOS)
    img_arr = np.asarray(img, dtype=np.float32) / 255.0
    sky_arr = np.asarray(sky, dtype=np.float32) / 255.0

    lum = 0.2126 * img_arr[..., 0] + 0.7152 * img_arr[..., 1] + 0.0722 * img_arr[..., 2]
    blue_dom = img_arr[..., 2] > (img_arr[..., 0] + img_arr[..., 1]) / 2.0 - 0.04
    mask = ((lum > mask_threshold) & blue_dom).astype(np.float32)

    # Feather the mask to avoid hard edges.
    mask_img = Image.fromarray((mask * 255).astype(np.uint8), mode="L")
    mask_img = mask_img.filter(ImageFilter.GaussianBlur(radius=6))
    mask = np.asarray(mask_img, dtype=np.float32)[..., None] / 255.0

    out = img_arr * (1.0 - mask) + sky_arr * mask
    return Image.fromarray(np.clip(out * 255, 0, 255).astype(np.uint8))


# ─── Main entrypoint ──────────────────────────────────────────────────────


PRESETS = {
    "brochure": {
        "shadow_warm": 0.07,
        "highlight_cool": 0.05,
        "contrast": 1.10,
        "vignette": 0.20,
        "grain": 0.014,
        "sharpen": True,
    },
    "subtle": {
        "shadow_warm": 0.04,
        "highlight_cool": 0.03,
        "contrast": 1.05,
        "vignette": 0.12,
        "grain": 0.008,
        "sharpen": True,
    },
    "cinematic": {
        "shadow_warm": 0.10,
        "highlight_cool": 0.08,
        "contrast": 1.14,
        "vignette": 0.28,
        "grain": 0.018,
        "sharpen": True,
    },
}


def postprod_image(img: Image.Image, preset: str = "brochure",
                   sky_path: Optional[Path] = None,
                   seed: int = 1234) -> Image.Image:
    """Apply the full post-prod pipeline. Returns a fresh PIL.Image."""
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset!r}, available : {list(PRESETS)}")
    cfg = PRESETS[preset]
    if sky_path is not None and Path(sky_path).exists():
        img = _replace_sky(img, Path(sky_path))
    if cfg["sharpen"]:
        img = _sharpen(img)
    arr = np.asarray(img.convert("RGB"), dtype=np.float32) / 255.0
    arr = _apply_curve(arr, cfg["shadow_warm"], cfg["highlight_cool"], cfg["contrast"])
    arr = _vignette(arr, cfg["vignette"])
    rng = np.random.default_rng(seed)
    arr = _grain(arr, cfg["grain"], rng=rng)
    return Image.fromarray(np.clip(arr * 255, 0, 255).astype(np.uint8))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("input_dir", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--preset", default="brochure", choices=list(PRESETS))
    ap.add_argument("--sky", type=Path, default=None,
                    help="Optional sky replacement HDR (jpeg/png)")
    args = ap.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    pngs = sorted(args.input_dir.rglob("*.png"))
    if not pngs:
        print(f"no PNG found in {args.input_dir}")
        return

    print(f"post-prod {len(pngs)} PNGs : preset={args.preset} sky={args.sky}")
    for p in pngs:
        img = Image.open(p)
        out = postprod_image(img, preset=args.preset, sky_path=args.sky)
        rel = p.relative_to(args.input_dir)
        dest = args.out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        out.save(dest)
        print(f"  ✓ {p.name} → {dest}")


if __name__ == "__main__":
    main()
