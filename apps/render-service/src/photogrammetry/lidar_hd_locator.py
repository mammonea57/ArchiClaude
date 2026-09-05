"""LiDAR HD tile locator — find the LAZ tile URL covering a given coordinate.

Uses Géoplateforme WFS to query IGNF_NUAGES-DE-POINTS-LIDAR-HD:dalle.
Returns tile metadata + download URL (COPC LAZ format) if classified.
"""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

from .ign_endpoints import GEOPLATEFORME_WFS, LIDAR_HD_DALLE_LAYER
from .bdtopo_harvester import BBox

logger = logging.getLogger(__name__)


@dataclass
class LidarTile:
    tile_id: int
    name: str
    download_url: str
    timestamp: str
    projection: str
    classification: Optional[str]
    acquisition_dates: Optional[str]


def find_tile(bbox: BBox, timeout_s: float = 30.0) -> Optional[LidarTile]:
    """Find the LiDAR HD tile covering the given bbox.

    Returns the first matching tile (1km x 1km tiles, usually 1-4 cover any urban bbox).
    Returns None if no classified tile available (rural / not yet published).
    """
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": LIDAR_HD_DALLE_LAYER,
        "bbox": bbox.as_wfs_param(),
        "count": "5",
        "outputFormat": "application/json",
    }
    url = f"{GEOPLATEFORME_WFS}?{urllib.parse.urlencode(params)}"
    logger.info("LiDAR HD locator: %s", url)
    with urllib.request.urlopen(url, timeout=timeout_s) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    features = data.get("features", [])
    if not features:
        logger.warning("No LiDAR HD tile found for bbox %s", bbox.as_wfs_param())
        return None
    props = features[0].get("properties", {})
    metadata_str = props.get("metadata", "{}")
    try:
        metadata = json.loads(metadata_str)
    except json.JSONDecodeError:
        metadata = {}
    return LidarTile(
        tile_id=props.get("id", -1),
        name=props.get("name", "unknown"),
        download_url=props.get("url", ""),
        timestamp=props.get("timestamp", ""),
        projection=props.get("projection", "EPSG:2154"),
        classification=metadata.get("classement"),
        acquisition_dates=f"{metadata.get('datedebut','?')} to {metadata.get('datefin','?')}",
    )
