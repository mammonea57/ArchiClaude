"""Generate a side-by-side comparison PNG : iter #320 FLUX baseline vs new render.

Useful to visually validate that UE5 (or any new pipeline output) is at least
on par with the baseline before declaring success.

Usage :
    python compare_side_by_side.py \\
        --new path/to/iter401_ue5.png \\
        [--baseline path/to/iter320_reference.png] \\
        --output path/to/comparison_iter401.png
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


def _draw_label(img: Image.Image, text: str, color: tuple[int, int, int]) -> None:
    """Paint a label band at the top of the image."""
    draw = ImageDraw.Draw(img)
    band_h = max(40, img.size[1] // 30)
    draw.rectangle([(0, 0), (img.size[0], band_h)], fill=color)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", band_h - 12)
    except Exception:
        font = ImageFont.load_default()
    draw.text((20, 6), text, fill=(255, 255, 255), font=font)


def make_comparison(new_png: Path, baseline_png: Path, output: Path,
                    target_height: int = 1080) -> None:
    new_img = Image.open(new_png).convert("RGB")
    base_img = Image.open(baseline_png).convert("RGB")

    # Resize both to same height
    def _resize(img: Image.Image) -> Image.Image:
        ratio = target_height / img.size[1]
        new_w = int(img.size[0] * ratio)
        return img.resize((new_w, target_height), Image.LANCZOS)

    new_resized = _resize(new_img)
    base_resized = _resize(base_img)

    # Add label bands (in place)
    _draw_label(base_resized, "BASELINE — iter #320 (FLUX)", (40, 80, 140))
    _draw_label(new_resized, f"NEW — {new_png.stem}", (40, 140, 60))

    # Concatenate horizontally with a 10px white spacer
    gap = 10
    total_w = base_resized.size[0] + new_resized.size[0] + gap
    out = Image.new("RGB", (total_w, target_height), color=(255, 255, 255))
    out.paste(base_resized, (0, 0))
    out.paste(new_resized, (base_resized.size[0] + gap, 0))
    output.parent.mkdir(parents=True, exist_ok=True)
    out.save(output, format="PNG", optimize=True)
    print(f"✓ Saved comparison → {output} ({output.stat().st_size:,} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--new", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, default=None,
                        help="Defaults to refs/baselines/iter-320/iter320_reference.png")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--target-height", type=int, default=1080)
    args = parser.parse_args()

    baseline = args.baseline or (
        Path(__file__).resolve().parent.parent.parent.parent
        / "refs" / "baselines" / "iter-320" / "iter320_reference.png"
    )
    make_comparison(args.new, baseline, args.output, args.target_height)


if __name__ == "__main__":
    main()
