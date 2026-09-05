"""INPN — Inventaire National du Patrimoine Naturel — WFS client.

Fetches environmental protection overlays around a parcelle from the IGN
Géoplateforme WFS (which exposes INPN-published layers):

  - **Natura 2000 ZSC** (Sites d'Importance Communautaire — directive Habitats)
    layer: ``PROTECTEDAREAS.SIC:sic``
  - **Natura 2000 ZPS** (Zones de Protection Spéciale — directive Oiseaux)
    layer: ``PROTECTEDAREAS.ZPS:zps``
  - **ZNIEFF type 1 et 2** (Zones Naturelles d'Intérêt Écologique, Faunistique
    et Floristique)
    layers: ``PROTECTEDAREAS.ZNIEFF1:znieff1``, ``PROTECTEDAREAS.ZNIEFF2:znieff2``
  - **EBC** (Espaces Boisés Classés au sens L.113-1 CU) — proxy via la couche
    *forêts publiques* INPN ``PROTECTEDAREAS.FORESTS:forets_publiques``
    (les EBC stricto sensu sont publiés au PLU ; cette couche est utilisée
    en faisceau d'indices, le résultat est marqué dans ``notes``).

Output mapping
--------------
Returns a :class:`InpnBundle` and three Pydantic overlays from
:mod:`core.urbanism_overlays.schemas`:

  - :class:`~core.urbanism_overlays.schemas.Natura2000`
  - :class:`~core.urbanism_overlays.schemas.ZNIEFF`
  - :class:`~core.urbanism_overlays.schemas.EBC`

Each overlay has ``applies=True`` only when at least one feature was
returned by the corresponding WFS query.

Caching
-------
Responses are cached on disk under ``refs/cache/inpn_api/`` with a 30-day
TTL keyed by ``(layer, bbox)``. A cache hit short-circuits the network
call entirely; corrupted cache files are deleted and refetched.

Resilience
----------
* Per-layer try/except — a single failing layer does NOT prevent the
  others from being returned (mode dégradé).
* HTTP rate limiting (HTTP 429) and transient 5xx responses trigger
  exponential backoff (tenacity, 4 attempts, 0.5 → 8 s).
* All exceptions are logged with ``exc_info=True``; the caller never
  sees a crash, only empty lists / ``applies=False`` overlays.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from core.http_client import get_http_client
from core.urbanism_overlays.schemas import EBC, ZNIEFF, Natura2000

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_WFS_URL = "https://data.geopf.fr/wfs/ows"

# Per-layer source URL hint for the overlay's ``source_url`` field.
_INPN_PUBLIC_URL = "https://inpn.mnhn.fr/"

# Layer typeNames published by the IGN Géoplateforme (INPN data).
_LAYER_ZSC = "PROTECTEDAREAS.SIC:sic"
_LAYER_ZPS = "PROTECTEDAREAS.ZPS:zps"
_LAYER_ZNIEFF1 = "PROTECTEDAREAS.ZNIEFF1:znieff1"
_LAYER_ZNIEFF2 = "PROTECTEDAREAS.ZNIEFF2:znieff2"
# EBC proxy — public forests (PLU EBC are not in INPN; this is a faisceau
# d'indices to flag the parcelle for a manual PLU check).
_LAYER_EBC_PROXY = "PROTECTEDAREAS.FORESTS:forets_publiques"

# Cache configuration
_CACHE_TTL_SECONDS = 30 * 24 * 3600  # 30 days
_CACHE_DIR = Path(__file__).resolve().parents[4] / "refs" / "cache" / "inpn_api"

# WFS query defaults
_DEFAULT_COUNT = 100
_DEFAULT_RADIUS_M = 500.0  # 500 m around the parcelle by default


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InpnFeature:
    """A single environmental-protection feature returned by the INPN WFS."""

    layer: str                 # "ZSC", "ZPS", "ZNIEFF1", "ZNIEFF2", "EBC"
    sitecode: str | None       # e.g. "FR1100795"
    name: str                  # human-readable site name
    geometry: dict[str, Any] | None  # GeoJSON geometry (WGS84) or None
    properties: dict[str, Any] = field(default_factory=dict)


@dataclass
class InpnBundle:
    """Aggregated result of an INPN WFS query around a parcelle.

    The bundle exposes three Pydantic overlays ready to plug into
    :class:`~core.urbanism_overlays.schemas.UrbanismOverlayBundle`.
    """

    features: list[InpnFeature] = field(default_factory=list)
    natura2000: Natura2000 | None = None
    znieff: ZNIEFF | None = None
    ebc: EBC | None = None

    @property
    def feature_count(self) -> int:
        return len(self.features)

    def sample(self, n: int = 3) -> list[InpnFeature]:
        """Return up to *n* features for logging / diagnostics."""
        return self.features[:n]


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _cache_key(layer: str, bbox: str) -> str:
    """Stable cache key for a (layer, bbox) tuple."""
    h = hashlib.sha256(f"{layer}|{bbox}".encode()).hexdigest()[:16]
    safe_layer = layer.replace(":", "_").replace(".", "_")
    return f"{safe_layer}__{h}.json"


def _cache_path(layer: str, bbox: str) -> Path:
    return _CACHE_DIR / _cache_key(layer, bbox)


def _cache_load(layer: str, bbox: str) -> dict[str, Any] | None:
    """Return cached payload if present and within TTL, else None."""
    path = _cache_path(layer, bbox)
    if not path.exists():
        return None
    try:
        age = time.time() - path.stat().st_mtime
        if age > _CACHE_TTL_SECONDS:
            return None
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]
    except (OSError, json.JSONDecodeError):
        # Corrupted cache — delete and refetch.
        with contextlib.suppress(OSError):
            path.unlink()
        return None


def _cache_store(layer: str, bbox: str, payload: dict[str, Any]) -> None:
    """Persist payload to disk; failures are logged but never raised."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _cache_path(layer, bbox)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(payload, f)
        tmp.replace(path)
    except OSError:
        _logger.warning("INPN cache write failed for %s", layer, exc_info=True)


# ---------------------------------------------------------------------------
# BBOX & geometry helpers
# ---------------------------------------------------------------------------


def _bbox_from_point(lat: float, lng: float, radius_m: float) -> tuple[float, float, float, float]:
    """Build a WGS84 BBOX (minLng, minLat, maxLng, maxLat) of half-side ~radius_m.

    Degree approximations valid at 48°N (Île-de-France):
        1° latitude  ≈ 111 000 m
        1° longitude ≈  73 000 m
    """
    dlat = radius_m / 111_000
    dlng = radius_m / 73_000
    return (lng - dlng, lat - dlat, lng + dlng, lat + dlat)


def _bbox_str(bbox: tuple[float, float, float, float]) -> str:
    """Render BBOX as ``minLng,minLat,maxLng,maxLat`` for WFS GET."""
    return ",".join(f"{v:.6f}" for v in bbox)


# ---------------------------------------------------------------------------
# HTTP layer with rate-limit-aware retry
# ---------------------------------------------------------------------------


class _RateLimitedError(Exception):
    """Raised when the server returns 429 — caught by tenacity for backoff."""


class _TransientServerError(Exception):
    """Raised on 5xx — caught by tenacity for backoff."""


@retry(
    retry=retry_if_exception_type((
        _RateLimitedError,
        _TransientServerError,
        httpx.ConnectError,
        httpx.ReadTimeout,
    )),
    stop=stop_after_attempt(4),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=8),
    reraise=True,
)
async def _wfs_get(
    *,
    typename: str,
    bbox: tuple[float, float, float, float],
    count: int = _DEFAULT_COUNT,
) -> dict[str, Any]:
    """Issue a WFS GetFeature against the Géoplateforme.

    Returns the raw GeoJSON FeatureCollection. Raises:
      - :class:`_RateLimitedError` on 429 (retried by tenacity)
      - :class:`_TransientServerError` on 5xx (retried by tenacity)
      - :class:`httpx.HTTPStatusError` on any other non-2xx (re-raised, caller skips)
    """
    params: dict[str, str | int | float] = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": typename,
        "SRSNAME": "EPSG:4326",
        "BBOX": _bbox_str(bbox),
        "COUNT": count,
        "OUTPUTFORMAT": "application/json",
    }
    client = get_http_client()
    response = await client.get(_WFS_URL, params=params)
    if response.status_code == 429:
        raise _RateLimitedError(f"INPN WFS rate-limited for {typename}")
    if 500 <= response.status_code < 600:
        raise _TransientServerError(
            f"INPN WFS {response.status_code} for {typename}"
        )
    response.raise_for_status()
    return response.json()  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Feature parsing
# ---------------------------------------------------------------------------


def _feature_to_inpn(feature: dict[str, Any], layer_label: str) -> InpnFeature:
    """Convert a WFS GeoJSON feature to a typed :class:`InpnFeature`."""
    props = feature.get("properties") or {}
    # INPN exposes site codes under various names depending on the layer:
    sitecode = (
        props.get("sitecode")
        or props.get("site_code")
        or props.get("id_sic")
        or props.get("id_zps")
        or props.get("id_mnhn")
        or props.get("id_local")
    )
    name = (
        props.get("sitename")
        or props.get("nom")
        or props.get("nom_site")
        or props.get("libelle")
        or ""
    )
    geom = feature.get("geometry")
    return InpnFeature(
        layer=layer_label,
        sitecode=str(sitecode) if sitecode is not None else None,
        name=str(name),
        geometry=geom if geom else None,
        properties=props,
    )


# ---------------------------------------------------------------------------
# Per-layer fetcher (with cache + per-layer error handling)
# ---------------------------------------------------------------------------


async def _fetch_layer(
    *,
    typename: str,
    layer_label: str,
    bbox: tuple[float, float, float, float],
) -> list[InpnFeature]:
    """Fetch one INPN layer.

    Always returns a list — never raises. Uses the disk cache when fresh.
    """
    bbox_key = _bbox_str(bbox)
    cached = _cache_load(typename, bbox_key)
    if cached is not None:
        try:
            return [_feature_to_inpn(f, layer_label) for f in cached.get("features", [])]
        except Exception:
            _logger.warning("INPN cache parse failed for %s — refetching", typename, exc_info=True)

    try:
        data = await _wfs_get(typename=typename, bbox=bbox)
    except Exception:
        _logger.warning("INPN WFS layer %s unavailable — skipping", typename, exc_info=True)
        return []

    _cache_store(typename, bbox_key, data)
    return [_feature_to_inpn(f, layer_label) for f in data.get("features", [])]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def fetch_inpn_overlays(
    *,
    lat: float | None = None,
    lng: float | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    radius_m: float = _DEFAULT_RADIUS_M,
) -> InpnBundle:
    """Fetch INPN environmental overlays around a point or BBOX.

    One of ``(lat, lng)`` or ``bbox`` MUST be supplied. When both are given,
    *bbox* takes precedence.

    Args:
        lat: Latitude in WGS84 decimal degrees (paired with ``lng``).
        lng: Longitude in WGS84 decimal degrees (paired with ``lat``).
        bbox: ``(minLng, minLat, maxLng, maxLat)`` in WGS84.
        radius_m: When using ``(lat, lng)``, half-side of the BBOX (default 500 m).

    Returns:
        :class:`InpnBundle` with:

          - ``features``: aggregated list of every feature from every layer
          - ``natura2000``: :class:`Natura2000` overlay (``applies=True`` if any
            ZSC or ZPS feature intersects the BBOX)
          - ``znieff``: :class:`ZNIEFF` overlay (type 1 if any ZNIEFF1, else type 2)
          - ``ebc``: :class:`EBC` overlay (``applies=True`` if a public forest
            polygon intersects the BBOX — informative, must be cross-checked
            against the PLU EBC layer for a hard rule)

        On total failure (every layer errored) the bundle is empty but the
        overlays are still returned with ``applies=False`` so the caller can
        treat the absence as "no constraint detected" rather than crash.
    """
    if bbox is None:
        if lat is None or lng is None:
            raise ValueError("Either bbox or (lat, lng) must be supplied")
        bbox = _bbox_from_point(lat, lng, radius_m)

    # Fan-out per layer — independent try/except in _fetch_layer.
    zsc = await _fetch_layer(typename=_LAYER_ZSC, layer_label="ZSC", bbox=bbox)
    zps = await _fetch_layer(typename=_LAYER_ZPS, layer_label="ZPS", bbox=bbox)
    znieff1 = await _fetch_layer(typename=_LAYER_ZNIEFF1, layer_label="ZNIEFF1", bbox=bbox)
    znieff2 = await _fetch_layer(typename=_LAYER_ZNIEFF2, layer_label="ZNIEFF2", bbox=bbox)
    ebc_proxy = await _fetch_layer(typename=_LAYER_EBC_PROXY, layer_label="EBC", bbox=bbox)

    all_features: list[InpnFeature] = [*zsc, *zps, *znieff1, *znieff2, *ebc_proxy]

    bundle = InpnBundle(features=all_features)
    bundle.natura2000 = _build_natura2000(zsc, zps)
    bundle.znieff = _build_znieff(znieff1, znieff2)
    bundle.ebc = _build_ebc(ebc_proxy)

    _logger.info(
        "INPN fetch — ZSC=%d ZPS=%d ZNIEFF1=%d ZNIEFF2=%d EBC=%d (total=%d)",
        len(zsc), len(zps), len(znieff1), len(znieff2), len(ebc_proxy),
        len(all_features),
    )
    return bundle


# ---------------------------------------------------------------------------
# Overlay constructors
# ---------------------------------------------------------------------------


def _first_geom(features: list[InpnFeature]) -> dict[str, Any] | None:
    for f in features:
        if f.geometry is not None:
            return f.geometry
    return None


def _build_natura2000(zsc: list[InpnFeature], zps: list[InpnFeature]) -> Natura2000:
    has_zsc = bool(zsc)
    has_zps = bool(zps)
    if has_zsc and has_zps:
        zone = "ZSC/ZPS"
    elif has_zps:
        zone = "ZPS"
    else:
        zone = "ZSC"

    notes: list[str] = []
    for f in [*zsc, *zps]:
        if f.sitecode:
            notes.append(f"{f.layer} {f.sitecode}: {f.name}".strip())

    return Natura2000(
        applies=has_zsc or has_zps,
        type_zone=zone,  # type: ignore[arg-type]
        source_url=_INPN_PUBLIC_URL,
        last_updated=date.today(),
        geometry_geojson=_first_geom([*zsc, *zps]),
        notes=notes,
    )


def _build_znieff(znieff1: list[InpnFeature], znieff2: list[InpnFeature]) -> ZNIEFF:
    has_1 = bool(znieff1)
    has_2 = bool(znieff2)
    applies = has_1 or has_2
    # Type 1 is the more constraining — prefer it when both present.
    type_z = "1" if has_1 else "2"

    notes: list[str] = []
    for f in [*znieff1, *znieff2]:
        if f.sitecode or f.name:
            notes.append(f"{f.layer} {f.sitecode or ''}: {f.name}".strip())

    return ZNIEFF(
        applies=applies,
        type_znieff=type_z,  # type: ignore[arg-type]
        source_url=_INPN_PUBLIC_URL,
        last_updated=date.today(),
        geometry_geojson=_first_geom([*znieff1, *znieff2]),
        notes=notes,
    )


def _build_ebc(ebc_proxy: list[InpnFeature]) -> EBC:
    applies = bool(ebc_proxy)
    notes: list[str] = []
    if applies:
        notes.append(
            "EBC pré-détecté via couche forêts publiques INPN — "
            "vérifier la couche EBC du PLU communal (L.113-1 CU) pour confirmation"
        )
        for f in ebc_proxy:
            if f.name:
                notes.append(f"Forêt publique: {f.name}")

    return EBC(
        applies=applies,
        source_url=_INPN_PUBLIC_URL,
        last_updated=date.today(),
        geometry_geojson=_first_geom(ebc_proxy),
        notes=notes,
    )
