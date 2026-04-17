"""IGN WFS transport stops client (Géoplateforme).

Fetches public transport stops (metro, RER, tram, bus) from the IGN BDTOPO
WFS endpoint. No API key required.

Computes haversine distance from the query point and sorts results by
distance ascending.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

from core.http_client import fetch_json

_WFS_URL = "https://data.geopf.fr/wfs/ows"
_TYPENAME = "BDTOPO_V3:transport_par_cable"  # main stops layer
_STOPS_TYPENAME = "BDTOPO_V3:zone_d_activites_ou_d_interet"

_logger = logging.getLogger(__name__)

# Nature values that indicate public transport stops
_NATURE_TO_MODE: dict[str, str] = {
    "Gare": "gare",
    "Gare ferroviaire": "gare",
    "Station de métro": "metro",
    "Station de RER": "RER",
    "Station de tramway": "tram",
    "Arrêt de bus": "bus",
    "Arrêt de car": "bus",
    "Station de bus": "bus",
}


@dataclass(frozen=True)
class ArretTC:
    """A public transport stop."""

    nom: str
    mode: str              # metro, RER, tram, bus, gare
    ligne: str | None
    exploitant: str | None
    lat: float
    lng: float
    distance_m: float | None = None


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the great-circle distance in metres between two WGS84 points."""
    r = 6_371_000.0  # Earth mean radius in metres
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _classify_mode(nature: str | None) -> str:
    """Return a normalised transport mode string from the IGN 'nature' attribute."""
    if not nature:
        return "bus"
    for key, mode in _NATURE_TO_MODE.items():
        if key.lower() in nature.lower():
            return mode
    return "bus"


async def fetch_arrets_around(
    *, lat: float, lng: float, radius_m: int = 500
) -> list[ArretTC]:
    """Fetch public transport stops within *radius_m* metres of the given point.

    Queries the IGN BDTOPO WFS for transport stops in the bounding box,
    then filters to those within *radius_m* using haversine distance and
    sorts by distance ascending.

    Args:
        lat: Latitude in WGS84 decimal degrees.
        lng: Longitude in WGS84 decimal degrees.
        radius_m: Maximum distance in metres from the centre point.

    Returns:
        List of :class:`ArretTC` sorted by distance ascending.
        Returns ``[]`` on any error (graceful degradation).
    """
    dlat = radius_m / 111_000
    dlng = radius_m / 73_000

    west = lng - dlng
    south = lat - dlat
    east = lng + dlng
    north = lat + dlat
    bbox = f"{west},{south},{east},{north},EPSG:4326"

    params: dict[str, str | int | float] = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": _STOPS_TYPENAME,
        "BBOX": bbox,
        "OUTPUTFORMAT": "application/json",
        "COUNT": 100,
    }

    try:
        data = await fetch_json(_WFS_URL, params=params)
    except Exception:
        _logger.warning("IGN transports WFS request failed — returning empty", exc_info=True)
        return []

    results: list[ArretTC] = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        geom = feature.get("geometry", {})
        coords = geom.get("coordinates", [None, None])

        if coords[0] is None or coords[1] is None:
            continue

        stop_lng, stop_lat = float(coords[0]), float(coords[1])
        nature: str | None = props.get("nature")
        mode = _classify_mode(nature)

        dist = _haversine_m(lat, lng, stop_lat, stop_lng)
        if dist > radius_m:
            continue

        results.append(
            ArretTC(
                nom=str(props.get("nom", props.get("toponyme", ""))),
                mode=mode,
                ligne=props.get("ligne") or None,
                exploitant=props.get("exploitant") or None,
                lat=stop_lat,
                lng=stop_lng,
                distance_m=round(dist, 1),
            )
        )

    results.sort(key=lambda a: a.distance_m or 0.0)
    return results
