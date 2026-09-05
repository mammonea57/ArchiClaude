"""Unit tests for core.sources.atlas_patrimoine — Atlas Patrimoine API client.

HTTP calls are intercepted at transport level by pytest-httpx, so the
module-level singleton in core.http_client is transparently mocked.

The Atlas Patrimoine module also has a local cache in
``refs/cache/atlas_patrimoine/``. Every test redirects that cache to a
temporary directory so the suite does not touch the developer's real cache.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from pytest_httpx import HTTPXMock

from core.sources import atlas_patrimoine as ap

_RECORDS_URL_RE = re.compile(
    r"https://data\.culture\.gouv\.fr/api/explore/v2\.1/catalog/datasets/"
    r"liste-des-immeubles-proteges-au-titre-des-monuments-historiques/records.*"
)

# Nogent-sur-Marne — 80 rue des Héros (approx).
_LAT = 48.83558
_LNG = 2.4810


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_record(
    *,
    designation: str,
    protection: str,
    commune: str,
    lat: float,
    lng: float,
    code_insee: str | None = "94052",
    adresse: str | None = None,
    ref_merimee: str | None = None,
) -> dict[str, Any]:
    """Build a synthetic OpenDataSoft record matching the live schema."""
    return {
        "denomination": designation,
        "statut_juridique": protection,
        "commune": commune,
        "code_insee": code_insee,
        "departement_en_lettres": "Val-de-Marne",
        "adresse": adresse,
        "date_de_la_derniere_etape_de_protection": "1975-04-01",
        "reference_de_la_notice_merimee": ref_merimee,
        "geo_point_2d": {"lat": lat, "lon": lng},
    }


def _payload(records: list[dict[str, Any]]) -> dict[str, Any]:
    return {"total_count": len(records), "results": records}


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect the module cache directory to a temporary path for each test."""
    cache_dir = tmp_path / "atlas_patrimoine"
    monkeypatch.setattr(ap, "_CACHE_DIR", cache_dir)
    return cache_dir


# ---------------------------------------------------------------------------
# Tests — point / radius search
# ---------------------------------------------------------------------------


async def test_fetch_around_point_parses_features(httpx_mock: HTTPXMock) -> None:
    """Records returned by the API are parsed into dataclasses with distance."""
    records = [
        _make_record(
            designation="Château de Nogent",
            protection="classé",
            commune="Nogent-sur-Marne",
            adresse="rue des Héros",
            ref_merimee="PA00079876",
            lat=48.8360, lng=2.4815,
        ),
        _make_record(
            designation="Pavillon Baltard",
            protection="inscrit",
            commune="Nogent-sur-Marne",
            lat=48.8390, lng=2.4830,
        ),
    ]
    httpx_mock.add_response(url=_RECORDS_URL_RE, json=_payload(records))

    features = await ap.fetch_mh_around_point(
        lat=_LAT, lng=_LNG, radius_m=500, use_cache=False,
    )

    assert len(features) == 2
    # Sorted by ascending distance.
    assert features[0].designation == "Château de Nogent"
    assert features[0].protection == "classé"
    assert features[0].commune == "Nogent-sur-Marne"
    assert features[0].adresse == "rue des Héros"
    assert features[0].reference_merimee == "PA00079876"
    assert features[0].code_insee == "94052"
    assert features[0].lat == pytest.approx(48.8360, abs=1e-4)
    assert features[0].lng == pytest.approx(2.4815, abs=1e-4)
    assert features[0].distance_m is not None
    assert features[0].distance_m < features[1].distance_m  # type: ignore[operator]


async def test_fetch_around_point_empty(httpx_mock: HTTPXMock) -> None:
    """An empty result set returns an empty list (no crash)."""
    httpx_mock.add_response(url=_RECORDS_URL_RE, json=_payload([]))

    features = await ap.fetch_mh_around_point(
        lat=_LAT, lng=_LNG, radius_m=200, use_cache=False,
    )

    assert features == []


# ---------------------------------------------------------------------------
# Tests — bbox search
# ---------------------------------------------------------------------------


async def test_fetch_in_bbox(httpx_mock: HTTPXMock) -> None:
    """Bounding-box search returns features without distance annotation."""
    records = [
        _make_record(
            designation="Pavillon Baltard",
            protection="inscrit",
            commune="Nogent-sur-Marne",
            lat=48.8390, lng=2.4830,
        ),
    ]
    httpx_mock.add_response(url=_RECORDS_URL_RE, json=_payload(records))

    features = await ap.fetch_mh_in_bbox(
        bbox=(2.475, 48.830, 2.490, 48.842), use_cache=False,
    )

    assert len(features) == 1
    assert features[0].designation == "Pavillon Baltard"
    assert features[0].distance_m is None  # bbox mode doesn't annotate distance


async def test_fetch_in_bbox_invalid() -> None:
    """An invalid bbox returns [] without hitting the network."""
    # east < west → invalid; pytest_httpx would error if a call slipped through.
    features = await ap.fetch_mh_in_bbox(bbox=(10.0, 10.0, 5.0, 20.0), use_cache=False)
    assert features == []


# ---------------------------------------------------------------------------
# Tests — error handling
# ---------------------------------------------------------------------------


async def test_http_error_returns_empty(httpx_mock: HTTPXMock) -> None:
    """A non-retried HTTP error returns [] rather than crashing."""
    httpx_mock.add_response(url=_RECORDS_URL_RE, status_code=400, text="bad query")

    features = await ap.fetch_mh_around_point(
        lat=_LAT, lng=_LNG, radius_m=500, use_cache=False,
    )

    assert features == []


async def test_rate_limit_then_success(
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 429 is retried with backoff, and the second response is consumed."""
    # Make backoff instantaneous in tests.
    async def _no_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(ap.asyncio, "sleep", _no_sleep)

    httpx_mock.add_response(
        url=_RECORDS_URL_RE, status_code=429, headers={"Retry-After": "0"},
    )
    httpx_mock.add_response(
        url=_RECORDS_URL_RE,
        json=_payload([
            _make_record(
                designation="Église Saint-Saturnin",
                protection="classé",
                commune="Nogent-sur-Marne",
                lat=48.8355, lng=2.4820,
            ),
        ]),
    )

    features = await ap.fetch_mh_around_point(
        lat=_LAT, lng=_LNG, radius_m=500, use_cache=False,
    )

    assert len(features) == 1
    assert features[0].designation == "Église Saint-Saturnin"


# ---------------------------------------------------------------------------
# Tests — local cache (30-day TTL)
# ---------------------------------------------------------------------------


async def test_cache_hit_avoids_second_http_call(httpx_mock: HTTPXMock) -> None:
    """A second identical call is served from the cache (no HTTP)."""
    records = [
        _make_record(
            designation="Maison classée",
            protection="classé",
            commune="Nogent-sur-Marne",
            lat=48.8358, lng=2.4811,
        ),
    ]
    # Register the response only ONCE — pytest-httpx will fail the test if a
    # second request is issued.
    httpx_mock.add_response(url=_RECORDS_URL_RE, json=_payload(records))

    first = await ap.fetch_mh_around_point(lat=_LAT, lng=_LNG, radius_m=500)
    second = await ap.fetch_mh_around_point(lat=_LAT, lng=_LNG, radius_m=500)

    assert len(first) == 1
    assert len(second) == 1
    assert second[0].designation == first[0].designation


# ---------------------------------------------------------------------------
# Tests — overlay adapter (Phase 2 schema)
# ---------------------------------------------------------------------------


def test_build_overlays_from_features() -> None:
    """Features map cleanly onto the AtlasPatrimoineMH Pydantic schema."""
    feature = ap.AtlasPatrimoineFeature(
        designation="Château de Nogent",
        protection="classé",
        commune="Nogent-sur-Marne",
        code_insee="94052",
        departement="Val-de-Marne",
        adresse="rue des Héros",
        date_protection="1975-04-01",
        reference_merimee="PA00079876",
        lat=48.836, lng=2.4815,
        distance_m=120.0,
    )
    overlays = ap.build_atlas_patrimoine_mh_overlays([feature])

    assert len(overlays) == 1
    ov = overlays[0]
    assert ov.applies is True
    assert "Château de Nogent" in ov.designation
    assert "classé" in ov.designation
    assert "120 m" in ov.designation
    # Notes carry the structured metadata for the dossier report.
    assert any("PA00079876" in n for n in ov.notes)
    assert any("rue des Héros" in n for n in ov.notes)


def test_build_overlays_no_coordinates_does_not_apply() -> None:
    """When the feature has no coordinates the overlay is non-applying."""
    feature = ap.AtlasPatrimoineFeature(
        designation="Édifice sans géo",
        protection="inscrit",
        commune="Nogent-sur-Marne",
        code_insee="94052",
        departement="Val-de-Marne",
        adresse=None,
        date_protection=None,
        reference_merimee=None,
        lat=None,
        lng=None,
    )
    overlays = ap.build_atlas_patrimoine_mh_overlays([feature])
    assert len(overlays) == 1
    assert overlays[0].applies is False
