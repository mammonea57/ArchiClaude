"""Merge the FULL Nogent voisinage (relaxed filters, ~200 buildings) into the
carrefour_se render config, REPLACING its sparse 65-quad voisin set so the
ControlNet polish can no longer hallucinate background neighbours.

Safety: before merging, verify the newly-built voisins share the same local
frame as the config's EXISTING voisin quads (compare XY bbox/centroid). If they
don't overlap, abort — a frame mismatch would scatter neighbours wrongly.

$0 — pure geometry, no GPU. Writes A_VISIBLE__carrefour_se_FULLVOISINS.json.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "render-service"))

from src.voisinage_mesh import GeoOrigin, voisins_to_local_polygons

CONFIG = REPO_ROOT / "refs/concept/nogent_80_heros_3_scenarios/configs_blender_v2/A_VISIBLE__carrefour_se.json"
GEOJSON = REPO_ROOT / "refs/photogrammetry/nogent/bdtopo_buildings.geojson"
OUT = CONFIG.parent / "A_VISIBLE__carrefour_se_FULLVOISINS.json"


def _extrude_box(footprint, height_m: float):
    pts = list(footprint)
    dd = []
    for p in pts:
        if not dd or abs(p[0]-dd[-1][0]) > 1e-6 or abs(p[1]-dd[-1][1]) > 1e-6:
            dd.append(p)
    if len(dd) >= 2 and dd[0] == dd[-1]:
        dd.pop()
    n = len(dd)
    if n < 3:
        return []
    z0, z1 = 0.0, float(height_m)
    q = []
    for i in range(n):
        a = dd[i]; b = dd[(i+1) % n]
        q.append([[a[0],a[1],z0],[b[0],b[1],z0],[b[0],b[1],z1],[a[0],a[1],z1]])
    if n >= 4:
        for i in range(1, n-2):
            q.append([[dd[0][0],dd[0][1],z1],[dd[i][0],dd[i][1],z1],
                      [dd[i+1][0],dd[i+1][1],z1],[dd[i+2][0],dd[i+2][1],z1]])
    elif n == 3:
        q.append([[dd[0][0],dd[0][1],z1],[dd[1][0],dd[1][1],z1],
                  [dd[2][0],dd[2][1],z1],[dd[2][0],dd[2][1],z1]])
    return q


def _bbox(quads):
    xs = [v[0] for qd in quads for v in qd]
    ys = [v[1] for qd in quads for v in qd]
    return (min(xs), min(ys), max(xs), max(ys),
            sum(xs)/len(xs), sum(ys)/len(ys))


def main() -> int:
    cfg = json.loads(CONFIG.read_text())
    existing = cfg["quads_by_material"].get("voisin", [])
    print(f"config existing voisin quads : {len(existing)}")
    ex = _bbox(existing)
    print(f"  existing bbox x[{ex[0]:.0f},{ex[2]:.0f}] y[{ex[1]:.0f},{ex[3]:.0f}] centroid=({ex[4]:.0f},{ex[5]:.0f})")

    gj = json.loads(GEOJSON.read_text())
    feats = list(gj.get("features", []))
    xs = []; ys = []
    for f in feats:
        g = f.get("geometry", {}); t = g.get("type"); c = g.get("coordinates", []) or []
        if t == "MultiPolygon":
            for poly in c:
                for ring in poly:
                    for pt in ring:
                        xs.append(pt[0]); ys.append(pt[1])
        elif t == "Polygon":
            for ring in c:
                for pt in ring:
                    xs.append(pt[0]); ys.append(pt[1])
    origin = GeoOrigin(lat=(min(ys)+max(ys))/2, lng=(min(xs)+max(xs))/2)

    cam = cfg["camera_pos"]
    pairs = voisins_to_local_polygons(
        feats, origin, (0.0, 0.0),
        skip_overlap_with=[(-10,-10),(10,-10),(10,10),(-10,10)],
        camera_pos_xy=(cam[0], cam[1]),
        block_camera_sight=True,            # drop voisins occluding camera->building sightline
        max_distance_m=120.0, min_height_m=2.5,
        max_height_m=25.0, forward_cone_cos=-1.0,
        min_camera_distance_ratio=0.35,     # drop voisins too close to camera (foreground occluders)
        max_voisin_count=200,
    )
    full = []
    for fp, h in pairs:
        full.extend(_extrude_box(fp, h))
    print(f"new full voisin quads : {len(full)} ({len(pairs)} buildings)")
    nb = _bbox(full)
    print(f"  new bbox x[{nb[0]:.0f},{nb[2]:.0f}] y[{nb[1]:.0f},{nb[3]:.0f}] centroid=({nb[4]:.0f},{nb[5]:.0f})")

    # alignment check : existing centroid must sit inside new bbox + centroids close
    inside = nb[0]-20 <= ex[4] <= nb[2]+20 and nb[1]-20 <= ex[5] <= nb[3]+20
    dcent = ((ex[4]-nb[4])**2 + (ex[5]-nb[5])**2) ** 0.5
    print(f"  alignment: existing_centroid_inside_new_bbox={inside}  centroid_dist={dcent:.0f}m")
    if not inside or dcent > 80:
        print("!! FRAME MISMATCH — aborting, not writing config. Voisins would scatter.")
        return 5

    merged = dict(cfg)
    qbm = dict(cfg["quads_by_material"])
    qbm["voisin"] = full
    merged["quads_by_material"] = qbm
    OUT.write_text(json.dumps(merged))
    print(f"✓ aligned. wrote {OUT.name} (voisin 65→{len(full)} quads, frame OK)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
