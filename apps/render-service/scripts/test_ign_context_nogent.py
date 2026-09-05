"""Jour 4 — end-to-end smoke test for the IGN photogrammetry context.

Builds a USDA scene for Nogent (project a3126a4f-bc96-40b0-a8db-89e1044765e7)
using `context_source="ign_photogrammetry"`. The scene contains :
  * Real BDTOPO V3 LOD2 voisins extruded from per-vertex z (~900 buildings)
  * A flat BD ORTHO macro JPG quad acting as the sol (600 m × 600 m)
  * A Vegetation Xform pointing at the cached LiDAR HD high_vegetation LAZ
    (or the remote LiDAR HD URL when the LAZ isn't on disk)

Outputs :
  * refs/renders/test_jour4_ign_context.usda
  * refs/renders/test_jour4_ign_context_report.md (counts + issues)

Run from repo root :
    apps/render-service/.venv/bin/python apps/render-service/scripts/test_ign_context_nogent.py
"""
from __future__ import annotations

import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "apps" / "render-service"))

from src.scene_to_usd import export_scene_to_usda
from src.scene_mesh import (
    extruded_voisin_quads_with_base,
    voisin_quads_from_context_source,
)


PROJECT_ID = "a3126a4f-bc96-40b0-a8db-89e1044765e7"


def fetch_parcelle_from_db() -> tuple[list[tuple[float, float]], tuple[float, float]]:
    """Read parcelle WGS84 coords from Postgres (SELECT only, no mutation).

    Returns the outer ring of the first parcelle + its centroid (lng, lat).
    """
    cmd = [
        "docker", "exec", "archiclaude-postgres", "psql",
        "-U", "archiclaude", "-d", "archiclaude",
        "-tA", "-c",
        f"SELECT brief->'parcelles_selectionnees'->0->'geometry'->'coordinates' "
        f"FROM projects WHERE id = '{PROJECT_ID}' LIMIT 1;",
    ]
    out = subprocess.check_output(cmd, timeout=15).decode("utf-8").strip()
    # Result is a JSON-ish text — for MultiPolygon coords it's [[[ring]]]
    coords = json.loads(out)
    # MultiPolygon: coords = [[[[lng,lat], ...]]] ; take outer ring of poly 0.
    ring = coords[0][0]
    lngs = [p[0] for p in ring]
    lats = [p[1] for p in ring]
    centroid_lng = sum(lngs) / len(lngs)
    centroid_lat = sum(lats) / len(lats)
    return [(p[0], p[1]) for p in ring], (centroid_lng, centroid_lat)


def wgs84_ring_to_local(
    ring_lnglat: list[tuple[float, float]],
    origin_lng: float,
    origin_lat: float,
) -> list[tuple[float, float]]:
    """Project parcelle WGS84 ring to local meters centred on the origin."""
    cos_lat = math.cos(math.radians(origin_lat))
    out = []
    for lng, lat in ring_lnglat:
        dx = (lng - origin_lng) * 111320.0 * cos_lat
        dy = (lat - origin_lat) * 111320.0
        out.append((dx, dy))
    return out


def main() -> int:
    t0 = time.time()
    print("─── Jour 4 — IGN context end-to-end smoke test ───")
    print(f"  project_id = {PROJECT_ID}")

    # 1) Verify cached IGN context exists
    ctx_dir = REPO_ROOT / "refs" / "photogrammetry" / PROJECT_ID
    manifest = ctx_dir / "build_context_manifest.json"
    geojson = ctx_dir / "bdtopo_buildings.geojson"
    ortho_macro = ctx_dir / "bdortho_macro.jpg"
    if not manifest.is_file():
        print(f"!! Missing manifest at {manifest} — run build_context first.")
        return 2
    if not geojson.is_file():
        print(f"!! Missing geojson at {geojson} — run build_context first.")
        return 2
    man = json.loads(manifest.read_text())
    print(
        f"  cached IGN context found : "
        f"{man['bdtopo_building_count_valid']} valid + "
        f"{man['bdtopo_building_count_sentinel']} sentinels (z_range={man['bdtopo_z_range_m']})"
    )

    # 2) Parcelle + centroid from DB
    try:
        parc_wgs, (lng0, lat0) = fetch_parcelle_from_db()
        print(f"  parcelle centroid : ({lat0:.6f}, {lng0:.6f}) — {len(parc_wgs)} vertices")
    except Exception as e:
        print(f"!! DB read failed ({e}); falling back to manifest centroid")
        lng0, lat0 = man["lng"], man["lat"]
        parc_wgs = []

    # The build_context manifest's (lat, lng) IS the geocoded address. We use
    # the parcelle centroid from DB when available so the local frame matches
    # the BM's coordinate system; otherwise we fall back to the manifest.
    parc_local = wgs84_ring_to_local(parc_wgs, man["lng"], man["lat"]) if parc_wgs else []
    if parc_local:
        cx = sum(p[0] for p in parc_local) / len(parc_local)
        cy = sum(p[1] for p in parc_local) / len(parc_local)
    else:
        cx, cy = 0.0, 0.0
    print(f"  parcelle centroid in local meters : ({cx:.2f}, {cy:.2f})")

    # 3) Voisinage from IGN — full radius, no camera filter for the smoke test
    triples, origin = voisin_quads_from_context_source(
        context_source="ign_photogrammetry",
        project_id=PROJECT_ID,
        parcel_center_local=(cx, cy),
        skip_overlap_with=parc_local if parc_local else None,
        camera_pos_xy=None,
        block_camera_sight=False,
        max_distance_m=350.0,   # match the 300 m build_context radius + slack
        min_height_m=1.5,       # include small annexes / sheds for visual context
        max_height_m=45.0,
    )
    print(f"  IGN voisins after filtering : {len(triples)}")

    # 4) Build quads_by_material — voisins go into 'voisin_ign' so the
    #    legacy 'voisin' material remains untouched. parcelle outline can
    #    be added later (skipped here — we want a clean voisinage-only test).
    quads_by_mat: dict[str, list] = {"voisin_ign": []}
    z_min = float("inf")
    z_max = float("-inf")
    for fp, h, z_base in triples:
        if not fp or h <= 0:
            continue
        quads = extruded_voisin_quads_with_base(fp, h, z_base_m=z_base)
        quads_by_mat["voisin_ign"].extend(quads)
        z_min = min(z_min, z_base)
        z_max = max(z_max, z_base + h)

    if not quads_by_mat["voisin_ign"]:
        print("!! No voisin quads produced — aborting USDA export.")
        return 3

    print(
        f"  voisin quads : {len(quads_by_mat['voisin_ign'])} (z {z_min:.1f}…{z_max:.1f} m)"
    )

    # 5) Export USDA with IGN context (ground ortho + vegetation Xform).
    out_dir = REPO_ROOT / "refs" / "renders"
    out_dir.mkdir(parents=True, exist_ok=True)
    usda_path = out_dir / "test_jour4_ign_context.usda"

    # Camera : isometric SE looking at parcelle, ~30 m up, 80 m back.
    cam_pos = (cx + 60.0, cy - 60.0, 30.0)
    cam_tgt = (cx, cy, 5.0)

    text = export_scene_to_usda(
        quads_by_material=quads_by_mat,
        camera_position=cam_pos,
        camera_target=cam_tgt,
        camera_fov_deg=42.0,
        sun_direction=(0.4, -0.6, 0.7),
        sun_energy=5.0,
        output_path=usda_path,
        context_source="ign_photogrammetry",
        project_id=PROJECT_ID,
        ortho_half_size_m=300.0,
        ortho_z_ground=-0.05,   # 5 cm below voisin base so building footprints sit on top
        ortho_center_xy=(cx, cy),
        copy_ign_textures=True,
    )
    print(f"  ✓ USDA written : {usda_path} ({usda_path.stat().st_size:,} bytes)")
    ortho_copy = usda_path.parent / "bdortho_macro.jpg"
    print(f"    ortho copy   : {ortho_copy} ({'present' if ortho_copy.is_file() else 'missing'})")

    # 6) Validation : grep USDA for expected prims
    n_voisin_quads = len(quads_by_mat["voisin_ign"])
    n_mesh_defs = len(re.findall(r"\n\s*def Mesh ", text))
    n_xform_defs = len(re.findall(r"\n\s*def Xform ", text))
    n_material_defs = len(re.findall(r"\n\s*def Material ", text))
    has_ground_ortho = "GroundOrtho" in text
    has_vegetation = "Vegetation" in text
    has_ortho_tex_ref = "bdortho_macro.jpg" in text
    # Look for whole-word `nan`/`inf` numeric tokens, not substrings (avoid
    # matching `info:id` inside Shader prim definitions).
    nan_count = len(re.findall(r"(?<![A-Za-z0-9_])(?:nan|inf)(?![A-Za-z0-9_])", text))

    # 7) Report
    report_path = out_dir / "test_jour4_ign_context_report.md"
    report = []
    report.append(f"# Jour 4 — IGN context smoke test report\n")
    report.append(f"Generated : {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
    report.append(f"Project   : `{PROJECT_ID}`\n")
    report.append(f"Duration  : {time.time() - t0:.1f} s\n")
    report.append(f"\n## USDA stats\n")
    report.append(f"- Path : `{usda_path}`")
    report.append(f"- Size : {usda_path.stat().st_size:,} bytes")
    report.append(f"- `def Mesh` count : {n_mesh_defs}")
    report.append(f"- `def Xform` count : {n_xform_defs}")
    report.append(f"- `def Material` count : {n_material_defs}")
    report.append(f"- voisin quads : {n_voisin_quads}")
    report.append(f"- IGN voisins kept : {len(triples)} (of {man['bdtopo_building_count_valid']} valid LOD2)")
    report.append(f"- scene z range : {z_min:.1f}…{z_max:.1f} m local")
    report.append(f"\n## Asset references\n")
    report.append(f"- GroundOrtho mesh present : {has_ground_ortho}")
    report.append(f"- Vegetation Xform present : {has_vegetation}")
    report.append(f"- bdortho_macro.jpg reference in USDA : {has_ortho_tex_ref}")
    report.append(f"- bdortho_macro.jpg copied next to USDA : {ortho_copy.is_file()}")
    report.append(f"\n## Sanity\n")
    report.append(f"- 'nan' / 'inf' occurrences in USDA text : {nan_count}")
    report.append(f"- BD ORTHO macro resolution : "
                  f"{man['bdortho_resolutions_cm_per_px'].get('macro')} cm/px (600 m × 600 m)")
    report.append(f"- LiDAR HD tile : `{man.get('lidar_tile_name')}`")
    issues = []
    if has_ground_ortho is False:
        issues.append("GroundOrtho mesh missing — manifest may not record bdortho_macro path")
    if has_ortho_tex_ref is False:
        issues.append("bdortho_macro.jpg reference missing from USDA text")
    if nan_count > 0:
        issues.append(f"USDA contains {nan_count} nan/inf occurrences")
    if len(triples) < 500:
        issues.append(f"Only {len(triples)} voisins kept — expected ≥800 valid LOD2")
    report.append("\n## Issues\n")
    if issues:
        for it in issues:
            report.append(f"- {it}")
    else:
        report.append("- (none)")
    report_path.write_text("\n".join(report))
    print(f"  ✓ Report written : {report_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
