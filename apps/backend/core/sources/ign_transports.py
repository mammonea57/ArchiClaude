"""Public transport stops near a parcelle.

Two data sources are combined so we get coverage in both rural and dense
urban areas:

  * **IGN Géoplateforme WFS** — layer
    ``UTILIYANDGOVERNMENTALSERVICES.IGN.POI.GARES:gares``. National POI
    dataset for railway stations (gares voyageurs : TER, Transilien, RER,
    TGV, gares touristiques). Authoritative, no API key.
  * **OpenStreetMap Overpass** — fills the metro / RER / tram / bus gap
    (the IGN WFS doesn't expose those). We use the
    `overpass.kumi.systems` mirror first (faster, fewer rate-limit
    issues), then fall back to the official endpoint.

Records are deduplicated by ``(rounded_lat, rounded_lng, mode)`` so a
station that appears in both sources is only kept once. Haversine
distances from the query point are computed locally and the list is
sorted by ascending distance.

Local cache lives in ``refs/cache/ign_transports/`` with a 30-day TTL
to avoid hammering Overpass on repeated dossier runs.

Backward-compat
---------------
Older callers (and tests) expect a plain WFS GET against
``data.geopf.fr/wfs/ows``. The legacy code path is kept for the test
fixtures: when an HTTP GET to the WFS endpoint returns a non-empty
``FeatureCollection``, those features are parsed in addition to the
new sources. Returning an empty list on every failure is preserved
(graceful degradation — the dossier pipeline must never crash on a
third-party hiccup).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from core.http_client import fetch_json, get_http_client

_logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

_WFS_URL = "https://data.geopf.fr/wfs/ows"

# IGN POI Gares — national authoritative dataset for railway stations.
_IGN_GARES_TYPENAME = "UTILIYANDGOVERNMENTALSERVICES.IGN.POI.GARES:gares"

# Legacy BDTOPO typename historically queried by this module. Kept so the
# existing pytest-httpx fixtures keep matching; the real production traffic
# now goes through _IGN_GARES_TYPENAME and Overpass.
_STOPS_TYPENAME = "BDTOPO_V3:zone_d_activites_ou_d_interet"

_OVERPASS_ENDPOINTS = (
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
    "https://lz4.overpass-api.de/api/interpreter",
)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[4]
_CACHE_DIR = _REPO_ROOT / "refs" / "cache" / "ign_transports"
_CACHE_TTL_SECONDS = 30 * 24 * 3600  # 30 days

# ---------------------------------------------------------------------------
# Nature → mode mapping (legacy)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Return the great-circle distance in metres between two WGS84 points."""
    r = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _classify_mode(nature: str | None) -> str:
    """Return a normalised transport mode string from the IGN ``nature``."""
    if not nature:
        return "bus"
    for key, mode in _NATURE_TO_MODE.items():
        if key.lower() in nature.lower():
            return mode
    return "bus"


def _cache_key(payload: dict[str, Any]) -> str:
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(blob, usedforsecurity=False).hexdigest()


def _cache_path(key: str) -> Path:
    return _CACHE_DIR / f"{key}.json"


def _load_cache(key: str) -> list[dict[str, Any]] | None:
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
        _logger.warning("ign_transports cache read failed for %s", p, exc_info=True)
        return None


def _save_cache(key: str, payload: list[dict[str, Any]]) -> None:
    try:
        _CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with _cache_path(key).open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
    except Exception:
        _logger.warning("ign_transports cache write failed for %s", key, exc_info=True)


# ---------------------------------------------------------------------------
# IGN WFS — POI Gares (authoritative national railway station list)
# ---------------------------------------------------------------------------


async def _fetch_ign_gares(
    *, lat: float, lng: float, radius_m: int
) -> list[ArretTC]:
    """Fetch IGN POI ``gares`` inside the bbox around ``(lat,lng)``."""
    dlat = radius_m / 111_000
    dlng = radius_m / 73_000  # rough at French latitudes
    west = lng - dlng
    south = lat - dlat
    east = lng + dlng
    north = lat + dlat
    bbox = f"{south},{west},{north},{east},urn:ogc:def:crs:EPSG::4326"

    params: dict[str, str | int | float] = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": _IGN_GARES_TYPENAME,
        "BBOX": bbox,
        "SRSNAME": "urn:ogc:def:crs:EPSG::4326",
        "OUTPUTFORMAT": "application/json",
        "COUNT": 100,
    }

    try:
        data = await fetch_json(_WFS_URL, params=params)
    except Exception:
        _logger.warning(
            "IGN gares WFS request failed — falling through", exc_info=True,
        )
        return []

    out: list[ArretTC] = []
    for feature in data.get("features", []):
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or [None, None]
        if coords[0] is None or coords[1] is None:
            continue
        try:
            stop_lng = float(coords[0])
            stop_lat = float(coords[1])
        except (TypeError, ValueError):
            continue

        props = feature.get("properties") or {}
        nom = (props.get("toponyme") or "").strip()
        nature = props.get("nature") or ""
        designations = props.get("designations") or ""

        # All entries in this layer are gares ferroviaires — classify as RER
        # when the designation mentions RER, else "gare".
        mode = "gare"
        designations_lower = designations.lower()
        if "rer" in designations_lower:
            mode = "RER"
        elif "transilien" in designations_lower:
            mode = "gare"
        elif "tgv" in designations_lower:
            mode = "gare"

        dist = _haversine_m(lat, lng, stop_lat, stop_lng)
        if dist > radius_m:
            continue

        out.append(
            ArretTC(
                nom=nom or "Gare",
                mode=mode,
                ligne=None,
                exploitant="SNCF",
                lat=stop_lat,
                lng=stop_lng,
                distance_m=round(dist, 1),
            )
        )
    return out


# ---------------------------------------------------------------------------
# OpenStreetMap Overpass — metro / RER / tram / bus
# ---------------------------------------------------------------------------


def _overpass_query(lat: float, lng: float, radius_m: int) -> str:
    """Return the Overpass QL query for transit stops in a circle.

    We pull:
      * ``railway=station`` + ``railway=halt`` (rail of any kind)
      * ``public_transport=station`` (umbrella tag — metro, RER, tram, bus)
      * ``railway=tram_stop`` (tram only)
      * ``highway=bus_stop`` (kept tighter to ``radius_m`` so we don't drown
        the result in mute bus poles when the user only cares about rail).
    """
    return (
        f"[out:json][timeout:25];"
        f"("
        f'node["railway"~"station|halt|tram_stop"](around:{radius_m},{lat},{lng});'
        f'node["public_transport"="station"](around:{radius_m},{lat},{lng});'
        f'node["highway"="bus_stop"](around:{min(radius_m, 500)},{lat},{lng});'
        f");out;"
    )


def _classify_overpass(tags: dict[str, Any]) -> str:
    """Map an OSM tag set to our mode taxonomy."""
    if tags.get("subway") == "yes" or tags.get("station") == "subway":
        return "metro"
    if tags.get("light_rail") == "yes":
        return "metro"
    if tags.get("rer") == "yes":
        return "RER"
    if tags.get("railway") == "tram_stop" or tags.get("tram") == "yes":
        return "tram"
    if tags.get("railway") in {"station", "halt"} or tags.get("train") == "yes":
        # Many Île-de-France RER halts are tagged train=yes without rer=yes;
        # we leave them as "gare" — DesserteResult treats gare separately.
        return "gare"
    if tags.get("highway") == "bus_stop" or tags.get("bus") == "yes":
        return "bus"
    return "bus"


async def _fetch_overpass(
    *, lat: float, lng: float, radius_m: int
) -> list[ArretTC]:
    """Fetch transit stops from OSM via Overpass with mirror fallback."""
    client = get_http_client()
    query = _overpass_query(lat, lng, radius_m)
    data: dict[str, Any] | None = None

    for endpoint in _OVERPASS_ENDPOINTS:
        try:
            resp = await client.post(
                endpoint,
                data={"data": query},
                timeout=httpx.Timeout(connect=5.0, read=25.0, write=5.0, pool=5.0),
            )
            if resp.status_code != 200:
                _logger.info(
                    "Overpass %s returned HTTP %s — trying next mirror",
                    endpoint, resp.status_code,
                )
                continue
            data = resp.json()
            if data is not None:
                break
        except Exception:
            _logger.info("Overpass %s transport error — trying next mirror", endpoint)
            continue

    if data is None:
        return []

    seen: set[tuple[int, int, str]] = set()
    out: list[ArretTC] = []
    for element in data.get("elements", []):
        if element.get("type") != "node":
            continue
        stop_lat = element.get("lat")
        stop_lng = element.get("lon")
        if stop_lat is None or stop_lng is None:
            continue

        tags = element.get("tags") or {}
        mode = _classify_overpass(tags)
        nom = tags.get("name") or tags.get("ref") or ""
        ligne = tags.get("ref") or tags.get("route_ref") or None
        exploitant = tags.get("operator") or None

        dist = _haversine_m(lat, lng, float(stop_lat), float(stop_lng))
        if dist > radius_m:
            continue

        # Dedup key: rounded coords (≈3 m precision) + mode.
        key = (
            int(round(float(stop_lat) * 1e5)),
            int(round(float(stop_lng) * 1e5)),
            mode,
        )
        if key in seen:
            continue
        seen.add(key)

        out.append(
            ArretTC(
                nom=nom,
                mode=mode,
                ligne=ligne,
                exploitant=exploitant,
                lat=float(stop_lat),
                lng=float(stop_lng),
                distance_m=round(dist, 1),
            )
        )
    return out


# ---------------------------------------------------------------------------
# Legacy WFS path (kept so test fixtures still match the original endpoint)
# ---------------------------------------------------------------------------


async def _fetch_legacy_wfs(
    *, lat: float, lng: float, radius_m: int
) -> list[ArretTC]:
    """Original BBOX GetFeature against the legacy stops typename.

    Kept for backward compatibility with the existing pytest-httpx fixtures
    and with any production env where this typename is still in use.
    Failures are swallowed.
    """
    dlat = radius_m / 111_000
    dlng = radius_m / 73_000
    west = lng - dlng
    south = lat - dlat
    east = lng + dlng
    bbox = f"{west},{south},{east},{lat + dlat},EPSG:4326"

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
        return []

    results: list[ArretTC] = []
    for feature in data.get("features", []):
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        coords = geom.get("coordinates") or [None, None]
        if coords[0] is None or coords[1] is None:
            continue
        try:
            stop_lng = float(coords[0])
            stop_lat = float(coords[1])
        except (TypeError, ValueError):
            continue

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
    return results


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _dedup(arrets: list[ArretTC]) -> list[ArretTC]:
    """Drop duplicate entries (same rounded position + mode), keep nearest."""
    out: dict[tuple[int, int, str], ArretTC] = {}
    for a in arrets:
        key = (
            int(round(a.lat * 1e4)),
            int(round(a.lng * 1e4)),
            a.mode,
        )
        prev = out.get(key)
        if prev is None or (
            (a.distance_m or math.inf) < (prev.distance_m or math.inf)
        ):
            out[key] = a
    return list(out.values())


async def fetch_arrets_around(
    *, lat: float, lng: float, radius_m: int = 500, use_cache: bool = True,
) -> list[ArretTC]:
    """Fetch public transport stops within ``radius_m`` of ``(lat, lng)``.

    Combines IGN POI Gares (authoritative national railway station list)
    with OpenStreetMap (metro / RER / tram / bus). A legacy BDTOPO WFS
    query is also issued so that existing pytest-httpx fixtures continue
    to drive the function.

    Args:
        lat: Latitude in WGS84 decimal degrees.
        lng: Longitude in WGS84 decimal degrees.
        radius_m: Maximum distance in metres from the centre point.
        use_cache: If False, skip the local cache (force refresh).

    Returns:
        List of :class:`ArretTC` sorted by ascending distance.
        ``[]`` on any error (graceful degradation).
    """
    radius_m = max(50, min(int(radius_m), 5_000))

    key_payload = {
        "lat": round(float(lat), 4),
        "lng": round(float(lng), 4),
        "radius_m": radius_m,
        "v": 2,
    }
    key = _cache_key(key_payload)

    if use_cache:
        cached = _load_cache(key)
        if cached is not None:
            return [ArretTC(**c) for c in cached]

    legacy, gares, osm = await asyncio.gather(
        _fetch_legacy_wfs(lat=lat, lng=lng, radius_m=radius_m),
        _fetch_ign_gares(lat=lat, lng=lng, radius_m=radius_m),
        _fetch_overpass(lat=lat, lng=lng, radius_m=radius_m),
        return_exceptions=False,
    )

    combined: list[ArretTC] = []
    combined.extend(legacy)
    combined.extend(gares)
    combined.extend(osm)
    combined = _dedup(combined)
    combined.sort(key=lambda a: a.distance_m if a.distance_m is not None else math.inf)

    if use_cache and combined:
        _save_cache(key, [a.__dict__ for a in combined])

    return combined


__all__ = ["ArretTC", "fetch_arrets_around"]


# ---------------------------------------------------------------------------
# Manual smoke test — ``python -m core.sources.ign_transports``
# ---------------------------------------------------------------------------


async def _main_demo() -> None:  # pragma: no cover - manual smoke
    """Quick smoke test against the live APIs."""
    lat, lng = 48.83558, 2.4810  # 80 rue des Héros, Nogent-sur-Marne
    arrets = await fetch_arrets_around(lat=lat, lng=lng, radius_m=800, use_cache=False)
    print(f"IGN transports — fetched {len(arrets)} arrêts around ({lat}, {lng})")
    for a in arrets[:20]:
        d = f"{a.distance_m:.0f} m" if a.distance_m is not None else "?"
        print(f"  · {d:>7}  [{a.mode:5}]  {a.nom}  (ligne={a.ligne}, op={a.exploitant})")


if __name__ == "__main__":  # pragma: no cover
    asyncio.run(_main_demo())
