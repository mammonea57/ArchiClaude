"""Modal endpoint — IGN LiDAR HD COPC streaming + classification filter.

Pipeline Jour 2 :
    URL COPC LAZ (from photogrammetry.lidar_hd_locator)
      → download to Modal Volume (cached, 6-month TTL recommended)
      → laspy COPC reader, spatial filter by Lambert93 bbox
      → classification filter (class=2 ground, class=6 building, class=5 high veg)
      → output filtered LAZ per class + JSON stats
      → save to Modal Volume + return manifest

Why Modal vs Mac local :
  - 128 MB LAZ download → Modal cloud bandwidth >> Mac home
  - PDAL/Poisson mesh aval (Jour 3) needs Linux + occasionally heavy RAM
  - Production pipeline = 100% cloud (memory feedback_universalite_pipeline)
  - Cache shared across all ArchiClaude users (1 download per quartier, served many parcelles)

Usage:
    .venv/bin/modal run src/modal_lidar_endpoint.py \\
        --url https://data.geopf.fr/.../LHD_FXX_0662_6860_PTS_LAMB93_IGN69.copc.laz \\
        --bbox-lambert93 661500,6858500,662500,6859500

License: Etalab 2.0 (IGN open data, commercial OK with attribution)
"""

from __future__ import annotations

import io
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Optional

import modal

app = modal.App("archfr-lidar-hd")

# COPC streaming + classification filtering is pure-CPU work — no GPU needed.
# Python 3.11 is the most stable for laspy/lazrs as of 2026.
image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "laspy[lazrs]>=2.5.4",  # COPC reader + lazrs lazperf alternative
        "numpy>=1.26",
        "requests>=2.32",
    )
)

# Persistent cache for downloaded LAZ tiles. 1 km × 1 km tile ≈ 128 MB,
# Île-de-France complète = ~50 GB cache. Modal Volume bills storage only.
lidar_cache = modal.Volume.from_name("archfr-lidar-hd-cache", create_if_missing=True)

CACHE_MOUNT = "/cache"
CACHE_TILE_DIR = f"{CACHE_MOUNT}/tiles"
CACHE_FILTERED_DIR = f"{CACHE_MOUNT}/filtered"

# IGN LiDAR HD classification scheme (ASPRS LAS spec + IGN extensions)
LAZ_CLASS_GROUND = 2
LAZ_CLASS_LOW_VEG = 3
LAZ_CLASS_MID_VEG = 4
LAZ_CLASS_HIGH_VEG = 5
LAZ_CLASS_BUILDING = 6
LAZ_CLASS_WATER = 9
LAZ_CLASS_BRIDGE = 17
LAZ_CLASS_NOISE = 7

CLASS_LABELS = {
    LAZ_CLASS_GROUND: "ground",
    LAZ_CLASS_LOW_VEG: "low_vegetation",
    LAZ_CLASS_MID_VEG: "mid_vegetation",
    LAZ_CLASS_HIGH_VEG: "high_vegetation",
    LAZ_CLASS_BUILDING: "building",
    LAZ_CLASS_WATER: "water",
    LAZ_CLASS_BRIDGE: "bridge",
    LAZ_CLASS_NOISE: "noise",
}


@dataclass
class LidarFilterResult:
    tile_name: str
    source_url: str
    tile_path: str
    bbox_lambert93: tuple
    total_points_in_tile: int
    points_in_bbox: int
    points_per_class: dict
    filtered_paths: dict
    duration_s: float


def _tile_name_from_url(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1].replace(".copc.laz", "")


@app.function(image=image, volumes={CACHE_MOUNT: lidar_cache}, timeout=900)
def fetch_and_filter(
    url: str,
    bbox_lambert93: tuple,
    extract_classes: Optional[list] = None,
) -> dict:
    """Download a COPC LAZ tile from IGN (cached on Modal Volume), then
    spatially crop + classify-filter to per-class LAZ output files.

    Args:
        url: IGN LiDAR HD download URL (from lidar_hd_locator.find_tile)
        bbox_lambert93: (x_min, y_min, x_max, y_max) in EPSG:2154 Lambert-93 (metres)
        extract_classes: list of LAS class codes to extract separately.
            Defaults to [2, 5, 6] (ground, high_veg, building)

    Returns dict serialisable for the manifest (asdict(LidarFilterResult)).
    """
    import time
    import laspy
    import numpy as np
    import requests

    t0 = time.time()
    tile_name = _tile_name_from_url(url)
    if extract_classes is None:
        extract_classes = [LAZ_CLASS_GROUND, LAZ_CLASS_HIGH_VEG, LAZ_CLASS_BUILDING]

    tile_dir = Path(CACHE_TILE_DIR)
    tile_dir.mkdir(parents=True, exist_ok=True)
    filtered_dir = Path(CACHE_FILTERED_DIR) / tile_name
    filtered_dir.mkdir(parents=True, exist_ok=True)
    tile_path = tile_dir / f"{tile_name}.copc.laz"

    if not tile_path.exists():
        print(f"[fetch] downloading {url} → {tile_path}")
        with requests.get(url, stream=True, timeout=600) as r:
            r.raise_for_status()
            with tile_path.open("wb") as fp:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    fp.write(chunk)
        lidar_cache.commit()
        print(f"[fetch] cached {tile_path.stat().st_size/1e6:.1f} MB")
    else:
        print(f"[fetch] cache hit {tile_path}")

    print(f"[laspy] opening {tile_path}")
    with laspy.open(str(tile_path)) as src:
        total_points = src.header.point_count
        las = src.read()

    x = np.asarray(las.x)
    y = np.asarray(las.y)
    cls = np.asarray(las.classification)

    x_min, y_min, x_max, y_max = bbox_lambert93
    bbox_mask = (x >= x_min) & (x <= x_max) & (y >= y_min) & (y <= y_max)
    in_bbox_count = int(bbox_mask.sum())

    points_per_class = {}
    for c in sorted(set(int(v) for v in cls[bbox_mask].tolist())):
        n = int(((cls == c) & bbox_mask).sum())
        points_per_class[CLASS_LABELS.get(c, f"class_{c}")] = n

    print(
        f"[laspy] total={total_points:,} in_bbox={in_bbox_count:,} "
        f"per_class={points_per_class}"
    )

    filtered_paths = {}
    for class_code in extract_classes:
        class_mask = (cls == class_code) & bbox_mask
        n = int(class_mask.sum())
        if n == 0:
            continue
        label = CLASS_LABELS.get(class_code, f"class_{class_code}")
        out_path = filtered_dir / f"{label}.laz"
        # Build a fresh non-COPC header so laspy can write the output
        new_header = laspy.LasHeader(
            point_format=las.header.point_format,
            version=las.header.version,
        )
        new_header.scales = las.header.scales
        new_header.offsets = las.header.offsets
        new_header.global_encoding = las.header.global_encoding
        out_las = laspy.LasData(new_header)
        out_las.points = las.points[class_mask]
        out_las.write(str(out_path))
        filtered_paths[label] = str(out_path)
        print(f"[write] {out_path.name} → {n:,} points")

    lidar_cache.commit()

    result = LidarFilterResult(
        tile_name=tile_name,
        source_url=url,
        tile_path=str(tile_path),
        bbox_lambert93=tuple(bbox_lambert93),
        total_points_in_tile=int(total_points),
        points_in_bbox=in_bbox_count,
        points_per_class=points_per_class,
        filtered_paths=filtered_paths,
        duration_s=round(time.time() - t0, 2),
    )
    return asdict(result)


@app.function(image=image, volumes={CACHE_MOUNT: lidar_cache}, timeout=120)
def list_cache() -> dict:
    """Inspect what's currently in the Modal Volume cache."""
    tile_dir = Path(CACHE_TILE_DIR)
    filtered_dir = Path(CACHE_FILTERED_DIR)
    tiles = sorted(
        {"name": p.name, "size_mb": round(p.stat().st_size / 1e6, 1)}
        for p in tile_dir.glob("*.copc.laz") if p.exists()
    ) if tile_dir.exists() else []
    filtered = []
    if filtered_dir.exists():
        for tile_subdir in sorted(filtered_dir.iterdir()):
            if tile_subdir.is_dir():
                items = [
                    {"name": p.name, "size_mb": round(p.stat().st_size / 1e6, 1)}
                    for p in tile_subdir.glob("*.laz")
                ]
                filtered.append({"tile": tile_subdir.name, "files": items})
    return {"tiles_cached": tiles, "filtered_outputs": filtered}


@app.local_entrypoint()
def main(
    url: str = "",
    bbox_lambert93: str = "",
    list_only: bool = False,
):
    """CLI entrypoint.

    Example for Nogent 80 Rue des Héros (project a3126a4f-...):
      modal run src/modal_lidar_endpoint.py \\
        --url https://data.geopf.fr/telechargement/download/LiDARHD-NUALID/NUALHD_1-0__LAZ_LAMB93_KE_2025-06-06/LHD_FXX_0662_6860_PTS_LAMB93_IGN69.copc.laz \\
        --bbox-lambert93 662200,6859700,662800,6860300
    """
    if list_only or not url:
        cache = list_cache.remote()
        print(json.dumps(cache, indent=2))
        return
    parts = [float(p.strip()) for p in bbox_lambert93.split(",")]
    if len(parts) != 4:
        raise ValueError("--bbox-lambert93 expects 'x_min,y_min,x_max,y_max'")
    bbox = (parts[0], parts[1], parts[2], parts[3])
    result = fetch_and_filter.remote(url=url, bbox_lambert93=bbox)
    print("\n=== Manifest ===")
    print(json.dumps(result, indent=2))
