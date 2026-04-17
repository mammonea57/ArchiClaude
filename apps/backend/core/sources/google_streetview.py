"""Google Street View Static API client — street-level imagery fallback.

API documentation: https://developers.google.com/maps/documentation/streetview
Requires GOOGLE_STREETVIEW_API_KEY environment variable.
Returns None gracefully when key is absent or no coverage exists.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from core.http_client import fetch_json

_METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
_IMAGE_URL = "https://maps.googleapis.com/maps/api/streetview"

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StreetViewImage:
    """A Google Street View image reference."""

    pano_id: str
    lat: float
    lng: float
    date: str | None  # "YYYY-MM" or None
    image_url: str    # fully constructed static image URL


async def fetch_streetview_image(
    *,
    lat: float,
    lng: float,
    heading: int = 0,
    fov: int = 90,
) -> StreetViewImage | None:
    """Fetch Street View metadata and construct an image URL for the given point.

    Checks the metadata endpoint first. If coverage exists (status == "OK"),
    constructs a 640x640 static image URL with the given heading and fov.

    Args:
        lat: Latitude in WGS84 decimal degrees.
        lng: Longitude in WGS84 decimal degrees.
        heading: Camera heading in degrees (0–360).
        fov: Field of view in degrees (default 90).

    Returns:
        A :class:`StreetViewImage` when coverage is available, or ``None``
        when the API key is absent, the location has no coverage, or any
        error occurs.
    """
    api_key = os.environ.get("GOOGLE_STREETVIEW_API_KEY")
    if not api_key:
        return None

    params: dict[str, str | int | float] = {
        "location": f"{lat},{lng}",
        "key": api_key,
    }

    try:
        metadata = await fetch_json(_METADATA_URL, params=params)
    except Exception:
        _logger.warning("Street View metadata request failed", exc_info=True)
        return None

    if metadata.get("status") != "OK":
        return None

    pano_id: str = metadata.get("pano_id", "")
    location = metadata.get("location", {})
    result_lat = float(location.get("lat", lat))
    result_lng = float(location.get("lng", lng))
    date: str | None = metadata.get("date")  # may be absent

    # Construct the static image URL (640×640)
    image_url = (
        f"{_IMAGE_URL}"
        f"?pano={pano_id}"
        f"&size=640x640"
        f"&heading={heading}"
        f"&fov={fov}"
        f"&key={api_key}"
    )

    return StreetViewImage(
        pano_id=pano_id,
        lat=result_lat,
        lng=result_lng,
        date=date,
        image_url=image_url,
    )
