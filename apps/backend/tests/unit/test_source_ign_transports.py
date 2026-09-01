"""Unit tests for core.sources.ign_transports — IGN WFS transport stops client.

HTTP calls are intercepted at transport level by pytest-httpx.
"""

from __future__ import annotations

import re

import pytest
from pytest_httpx import HTTPXMock

from core.sources.ign_transports import fetch_arrets_around

_WFS_URL_RE = re.compile(r"https://data\.geopf\.fr/wfs/ows.*")
_WFS_LEGACY_URL_RE = re.compile(
    r"https://data\.geopf\.fr/wfs/ows.*zone_d_activites_ou_d_interet.*"
)
_WFS_GARES_URL_RE = re.compile(
    r"https://data\.geopf\.fr/wfs/ows.*POI\.GARES.*"
)

_LAT = 48.8375
_LNG = 2.4833

_ARRETS_RESPONSE = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {
                "nom": "Nogent - Le Perreux",
                "nature": "Station de RER",
                "ligne": "A",
                "exploitant": "RATP",
            },
            "geometry": {"type": "Point", "coordinates": [2.4840, 48.8380]},
        },
        {
            "type": "Feature",
            "properties": {
                "nom": "Mairie de Nogent",
                "nature": "Arrêt de bus",
                "ligne": "210",
                "exploitant": "RATP",
            },
            "geometry": {"type": "Point", "coordinates": [2.4850, 48.8370]},
        },
    ],
}

_EMPTY_RESPONSE = {
    "type": "FeatureCollection",
    "features": [],
}


_OVERPASS_URL_RE = re.compile(r"https://(overpass\.kumi\.systems|.*overpass-api\.de)/api/interpreter.*")


async def test_arrets_found(httpx_mock: HTTPXMock) -> None:
    """Returns ArretTC list sorted by distance when WFS returns stops."""
    # The fetch implementation queries IGN WFS twice (legacy BDTOPO + POI
    # Gares) and Overpass concurrently. We stub the gares + Overpass calls
    # with empty payloads so this test focuses on the legacy BDTOPO path
    # exercised by the pre-2026 fixture.
    httpx_mock.add_response(
        url=_WFS_LEGACY_URL_RE, json=_ARRETS_RESPONSE, is_reusable=True,
    )
    httpx_mock.add_response(
        url=_WFS_GARES_URL_RE,
        json={"type": "FeatureCollection", "features": []},
        is_reusable=True,
    )
    httpx_mock.add_response(
        url=_OVERPASS_URL_RE,
        json={"version": 0.6, "generator": "test", "elements": []},
        is_reusable=True,
    )

    arrets = await fetch_arrets_around(lat=_LAT, lng=_LNG, radius_m=500, use_cache=False)

    assert len(arrets) == 2
    # Sorted by distance ascending
    assert arrets[0].distance_m is not None
    assert arrets[1].distance_m is not None
    assert arrets[0].distance_m <= arrets[1].distance_m

    rer = next(a for a in arrets if "Nogent" in a.nom and "Perreux" in a.nom)
    assert rer.mode in ("RER", "rer", "metro", "gare")
    assert rer.ligne == "A"
    assert rer.exploitant == "RATP"
    assert rer.lat == pytest.approx(48.8380)
    assert rer.lng == pytest.approx(2.4840)

    bus = next(a for a in arrets if "Mairie" in a.nom)
    assert bus.mode == "bus"
    assert bus.ligne == "210"


async def test_no_arrets(httpx_mock: HTTPXMock) -> None:
    """Returns empty list when WFS returns no stops."""
    httpx_mock.add_response(url=_WFS_URL_RE, json=_EMPTY_RESPONSE, is_reusable=True)
    httpx_mock.add_response(
        url=_OVERPASS_URL_RE,
        json={"version": 0.6, "generator": "test", "elements": []},
        is_reusable=True,
    )

    arrets = await fetch_arrets_around(lat=_LAT, lng=_LNG, use_cache=False)

    assert arrets == []


async def test_error_returns_empty(httpx_mock: HTTPXMock) -> None:
    """Returns empty list (graceful degradation) when WFS returns an error."""
    httpx_mock.add_response(url=_WFS_URL_RE, status_code=503, is_reusable=True)
    httpx_mock.add_response(url=_OVERPASS_URL_RE, status_code=503, is_reusable=True)

    arrets = await fetch_arrets_around(lat=_LAT, lng=_LNG, use_cache=False)

    assert arrets == []
