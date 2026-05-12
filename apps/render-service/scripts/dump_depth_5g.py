"""Dump the Phase 5g depth map locally (no Modal call) for visual debug."""
from __future__ import annotations

import io
import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.depth_map import camera_from_preset, depth_to_pil, render_depth_map
from src.scene_mesh import (
    balcons_filants_quads,
    clip_footprint_to_parcelle,
    far_ground_quad,
    jardins_rdc_quads,
    pleine_terre_quads,
    rooftop_terrace_quads,
    voirie_strip_quads,
)
from src.depth_map import _polygon_inset
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
fp = model["envelope"]["footprint_geojson"]["coordinates"][0]
fp_xy = [(float(p[0]), float(p[1])) for p in fp]
h = float(model["envelope"].get("hauteur_totale_m", 17.0))
cam = camera_from_preset(fp_xy, h, PRESET)

parc = bm["model_json"]["site"]["parcelle_geojson"]["coordinates"][0]
parc_pts = [(p[0], p[1]) for p in parc[:-1]]

clipped_rings = clip_footprint_to_parcelle(fp_xy, parc_pts)
real_building_ring = max(clipped_rings, key=lambda r: _ring_area(r))
print(f"clipped footprint: {len(real_building_ring)} pts, area={_ring_area(real_building_ring):.0f}m² (raw fp={len(fp_xy)} pts)")
print(f"clipped ring sample: {real_building_ring[:3]}")
print(f"raw fp sample: {fp_xy[:3]}")
print(f"camera position: {cam.position}, target: {cam.target}")
print(f"parcelle bbox: x=[{min(p[0] for p in parc_pts):.1f},{max(p[0] for p in parc_pts):.1f}] y=[{min(p[1] for p in parc_pts):.1f},{max(p[1] for p in parc_pts):.1f}]")
print(f"clipped bbox:  x=[{min(p[0] for p in real_building_ring):.1f},{max(p[0] for p in real_building_ring):.1f}] y=[{min(p[1] for p in real_building_ring):.1f},{max(p[1] for p in real_building_ring):.1f}]")

voirie_sides = bm["model_json"]["site"].get("voirie_orientations") or ["sud"]
voirie_quads_list = voirie_strip_quads(parc_pts, voirie_sides, thickness_m=6.0)
print(f"voirie sides: {voirie_sides} → {len(voirie_quads_list)} quads")
pleine_terre_list = pleine_terre_quads(parc_pts, real_building_ring)
print(f"pleine terre: {len(pleine_terre_list)} fan-triangles")
niveaux = int(model["envelope"].get("niveaux") or 6)
h_rdc = float(model["envelope"].get("hauteur_rdc_m") or 3.5)
h_etage = float(model["envelope"].get("hauteur_etage_courant_m") or 2.7)
balcons_list = balcons_filants_quads(real_building_ring, voirie_sides,
                                     niveaux=niveaux, hauteur_rdc_m=h_rdc, hauteur_etage_m=h_etage)
print(f"balcons filants: {len(balcons_list)} quads")

voisins_polygons = []
try:
    with urllib.request.urlopen(f"http://localhost:8000/api/v1/projects/{PROJECT_ID}") as r:
        proj = json.load(r)
    address = proj.get("name") or "80 Rue des Héros Nogentais 94130 Nogent-sur-Marne"
    origin = geocode_address(address)
    cx_local = sum(p[0] for p in parc_pts) / len(parc_pts)
    cy_local = sum(p[1] for p in parc_pts) / len(parc_pts)
    feats = fetch_voisins_bdtopo(origin, radius_m=300.0)
    voisins_polygons = voisins_to_local_polygons(
        feats, origin, (cx_local, cy_local),
        skip_overlap_with=real_building_ring,
        camera_pos_xy=(cam.position[0], cam.position[1]),
        block_camera_sight=True,
        max_distance_m=200.0,
        min_height_m=4.0,
    )
    print(f"voisinage: {len(voisins_polygons)} buildings (filtered)")
except Exception as e:
    print(f"!! voisinage fetch failed ({e})")

jardins_list = jardins_rdc_quads(real_building_ring, voirie_sides)
print(f"cloisons jardins RDC: {len(jardins_list)} quads")
setback = _polygon_inset(real_building_ring, 1.5)
rooftop_list = rooftop_terrace_quads(setback, h) if len(setback) >= 3 else []
print(f"rooftop terrasse: {len(rooftop_list)} quads")
far_ground = []   # disabled (was polluting the z-buffer)
extra_all = voirie_quads_list + balcons_list + jardins_list + rooftop_list
depth = render_depth_map(real_building_ring, h, cam,
                         voisins=None,
                         extra_quads=extra_all or None,
                         background_quads=far_ground or None)
print(f"depth shape: {depth.shape}, range=[{depth.min():.2f},{depth.max():.2f}], mean={depth.mean():.2f}")
zero_pct = (depth == 0).sum() / depth.size * 100
print(f"zero pixels (sky/empty): {zero_pct:.1f}%")

depth_pil = depth_to_pil(depth)
out = Path(f"/tmp/debug_depth_5g_{PRESET}.png")
depth_pil.save(out, format="PNG")
print(f"✓ saved → {out}")
