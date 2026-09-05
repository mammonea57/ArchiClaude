"""Atlas Patrimoine — Monuments Historiques (Ministère de la Culture).

Fetches Monuments Historiques (classés / inscrits) around a parcelle.

Source : Plateforme ouverte du patrimoine — data.culture.gouv.fr
Dataset : ``liste-des-immeubles-proteges-au-titre-des-monuments-historiques``
API     : OpenDataSoft Explore v2.1 (records endpoint with ``where`` and
          ``within_distance`` geo-filter on ``coordonnees_au_format_wgs84``).
No API key required.

Notes (2026-06 — schema migration) :
  * The legacy ``geo_point_2d`` field was removed from the dataset; the
    canonical geo field is now ``coordonnees_au_format_wgs84`` (a
    ``{"lat":..., "lon":...}`` point).
  * In ODSQL v2.1 the radius geo-filter is ``within_distance(field, geom,
    radius)`` — ``in_distance`` is no longer recognised in the ``where``
    clause.

Two query modes :
  * ``fetch_mh_around_point(lat, lng, radius_m)`` — radius search around a point
  * ``fetch_mh_in_bbox(bbox)`` — bounding-box search ``(west, south, east, north)``

Both modes return a list of :class:`AtlasPatrimoineFeature` dataclasses, plus
a helper :func:`build_atlas_patrimoine_mh_overlays` that maps each feature to
an :class:`AtlasPatrimoineMH` schema instance from the urbanism overlays.

Local cache (``refs/cache/atlas_patrimoine/``) with a 30-day TTL is used to
avoid hammering the API during repeated dossier runs. Cache entries are keyed
by the query parameters (rounded to ~10 m so neighbouring lookups share a
cache entry).

Error handling : log + skip + return empty rather than crash. The dossier
pipeline should never crash because a third-party API is unavailable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from core.http_client import get_http_client
from core.urbanism_overlays.schemas import AtlasPatrimoineMH

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# OpenDataSoft Explore v2.1 records endpoint.
_BASE_URL = (
    "https://data.culture.gouv.fr/api/explore/v2.1/catalog/datasets/"
    "liste-des-immeubles-proteges-au-titre-des-monuments-historiques/records"
)
_SOURCE_PORTAL_URL = (
    "https://data.culture.gouv.fr/explore/dataset/"
    "liste-des-immeubles-proteges-au-titre-des-monuments-historiques/"
)

# Cache lives next to the other ArchiClaude refs.
_REPO_ROOT = Path(__file__).resolve().parents[4]
_CACHE_DIR = _REPO_ROOT / "refs" / "cache" / "atlas_patrimoine"
_CACHE_TTL_SECONDS = 30 * 24 * 3600  # 30 days

# Rate-limit / backoff configuration.
_MAX_ATTEMPTS = 4
_BACKOFF_BASE_S = 0.5
_BACKOFF_MAX_S = 8.0

# Default search radius (m) around the parcelle for the "near-by MH" lookup.
DEFAULT_RADIUS_M = 500.0
# OpenDataSoft caps records page size at 100; ample for a 500 m radius lookup.
_PAGE_LIMIT = 100


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AtlasPatrimoineFeature:
    """A single Monument Historique feature."""

    designation: str
    protection: str  # "classé" / "inscrit" / "classé et inscrit" / ...
    commune: str
    code_insee: str | None
    departement: str | None
    adresse: str | None
    date_protection: str | None
    reference_merimee: str | None  # PA000xxxx etc.
    lat: float | None
    lng: float | None
    distance_m: float | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------


def _cache_key(payload: dict[str, Any]) -> str:
    """Stable hash of the query payload."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(blob, usedforsecurity=False).hexdigest()


def _cache_path(key: str) -> Path:
    return _CACHE_DIR / f"{key}.json"


def _load_from_cache(key: str) -> dict[str, Any] | None:
    """Return cached payload if fresh, else ``None``."""
    p = _cache_path(key)
    if not p.exists():
        return None
    try:
        age = time.time() - p.stat().st_mtime
        if age > _CACHE_TTL_SECONDS:
            return None
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)  # type: ignore[no-any-return]
    except Exception:
        _logger.warning("Atlas Patrimoine cache read failed for %s", p, exc_info=True)
        return None


def _save_to_cache(key: str, payload: dict[str, Any]) -> None:
    """Persist payload to cache. Failures are logged & swallowed."""
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with _cache_path(key).open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception:
        _logger.warning("Atlas Patrimoine cache write failed for %s", key, exc_info=True)


# ---------------------------------------------------------------------------
# HTTP fetch with exponential backoff
# ---------------------------------------------------------------------------


async def _fetch_with_backoff(params: dict[str, Any]) -> dict[str, Any] | None:
    """GET the records endpoint with retries on rate-limit / transient errors.

    Returns the parsed JSON body or ``None`` if the request ultimately fails.
    Never raises — the dossier pipeline must keep running in mode dégradé.
    """
    client = get_http_client()
    delay = _BACKOFF_BASE_S
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            resp = await client.get(_BASE_URL, params=params)
        except (httpx.ConnectError, httpx.ReadTimeout, httpx.TransportError) as exc:
            _logger.warning(
                "Atlas Patrimoine transport error (attempt %d/%d): %s",
                attempt, _MAX_ATTEMPTS, exc,
            )
            if attempt >= _MAX_ATTEMPTS:
                return None
            await asyncio.sleep(min(delay + random.uniform(0, 0.25), _BACKOFF_MAX_S))
            delay = min(delay * 2, _BACKOFF_MAX_S)
            continue

        # Rate limit / server error → exponential backoff.
        if resp.status_code in (429, 500, 502, 503, 504):
            retry_after = resp.headers.get("Retry-After")
            try:
                wait_s = float(retry_after) if retry_after else delay
            except ValueError:
                wait_s = delay
            wait_s = min(wait_s + random.uniform(0, 0.25), _BACKOFF_MAX_S)
            _logger.warning(
                "Atlas Patrimoine HTTP %s — retrying in %.1fs (attempt %d/%d)",
                resp.status_code, wait_s, attempt, _MAX_ATTEMPTS,
            )
            if attempt >= _MAX_ATTEMPTS:
                return None
            await asyncio.sleep(wait_s)
            delay = min(delay * 2, _BACKOFF_MAX_S)
            continue

        if resp.status_code >= 400:
            _logger.warning(
                "Atlas Patrimoine HTTP %s — giving up (no retry): %s",
                resp.status_code, resp.text[:200],
            )
            return None

        try:
            return resp.json()  # type: ignore[no-any-return]
        except Exception:
            _logger.warning("Atlas Patrimoine JSON decode failed", exc_info=True)
            return None
    return None


# ---------------------------------------------------------------------------
# Feature parsing
# ---------------------------------------------------------------------------


def _first(d: dict[str, Any], *keys: str) -> Any:
    """Return the first non-empty value among the candidate keys."""
    for k in keys:
        v = d.get(k)
        if v not in (None, "", []):
            return v
    return None


def _extract_lat_lng(record: dict[str, Any]) -> tuple[float | None, float | None]:
    """Best-effort lat/lng extraction across OpenDataSoft schema variants.

    The MH dataset historically used ``coordonnees`` then ``geo_point_2d``;
    the current (v2.1 schema, 2026) field is ``coordonnees_au_format_wgs84``.
    We accept all three plus a GeoJSON ``geometry`` fallback.
    """
    gp = (
        record.get("coordonnees_au_format_wgs84")
        or record.get("geo_point_2d")
        or record.get("coordonnees")
    )
    if isinstance(gp, dict):
        lat = gp.get("lat")
        lng = gp.get("lon") or gp.get("lng") or gp.get("longitude")
        if lat is not None and lng is not None:
            return float(lat), float(lng)
    if isinstance(gp, (list, tuple)) and len(gp) >= 2:
        try:
            return float(gp[0]), float(gp[1])
        except (TypeError, ValueError):
            pass
    if isinstance(gp, str) and "," in gp:
        try:
            a, b = (s.strip() for s in gp.split(",", 1))
            return float(a), float(b)
        except ValueError:
            pass

    geom = record.get("geo_shape") or record.get("geometry")
    if isinstance(geom, dict):
        # GeoJSON geometry — take the first coordinate of a Point/MultiPoint;
        # fall back to bounding box centroid for polygons.
        coords = geom.get("coordinates")
        gtype = geom.get("type", "")
        if gtype == "Point" and isinstance(coords, (list, tuple)) and len(coords) >= 2:
            return float(coords[1]), float(coords[0])
        if gtype in ("MultiPoint", "LineString") and coords:
            first = coords[0]
            if isinstance(first, (list, tuple)) and len(first) >= 2:
                return float(first[1]), float(first[0])
    return None, None


def _record_to_feature(record: dict[str, Any]) -> AtlasPatrimoineFeature:
    """Convert one OpenDataSoft record to our dataclass.

    Field aliases handle both the legacy schema (``denomination``,
    ``statut_juridique``, ``commune``, etc.) and the current 2026 schema
    (``titre_editorial_de_la_notice``, ``typologie_de_la_protection``,
    ``commune_forme_editoriale``, ``reference`` for the Mérimée id, ...).
    """
    designation = _first(
        record,
        "titre_editorial_de_la_notice",
        "denomination",
        "denomination_de_l_edifice",
        "appellation_courante",
        "titre_courant",
        "nom",
    ) or "Monument historique"
    protection = _first(
        record,
        "typologie_de_la_protection",
        "date_et_typologie_de_la_protection",
        "statut_juridique",
        "statut",
        "protection_label",
        "protection",
    ) or ""
    commune = _first(
        record, "commune_forme_editoriale", "commune", "nom_commune", "ville",
    ) or ""
    code_insee_raw = _first(
        record,
        "cog_insee_lors_de_la_protection",
        "code_insee",
        "code_insee_commune",
        "insee_commune",
    )
    if isinstance(code_insee_raw, list) and code_insee_raw:
        code_insee_raw = code_insee_raw[0]
    code_insee = str(code_insee_raw).zfill(5) if code_insee_raw else None
    departement_raw = _first(
        record, "departement_en_lettres", "departement",
    )
    if isinstance(departement_raw, list) and departement_raw:
        departement_raw = departement_raw[0]
    departement = departement_raw
    adresse = _first(
        record,
        "adresse_forme_editoriale",
        "adresse",
        "adresse_normalisee",
        "adresse_complete",
        "adresse_forme_index",
    )
    date_protection = _first(
        record,
        "date_de_la_derniere_etape_de_protection",
        "date_protection",
        "date_de_protection",
        "date_et_typologie_de_la_protection",
    )
    reference_merimee = _first(
        record, "reference", "reference_de_la_notice_merimee", "ref",
    )
    lat, lng = _extract_lat_lng(record)

    return AtlasPatrimoineFeature(
        designation=str(designation),
        protection=str(protection),
        commune=str(commune),
        code_insee=code_insee,
        departement=str(departement) if departement else None,
        adresse=str(adresse) if adresse else None,
        date_protection=str(date_protection) if date_protection else None,
        reference_merimee=str(reference_merimee) if reference_merimee else None,
        lat=lat,
        lng=lng,
        raw=record,
    )


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres."""
    from math import asin, cos, radians, sin, sqrt

    r = 6_371_000.0
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = radians(lat2 - lat1), radians(lng2 - lng1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return float(2 * r * asin(sqrt(a)))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def fetch_mh_around_point(
    *,
    lat: float,
    lng: float,
    radius_m: float = DEFAULT_RADIUS_M,
    limit: int = _PAGE_LIMIT,
    use_cache: bool = True,
) -> list[AtlasPatrimoineFeature]:
    """Return Monuments Historiques within ``radius_m`` of ``(lat, lng)``.

    Args:
        lat: WGS84 latitude (decimal degrees).
        lng: WGS84 longitude (decimal degrees).
        radius_m: Search radius in metres (capped to 50 km).
        limit: Max records to fetch (≤ 100, OpenDataSoft hard cap per page).
        use_cache: If False, skip the local cache (force-refresh).

    Returns:
        List of :class:`AtlasPatrimoineFeature`. Empty list on any failure.
    """
    radius_m = max(10.0, min(float(radius_m), 50_000.0))
    limit = max(1, min(int(limit), _PAGE_LIMIT))

    # Round lat/lng to ~10 m so neighbouring iterations share cache entries.
    key_payload = {
        "mode": "point",
        "lat": round(float(lat), 4),
        "lng": round(float(lng), 4),
        "radius_m": round(float(radius_m), 0),
        "limit": limit,
    }
    key = _cache_key(key_payload)

    if use_cache:
        cached = _load_from_cache(key)
        if cached is not None:
            return [_record_to_feature(r) for r in cached.get("results", [])]

    where = (
        f"within_distance(coordonnees_au_format_wgs84, "
        f"geom'POINT({lng} {lat})', {int(radius_m)}m)"
    )
    params = {"where": where, "limit": limit}
    payload = await _fetch_with_backoff(params)
    if payload is None:
        return []

    results = payload.get("results") or payload.get("records") or []
    if use_cache:
        _save_to_cache(key, {"results": results})

    features = [_record_to_feature(r) for r in results]

    # Annotate with Haversine distance to the query point.
    annotated: list[AtlasPatrimoineFeature] = []
    for f in features:
        if f.lat is None or f.lng is None:
            annotated.append(f)
            continue
        d = _haversine_m(lat, lng, f.lat, f.lng)
        annotated.append(
            AtlasPatrimoineFeature(
                designation=f.designation,
                protection=f.protection,
                commune=f.commune,
                code_insee=f.code_insee,
                departement=f.departement,
                adresse=f.adresse,
                date_protection=f.date_protection,
                reference_merimee=f.reference_merimee,
                lat=f.lat,
                lng=f.lng,
                distance_m=round(d, 1),
                raw=f.raw,
            )
        )
    annotated.sort(key=lambda x: (x.distance_m is None, x.distance_m or 0.0))
    return annotated


async def fetch_mh_in_bbox(
    *,
    bbox: tuple[float, float, float, float],
    limit: int = _PAGE_LIMIT,
    use_cache: bool = True,
) -> list[AtlasPatrimoineFeature]:
    """Return Monuments Historiques inside ``bbox`` = ``(west, south, east, north)``.

    Coordinates are WGS84 (lon/lat). Empty list on any failure.
    """
    west, south, east, north = bbox
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        _logger.warning("Atlas Patrimoine: invalid bbox %s", bbox)
        return []

    limit = max(1, min(int(limit), _PAGE_LIMIT))

    key_payload = {
        "mode": "bbox",
        "bbox": [round(west, 4), round(south, 4), round(east, 4), round(north, 4)],
        "limit": limit,
    }
    key = _cache_key(key_payload)

    if use_cache:
        cached = _load_from_cache(key)
        if cached is not None:
            return [_record_to_feature(r) for r in cached.get("results", [])]

    # OpenDataSoft accepts a bbox via in_bbox(<geo_field>, lat_min, lon_min,
    # lat_max, lon_max). The dataset's canonical geo field is now
    # ``coordonnees_au_format_wgs84``.
    where = (
        f"in_bbox(coordonnees_au_format_wgs84, "
        f"{south}, {west}, {north}, {east})"
    )
    params = {"where": where, "limit": limit}
    payload = await _fetch_with_backoff(params)
    if payload is None:
        return []

    results = payload.get("results") or payload.get("records") or []
    if use_cache:
        _save_to_cache(key, {"results": results})

    return [_record_to_feature(r) for r in results]


def build_atlas_patrimoine_mh_overlays(
    features: list[AtlasPatrimoineFeature],
) -> list[AtlasPatrimoineMH]:
    """Convert features into Phase-2 :class:`AtlasPatrimoineMH` overlays.

    The overlay's ``applies`` flag is set ``True`` only when at least one
    coordinate is present (we cannot constrain a project from an MH whose
    location we don't know).
    """
    out: list[AtlasPatrimoineMH] = []
    for f in features:
        designation = f.designation
        if f.protection:
            designation = f"{designation} ({f.protection})"
        if f.distance_m is not None:
            designation = f"{designation} — {f.distance_m:.0f} m"
        notes: list[str] = []
        if f.reference_merimee:
            notes.append(f"Réf. Mérimée : {f.reference_merimee}")
        if f.adresse:
            notes.append(f"Adresse : {f.adresse}")
        if f.commune:
            notes.append(f"Commune : {f.commune}")
        if f.date_protection:
            notes.append(f"Date protection : {f.date_protection}")

        overlay = AtlasPatrimoineMH(
            applies=f.lat is not None and f.lng is not None,
            designation=designation,
            source_url=_SOURCE_PORTAL_URL,
            notes=notes,
        )
        out.append(overlay)
    return out


__all__ = [
    "AtlasPatrimoineFeature",
    "DEFAULT_RADIUS_M",
    "build_atlas_patrimoine_mh_overlays",
    "fetch_mh_around_point",
    "fetch_mh_in_bbox",
]


# ---------------------------------------------------------------------------
# Debug helper — `python -m core.sources.atlas_patrimoine`
# ---------------------------------------------------------------------------


async def _main_demo() -> None:  # pragma: no cover - manual smoke
    """Quick smoke test against the live API."""
    # Nogent-sur-Marne — 80 rue des Héros (approx).
    lat, lng = 48.83558, 2.4810
    features = await fetch_mh_around_point(lat=lat, lng=lng, radius_m=750)
    print(f"Atlas Patrimoine — fetched {len(features)} feature(s) around ({lat}, {lng})")
    for f in features[:5]:
        d = f"{f.distance_m:.0f} m" if f.distance_m is not None else "?"
        print(f"  · {d:>7}  {f.designation}  [{f.protection}]  {f.commune}")
    if features:
        print("\nSample (1st feature) as dict:")
        sample = {k: v for k, v in asdict(features[0]).items() if k != "raw"}
        print(json.dumps(sample, indent=2, ensure_ascii=False))


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main_demo())
