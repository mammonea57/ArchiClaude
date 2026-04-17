"""Mapillary Graph API client — street-level photos.

API documentation: https://www.mapillary.com/developer/api-documentation
Requires MAPILLARY_CLIENT_TOKEN environment variable.
Returns empty list gracefully when token is absent.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from core.http_client import fetch_json

_MAPILLARY_URL = "https://graph.mapillary.com/images"

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MapillaryPhoto:
    """A single street-level photo from Mapillary."""

    image_id: str
    thumb_url: str
    captured_at: int  # unix milliseconds
    compass_angle: float
    lat: float
    lng: float


async def fetch_photos_around(
    *, lat: float, lng: float, radius_m: int = 50
) -> list[MapillaryPhoto]:
    """Fetch street-level photos near the given WGS84 point.

    Args:
        lat: Latitude in WGS84 decimal degrees.
        lng: Longitude in WGS84 decimal degrees.
        radius_m: Search radius in metres (converted to a bbox internally).

    Returns:
        List of :class:`MapillaryPhoto` sorted by captured_at descending (most
        recent first). Returns an empty list when ``MAPILLARY_CLIENT_TOKEN`` is
        not set — no HTTP call is made in that case.
    """
    token = os.environ.get("MAPILLARY_CLIENT_TOKEN")
    if not token:
        return []

    # Approximate degree offsets for the search bbox
    dlat = radius_m / 111_000
    dlng = radius_m / 73_000

    west = lng - dlng
    south = lat - dlat
    east = lng + dlng
    north = lat + dlat
    bbox = f"{west},{south},{east},{north}"

    params: dict[str, str | int | float] = {
        "access_token": token,
        "fields": "id,captured_at,compass_angle,thumb_1024_url,geometry",
        "bbox": bbox,
        "limit": 20,
    }

    data = await fetch_json(_MAPILLARY_URL, params=params)

    results: list[MapillaryPhoto] = []
    for item in data.get("data", []):
        geom = item.get("geometry", {})
        coords = geom.get("coordinates", [None, None])
        item_lng, item_lat = coords[0], coords[1]

        if item_lat is None or item_lng is None:
            continue

        results.append(
            MapillaryPhoto(
                image_id=item["id"],
                thumb_url=item.get("thumb_1024_url", ""),
                captured_at=int(item.get("captured_at", 0)),
                compass_angle=float(item.get("compass_angle", 0.0)),
                lat=float(item_lat),
                lng=float(item_lng),
            )
        )

    results.sort(key=lambda p: p.captured_at, reverse=True)
    return results
