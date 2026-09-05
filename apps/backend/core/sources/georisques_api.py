"""GeoRisques API v1 — comprehensive multi-endpoint client.

Fetches structured natural and technological risk data from the seven
public GeoRisques sub-APIs and maps the response into the Phase 2
:mod:`core.urbanism_overlays.schemas` Pydantic risk overlays.

Endpoints (Géorisques API v1 — 2025 schema)
-------------------------------------------
    PPRI / PPR      : ``/api/v1/gaspar/risques`` (filtered on inondation)
    RGA (argiles)   : ``/api/v1/rga``
    BASIAS (CASIAS) : ``/api/v1/ssp/casias``             (ex-BASIAS)
    BASOL           : ``/api/v1/ssp/instructions``       (ex-BASOL)
    SIS             : ``/api/v1/ssp/conclusions_sis``
    ICPE            : ``/api/v1/installations_classees``
    Cavités         : ``/api/v1/cavites``

The previous URLs (``/api/v1/basias_canvas``, ``/api/v1/basol``,
``/api/v1/sis``) were retired in the BRGM 2024/2025 Géorisques refactor —
all sites-et-sols-pollués (SSP) datasets are now nested under
``/api/v1/ssp/...``. The new payloads use ``latlon=<lon>,<lat>`` (note:
longitude first), ``rayon`` in metres, and return ``{data, results, page,
total_pages}`` envelopes consistent with the other v1 endpoints.

All endpoints accept either ``latlon=<lon>,<lat>`` + ``rayon`` (radius in
metres) or a BBOX (``ouest, sud, est, nord`` in WGS84). Both modes are
exposed via :func:`fetch_georisques_overlays`.

Reliability features
--------------------
* Local on-disk JSON cache at ``refs/cache/georisques_api/`` with a
  configurable TTL (default 30 days).
* Per-endpoint try/except so one HTTP failure does not abort the bundle.
* Manual exponential-backoff retry for the public ``fetch_*`` helpers
  (the shared :func:`core.http_client.fetch_json` already retries
  ``ConnectError`` / ``ReadTimeout`` 3×).
* On total failure: log warning, skip the endpoint, return empty list
  rather than raising.

Output
------
The high-level :func:`fetch_georisques_overlays` returns a list of
``_RisqueBase`` subclasses ready to be plugged into
:class:`UrbanismOverlayBundle.risques`. The lower-level
:func:`fetch_all_features` returns the raw dictionaries fetched from
each endpoint, useful for debugging and for the unit test.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from core.http_client import get_http_client
from core.urbanism_overlays.schemas import (
    BASIAS,
    BASOL,
    PPRI,
    RGA,
    SIS,
    Cavites,
    ICPE,
    _RisqueBase,
)

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASE_URL = "https://georisques.gouv.fr/api/v1"

ENDPOINTS: dict[str, str] = {
    "ppri": f"{_BASE_URL}/gaspar/risques",
    "rga": f"{_BASE_URL}/rga",
    # SSP sub-API (sites-et-sols-pollués) — 2024/2025 refactor.
    "basias": f"{_BASE_URL}/ssp/casias",
    "basol": f"{_BASE_URL}/ssp/instructions",
    "sis": f"{_BASE_URL}/ssp/conclusions_sis",
    "icpe": f"{_BASE_URL}/installations_classees",
    "cavites": f"{_BASE_URL}/cavites",
}

# Pollution-sols sub-set of ENDPOINTS — what `fetch_pollution_sols` queries.
POLLUTION_SOL_ENDPOINTS: tuple[str, ...] = ("basias", "basol", "sis")

# Cache lives at the project root, alongside refs/renders, refs/plu, etc.
# Resolves to <repo>/refs/cache/georisques_api/
_DEFAULT_CACHE_DIR = (
    Path(__file__).resolve().parents[4] / "refs" / "cache" / "georisques_api"
)
_DEFAULT_CACHE_TTL_S = 30 * 24 * 3600  # 30 days
_DEFAULT_RADIUS_M = 500
_DEFAULT_PAGE_SIZE = 50

# Backoff parameters for HTTP-level retries (429, 503, transient 5xx)
_BACKOFF_MAX_ATTEMPTS = 4
_BACKOFF_BASE_S = 0.5
_BACKOFF_CAP_S = 8.0


# ---------------------------------------------------------------------------
# Local file cache
# ---------------------------------------------------------------------------


def _cache_key(url: str, params: dict[str, Any]) -> str:
    """Stable SHA-1 of (url + sorted params) for a cache filename."""
    payload = json.dumps({"url": url, "params": params}, sort_keys=True, default=str)
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


def _cache_path(cache_dir: Path, key: str) -> Path:
    return cache_dir / f"{key}.json"


def _read_cache(
    cache_dir: Path, key: str, ttl_seconds: int
) -> dict[str, Any] | None:
    path = _cache_path(cache_dir, key)
    if not path.exists():
        return None
    try:
        mtime = path.stat().st_mtime
        if time.time() - mtime > ttl_seconds:
            return None
        with path.open() as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        _logger.warning("GeoRisques: corrupt cache entry at %s — ignoring", path)
        return None


def _write_cache(cache_dir: Path, key: str, payload: dict[str, Any]) -> None:
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = _cache_path(cache_dir, key)
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w") as f:
            json.dump(payload, f)
        tmp.replace(path)
    except OSError as exc:
        _logger.warning("GeoRisques: cache write failed (%s) — continuing", exc)


# ---------------------------------------------------------------------------
# Low-level HTTP fetch with exponential backoff
# ---------------------------------------------------------------------------


async def _fetch_with_backoff(
    url: str, params: dict[str, Any]
) -> dict[str, Any] | None:
    """GET ``url`` with manual exponential backoff for 429 / 5xx.

    Returns the parsed JSON on success, ``None`` on definitive failure
    (after all retries are exhausted or on a non-retryable HTTP error).
    """
    client = get_http_client()
    delay = _BACKOFF_BASE_S
    last_exc: Exception | None = None

    for attempt in range(1, _BACKOFF_MAX_ATTEMPTS + 1):
        try:
            response = await client.get(url, params=params)
            if response.status_code == 429 or 500 <= response.status_code < 600:
                _logger.warning(
                    "GeoRisques %s — HTTP %s (attempt %d/%d)",
                    url,
                    response.status_code,
                    attempt,
                    _BACKOFF_MAX_ATTEMPTS,
                )
                if attempt >= _BACKOFF_MAX_ATTEMPTS:
                    return None
                await asyncio.sleep(min(delay, _BACKOFF_CAP_S))
                delay *= 2
                continue
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, dict) else {"data": data}
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
            last_exc = exc
            _logger.warning(
                "GeoRisques %s — transport error %s (attempt %d/%d)",
                url, type(exc).__name__, attempt, _BACKOFF_MAX_ATTEMPTS,
            )
            if attempt >= _BACKOFF_MAX_ATTEMPTS:
                return None
            await asyncio.sleep(min(delay, _BACKOFF_CAP_S))
            delay *= 2
        except httpx.HTTPStatusError as exc:
            # Non-retryable (4xx other than 429) — log and bail.
            _logger.warning("GeoRisques %s — HTTP %s, skipping", url, exc.response.status_code)
            return None
        except Exception as exc:  # pragma: no cover — defensive
            last_exc = exc
            _logger.warning("GeoRisques %s — unexpected error %s", url, exc, exc_info=True)
            return None

    if last_exc is not None:
        _logger.warning("GeoRisques %s — gave up after %d attempts (%s)",
                        url, _BACKOFF_MAX_ATTEMPTS, last_exc)
    return None


# ---------------------------------------------------------------------------
# Cached fetch (cache → backoff → cache write)
# ---------------------------------------------------------------------------


async def _cached_fetch(
    url: str,
    params: dict[str, Any],
    *,
    cache_dir: Path,
    ttl_seconds: int,
    use_cache: bool,
) -> dict[str, Any] | None:
    key = _cache_key(url, params)
    if use_cache:
        hit = _read_cache(cache_dir, key, ttl_seconds)
        if hit is not None:
            return hit
    payload = await _fetch_with_backoff(url, params)
    if payload is not None and use_cache:
        _write_cache(cache_dir, key, payload)
    return payload


# ---------------------------------------------------------------------------
# Public fetch
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GeorisquesQuery:
    """Coordinates input for the GeoRisques API.

    Either ``lat``/``lng`` (point + radius) **or** ``bbox`` must be given;
    when both are present ``bbox`` wins.
    """

    lat: float | None = None
    lng: float | None = None
    rayon: int = _DEFAULT_RADIUS_M
    bbox: tuple[float, float, float, float] | None = None  # (west, south, east, north)
    page_size: int = _DEFAULT_PAGE_SIZE

    def base_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {"page_size": self.page_size}
        if self.bbox is not None:
            west, south, east, north = self.bbox
            # GeoRisques BBOX format = "lon_min,lat_min,lon_max,lat_max"
            params["bbox"] = f"{west},{south},{east},{north}"
        elif self.lat is not None and self.lng is not None:
            params["latlon"] = f"{self.lng},{self.lat}"
            params["rayon"] = self.rayon
        else:
            raise ValueError("GeorisquesQuery: provide either (lat, lng) or bbox")
        return params


@dataclass
class GeorisquesFetchResult:
    """Aggregated raw payloads + overlays for one query."""

    overlays: list[_RisqueBase] = field(default_factory=list)
    raw_by_endpoint: dict[str, dict[str, Any]] = field(default_factory=dict)
    feature_counts: dict[str, int] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def total_features(self) -> int:
        return sum(self.feature_counts.values())


def _features_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract the list of feature dicts from a GeoRisques v1 payload.

    The v1 API consistently nests results under ``data`` (older endpoints)
    or ``features`` (GeoJSON-flavoured ones). We accept both and fall back
    to the empty list rather than crashing on a schema surprise.
    """
    if not isinstance(payload, dict):
        return []
    for k in ("data", "features", "results"):
        v = payload.get(k)
        if isinstance(v, list):
            return [item for item in v if isinstance(item, dict)]
    return []


# ---------------------------------------------------------------------------
# Endpoint → overlay mappers
# ---------------------------------------------------------------------------


def _zone_alea_from_label(label: str) -> str:
    """Map a free-text aléa label to the PPRI zone literal."""
    s = (label or "").lower()
    if "rouge" in s:
        return "rouge"
    if "orange" in s:
        return "orange"
    if "bleu" in s:
        return "bleu"
    return "blanc"


def _ppri_overlays(features: list[dict[str, Any]]) -> list[PPRI]:
    out: list[PPRI] = []
    for f in features:
        risk_type = (f.get("type_risque") or f.get("libelle_risque") or "").lower()
        if "inond" not in risk_type and f.get("code_risque", "").lower().find("ppri") < 0:
            continue
        zone = _zone_alea_from_label(
            f.get("niveau_alea") or f.get("libelle_alea") or ""
        )
        out.append(PPRI(
            applies=True,
            zone_alea=zone,  # type: ignore[arg-type]
            aleas=["inondation"],
            source_url=ENDPOINTS["ppri"],
            notes=[f.get("libelle_risque", "PPRI")],
        ))
    return out


def _rga_overlays(features: list[dict[str, Any]]) -> list[RGA]:
    out: list[RGA] = []
    for f in features:
        niveau = (f.get("niveau_alea") or f.get("classe") or "faible").lower()
        if niveau not in {"faible", "moyen", "fort"}:
            niveau = "faible"
        out.append(RGA(
            applies=True,
            niveau=niveau,  # type: ignore[arg-type]
            aleas=["retrait-gonflement argiles"],
            source_url=ENDPOINTS["rga"],
            notes=[f.get("libelle_alea", "RGA")],
        ))
    return out


def _basias_overlays(features: list[dict[str, Any]]) -> list[BASIAS]:
    return [
        BASIAS(
            applies=True,
            aleas=["pollution sol"],
            source_url=ENDPOINTS["basias"],
            notes=[
                # CASIAS v1 payload: nom_etablissement + activite_principale.
                str(
                    f.get("nom_etablissement")
                    or f.get("nom_usuel")
                    or f.get("raison_sociale")
                    or f.get("activite_principale")
                    or "Site BASIAS"
                ),
            ],
        )
        for f in features
    ]


def _basol_overlays(features: list[dict[str, Any]]) -> list[BASOL]:
    return [
        BASOL(
            applies=True,
            aleas=["pollution sol avérée"],
            source_url=ENDPOINTS["basol"],
            notes=[
                # SSP instructions v1 payload: nom_etablissement + statut.
                str(
                    f.get("nom_etablissement")
                    or f.get("nom_usuel")
                    or f.get("nom")
                    or "Site BASOL"
                ),
            ],
        )
        for f in features
    ]


def _sis_overlays(features: list[dict[str, Any]]) -> list[SIS]:
    return [
        SIS(
            applies=True,
            aleas=["sol pollué — SIS"],
            source_url=ENDPOINTS["sis"],
            notes=[str(f.get("nom") or f.get("statut_classification") or "SIS")],
        )
        for f in features
    ]


def _icpe_overlays(features: list[dict[str, Any]]) -> list[ICPE]:
    out: list[ICPE] = []
    for f in features:
        rayon_str = f.get("rayon_effets") or f.get("rayon_etude")
        try:
            rayon = float(rayon_str) if rayon_str is not None else None
        except (TypeError, ValueError):
            rayon = None
        out.append(ICPE(
            applies=True,
            rayon_effets_m=rayon,
            type_etablissement=str(f.get("regime") or f.get("type_etablissement") or "")
            or None,
            aleas=["ICPE proximité"],
            source_url=ENDPOINTS["icpe"],
            notes=[str(f.get("nom_etablissement") or f.get("raison_sociale") or "ICPE")],
        ))
    return out


def _cavites_overlays(features: list[dict[str, Any]]) -> list[Cavites]:
    return [
        Cavites(
            applies=True,
            aleas=["cavité souterraine"],
            source_url=ENDPOINTS["cavites"],
            notes=[str(f.get("nature") or f.get("libelle") or "Cavité")],
        )
        for f in features
    ]


_MAPPERS = {
    "ppri": _ppri_overlays,
    "rga": _rga_overlays,
    "basias": _basias_overlays,
    "basol": _basol_overlays,
    "sis": _sis_overlays,
    "icpe": _icpe_overlays,
    "cavites": _cavites_overlays,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def fetch_all_features(
    query: GeorisquesQuery,
    *,
    cache_dir: Path | None = None,
    ttl_seconds: int = _DEFAULT_CACHE_TTL_S,
    use_cache: bool = True,
    endpoints: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Fetch raw payloads from every endpoint and return them keyed by name.

    Endpoints that fail are simply absent from the returned dict (their
    error is logged). This keeps the function side-effect free for the
    caller's overlay assembly.
    """
    cache_dir = cache_dir or _DEFAULT_CACHE_DIR
    selected = endpoints or list(ENDPOINTS.keys())
    params_base = query.base_params()

    async def _one(name: str) -> tuple[str, dict[str, Any] | None]:
        url = ENDPOINTS[name]
        try:
            payload = await _cached_fetch(
                url, params_base,
                cache_dir=cache_dir, ttl_seconds=ttl_seconds, use_cache=use_cache,
            )
            return name, payload
        except Exception as exc:  # pragma: no cover — backoff already swallows
            _logger.warning("GeoRisques %s failed: %s", name, exc, exc_info=True)
            return name, None

    results = await asyncio.gather(*(_one(n) for n in selected))
    return {name: payload for name, payload in results if payload is not None}


async def fetch_georisques_overlays(
    *,
    lat: float | None = None,
    lng: float | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    rayon: int = _DEFAULT_RADIUS_M,
    cache_dir: Path | None = None,
    ttl_seconds: int = _DEFAULT_CACHE_TTL_S,
    use_cache: bool = True,
    endpoints: list[str] | None = None,
) -> GeorisquesFetchResult:
    """Fetch every risk endpoint and translate the result to overlays.

    Args:
        lat, lng: Centre of the query in WGS84 (decimal degrees).
        bbox: Alternative to ``lat``/``lng``: ``(west, south, east, north)``.
        rayon: Radius in metres around the point (ignored when ``bbox`` is set).
        cache_dir: Override the default ``refs/cache/georisques_api/`` directory.
        ttl_seconds: Cache TTL (default 30 days).
        use_cache: Disable to force a network fetch (e.g. in tests).
        endpoints: Restrict the call to a subset of :data:`ENDPOINTS`.

    Returns:
        A :class:`GeorisquesFetchResult` aggregating overlays, raw payloads,
        per-endpoint feature counts, and per-endpoint errors. Never raises.
    """
    query = GeorisquesQuery(lat=lat, lng=lng, rayon=rayon, bbox=bbox)
    result = GeorisquesFetchResult()

    raw_by_endpoint = await fetch_all_features(
        query,
        cache_dir=cache_dir,
        ttl_seconds=ttl_seconds,
        use_cache=use_cache,
        endpoints=endpoints,
    )

    for name, payload in raw_by_endpoint.items():
        features = _features_from_payload(payload)
        result.raw_by_endpoint[name] = payload
        result.feature_counts[name] = len(features)
        mapper = _MAPPERS.get(name)
        if mapper is None or not features:
            continue
        try:
            result.overlays.extend(mapper(features))
        except Exception as exc:
            _logger.warning("GeoRisques mapper %s failed: %s", name, exc, exc_info=True)
            result.errors[name] = str(exc)

    # Endpoints absent from raw_by_endpoint failed -> record as missing.
    for name in (endpoints or ENDPOINTS.keys()):
        if name not in raw_by_endpoint:
            result.errors.setdefault(name, "fetch_failed")
            result.feature_counts.setdefault(name, 0)

    return result


__all__ = [
    "ENDPOINTS",
    "GeorisquesFetchResult",
    "GeorisquesQuery",
    "fetch_all_features",
    "fetch_georisques_overlays",
]
