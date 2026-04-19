"""PCMI7 / PCMI8 — Environment photo fetcher.

PCMI7 : Photographie de l'environnement proche (radius ≈ 30 m)
PCMI8 : Photographie de l'environnement lointain (radius ≈ 200 m, fov 120°)

Both functions try Mapillary first, then fall back to Google Street View.
All exceptions are caught and logged — the functions return None on failure
(mode dégradé: never block the dossier generation pipeline).
"""

from __future__ import annotations

import logging

from core.http_client import get_http_client
from core.sources.google_streetview import fetch_streetview_image
from core.sources.mapillary import fetch_photos_around

_logger = logging.getLogger(__name__)


async def _download_image(url: str) -> bytes | None:
    """Download image bytes from a URL via the shared HTTP client.

    Args:
        url: Absolute URL of the image to download.

    Returns:
        Raw image bytes, or ``None`` on any error.
    """
    try:
        client = get_http_client()
        response = await client.get(url)
        return response.content
    except Exception:
        _logger.warning("Failed to download image from %s", url, exc_info=True)
        return None


async def fetch_photo_environnement_proche(
    *, lat: float, lng: float
) -> bytes | None:
    """PCMI7: Fetch a street-level photo of the immediate environment.

    Strategy:
    1. Mapillary (radius 30 m) — download first photo's thumb_url.
    2. Fallback to Google Street View (default fov=90).
    3. Return None if both fail.

    Args:
        lat: Site latitude in WGS84 decimal degrees.
        lng: Site longitude in WGS84 decimal degrees.

    Returns:
        Image bytes, or ``None`` when no source is available.
    """
    # --- Try Mapillary first ---
    try:
        photos = await fetch_photos_around(lat=lat, lng=lng, radius_m=30)
        if photos:
            image_bytes = await _download_image(photos[0].thumb_url)
            if image_bytes:
                return image_bytes
    except Exception:
        _logger.warning(
            "Mapillary fetch failed for proche (%.6f, %.6f)", lat, lng, exc_info=True
        )

    # --- Fallback: Street View ---
    try:
        sv = await fetch_streetview_image(lat=lat, lng=lng)
        if sv is not None:
            image_bytes = await _download_image(sv.image_url)
            if image_bytes:
                return image_bytes
    except Exception:
        _logger.warning(
            "Street View fetch failed for proche (%.6f, %.6f)", lat, lng, exc_info=True
        )

    return None


async def fetch_photo_environnement_lointain(
    *, lat: float, lng: float
) -> bytes | None:
    """PCMI8: Fetch a street-level photo of the wider environment.

    Strategy:
    1. Mapillary (radius 200 m) — download first photo's thumb_url.
    2. Fallback to Google Street View with fov=120 (wide angle).
    3. Return None if both fail.

    Args:
        lat: Site latitude in WGS84 decimal degrees.
        lng: Site longitude in WGS84 decimal degrees.

    Returns:
        Image bytes, or ``None`` when no source is available.
    """
    # --- Try Mapillary first ---
    try:
        photos = await fetch_photos_around(lat=lat, lng=lng, radius_m=200)
        if photos:
            image_bytes = await _download_image(photos[0].thumb_url)
            if image_bytes:
                return image_bytes
    except Exception:
        _logger.warning(
            "Mapillary fetch failed for lointain (%.6f, %.6f)", lat, lng, exc_info=True
        )

    # --- Fallback: Street View with wide angle ---
    try:
        sv = await fetch_streetview_image(lat=lat, lng=lng, fov=120)
        if sv is not None:
            image_bytes = await _download_image(sv.image_url)
            if image_bytes:
                return image_bytes
    except Exception:
        _logger.warning(
            "Street View fetch failed for lointain (%.6f, %.6f)", lat, lng, exc_info=True
        )

    return None
