# ArchiClaude — Phase 2 : Sources de site enrichies — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire les clients de données de site (photos Mapillary/Street View, bruit Cerema/Bruitparif, transports IGN/Navitia, comparables, SRU), les modules d'analyse de site (orientation, voisinage), les tables DB associées (comparable_projects, commune_sru), et les 7 endpoints API `/site/*`.

**Architecture:** Modules `core/sources/*.py` pour les API externes (Mapillary, Street View, Cerema, Bruitparif, Navitia, Sitadel, INSEE SRU), modules `core/site/*.py` pour la logique de calcul (orientation segments, agrégation bruit, qualification transports, enrichissement voisinage), routes FastAPI `api/routes/site.py`, modèles DB pour les tables mutualisées.

**Tech Stack:** Python 3.12, httpx, tenacity, shapely (azimut), pyproj, anthropic SDK (vision Claude pour voisinage), SQLAlchemy 2.0, Alembic, FastAPI, pytest + pytest-httpx.

**Spec source:** `docs/superpowers/specs/2026-04-16-archiclaude-sous-projet-1-design.md` §3.7-3.11 (Sources), §5.12-5.13 (Site + Comparables), §7.2 (Endpoints /site/*)

---

## File Structure (final état Phase 2)

```
apps/backend/
├── core/
│   ├── sources/
│   │   ├── mapillary.py                     (NEW — street-level photos)
│   │   ├── google_streetview.py             (NEW — fallback photos)
│   │   ├── cerema_bruit.py                  (NEW — classement sonore voies)
│   │   ├── bruitparif.py                    (NEW — cartes bruit IDF)
│   │   ├── ign_transports.py               (NEW — arrêts TC WFS)
│   │   ├── navitia.py                       (NEW — fréquence lignes IDF)
│   │   ├── sitadel.py                       (NEW — PC délivrés open data)
│   │   └── insee_sru.py                     (NEW — statut SRU communes)
│   └── site/
│       ├── __init__.py                      (NEW)
│       ├── orientation.py                   (NEW — azimut segments parcelle)
│       ├── bruit.py                         (NEW — agrégation bruit)
│       ├── transports.py                    (NEW — qualification desserte)
│       └── voisinage.py                     (NEW — BDTopo enrichi + vision)
├── api/
│   ├── routes/
│   │   └── site.py                          (NEW — /site/* endpoints)
│   └── main.py                              (MODIFY — register site router)
├── db/
│   └── models/
│       ├── comparable_projects.py           (NEW)
│       └── commune_sru.py                   (NEW)
├── schemas/
│   └── site.py                              (NEW — API schemas for /site/*)
├── alembic/versions/
│   └── 20260417_0002_comparable_projects_commune_sru.py (NEW)
└── tests/
    ├── unit/
    │   ├── test_source_mapillary.py          (NEW)
    │   ├── test_source_streetview.py         (NEW)
    │   ├── test_source_cerema_bruit.py       (NEW)
    │   ├── test_source_bruitparif.py         (NEW)
    │   ├── test_source_ign_transports.py     (NEW)
    │   ├── test_source_navitia.py            (NEW)
    │   ├── test_source_sitadel.py            (NEW)
    │   ├── test_source_insee_sru.py          (NEW)
    │   ├── test_site_orientation.py          (NEW)
    │   ├── test_site_bruit.py               (NEW)
    │   ├── test_site_transports.py          (NEW)
    │   └── test_site_voisinage.py           (NEW)
    └── integration/
        └── test_site_endpoints.py           (NEW)
```

**Responsabilités par fichier :**
- `core/sources/mapillary.py` : recherche photos street-level dans un rayon via Mapillary Graph API
- `core/sources/google_streetview.py` : fallback via Google Street View Static API (payant)
- `core/sources/cerema_bruit.py` : classement sonore des voies via data.gouv.fr / WMS Cerema
- `core/sources/bruitparif.py` : cartes de bruit IDF, mesures ponctuelles Bruitparif
- `core/sources/ign_transports.py` : arrêts TC via WFS IGN Géoplateforme
- `core/sources/navitia.py` : fréquence des lignes via API STIF Île-de-France Mobilités
- `core/sources/sitadel.py` : PC délivrés open data (Paris, données agrégées)
- `core/sources/insee_sru.py` : statut SRU communal via data.gouv.fr
- `core/site/orientation.py` : calcul azimut + qualification cardinale de chaque segment de parcelle
- `core/site/bruit.py` : agrégation Cerema + Bruitparif → classement dominant + obligation acoustique
- `core/site/transports.py` : liste arrêts + qualification "bien desservie" + exonération stationnement
- `core/site/voisinage.py` : enrichissement BDTopo voisins + usage DPE + détection ouvertures via vision Claude
- `api/routes/site.py` : 7 endpoints REST `/site/*`
- `schemas/site.py` : Pydantic request/response pour toutes les routes site

---

## Task 1: Client Mapillary + Google Street View (photos de site)

**Files:**
- Create: `apps/backend/core/sources/mapillary.py`
- Create: `apps/backend/core/sources/google_streetview.py`
- Test: `apps/backend/tests/unit/test_source_mapillary.py`
- Test: `apps/backend/tests/unit/test_source_streetview.py`

- [ ] **Step 1: Write failing tests for Mapillary**

```python
# apps/backend/tests/unit/test_source_mapillary.py
"""Tests for Mapillary street-level photos client."""
import os
import pytest
from pytest_httpx import HTTPXMock

from core.sources.mapillary import fetch_photos_around, MapillaryPhoto

MOCK_RESPONSE = {
    "data": [
        {
            "id": "1234567890",
            "captured_at": 1700000000000,
            "compass_angle": 135.5,
            "thumb_1024_url": "https://scontent.mapillary.com/thumb1024_1234567890.jpg",
            "geometry": {"type": "Point", "coordinates": [2.4833, 48.8375]}
        },
        {
            "id": "9876543210",
            "captured_at": 1695000000000,
            "compass_angle": 270.0,
            "thumb_1024_url": "https://scontent.mapillary.com/thumb1024_9876543210.jpg",
            "geometry": {"type": "Point", "coordinates": [2.4835, 48.8377]}
        }
    ]
}


class TestFetchPhotosAround:
    @pytest.mark.asyncio
    async def test_photos_found(self, httpx_mock: HTTPXMock, monkeypatch):
        monkeypatch.setenv("MAPILLARY_CLIENT_TOKEN", "test-token")
        httpx_mock.add_response(json=MOCK_RESPONSE)
        results = await fetch_photos_around(lat=48.8375, lng=2.4833, radius_m=50)
        assert len(results) == 2
        p = results[0]
        assert isinstance(p, MapillaryPhoto)
        assert p.image_id == "1234567890"
        assert p.thumb_url is not None
        assert p.compass_angle == 135.5

    @pytest.mark.asyncio
    async def test_no_photos(self, httpx_mock: HTTPXMock, monkeypatch):
        monkeypatch.setenv("MAPILLARY_CLIENT_TOKEN", "test-token")
        httpx_mock.add_response(json={"data": []})
        results = await fetch_photos_around(lat=48.0, lng=2.0, radius_m=50)
        assert results == []

    @pytest.mark.asyncio
    async def test_no_token_returns_empty(self, monkeypatch):
        monkeypatch.delenv("MAPILLARY_CLIENT_TOKEN", raising=False)
        results = await fetch_photos_around(lat=48.8375, lng=2.4833, radius_m=50)
        assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_mapillary.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement Mapillary client**

```python
# apps/backend/core/sources/mapillary.py
"""Mapillary Graph API — street-level contributive photos.

API: https://graph.mapillary.com/images
Requires MAPILLARY_CLIENT_TOKEN env var.
Free access, coverage varies in IDF.
"""
import os
from dataclasses import dataclass

from core.http_client import fetch_json

MAPILLARY_URL = "https://graph.mapillary.com/images"


@dataclass(frozen=True)
class MapillaryPhoto:
    image_id: str
    thumb_url: str
    captured_at: int  # unix ms
    compass_angle: float  # degrees, 0=north
    lat: float
    lng: float


async def fetch_photos_around(
    *, lat: float, lng: float, radius_m: int = 50
) -> list[MapillaryPhoto]:
    """Fetch Mapillary street-level photos within radius of a point.

    Returns empty list if MAPILLARY_CLIENT_TOKEN is not set (graceful degradation).
    """
    token = os.environ.get("MAPILLARY_CLIENT_TOKEN")
    if not token:
        return []

    # Mapillary uses bbox: west,south,east,north
    dlat = radius_m / 111_000
    dlng = radius_m / 73_000
    bbox = f"{lng - dlng},{lat - dlat},{lng + dlng},{lat + dlat}"

    data = await fetch_json(
        MAPILLARY_URL,
        params={
            "access_token": token,
            "fields": "id,captured_at,compass_angle,thumb_1024_url,geometry",
            "bbox": bbox,
            "limit": "20",
        },
    )

    results = []
    for item in data.get("data", []):
        coords = item.get("geometry", {}).get("coordinates", [0, 0])
        results.append(
            MapillaryPhoto(
                image_id=str(item["id"]),
                thumb_url=item.get("thumb_1024_url", ""),
                captured_at=item.get("captured_at", 0),
                compass_angle=item.get("compass_angle", 0.0),
                lat=coords[1],
                lng=coords[0],
            )
        )
    # Most recent first
    results.sort(key=lambda p: p.captured_at, reverse=True)
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_mapillary.py -v`
Expected: PASS

- [ ] **Step 5: Write failing tests for Google Street View**

```python
# apps/backend/tests/unit/test_source_streetview.py
"""Tests for Google Street View Static API client (fallback)."""
import os
import pytest
from pytest_httpx import HTTPXMock

from core.sources.google_streetview import fetch_streetview_image, StreetViewImage

MOCK_METADATA = {
    "status": "OK",
    "pano_id": "abc123def456",
    "location": {"lat": 48.8375, "lng": 2.4833},
    "date": "2024-06"
}


class TestFetchStreetViewImage:
    @pytest.mark.asyncio
    async def test_image_found(self, httpx_mock: HTTPXMock, monkeypatch):
        monkeypatch.setenv("GOOGLE_STREETVIEW_API_KEY", "test-key")
        httpx_mock.add_response(json=MOCK_METADATA)
        result = await fetch_streetview_image(lat=48.8375, lng=2.4833)
        assert result is not None
        assert isinstance(result, StreetViewImage)
        assert result.pano_id == "abc123def456"
        assert result.image_url is not None

    @pytest.mark.asyncio
    async def test_no_coverage(self, httpx_mock: HTTPXMock, monkeypatch):
        monkeypatch.setenv("GOOGLE_STREETVIEW_API_KEY", "test-key")
        httpx_mock.add_response(json={"status": "ZERO_RESULTS"})
        result = await fetch_streetview_image(lat=0.0, lng=0.0)
        assert result is None

    @pytest.mark.asyncio
    async def test_no_api_key_returns_none(self, monkeypatch):
        monkeypatch.delenv("GOOGLE_STREETVIEW_API_KEY", raising=False)
        result = await fetch_streetview_image(lat=48.8375, lng=2.4833)
        assert result is None
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_streetview.py -v`
Expected: FAIL

- [ ] **Step 7: Implement Google Street View client**

```python
# apps/backend/core/sources/google_streetview.py
"""Google Street View Static API — fallback for site photos.

API: https://maps.googleapis.com/maps/api/streetview/metadata
Requires GOOGLE_STREETVIEW_API_KEY env var. Paid (~$7/1000 images).
Used only when Mapillary has no nearby coverage.
"""
import os
from dataclasses import dataclass

from core.http_client import fetch_json

METADATA_URL = "https://maps.googleapis.com/maps/api/streetview/metadata"
IMAGE_BASE_URL = "https://maps.googleapis.com/maps/api/streetview"


@dataclass(frozen=True)
class StreetViewImage:
    pano_id: str
    lat: float
    lng: float
    date: str | None  # "YYYY-MM"
    image_url: str  # constructed URL for 600x400 image


async def fetch_streetview_image(
    *, lat: float, lng: float, heading: int = 0, fov: int = 90
) -> StreetViewImage | None:
    """Check Street View coverage and return image URL if available.

    Returns None if no API key or no coverage at this location.
    """
    api_key = os.environ.get("GOOGLE_STREETVIEW_API_KEY")
    if not api_key:
        return None

    data = await fetch_json(
        METADATA_URL,
        params={"location": f"{lat},{lng}", "key": api_key},
    )

    if data.get("status") != "OK":
        return None

    pano_id = data.get("pano_id", "")
    loc = data.get("location", {})
    image_url = (
        f"{IMAGE_BASE_URL}?size=600x400&pano={pano_id}"
        f"&heading={heading}&fov={fov}&key={api_key}"
    )

    return StreetViewImage(
        pano_id=pano_id,
        lat=loc.get("lat", lat),
        lng=loc.get("lng", lng),
        date=data.get("date"),
        image_url=image_url,
    )
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_streetview.py -v`
Expected: PASS

- [ ] **Step 9: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/core/sources/mapillary.py apps/backend/core/sources/google_streetview.py apps/backend/tests/unit/test_source_mapillary.py apps/backend/tests/unit/test_source_streetview.py
git commit -m "feat(sources): add Mapillary + Google Street View photo clients"
```

---

## Task 2: Clients bruit — Cerema + Bruitparif

**Files:**
- Create: `apps/backend/core/sources/cerema_bruit.py`
- Create: `apps/backend/core/sources/bruitparif.py`
- Test: `apps/backend/tests/unit/test_source_cerema_bruit.py`
- Test: `apps/backend/tests/unit/test_source_bruitparif.py`

- [ ] **Step 1: Write failing tests for Cerema**

```python
# apps/backend/tests/unit/test_source_cerema_bruit.py
"""Tests for Cerema noise classification client."""
import pytest
from pytest_httpx import HTTPXMock

from core.sources.cerema_bruit import fetch_classement_sonore, ClassementSonore

MOCK_RESPONSE = {
    "features": [
        {
            "properties": {
                "cat_bruit": 3,
                "type_infra": "route",
                "nom_voie": "Avenue de Vincennes",
                "lden": 68.5
            }
        },
        {
            "properties": {
                "cat_bruit": 4,
                "type_infra": "route",
                "nom_voie": "Rue du Château",
                "lden": 62.0
            }
        }
    ]
}


class TestFetchClassementSonore:
    @pytest.mark.asyncio
    async def test_voies_found(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json=MOCK_RESPONSE)
        results = await fetch_classement_sonore(lat=48.8375, lng=2.4833, radius_m=200)
        assert len(results) == 2
        assert isinstance(results[0], ClassementSonore)
        assert results[0].categorie == 3
        assert results[0].nom_voie == "Avenue de Vincennes"
        assert results[0].lden == 68.5

    @pytest.mark.asyncio
    async def test_no_voies(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json={"features": []})
        results = await fetch_classement_sonore(lat=48.0, lng=2.0, radius_m=200)
        assert results == []
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement Cerema client**

```python
# apps/backend/core/sources/cerema_bruit.py
"""Cerema — classement sonore des voies terrestres.

Source: data.gouv.fr or WMS carto.geosignal.fr
Categories: 1 (très bruyant, >81dB) to 5 (calme, <55dB).
No API key required.
"""
from dataclasses import dataclass

from core.http_client import fetch_json

# WFS endpoint for noise classification data
CEREMA_WFS_URL = "https://data.geopf.fr/wfs/ows"


@dataclass(frozen=True)
class ClassementSonore:
    categorie: int  # 1-5, 1=très bruyant
    type_infra: str  # route, voie_ferree
    nom_voie: str | None
    lden: float | None  # dB(A) Lden


async def fetch_classement_sonore(
    *, lat: float, lng: float, radius_m: int = 200
) -> list[ClassementSonore]:
    """Fetch noise classification of roads near a point."""
    dlat = radius_m / 111_000
    dlng = radius_m / 73_000
    bbox = f"{lat - dlat},{lng - dlng},{lat + dlat},{lng + dlng}"

    try:
        data = await fetch_json(
            CEREMA_WFS_URL,
            params={
                "SERVICE": "WFS",
                "VERSION": "2.0.0",
                "REQUEST": "GetFeature",
                "TYPENAMES": "BDNB:classement_sonore_infrastructure",
                "SRSNAME": "EPSG:4326",
                "BBOX": bbox,
                "COUNT": "50",
                "OUTPUTFORMAT": "application/json",
            },
        )
    except Exception:
        return []

    results = []
    for f in data.get("features", []):
        props = f.get("properties", {})
        results.append(
            ClassementSonore(
                categorie=props.get("cat_bruit", 5),
                type_infra=props.get("type_infra", "route"),
                nom_voie=props.get("nom_voie"),
                lden=props.get("lden"),
            )
        )
    return results
```

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Write failing tests + implement Bruitparif**

```python
# apps/backend/tests/unit/test_source_bruitparif.py
"""Tests for Bruitparif IDF noise data client."""
import pytest
from pytest_httpx import HTTPXMock

from core.sources.bruitparif import fetch_bruit_idf, BruitparifResult

MOCK_RESPONSE = {
    "results": [
        {
            "lden": 65.2,
            "lnight": 58.1,
            "source_type": "routier",
            "code_insee": "94052"
        }
    ]
}


class TestFetchBruitIdf:
    @pytest.mark.asyncio
    async def test_data_found(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json=MOCK_RESPONSE)
        result = await fetch_bruit_idf(lat=48.8375, lng=2.4833)
        assert result is not None
        assert isinstance(result, BruitparifResult)
        assert result.lden == 65.2

    @pytest.mark.asyncio
    async def test_no_data(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json={"results": []})
        result = await fetch_bruit_idf(lat=48.0, lng=2.0)
        assert result is None
```

```python
# apps/backend/core/sources/bruitparif.py
"""Bruitparif — IDF-specific noise cartography.

Source: rumeur.bruitparif.fr — finer than Cerema for Île-de-France.
No API key required.
"""
from dataclasses import dataclass

from core.http_client import fetch_json

BRUITPARIF_URL = "https://rumeur.bruitparif.fr/api/v1/noise"


@dataclass(frozen=True)
class BruitparifResult:
    lden: float  # dB(A) Lden (day-evening-night)
    lnight: float | None  # dB(A) Lnight
    source_type: str | None  # routier, ferroviaire, aerien
    code_insee: str | None


async def fetch_bruit_idf(*, lat: float, lng: float) -> BruitparifResult | None:
    """Fetch Bruitparif noise level at a point in IDF."""
    try:
        data = await fetch_json(
            BRUITPARIF_URL,
            params={"lat": str(lat), "lon": str(lng)},
        )
    except Exception:
        return None

    results = data.get("results", [])
    if not results:
        return None

    r = results[0]
    return BruitparifResult(
        lden=r.get("lden", 0.0),
        lnight=r.get("lnight"),
        source_type=r.get("source_type"),
        code_insee=r.get("code_insee"),
    )
```

- [ ] **Step 6: Run all bruit tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_cerema_bruit.py tests/unit/test_source_bruitparif.py -v`

- [ ] **Step 7: Commit**

```bash
git add apps/backend/core/sources/cerema_bruit.py apps/backend/core/sources/bruitparif.py apps/backend/tests/unit/test_source_cerema_bruit.py apps/backend/tests/unit/test_source_bruitparif.py
git commit -m "feat(sources): add Cerema + Bruitparif noise classification clients"
```

---

## Task 3: Clients transports — IGN arrêts TC + Navitia fréquence

**Files:**
- Create: `apps/backend/core/sources/ign_transports.py`
- Create: `apps/backend/core/sources/navitia.py`
- Test: `apps/backend/tests/unit/test_source_ign_transports.py`
- Test: `apps/backend/tests/unit/test_source_navitia.py`

- [ ] **Step 1: Write failing tests for IGN transports**

```python
# apps/backend/tests/unit/test_source_ign_transports.py
"""Tests for IGN Géoplateforme transport stops WFS client."""
import pytest
from pytest_httpx import HTTPXMock

from core.sources.ign_transports import fetch_arrets_around, ArretTC

MOCK_WFS = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [2.4840, 48.8380]},
            "properties": {
                "nom": "Nogent-sur-Marne RER",
                "mode": "RER",
                "ligne": "A",
                "exploitant": "RATP"
            }
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [2.4860, 48.8370]},
            "properties": {
                "nom": "Nogent Centre",
                "mode": "bus",
                "ligne": "114",
                "exploitant": "RATP"
            }
        }
    ]
}


class TestFetchArrets:
    @pytest.mark.asyncio
    async def test_arrets_found(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json=MOCK_WFS)
        results = await fetch_arrets_around(lat=48.8375, lng=2.4833, radius_m=500)
        assert len(results) == 2
        r = results[0]
        assert isinstance(r, ArretTC)
        assert r.nom == "Nogent-sur-Marne RER"
        assert r.mode == "RER"

    @pytest.mark.asyncio
    async def test_no_arrets(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json={"type": "FeatureCollection", "features": []})
        results = await fetch_arrets_around(lat=48.0, lng=2.0, radius_m=500)
        assert results == []
```

- [ ] **Step 2: Implement IGN transports client**

```python
# apps/backend/core/sources/ign_transports.py
"""IGN Géoplateforme — WFS transport stops (metro/RER/tram/bus).

API: https://data.geopf.fr/wfs/ows
Layer: BDTOPO_V3:transport_commun (or similar)
No API key required.
"""
import math
from dataclasses import dataclass
from typing import Any

from core.http_client import fetch_json

WFS_URL = "https://data.geopf.fr/wfs/ows"


@dataclass(frozen=True)
class ArretTC:
    nom: str
    mode: str  # metro, RER, tram, bus
    ligne: str | None
    exploitant: str | None
    lat: float
    lng: float
    distance_m: float | None = None


def _haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Approximate distance in meters between two WGS84 points."""
    r = 6_371_000
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlng / 2) ** 2
    return r * 2 * math.asin(math.sqrt(a))


async def fetch_arrets_around(
    *, lat: float, lng: float, radius_m: int = 500
) -> list[ArretTC]:
    """Fetch public transport stops within radius of a point."""
    dlat = radius_m / 111_000
    dlng = radius_m / 73_000
    bbox = f"{lat - dlat},{lng - dlng},{lat + dlat},{lng + dlng}"

    try:
        data = await fetch_json(
            WFS_URL,
            params={
                "SERVICE": "WFS",
                "VERSION": "2.0.0",
                "REQUEST": "GetFeature",
                "TYPENAMES": "BDTOPO_V3:zone_d_activite_ou_d_interet",
                "SRSNAME": "EPSG:4326",
                "BBOX": bbox,
                "COUNT": "100",
                "OUTPUTFORMAT": "application/json",
                "CQL_FILTER": "nature IN ('Gare','Station de métro','Arrêt de bus','Station de tramway')",
            },
        )
    except Exception:
        return []

    results = []
    for f in data.get("features", []):
        props = f.get("properties", {})
        coords = f.get("geometry", {}).get("coordinates", [0, 0])
        stop_lat, stop_lng = coords[1], coords[0]
        dist = _haversine_m(lat, lng, stop_lat, stop_lng)
        if dist <= radius_m:
            results.append(
                ArretTC(
                    nom=props.get("nom", props.get("toponyme", "Arrêt inconnu")),
                    mode=_classify_mode(props.get("nature", "")),
                    ligne=props.get("ligne"),
                    exploitant=props.get("exploitant"),
                    lat=stop_lat,
                    lng=stop_lng,
                    distance_m=round(dist, 1),
                )
            )
    results.sort(key=lambda a: a.distance_m or 9999)
    return results


def _classify_mode(nature: str) -> str:
    nature_lower = nature.lower()
    if "métro" in nature_lower:
        return "metro"
    if "gare" in nature_lower:
        return "RER"
    if "tramway" in nature_lower:
        return "tram"
    return "bus"
```

- [ ] **Step 3: Write failing tests + implement Navitia client**

```python
# apps/backend/tests/unit/test_source_navitia.py
"""Tests for Navitia / STIF IDF Mobilités client."""
import os
import pytest
from pytest_httpx import HTTPXMock

from core.sources.navitia import fetch_line_frequency, LineFrequency

MOCK_RESPONSE = {
    "departures": [
        {"stop_date_time": {"departure_date_time": "20260417T080000"}},
        {"stop_date_time": {"departure_date_time": "20260417T081200"}},
        {"stop_date_time": {"departure_date_time": "20260417T082500"}},
        {"stop_date_time": {"departure_date_time": "20260417T083700"}},
        {"stop_date_time": {"departure_date_time": "20260417T085000"}},
    ]
}


class TestFetchLineFrequency:
    @pytest.mark.asyncio
    async def test_frequency_calculated(self, httpx_mock: HTTPXMock, monkeypatch):
        monkeypatch.setenv("NAVITIA_API_KEY", "test-key")
        httpx_mock.add_response(json=MOCK_RESPONSE)
        result = await fetch_line_frequency(stop_name="Nogent-sur-Marne", line_code="A")
        assert result is not None
        assert isinstance(result, LineFrequency)
        assert result.avg_interval_minutes > 0
        assert result.is_frequent  # < 15 min interval

    @pytest.mark.asyncio
    async def test_no_api_key(self, monkeypatch):
        monkeypatch.delenv("NAVITIA_API_KEY", raising=False)
        result = await fetch_line_frequency(stop_name="Test", line_code="A")
        assert result is None
```

```python
# apps/backend/core/sources/navitia.py
"""Navitia / STIF Île-de-France Mobilités — line frequency.

API: https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia/
Requires NAVITIA_API_KEY env var. Free for IDF.
Used to determine if a bus line is "frequent" (≥1 passage/15min peak hour).
"""
import os
from dataclasses import dataclass

from core.http_client import fetch_json

NAVITIA_URL = "https://prim.iledefrance-mobilites.fr/marketplace/v2/navitia"


@dataclass(frozen=True)
class LineFrequency:
    stop_name: str
    line_code: str
    avg_interval_minutes: float
    is_frequent: bool  # True if avg interval ≤ 15 min


async def fetch_line_frequency(
    *, stop_name: str, line_code: str
) -> LineFrequency | None:
    """Check frequency of a transit line at a stop during peak hours."""
    api_key = os.environ.get("NAVITIA_API_KEY")
    if not api_key:
        return None

    try:
        data = await fetch_json(
            f"{NAVITIA_URL}/departures",
            params={
                "q": stop_name,
                "line": line_code,
                "count": "10",
                "apikey": api_key,
            },
        )
    except Exception:
        return None

    departures = data.get("departures", [])
    if len(departures) < 2:
        return None

    # Calculate average interval from departure times
    times = []
    for dep in departures:
        dt_str = dep.get("stop_date_time", {}).get("departure_date_time", "")
        if len(dt_str) >= 13:  # "20260417T083700"
            h, m = int(dt_str[9:11]), int(dt_str[11:13])
            times.append(h * 60 + m)

    if len(times) < 2:
        return None

    times.sort()
    intervals = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    avg_interval = sum(intervals) / len(intervals)

    return LineFrequency(
        stop_name=stop_name,
        line_code=line_code,
        avg_interval_minutes=round(avg_interval, 1),
        is_frequent=avg_interval <= 15,
    )
```

- [ ] **Step 4: Run all transport tests**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_ign_transports.py tests/unit/test_source_navitia.py -v`

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/sources/ign_transports.py apps/backend/core/sources/navitia.py apps/backend/tests/unit/test_source_ign_transports.py apps/backend/tests/unit/test_source_navitia.py
git commit -m "feat(sources): add IGN transport stops + Navitia frequency clients"
```

---

## Task 4: Clients comparables (Sitadel) + INSEE SRU + DB models + migration

**Files:**
- Create: `apps/backend/core/sources/sitadel.py`
- Create: `apps/backend/core/sources/insee_sru.py`
- Create: `apps/backend/db/models/comparable_projects.py`
- Create: `apps/backend/db/models/commune_sru.py`
- Create: `apps/backend/alembic/versions/20260417_0002_comparable_projects_commune_sru.py`
- Test: `apps/backend/tests/unit/test_source_sitadel.py`
- Test: `apps/backend/tests/unit/test_source_insee_sru.py`

- [ ] **Step 1: Write failing tests for Sitadel**

```python
# apps/backend/tests/unit/test_source_sitadel.py
"""Tests for Sitadel / open data PC client."""
import pytest
from pytest_httpx import HTTPXMock

from core.sources.sitadel import fetch_pc_commune, ComparablePC

MOCK_RESPONSE = {
    "records": [
        {
            "fields": {
                "date_arrete": "2025-06-15",
                "adresse": "12 Rue du Test",
                "nb_logements": 25,
                "sdp_m2": 1800.0,
                "destination": "logement",
                "hauteur_niveaux": 5
            },
            "geometry": {"type": "Point", "coordinates": [2.4833, 48.8375]}
        }
    ]
}


class TestFetchPcCommune:
    @pytest.mark.asyncio
    async def test_pc_found(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json=MOCK_RESPONSE)
        results = await fetch_pc_commune(code_insee="94052")
        assert len(results) == 1
        pc = results[0]
        assert isinstance(pc, ComparablePC)
        assert pc.nb_logements == 25
        assert pc.sdp_m2 == 1800.0

    @pytest.mark.asyncio
    async def test_no_pc(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json={"records": []})
        results = await fetch_pc_commune(code_insee="99999")
        assert results == []
```

- [ ] **Step 2: Implement Sitadel client**

```python
# apps/backend/core/sources/sitadel.py
"""Sitadel / open data communes — PC délivrés.

Sources:
  - Paris: opendata.paris.fr dataset "Permis de construire"
  - Sitadel: data.gouv.fr agrégated stats
No API key required.
"""
from dataclasses import dataclass

from core.http_client import fetch_json

PARIS_PC_URL = "https://opendata.paris.fr/api/records/1.0/search/"


@dataclass(frozen=True)
class ComparablePC:
    date_arrete: str | None
    adresse: str | None
    nb_logements: int | None
    sdp_m2: float | None
    destination: str | None
    hauteur_niveaux: int | None
    lat: float | None
    lng: float | None
    source: str


async def fetch_pc_commune(*, code_insee: str) -> list[ComparablePC]:
    """Fetch building permits for a commune from open data sources."""
    results: list[ComparablePC] = []

    # Paris has well-structured open data
    if code_insee.startswith("75"):
        try:
            data = await fetch_json(
                PARIS_PC_URL,
                params={
                    "dataset": "permis-de-construire",
                    "rows": "50",
                    "sort": "-date_arrete",
                },
            )
            for rec in data.get("records", []):
                fields = rec.get("fields", {})
                geom = rec.get("geometry", {})
                coords = geom.get("coordinates", [None, None])
                results.append(
                    ComparablePC(
                        date_arrete=fields.get("date_arrete"),
                        adresse=fields.get("adresse"),
                        nb_logements=fields.get("nb_logements"),
                        sdp_m2=fields.get("sdp_m2"),
                        destination=fields.get("destination"),
                        hauteur_niveaux=fields.get("hauteur_niveaux"),
                        lat=coords[1] if coords[1] else None,
                        lng=coords[0] if coords[0] else None,
                        source="opendata_paris",
                    )
                )
        except Exception:
            pass

    return results
```

- [ ] **Step 3: Write failing tests + implement INSEE SRU**

```python
# apps/backend/tests/unit/test_source_insee_sru.py
"""Tests for INSEE SRU commune status client."""
import pytest
from pytest_httpx import HTTPXMock

from core.sources.insee_sru import fetch_sru_commune, CommuneSRU

MOCK_RESPONSE = {
    "results": [
        {
            "code_insee": "94052",
            "taux_lls": 18.5,
            "taux_cible": 25.0,
            "statut": "rattrapage",
            "penalite_eur": 125000
        }
    ]
}


class TestFetchSruCommune:
    @pytest.mark.asyncio
    async def test_commune_found(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json=MOCK_RESPONSE)
        result = await fetch_sru_commune(code_insee="94052")
        assert result is not None
        assert isinstance(result, CommuneSRU)
        assert result.statut == "rattrapage"
        assert result.taux_lls == 18.5

    @pytest.mark.asyncio
    async def test_commune_not_found(self, httpx_mock: HTTPXMock):
        httpx_mock.add_response(json={"results": []})
        result = await fetch_sru_commune(code_insee="99999")
        assert result is None
```

```python
# apps/backend/core/sources/insee_sru.py
"""INSEE / Ministère du Logement — statut SRU communal.

Source: data.gouv.fr logements-sociaux dataset.
Identifies communes carencées, en rattrapage, conformes.
No API key required.
"""
from dataclasses import dataclass

from core.http_client import fetch_json

SRU_URL = "https://www.data.gouv.fr/api/1/datasets/logements-sociaux/"


@dataclass(frozen=True)
class CommuneSRU:
    code_insee: str
    taux_lls: float | None  # current % LLS
    taux_cible: float | None  # target % (25 or 30)
    statut: str  # conforme, rattrapage, carencee, non_soumise
    penalite_eur: float | None


async def fetch_sru_commune(*, code_insee: str) -> CommuneSRU | None:
    """Fetch SRU status for a commune."""
    try:
        data = await fetch_json(
            SRU_URL,
            params={"code_insee": code_insee},
        )
    except Exception:
        return None

    results = data.get("results", [])
    if not results:
        return None

    r = results[0]
    return CommuneSRU(
        code_insee=r.get("code_insee", code_insee),
        taux_lls=r.get("taux_lls"),
        taux_cible=r.get("taux_cible"),
        statut=r.get("statut", "non_soumise"),
        penalite_eur=r.get("penalite_eur"),
    )
```

- [ ] **Step 4: Create DB models**

```python
# apps/backend/db/models/comparable_projects.py
"""SQLAlchemy model for comparable building permits."""
import uuid
from geoalchemy2 import Geometry
from sqlalchemy import Column, Date, DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from db.base import Base


class ComparableProjectRow(Base):
    __tablename__ = "comparable_projects"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(Text, nullable=False)
    commune_insee = Column(String(5), nullable=False)
    date_arrete = Column(Date, nullable=True)
    address = Column(Text, nullable=True)
    geom = Column(Geometry("POINT", srid=4326), nullable=True)
    sdp_m2 = Column(Numeric, nullable=True)
    nb_logements = Column(Integer, nullable=True)
    destination = Column(Text, nullable=True)
    hauteur_niveaux = Column(Integer, nullable=True)
    url_reference = Column(Text, nullable=True)
    ingested_at = Column(DateTime(timezone=True), server_default=func.now())
```

```python
# apps/backend/db/models/commune_sru.py
"""SQLAlchemy model for commune SRU status cache."""
from sqlalchemy import Column, DateTime, Integer, Numeric, String, Text, func
from db.base import Base


class CommuneSruRow(Base):
    __tablename__ = "commune_sru"
    code_insee = Column(String(5), primary_key=True)
    annee_bilan = Column(Integer, nullable=False)
    taux_lls_actuel = Column(Numeric(5, 2), nullable=True)
    taux_lls_cible = Column(Numeric(5, 2), nullable=True)
    statut = Column(Text, nullable=True)  # conforme, rattrapage, carencee, non_soumise
    penalite_annuelle_eur = Column(Numeric, nullable=True)
    source_url = Column(Text, nullable=True)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 5: Create Alembic migration**

Write migration `20260417_0002_comparable_projects_commune_sru.py` creating both tables with:
- `comparable_projects`: GiST index on geom, composite index on (commune_insee, date_arrete DESC)
- `commune_sru`: primary key on code_insee (no extra indexes needed)

Import new models in `alembic/env.py`.

- [ ] **Step 6: Run tests to verify**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_source_sitadel.py tests/unit/test_source_insee_sru.py -v`

- [ ] **Step 7: Commit**

```bash
git add apps/backend/core/sources/sitadel.py apps/backend/core/sources/insee_sru.py apps/backend/db/models/comparable_projects.py apps/backend/db/models/commune_sru.py apps/backend/alembic/ apps/backend/tests/unit/test_source_sitadel.py apps/backend/tests/unit/test_source_insee_sru.py
git commit -m "feat(sources+db): add Sitadel/INSEE SRU clients + comparable_projects/commune_sru tables"
```

---

## Task 5: Module orientation parcelle (core/site/orientation.py)

**Files:**
- Create: `apps/backend/core/site/__init__.py`
- Create: `apps/backend/core/site/orientation.py`
- Test: `apps/backend/tests/unit/test_site_orientation.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_site_orientation.py
"""Tests for parcel orientation analysis — azimuth and cardinal direction of segments."""
import pytest
from shapely.geometry import Polygon

from core.site.orientation import compute_orientations, SegmentOrientation


class TestComputeOrientations:
    def test_square_parcel_4_segments(self):
        """A simple square should produce 4 segments with known orientations."""
        # Square aligned with axes in Lambert-93
        square = Polygon([
            (648000, 6862000),  # SW
            (648100, 6862000),  # SE
            (648100, 6862100),  # NE
            (648000, 6862100),  # NW
            (648000, 6862000),  # close
        ])
        segments = compute_orientations(square)
        assert len(segments) == 4
        for s in segments:
            assert isinstance(s, SegmentOrientation)
            assert s.longueur_m > 0
            assert s.qualification in ("N", "NE", "E", "SE", "S", "SO", "O", "NO")

    def test_south_facing_segment(self):
        """A segment going east (bottom of square) faces south."""
        square = Polygon([
            (0, 0), (100, 0), (100, 100), (0, 100), (0, 0)
        ])
        segments = compute_orientations(square)
        # Bottom segment (0,0)->(100,0) goes east, normal faces south
        south_segs = [s for s in segments if s.qualification == "S"]
        assert len(south_segs) >= 1

    def test_segment_lengths_correct(self):
        """100m sides should produce ~100m segment lengths."""
        square = Polygon([
            (0, 0), (100, 0), (100, 100), (0, 100), (0, 0)
        ])
        segments = compute_orientations(square)
        for s in segments:
            assert abs(s.longueur_m - 100.0) < 0.1
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement orientation module**

```python
# apps/backend/core/site/__init__.py
"""Site analysis modules for ArchiClaude."""

# apps/backend/core/site/orientation.py
"""Parcel segment orientation — azimuth and cardinal direction.

For each segment of the parcel boundary, computes the outward-facing
azimuth (normal direction) and classifies as N/NE/E/SE/S/SO/O/NO.
Input geometry should be in a projected CRS (Lambert-93) for accurate distances.
"""
import math
from dataclasses import dataclass

from shapely.geometry import Polygon


@dataclass(frozen=True)
class SegmentOrientation:
    azimut: float  # degrees, 0=north, clockwise
    longueur_m: float
    qualification: str  # N, NE, E, SE, S, SO, O, NO
    start_x: float
    start_y: float
    end_x: float
    end_y: float


def _azimuth_degrees(dx: float, dy: float) -> float:
    """Compute azimuth in degrees (0=north, clockwise) from a direction vector."""
    angle = math.degrees(math.atan2(dx, dy))  # atan2(east, north) = bearing
    return angle % 360


def _classify_azimuth(azimut: float) -> str:
    """Classify azimuth into 8 cardinal directions."""
    # Normalize to 0-360
    a = azimut % 360
    if a < 22.5 or a >= 337.5:
        return "N"
    if a < 67.5:
        return "NE"
    if a < 112.5:
        return "E"
    if a < 157.5:
        return "SE"
    if a < 202.5:
        return "S"
    if a < 247.5:
        return "SO"
    if a < 292.5:
        return "O"
    return "NO"


def compute_orientations(polygon: Polygon) -> list[SegmentOrientation]:
    """Compute orientation of each boundary segment of a polygon.

    The outward-facing normal azimuth is computed for each segment.
    For a counter-clockwise exterior ring, the outward normal is to the right
    of the segment direction. For clockwise, it's to the left.

    Args:
        polygon: Shapely Polygon in projected CRS (meters). Ideally Lambert-93.

    Returns:
        List of SegmentOrientation, one per boundary segment.
    """
    coords = list(polygon.exterior.coords)
    # Ensure counter-clockwise (shapely convention for exterior)
    if not polygon.exterior.is_ccw:
        coords = coords[::-1]

    segments = []
    for i in range(len(coords) - 1):
        x1, y1 = coords[i]
        x2, y2 = coords[i + 1]
        dx = x2 - x1
        dy = y2 - y1
        length = math.sqrt(dx * dx + dy * dy)
        if length < 0.01:
            continue

        # Outward normal for CCW ring: rotate segment direction 90° clockwise
        # Segment direction = (dx, dy), right normal = (dy, -dx)
        normal_dx = dy
        normal_dy = -dx
        azimut = _azimuth_degrees(normal_dx, normal_dy)

        segments.append(
            SegmentOrientation(
                azimut=round(azimut, 1),
                longueur_m=round(length, 2),
                qualification=_classify_azimuth(azimut),
                start_x=x1,
                start_y=y1,
                end_x=x2,
                end_y=y2,
            )
        )

    return segments
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_site_orientation.py -v`

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/site/ apps/backend/tests/unit/test_site_orientation.py
git commit -m "feat(site): add parcel segment orientation analysis"
```

---

## Task 6: Module bruit agrégé (core/site/bruit.py)

**Files:**
- Create: `apps/backend/core/site/bruit.py`
- Test: `apps/backend/tests/unit/test_site_bruit.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_site_bruit.py
"""Tests for aggregated noise analysis."""
import pytest

from core.sources.cerema_bruit import ClassementSonore
from core.sources.bruitparif import BruitparifResult
from core.site.bruit import aggregate_bruit, BruitSiteResult


class TestAggregateBruit:
    def test_cerema_only(self):
        voies = [
            ClassementSonore(categorie=3, type_infra="route", nom_voie="Av. Vincennes", lden=68.5),
            ClassementSonore(categorie=4, type_infra="route", nom_voie="Rue du Château", lden=62.0),
        ]
        result = aggregate_bruit(cerema=voies, bruitparif=None)
        assert isinstance(result, BruitSiteResult)
        assert result.classement_sonore == 3  # worst (lowest number = noisiest)
        assert result.source == "cerema"
        assert result.isolation_acoustique_obligatoire is True  # cat 1-3 → obligatoire

    def test_bruitparif_overrides(self):
        voies = [ClassementSonore(categorie=4, type_infra="route", nom_voie="Rue X", lden=62.0)]
        bp = BruitparifResult(lden=72.0, lnight=64.0, source_type="routier", code_insee="94052")
        result = aggregate_bruit(cerema=voies, bruitparif=bp)
        # Bruitparif lden 72 → categorie ~2, worse than cerema 4
        assert result.classement_sonore <= 3
        assert result.source == "bruitparif"

    def test_no_data(self):
        result = aggregate_bruit(cerema=[], bruitparif=None)
        assert result.classement_sonore is None
        assert result.isolation_acoustique_obligatoire is False

    def test_category_5_no_obligation(self):
        voies = [ClassementSonore(categorie=5, type_infra="route", nom_voie="Impasse calme", lden=50.0)]
        result = aggregate_bruit(cerema=voies, bruitparif=None)
        assert result.classement_sonore == 5
        assert result.isolation_acoustique_obligatoire is False
```

- [ ] **Step 2: Run tests to verify they fail**

- [ ] **Step 3: Implement bruit aggregation**

```python
# apps/backend/core/site/bruit.py
"""Aggregated noise analysis from Cerema + Bruitparif sources.

Determines the dominant noise classification and whether acoustic
insulation is mandatory per arrêté 30/05/1996.
"""
from dataclasses import dataclass

from core.sources.bruitparif import BruitparifResult
from core.sources.cerema_bruit import ClassementSonore


@dataclass(frozen=True)
class BruitSiteResult:
    classement_sonore: int | None  # 1-5, 1=noisiest
    source: str | None  # cerema, bruitparif
    lden_dominant: float | None
    isolation_acoustique_obligatoire: bool  # True if cat 1-3


def _lden_to_categorie(lden: float) -> int:
    """Convert Lden dB(A) to noise category 1-5."""
    if lden >= 81:
        return 1
    if lden >= 76:
        return 2
    if lden >= 70:
        return 3
    if lden >= 65:
        return 4
    return 5


def aggregate_bruit(
    *, cerema: list[ClassementSonore], bruitparif: BruitparifResult | None
) -> BruitSiteResult:
    """Aggregate noise data from both sources.

    Returns the worst (lowest number) classification between Cerema and Bruitparif.
    Bruitparif is preferred when available (finer IDF data).
    """
    cerema_worst: int | None = None
    cerema_lden: float | None = None
    if cerema:
        cerema_worst = min(v.categorie for v in cerema)
        ldens = [v.lden for v in cerema if v.lden is not None]
        cerema_lden = max(ldens) if ldens else None

    bp_cat: int | None = None
    bp_lden: float | None = None
    if bruitparif:
        bp_lden = bruitparif.lden
        bp_cat = _lden_to_categorie(bruitparif.lden)

    # Pick worst (lowest) category
    if cerema_worst is not None and bp_cat is not None:
        if bp_cat <= cerema_worst:
            cat, source, lden = bp_cat, "bruitparif", bp_lden
        else:
            cat, source, lden = cerema_worst, "cerema", cerema_lden
    elif bp_cat is not None:
        cat, source, lden = bp_cat, "bruitparif", bp_lden
    elif cerema_worst is not None:
        cat, source, lden = cerema_worst, "cerema", cerema_lden
    else:
        return BruitSiteResult(
            classement_sonore=None, source=None, lden_dominant=None,
            isolation_acoustique_obligatoire=False,
        )

    return BruitSiteResult(
        classement_sonore=cat,
        source=source,
        lden_dominant=lden,
        isolation_acoustique_obligatoire=cat <= 3,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/site/bruit.py apps/backend/tests/unit/test_site_bruit.py
git commit -m "feat(site): add aggregated noise analysis from Cerema + Bruitparif"
```

---

## Task 7: Module transports — qualification desserte (core/site/transports.py)

**Files:**
- Create: `apps/backend/core/site/transports.py`
- Test: `apps/backend/tests/unit/test_site_transports.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_site_transports.py
"""Tests for transport accessibility qualification."""
import pytest

from core.sources.ign_transports import ArretTC
from core.site.transports import qualify_desserte, DesserteResult


class TestQualifyDesserte:
    def test_metro_within_400m(self):
        arrets = [
            ArretTC(nom="Station X", mode="metro", ligne="1", exploitant="RATP", lat=48.838, lng=2.484, distance_m=350),
        ]
        result = qualify_desserte(arrets)
        assert isinstance(result, DesserteResult)
        assert result.bien_desservie is True
        assert result.stationnement_exoneration_possible is True

    def test_rer_within_400m(self):
        arrets = [
            ArretTC(nom="Gare RER", mode="RER", ligne="A", exploitant="SNCF", lat=48.838, lng=2.484, distance_m=300),
        ]
        result = qualify_desserte(arrets)
        assert result.bien_desservie is True

    def test_two_frequent_buses(self):
        arrets = [
            ArretTC(nom="Bus A", mode="bus", ligne="114", exploitant="RATP", lat=48.838, lng=2.484, distance_m=200),
            ArretTC(nom="Bus B", mode="bus", ligne="210", exploitant="RATP", lat=48.837, lng=2.485, distance_m=250),
        ]
        # With 2+ bus lines within 300m, qualifies as well-served
        result = qualify_desserte(arrets, frequent_bus_lines={"114", "210"})
        assert result.bien_desservie is True

    def test_only_distant_bus(self):
        arrets = [
            ArretTC(nom="Bus loin", mode="bus", ligne="999", exploitant="RATP", lat=48.84, lng=2.49, distance_m=450),
        ]
        result = qualify_desserte(arrets)
        assert result.bien_desservie is False
        assert result.stationnement_exoneration_possible is False

    def test_empty(self):
        result = qualify_desserte([])
        assert result.bien_desservie is False
```

- [ ] **Step 2: Implement transports module**

```python
# apps/backend/core/site/transports.py
"""Transport accessibility qualification.

Determines if a site is "bien desservie" per PLU criteria:
- Metro/RER within 400m, OR
- Tram within 300m, OR
- ≥2 frequent bus lines within 300m

Impact: can exempt from car parking requirements in some PLU.
"""
from dataclasses import dataclass

from core.sources.ign_transports import ArretTC


@dataclass(frozen=True)
class DesserteResult:
    bien_desservie: bool
    stationnement_exoneration_possible: bool
    motif: str | None  # explanation for the qualification


def qualify_desserte(
    arrets: list[ArretTC],
    *,
    frequent_bus_lines: set[str] | None = None,
) -> DesserteResult:
    """Qualify transport accessibility from a list of nearby stops.

    Args:
        arrets: Stops with distance_m already computed.
        frequent_bus_lines: Set of line codes known to be frequent (≤15min peak).
    """
    if not arrets:
        return DesserteResult(
            bien_desservie=False,
            stationnement_exoneration_possible=False,
            motif="Aucun arrêt TC à proximité",
        )

    if frequent_bus_lines is None:
        frequent_bus_lines = set()

    # Check metro/RER within 400m
    metro_rer = [a for a in arrets if a.mode in ("metro", "RER") and (a.distance_m or 9999) <= 400]
    if metro_rer:
        return DesserteResult(
            bien_desservie=True,
            stationnement_exoneration_possible=True,
            motif=f"{metro_rer[0].mode} {metro_rer[0].nom} à {metro_rer[0].distance_m}m",
        )

    # Check tram within 300m
    tram = [a for a in arrets if a.mode == "tram" and (a.distance_m or 9999) <= 300]
    if tram:
        return DesserteResult(
            bien_desservie=True,
            stationnement_exoneration_possible=True,
            motif=f"Tram {tram[0].nom} à {tram[0].distance_m}m",
        )

    # Check ≥2 frequent bus lines within 300m
    bus_close = [
        a for a in arrets
        if a.mode == "bus" and (a.distance_m or 9999) <= 300 and a.ligne in frequent_bus_lines
    ]
    unique_lines = {a.ligne for a in bus_close if a.ligne}
    if len(unique_lines) >= 2:
        return DesserteResult(
            bien_desservie=True,
            stationnement_exoneration_possible=True,
            motif=f"{len(unique_lines)} lignes bus fréquent <300m",
        )

    return DesserteResult(
        bien_desservie=False,
        stationnement_exoneration_possible=False,
        motif="Desserte insuffisante pour exonération stationnement",
    )
```

- [ ] **Step 3: Run tests to verify they pass**

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/site/transports.py apps/backend/tests/unit/test_site_transports.py
git commit -m "feat(site): add transport accessibility qualification module"
```

---

## Task 8: Module voisinage enrichi (core/site/voisinage.py)

**Files:**
- Create: `apps/backend/core/site/voisinage.py`
- Test: `apps/backend/tests/unit/test_site_voisinage.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_site_voisinage.py
"""Tests for enriched neighborhood analysis."""
import pytest
from unittest.mock import AsyncMock, patch

from core.sources.ign_bdtopo import BatimentResult
from core.sources.dpe import DpeResult
from core.site.voisinage import enrich_voisinage, VoisinEnrichi


class TestEnrichVoisinage:
    @pytest.mark.asyncio
    async def test_basic_enrichment(self):
        batiments = [
            BatimentResult(hauteur=15.0, nb_etages=5, usage="Résidentiel", altitude_sol=45.0, altitude_toit=60.0, geometry={"type": "Polygon", "coordinates": []}),
            BatimentResult(hauteur=9.0, nb_etages=3, usage="Commercial", altitude_sol=45.0, altitude_toit=54.0, geometry={"type": "Polygon", "coordinates": []}),
        ]
        dpe_results = [
            DpeResult(nb_niveaux=5, hauteur_sous_plafond=2.6, classe_energie="D", type_batiment="immeuble", adresse="12 Rue Test"),
        ]

        with patch("core.site.voisinage._detect_ouvertures", new_callable=AsyncMock, return_value=None):
            voisins = await enrich_voisinage(batiments=batiments, dpe_nearby=dpe_results)

        assert len(voisins) == 2
        v = voisins[0]
        assert isinstance(v, VoisinEnrichi)
        assert v.hauteur == 15.0
        assert v.usage == "Résidentiel"

    @pytest.mark.asyncio
    async def test_empty_batiments(self):
        with patch("core.site.voisinage._detect_ouvertures", new_callable=AsyncMock, return_value=None):
            voisins = await enrich_voisinage(batiments=[], dpe_nearby=[])
        assert voisins == []

    @pytest.mark.asyncio
    async def test_dpe_enrichment(self):
        batiments = [
            BatimentResult(hauteur=12.0, nb_etages=4, usage="Résidentiel", altitude_sol=45.0, altitude_toit=57.0, geometry=None),
        ]
        dpe_results = [
            DpeResult(nb_niveaux=4, hauteur_sous_plafond=2.5, classe_energie="E", type_batiment="immeuble", adresse=None),
        ]
        with patch("core.site.voisinage._detect_ouvertures", new_callable=AsyncMock, return_value=None):
            voisins = await enrich_voisinage(batiments=batiments, dpe_nearby=dpe_results)
        assert voisins[0].dpe_classe == "E"
```

- [ ] **Step 2: Implement voisinage module**

```python
# apps/backend/core/site/voisinage.py
"""Enriched neighborhood analysis — buildings with usage, DPE, and openings.

Combines BDTopo building data with DPE energy classification and
(optionally) Claude vision analysis for detecting visible openings.
"""
from dataclasses import dataclass
from typing import Any

from core.sources.dpe import DpeResult
from core.sources.ign_bdtopo import BatimentResult


@dataclass(frozen=True)
class VoisinEnrichi:
    hauteur: float | None
    nb_etages: int | None
    usage: str | None  # Résidentiel, Commercial, etc.
    dpe_classe: str | None  # A-G energy class
    ouvertures_visibles: bool | None  # from Claude vision (None if not analyzed)
    geometry: dict[str, Any] | None


async def _detect_ouvertures(geometry: dict | None) -> bool | None:
    """Detect visible openings via Claude vision on orthophoto.

    Returns None when vision analysis is not available or not applicable.
    This is a placeholder — actual implementation requires orthophoto fetching
    and Anthropic Vision API call. Deferred to Phase 6 integration.
    """
    # Phase 2: stub — vision detection deferred to Phase 6
    return None


async def enrich_voisinage(
    *,
    batiments: list[BatimentResult],
    dpe_nearby: list[DpeResult],
) -> list[VoisinEnrichi]:
    """Enrich BDTopo buildings with DPE data and opening detection.

    Args:
        batiments: Buildings from IGN BDTopo.
        dpe_nearby: DPE results in the area (best-effort matching by floor count).
    """
    if not batiments:
        return []

    # Build DPE lookup by nb_niveaux for approximate matching
    dpe_by_niveaux: dict[int, DpeResult] = {}
    for d in dpe_nearby:
        if d.nb_niveaux and d.nb_niveaux not in dpe_by_niveaux:
            dpe_by_niveaux[d.nb_niveaux] = d

    voisins = []
    for bat in batiments:
        # Match DPE by floor count (approximate)
        dpe_match = dpe_by_niveaux.get(bat.nb_etages) if bat.nb_etages else None

        ouvertures = await _detect_ouvertures(bat.geometry)

        voisins.append(
            VoisinEnrichi(
                hauteur=bat.hauteur,
                nb_etages=bat.nb_etages,
                usage=bat.usage,
                dpe_classe=dpe_match.classe_energie if dpe_match else None,
                ouvertures_visibles=ouvertures,
                geometry=bat.geometry,
            )
        )

    return voisins
```

- [ ] **Step 3: Run tests to verify they pass**

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/site/voisinage.py apps/backend/tests/unit/test_site_voisinage.py
git commit -m "feat(site): add enriched neighborhood analysis with DPE matching"
```

---

## Task 9: Schemas Pydantic + API routes /site/* + integration tests

**Files:**
- Create: `apps/backend/schemas/site.py`
- Create: `apps/backend/api/routes/site.py`
- Modify: `apps/backend/api/main.py`
- Test: `apps/backend/tests/integration/test_site_endpoints.py`

- [ ] **Step 1: Create Pydantic schemas**

```python
# apps/backend/schemas/site.py
"""Pydantic schemas for /site/* API endpoints."""
from typing import Any
from pydantic import BaseModel


class MapillaryPhotoOut(BaseModel):
    image_id: str
    thumb_url: str
    captured_at: int
    compass_angle: float
    lat: float
    lng: float


class StreetViewImageOut(BaseModel):
    pano_id: str
    image_url: str
    lat: float
    lng: float
    date: str | None


class SitePhotosResponse(BaseModel):
    mapillary: list[MapillaryPhotoOut]
    streetview: list[StreetViewImageOut]


class SegmentOrientationOut(BaseModel):
    azimut: float
    longueur_m: float
    qualification: str


class SiteOrientationResponse(BaseModel):
    segments: list[SegmentOrientationOut]


class ArretTCOut(BaseModel):
    nom: str
    mode: str
    ligne: str | None
    distance_m: float | None


class SiteTransportsResponse(BaseModel):
    arrets: list[ArretTCOut]
    bien_desservie: bool
    stationnement_exoneration_possible: bool
    motif: str | None


class SiteBruitResponse(BaseModel):
    classement_sonore: int | None
    source: str | None
    lden_dominant: float | None
    isolation_acoustique_obligatoire: bool


class VoisinOut(BaseModel):
    hauteur: float | None
    nb_etages: int | None
    usage: str | None
    dpe_classe: str | None
    ouvertures_visibles: bool | None
    geometry: dict[str, Any] | None


class SiteVoisinageResponse(BaseModel):
    batiments: list[VoisinOut]


class ComparableProjectOut(BaseModel):
    date_arrete: str | None
    adresse: str | None
    nb_logements: int | None
    sdp_m2: float | None
    destination: str | None
    hauteur_niveaux: int | None
    source: str


class SiteComparablesResponse(BaseModel):
    projects: list[ComparableProjectOut]


class DvfTransactionOut(BaseModel):
    date_mutation: str
    nature_mutation: str
    valeur_fonciere: float | None
    type_local: str | None
    surface_m2: float | None
    nb_pieces: int | None
    adresse: str | None


class DvfAggregates(BaseModel):
    prix_moyen_m2_appartement: float | None
    prix_moyen_m2_maison: float | None
    nb_transactions: int


class SiteDvfResponse(BaseModel):
    transactions: list[DvfTransactionOut]
    aggregates: DvfAggregates
```

- [ ] **Step 2: Create /site/* API routes**

```python
# apps/backend/api/routes/site.py
"""Site data endpoints — photos, orientation, transports, bruit, voisinage, comparables, DVF."""
import asyncio

from fastapi import APIRouter, Query

from core.sources import (
    cerema_bruit,
    bruitparif,
    dvf,
    google_streetview,
    ign_bdtopo,
    ign_transports,
    mapillary,
    dpe,
    sitadel,
)
from core.site import bruit as bruit_module, transports as transports_module, voisinage as voisinage_module
from schemas.site import (
    ArretTCOut,
    ComparableProjectOut,
    DvfAggregates,
    DvfTransactionOut,
    MapillaryPhotoOut,
    SegmentOrientationOut,
    SiteBruitResponse,
    SiteComparablesResponse,
    SiteDvfResponse,
    SiteOrientationResponse,
    SitePhotosResponse,
    SiteTransportsResponse,
    SiteVoisinageResponse,
    StreetViewImageOut,
    VoisinOut,
)

router = APIRouter(prefix="/site", tags=["site"])


@router.get("/photos", response_model=SitePhotosResponse)
async def site_photos(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_m: int = Query(50, ge=10, le=200),
):
    """Fetch street-level photos from Mapillary (+ Street View fallback)."""
    mp_photos, sv_image = await asyncio.gather(
        mapillary.fetch_photos_around(lat=lat, lng=lng, radius_m=radius_m),
        google_streetview.fetch_streetview_image(lat=lat, lng=lng),
    )
    return SitePhotosResponse(
        mapillary=[MapillaryPhotoOut(image_id=p.image_id, thumb_url=p.thumb_url, captured_at=p.captured_at, compass_angle=p.compass_angle, lat=p.lat, lng=p.lng) for p in mp_photos],
        streetview=[StreetViewImageOut(pano_id=sv_image.pano_id, image_url=sv_image.image_url, lat=sv_image.lat, lng=sv_image.lng, date=sv_image.date)] if sv_image else [],
    )


@router.get("/bruit", response_model=SiteBruitResponse)
async def site_bruit(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
):
    """Fetch noise classification from Cerema + Bruitparif."""
    cerema_data, bp_data = await asyncio.gather(
        cerema_bruit.fetch_classement_sonore(lat=lat, lng=lng),
        bruitparif.fetch_bruit_idf(lat=lat, lng=lng),
    )
    result = bruit_module.aggregate_bruit(cerema=cerema_data, bruitparif=bp_data)
    return SiteBruitResponse(
        classement_sonore=result.classement_sonore,
        source=result.source,
        lden_dominant=result.lden_dominant,
        isolation_acoustique_obligatoire=result.isolation_acoustique_obligatoire,
    )


@router.get("/transports", response_model=SiteTransportsResponse)
async def site_transports(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_m: int = Query(500, ge=100, le=1000),
):
    """Fetch transport stops and qualify accessibility."""
    arrets = await ign_transports.fetch_arrets_around(lat=lat, lng=lng, radius_m=radius_m)
    desserte = transports_module.qualify_desserte(arrets)
    return SiteTransportsResponse(
        arrets=[ArretTCOut(nom=a.nom, mode=a.mode, ligne=a.ligne, distance_m=a.distance_m) for a in arrets],
        bien_desservie=desserte.bien_desservie,
        stationnement_exoneration_possible=desserte.stationnement_exoneration_possible,
        motif=desserte.motif,
    )


@router.get("/voisinage", response_model=SiteVoisinageResponse)
async def site_voisinage(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_m: int = Query(100, ge=50, le=300),
):
    """Fetch enriched neighborhood buildings."""
    batiments, dpe_data = await asyncio.gather(
        ign_bdtopo.fetch_batiments_around(lat=lat, lng=lng, radius_m=radius_m),
        dpe.fetch_dpe_around(lat=lat, lng=lng, radius_m=radius_m),
    )
    voisins = await voisinage_module.enrich_voisinage(batiments=batiments, dpe_nearby=dpe_data)
    return SiteVoisinageResponse(
        batiments=[VoisinOut(hauteur=v.hauteur, nb_etages=v.nb_etages, usage=v.usage, dpe_classe=v.dpe_classe, ouvertures_visibles=v.ouvertures_visibles, geometry=v.geometry) for v in voisins],
    )


@router.get("/comparables", response_model=SiteComparablesResponse)
async def site_comparables(
    code_insee: str = Query(..., pattern=r"^\d{5}$"),
    radius_m: int = Query(500, ge=100, le=1000),
    months: int = Query(36, ge=6, le=60),
):
    """Fetch comparable building permits in the area."""
    pcs = await sitadel.fetch_pc_commune(code_insee=code_insee)
    return SiteComparablesResponse(
        projects=[
            ComparableProjectOut(
                date_arrete=pc.date_arrete, adresse=pc.adresse,
                nb_logements=pc.nb_logements, sdp_m2=pc.sdp_m2,
                destination=pc.destination, hauteur_niveaux=pc.hauteur_niveaux,
                source=pc.source,
            )
            for pc in pcs
        ],
    )


@router.get("/dvf", response_model=SiteDvfResponse)
async def site_dvf(
    code_insee: str = Query(..., pattern=r"^\d{5}$"),
    section: str = Query(..., pattern=r"^[0-9A-Z]{1,3}$"),
    numero: str = Query(..., pattern=r"^\d{1,5}$"),
    radius_m: int = Query(300, ge=100, le=500),
    years: int = Query(6, ge=1, le=10),
):
    """Fetch DVF transactions for a parcel and neighborhood."""
    transactions = await dvf.fetch_dvf_parcelle(
        code_insee=code_insee, section=section, numero=numero
    )
    # Compute aggregates
    apparts = [t for t in transactions if t.type_local == "Appartement" and t.valeur_fonciere and t.surface_m2]
    maisons = [t for t in transactions if t.type_local == "Maison" and t.valeur_fonciere and t.surface_m2]
    prix_appart = (sum(t.valeur_fonciere / t.surface_m2 for t in apparts) / len(apparts)) if apparts else None
    prix_maison = (sum(t.valeur_fonciere / t.surface_m2 for t in maisons) / len(maisons)) if maisons else None

    return SiteDvfResponse(
        transactions=[
            DvfTransactionOut(
                date_mutation=t.date_mutation, nature_mutation=t.nature_mutation,
                valeur_fonciere=t.valeur_fonciere, type_local=t.type_local,
                surface_m2=t.surface_m2, nb_pieces=t.nb_pieces, adresse=t.adresse,
            )
            for t in transactions
        ],
        aggregates=DvfAggregates(
            prix_moyen_m2_appartement=round(prix_appart, 2) if prix_appart else None,
            prix_moyen_m2_maison=round(prix_maison, 2) if prix_maison else None,
            nb_transactions=len(transactions),
        ),
    )
```

- [ ] **Step 3: Register site router in main.py**

Add to `apps/backend/api/main.py`:
```python
from api.routes.site import router as site_router
app.include_router(site_router, prefix="/api/v1")
```

- [ ] **Step 4: Write integration tests**

```python
# apps/backend/tests/integration/test_site_endpoints.py
"""Integration tests for /site/* endpoints."""
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient

from core.sources.mapillary import MapillaryPhoto
from core.sources.google_streetview import StreetViewImage
from core.sources.cerema_bruit import ClassementSonore
from core.sources.ign_transports import ArretTC
from core.sources.ign_bdtopo import BatimentResult
from core.sources.dpe import DpeResult
from core.sources.dvf import DvfTransaction
from core.sources.sitadel import ComparablePC


class TestSitePhotos:
    @pytest.mark.asyncio
    async def test_photos_returned(self, client: AsyncClient):
        with (
            patch("api.routes.site.mapillary.fetch_photos_around", new_callable=AsyncMock, return_value=[
                MapillaryPhoto(image_id="123", thumb_url="http://img.jpg", captured_at=1700000000000, compass_angle=90.0, lat=48.83, lng=2.48),
            ]),
            patch("api.routes.site.google_streetview.fetch_streetview_image", new_callable=AsyncMock, return_value=None),
        ):
            resp = await client.get("/api/v1/site/photos", params={"lat": "48.8375", "lng": "2.4833"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["mapillary"]) == 1
        assert data["streetview"] == []


class TestSiteBruit:
    @pytest.mark.asyncio
    async def test_bruit_returned(self, client: AsyncClient):
        with (
            patch("api.routes.site.cerema_bruit.fetch_classement_sonore", new_callable=AsyncMock, return_value=[
                ClassementSonore(categorie=3, type_infra="route", nom_voie="Av. Test", lden=68.0),
            ]),
            patch("api.routes.site.bruitparif.fetch_bruit_idf", new_callable=AsyncMock, return_value=None),
        ):
            resp = await client.get("/api/v1/site/bruit", params={"lat": "48.8375", "lng": "2.4833"})
        assert resp.status_code == 200
        assert resp.json()["classement_sonore"] == 3
        assert resp.json()["isolation_acoustique_obligatoire"] is True


class TestSiteTransports:
    @pytest.mark.asyncio
    async def test_transports_returned(self, client: AsyncClient):
        with patch("api.routes.site.ign_transports.fetch_arrets_around", new_callable=AsyncMock, return_value=[
            ArretTC(nom="Nogent RER", mode="RER", ligne="A", exploitant="SNCF", lat=48.838, lng=2.484, distance_m=300),
        ]):
            resp = await client.get("/api/v1/site/transports", params={"lat": "48.8375", "lng": "2.4833"})
        assert resp.status_code == 200
        assert resp.json()["bien_desservie"] is True


class TestSiteDvf:
    @pytest.mark.asyncio
    async def test_dvf_returned(self, client: AsyncClient):
        with patch("api.routes.site.dvf.fetch_dvf_parcelle", new_callable=AsyncMock, return_value=[
            DvfTransaction(date_mutation="2024-03-15", nature_mutation="Vente", valeur_fonciere=350000, type_local="Appartement", surface_m2=65, nb_pieces=3, code_commune="94052", adresse="Rue Test"),
        ]):
            resp = await client.get("/api/v1/site/dvf", params={"code_insee": "94052", "section": "AB", "numero": "0042"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["aggregates"]["nb_transactions"] == 1
        assert data["aggregates"]["prix_moyen_m2_appartement"] is not None


class TestSiteComparables:
    @pytest.mark.asyncio
    async def test_comparables_returned(self, client: AsyncClient):
        with patch("api.routes.site.sitadel.fetch_pc_commune", new_callable=AsyncMock, return_value=[
            ComparablePC(date_arrete="2025-06-15", adresse="12 Rue Test", nb_logements=25, sdp_m2=1800, destination="logement", hauteur_niveaux=5, lat=48.83, lng=2.48, source="opendata_paris"),
        ]):
            resp = await client.get("/api/v1/site/comparables", params={"code_insee": "94052"})
        assert resp.status_code == 200
        assert len(resp.json()["projects"]) == 1
```

- [ ] **Step 5: Run all tests**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/ -v`

- [ ] **Step 6: Commit**

```bash
git add apps/backend/schemas/site.py apps/backend/api/routes/site.py apps/backend/api/main.py apps/backend/tests/integration/test_site_endpoints.py
git commit -m "feat(api): add 7 /site/* endpoints — photos, bruit, transports, voisinage, comparables, dvf"
```

---

## Task 10: Vérification finale — lint + tests + coverage

- [ ] **Step 1: Run ruff**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && ruff check . --fix
```

- [ ] **Step 2: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short
```

- [ ] **Step 3: Fix any issues**

- [ ] **Step 4: Commit cleanup**

```bash
git add -A && git commit -m "chore: Phase 2 lint fixes and cleanup"
```
