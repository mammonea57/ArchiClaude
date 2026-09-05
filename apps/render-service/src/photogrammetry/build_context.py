"""Pipeline universel : adresse + parcelle → contexte 3D IGN complet.

Entry point pour le pipeline auto que ArchiClaude appellera depuis le backend
quand un user crée/analyse un projet sur n'importe quelle parcelle France.

Usage:
    from photogrammetry.build_context import build_context_for_project
    artefacts = build_context_for_project(project_id, lat, lng, radius_m=300)

Output dans refs/photogrammetry/<project_id>/ :
    - bdtopo_buildings.geojson  (LOD2 footprints + heights)
    - bdortho_aerial.jpg        (texture aérienne 20cm)
    - lidar_hd_tile.json        (URL + métadonnées dalle LAZ pour download Modal)
    - build_context_manifest.json (résumé + paths)
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

from .bdortho_harvester import fetch_ortho_jpeg
from .bdtopo_harvester import BBox, fetch_buildings, save_buildings_geojson
from .lidar_hd_locator import find_tile

logger = logging.getLogger(__name__)


@dataclass
class ContextArtefacts:
    project_id: str
    lat: float
    lng: float
    radius_m: float
    bdtopo_path: Optional[str]
    bdtopo_building_count: int
    bdtopo_building_count_valid: int
    bdtopo_building_count_sentinel: int
    bdtopo_z_range_m: Optional[tuple]
    bdortho_paths: dict  # {macro,meso,micro,parcelle}
    bdortho_resolutions_cm_per_px: dict
    lidar_tile_name: Optional[str]
    lidar_tile_url: Optional[str]
    lidar_tile_classification: Optional[str]
    lidar_tile_timestamp: Optional[str]
    overlay_path: Optional[str]
    duration_s: float


IGN_Z_SENTINEL_NULL = -1000.0  # IGN convention: bâtiment hauteur non mesurée


def _walk_z(node, out: list) -> None:
    if isinstance(node, list) and node and isinstance(node[0], (int, float)) and len(node) >= 3:
        out.append(node[2])
    elif isinstance(node, list):
        for child in node:
            _walk_z(child, out)


def _z_range(geojson: dict) -> Optional[tuple]:
    """Return (z_min, z_max) for valid buildings only — filters IGN -1000 sentinels."""
    z_values: list = []
    for feature in geojson.get("features", []):
        _walk_z(feature.get("geometry", {}).get("coordinates", []), z_values)
    z_valid = [z for z in z_values if z > IGN_Z_SENTINEL_NULL + 1]
    if not z_valid:
        return None
    return (round(min(z_valid), 1), round(max(z_valid), 1))


def _render_overlay(
    project_dir: Path,
    base_jpg: Path,
    bbox: BBox,
    buildings_geojson: dict,
    parcelle_geojson: Optional[dict],
    output_name: str,
) -> Path:
    """Draw BDTOPO building footprints (red) + parcelle (yellow) over the base JPG.

    Output preserves the base image's pixel resolution. Coords are projected from
    WGS84 (lng, lat) into pixel space using the bbox bounds (axis-aligned).
    """
    from PIL import Image, ImageDraw

    img = Image.open(base_jpg).convert("RGBA")
    w, h = img.size
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    def project(lng: float, lat: float) -> tuple:
        # axis: pixel x grows east (= lng increase) ; pixel y grows south (= lat decrease)
        px = (lng - bbox.lng_min) / (bbox.lng_max - bbox.lng_min) * w
        py = (bbox.lat_max - lat) / (bbox.lat_max - bbox.lat_min) * h
        return (px, py)

    def iter_polygons(geom_coords):
        # MultiPolygon -> [[[ring], ...]] ; Polygon -> [[ring]]
        if not isinstance(geom_coords, list) or not geom_coords:
            return
        first = geom_coords[0]
        if isinstance(first, list) and first and isinstance(first[0], list) and len(first[0]) > 0 and isinstance(first[0][0], list):
            # MultiPolygon
            for poly in geom_coords:
                for ring in poly:
                    yield ring
        elif isinstance(first, list) and first and isinstance(first[0], (int, float)):
            # Single ring (Polygon's first ring)
            yield first
        else:
            # Polygon: list of rings
            for ring in geom_coords:
                yield ring

    # Buildings — semi-transparent red outline + fill
    bld_color_fill = (220, 30, 30, 70)
    bld_color_line = (220, 0, 0, 220)
    for feature in buildings_geojson.get("features", []):
        geom = feature.get("geometry", {})
        coords = geom.get("coordinates", [])
        for ring in iter_polygons(coords):
            pts = [project(c[0], c[1]) for c in ring if isinstance(c, list) and len(c) >= 2]
            if len(pts) >= 3:
                draw.polygon(pts, fill=bld_color_fill, outline=bld_color_line)

    # Parcelle — yellow thick outline (no fill, important for visibility)
    if parcelle_geojson:
        parc_color = (255, 235, 0, 255)
        features = parcelle_geojson if isinstance(parcelle_geojson, list) else parcelle_geojson.get("features", [parcelle_geojson])
        for feature in features:
            geom = feature.get("geometry") if isinstance(feature, dict) and "geometry" in feature else feature
            coords = geom.get("coordinates", []) if isinstance(geom, dict) else []
            for ring in iter_polygons(coords):
                pts = [project(c[0], c[1]) for c in ring if isinstance(c, list) and len(c) >= 2]
                if len(pts) >= 3:
                    draw.line(pts + [pts[0]], fill=parc_color, width=6)

    combined = Image.alpha_composite(img, overlay).convert("RGB")
    output_path = project_dir / output_name
    combined.save(output_path, "JPEG", quality=92)
    logger.info("Overlay saved: %s", output_path)
    return output_path


def _count_sentinel_features(geojson: dict) -> int:
    count = 0
    for feature in geojson.get("features", []):
        zs: list = []
        _walk_z(feature.get("geometry", {}).get("coordinates", []), zs)
        if zs and all(z <= IGN_Z_SENTINEL_NULL + 1 for z in zs):
            count += 1
    return count


# Multi-zoom orthophoto: macro context (quartier) → ultra (façades visibles).
# Default layer = THR (Très Haute Résolution, 5 cm/pixel native, IDF + métropoles).
# Fallback HR (20 cm/pixel, France entière) si THR pas dispo zone rurale.
# Image fixée à 2048×2048 ; output cm/px = (2 × radius_m × 100) / 2048
ORTHO_ZOOM_LEVELS = {
    "macro":    {"radius_m": 300.0, "size_px": 2048},  # 600m → 29 cm/px
    "meso":     {"radius_m": 100.0, "size_px": 2048},  # 200m → 10 cm/px
    "micro":    {"radius_m": 50.0,  "size_px": 2048},  # 100m → 4.9 cm/px (= THR native)
    "parcelle": {"radius_m": 25.0,  "size_px": 2048},  # 50m  → 2.4 cm/px
    "ultra":    {"radius_m": 12.0,  "size_px": 2048},  # 24m  → 1.2 cm/px (façades + voitures)
    "facade":   {"radius_m": 8.0,   "size_px": 2048},  # 16m  → 0.8 cm/px (passage piéton lisible)
}


def build_context_for_project(
    project_id: str,
    lat: float,
    lng: float,
    radius_m: float = 300.0,
    output_root: Optional[Path] = None,
    ortho_size_px: int = 1024,
    parcelle_geojson: Optional[dict] = None,
) -> ContextArtefacts:
    """Fetch the full IGN 3D context for a project's parcelle.

    Args:
        project_id: ArchiClaude project UUID (used as folder name)
        lat, lng: parcelle centroid in WGS84
        radius_m: bbox radius around the centroid
        output_root: defaults to refs/photogrammetry/
        ortho_size_px: BD ORTHO output resolution

    Returns ContextArtefacts with paths + metadata.
    """
    t0 = time.time()
    if output_root is None:
        output_root = Path("refs/photogrammetry")
    project_dir = output_root / project_id
    project_dir.mkdir(parents=True, exist_ok=True)

    bbox = BBox.around(lat=lat, lng=lng, radius_m=radius_m)

    bdtopo_data = fetch_buildings(bbox, max_features=5000)
    bdtopo_path = project_dir / "bdtopo_buildings.geojson"
    save_buildings_geojson(bdtopo_data, bdtopo_path)
    n_buildings = len(bdtopo_data.get("features", []))
    n_sentinel = _count_sentinel_features(bdtopo_data)
    n_valid = n_buildings - n_sentinel
    z_range = _z_range(bdtopo_data)

    bdortho_paths: dict = {}
    bdortho_resolutions: dict = {}
    for zoom_label, params in ORTHO_ZOOM_LEVELS.items():
        zoom_bbox = BBox.around(lat=lat, lng=lng, radius_m=params["radius_m"])
        zoom_path = project_dir / f"bdortho_{zoom_label}.jpg"
        fetch_ortho_jpeg(zoom_bbox, zoom_path, width=params["size_px"], height=params["size_px"])
        bdortho_paths[zoom_label] = str(zoom_path)
        ground_width_m = 2 * params["radius_m"]
        bdortho_resolutions[zoom_label] = round(ground_width_m * 100 / params["size_px"], 1)

    overlay_path: Optional[Path] = None
    try:
        overlay_path = _render_overlay(
            project_dir=project_dir,
            base_jpg=Path(bdortho_paths["micro"]),
            bbox=BBox.around(lat=lat, lng=lng, radius_m=ORTHO_ZOOM_LEVELS["micro"]["radius_m"]),
            buildings_geojson=bdtopo_data,
            parcelle_geojson=parcelle_geojson,
            output_name="bdortho_micro_with_overlay.jpg",
        )
    except Exception as exc:  # PIL missing in some venvs — overlay is non-fatal
        logger.warning("Overlay render skipped: %s", exc)

    tile = find_tile(bbox)
    lidar_tile_path = project_dir / "lidar_hd_tile.json"
    if tile is not None:
        lidar_tile_path.write_text(json.dumps(asdict(tile), indent=2), encoding="utf-8")

    artefacts = ContextArtefacts(
        project_id=project_id,
        lat=lat,
        lng=lng,
        radius_m=radius_m,
        bdtopo_path=str(bdtopo_path),
        bdtopo_building_count=n_buildings,
        bdtopo_building_count_valid=n_valid,
        bdtopo_building_count_sentinel=n_sentinel,
        bdtopo_z_range_m=z_range,
        bdortho_paths=bdortho_paths,
        bdortho_resolutions_cm_per_px=bdortho_resolutions,
        overlay_path=str(overlay_path) if overlay_path else None,
        lidar_tile_name=tile.name if tile else None,
        lidar_tile_url=tile.download_url if tile else None,
        lidar_tile_classification=tile.classification if tile else None,
        lidar_tile_timestamp=tile.timestamp if tile else None,
        duration_s=round(time.time() - t0, 2),
    )

    manifest_path = project_dir / "build_context_manifest.json"
    manifest_path.write_text(json.dumps(asdict(artefacts), indent=2), encoding="utf-8")
    logger.info("Context built for %s in %.1fs : %s", project_id, artefacts.duration_s, manifest_path)
    return artefacts


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    if len(sys.argv) < 4:
        print("Usage: python -m photogrammetry.build_context <project_id> <lat> <lng> [radius_m]")
        sys.exit(1)
    pid = sys.argv[1]
    lat = float(sys.argv[2])
    lng = float(sys.argv[3])
    radius = float(sys.argv[4]) if len(sys.argv) > 4 else 300.0
    artefacts = build_context_for_project(pid, lat, lng, radius_m=radius)
    print(json.dumps(asdict(artefacts), indent=2))
