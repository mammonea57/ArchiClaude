# ArchiClaude — Phase 1 : Données parcelle & urbanisme — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire les clients de données externes (BAN, Cadastre, GPU, IGN BDTopo, BD Alti, GeoRisques, POP, DPE, DVF), les modèles DB associés, le cache Redis, et les endpoints API `/parcels/*` + `/plu/at-point` — le tout testé en TDD avec les fixtures de référence Phase 0.

**Architecture:** Modules `core/sources/*.py` (ports/adapters purs, sans FastAPI/DB), utilitaire `core/geo/` (projections Lambert-93, calculs surfaciques), cache Redis via `core/cache.py`, modèles SQLAlchemy `db/models/`, routes FastAPI `api/routes/parcels.py` + `api/routes/plu.py`. Chaque source externe a retry tenacity + timeout + mode dégradé.

**Tech Stack:** Python 3.12, httpx (async HTTP), tenacity (retry), redis.asyncio, shapely, pyproj, geopandas, SQLAlchemy 2.0, Alembic, FastAPI, pytest + pytest-asyncio + pytest-httpx.

**Spec source:** `docs/superpowers/specs/2026-04-16-archiclaude-sous-projet-1-design.md` §3 (Sources données), §6 (Modèle DB), §7.2 (Endpoints)

**Reference context:** Existing bot at `~/Desktop/Urbanisme app/urbanisme-france-live/src/lib/api.ts` — read-only reference for API URLs and data flow patterns. Never modify.

---

## File Structure (final état Phase 1)

```
apps/backend/
├── core/
│   ├── __init__.py                          (exists)
│   ├── flags.py                             (exists)
│   ├── cache.py                             (NEW — Redis cache utility)
│   ├── http_client.py                       (NEW — shared httpx client with retry)
│   ├── geo/
│   │   ├── __init__.py                      (NEW)
│   │   ├── projections.py                   (NEW — Lambert-93 ↔ WGS84)
│   │   └── surface.py                       (NEW — Shoelace area, buffer helpers)
│   └── sources/
│       ├── __init__.py                      (NEW)
│       ├── ban.py                           (NEW — BAN geocoding)
│       ├── cadastre.py                      (NEW — API Carto Cadastre)
│       ├── gpu.py                           (NEW — GPU zones/servitudes/documents)
│       ├── ign_bdtopo.py                    (NEW — WFS BDTopo buildings)
│       ├── ign_bd_alti.py                   (NEW — BD ALTI altitude)
│       ├── georisques.py                    (NEW — PPRI, argiles, sols pollués)
│       ├── pop.py                           (NEW — Patrimoine monuments historiques)
│       ├── dpe.py                           (NEW — DPE ADEME)
│       └── dvf.py                           (NEW — DVF valeurs foncières)
├── api/
│   ├── routes/
│   │   ├── health.py                        (exists)
│   │   ├── parcels.py                       (NEW — /parcels/search, at-point, by-ref, {id})
│   │   └── plu.py                           (NEW — /plu/at-point)
│   └── main.py                              (MODIFY — register new routers)
├── db/
│   ├── models/
│   │   ├── feature_flags.py                 (exists)
│   │   ├── audit_logs.py                    (exists)
│   │   ├── users.py                         (exists — rename from user in models)
│   │   ├── parcels.py                       (NEW)
│   │   ├── plu.py                           (NEW — plu_documents, plu_zones)
│   │   └── servitudes.py                    (NEW)
│   └── base.py                              (exists)
├── schemas/
│   ├── parcel.py                            (NEW — API request/response schemas)
│   └── plu.py                               (NEW — PLU API schemas)
├── alembic/versions/
│   └── 20260417_0001_parcels_plu_servitudes.py (NEW)
├── tests/
│   ├── conftest.py                          (MODIFY — add Redis fixture)
│   ├── unit/
│   │   ├── test_geo_projections.py          (NEW)
│   │   ├── test_geo_surface.py              (NEW)
│   │   ├── test_cache.py                    (NEW)
│   │   ├── test_source_ban.py               (NEW)
│   │   ├── test_source_cadastre.py          (NEW)
│   │   ├── test_source_gpu.py               (NEW)
│   │   ├── test_source_ign_bdtopo.py        (NEW)
│   │   ├── test_source_ign_bd_alti.py       (NEW)
│   │   ├── test_source_georisques.py        (NEW)
│   │   ├── test_source_pop.py               (NEW)
│   │   ├── test_source_dpe.py               (NEW)
│   │   └── test_source_dvf.py               (NEW)
│   ├── integration/
│   │   ├── test_parcels_endpoints.py        (NEW)
│   │   └── test_plu_endpoints.py            (NEW)
│   └── fixtures/
│       ├── parcelles_reference.yaml         (exists)
│       ├── ban_responses.json               (NEW — mocked BAN responses)
│       ├── cadastre_responses.json          (NEW — mocked cadastre GeoJSON)
│       └── gpu_responses.json               (NEW — mocked GPU zones/servitudes)
└── pyproject.toml                           (MODIFY — add httpx, fakeredis)
```

**Responsabilités par fichier :**
- `core/cache.py` : wrapper Redis async avec get/set/TTL, serialisation JSON, prefix par namespace
- `core/http_client.py` : httpx.AsyncClient singleton avec timeout, retry tenacity, logging
- `core/geo/projections.py` : fonctions `wgs84_to_lambert93()`, `lambert93_to_wgs84()` via pyproj
- `core/geo/surface.py` : `polygon_area_m2()` via shapely en Lambert-93, `buffer_point_m()`
- `core/sources/*.py` : chaque module expose une fonction async principale (ex: `geocode()`, `fetch_parcelle()`) — pas de dépendance FastAPI/DB
- `db/models/parcels.py` : ORM `ParcelRow` avec géométrie PostGIS
- `db/models/plu.py` : ORM `PluDocumentRow`, `PluZoneRow`
- `db/models/servitudes.py` : ORM `ServitudeRow`
- `api/routes/parcels.py` : endpoints REST `/parcels/*` avec cache Redis
- `api/routes/plu.py` : endpoint `/plu/at-point` agrégant GPU + servitudes
- `schemas/parcel.py` : Pydantic request/response pour parcels API
- `schemas/plu.py` : Pydantic request/response pour PLU API

---

## Task 1: Utilitaires géographiques (core/geo/)

**Files:**
- Create: `apps/backend/core/geo/__init__.py`
- Create: `apps/backend/core/geo/projections.py`
- Create: `apps/backend/core/geo/surface.py`
- Test: `apps/backend/tests/unit/test_geo_projections.py`
- Test: `apps/backend/tests/unit/test_geo_surface.py`

- [ ] **Step 1: Write failing tests for projections**

```python
# apps/backend/tests/unit/test_geo_projections.py
"""Tests for Lambert-93 ↔ WGS84 coordinate projections."""
import pytest
from core.geo.projections import wgs84_to_lambert93, lambert93_to_wgs84


class TestWgs84ToLambert93:
    def test_paris_center(self):
        """Tour Eiffel: WGS84 (48.8584, 2.2945) → Lambert-93 ~(648240, 6862260)."""
        x, y = wgs84_to_lambert93(lat=48.8584, lng=2.2945)
        assert abs(x - 648240) < 5  # 5m tolerance
        assert abs(y - 6862260) < 5

    def test_nogent_sur_marne(self):
        """Nogent-sur-Marne mairie: WGS84 (48.8375, 2.4833)."""
        x, y = wgs84_to_lambert93(lat=48.8375, lng=2.4833)
        assert 650000 < x < 670000
        assert 6850000 < y < 6870000

    def test_roundtrip(self):
        """WGS84 → L93 → WGS84 should be identity within 1cm."""
        lat_in, lng_in = 48.8584, 2.2945
        x, y = wgs84_to_lambert93(lat=lat_in, lng=lng_in)
        lat_out, lng_out = lambert93_to_wgs84(x=x, y=y)
        assert abs(lat_out - lat_in) < 1e-7
        assert abs(lng_out - lng_in) < 1e-7


class TestLambert93ToWgs84:
    def test_known_point(self):
        lat, lng = lambert93_to_wgs84(x=648240, y=6862260)
        assert abs(lat - 48.858) < 0.01
        assert abs(lng - 2.294) < 0.01
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_geo_projections.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.geo'`

- [ ] **Step 3: Implement projections module**

```python
# apps/backend/core/geo/__init__.py
"""Geographic utilities for ArchiClaude."""

# apps/backend/core/geo/projections.py
"""Lambert-93 (EPSG:2154) ↔ WGS84 (EPSG:4326) coordinate transformations."""
from pyproj import Transformer

# Thread-safe singleton transformers (pyproj is thread-safe after init)
_to_lambert = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)
_to_wgs84 = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)


def wgs84_to_lambert93(*, lat: float, lng: float) -> tuple[float, float]:
    """Convert WGS84 (lat, lng) to Lambert-93 (x, y) in meters."""
    x, y = _to_lambert.transform(lng, lat)
    return x, y


def lambert93_to_wgs84(*, x: float, y: float) -> tuple[float, float]:
    """Convert Lambert-93 (x, y) to WGS84 (lat, lng)."""
    lng, lat = _to_wgs84.transform(x, y)
    return lat, lng
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_geo_projections.py -v`
Expected: PASS — all 4 tests green

- [ ] **Step 5: Write failing tests for surface calculations**

```python
# apps/backend/tests/unit/test_geo_surface.py
"""Tests for geometric surface calculations."""
import pytest
from shapely.geometry import Point, Polygon
from core.geo.surface import polygon_area_m2, buffer_point_m


class TestPolygonAreaM2:
    def test_known_square_100m(self):
        """A 100m x 100m square in Lambert-93 should have area ~10000 m²."""
        # Square near Paris in Lambert-93
        square = Polygon([
            (648000, 6862000),
            (648100, 6862000),
            (648100, 6862100),
            (648000, 6862100),
            (648000, 6862000),
        ])
        area = polygon_area_m2(square, source_crs="EPSG:2154")
        assert abs(area - 10000) < 1  # 1m² tolerance

    def test_wgs84_polygon(self):
        """A polygon in WGS84 should be reprojected before area calc."""
        # ~small polygon near Paris
        poly = Polygon([
            (2.2940, 48.8580),
            (2.2960, 48.8580),
            (2.2960, 48.8600),
            (2.2940, 48.8600),
            (2.2940, 48.8580),
        ])
        area = polygon_area_m2(poly, source_crs="EPSG:4326")
        assert 10000 < area < 50000  # reasonable urban block


class TestBufferPointM:
    def test_50m_radius(self):
        """Buffer 50m around a WGS84 point should produce ~7854 m² circle."""
        center = Point(2.2945, 48.8584)
        buffered = buffer_point_m(center, radius_m=50, source_crs="EPSG:4326")
        area = polygon_area_m2(buffered, source_crs="EPSG:2154")
        expected = 3.14159 * 50 * 50
        assert abs(area - expected) < 100  # 100m² tolerance for circle approx
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_geo_surface.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.geo.surface'`

- [ ] **Step 7: Implement surface module**

```python
# apps/backend/core/geo/surface.py
"""Geometric surface and buffer calculations with CRS-aware reprojection."""
from pyproj import Transformer
from shapely.geometry import Point, Polygon, MultiPolygon
from shapely.ops import transform as shapely_transform

_to_lambert = Transformer.from_crs("EPSG:4326", "EPSG:2154", always_xy=True)
_to_wgs84 = Transformer.from_crs("EPSG:2154", "EPSG:4326", always_xy=True)


def _reproject(geom, from_crs: str, to_crs: str):
    """Reproject a shapely geometry between CRS."""
    if from_crs == to_crs:
        return geom
    if from_crs == "EPSG:4326" and to_crs == "EPSG:2154":
        return shapely_transform(_to_lambert.transform, geom)
    if from_crs == "EPSG:2154" and to_crs == "EPSG:4326":
        return shapely_transform(_to_wgs84.transform, geom)
    t = Transformer.from_crs(from_crs, to_crs, always_xy=True)
    return shapely_transform(t.transform, geom)


def polygon_area_m2(
    geom: Polygon | MultiPolygon, source_crs: str = "EPSG:4326"
) -> float:
    """Calculate area in square meters. Reprojects to Lambert-93 if needed."""
    proj = _reproject(geom, source_crs, "EPSG:2154")
    return proj.area


def buffer_point_m(
    point: Point, radius_m: float, source_crs: str = "EPSG:4326"
) -> Polygon:
    """Buffer a point by radius in meters. Returns geometry in Lambert-93."""
    proj = _reproject(point, source_crs, "EPSG:2154")
    return proj.buffer(radius_m)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_geo_surface.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/core/geo/ apps/backend/tests/unit/test_geo_projections.py apps/backend/tests/unit/test_geo_surface.py
git commit -m "feat(core): add geo utilities — Lambert-93 projections and surface calculations"
```

---

## Task 2: HTTP client partagé + cache Redis

**Files:**
- Create: `apps/backend/core/http_client.py`
- Create: `apps/backend/core/cache.py`
- Test: `apps/backend/tests/unit/test_cache.py`
- Modify: `apps/backend/pyproject.toml`

- [ ] **Step 1: Add httpx and fakeredis dependencies**

Add to `apps/backend/pyproject.toml` in `[project.dependencies]`:
```
"httpx>=0.27",
```
Add to `[project.optional-dependencies] dev`:
```
"fakeredis[lua]>=2.25",
```

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && pip install -e ".[dev]"`

- [ ] **Step 2: Write failing tests for cache**

```python
# apps/backend/tests/unit/test_cache.py
"""Tests for Redis cache utility."""
import pytest
import fakeredis.aioredis
from core.cache import RedisCache


@pytest.fixture
async def cache():
    r = fakeredis.aioredis.FakeRedis()
    c = RedisCache(redis=r, prefix="test")
    yield c
    await r.aclose()


class TestRedisCache:
    @pytest.mark.asyncio
    async def test_get_miss(self, cache: RedisCache):
        result = await cache.get("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_and_get(self, cache: RedisCache):
        await cache.set("key1", {"lat": 48.85, "lng": 2.29}, ttl_seconds=60)
        result = await cache.get("key1")
        assert result == {"lat": 48.85, "lng": 2.29}

    @pytest.mark.asyncio
    async def test_prefix_isolation(self, cache: RedisCache):
        await cache.set("shared", "value1", ttl_seconds=60)
        r2 = fakeredis.aioredis.FakeRedis()
        other = RedisCache(redis=r2, prefix="other")
        result = await other.get("shared")
        assert result is None
        await r2.aclose()

    @pytest.mark.asyncio
    async def test_get_or_fetch_cache_hit(self, cache: RedisCache):
        await cache.set("cached", 42, ttl_seconds=60)
        call_count = 0

        async def fetcher():
            nonlocal call_count
            call_count += 1
            return 99

        result = await cache.get_or_fetch("cached", fetcher, ttl_seconds=60)
        assert result == 42
        assert call_count == 0

    @pytest.mark.asyncio
    async def test_get_or_fetch_cache_miss(self, cache: RedisCache):
        async def fetcher():
            return {"data": "fresh"}

        result = await cache.get_or_fetch("miss", fetcher, ttl_seconds=60)
        assert result == {"data": "fresh"}
        # Should now be cached
        cached = await cache.get("miss")
        assert cached == {"data": "fresh"}
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.cache'`

- [ ] **Step 4: Implement cache module**

```python
# apps/backend/core/cache.py
"""Redis cache utility with JSON serialization and key prefixing."""
import json
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio import Redis


class RedisCache:
    """Thin async Redis wrapper with namespace prefixing and JSON serde."""

    def __init__(self, redis: Redis, prefix: str) -> None:
        self._redis = redis
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}:{key}"

    async def get(self, key: str) -> Any | None:
        raw = await self._redis.get(self._key(key))
        if raw is None:
            return None
        return json.loads(raw)

    async def set(self, key: str, value: Any, *, ttl_seconds: int) -> None:
        await self._redis.set(
            self._key(key), json.dumps(value, default=str), ex=ttl_seconds
        )

    async def get_or_fetch(
        self,
        key: str,
        fetcher: Callable[[], Awaitable[Any]],
        *,
        ttl_seconds: int,
    ) -> Any:
        cached = await self.get(key)
        if cached is not None:
            return cached
        result = await fetcher()
        await self.set(key, result, ttl_seconds=ttl_seconds)
        return result
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_cache.py -v`
Expected: PASS — all 5 tests green

- [ ] **Step 6: Implement shared HTTP client**

```python
# apps/backend/core/http_client.py
"""Shared async HTTP client with retry and timeout."""
import logging
import os

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

# Module-level singleton — created lazily
_client: httpx.AsyncClient | None = None

DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)
PDF_TIMEOUT = httpx.Timeout(connect=5.0, read=40.0, write=5.0, pool=5.0)


def get_http_client() -> httpx.AsyncClient:
    """Get or create the shared httpx AsyncClient."""
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "ArchiClaude/1.0"},
        )
    return _client


async def close_http_client() -> None:
    """Close the shared client (call on app shutdown)."""
    global _client
    if _client and not _client.is_closed:
        await _client.aclose()
        _client = None


@retry(
    retry=retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
async def fetch_json(url: str, *, params: dict | None = None, timeout: httpx.Timeout | None = None) -> dict:
    """GET JSON from URL with retry on transient errors."""
    client = get_http_client()
    kwargs = {"params": params}
    if timeout:
        kwargs["timeout"] = timeout
    resp = await client.get(url, **kwargs)
    resp.raise_for_status()
    return resp.json()


@retry(
    retry=retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
async def post_json(url: str, *, json_body: dict | None = None, params: dict | None = None) -> dict:
    """POST JSON and return parsed response with retry."""
    client = get_http_client()
    resp = await client.post(url, json=json_body, params=params)
    resp.raise_for_status()
    return resp.json()
```

- [ ] **Step 7: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/core/cache.py apps/backend/core/http_client.py apps/backend/tests/unit/test_cache.py apps/backend/pyproject.toml
git commit -m "feat(core): add Redis cache utility and shared HTTP client with retry"
```

---

## Task 3: Client BAN — géocodage adresse

**Files:**
- Create: `apps/backend/core/sources/__init__.py`
- Create: `apps/backend/core/sources/ban.py`
- Create: `apps/backend/tests/fixtures/ban_responses.json`
- Test: `apps/backend/tests/unit/test_source_ban.py`

- [ ] **Step 1: Create mock fixture for BAN responses**

```json
// apps/backend/tests/fixtures/ban_responses.json
{
  "geocode_12_rue_paix_paris": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [2.331, 48.869]},
        "properties": {
          "label": "12 Rue de la Paix 75002 Paris",
          "score": 0.95,
          "housenumber": "12",
          "street": "Rue de la Paix",
          "postcode": "75002",
          "citycode": "75102",
          "city": "Paris",
          "context": "75, Paris, \u00cele-de-France",
          "x": 651427.5,
          "y": 6863289.3
        }
      }
    ]
  },
  "geocode_nogent": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [2.4833, 48.8375]},
        "properties": {
          "label": "1 Place Pierre S\u00e9mard 94130 Nogent-sur-Marne",
          "score": 0.88,
          "citycode": "94052",
          "city": "Nogent-sur-Marne",
          "x": 661234.0,
          "y": 6860456.0
        }
      }
    ]
  }
}
```

- [ ] **Step 2: Write failing tests for BAN client**

```python
# apps/backend/tests/unit/test_source_ban.py
"""Tests for BAN geocoding client."""
import json
from pathlib import Path

import pytest
import httpx
from pytest_httpx import HTTPXMock

from core.sources.ban import geocode, GeocodingResult

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture(key: str) -> dict:
    data = json.loads((FIXTURES / "ban_responses.json").read_text())
    return data[key]


class TestGeocode:
    @pytest.mark.asyncio
    async def test_paris_address(self, httpx_mock: HTTPXMock):
        fixture = _load_fixture("geocode_12_rue_paix_paris")
        httpx_mock.add_response(
            url=httpx.URL("https://api-adresse.data.gouv.fr/search/", params={"q": "12 rue de la Paix Paris", "limit": "5"}),
            json=fixture,
        )
        results = await geocode("12 rue de la Paix Paris", limit=5)
        assert len(results) == 1
        r = results[0]
        assert r.label == "12 Rue de la Paix 75002 Paris"
        assert r.citycode == "75102"
        assert abs(r.lat - 48.869) < 0.01
        assert abs(r.lng - 2.331) < 0.01
        assert r.score > 0.9

    @pytest.mark.asyncio
    async def test_empty_query_returns_empty(self, httpx_mock: HTTPXMock):
        results = await geocode("", limit=5)
        assert results == []

    @pytest.mark.asyncio
    async def test_api_error_raises(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(status_code=500)
        with pytest.raises(httpx.HTTPStatusError):
            await geocode("test", limit=5)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_ban.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.sources'`

- [ ] **Step 4: Implement BAN client**

```python
# apps/backend/core/sources/__init__.py
"""External data source clients for ArchiClaude."""

# apps/backend/core/sources/ban.py
"""BAN (Base Adresse Nationale) geocoding client.

API: https://api-adresse.data.gouv.fr/search/
Limit: 50 req/s, no API key required.
"""
from dataclasses import dataclass

from core.http_client import fetch_json

BAN_SEARCH_URL = "https://api-adresse.data.gouv.fr/search/"


@dataclass(frozen=True)
class GeocodingResult:
    label: str
    score: float
    lat: float
    lng: float
    citycode: str
    city: str
    postcode: str | None = None
    housenumber: str | None = None
    street: str | None = None


async def geocode(query: str, *, limit: int = 5) -> list[GeocodingResult]:
    """Geocode an address string via BAN API.

    Returns up to `limit` results sorted by relevance score.
    """
    if not query.strip():
        return []

    data = await fetch_json(BAN_SEARCH_URL, params={"q": query, "limit": str(limit)})

    results = []
    for feat in data.get("features", []):
        props = feat["properties"]
        coords = feat["geometry"]["coordinates"]
        results.append(
            GeocodingResult(
                label=props.get("label", ""),
                score=props.get("score", 0.0),
                lat=coords[1],
                lng=coords[0],
                citycode=props.get("citycode", ""),
                city=props.get("city", ""),
                postcode=props.get("postcode"),
                housenumber=props.get("housenumber"),
                street=props.get("street"),
            )
        )
    return results
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_ban.py -v`
Expected: PASS — all 3 tests green

- [ ] **Step 6: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/core/sources/ apps/backend/tests/unit/test_source_ban.py apps/backend/tests/fixtures/ban_responses.json
git commit -m "feat(sources): add BAN geocoding client with tests"
```

---

## Task 4: Client Cadastre — parcelles

**Files:**
- Create: `apps/backend/core/sources/cadastre.py`
- Create: `apps/backend/tests/fixtures/cadastre_responses.json`
- Test: `apps/backend/tests/unit/test_source_cadastre.py`

- [ ] **Step 1: Create mock fixture for cadastre**

```json
// apps/backend/tests/fixtures/cadastre_responses.json
{
  "parcelle_by_ref_nogent_AB_42": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "geometry": {
          "type": "MultiPolygon",
          "coordinates": [[[[2.4830, 48.8370], [2.4840, 48.8370], [2.4840, 48.8380], [2.4830, 48.8380], [2.4830, 48.8370]]]]
        },
        "properties": {
          "numero": "0042",
          "section": "AB",
          "code_dep": "94",
          "nom_com": "Nogent-sur-Marne",
          "code_com": "052",
          "code_arr": "000",
          "contenance": 1250
        }
      }
    ]
  },
  "parcelle_at_point_paris": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "geometry": {
          "type": "MultiPolygon",
          "coordinates": [[[[2.3100, 48.8690], [2.3115, 48.8690], [2.3115, 48.8700], [2.3100, 48.8700], [2.3100, 48.8690]]]]
        },
        "properties": {
          "numero": "0015",
          "section": "AH",
          "code_dep": "75",
          "nom_com": "Paris",
          "code_com": "102",
          "code_arr": "000",
          "contenance": 890
        }
      }
    ]
  }
}
```

- [ ] **Step 2: Write failing tests for cadastre client**

```python
# apps/backend/tests/unit/test_source_cadastre.py
"""Tests for API Carto Cadastre client."""
import json
from pathlib import Path

import pytest
import httpx
from pytest_httpx import HTTPXMock

from core.sources.cadastre import (
    fetch_parcelle_by_ref,
    fetch_parcelle_at_point,
    ParcelleResult,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture(key: str) -> dict:
    data = json.loads((FIXTURES / "cadastre_responses.json").read_text())
    return data[key]


class TestFetchParcelleByRef:
    @pytest.mark.asyncio
    async def test_nogent_ab_42(self, httpx_mock: HTTPXMock):
        fixture = _load_fixture("parcelle_by_ref_nogent_AB_42")
        httpx_mock.add_response(json=fixture)
        result = await fetch_parcelle_by_ref(
            code_insee="94052", section="AB", numero="0042"
        )
        assert result is not None
        assert result.section == "AB"
        assert result.numero == "0042"
        assert result.contenance_m2 == 1250
        assert result.commune == "Nogent-sur-Marne"
        assert result.geometry is not None

    @pytest.mark.asyncio
    async def test_not_found(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json={"type": "FeatureCollection", "features": []})
        result = await fetch_parcelle_by_ref(
            code_insee="94052", section="ZZ", numero="9999"
        )
        assert result is None


class TestFetchParcelleAtPoint:
    @pytest.mark.asyncio
    async def test_paris_point(self, httpx_mock: HTTPXMock):
        fixture = _load_fixture("parcelle_at_point_paris")
        httpx_mock.add_response(json=fixture)
        result = await fetch_parcelle_at_point(lat=48.869, lng=2.310)
        assert result is not None
        assert result.section == "AH"
        assert result.contenance_m2 == 890
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_cadastre.py -v`
Expected: FAIL

- [ ] **Step 4: Implement cadastre client**

```python
# apps/backend/core/sources/cadastre.py
"""API Carto IGN — module Cadastre.

API: https://apicarto.ign.fr/api/cadastre/parcelle
No API key required.
"""
from dataclasses import dataclass
from typing import Any

from core.http_client import fetch_json

CADASTRE_URL = "https://apicarto.ign.fr/api/cadastre/parcelle"


@dataclass(frozen=True)
class ParcelleResult:
    code_insee: str
    section: str
    numero: str
    contenance_m2: int | None
    commune: str
    geometry: dict[str, Any]  # GeoJSON geometry


async def fetch_parcelle_by_ref(
    *, code_insee: str, section: str, numero: str
) -> ParcelleResult | None:
    """Fetch a parcel by cadastral reference (INSEE + section + numero)."""
    data = await fetch_json(
        CADASTRE_URL,
        params={
            "code_insee": code_insee,
            "section": section,
            "numero": numero,
        },
    )
    features = data.get("features", [])
    if not features:
        return None
    return _feature_to_result(features[0], code_insee)


async def fetch_parcelle_at_point(
    *, lat: float, lng: float
) -> ParcelleResult | None:
    """Fetch the parcel at a given WGS84 point."""
    # API Carto accepts a GeoJSON geometry for intersection
    geom = {"type": "Point", "coordinates": [lng, lat]}
    data = await fetch_json(
        CADASTRE_URL,
        params={"geom": __import__("json").dumps(geom)},
    )
    features = data.get("features", [])
    if not features:
        return None
    props = features[0]["properties"]
    code_insee = f"{props.get('code_dep', '')}{props.get('code_com', '')}"
    return _feature_to_result(features[0], code_insee)


def _feature_to_result(feature: dict, code_insee: str) -> ParcelleResult:
    props = feature["properties"]
    if not code_insee:
        code_insee = f"{props.get('code_dep', '')}{props.get('code_com', '')}"
    return ParcelleResult(
        code_insee=code_insee,
        section=props.get("section", ""),
        numero=props.get("numero", ""),
        contenance_m2=props.get("contenance"),
        commune=props.get("nom_com", ""),
        geometry=feature["geometry"],
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_cadastre.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/core/sources/cadastre.py apps/backend/tests/unit/test_source_cadastre.py apps/backend/tests/fixtures/cadastre_responses.json
git commit -m "feat(sources): add Cadastre API client with tests"
```

---

## Task 5: Client GPU — zonage PLU, servitudes, documents

**Files:**
- Create: `apps/backend/core/sources/gpu.py`
- Create: `apps/backend/tests/fixtures/gpu_responses.json`
- Test: `apps/backend/tests/unit/test_source_gpu.py`

- [ ] **Step 1: Create mock fixture for GPU**

```json
// apps/backend/tests/fixtures/gpu_responses.json
{
  "zone_urba_nogent": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "geometry": {
          "type": "MultiPolygon",
          "coordinates": [[[[2.48, 48.83], [2.49, 48.83], [2.49, 48.84], [2.48, 48.84], [2.48, 48.83]]]]
        },
        "properties": {
          "libelle": "UB",
          "libelong": "Zone urbaine mixte",
          "typezone": "U",
          "partition": "94052_PLUi_20220101",
          "idurba": "94052_PLUi_20220101",
          "nomfic": "94052_reglement_UB.pdf",
          "urlfic": "https://gpu.beta.gouv.fr/documents/94052/reglement_UB.pdf"
        }
      }
    ]
  },
  "document_nogent": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "geometry": null,
        "properties": {
          "idurba": "94052_PLUi_20220101",
          "typedoc": "PLUi",
          "datappro": "2022-01-01",
          "nom": "PLUi Val-de-Marne Est"
        }
      }
    ]
  },
  "servitudes_nogent": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "geometry": {
          "type": "Polygon",
          "coordinates": [[[2.483, 48.837], [2.484, 48.837], [2.484, 48.838], [2.483, 48.838], [2.483, 48.837]]]
        },
        "properties": {
          "libelle": "P\u00e9rim\u00e8tre de protection monument historique",
          "categorie": "AC1",
          "txt": "Protection \u00e9glise Saint-Saturnin"
        }
      }
    ]
  },
  "prescriptions_nogent": {
    "type": "FeatureCollection",
    "features": [
      {
        "type": "Feature",
        "geometry": {
          "type": "Polygon",
          "coordinates": [[[2.483, 48.837], [2.485, 48.837], [2.485, 48.839], [2.483, 48.839], [2.483, 48.837]]]
        },
        "properties": {
          "libelle": "Hauteur maximum 15m",
          "txt": "R\u00e8gle de hauteur",
          "typepsc": "05"
        }
      }
    ]
  }
}
```

- [ ] **Step 2: Write failing tests for GPU client**

```python
# apps/backend/tests/unit/test_source_gpu.py
"""Tests for GPU (Géoportail de l'Urbanisme) client."""
import json
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from core.sources.gpu import (
    fetch_zones_at_point,
    fetch_document,
    fetch_servitudes_at_point,
    fetch_prescriptions_at_point,
    GpuZone,
    GpuDocument,
    GpuServitude,
    GpuPrescription,
)

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_fixture(key: str) -> dict:
    data = json.loads((FIXTURES / "gpu_responses.json").read_text())
    return data[key]


class TestFetchZonesAtPoint:
    @pytest.mark.asyncio
    async def test_nogent(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json=_load_fixture("zone_urba_nogent"))
        zones = await fetch_zones_at_point(lat=48.8375, lng=2.4833)
        assert len(zones) == 1
        z = zones[0]
        assert isinstance(z, GpuZone)
        assert z.libelle == "UB"
        assert z.typezone == "U"
        assert z.urlfic is not None
        assert z.geometry is not None


class TestFetchDocument:
    @pytest.mark.asyncio
    async def test_document_nogent(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json=_load_fixture("document_nogent"))
        docs = await fetch_document(lat=48.8375, lng=2.4833)
        assert len(docs) >= 1
        d = docs[0]
        assert isinstance(d, GpuDocument)
        assert d.typedoc == "PLUi"


class TestFetchServitudes:
    @pytest.mark.asyncio
    async def test_servitudes_found(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json=_load_fixture("servitudes_nogent"))
        servs = await fetch_servitudes_at_point(lat=48.8375, lng=2.4833)
        assert len(servs) == 1
        assert servs[0].categorie == "AC1"


class TestFetchPrescriptions:
    @pytest.mark.asyncio
    async def test_prescriptions_found(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json=_load_fixture("prescriptions_nogent"))
        prescs = await fetch_prescriptions_at_point(lat=48.8375, lng=2.4833)
        assert len(prescs) == 1
        assert "hauteur" in prescs[0].libelle.lower()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_gpu.py -v`
Expected: FAIL

- [ ] **Step 4: Implement GPU client**

```python
# apps/backend/core/sources/gpu.py
"""GPU (Géoportail de l'Urbanisme) client — zones, servitudes, prescriptions, documents.

APIs:
  - https://apicarto.ign.fr/api/gpu/zone-urba
  - https://apicarto.ign.fr/api/gpu/document
  - https://apicarto.ign.fr/api/gpu/prescription-surf
  - https://apicarto.ign.fr/api/gpu/prescription-lin
  - https://apicarto.ign.fr/api/gpu/prescription-pct
  - https://apicarto.ign.fr/api/gpu/assiette-sup-s
  - https://apicarto.ign.fr/api/gpu/assiette-sup-l
  - https://apicarto.ign.fr/api/gpu/assiette-sup-p
No API key required.
"""
import json
from dataclasses import dataclass, field
from typing import Any

from core.http_client import fetch_json

GPU_BASE = "https://apicarto.ign.fr/api/gpu"


@dataclass(frozen=True)
class GpuZone:
    libelle: str
    libelong: str | None
    typezone: str  # U, AU, A, N
    partition: str | None
    idurba: str | None
    nomfic: str | None
    urlfic: str | None
    geometry: dict[str, Any] | None


@dataclass(frozen=True)
class GpuDocument:
    idurba: str
    typedoc: str  # PLU, PLUi, POS, CC, RNU
    datappro: str | None
    nom: str | None


@dataclass(frozen=True)
class GpuServitude:
    libelle: str
    categorie: str  # AC1, PM1, etc.
    txt: str | None
    geometry: dict[str, Any] | None


@dataclass(frozen=True)
class GpuPrescription:
    libelle: str
    txt: str | None
    typepsc: str | None
    geometry: dict[str, Any] | None


def _point_geom(lat: float, lng: float) -> str:
    return json.dumps({"type": "Point", "coordinates": [lng, lat]})


async def fetch_zones_at_point(*, lat: float, lng: float) -> list[GpuZone]:
    """Fetch PLU zones intersecting a point."""
    data = await fetch_json(
        f"{GPU_BASE}/zone-urba", params={"geom": _point_geom(lat, lng)}
    )
    return [
        GpuZone(
            libelle=f["properties"].get("libelle", ""),
            libelong=f["properties"].get("libelong"),
            typezone=f["properties"].get("typezone", ""),
            partition=f["properties"].get("partition"),
            idurba=f["properties"].get("idurba"),
            nomfic=f["properties"].get("nomfic"),
            urlfic=f["properties"].get("urlfic"),
            geometry=f.get("geometry"),
        )
        for f in data.get("features", [])
    ]


async def fetch_document(*, lat: float, lng: float) -> list[GpuDocument]:
    """Fetch PLU document metadata at a point."""
    data = await fetch_json(
        f"{GPU_BASE}/document", params={"geom": _point_geom(lat, lng)}
    )
    return [
        GpuDocument(
            idurba=f["properties"].get("idurba", ""),
            typedoc=f["properties"].get("typedoc", ""),
            datappro=f["properties"].get("datappro"),
            nom=f["properties"].get("nom"),
        )
        for f in data.get("features", [])
    ]


async def fetch_servitudes_at_point(*, lat: float, lng: float) -> list[GpuServitude]:
    """Fetch servitudes (SUP) at a point — surface, linear, and point types."""
    all_servitudes = []
    for suffix in ("assiette-sup-s", "assiette-sup-l", "assiette-sup-p"):
        try:
            data = await fetch_json(
                f"{GPU_BASE}/{suffix}", params={"geom": _point_geom(lat, lng)}
            )
            for f in data.get("features", []):
                props = f["properties"]
                all_servitudes.append(
                    GpuServitude(
                        libelle=props.get("libelle", ""),
                        categorie=props.get("categorie", ""),
                        txt=props.get("txt"),
                        geometry=f.get("geometry"),
                    )
                )
        except Exception:
            # Mode dégradé — continue with other types
            pass
    return all_servitudes


async def fetch_prescriptions_at_point(
    *, lat: float, lng: float
) -> list[GpuPrescription]:
    """Fetch prescriptions at a point — surface, linear, and point types."""
    all_prescs = []
    for suffix in ("prescription-surf", "prescription-lin", "prescription-pct"):
        try:
            data = await fetch_json(
                f"{GPU_BASE}/{suffix}", params={"geom": _point_geom(lat, lng)}
            )
            for f in data.get("features", []):
                props = f["properties"]
                all_prescs.append(
                    GpuPrescription(
                        libelle=props.get("libelle", ""),
                        txt=props.get("txt"),
                        typepsc=props.get("typepsc"),
                        geometry=f.get("geometry"),
                    )
                )
        except Exception:
            pass
    return all_prescs
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_gpu.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/core/sources/gpu.py apps/backend/tests/unit/test_source_gpu.py apps/backend/tests/fixtures/gpu_responses.json
git commit -m "feat(sources): add GPU client — zones, servitudes, prescriptions, documents"
```

---

## Task 6: Clients IGN BDTopo + BD Alti

**Files:**
- Create: `apps/backend/core/sources/ign_bdtopo.py`
- Create: `apps/backend/core/sources/ign_bd_alti.py`
- Test: `apps/backend/tests/unit/test_source_ign_bdtopo.py`
- Test: `apps/backend/tests/unit/test_source_ign_bd_alti.py`

- [ ] **Step 1: Write failing tests for BDTopo**

```python
# apps/backend/tests/unit/test_source_ign_bdtopo.py
"""Tests for IGN BDTopo WFS client."""
import pytest
from pytest_httpx import HTTPXMock

from core.sources.ign_bdtopo import fetch_batiments_around, BatimentResult

MOCK_WFS_RESPONSE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [[2.483, 48.837], [2.484, 48.837], [2.484, 48.838], [2.483, 48.838], [2.483, 48.837]]
                ],
            },
            "properties": {
                "hauteur": 12.5,
                "nombre_d_etages": 4,
                "usage_1": "Résidentiel",
                "altitude_minimale_sol": 45.0,
                "altitude_maximale_toit": 57.5,
            },
        }
    ],
}


class TestFetchBatiments:
    @pytest.mark.asyncio
    async def test_buildings_found(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json=MOCK_WFS_RESPONSE)
        results = await fetch_batiments_around(lat=48.8375, lng=2.4833, radius_m=100)
        assert len(results) == 1
        b = results[0]
        assert isinstance(b, BatimentResult)
        assert b.hauteur == 12.5
        assert b.nb_etages == 4
        assert b.usage == "Résidentiel"

    @pytest.mark.asyncio
    async def test_empty_area(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json={"type": "FeatureCollection", "features": []})
        results = await fetch_batiments_around(lat=48.0, lng=2.0, radius_m=50)
        assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_ign_bdtopo.py -v`
Expected: FAIL

- [ ] **Step 3: Implement BDTopo client**

```python
# apps/backend/core/sources/ign_bdtopo.py
"""IGN BDTopo WFS client — building footprints, heights, and usage.

API: https://data.geopf.fr/wfs/ows (OGC WFS 2.0)
Layer: BDTOPO_V3:batiment
No API key required.
"""
from dataclasses import dataclass
from typing import Any

from core.http_client import fetch_json

WFS_URL = "https://data.geopf.fr/wfs/ows"


@dataclass(frozen=True)
class BatimentResult:
    hauteur: float | None
    nb_etages: int | None
    usage: str | None
    altitude_sol: float | None
    altitude_toit: float | None
    geometry: dict[str, Any] | None


def _bbox_from_point(lat: float, lng: float, radius_m: float) -> str:
    """Approximate bounding box in WGS84 from point + radius in meters."""
    # ~111km per degree lat, ~73km per degree lng at 48°N
    dlat = radius_m / 111_000
    dlng = radius_m / 73_000
    return f"{lat - dlat},{lng - dlng},{lat + dlat},{lng + dlng}"


async def fetch_batiments_around(
    *, lat: float, lng: float, radius_m: float = 100
) -> list[BatimentResult]:
    """Fetch BDTopo buildings within radius of a point."""
    bbox = _bbox_from_point(lat, lng, radius_m)
    data = await fetch_json(
        WFS_URL,
        params={
            "SERVICE": "WFS",
            "VERSION": "2.0.0",
            "REQUEST": "GetFeature",
            "TYPENAMES": "BDTOPO_V3:batiment",
            "SRSNAME": "EPSG:4326",
            "BBOX": bbox,
            "COUNT": "200",
            "OUTPUTFORMAT": "application/json",
        },
    )
    results = []
    for f in data.get("features", []):
        props = f.get("properties", {})
        results.append(
            BatimentResult(
                hauteur=props.get("hauteur"),
                nb_etages=props.get("nombre_d_etages"),
                usage=props.get("usage_1"),
                altitude_sol=props.get("altitude_minimale_sol"),
                altitude_toit=props.get("altitude_maximale_toit"),
                geometry=f.get("geometry"),
            )
        )
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_ign_bdtopo.py -v`
Expected: PASS

- [ ] **Step 5: Write failing tests for BD Alti**

```python
# apps/backend/tests/unit/test_source_ign_bd_alti.py
"""Tests for IGN BD ALTI altitude client."""
import pytest
from pytest_httpx import HTTPXMock

from core.sources.ign_bd_alti import fetch_altitude, AltitudeResult

MOCK_ALTI_RESPONSE = {"elevations": [{"lon": 2.4833, "lat": 48.8375, "z": 52.3}]}


class TestFetchAltitude:
    @pytest.mark.asyncio
    async def test_altitude_found(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json=MOCK_ALTI_RESPONSE)
        result = await fetch_altitude(lat=48.8375, lng=2.4833)
        assert isinstance(result, AltitudeResult)
        assert result.altitude_m == 52.3

    @pytest.mark.asyncio
    async def test_no_data(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json={"elevations": []})
        result = await fetch_altitude(lat=0.0, lng=0.0)
        assert result is None
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_ign_bd_alti.py -v`
Expected: FAIL

- [ ] **Step 7: Implement BD Alti client**

```python
# apps/backend/core/sources/ign_bd_alti.py
"""IGN BD ALTI altitude service.

API: https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json
No API key required.
"""
from dataclasses import dataclass

from core.http_client import fetch_json

ALTI_URL = "https://data.geopf.fr/altimetrie/1.0/calcul/alti/rest/elevation.json"


@dataclass(frozen=True)
class AltitudeResult:
    lat: float
    lng: float
    altitude_m: float


async def fetch_altitude(*, lat: float, lng: float) -> AltitudeResult | None:
    """Fetch terrain altitude at a WGS84 point via IGN BD ALTI."""
    data = await fetch_json(
        ALTI_URL,
        params={"lon": str(lng), "lat": str(lat), "zonly": "false"},
    )
    elevations = data.get("elevations", [])
    if not elevations:
        return None
    e = elevations[0]
    z = e.get("z")
    if z is None or z == -99999:
        return None
    return AltitudeResult(lat=lat, lng=lng, altitude_m=float(z))
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_ign_bd_alti.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/core/sources/ign_bdtopo.py apps/backend/core/sources/ign_bd_alti.py apps/backend/tests/unit/test_source_ign_bdtopo.py apps/backend/tests/unit/test_source_ign_bd_alti.py
git commit -m "feat(sources): add IGN BDTopo WFS and BD ALTI altitude clients"
```

---

## Task 7: Clients GeoRisques + POP (patrimoine)

**Files:**
- Create: `apps/backend/core/sources/georisques.py`
- Create: `apps/backend/core/sources/pop.py`
- Test: `apps/backend/tests/unit/test_source_georisques.py`
- Test: `apps/backend/tests/unit/test_source_pop.py`

- [ ] **Step 1: Write failing tests for GeoRisques**

```python
# apps/backend/tests/unit/test_source_georisques.py
"""Tests for GeoRisques API client."""
import pytest
from pytest_httpx import HTTPXMock

from core.sources.georisques import fetch_risques, RisqueResult

MOCK_RISQUES = {
    "results": [
        {
            "code_national": "PPRI-94-001",
            "libelle_risque": "Inondation - Par débordement de cours d'eau",
            "alea": "moyen"
        }
    ]
}

MOCK_ARGILES = {
    "results": [
        {
            "niveau_alea": "fort",
            "description": "Zone d'aléa fort de retrait-gonflement des argiles"
        }
    ]
}


class TestFetchRisques:
    @pytest.mark.asyncio
    async def test_risques_found(self, httpx_mock: HTTPXMock):
        # GeoRisques gaspar + argiles
        httpx_mock.add_response(json=MOCK_RISQUES)
        httpx_mock.add_response(json=MOCK_ARGILES)
        results = await fetch_risques(lat=48.8375, lng=2.4833)
        assert len(results) >= 1
        r = results[0]
        assert isinstance(r, RisqueResult)
        assert "inondation" in r.libelle.lower()

    @pytest.mark.asyncio
    async def test_no_risks(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json={"results": []})
        httpx_mock.add_response(json={"results": []})
        results = await fetch_risques(lat=48.0, lng=2.0)
        assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_georisques.py -v`
Expected: FAIL

- [ ] **Step 3: Implement GeoRisques client**

```python
# apps/backend/core/sources/georisques.py
"""GeoRisques API client — PPRI, argiles, sols pollués.

API: https://georisques.gouv.fr/api/v1/
No API key required.
"""
from dataclasses import dataclass

from core.http_client import fetch_json

GASPAR_URL = "https://georisques.gouv.fr/api/v1/gaspar"
ARGILES_URL = "https://georisques.gouv.fr/api/v1/mvt"


@dataclass(frozen=True)
class RisqueResult:
    type: str  # ppri, argiles, basias, basol
    code: str | None
    libelle: str
    niveau_alea: str | None


async def fetch_risques(*, lat: float, lng: float) -> list[RisqueResult]:
    """Fetch all known risks at a point (PPRI, argiles, sols pollués)."""
    results: list[RisqueResult] = []

    # GASPAR — natural and technological risks
    try:
        data = await fetch_json(
            GASPAR_URL,
            params={"latlon": f"{lat},{lng}", "rayon": "100"},
        )
        for r in data.get("results", []):
            results.append(
                RisqueResult(
                    type="ppri",
                    code=r.get("code_national"),
                    libelle=r.get("libelle_risque", "Risque non précisé"),
                    niveau_alea=r.get("alea"),
                )
            )
    except Exception:
        pass

    # Argiles — retrait-gonflement
    try:
        data = await fetch_json(
            ARGILES_URL,
            params={"latlon": f"{lat},{lng}"},
        )
        for r in data.get("results", []):
            results.append(
                RisqueResult(
                    type="argiles",
                    code=None,
                    libelle=r.get("description", "Retrait-gonflement des argiles"),
                    niveau_alea=r.get("niveau_alea"),
                )
            )
    except Exception:
        pass

    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_georisques.py -v`
Expected: PASS

- [ ] **Step 5: Write failing tests for POP**

```python
# apps/backend/tests/unit/test_source_pop.py
"""Tests for POP (Plateforme Ouverte du Patrimoine) client."""
import pytest
from pytest_httpx import HTTPXMock

from core.sources.pop import fetch_monuments_around, MonumentResult

MOCK_POP_RESPONSE = {
    "total": 1,
    "hits": {
        "hits": [
            {
                "_source": {
                    "REF": "PA00079842",
                    "TICO": "Église Saint-Saturnin",
                    "DPRO": "1906-07-12",
                    "COM": "Nogent-sur-Marne",
                    "DPT": "94",
                    "POP_COORDONNEES": {"lat": 48.837, "lon": 2.483}
                }
            }
        ]
    },
}


class TestFetchMonuments:
    @pytest.mark.asyncio
    async def test_monument_found(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json=MOCK_POP_RESPONSE)
        results = await fetch_monuments_around(lat=48.8375, lng=2.4833, radius_m=500)
        assert len(results) == 1
        m = results[0]
        assert isinstance(m, MonumentResult)
        assert "Saint-Saturnin" in m.nom
        assert m.reference == "PA00079842"

    @pytest.mark.asyncio
    async def test_no_monuments(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json={"total": 0, "hits": {"hits": []}})
        results = await fetch_monuments_around(lat=48.0, lng=2.0, radius_m=500)
        assert results == []
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_pop.py -v`
Expected: FAIL

- [ ] **Step 7: Implement POP client**

```python
# apps/backend/core/sources/pop.py
"""POP (Plateforme Ouverte du Patrimoine) — monuments historiques.

API: https://api.pop.culture.gouv.fr/search/
No API key required.
"""
from dataclasses import dataclass

from core.http_client import post_json

POP_SEARCH_URL = "https://api.pop.culture.gouv.fr/search/"


@dataclass(frozen=True)
class MonumentResult:
    reference: str
    nom: str
    date_protection: str | None
    commune: str | None
    departement: str | None
    lat: float | None
    lng: float | None
    distance_m: float | None = None


async def fetch_monuments_around(
    *, lat: float, lng: float, radius_m: int = 500
) -> list[MonumentResult]:
    """Fetch listed monuments within radius of a point."""
    # POP uses Elasticsearch DSL
    body = {
        "size": 50,
        "query": {
            "bool": {
                "filter": [
                    {
                        "geo_distance": {
                            "distance": f"{radius_m}m",
                            "POP_COORDONNEES": {"lat": lat, "lon": lng},
                        }
                    }
                ]
            }
        },
    }
    data = await post_json(POP_SEARCH_URL, json_body=body)

    results = []
    for hit in data.get("hits", {}).get("hits", []):
        src = hit.get("_source", {})
        coords = src.get("POP_COORDONNEES", {})
        results.append(
            MonumentResult(
                reference=src.get("REF", ""),
                nom=src.get("TICO", "Monument non identifié"),
                date_protection=src.get("DPRO"),
                commune=src.get("COM"),
                departement=src.get("DPT"),
                lat=coords.get("lat"),
                lng=coords.get("lon"),
            )
        )
    return results
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_pop.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/core/sources/georisques.py apps/backend/core/sources/pop.py apps/backend/tests/unit/test_source_georisques.py apps/backend/tests/unit/test_source_pop.py
git commit -m "feat(sources): add GeoRisques and POP patrimoine clients"
```

---

## Task 8: Clients DPE + DVF

**Files:**
- Create: `apps/backend/core/sources/dpe.py`
- Create: `apps/backend/core/sources/dvf.py`
- Test: `apps/backend/tests/unit/test_source_dpe.py`
- Test: `apps/backend/tests/unit/test_source_dvf.py`

- [ ] **Step 1: Write failing tests for DPE**

```python
# apps/backend/tests/unit/test_source_dpe.py
"""Tests for DPE ADEME client."""
import pytest
from pytest_httpx import HTTPXMock

from core.sources.dpe import fetch_dpe_around, DpeResult

MOCK_DPE_RESPONSE = {
    "total": 2,
    "results": [
        {
            "nombre_niveau_immeuble": 5,
            "hauteur_sous_plafond": 2.6,
            "classe_consommation_energie": "D",
            "type_batiment": "immeuble",
            "geo_adresse": "12 Rue du Test 94130 Nogent-sur-Marne"
        },
        {
            "nombre_niveau_immeuble": 4,
            "hauteur_sous_plafond": 2.5,
            "classe_consommation_energie": "E",
            "type_batiment": "immeuble",
            "geo_adresse": "14 Rue du Test 94130 Nogent-sur-Marne"
        }
    ],
}


class TestFetchDpe:
    @pytest.mark.asyncio
    async def test_dpe_found(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json=MOCK_DPE_RESPONSE)
        results = await fetch_dpe_around(lat=48.8375, lng=2.4833, radius_m=30)
        assert len(results) == 2
        assert isinstance(results[0], DpeResult)
        assert results[0].nb_niveaux == 5
        assert results[0].classe_energie == "D"

    @pytest.mark.asyncio
    async def test_no_dpe(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json={"total": 0, "results": []})
        results = await fetch_dpe_around(lat=48.0, lng=2.0, radius_m=30)
        assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_dpe.py -v`
Expected: FAIL

- [ ] **Step 3: Implement DPE client**

```python
# apps/backend/core/sources/dpe.py
"""DPE ADEME — Diagnostic de Performance Énergétique.

API: https://data.ademe.fr/data-fair/api/v1/datasets/meg-83tjwtg8dyz4vv7h1dqe/lines
No API key required.
"""
from dataclasses import dataclass

from core.http_client import fetch_json

DPE_URL = "https://data.ademe.fr/data-fair/api/v1/datasets/meg-83tjwtg8dyz4vv7h1dqe/lines"


@dataclass(frozen=True)
class DpeResult:
    nb_niveaux: int | None
    hauteur_sous_plafond: float | None
    classe_energie: str | None
    type_batiment: str | None
    adresse: str | None


async def fetch_dpe_around(
    *, lat: float, lng: float, radius_m: int = 30
) -> list[DpeResult]:
    """Fetch DPE entries near a point. Prioritizes 'immeuble' type."""
    # ADEME API uses bbox format: lng_min,lat_min,lng_max,lat_max
    dlat = radius_m / 111_000
    dlng = radius_m / 73_000
    bbox = f"{lng - dlng},{lat - dlat},{lng + dlng},{lat + dlat}"

    data = await fetch_json(
        DPE_URL,
        params={
            "geo_distance": f"{lat},{lng},{radius_m}m",
            "size": "20",
            "select": "nombre_niveau_immeuble,hauteur_sous_plafond,classe_consommation_energie,type_batiment,geo_adresse",
        },
    )

    results = []
    for r in data.get("results", []):
        results.append(
            DpeResult(
                nb_niveaux=r.get("nombre_niveau_immeuble"),
                hauteur_sous_plafond=r.get("hauteur_sous_plafond"),
                classe_energie=r.get("classe_consommation_energie"),
                type_batiment=r.get("type_batiment"),
                adresse=r.get("geo_adresse"),
            )
        )

    # Sort: 'immeuble' first (more relevant for urban context)
    results.sort(key=lambda d: (0 if d.type_batiment == "immeuble" else 1))
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_dpe.py -v`
Expected: PASS

- [ ] **Step 5: Write failing tests for DVF**

```python
# apps/backend/tests/unit/test_source_dvf.py
"""Tests for DVF (Demande de Valeurs Foncières) client."""
import pytest
from pytest_httpx import HTTPXMock

from core.sources.dvf import fetch_dvf_parcelle, DvfTransaction

MOCK_DVF_RESPONSE = {
    "resultats": [
        {
            "date_mutation": "2024-03-15",
            "nature_mutation": "Vente",
            "valeur_fonciere": 350000.0,
            "type_local": "Appartement",
            "surface_reelle_bati": 65.0,
            "nombre_pieces_principales": 3,
            "code_commune": "94052",
            "adresse_nom_voie": "RUE DE LA PAIX"
        },
        {
            "date_mutation": "2023-11-20",
            "nature_mutation": "Vente",
            "valeur_fonciere": 280000.0,
            "type_local": "Appartement",
            "surface_reelle_bati": 45.0,
            "nombre_pieces_principales": 2,
            "code_commune": "94052",
            "adresse_nom_voie": "RUE DU CHATEAU"
        }
    ]
}


class TestFetchDvf:
    @pytest.mark.asyncio
    async def test_transactions_found(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json=MOCK_DVF_RESPONSE)
        results = await fetch_dvf_parcelle(code_insee="94052", section="AB", numero="0042")
        assert len(results) == 2
        t = results[0]
        assert isinstance(t, DvfTransaction)
        assert t.valeur_fonciere == 350000.0
        assert t.type_local == "Appartement"
        assert t.surface_m2 == 65.0

    @pytest.mark.asyncio
    async def test_no_transactions(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json={"resultats": []})
        results = await fetch_dvf_parcelle(code_insee="94052", section="ZZ", numero="9999")
        assert results == []
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_dvf.py -v`
Expected: FAIL

- [ ] **Step 7: Implement DVF client**

```python
# apps/backend/core/sources/dvf.py
"""DVF (Demande de Valeurs Foncières) — property transaction history.

API: https://api.cquest.org/dvf (community mirror) or
     https://files.data.gouv.fr/geo-dvf/latest/csv/
No API key required.
"""
from dataclasses import dataclass

from core.http_client import fetch_json

DVF_API_URL = "https://api.cquest.org/dvf"


@dataclass(frozen=True)
class DvfTransaction:
    date_mutation: str
    nature_mutation: str
    valeur_fonciere: float | None
    type_local: str | None
    surface_m2: float | None
    nb_pieces: int | None
    code_commune: str
    adresse: str | None


async def fetch_dvf_parcelle(
    *, code_insee: str, section: str, numero: str
) -> list[DvfTransaction]:
    """Fetch DVF transactions for a specific parcel."""
    # DVF API uses code_commune + section + numero
    data = await fetch_json(
        DVF_API_URL,
        params={
            "code_commune": code_insee,
            "section": section,
            "numero": numero,
        },
    )

    results = []
    for r in data.get("resultats", []):
        results.append(
            DvfTransaction(
                date_mutation=r.get("date_mutation", ""),
                nature_mutation=r.get("nature_mutation", ""),
                valeur_fonciere=r.get("valeur_fonciere"),
                type_local=r.get("type_local"),
                surface_m2=r.get("surface_reelle_bati"),
                nb_pieces=r.get("nombre_pieces_principales"),
                code_commune=r.get("code_commune", code_insee),
                adresse=r.get("adresse_nom_voie"),
            )
        )
    return results
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_dvf.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/core/sources/dpe.py apps/backend/core/sources/dvf.py apps/backend/tests/unit/test_source_dpe.py apps/backend/tests/unit/test_source_dvf.py
git commit -m "feat(sources): add DPE ADEME and DVF transaction clients"
```

---

## Task 9: Modèles SQLAlchemy — parcels, plu_documents, plu_zones, servitudes

**Files:**
- Create: `apps/backend/db/models/parcels.py`
- Create: `apps/backend/db/models/plu.py`
- Create: `apps/backend/db/models/servitudes.py`
- Modify: `apps/backend/db/base.py` (import new models)

- [ ] **Step 1: Read existing db/base.py to understand model registration pattern**

Read: `apps/backend/db/base.py`

- [ ] **Step 2: Create ParcelRow model**

```python
# apps/backend/db/models/parcels.py
"""SQLAlchemy model for cadastral parcels."""
import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import Column, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from db.base import Base


class ParcelRow(Base):
    __tablename__ = "parcels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code_insee = Column(String(5), nullable=False)
    section = Column(String(3), nullable=False)
    numero = Column(String(5), nullable=False)
    contenance_m2 = Column(Integer, nullable=True)
    geom = Column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)
    address = Column(Text, nullable=True)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        {"schema": None},
    )
    # Unique constraint handled in migration for proper index naming
```

- [ ] **Step 3: Create PLU models**

```python
# apps/backend/db/models/plu.py
"""SQLAlchemy models for PLU documents and zones."""
import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import Column, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID

from db.base import Base


class PluDocumentRow(Base):
    __tablename__ = "plu_documents"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code_insee = Column(String(5), nullable=False)
    gpu_doc_id = Column(Text, unique=True, nullable=True)
    partition = Column(Text, nullable=True)
    type = Column(String(20), nullable=True)  # PLU, PLUi, PLUbioclim, POS, RNU, CC
    nomfic = Column(Text, nullable=True)
    pdf_url = Column(Text, nullable=True)
    pdf_sha256 = Column(String(64), nullable=True)
    pdf_text_raw = Column(Text, nullable=True)
    fetched_at = Column(DateTime(timezone=True), nullable=True)
    last_checked_at = Column(DateTime(timezone=True), nullable=True)


class PluZoneRow(Base):
    __tablename__ = "plu_zones"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plu_doc_id = Column(
        UUID(as_uuid=True),
        ForeignKey("plu_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    code = Column(Text, nullable=False)
    libelle = Column(Text, nullable=True)
    libelong = Column(Text, nullable=True)
    typezone = Column(Text, nullable=True)
    geom = Column(Geometry("MULTIPOLYGON", srid=4326), nullable=True)

    # Unique constraint (plu_doc_id, code) handled in migration
```

- [ ] **Step 4: Create Servitude model**

```python
# apps/backend/db/models/servitudes.py
"""SQLAlchemy model for urban servitudes (SUP)."""
import uuid

from geoalchemy2 import Geometry
from sqlalchemy import Column, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID

from db.base import Base


class ServitudeRow(Base):
    __tablename__ = "servitudes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    type = Column(Text, nullable=False)
    sous_type = Column(Text, nullable=True)
    libelle = Column(Text, nullable=True)
    geom = Column(Geometry("GEOMETRY", srid=4326), nullable=True)
    attributes = Column(JSONB, nullable=True)
    source = Column(Text, nullable=True)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 5: Update db/base.py to import new models**

Add imports for the new models so Alembic can detect them during `autogenerate`.

- [ ] **Step 6: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/db/models/parcels.py apps/backend/db/models/plu.py apps/backend/db/models/servitudes.py apps/backend/db/base.py
git commit -m "feat(db): add SQLAlchemy models for parcels, PLU documents/zones, servitudes"
```

---

## Task 10: Migration Alembic — tables parcels, plu_documents, plu_zones, servitudes

**Files:**
- Create: `apps/backend/alembic/versions/20260417_0001_parcels_plu_servitudes.py`

- [ ] **Step 1: Generate Alembic migration**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
alembic revision --autogenerate -m "add parcels plu_documents plu_zones servitudes tables"
```

- [ ] **Step 2: Review and edit generated migration**

The migration should create:
- `parcels` table with PostGIS geometry, unique constraint on `(code_insee, section, numero)`, GiST index on `geom`, GIN trigram index on `address`
- `plu_documents` table
- `plu_zones` table with FK to `plu_documents`, unique on `(plu_doc_id, code)`, GiST index on `geom`
- `servitudes` table with GiST index on `geom`, index on `type`

Verify the migration matches the DDL in spec §6.2. Edit if autogenerate missed indexes or constraints.

```python
# Expected content of the migration (verify autogenerate output matches):
def upgrade():
    # parcels
    op.create_table(
        "parcels",
        sa.Column("id", sa.dialects.postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("code_insee", sa.String(5), nullable=False),
        sa.Column("section", sa.String(3), nullable=False),
        sa.Column("numero", sa.String(5), nullable=False),
        sa.Column("contenance_m2", sa.Integer, nullable=True),
        sa.Column("geom", Geometry("MULTIPOLYGON", srid=4326), nullable=False),
        sa.Column("address", sa.Text, nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("code_insee", "section", "numero", name="uq_parcels_ref"),
    )
    op.create_index("parcels_geom_gist", "parcels", ["geom"], postgresql_using="gist")
    op.execute("CREATE INDEX parcels_address_trgm ON parcels USING GIN (address gin_trgm_ops)")

    # plu_documents
    op.create_table(
        "plu_documents",
        # ... columns per model
    )

    # plu_zones
    op.create_table(
        "plu_zones",
        # ... columns per model, FK to plu_documents
        sa.UniqueConstraint("plu_doc_id", "code", name="uq_plu_zones_doc_code"),
    )
    op.create_index("plu_zones_geom_gist", "plu_zones", ["geom"], postgresql_using="gist")

    # servitudes
    op.create_table(
        "servitudes",
        # ... columns per model
    )
    op.create_index("servitudes_geom_gist", "servitudes", ["geom"], postgresql_using="gist")
    op.create_index("servitudes_type", "servitudes", ["type"])
```

- [ ] **Step 3: Run migration**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
alembic upgrade head
```
Expected: Migration applies successfully, 4 new tables created.

- [ ] **Step 4: Verify tables exist**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
python -c "
from sqlalchemy import create_engine, inspect
engine = create_engine('postgresql://archiclaude:archiclaude@localhost:5432/archiclaude')
insp = inspect(engine)
tables = insp.get_table_names()
for t in ['parcels', 'plu_documents', 'plu_zones', 'servitudes']:
    assert t in tables, f'{t} not found'
    print(f'  ✓ {t}')
print('All tables verified.')
"
```

- [ ] **Step 5: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/alembic/versions/
git commit -m "feat(db): add Alembic migration for parcels, PLU, servitudes tables"
```

---

## Task 11: Schemas Pydantic API — parcels et PLU

**Files:**
- Create: `apps/backend/schemas/parcel.py`
- Create: `apps/backend/schemas/plu.py`

- [ ] **Step 1: Create parcel API schemas**

```python
# apps/backend/schemas/parcel.py
"""Pydantic schemas for parcel API endpoints."""
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ParcelSearchQuery(BaseModel):
    q: str = Field(..., min_length=3, description="Address search query")
    limit: int = Field(5, ge=1, le=20)


class GeocodingResultOut(BaseModel):
    label: str
    score: float
    lat: float
    lng: float
    citycode: str
    city: str


class ParcelOut(BaseModel):
    id: UUID
    code_insee: str
    section: str
    numero: str
    contenance_m2: int | None
    address: str | None
    geometry: dict[str, Any]  # GeoJSON

    class Config:
        from_attributes = True


class ParcelFromApi(BaseModel):
    """Parcel data returned directly from external API (before DB storage)."""
    code_insee: str
    section: str
    numero: str
    contenance_m2: int | None
    commune: str
    geometry: dict[str, Any]
```

- [ ] **Step 2: Create PLU API schemas**

```python
# apps/backend/schemas/plu.py
"""Pydantic schemas for PLU API endpoints."""
from typing import Any

from pydantic import BaseModel


class PluZoneOut(BaseModel):
    libelle: str
    libelong: str | None
    typezone: str
    nomfic: str | None
    urlfic: str | None
    geometry: dict[str, Any] | None


class PluDocumentOut(BaseModel):
    idurba: str
    typedoc: str
    datappro: str | None
    nom: str | None


class ServitudeOut(BaseModel):
    libelle: str
    categorie: str
    txt: str | None
    geometry: dict[str, Any] | None


class PrescriptionOut(BaseModel):
    libelle: str
    txt: str | None
    typepsc: str | None
    geometry: dict[str, Any] | None


class RisqueOut(BaseModel):
    type: str
    code: str | None
    libelle: str
    niveau_alea: str | None


class MonumentOut(BaseModel):
    reference: str
    nom: str
    date_protection: str | None
    commune: str | None
    lat: float | None
    lng: float | None


class PluAtPointResponse(BaseModel):
    """Full urbanisme data at a point."""
    zones: list[PluZoneOut]
    document: PluDocumentOut | None
    servitudes: list[ServitudeOut]
    prescriptions: list[PrescriptionOut]
    risques: list[RisqueOut]
    monuments: list[MonumentOut]
```

- [ ] **Step 3: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/schemas/parcel.py apps/backend/schemas/plu.py
git commit -m "feat(schemas): add Pydantic API schemas for parcels and PLU endpoints"
```

---

## Task 12: Endpoints API /parcels/*

**Files:**
- Create: `apps/backend/api/routes/parcels.py`
- Modify: `apps/backend/api/main.py` (register router)
- Modify: `apps/backend/tests/conftest.py` (add Redis mock fixture)
- Test: `apps/backend/tests/integration/test_parcels_endpoints.py`

- [ ] **Step 1: Write failing integration tests for parcel endpoints**

```python
# apps/backend/tests/integration/test_parcels_endpoints.py
"""Integration tests for /parcels/* endpoints."""
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _ban_fixture():
    data = json.loads((FIXTURES / "ban_responses.json").read_text())
    return data["geocode_12_rue_paix_paris"]


def _cadastre_fixture():
    data = json.loads((FIXTURES / "cadastre_responses.json").read_text())
    return data["parcelle_at_point_paris"]


class TestParcelSearch:
    @pytest.mark.asyncio
    async def test_search_returns_results(self, client: AsyncClient):
        with patch("api.routes.parcels.ban.geocode", new_callable=AsyncMock) as mock_geo:
            from core.sources.ban import GeocodingResult

            mock_geo.return_value = [
                GeocodingResult(
                    label="12 Rue de la Paix 75002 Paris",
                    score=0.95,
                    lat=48.869,
                    lng=2.331,
                    citycode="75102",
                    city="Paris",
                )
            ]
            resp = await client.get("/api/v1/parcels/search", params={"q": "12 rue de la Paix Paris"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["label"] == "12 Rue de la Paix 75002 Paris"

    @pytest.mark.asyncio
    async def test_search_short_query_422(self, client: AsyncClient):
        resp = await client.get("/api/v1/parcels/search", params={"q": "ab"})
        assert resp.status_code == 422


class TestParcelAtPoint:
    @pytest.mark.asyncio
    async def test_at_point_returns_parcel(self, client: AsyncClient):
        with patch(
            "api.routes.parcels.cadastre.fetch_parcelle_at_point",
            new_callable=AsyncMock,
        ) as mock_cad:
            from core.sources.cadastre import ParcelleResult

            mock_cad.return_value = ParcelleResult(
                code_insee="75102",
                section="AH",
                numero="0015",
                contenance_m2=890,
                commune="Paris",
                geometry={"type": "MultiPolygon", "coordinates": []},
            )
            resp = await client.get(
                "/api/v1/parcels/at-point", params={"lat": "48.869", "lng": "2.310"}
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["section"] == "AH"
        assert data["contenance_m2"] == 890
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/integration/test_parcels_endpoints.py -v`
Expected: FAIL

- [ ] **Step 3: Implement parcel routes**

```python
# apps/backend/api/routes/parcels.py
"""Parcel search and lookup endpoints."""
from fastapi import APIRouter, HTTPException, Query

from core.sources import ban, cadastre
from schemas.parcel import GeocodingResultOut, ParcelFromApi

router = APIRouter(prefix="/parcels", tags=["parcels"])


@router.get("/search", response_model=list[GeocodingResultOut])
async def search_parcels(
    q: str = Query(..., min_length=3, description="Address search query"),
    limit: int = Query(5, ge=1, le=20),
):
    """Geocode an address via BAN API."""
    results = await ban.geocode(q, limit=limit)
    return [
        GeocodingResultOut(
            label=r.label,
            score=r.score,
            lat=r.lat,
            lng=r.lng,
            citycode=r.citycode,
            city=r.city,
        )
        for r in results
    ]


@router.get("/at-point", response_model=ParcelFromApi)
async def parcel_at_point(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    """Fetch the cadastral parcel at a given point."""
    result = await cadastre.fetch_parcelle_at_point(lat=lat, lng=lng)
    if result is None:
        raise HTTPException(status_code=404, detail="No parcel found at this location")
    return ParcelFromApi(
        code_insee=result.code_insee,
        section=result.section,
        numero=result.numero,
        contenance_m2=result.contenance_m2,
        commune=result.commune,
        geometry=result.geometry,
    )


@router.get("/by-ref", response_model=ParcelFromApi)
async def parcel_by_ref(
    insee: str = Query(..., pattern=r"^\d{5}$"),
    section: str = Query(..., pattern=r"^[0-9A-Z]{1,3}$"),
    numero: str = Query(..., pattern=r"^\d{1,5}$"),
):
    """Fetch a parcel by cadastral reference (INSEE + section + numero)."""
    result = await cadastre.fetch_parcelle_by_ref(
        code_insee=insee, section=section, numero=numero
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Parcel not found")
    return ParcelFromApi(
        code_insee=result.code_insee,
        section=result.section,
        numero=result.numero,
        contenance_m2=result.contenance_m2,
        commune=result.commune,
        geometry=result.geometry,
    )
```

- [ ] **Step 4: Register parcels router in main.py**

Add to `apps/backend/api/main.py`:
```python
from api.routes.parcels import router as parcels_router
app.include_router(parcels_router, prefix="/api/v1")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/integration/test_parcels_endpoints.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/api/routes/parcels.py apps/backend/api/main.py apps/backend/tests/integration/test_parcels_endpoints.py
git commit -m "feat(api): add /parcels/search, /at-point, /by-ref endpoints"
```

---

## Task 13: Endpoint API /plu/at-point

**Files:**
- Create: `apps/backend/api/routes/plu.py`
- Modify: `apps/backend/api/main.py` (register router)
- Test: `apps/backend/tests/integration/test_plu_endpoints.py`

- [ ] **Step 1: Write failing integration tests**

```python
# apps/backend/tests/integration/test_plu_endpoints.py
"""Integration tests for /plu/at-point endpoint."""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient


class TestPluAtPoint:
    @pytest.mark.asyncio
    async def test_returns_zones_and_servitudes(self, client: AsyncClient):
        from core.sources.gpu import GpuZone, GpuDocument, GpuServitude, GpuPrescription
        from core.sources.georisques import RisqueResult
        from core.sources.pop import MonumentResult

        mock_zones = [
            GpuZone(
                libelle="UB", libelong="Zone urbaine mixte",
                typezone="U", partition="94052_PLUi", idurba="94052_PLUi",
                nomfic="reglement.pdf", urlfic="https://gpu.beta.gouv.fr/doc.pdf",
                geometry={"type": "MultiPolygon", "coordinates": []},
            )
        ]
        mock_doc = [
            GpuDocument(idurba="94052_PLUi", typedoc="PLUi", datappro="2022-01-01", nom="PLUi VdM")
        ]
        mock_servitudes = [
            GpuServitude(
                libelle="Périmètre MH", categorie="AC1",
                txt="Protection église", geometry=None,
            )
        ]
        mock_prescriptions = []
        mock_risques = [
            RisqueResult(type="argiles", code=None, libelle="Retrait-gonflement", niveau_alea="moyen")
        ]
        mock_monuments = [
            MonumentResult(
                reference="PA00079842", nom="Église Saint-Saturnin",
                date_protection="1906", commune="Nogent-sur-Marne",
                departement="94", lat=48.837, lng=2.483,
            )
        ]

        with (
            patch("api.routes.plu.gpu.fetch_zones_at_point", new_callable=AsyncMock, return_value=mock_zones),
            patch("api.routes.plu.gpu.fetch_document", new_callable=AsyncMock, return_value=mock_doc),
            patch("api.routes.plu.gpu.fetch_servitudes_at_point", new_callable=AsyncMock, return_value=mock_servitudes),
            patch("api.routes.plu.gpu.fetch_prescriptions_at_point", new_callable=AsyncMock, return_value=mock_prescriptions),
            patch("api.routes.plu.georisques.fetch_risques", new_callable=AsyncMock, return_value=mock_risques),
            patch("api.routes.plu.pop.fetch_monuments_around", new_callable=AsyncMock, return_value=mock_monuments),
        ):
            resp = await client.get("/api/v1/plu/at-point", params={"lat": "48.8375", "lng": "2.4833"})

        assert resp.status_code == 200
        data = resp.json()
        assert len(data["zones"]) == 1
        assert data["zones"][0]["libelle"] == "UB"
        assert data["document"]["typedoc"] == "PLUi"
        assert len(data["servitudes"]) == 1
        assert data["servitudes"][0]["categorie"] == "AC1"
        assert len(data["risques"]) == 1
        assert len(data["monuments"]) == 1

    @pytest.mark.asyncio
    async def test_missing_params_422(self, client: AsyncClient):
        resp = await client.get("/api/v1/plu/at-point")
        assert resp.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/integration/test_plu_endpoints.py -v`
Expected: FAIL

- [ ] **Step 3: Implement PLU route**

```python
# apps/backend/api/routes/plu.py
"""PLU urbanisme endpoints."""
import asyncio

from fastapi import APIRouter, Query

from core.sources import georisques, gpu, pop
from schemas.plu import (
    MonumentOut,
    PluAtPointResponse,
    PluDocumentOut,
    PluZoneOut,
    PrescriptionOut,
    RisqueOut,
    ServitudeOut,
)

router = APIRouter(prefix="/plu", tags=["plu"])


@router.get("/at-point", response_model=PluAtPointResponse)
async def plu_at_point(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    """Fetch all urbanisme data at a point: zones, document, servitudes, prescriptions, risks, monuments."""
    # Parallel fetch all sources
    (
        zones_raw,
        docs_raw,
        servitudes_raw,
        prescriptions_raw,
        risques_raw,
        monuments_raw,
    ) = await asyncio.gather(
        gpu.fetch_zones_at_point(lat=lat, lng=lng),
        gpu.fetch_document(lat=lat, lng=lng),
        gpu.fetch_servitudes_at_point(lat=lat, lng=lng),
        gpu.fetch_prescriptions_at_point(lat=lat, lng=lng),
        georisques.fetch_risques(lat=lat, lng=lng),
        pop.fetch_monuments_around(lat=lat, lng=lng, radius_m=500),
    )

    zones = [
        PluZoneOut(
            libelle=z.libelle,
            libelong=z.libelong,
            typezone=z.typezone,
            nomfic=z.nomfic,
            urlfic=z.urlfic,
            geometry=z.geometry,
        )
        for z in zones_raw
    ]

    document = None
    if docs_raw:
        d = docs_raw[0]
        document = PluDocumentOut(
            idurba=d.idurba, typedoc=d.typedoc, datappro=d.datappro, nom=d.nom
        )

    servitudes = [
        ServitudeOut(
            libelle=s.libelle,
            categorie=s.categorie,
            txt=s.txt,
            geometry=s.geometry,
        )
        for s in servitudes_raw
    ]

    prescriptions = [
        PrescriptionOut(
            libelle=p.libelle, txt=p.txt, typepsc=p.typepsc, geometry=p.geometry
        )
        for p in prescriptions_raw
    ]

    risques = [
        RisqueOut(
            type=r.type, code=r.code, libelle=r.libelle, niveau_alea=r.niveau_alea
        )
        for r in risques_raw
    ]

    monuments = [
        MonumentOut(
            reference=m.reference,
            nom=m.nom,
            date_protection=m.date_protection,
            commune=m.commune,
            lat=m.lat,
            lng=m.lng,
        )
        for m in monuments_raw
    ]

    return PluAtPointResponse(
        zones=zones,
        document=document,
        servitudes=servitudes,
        prescriptions=prescriptions,
        risques=risques,
        monuments=monuments,
    )
```

- [ ] **Step 4: Register PLU router in main.py**

Add to `apps/backend/api/main.py`:
```python
from api.routes.plu import router as plu_router
app.include_router(plu_router, prefix="/api/v1")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/integration/test_plu_endpoints.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/api/routes/plu.py apps/backend/api/main.py apps/backend/tests/integration/test_plu_endpoints.py
git commit -m "feat(api): add /plu/at-point endpoint aggregating GPU, GeoRisques, POP"
```

---

## Task 14: Tests d'intégration avec fixtures de référence

**Files:**
- Modify: `apps/backend/tests/fixtures/parcelles_reference.yaml` (enrich with expected API responses)
- Create: `apps/backend/tests/integration/test_reference_parcels.py`

- [ ] **Step 1: Read current fixtures to understand structure**

Read: `apps/backend/tests/fixtures/parcelles_reference.yaml`

- [ ] **Step 2: Write integration tests using reference parcels**

```python
# apps/backend/tests/integration/test_reference_parcels.py
"""Integration tests validating full data pipeline against reference parcels.

Uses the 5 reference parcels from parcelles_reference.yaml to validate
that the source clients + API endpoints produce consistent results.
"""
import yaml
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from core.sources.ban import GeocodingResult

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load_reference_parcels() -> list[dict]:
    with open(FIXTURES / "parcelles_reference.yaml") as f:
        data = yaml.safe_load(f)
    return data.get("parcelles", data.get("parcels", []))


class TestReferenceParcels:
    """Smoke tests ensuring all 5 reference parcels can be geocoded and looked up."""

    @pytest.mark.asyncio
    async def test_paris_8e_geocodable(self, client: AsyncClient):
        """Paris 8e (UG bioclim) should geocode via BAN."""
        with patch("api.routes.parcels.ban.geocode", new_callable=AsyncMock) as mock:
            mock.return_value = [
                GeocodingResult(
                    label="Rue du Faubourg Saint-Honoré 75008 Paris",
                    score=0.92,
                    lat=48.8722,
                    lng=2.3155,
                    citycode="75108",
                    city="Paris",
                )
            ]
            resp = await client.get(
                "/api/v1/parcels/search",
                params={"q": "Faubourg Saint-Honoré Paris 8e"},
            )
        assert resp.status_code == 200
        assert len(resp.json()) >= 1
        assert resp.json()[0]["citycode"] == "75108"

    @pytest.mark.asyncio
    async def test_nogent_by_ref(self, client: AsyncClient):
        """Nogent-sur-Marne (UB PLUi) should be fetchable by ref."""
        from core.sources.cadastre import ParcelleResult

        with patch(
            "api.routes.parcels.cadastre.fetch_parcelle_by_ref",
            new_callable=AsyncMock,
        ) as mock:
            mock.return_value = ParcelleResult(
                code_insee="94052",
                section="AB",
                numero="0042",
                contenance_m2=1250,
                commune="Nogent-sur-Marne",
                geometry={"type": "MultiPolygon", "coordinates": []},
            )
            resp = await client.get(
                "/api/v1/parcels/by-ref",
                params={"insee": "94052", "section": "AB", "numero": "00042"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["code_insee"] == "94052"
        assert data["contenance_m2"] == 1250
```

- [ ] **Step 3: Run tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/integration/test_reference_parcels.py -v`
Expected: PASS

- [ ] **Step 4: Run full test suite**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest -v --tb=short`
Expected: All tests pass (Phase 0 tests + all new Phase 1 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/tests/integration/test_reference_parcels.py
git commit -m "test: add integration tests against reference parcels for Phase 1 pipeline"
```

---

## Task 15: Vérification finale et nettoyage

- [ ] **Step 1: Run linter**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
ruff check . --fix
```

- [ ] **Step 2: Run type checker**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
mypy core/ api/ schemas/ db/ --ignore-missing-imports
```

- [ ] **Step 3: Run full test suite with coverage**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
python -m pytest -v --cov=core --cov=api --cov=schemas --cov-report=term-missing
```
Expected: All tests pass, reasonable coverage on new modules.

- [ ] **Step 4: Fix any issues found**

Address lint warnings, type errors, or test failures.

- [ ] **Step 5: Final commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add -A
git commit -m "chore: Phase 1 lint/type fixes and cleanup"
```
