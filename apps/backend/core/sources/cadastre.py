"""IGN Géoplateforme — module Cadastre (parcelles).

Fetches parcel (parcelle) data from the IGN Géoplateforme WFS service.
No API key required.

Migration note: previously used `apicarto.ign.fr/api/cadastre/parcelle`
which was a thin wrapper around `CADASTRALPARCELS.PARCELLAIRE_EXPRESS:parcelle`
on the WFS service. IGN deprecated that feature type in 2026; the
replacement is `BDPARCELLAIRE-VECTEUR_WLD_BDD_WGS84G:parcelle` on
`data.geopf.fr/wfs/ows`. The new feature lacks a `contenance` property
so we compute the area from the geometry (Lambert-93 reprojection).

Authoritative address→parcelle resolution
-----------------------------------------

BAN geocoding returns a lat/lng on the **street threshold** of the
building, not inside the parcelle polygon. A strict point-in-polygon
query routinely fails and the nearest-parcelle fallback snaps to a
neighbour (wrong section, wrong PLU zone).

The authoritative source is the ``BAN-PLUS:lien_adresse_parcelle`` WFS
layer published on Géoplateforme: each BAN identifier
(``id_adr`` — same as ``properties.id`` on a BAN feature) is linked to
the IDU of its actual parcelle. Use :func:`resolve_parcelle_via_ban_link`
whenever you have a BAN id; fall back to :func:`fetch_parcelle_at_point`
only when the BAN id is missing.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from shapely.geometry import shape
from shapely.ops import transform as shp_transform
from pyproj import Transformer

from core.http_client import fetch_json

log = logging.getLogger(__name__)

_WFS_URL = "https://data.geopf.fr/wfs/ows"
_TYPENAME = "BDPARCELLAIRE-VECTEUR_WLD_BDD_WGS84G:parcelle"
_BAN_LINK_TYPENAME = "BAN-PLUS:lien_adresse_parcelle"

_TO_LAMBERT93 = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True).transform

# ---------------------------------------------------------------------------
# BAN-PLUS local cache (30-day TTL)
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BAN_LINK_CACHE_DIR = _REPO_ROOT / "refs" / "cache" / "ban_plus"
_BAN_LINK_TTL_S = 30 * 24 * 3600  # 30 days


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


def _parse_idu(idu: str) -> tuple[str, str, str] | None:
    """Split an IDU (14 chars) into ``(code_insee, section, numero)``.

    Layout (cf. CNIG / DGFiP) : ``DDDDD CCC SS NNNN``
      - 5 chars : code INSEE (department + commune)
      - 3 chars : commune absorbée (000 when not applicable)
      - 2 chars : section
      - 4 chars : numéro

    Returns ``None`` for any IDU that does not match the expected length.
    """
    if not idu or len(idu) != 14:
        return None
    code_insee = idu[0:5]
    # idu[5:8] = com_abs (000 when none)
    section = idu[8:10]
    numero = idu[10:14]
    return code_insee, section, numero


def _ban_link_cache_path(ban_id: str) -> Path:
    """Return the on-disk cache path for a BAN id link lookup.

    BAN ids contain underscores and a colon-free alphanumeric pattern, so
    we can use them directly as filenames without escaping.
    """
    safe = ban_id.replace("/", "_").replace("\\", "_")
    return _BAN_LINK_CACHE_DIR / f"{safe}.json"


def _read_ban_link_cache(ban_id: str) -> dict[str, Any] | None:
    """Return cached lien_adresse_parcelle JSON when fresh, else ``None``."""
    path = _ban_link_cache_path(ban_id)
    if not path.is_file():
        return None
    try:
        age = time.time() - path.stat().st_mtime
        if age > _BAN_LINK_TTL_S:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.warning("ban_link cache read failed for %s: %s", ban_id, exc)
        return None


def _write_ban_link_cache(ban_id: str, payload: dict[str, Any]) -> None:
    """Persist the lien_adresse_parcelle JSON for offline + 30-day reuse."""
    try:
        _BAN_LINK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _ban_link_cache_path(ban_id).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("ban_link cache write failed for %s: %s", ban_id, exc)


async def _fetch_ban_link(ban_id: str) -> dict[str, Any] | None:
    """Query ``BAN-PLUS:lien_adresse_parcelle`` for *ban_id* with 30-day cache.

    Returns the raw FeatureCollection JSON, or ``None`` on HTTP error.
    """
    cached = _read_ban_link_cache(ban_id)
    if cached is not None:
        return cached
    params = {
        "service": "WFS",
        "version": "2.0.0",
        "request": "GetFeature",
        "typeNames": _BAN_LINK_TYPENAME,
        "outputFormat": "application/json",
        "srsname": "EPSG:4326",
        "CQL_FILTER": f"id_adr='{ban_id}'",
    }
    try:
        data = await fetch_json(_WFS_URL, params=params)
    except Exception as exc:  # noqa: BLE001
        log.warning("BAN-PLUS lien_adresse_parcelle fetch failed for %s: %s", ban_id, exc)
        return None
    _write_ban_link_cache(ban_id, data)
    return data


async def resolve_parcelle_via_ban_link(ban_id: str) -> ParcelleResult | None:
    """Resolve the authoritative parcelle linked to a BAN address id.

    Uses the ``BAN-PLUS:lien_adresse_parcelle`` WFS layer to look up the
    IDU bound to *ban_id*, then fetches the parcelle polygon from
    ``BDPARCELLAIRE-VECTEUR_WLD_BDD_WGS84G:parcelle``.

    This is the **only** reliable address→parcelle path: a naive
    point-in-polygon on the BAN lat/lng commonly snaps to the wrong
    parcelle (the BAN coord sits on the street threshold).

    Args:
        ban_id: BAN identifier from
            :attr:`core.sources.ban.GeocodingResult.ban_id`
            (e.g. ``94052_4430_00080``).

    Returns:
        A :class:`ParcelleResult` or ``None`` when no link exists or the
        IDU is malformed.
    """
    if not ban_id:
        return None
    data = await _fetch_ban_link(ban_id)
    if not data:
        return None
    features = data.get("features") or []
    if not features:
        return None
    props = features[0].get("properties", {})
    idu: str = props.get("idu", "") or ""
    parsed = _parse_idu(idu)
    if parsed is None:
        log.warning("BAN-PLUS returned malformed IDU %r for ban_id=%s", idu, ban_id)
        return None
    code_insee, section, numero = parsed
    return await fetch_parcelle_by_ref(
        code_insee=code_insee, section=section, numero=numero,
    )


async def resolve_parcelle_for_geocode(
    *,
    ban_id: str | None,
    lat: float,
    lng: float,
) -> ParcelleResult | None:
    """Resolve the parcelle for a geocoded address.

    Tries the authoritative BAN-PLUS link first (when *ban_id* is provided)
    and falls back to point-in-polygon on the cadastre WFS otherwise.

    Logs ``[parcelle] via BAN link`` or ``[parcelle] via PIP fallback`` so
    operators can see which path was used in dossier pipelines.
    """
    if ban_id:
        result = await resolve_parcelle_via_ban_link(ban_id)
        if result is not None:
            log.info(
                "[parcelle] via BAN link → %s%s%s (%s m²) ban_id=%s",
                result.code_insee, result.section, result.numero,
                result.contenance_m2, ban_id,
            )
            return result
        log.warning(
            "[parcelle] BAN link missing or malformed for ban_id=%s — falling back to PIP",
            ban_id,
        )
    else:
        log.info("[parcelle] no ban_id — using PIP fallback at (%.6f, %.6f)", lat, lng)
    result = await fetch_parcelle_at_point(lat=lat, lng=lng)
    if result is not None:
        log.info(
            "[parcelle] via PIP fallback → %s%s%s (%s m²)",
            result.code_insee, result.section, result.numero, result.contenance_m2,
        )
    return result


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
