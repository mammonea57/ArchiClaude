"""API Carto IGN — module Cadastre.

Fetches parcel (parcelle) data from the IGN cadastre API.
No API key required.

API documentation: https://apicarto.ign.fr/api/doc/cadastre
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from core.http_client import fetch_json

_BASE_URL = "https://apicarto.ign.fr/api/cadastre/parcelle"


@dataclass(frozen=True)
class ParcelleResult:
    """Structured result from a cadastre parcel query."""

    code_insee: str
    section: str
    numero: str
    contenance_m2: int | None
    commune: str
    geometry: dict[str, Any]  # GeoJSON geometry


def _feature_to_result(feature: dict[str, Any]) -> ParcelleResult:
    """Convert a GeoJSON feature to a ParcelleResult."""
    props = feature.get("properties", {})
    # code_insee = code_dep + code_com (e.g. "94" + "052" = "94052")
    code_dep: str = props.get("code_dep", "")
    code_com: str = props.get("code_com", "")
    code_insee = code_dep + code_com

    raw_contenance = props.get("contenance")
    contenance_m2: int | None = int(raw_contenance) if raw_contenance is not None else None

    return ParcelleResult(
        code_insee=code_insee,
        section=props.get("section", ""),
        numero=props.get("numero", ""),
        contenance_m2=contenance_m2,
        commune=props.get("nom_com", ""),
        geometry=feature.get("geometry", {}),
    )


async def fetch_parcelle_by_ref(
    *,
    code_insee: str,
    section: str,
    numero: str,
) -> ParcelleResult | None:
    """Fetch a parcel by its cadastral reference (code_insee + section + numero).

    Args:
        code_insee: 5-character INSEE code (e.g. "94052").
        section: Cadastral section letters (e.g. "AB").
        numero: Parcel number, zero-padded to 4 digits (e.g. "0042").

    Returns:
        A :class:`ParcelleResult` or ``None`` if the parcel is not found.

    Raises:
        httpx.HTTPStatusError: on non-2xx API responses.
    """
    params: dict[str, str | int | float] = {
        "code_insee": code_insee,
        "section": section,
        "numero": numero,
    }
    data = await fetch_json(_BASE_URL, params=params)
    features = data.get("features", [])
    if not features:
        return None
    return _feature_to_result(features[0])


async def fetch_parcelle_at_point(
    *,
    lat: float,
    lng: float,
) -> ParcelleResult | None:
    """Fetch the parcel containing a WGS84 point.

    The GeoJSON Point geometry is JSON-serialised and passed as the ``geom``
    query parameter, as required by the API Carto IGN specification.

    Args:
        lat: Latitude in WGS84 decimal degrees.
        lng: Longitude in WGS84 decimal degrees.

    Returns:
        A :class:`ParcelleResult` or ``None`` if no parcel is found at the point.

    Raises:
        httpx.HTTPStatusError: on non-2xx API responses.
    """
    point_geom = json.dumps({"type": "Point", "coordinates": [lng, lat]})
    params: dict[str, str | int | float] = {"geom": point_geom}
    data = await fetch_json(_BASE_URL, params=params)
    features = data.get("features", [])
    if not features:
        return None
    return _feature_to_result(features[0])
