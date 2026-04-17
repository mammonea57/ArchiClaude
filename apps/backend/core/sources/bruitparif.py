"""Bruitparif IDF noise client.

Queries the Bruitparif API for Île-de-France specific noise exposure levels.
No API key required.

Returns None gracefully on any network or parsing error, or when no data
is available for the given location.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.http_client import fetch_json

_BRUITPARIF_URL = "https://rumeur.bruitparif.fr/api/v1/noise"

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BruitparifResult:
    """Noise exposure result from Bruitparif."""

    lden: float               # day-evening-night indicator in dB(A)
    lnight: float | None      # night-time indicator in dB(A), may be absent
    source_type: str | None   # "routier", "ferroviaire", "aerien"
    code_insee: str | None    # INSEE municipality code


async def fetch_bruit_idf(*, lat: float, lng: float) -> BruitparifResult | None:
    """Fetch noise exposure for the given WGS84 point from Bruitparif.

    Args:
        lat: Latitude in WGS84 decimal degrees.
        lng: Longitude in WGS84 decimal degrees.

    Returns:
        A :class:`BruitparifResult` when data is available, or ``None``
        when no data exists or any error occurs.
    """
    params: dict[str, str | int | float] = {
        "lat": lat,
        "lng": lng,
    }

    try:
        data = await fetch_json(_BRUITPARIF_URL, params=params)
    except Exception:
        _logger.warning("Bruitparif request failed — returning None", exc_info=True)
        return None

    if not data or "lden" not in data:
        return None

    try:
        lnight_raw = data.get("lnight")
        return BruitparifResult(
            lden=float(data["lden"]),
            lnight=float(lnight_raw) if lnight_raw is not None else None,
            source_type=data.get("source_type") or None,
            code_insee=data.get("code_insee") or None,
        )
    except (KeyError, ValueError, TypeError):
        _logger.warning("Bruitparif response malformed: %s", data)
        return None
