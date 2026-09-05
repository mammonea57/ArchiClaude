"""Test : generate a Nogent USDA scene with the FULL voisinage (50-200 buildings)
using the cached BDTOPO geojson at refs/photogrammetry/nogent/.

Background
----------
The legacy modal_blender pipeline calls `voisins_to_local_polygons` with
aggressive depth-map filters (`block_camera_sight=True`,
`forward_cone_cos=0.25` ≈ ±75° cone, `min_camera_distance_ratio=0.90` that
drops the entire foreground). Combined with `max_distance_m=100.0`, this
killed all but 2-3 voisins in the final render — destroying the "implantation
paysagère" needed for €5-50M decisions.

This script consumes the cached `refs/photogrammetry/nogent/bdtopo_buildings.geojson`
(873 BDTOPO features in a 300 m radius around the T-junction
Rue de Plaisance × Rue des Héros, Nogent-sur-Marne) and feeds the relaxed
filter knobs introduced in voisinage_mesh.py :

  forward_cone_cos          = -1.0  (keep every direction — Cycles renders full 360°)
  min_camera_distance_ratio = 0.0   (keep foreground voisins, they ARE the context)
  max_distance_m            = 120.0 (wider radius than the 100 m legacy default)
  min_height_m              = 2.5   (include single-storey annexes / sheds)
  max_voisin_count          = 200   (hard cap so Cycles perf stays sane)

Output : `refs/renders/test_nogent_voisinage_v2/scene_rue_streetview_seed11.usda`

Run from repo root :
    apps/render-service/.venv/bin/python apps/render-service/scripts/test_nogent_voisinage_v2.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "render-service"))

from src.scene_to_usd import export_scene_to_usda
from src.scene_mesh import _extrude_simple  # noqa: F401  (re-used below)
from src.voisinage_mesh import (
    GeoOrigin,
    voisins_to_local_polygons,
)


# Camera preset (mirrors `rue_streetview` from depth_map.py — eye-level on
# the cadastral street, looking at the project parcel).
CAMERA_FOV_DEG = 70.0
CAMERA_POSITION = (-17.689184538565573, 56.65797265014797, 1.7)
CAMERA_TARGET = (15.99693066085456, 17.728811123408377, 6.0)

# Cached geojson : 873 BDTOPO V3 features around the Nogent T-junction
# (Rue de Plaisance × Rue des Héros, 94130 Nogent-sur-Marne). The reference
# Street View shot used to drive the FLUX target lives at this T-junction
# (see MEMORY.md → project_nogent_streetview_reference). The legacy BAN
# geocode for "80 Rue des Héros Nogentais" drifts ~1.1 km from this bbox,
# so we use the GeoJSON's natural centroid as the local frame origin.
NOGENT_GEOJSON = REPO_ROOT / "refs" / "photogrammetry" / "nogent" / "bdtopo_buildings.geojson"


def _extrude_box(footprint, height_m: float):
    """Mirror of `_extrude_simple` from scene_mesh — duplicate here to avoid
    pulling the heavy scene_mesh import graph (which depends on BuildingModel
    schemas, sqlalchemy, etc.). Generates 4-vert quads, no roof triangulation
    needed for context buildings."""
    pts = list(footprint)
    # Remove consecutive duplicates
    deduped = []
    for p in pts:
        if not deduped or (abs(p[0] - deduped[-1][0]) > 1e-6 or abs(p[1] - deduped[-1][1]) > 1e-6):
            deduped.append(p)
    if len(deduped) >= 2 and deduped[0] == deduped[-1]:
        deduped.pop()
    n = len(deduped)
    if n < 3:
        return []
    z0, z1 = 0.0, float(height_m)
    quads = []
    # Side walls
    for i in range(n):
        a = deduped[i]
        b = deduped[(i + 1) % n]
        quads.append((
            (a[0], a[1], z0),
            (b[0], b[1], z0),
            (b[0], b[1], z1),
            (a[0], a[1], z1),
        ))
    # Flat roof as a fan of quads (degenerate at apex for triangles is ok in USDA).
    # We emit n-2 quads by using the polygon's first vertex as the anchor.
    if n >= 4:
        for i in range(1, n - 2):
            quads.append((
                (deduped[0][0], deduped[0][1], z1),
                (deduped[i][0], deduped[i][1], z1),
                (deduped[i + 1][0], deduped[i + 1][1], z1),
                (deduped[i + 2][0], deduped[i + 2][1], z1),
            ))
    elif n == 3:
        # Triangle roof : emit as a degenerate quad (last vertex repeated).
        quads.append((
            (deduped[0][0], deduped[0][1], z1),
            (deduped[1][0], deduped[1][1], z1),
            (deduped[2][0], deduped[2][1], z1),
            (deduped[2][0], deduped[2][1], z1),
        ))
    return quads


def main() -> int:
    t0 = time.time()
    print("─── Nogent voisinage v2 — relaxed filters ───")
    print(f"  geojson : {NOGENT_GEOJSON}")
    if not NOGENT_GEOJSON.is_file():
        print(f"!! Missing geojson {NOGENT_GEOJSON}")
        return 2

    # 1) Load cached BDTOPO features (no live WFS call — geocode + the GeoJSON
    #    were captured together by build_context).
    with open(NOGENT_GEOJSON, "r", encoding="utf-8") as f:
        gj = json.load(f)
    features = list(gj.get("features", []))
    print(f"  cached features : {len(features)}")

    # 2) Derive the local-frame origin from the GeoJSON's vertex bbox centroid
    #    (= the T-junction the geojson was captured around). This avoids the
    #    1.1 km drift of the public BAN geocoder for this address.
    all_xs: list[float] = []
    all_ys: list[float] = []
    for feat in features:
        coords = feat.get("geometry", {}).get("coordinates", []) or []
        if feat.get("geometry", {}).get("type") == "MultiPolygon":
            for poly in coords:
                for ring in poly:
                    for pt in ring:
                        all_xs.append(pt[0]); all_ys.append(pt[1])
        elif feat.get("geometry", {}).get("type") == "Polygon":
            for ring in coords:
                for pt in ring:
                    all_xs.append(pt[0]); all_ys.append(pt[1])
    if not all_xs:
        print("!! GeoJSON has no readable coordinates")
        return 4
    origin_lng = (min(all_xs) + max(all_xs)) / 2.0
    origin_lat = (min(all_ys) + max(all_ys)) / 2.0
    origin = GeoOrigin(lat=origin_lat, lng=origin_lng)
    print(f"  origin lat/lng : ({origin.lat:.6f}, {origin.lng:.6f}) — geojson bbox centroid")

    # 3) The legacy scene puts the project building at local (0, 0). We use
    #    that as the parcel centre. `skip_overlap_with` is the parcel ring —
    #    we pass a tiny synthetic square (±10 m) so the "own building" filter
    #    (d_proj < 5 m) still kills the parcel itself but everything else
    #    survives.
    parcel_center = (0.0, 0.0)
    skip_ring = [(-10.0, -10.0), (10.0, -10.0), (10.0, 10.0), (-10.0, 10.0)]

    # 4) RELAXED filters — keep voisins regardless of camera frustum so
    #    the Cycles render shows the real urban context.
    pairs = voisins_to_local_polygons(
        features,
        origin,
        parcel_center,
        skip_overlap_with=skip_ring,
        camera_pos_xy=(CAMERA_POSITION[0], CAMERA_POSITION[1]),
        block_camera_sight=False,           # full-context mode : keep every direction
        max_distance_m=120.0,               # ~120 m radius around parcel
        min_height_m=2.5,                   # include 1-storey annexes / sheds
        max_height_m=25.0,                  # cap skyscrapers (none here, defensive)
        forward_cone_cos=-1.0,              # accept any direction (incl. behind cam)
        min_camera_distance_ratio=0.0,      # do not drop foreground voisins
        max_voisin_count=200,               # hard cap so Cycles perf stays sane
    )
    print(f"  voisins kept : {len(pairs)} (of {len(features)} cached features)")

    # 5) Build quads_by_material with EXACTLY the same material name the
    #    modal_blender pipeline uses ("voisin"), so downstream consumers
    #    (UE5 import, Cycles materials) keep working unchanged.
    quads_by_mat: dict[str, list] = {"voisin": []}
    voisin_count_with_quads = 0
    for footprint, h in pairs:
        quads = _extrude_box(footprint, h)
        if quads:
            quads_by_mat["voisin"].extend(quads)
            voisin_count_with_quads += 1
    print(
        f"  voisin meshes  : {voisin_count_with_quads} buildings "
        f"({len(quads_by_mat['voisin'])} quads total)"
    )

    if not quads_by_mat["voisin"]:
        print("!! No voisin quads produced — aborting USDA export.")
        return 3

    # 6) Export the USDA — re-use the unchanged scene_to_usd interface.
    out_dir = REPO_ROOT / "refs" / "renders" / "test_nogent_voisinage_v2"
    out_dir.mkdir(parents=True, exist_ok=True)
    usda_path = out_dir / "scene_rue_streetview_seed11.usda"

    text = export_scene_to_usda(
        quads_by_material=quads_by_mat,
        camera_position=CAMERA_POSITION,
        camera_target=CAMERA_TARGET,
        camera_fov_deg=CAMERA_FOV_DEG,
        sun_direction=(0.4, -0.6, 0.7),
        sun_energy=5.0,
        output_path=usda_path,
        context_source="bdtopo_legacy",
    )
    print(f"  USDA written : {usda_path} ({usda_path.stat().st_size:,} bytes)")

    # 7) Quick validation : grep USDA for expected prims + count unique
    #    voisin building footprints by parsing face-counts of the "voisin"
    #    mesh prim.
    m = re.search(r'def Mesh "voisin"\s*\{(.*?)(?=\n\s*def Mesh|\n\s*\})', text, re.DOTALL)
    if not m:
        print("!! could not find voisin mesh in USDA text")
        return 4
    block = m.group(1)
    fc_match = re.search(r"int\[\] faceVertexCounts = \[(.*?)\]", block, re.DOTALL)
    n_faces = len(fc_match.group(1).split(",")) if fc_match else 0

    print("\n─── Verification ───")
    print(f"  USDA voisin Mesh prim : 1 (legacy structure preserved)")
    print(f"  USDA voisin faces     : {n_faces}")
    print(f"  Unique voisin buildings (= meshes) : {voisin_count_with_quads}")
    print(f"  Duration : {time.time() - t0:.1f} s")

    if voisin_count_with_quads < 30:
        print(f"!! Only {voisin_count_with_quads} voisins — expected > 30. FAIL.")
        return 5

    print(f"\n  ✓ PASS — {voisin_count_with_quads} voisins (> 30 target)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
