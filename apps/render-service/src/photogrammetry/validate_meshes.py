"""Cross-validate Poisson-reconstructed LiDAR meshes against BDTOPO V3 LOD2.

For each Poisson OBJ in <meshes_dir>:
  1. Compute its 2D footprint = convex hull of vertices projected to z_min plane.
  2. Compute its z_max (roof height in NGF metres).
  3. Find nearest BDTOPO building by centroid distance.
  4. Score: XY centroid RMSE, area ratio, Z accuracy.

Outputs a JSON report + a coverage summary suitable for jour3_validation.md.

Coordinates: BDTOPO ships in WGS84 with NGF z in coords[2]. We reproject to
EPSG:2154 Lambert-93 so that distances/areas are in metres directly. Poisson
meshes are already in Lambert-93 (modal_pdal_endpoint runs on cropped LiDAR).
"""

from __future__ import annotations

import json
import logging
import math
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class MeshFootprintStat:
    obj_path: str
    n_vertices: int
    n_faces: int
    centroid_lambert93: tuple  # (x, y)
    z_min: float
    z_max: float
    area_m2: float
    convex_hull_xy: list  # [(x, y), ...]


@dataclass
class BdtopoBuildingStat:
    feature_index: int
    centroid_lambert93: tuple
    z_max: float
    area_m2: float
    polygon_xy: list


@dataclass
class MatchPair:
    obj_path: str
    bdtopo_feature_index: Optional[int]
    centroid_offset_m: float
    poisson_area_m2: float
    bdtopo_area_m2: float
    area_ratio: float  # poisson / bdtopo
    poisson_z_max: float
    bdtopo_z_max: float
    z_offset_m: float


@dataclass
class ValidationReport:
    meshes_dir: str
    bdtopo_path: str
    project_centroid_lambert93: tuple
    bbox_lambert93: tuple
    n_poisson_meshes: int
    n_bdtopo_buildings_in_bbox: int
    n_matched: int
    coverage_pct: float
    centroid_rmse_m: float
    centroid_median_offset_m: float
    area_ratio_mean: float
    area_ratio_median: float
    z_rmse_m: float
    z_mean_offset_m: float
    matches: list  # list[MatchPair]


def _parse_obj_vertices(obj_path: Path):
    """Parse OBJ file, return (vertices N×3 ndarray, n_faces).

    We only need vertices + face count, not connectivity, so a simple parser
    is enough and avoids a trimesh/Open3D dependency on the Mac side.
    """
    import numpy as np

    vs = []
    n_faces = 0
    with obj_path.open() as fp:
        for line in fp:
            if line.startswith("v "):
                parts = line.strip().split()
                vs.append((float(parts[1]), float(parts[2]), float(parts[3])))
            elif line.startswith("f "):
                n_faces += 1
    return np.array(vs, dtype=np.float64), n_faces


def _convex_hull_2d(points_xy):
    """Andrew's monotone chain convex hull. Avoids scipy dep."""
    pts = sorted({(float(x), float(y)) for x, y in points_xy})
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _polygon_area(ring):
    """Shoelace area for a closed XY ring."""
    if len(ring) < 3:
        return 0.0
    s = 0.0
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i]
        x2, y2 = ring[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) * 0.5


def _polygon_centroid(ring):
    if len(ring) < 3:
        return (0.0, 0.0)
    sx = sum(p[0] for p in ring) / len(ring)
    sy = sum(p[1] for p in ring) / len(ring)
    return (sx, sy)


def _mesh_stats(obj_path: Path) -> Optional[MeshFootprintStat]:
    import numpy as np

    verts, n_faces = _parse_obj_vertices(obj_path)
    if verts.shape[0] < 3:
        return None
    z = verts[:, 2]
    z_min = float(z.min())
    z_max = float(z.max())
    # Project to XY and take the convex hull
    hull = _convex_hull_2d(verts[:, :2].tolist())
    if len(hull) < 3:
        return None
    area = _polygon_area(hull)
    cx, cy = _polygon_centroid(hull)
    return MeshFootprintStat(
        obj_path=str(obj_path),
        n_vertices=int(verts.shape[0]),
        n_faces=int(n_faces),
        centroid_lambert93=(cx, cy),
        z_min=z_min,
        z_max=z_max,
        area_m2=area,
        convex_hull_xy=hull,
    )


def _bdtopo_stats(
    bdtopo_geojson: dict,
    bbox_lambert93: tuple,
    transformer,
) -> list:
    """Convert each BDTOPO feature to Lambert-93 polygons + stats.

    Filters out sentinel z=-1000 vertices and features falling outside the bbox.
    """
    x_min, y_min, x_max, y_max = bbox_lambert93
    out: list = []
    for idx, feature in enumerate(bdtopo_geojson.get("features", [])):
        coords = feature.get("geometry", {}).get("coordinates", [])
        for poly in coords:
            for ring in poly:
                xys = []
                zs = []
                for vertex in ring:
                    if not isinstance(vertex, list) or len(vertex) < 2:
                        continue
                    lng = float(vertex[0])
                    lat = float(vertex[1])
                    z = float(vertex[2]) if len(vertex) >= 3 else -1000.0
                    x, y = transformer.transform(lng, lat)
                    xys.append((x, y))
                    if z > -100.0:
                        zs.append(z)
                if len(xys) < 3 or not zs:
                    continue
                area = _polygon_area(xys)
                if area < 1.0:
                    continue
                cx, cy = _polygon_centroid(xys)
                # Bbox filter — keep building if centroid is inside crop bbox
                if not (x_min <= cx <= x_max and y_min <= cy <= y_max):
                    continue
                out.append(
                    BdtopoBuildingStat(
                        feature_index=idx,
                        centroid_lambert93=(cx, cy),
                        z_max=max(zs),
                        area_m2=area,
                        polygon_xy=xys,
                    )
                )
    return out


def cross_validate(
    meshes_dir: Path,
    bdtopo_geojson_path: Path,
    bbox_lambert93: tuple,
    project_centroid_lambert93: tuple,
    output_path: Path,
    max_match_distance_m: float = 30.0,
) -> ValidationReport:
    """Compare Poisson OBJs vs BDTOPO LOD2, write JSON report.

    Args:
        meshes_dir: directory containing building_*.obj (downloaded from Modal)
        bdtopo_geojson_path: BDTOPO V3 FeatureCollection (LOD2, z in coords)
        bbox_lambert93: same crop as the Modal job (x_min, y_min, x_max, y_max)
        project_centroid_lambert93: (x, y) used as a sanity-check anchor
        output_path: validation_report.json output path
        max_match_distance_m: discard Poisson↔BDTOPO pairs farther than this
    """
    import numpy as np
    from pyproj import Transformer

    obj_paths = sorted(meshes_dir.glob("building_*.obj"))
    if not obj_paths:
        raise FileNotFoundError(f"No building_*.obj files in {meshes_dir}")

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)
    bdtopo_geojson = json.loads(bdtopo_geojson_path.read_text())
    bdtopo_stats = _bdtopo_stats(bdtopo_geojson, bbox_lambert93, transformer)
    logger.info("BDTOPO buildings in bbox: %d", len(bdtopo_stats))

    poisson_stats = []
    for p in obj_paths:
        stat = _mesh_stats(p)
        if stat is not None:
            poisson_stats.append(stat)
    logger.info("Poisson meshes parsed: %d", len(poisson_stats))

    # Greedy match: for each Poisson mesh, take nearest unmatched BDTOPO centroid.
    used = set()
    matches: list = []
    for p_stat in poisson_stats:
        px, py = p_stat.centroid_lambert93
        best_idx = -1
        best_d = float("inf")
        for bi, b_stat in enumerate(bdtopo_stats):
            if bi in used:
                continue
            bx, by = b_stat.centroid_lambert93
            d = math.hypot(px - bx, py - by)
            if d < best_d:
                best_d = d
                best_idx = bi
        if best_idx == -1 or best_d > max_match_distance_m:
            matches.append(
                asdict(
                    MatchPair(
                        obj_path=p_stat.obj_path,
                        bdtopo_feature_index=None,
                        centroid_offset_m=best_d if best_idx != -1 else float("nan"),
                        poisson_area_m2=p_stat.area_m2,
                        bdtopo_area_m2=float("nan"),
                        area_ratio=float("nan"),
                        poisson_z_max=p_stat.z_max,
                        bdtopo_z_max=float("nan"),
                        z_offset_m=float("nan"),
                    )
                )
            )
            continue
        used.add(best_idx)
        b_stat = bdtopo_stats[best_idx]
        matches.append(
            asdict(
                MatchPair(
                    obj_path=p_stat.obj_path,
                    bdtopo_feature_index=b_stat.feature_index,
                    centroid_offset_m=best_d,
                    poisson_area_m2=p_stat.area_m2,
                    bdtopo_area_m2=b_stat.area_m2,
                    area_ratio=p_stat.area_m2 / b_stat.area_m2
                    if b_stat.area_m2 > 0
                    else float("nan"),
                    poisson_z_max=p_stat.z_max,
                    bdtopo_z_max=b_stat.z_max,
                    z_offset_m=p_stat.z_max - b_stat.z_max,
                )
            )
        )

    matched = [m for m in matches if m["bdtopo_feature_index"] is not None]
    n_matched = len(matched)

    def _safe_arr(key):
        return np.array(
            [m[key] for m in matched if not math.isnan(m[key])], dtype=np.float64
        )

    offset_arr = _safe_arr("centroid_offset_m")
    area_arr = _safe_arr("area_ratio")
    z_arr = _safe_arr("z_offset_m")

    centroid_rmse = float(math.sqrt((offset_arr**2).mean())) if offset_arr.size else float("nan")
    centroid_median = float(np.median(offset_arr)) if offset_arr.size else float("nan")
    area_mean = float(area_arr.mean()) if area_arr.size else float("nan")
    area_median = float(np.median(area_arr)) if area_arr.size else float("nan")
    z_rmse = float(math.sqrt((z_arr**2).mean())) if z_arr.size else float("nan")
    z_mean = float(z_arr.mean()) if z_arr.size else float("nan")

    coverage = 100.0 * n_matched / len(bdtopo_stats) if bdtopo_stats else 0.0

    report = ValidationReport(
        meshes_dir=str(meshes_dir),
        bdtopo_path=str(bdtopo_geojson_path),
        project_centroid_lambert93=tuple(project_centroid_lambert93),
        bbox_lambert93=tuple(bbox_lambert93),
        n_poisson_meshes=len(poisson_stats),
        n_bdtopo_buildings_in_bbox=len(bdtopo_stats),
        n_matched=n_matched,
        coverage_pct=coverage,
        centroid_rmse_m=centroid_rmse,
        centroid_median_offset_m=centroid_median,
        area_ratio_mean=area_mean,
        area_ratio_median=area_median,
        z_rmse_m=z_rmse,
        z_mean_offset_m=z_mean,
        matches=matches,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(asdict(report), indent=2))
    logger.info("Validation report → %s", output_path)
    return report
