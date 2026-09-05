"""Zoomed top-down of the IMMEDIATE neighbours around 80 Rue des Héros.

Same data as preview_ign_context.py but :
  * only close voisins (<= max_distance_m, default 90 m)
  * tight crop (+/- half_window_m, default 70 m) then upscaled for legibility
  * each footprint annotated with its height (m)

Output : refs/renders/voisins_zoom_preview.png
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "render-service"))

from src.voisinage_mesh import GeoOrigin, voisins_from_ign_geojson

PROJECT_ID = "a3126a4f-bc96-40b0-a8db-89e1044765e7"
MAX_DIST_M = 90.0       # close neighbours only
HALF_WINDOW_M = 70.0    # crop half-width around parcelle
UPSCALE = 3             # enlarge the crop for legibility


def main() -> int:
    ctx_dir = REPO_ROOT / "refs" / "photogrammetry" / PROJECT_ID
    man = json.loads((ctx_dir / "build_context_manifest.json").read_text())
    origin = GeoOrigin(lat=man["lat"], lng=man["lng"])

    voisins = voisins_from_ign_geojson(
        project_id=PROJECT_ID,
        origin=origin,
        parcel_center_local=(0.0, 0.0),
        max_distance_m=MAX_DIST_M,
        min_height_m=1.5,
        max_height_m=45.0,
    )
    print(f"voisins proches (<= {MAX_DIST_M}m) : {len(voisins)}")

    ortho = Image.open(ctx_dir / "bdortho_macro.jpg").convert("RGBA")
    w, h = ortho.size
    half_m = 300.0
    px_per_m = w / (2 * half_m)

    def to_px(x: float, y: float) -> tuple[float, float]:
        return (w / 2 + x * px_per_m, h / 2 - y * px_per_m)

    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    labels: list[tuple[float, float, str]] = []

    for fp, height_m, z_base in voisins:
        if len(fp) < 3:
            continue
        pts = [to_px(p[0], p[1]) for p in fp]
        hn = max(0.0, min(1.0, (height_m - 2.0) / 25.0))
        r = int(80 + 175 * hn); g = int(40 + 200 * hn); b = int(40 + 30 * hn)
        draw.polygon(pts, fill=(r, g, b, 120), outline=(r, g, b, 255))
        cx = sum(p[0] for p in pts) / len(pts)
        cy = sum(p[1] for p in pts) / len(pts)
        labels.append((cx, cy, f"{height_m:.0f}m"))

    # parcelle cross
    cx0, cy0 = w / 2, h / 2
    draw.line([(cx0 - 18, cy0), (cx0 + 18, cy0)], fill=(0, 255, 120, 255), width=4)
    draw.line([(cx0, cy0 - 18), (cx0, cy0 + 18)], fill=(0, 255, 120, 255), width=4)

    composed = Image.alpha_composite(ortho, overlay).convert("RGB")

    # tight crop around centre
    hw_px = int(HALF_WINDOW_M * px_per_m)
    box = (int(cx0 - hw_px), int(cy0 - hw_px), int(cx0 + hw_px), int(cy0 + hw_px))
    crop = composed.crop(box)
    cw, ch = crop.size
    crop = crop.resize((cw * UPSCALE, ch * UPSCALE), Image.LANCZOS)

    # draw height labels on the upscaled crop
    d2 = ImageDraw.Draw(crop)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 22)
    except Exception:
        font = ImageFont.load_default()
    for lx, ly, txt in labels:
        nx = (lx - box[0]) * UPSCALE
        ny = (ly - box[1]) * UPSCALE
        if 0 <= nx <= cw * UPSCALE and 0 <= ny <= ch * UPSCALE:
            d2.text((nx + 1, ny + 1), txt, fill=(0, 0, 0), font=font)
            d2.text((nx, ny), txt, fill=(255, 255, 255), font=font)

    # scale bar (20 m)
    bar_px = int(20 * px_per_m * UPSCALE)
    bx, by = 20, ch * UPSCALE - 30
    d2.rectangle([bx, by, bx + bar_px, by + 6], fill=(255, 255, 255))
    d2.text((bx, by - 24), "20 m", fill=(255, 255, 255), font=font)

    out = REPO_ROOT / "refs" / "renders" / "voisins_zoom_preview.png"
    crop.save(out, "PNG")
    print(f"✓ {out}  ({len(labels)} voisins labelled, window +/-{HALF_WINDOW_M:.0f}m)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
