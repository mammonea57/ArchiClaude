"""Dump multiple depth-map variants to isolate which mesh element breaks the render."""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.depth_map import camera_from_preset, depth_to_pil, render_depth_map
from src.scene_mesh import clip_footprint_to_parcelle, voirie_strip_quads
from src.voisinage_mesh import (
    fetch_voisins_bdtopo,
    geocode_address,
    voisins_to_local_polygons,
)


def _ring_area(ring):
    n = len(ring)
    a = 0.0
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        a += x1 * y2 - x2 * y1
    return abs(a) / 2.0


PROJECT_ID = "e9a960c8-081f-4c42-a65b-619610a61134"
PRESET = "rue_se_eloignee"

with urllib.request.urlopen(
    f"http://localhost:8000/api/v1/projects/{PROJECT_ID}/building_model"
) as r:
    bm = json.load(r)
model = bm.get("model_json", bm)
fp_raw = [(float(p[0]), float(p[1])) for p in model["envelope"]["footprint_geojson"]["coordinates"][0]]
h = float(model["envelope"].get("hauteur_totale_m", 17.0))
cam = camera_from_preset(fp_raw, h, PRESET)

parc = bm["model_json"]["site"]["parcelle_geojson"]["coordinates"][0]
parc_pts = [(p[0], p[1]) for p in parc[:-1]]

clipped_rings = clip_footprint_to_parcelle(fp_raw, parc_pts)
fp_clipped = max(clipped_rings, key=lambda r: _ring_area(r))

voirie_sides = bm["model_json"]["site"].get("voirie_orientations") or ["sud"]
voirie_quads = voirie_strip_quads(parc_pts, voirie_sides, thickness_m=6.0)

with urllib.request.urlopen(f"http://localhost:8000/api/v1/projects/{PROJECT_ID}") as r:
    proj = json.load(r)
address = proj.get("name") or "80 Rue des Héros Nogentais 94130 Nogent-sur-Marne"
origin = geocode_address(address)
cx_local = sum(p[0] for p in parc_pts) / len(parc_pts)
cy_local = sum(p[1] for p in parc_pts) / len(parc_pts)
feats = fetch_voisins_bdtopo(origin, radius_m=120.0)
voisins = voisins_to_local_polygons(
    feats, origin, (cx_local, cy_local),
    skip_overlap_with=fp_clipped,
    camera_pos_xy=(cam.position[0], cam.position[1]),
    block_camera_sight=True,
    max_distance_m=70.0,
    min_height_m=4.0,
)


def _dump(label, fp, voi, extra):
    d = render_depth_map(fp, h, cam, voisins=voi, extra_quads=extra)
    out = Path(f"/tmp/iso_{label}.png")
    depth_to_pil(d).save(out)
    print(f"{label:30s}  range=[{d.min():.2f},{d.max():.2f}] mean={d.mean():.3f}  → {out}")

print(f"camera position: {cam.position}, target: {cam.target}")
print(f"raw fp (n={len(fp_raw)}): bbox x=[{min(p[0] for p in fp_raw):.1f},{max(p[0] for p in fp_raw):.1f}] y=[{min(p[1] for p in fp_raw):.1f},{max(p[1] for p in fp_raw):.1f}]")
print(f"clipped fp (n={len(fp_clipped)}): bbox x=[{min(p[0] for p in fp_clipped):.1f},{max(p[0] for p in fp_clipped):.1f}] y=[{min(p[1] for p in fp_clipped):.1f},{max(p[1] for p in fp_clipped):.1f}]")
print(f"voirie quads: {len(voirie_quads)}, voisins: {len(voisins)}")
print()

_dump("A_raw_only",       fp_raw,     None,    None)
_dump("B_clipped_only",   fp_clipped, None,    None)
_dump("C_clipped+voirie", fp_clipped, None,    voirie_quads)
_dump("D_clipped+voisins",fp_clipped, voisins, None)
_dump("E_full",           fp_clipped, voisins, voirie_quads)
