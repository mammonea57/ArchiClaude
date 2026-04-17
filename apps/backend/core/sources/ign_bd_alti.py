"""IGN BD ALTI altitude client.

API: https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json
No API key required.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.http_client import fetch_json

_ALTI_URL = "https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json"

# Sentinel value returned by the API when elevation is unavailable.
_NO_DATA_SENTINEL = -99999.0


@dataclass(frozen=True)
class AltitudeResult:
    """Structured result from a BD ALTI elevation query."""

    lat: float
    lng: float
    altitude_m: float


async def fetch_altitude(*, lat: float, lng: float) -> AltitudeResult | None:
    """Fetch the ground altitude at a WGS84 point from IGN BD ALTI.

    Args:
        lat: Latitude in WGS84 decimal degrees.
        lng: Longitude in WGS84 decimal degrees.

    Returns:
        An :class:`AltitudeResult` or ``None`` when the API returns no data or
        the sentinel value ``-99999``.

    Raises:
        httpx.HTTPStatusError: on non-2xx API responses.
    """
    params: dict[str, str | int | float] = {
        "lon": lng,
        "lat": lat,
        "zonly": "false",
    }
    data = await fetch_json(_ALTI_URL, params=params)

    elevations = data.get("elevations")
    if not elevations:
        return None

    first = elevations[0]
    z = first.get("z")
    if z is None or float(z) == _NO_DATA_SENTINEL:
        return None

    return AltitudeResult(
        lat=float(first.get("lat", lat)),
        lng=float(first.get("lon", lng)),
        altitude_m=float(z),
    )
