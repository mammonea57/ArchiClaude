"""BD TOPO V3 buildings harvester — fetches LOD2 footprints + heights for an area.

WFS query returns buildings with 3D geometry (z-coords baked into vertices).
Etalab 2.0 license, commercial use OK with attribution.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .ign_endpoints import BDTOPO_BATIMENT_LAYER, GEOPLATEFORME_WFS

logger = logging.getLogger(__name__)


@dataclass
class BBox:
    """WGS84 bbox: lat_min, lng_min, lat_max, lng_max."""
    lat_min: float
    lng_min: float
    lat_max: float
    lng_max: float

    def as_wfs_param(self) -> str:
        return f"{self.lng_min},{self.lat_min},{self.lng_max},{self.lat_max},EPSG:4326"

    @classmethod
    def around(cls, lat: float, lng: float, radius_m: float = 200.0) -> "BBox":
        """Approximate bbox of radius_m around a point (small angles, EU latitudes)."""
        deg_lat = radius_m / 111_000.0
        import math
        deg_lng = radius_m / (111_000.0 * max(0.01, math.cos(math.radians(lat))))
        return cls(
            lat_min=lat - deg_lat,
            lng_min=lng - deg_lng,
            lat_max=lat + deg_lat,
            lng_max=lng + deg_lng,
        )


def fetch_buildings(bbox: BBox, max_features: int = 5000, timeout_s: float = 30.0) -> dict:
    """Fetch BD TOPO V3 buildings as GeoJSON FeatureCollection (3D geom).

    Returns dict with keys 'type', 'features'. Empty 'features' list on no result.
    Raises urllib.error.URLError on network failure.
    """
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": BDTOPO_BATIMENT_LAYER,
        "bbox": bbox.as_wfs_param(),
        "count": str(max_features),
        "outputFormat": "application/json",
    }
    url = f"{GEOPLATEFORME_WFS}?{urllib.parse.urlencode(params)}"
    logger.info("BDTOPO fetch: %s", url)
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    n = len(data.get("features", []))
    logger.info("BDTOPO returned %d buildings", n)
    return data


def save_buildings_geojson(data: dict, output_path: Path) -> None:
    """Persist GeoJSON to cache."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(data), encoding="utf-8")
    logger.info("BDTOPO saved: %s (%d features)", output_path, len(data.get("features", [])))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    nogent_t_junction = BBox.around(lat=48.838, lng=2.474, radius_m=200)
    data = fetch_buildings(nogent_t_junction, max_features=100)
    print(f"features: {len(data.get('features', []))}")
    if data.get("features"):
        first = data["features"][0]
        coords = first.get("geometry", {}).get("coordinates", [])
        sample_z = []
        def walk(node):
            if isinstance(node, list) and node and isinstance(node[0], (int, float)) and len(node) >= 3:
                sample_z.append(node[2])
            elif isinstance(node, list):
                for child in node:
                    walk(child)
        walk(coords)
        if sample_z:
            print(f"z-range: {min(sample_z):.1f} - {max(sample_z):.1f} m  (LOD2 confirmed)")
