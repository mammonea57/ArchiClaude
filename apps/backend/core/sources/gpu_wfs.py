"""GPU (Géoportail de l'Urbanisme) loader via the IGN Géoplateforme WFS.

This module is the canonical entry point for fetching the four layer
families that constrain a parcelle from the GPU:

    * ``zone-urba``            — PLU/PLUi zoning polygons
    * ``prescription-*``       — graphical prescriptions (surface / linear / point)
    * ``assiette-sup-*``       — Servitudes d'Utilité Publique (SUP) assiettes
    * ``secteur-oap``          — sectoral OAPs

Endpoint base : ``https://data.geopf.fr/wfs/ows`` (OGC WFS 2.0.0,
``OUTPUTFORMAT=application/json``). No API key required.

Design notes
------------
* All network calls go through :func:`_fetch_wfs_layer` which:

  - caches every response on disk under ``refs/cache/gpu_wfs/`` for 30
    days (TTL configurable),
  - applies exponential backoff on transient failures (connect/timeout
    and 5xx, plus the 429 rate-limit response IGN serves),
  - never crashes the pipeline: on definitive failure the layer is
    skipped, a warning is logged, and an empty list is returned.

* Public callers either pass a (lat, lng) — converted to a ~50 m BBOX
  internally — or an explicit BBOX tuple ``(min_lng, min_lat, max_lng,
  max_lat)`` in WGS84.

* :func:`load_gpu_overlays` aggregates everything into a structured
  :class:`GpuWfsBundle` of dataclasses which the urbanism_overlays
  layer maps into Pydantic overlays (``PLUZonage``, ``OAPSectorielle``,
  ``SUP_*``, ``Prescription44`` …). The Pydantic models live in
  ``apps/backend/core/urbanism_overlays/schemas.py`` and we
  deliberately keep the mapping outside this module so the loader has
  zero upward dependency.

Reference :
  * IGN WFS catalogue : https://data.geopf.fr/wfs/ows?REQUEST=GetCapabilities
  * Layer index (CNIG) : https://cnig.gouv.fr/
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from core.http_client import get_http_client

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_WFS_URL = "https://data.geopf.fr/wfs/ows"

# Cache directory, anchored on the repository root (apps/backend/core/sources
# is 4 levels deep relative to refs/).
_CACHE_DIR = Path(__file__).resolve().parents[4] / "refs" / "cache" / "gpu_wfs"
_CACHE_TTL_SECONDS = 30 * 24 * 3600  # 30 days

# IGN WFS layer typenames for the GPU. The naming follows the CNIG
# nomenclature (su_doc_urba):
_TYPENAMES: dict[str, str] = {
    "zone_urba": "wfs_du:zone_urba",
    "prescription_surf": "wfs_du:prescription_surf",
    "prescription_lin": "wfs_du:prescription_lin",
    "prescription_pct": "wfs_du:prescription_pct",
    "assiette_sup_s": "wfs_sup:assiette_sup_s",
    "assiette_sup_l": "wfs_sup:assiette_sup_l",
    "assiette_sup_p": "wfs_sup:assiette_sup_p",
    "secteur_oap": "wfs_du:secteur_oap",
}

# Default radius used when the caller passes a point. 50 m is enough to
# capture the parcelle and its immediate neighbours.
_DEFAULT_RADIUS_M = 50.0

# Retry tuning
_MAX_ATTEMPTS = 4
_BACKOFF_BASE_S = 1.0
_BACKOFF_MAX_S = 30.0

# Status codes we retry (transient): connection/timeout exceptions are
# always retried; 429 + 5xx are retried with backoff; everything else
# is treated as a definitive failure.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


# ---------------------------------------------------------------------------
# Public dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GpuZoneFeature:
    """A single PLU zoning polygon."""

    libelle: str
    libelong: str | None
    typezone: str
    partition: str | None
    idurba: str | None
    nomfic: str | None
    urlfic: str | None
    geometry: dict[str, Any] | None


@dataclass(frozen=True)
class GpuPrescriptionFeature:
    """A single PLU prescription (surface, linear or point)."""

    libelle: str
    txt: str | None
    typepsc: str | None
    geom_kind: str  # "surf" | "lin" | "pct"
    geometry: dict[str, Any] | None


@dataclass(frozen=True)
class GpuSupFeature:
    """A single SUP (Servitude d'Utilité Publique) assiette."""

    libelle: str
    categorie: str
    txt: str | None
    geom_kind: str  # "s" | "l" | "p"
    geometry: dict[str, Any] | None


@dataclass(frozen=True)
class GpuOapSectorFeature:
    """A sectoral OAP polygon."""

    nom_oap: str
    type_oap: str | None
    txt: str | None
    geometry: dict[str, Any] | None


@dataclass
class GpuWfsBundle:
    """Aggregated GPU WFS payload for a parcelle.

    The bundle is intentionally flat: downstream code converts it into
    the structured Pydantic overlays from Phase 2.
    """

    bbox: tuple[float, float, float, float]
    zones: list[GpuZoneFeature] = field(default_factory=list)
    prescriptions: list[GpuPrescriptionFeature] = field(default_factory=list)
    sups: list[GpuSupFeature] = field(default_factory=list)
    oap_sectors: list[GpuOapSectorFeature] = field(default_factory=list)
    layer_errors: dict[str, str] = field(default_factory=dict)

    def feature_count(self) -> int:
        return (
            len(self.zones)
            + len(self.prescriptions)
            + len(self.sups)
            + len(self.oap_sectors)
        )

    def to_jsonable(self) -> dict[str, Any]:
        return {
            "bbox": list(self.bbox),
            "zones": [asdict(z) for z in self.zones],
            "prescriptions": [asdict(p) for p in self.prescriptions],
            "sups": [asdict(s) for s in self.sups],
            "oap_sectors": [asdict(o) for o in self.oap_sectors],
            "layer_errors": dict(self.layer_errors),
        }


# ---------------------------------------------------------------------------
# Geometry helpers
# ---------------------------------------------------------------------------


def _bbox_from_point(
    lat: float, lng: float, radius_m: float = _DEFAULT_RADIUS_M
) -> tuple[float, float, float, float]:
    """Return a WGS84 BBOX (min_lng, min_lat, max_lng, max_lat) around a point.

    Uses the same flat-earth approximation as :mod:`core.sources.ign_bdtopo`
    (1° lat ≈ 111 000 m, 1° lng ≈ 73 000 m at IDF latitudes). At a 50 m
    radius the error is sub-metre — adequate for WFS filtering.
    """
    dlat = radius_m / 111_000
    dlng = radius_m / 73_000
    return (lng - dlng, lat - dlat, lng + dlng, lat + dlat)


def _bbox_param(bbox: tuple[float, float, float, float]) -> str:
    """Serialise a BBOX tuple to the comma-separated string WFS expects."""
    return ",".join(f"{v:.7f}" for v in bbox)


# ---------------------------------------------------------------------------
# Disk cache
# ---------------------------------------------------------------------------


def _cache_key(typename: str, bbox: tuple[float, float, float, float]) -> str:
    """Stable SHA-1 cache key for (layer, bbox)."""
    payload = json.dumps({"t": typename, "b": [round(v, 7) for v in bbox]}, sort_keys=True)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _cache_path(key: str) -> Path:
    return _CACHE_DIR / f"{key}.json"


def _cache_read(key: str, ttl_s: int) -> dict[str, Any] | None:
    """Return cached payload if fresh, else ``None``."""
    path = _cache_path(key)
    if not path.exists():
        return None
    age = time.time() - path.stat().st_mtime
    if age > ttl_s:
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)  # type: ignore[no-any-return]
    except (OSError, json.JSONDecodeError):
        _logger.warning("Corrupt GPU WFS cache entry %s — ignoring", path)
        return None


def _cache_write(key: str, payload: dict[str, Any]) -> None:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = _cache_path(key)
    tmp = path.with_suffix(".tmp")
    try:
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        tmp.replace(path)
    except OSError as exc:
        _logger.warning("Could not write GPU WFS cache %s: %s", path, exc)


# ---------------------------------------------------------------------------
# WFS fetch with retry + cache
# ---------------------------------------------------------------------------


async def _wfs_get(
    typename: str,
    bbox: tuple[float, float, float, float],
    *,
    count: int = 200,
) -> dict[str, Any]:
    """Single WFS GET — raises on HTTP error.

    Kept thin so retry/backoff logic stays in :func:`_fetch_wfs_layer`.
    """
    params: dict[str, str | int | float] = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": typename,
        "SRSNAME": "EPSG:4326",
        "BBOX": f"{_bbox_param(bbox)},EPSG:4326",
        "COUNT": count,
        "OUTPUTFORMAT": "application/json",
    }
    client = get_http_client()
    response = await client.get(_WFS_URL, params=params)
    response.raise_for_status()
    return response.json()  # type: ignore[no-any-return]


async def _fetch_wfs_layer(
    typename: str,
    bbox: tuple[float, float, float, float],
    *,
    cache_ttl_s: int = _CACHE_TTL_SECONDS,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Fetch a WFS layer with cache + exponential backoff + graceful skip.

    Returns the parsed FeatureCollection or an empty one on failure. Never
    raises — this is the contract that lets the orchestrator log + skip
    instead of crashing.
    """
    key = _cache_key(typename, bbox)
    if use_cache:
        cached = _cache_read(key, cache_ttl_s)
        if cached is not None:
            _logger.debug("GPU WFS cache hit for %s", typename)
            return cached

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            data = await _wfs_get(typename, bbox)
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            last_exc = exc
            if status not in _RETRYABLE_STATUS:
                _logger.warning(
                    "GPU WFS %s — HTTP %s (definitive), skipping", typename, status
                )
                return {"type": "FeatureCollection", "features": [], "_error": f"HTTP {status}"}
            # Honour Retry-After if present (esp. on 429).
            retry_after = exc.response.headers.get("Retry-After")
            wait_s = (
                float(retry_after)
                if retry_after and retry_after.isdigit()
                else min(_BACKOFF_BASE_S * (2 ** (attempt - 1)), _BACKOFF_MAX_S)
            )
            _logger.info(
                "GPU WFS %s — HTTP %s on attempt %s/%s, retrying in %.1fs",
                typename, status, attempt, _MAX_ATTEMPTS, wait_s,
            )
            await asyncio.sleep(wait_s)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            last_exc = exc
            wait_s = min(_BACKOFF_BASE_S * (2 ** (attempt - 1)), _BACKOFF_MAX_S)
            _logger.info(
                "GPU WFS %s — %s on attempt %s/%s, retrying in %.1fs",
                typename, type(exc).__name__, attempt, _MAX_ATTEMPTS, wait_s,
            )
            await asyncio.sleep(wait_s)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            _logger.warning("GPU WFS %s — unexpected error: %r, skipping", typename, exc)
            return {
                "type": "FeatureCollection",
                "features": [],
                "_error": f"{type(exc).__name__}: {exc}",
            }
        else:
            if use_cache:
                _cache_write(key, data)
            return data

    _logger.warning(
        "GPU WFS %s — gave up after %s attempts (last error: %r)",
        typename, _MAX_ATTEMPTS, last_exc,
    )
    return {
        "type": "FeatureCollection",
        "features": [],
        "_error": f"giving up after {_MAX_ATTEMPTS} attempts: {last_exc!r}",
    }


# ---------------------------------------------------------------------------
# Feature → dataclass converters
# ---------------------------------------------------------------------------


def _geom_or_none(feature: dict[str, Any]) -> dict[str, Any] | None:
    geom = feature.get("geometry")
    return geom if geom else None


def _to_zone(feature: dict[str, Any]) -> GpuZoneFeature:
    props = feature.get("properties", {})
    return GpuZoneFeature(
        libelle=props.get("libelle", ""),
        libelong=props.get("libelong"),
        typezone=props.get("typezone", ""),
        partition=props.get("partition"),
        idurba=props.get("idurba"),
        nomfic=props.get("nomfic"),
        urlfic=props.get("urlfic"),
        geometry=_geom_or_none(feature),
    )


def _to_prescription(feature: dict[str, Any], kind: str) -> GpuPrescriptionFeature:
    props = feature.get("properties", {})
    return GpuPrescriptionFeature(
        libelle=props.get("libelle", ""),
        txt=props.get("txt"),
        typepsc=props.get("typepsc"),
        geom_kind=kind,
        geometry=_geom_or_none(feature),
    )


def _to_sup(feature: dict[str, Any], kind: str) -> GpuSupFeature:
    props = feature.get("properties", {})
    return GpuSupFeature(
        libelle=props.get("libelle", ""),
        categorie=props.get("categorie", ""),
        txt=props.get("txt"),
        geom_kind=kind,
        geometry=_geom_or_none(feature),
    )


def _to_oap_sector(feature: dict[str, Any]) -> GpuOapSectorFeature:
    props = feature.get("properties", {})
    return GpuOapSectorFeature(
        nom_oap=props.get("nom_oap", "") or props.get("libelle", ""),
        type_oap=props.get("type_oap"),
        txt=props.get("txt"),
        geometry=_geom_or_none(feature),
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def load_gpu_overlays(
    *,
    lat: float | None = None,
    lng: float | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    radius_m: float = _DEFAULT_RADIUS_M,
    cache_ttl_s: int = _CACHE_TTL_SECONDS,
    use_cache: bool = True,
) -> GpuWfsBundle:
    """Load every GPU WFS layer for a parcelle and return a structured bundle.

    Either pass ``(lat, lng)`` (a BBOX of ``radius_m`` is derived) or an
    explicit ``bbox=(min_lng, min_lat, max_lng, max_lat)``.

    Errors on individual layers are recorded in ``bundle.layer_errors``
    rather than propagated — the worst case is an empty bundle, never a
    crash.
    """
    if bbox is None:
        if lat is None or lng is None:
            raise ValueError("load_gpu_overlays requires either bbox= or both lat= and lng=")
        bbox = _bbox_from_point(lat, lng, radius_m)

    bundle = GpuWfsBundle(bbox=bbox)

    # Fan-out all layer fetches concurrently. Each task returns its own
    # FeatureCollection (or an empty one on failure) so we can use
    # gather() without worrying about exception leaks.
    layer_jobs = {
        name: _fetch_wfs_layer(
            typename, bbox, cache_ttl_s=cache_ttl_s, use_cache=use_cache
        )
        for name, typename in _TYPENAMES.items()
    }
    results = await asyncio.gather(*layer_jobs.values(), return_exceptions=False)
    payloads = dict(zip(layer_jobs.keys(), results, strict=True))

    # zone-urba
    for feature in payloads["zone_urba"].get("features", []):
        try:
            bundle.zones.append(_to_zone(feature))
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Failed to parse zone_urba feature: %r", exc)

    # prescriptions
    for kind, key in (("surf", "prescription_surf"), ("lin", "prescription_lin"), ("pct", "prescription_pct")):
        for feature in payloads[key].get("features", []):
            try:
                bundle.prescriptions.append(_to_prescription(feature, kind))
            except Exception as exc:  # noqa: BLE001
                _logger.warning("Failed to parse %s feature: %r", key, exc)

    # SUP
    for kind, key in (("s", "assiette_sup_s"), ("l", "assiette_sup_l"), ("p", "assiette_sup_p")):
        for feature in payloads[key].get("features", []):
            try:
                bundle.sups.append(_to_sup(feature, kind))
            except Exception as exc:  # noqa: BLE001
                _logger.warning("Failed to parse %s feature: %r", key, exc)

    # OAP sectorielle
    for feature in payloads["secteur_oap"].get("features", []):
        try:
            bundle.oap_sectors.append(_to_oap_sector(feature))
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Failed to parse secteur_oap feature: %r", exc)

    # Propagate per-layer error markers (set by _fetch_wfs_layer when it
    # gave up after retries or hit a non-retryable HTTP status).
    for name, payload in payloads.items():
        err = payload.get("_error")
        if err:
            bundle.layer_errors[name] = str(err)

    return bundle


__all__ = [
    "GpuOapSectorFeature",
    "GpuPrescriptionFeature",
    "GpuSupFeature",
    "GpuWfsBundle",
    "GpuZoneFeature",
    "load_gpu_overlays",
]
