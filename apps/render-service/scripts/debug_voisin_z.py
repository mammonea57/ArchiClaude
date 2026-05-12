"""Debug : check view_z range of voisins vs main building."""
from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.depth_map import _extrude_simple, _project_quads, camera_from_preset, extrude_footprint
from src.scene_mesh import clip_footprint_to_parcelle
from src.voisinage_mesh import (
    fetch_voisins_bdtopo,
    geocode_address,
    voisins_to_local_polygons,
)

PROJECT_ID = "e9a960c8-081f-4c42-a65b-619610a61134"
with urllib.request.urlopen(f"http://localhost:8000/api/v1/projects/{PROJECT_ID}/building_model") as r:
    bm = json.load(r)
m = bm["model_json"]
fp = [(p[0], p[1]) for p in m["envelope"]["footprint_geojson"]["coordinates"][0]]
parc = [(p[0], p[1]) for p in m["site"]["parcelle_geojson"]["coordinates"][0][:-1]]
h = float(m["envelope"]["hauteur_totale_m"])
cam = camera_from_preset(fp, h, "rue_se_eloignee")

clipped_rings = clip_footprint_to_parcelle(fp, parc)
def _ring_area(r):
    n = len(r); a = 0.0
    for i in range(n):
        x1, y1 = r[i]; x2, y2 = r[(i+1)%n]
        a += x1*y2 - x2*y1
    return abs(a)/2.0
clipped = max(clipped_rings, key=_ring_area)

origin = geocode_address("80 Rue des Héros Nogentais 94130 Nogent-sur-Marne")
cx = sum(p[0] for p in parc)/len(parc); cy = sum(p[1] for p in parc)/len(parc)
voisins = voisins_to_local_polygons(
    fetch_voisins_bdtopo(origin, radius_m=120.0), origin, (cx, cy),
    skip_overlap_with=clipped,
    camera_pos_xy=(cam.position[0], cam.position[1]),
    block_camera_sight=True, max_distance_m=70.0, min_height_m=4.0,
)
print(f"voisins after filter: {len(voisins)}")
print(f"camera pos: {cam.position}, target: {cam.target}, parcel center: ({cx:.1f},{cy:.1f})")

# Main building view_z range
main_z = []
for screen, view_z in _project_quads(extrude_footprint(clipped, h), cam):
    main_z.extend(view_z.tolist())
print(f"BUILDING view_z range: [{min(main_z):.2f}, {max(main_z):.2f}]  n={len(main_z)}")

# Voisin view_z range
voi_z = []
voi_centroids = []
for i, (vfp, vh) in enumerate(voisins):
    qs = _extrude_simple(vfp, vh)
    rcx = sum(p[0] for p in vfp)/len(vfp); rcy = sum(p[1] for p in vfp)/len(vfp)
    d_cam = ((rcx-cam.position[0])**2 + (rcy-cam.position[1])**2)**0.5
    voi_centroids.append((i, rcx, rcy, vh, d_cam))
    for screen, view_z in _project_quads(qs, cam):
        voi_z.extend(view_z.tolist())
print(f"VOISINS view_z range: [{min(voi_z):.2f}, {max(voi_z):.2f}]  n={len(voi_z)}")
print()
print("Sample voisin centroids :")
for i, rcx, rcy, vh, d_cam in sorted(voi_centroids, key=lambda x: x[4])[:8]:
    print(f"  v{i:2d}: ({rcx:7.1f},{rcy:7.1f}) h={vh:5.1f}m  dist_cam={d_cam:6.1f}m")
print(f"  ... (total {len(voi_centroids)})")
