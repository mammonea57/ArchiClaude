"""IGN Géoplateforme — module Cadastre (parcelles).

Fetches parcel (parcelle) data from the IGN Géoplateforme WFS service.
No API key required.

Migration note: previously used `apicarto.ign.fr/api/cadastre/parcelle`
which was a thin wrapper around `CADASTRALPARCELS.PARCELLAIRE_EXPRESS:parcelle`
on the WFS service. IGN deprecated that feature type in 2026; the
replacement is `BDPARCELLAIRE-VECTEUR_WLD_BDD_WGS84G:parcelle` on
`data.geopf.fr/wfs/ows`. The new feature lacks a `contenance` property
so we compute the area from the geometry (Lambert-93 reprojection).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from shapely.geometry import shape
from shapely.ops import transform as shp_transform
from pyproj import Transformer

from core.http_client import fetch_json

_WFS_URL = "https://data.geopf.fr/wfs/ows"
_TYPENAME = "BDPARCELLAIRE-VECTEUR_WLD_BDD_WGS84G:parcelle"

_TO_LAMBERT93 = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True).transform


@dataclass(frozen=True)
class ParcelleResult:
    """Structured result from a cadastre parcel query."""

    code_insee: str
    section: str
    numero: str
    contenance_m2: int | None
    commune: str
    geometry: dict[str, Any]  # GeoJSON geometry, WGS84 lon/lat


def _compute_contenance_m2(geom_geojson: dict[str, Any]) -> int | None:
    """Compute parcelle area in m² by reprojecting WGS84 → Lambert-93."""
    if not geom_geojson:
        return None
    try:
        geom = shape(geom_geojson)
        projected = shp_transform(_TO_LAMBERT93, geom)
        return int(round(projected.area))
    except Exception:
        return None


def _feature_to_result(feature: dict[str, Any]) -> ParcelleResult:
    """Convert a GeoJSON feature to a ParcelleResult."""
    props = feature.get("properties", {})
    code_dep: str = props.get("code_dep", "")
    code_com: str = props.get("code_com", "")
    code_insee = code_dep + code_com

    geometry = feature.get("geometry", {})
    contenance_m2 = _compute_contenance_m2(geometry)

    return ParcelleResult(
        code_insee=code_insee,
        section=props.get("section", ""),
        numero=props.get("numero", ""),
        contenance_m2=contenance_m2,
        commune=props.get("nom_com", ""),
        geometry=geometry,
    )


async def _wfs_get_feature(
    *,
    cql_filter: str | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    count: int = 1,
) -> list[dict[str, Any]]:
    """Issue a WFS GetFeature request and return the features list."""
    params: dict[str, str | int | float] = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeName": _TYPENAME,
        "srsname": "EPSG:4326",
        "outputFormat": "application/json",
        "count": count,
    }
    if cql_filter is not None:
        params["CQL_FILTER"] = cql_filter
    if bbox is not None:
        west, south, east, north = bbox
        params["BBOX"] = f"{west},{south},{east},{north},EPSG:4326"
    data = await fetch_json(_WFS_URL, params=params)
    return data.get("features", []) or []


async def fetch_parcelle_by_ref(
    *,
    code_insee: str,
    section: str,
    numero: str,
) -> ParcelleResult | None:
    """Fetch a parcel by its cadastral reference.

    Args:
        code_insee: 5-character INSEE code (department code + commune code, e.g. "94052").
        section: Cadastral section (e.g. "AB" or "0G"). Padded to 2 chars when shorter.
        numero: Parcel number, zero-padded to 4 digits (e.g. "0042").

    Returns:
        A :class:`ParcelleResult` or ``None`` if the parcel is not found.
    """
    if len(code_insee) != 5:
        return None
    code_dep = code_insee[:2]
    code_com = code_insee[2:]
    cql = (
        f"code_dep='{code_dep}' AND code_com='{code_com}' "
        f"AND section='{section}' AND numero='{numero}'"
    )
    features = await _wfs_get_feature(cql_filter=cql, count=1)
    if not features:
        return None
    return _feature_to_result(features[0])


async def fetch_parcelle_at_point(
    *,
    lat: float,
    lng: float,
) -> ParcelleResult | None:
    """Fetch the parcel containing a WGS84 point.

    Uses a tiny BBOX around the point and picks the first feature whose
    polygon actually contains the point (BBOX may match adjacent parcelles).

    Args:
        lat: Latitude in WGS84 decimal degrees.
        lng: Longitude in WGS84 decimal degrees.

    Returns:
        A :class:`ParcelleResult` or ``None`` if no parcel is found at the point.
    """
    from shapely.geometry import Point

    delta = 0.0002  # ≈ 22 m at latitude 48° — small enough to limit candidates
    bbox = (lng - delta, lat - delta, lng + delta, lat + delta)
    features = await _wfs_get_feature(bbox=bbox, count=10)
    if not features:
        return None

    point = Point(lng, lat)
    for feat in features:
        try:
            geom = shape(feat.get("geometry", {}))
            if geom.contains(point) or geom.buffer(1e-6).contains(point):
                return _feature_to_result(feat)
        except Exception:
            continue
    # Fallback: nearest parcelle (BBOX matched but no exact containment)
    return _feature_to_result(features[0])
