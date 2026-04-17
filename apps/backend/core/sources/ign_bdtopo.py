"""IGN BDTopo WFS client — building footprints, heights, and usage.

API: https://data.geopf.fr/wfs/ows (OGC WFS 2.0)
Layer: BDTOPO_V3:batiment
No API key required.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.http_client import fetch_json

_WFS_URL = "https://data.geopf.fr/wfs/ows"


@dataclass(frozen=True)
class BatimentResult:
    """Structured result from a BDTopo batiment WFS query."""

    hauteur: float | None
    nb_etages: int | None
    usage: str | None
    altitude_sol: float | None
    altitude_toit: float | None
    geometry: dict[str, Any] | None


def _bbox_from_point(lat: float, lng: float, radius_m: float) -> str:
    """Compute an approximate WGS84 BBOX string from a point and radius.

    Uses simple degree approximations:
        1° latitude  ≈ 111 000 m
        1° longitude ≈  73 000 m  (at ~48°N, valid for IDF)

    Returns a comma-separated string: ``minLng,minLat,maxLng,maxLat``.
    """
    dlat = radius_m / 111_000
    dlng = radius_m / 73_000
    min_lat = lat - dlat
    max_lat = lat + dlat
    min_lng = lng - dlng
    max_lng = lng + dlng
    return f"{min_lng},{min_lat},{max_lng},{max_lat}"


def _feature_to_result(feature: dict[str, Any]) -> BatimentResult:
    """Convert a GeoJSON WFS feature to a BatimentResult."""
    props = feature.get("properties", {})

    raw_hauteur = props.get("hauteur")
    hauteur: float | None = float(raw_hauteur) if raw_hauteur is not None else None

    raw_etages = props.get("nombre_d_etages_sur_rez_de_chaussee")
    nb_etages: int | None = int(raw_etages) if raw_etages is not None else None

    raw_alt_sol = props.get("altitude_minimale_sol")
    altitude_sol: float | None = float(raw_alt_sol) if raw_alt_sol is not None else None

    raw_alt_toit = props.get("altitude_maximale_toit")
    altitude_toit: float | None = float(raw_alt_toit) if raw_alt_toit is not None else None

    geom = feature.get("geometry")

    return BatimentResult(
        hauteur=hauteur,
        nb_etages=nb_etages,
        usage=props.get("usage_1"),
        altitude_sol=altitude_sol,
        altitude_toit=altitude_toit,
        geometry=geom if geom else None,
    )


async def fetch_batiments_around(
    *,
    lat: float,
    lng: float,
    radius_m: float = 100,
) -> list[BatimentResult]:
    """Fetch BDTopo building footprints within *radius_m* metres of a WGS84 point.

    Args:
        lat: Latitude in WGS84 decimal degrees.
        lng: Longitude in WGS84 decimal degrees.
        radius_m: Search radius in metres (default 100).

    Returns:
        List of :class:`BatimentResult`. Empty list when no buildings are found.

    Raises:
        httpx.HTTPStatusError: on non-2xx API responses.
    """
    bbox = _bbox_from_point(lat, lng, radius_m)
    params: dict[str, str | int | float] = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": "BDTOPO_V3:batiment",
        "SRSNAME": "EPSG:4326",
        "BBOX": bbox,
        "COUNT": 200,
        "OUTPUTFORMAT": "application/json",
    }
    data = await fetch_json(_WFS_URL, params=params)
    return [_feature_to_result(f) for f in data.get("features", [])]
