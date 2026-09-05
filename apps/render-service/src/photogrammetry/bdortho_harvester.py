"""BD ORTHO 20cm harvester via Géoplateforme WMS.

Single WMS GetMap call returns a JPEG of the requested bbox.
Etalab 2.0 license, commercial use OK with attribution.
"""

from __future__ import annotations

import logging
import urllib.parse
import urllib.request
from pathlib import Path

from .ign_endpoints import GEOPLATEFORME_WMS, ORTHO_HR_LAYER, ORTHO_THR_LAYER
from .bdtopo_harvester import BBox

logger = logging.getLogger(__name__)


def fetch_ortho_jpeg(
    bbox: BBox,
    output_path: Path,
    width: int = 1024,
    height: int = 1024,
    timeout_s: float = 30.0,
    layer: str = ORTHO_THR_LAYER,
) -> Path:
    """Download a BD ORTHO 20cm JPEG for the given bbox to output_path.

    WMS 1.3.0 EPSG:4326 axis order is (lat,lng) → bbox param order:
      lat_min,lng_min,lat_max,lng_max
    """
    params = {
        "SERVICE": "WMS",
        "VERSION": "1.3.0",
        "REQUEST": "GetMap",
        "LAYERS": layer,
        "FORMAT": "image/jpeg",
        "CRS": "EPSG:4326",
        "BBOX": f"{bbox.lat_min},{bbox.lng_min},{bbox.lat_max},{bbox.lng_max}",
        "WIDTH": str(width),
        "HEIGHT": str(height),
        "STYLES": "normal",
    }
    url = f"{GEOPLATEFORME_WMS}?{urllib.parse.urlencode(params)}"
    logger.info("BD ORTHO fetch: %dx%d for bbox %s", width, height, params["BBOX"])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        output_path.write_bytes(resp.read())
    size_kb = output_path.stat().st_size / 1024
    logger.info("BD ORTHO saved: %s (%.1f KB)", output_path, size_kb)
    return output_path
