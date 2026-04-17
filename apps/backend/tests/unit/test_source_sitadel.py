"""Unit tests for core.sources.sitadel — building permits client.

HTTP calls are intercepted at transport level by pytest-httpx.
"""

from __future__ import annotations

import re

import pytest
from pytest_httpx import HTTPXMock

from core.sources.sitadel import ComparablePC, fetch_pc_commune

_PARIS_URL_RE = re.compile(r"https://opendata\.paris\.fr/.*")

_PARIS_RESPONSE = {
    "results": [
        {
            "date_arrete": "2024-03-15",
            "adresse": "12 RUE DE RIVOLI 75001 PARIS",
            "nb_logements": 24,
            "sdp_totale": 1850.5,
            "destination": "logement",
            "nb_niveaux": 7,
            "geo_point_2d": {"lat": 48.857, "lon": 2.352},
        },
        {
            "date_arrete": "2024-01-10",
            "adresse": "45 AVENUE HOCHE 75008 PARIS",
            "nb_logements": 12,
            "sdp_totale": 920.0,
            "destination": "logement",
            "nb_niveaux": 5,
            "geo_point_2d": {"lat": 48.878, "lon": 2.303},
        },
    ]
}

_EMPTY_RESPONSE: dict = {"results": []}


async def test_pc_found(httpx_mock: HTTPXMock) -> None:
    """Returns ComparablePC list when Paris opendata responds with records."""
    httpx_mock.add_response(url=_PARIS_URL_RE, json=_PARIS_RESPONSE)

    results = await fetch_pc_commune(code_insee="75001")

    assert len(results) == 2
    r: ComparablePC = results[0]
    assert r.source == "opendata_paris"
    assert r.date_arrete == "2024-03-15"
    assert r.adresse == "12 RUE DE RIVOLI 75001 PARIS"
    assert r.nb_logements == 24
    assert r.sdp_m2 == pytest.approx(1850.5)
    assert r.destination == "logement"
    assert r.hauteur_niveaux == 7
    assert r.lat == pytest.approx(48.857)
    assert r.lng == pytest.approx(2.352)


async def test_no_pc(httpx_mock: HTTPXMock) -> None:
    """Returns empty list when the Paris API returns no records."""
    httpx_mock.add_response(url=_PARIS_URL_RE, json=_EMPTY_RESPONSE)

    results = await fetch_pc_commune(code_insee="75056")

    assert results == []


async def test_non_paris_commune_returns_empty() -> None:
    """Non-Paris communes return empty list without making any HTTP call (v1)."""
    results = await fetch_pc_commune(code_insee="69123")
    assert results == []

    results2 = await fetch_pc_commune(code_insee="92012")
    assert results2 == []


async def test_api_error_returns_empty(httpx_mock: HTTPXMock) -> None:
    """Graceful degradation: returns [] on API error."""
    httpx_mock.add_response(url=_PARIS_URL_RE, status_code=503)

    results = await fetch_pc_commune(code_insee="75001")

    assert results == []
