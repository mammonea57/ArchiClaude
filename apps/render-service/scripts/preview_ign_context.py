"""Quick visual sanity-check for Jour 4 IGN context.

Renders a top-down preview PNG that overlays the BDTOPO LOD2 voisin footprints
(extruded heights shown as fill colour brightness) on top of the BD ORTHO
macro JPG. Lets us confirm visually that :
  * voisins land on real building footprints in the aerial photo
  * heights vary realistically (no flat carpet of identical voisins)
  * the parcelle centroid sits at the centre of the ortho

Output : refs/renders/test_jour4_ign_context_preview.png
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "render-service"))

from src.voisinage_mesh import (
    GeoOrigin,
    voisins_from_ign_geojson,
)

PROJECT_ID = "a3126a4f-bc96-40b0-a8db-89e1044765e7"


def main() -> int:
    ctx_dir = REPO_ROOT / "refs" / "photogrammetry" / PROJECT_ID
    man = json.loads((ctx_dir / "build_context_manifest.json").read_text())
    lat0, lng0 = man["lat"], man["lng"]
    origin = GeoOrigin(lat=lat0, lng=lng0)

    # Use parcelle centroid in local meters as (0,0) reference for the preview.
    # We need to project the parcelle centroid → local meters via the same
    # origin. For the smoke check we just centre on the geocoded address.
    voisins = voisins_from_ign_geojson(
        project_id=PROJECT_ID,
        origin=origin,
        parcel_center_local=(0.0, 0.0),
        max_distance_m=350.0,
        min_height_m=1.5,
        max_height_m=45.0,
    )
    print(f"voisins : {len(voisins)}")

    ortho = Image.open(ctx_dir / "bdortho_macro.jpg").convert("RGBA")
    w, h = ortho.size
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    half_m = 300.0  # bdortho_macro is 600m wide
    px_per_m = w / (2 * half_m)

    def to_px(x: float, y: float) -> tuple[float, float]:
        # ortho image : +x right, +y down ; scene : +x east, +y north.
        # The image bbox is centred on the geocoded (lng0, lat0); +x east
        # maps to +px x ; +y north maps to -px y.
        return (w / 2 + x * px_per_m, h / 2 - y * px_per_m)

    drawn = 0
    for fp, height_m, z_base in voisins:
        if len(fp) < 3:
            continue
        pts = [to_px(p[0], p[1]) for p in fp]
        # Fill colour from height : low = dark red, tall = bright yellow.
        h_norm = max(0.0, min(1.0, (height_m - 2.0) / 25.0))
        r = int(80 + 175 * h_norm)
        g = int(40 + 200 * h_norm)
        b = int(40 + 30 * h_norm)
        fill = (r, g, b, 140)
        line = (r, g, b, 230)
        draw.polygon(pts, fill=fill, outline=line)
        drawn += 1
    print(f"drawn polygons : {drawn}")

    # Mark the centre (parcelle) with a thick yellow cross.
    cx, cy = w / 2, h / 2
    draw.line([(cx - 25, cy), (cx + 25, cy)], fill=(255, 240, 0, 255), width=5)
    draw.line([(cx, cy - 25), (cx, cy + 25)], fill=(255, 240, 0, 255), width=5)

    composed = Image.alpha_composite(ortho, overlay).convert("RGB")
    out = REPO_ROOT / "refs" / "renders" / "test_jour4_ign_context_preview.png"
    composed.save(out, "PNG")
    print(f"✓ Preview saved → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
