"""Unit tests for core.sources.georisques — GeoRisques API client.

HTTP calls are intercepted at transport level by pytest-httpx, so the
module-level singleton in core.http_client is transparently mocked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from core.sources.georisques import RisqueResult, fetch_risques

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

_FIXTURES_PATH = Path(__file__).parent.parent / "fixtures" / "georisques_responses.json"


def _load_fixture(key: str) -> dict:  # type: ignore[type-arg]
    with _FIXTURES_PATH.open() as f:
        return json.load(f)[key]  # type: ignore[no-any-return]


_GASPAR_URL_RE = re.compile(r"https://georisques\.gouv\.fr/api/v1/gaspar/risque.*")
_ARGILES_URL_RE = re.compile(r"https://georisques\.gouv\.fr/api/v1/argiles.*")

_LAT = 48.8375
_LNG = 2.4833

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_risques_found(httpx_mock: HTTPXMock) -> None:
    """GASPAR + argiles both return data — results are aggregated correctly."""
    httpx_mock.add_response(url=_GASPAR_URL_RE, json=_load_fixture("gaspar_nogent"))
    httpx_mock.add_response(url=_ARGILES_URL_RE, json=_load_fixture("argiles_nogent"))

    results = await fetch_risques(lat=_LAT, lng=_LNG)

    assert len(results) == 2

    ppri = next(r for r in results if r.type == "ppri")
    assert ppri.code == "PPRi-Val-de-Marne"
    assert "inondation" in ppri.libelle.lower()
    assert ppri.niveau_alea == "moyen"

    argiles = next(r for r in results if r.type == "argiles")
    assert argiles.code == "G2"
    assert argiles.niveau_alea == "moyen"


async def test_no_risks(httpx_mock: HTTPXMock) -> None:
    """Both endpoints return empty data lists — result is an empty list."""
    httpx_mock.add_response(url=_GASPAR_URL_RE, json=_load_fixture("gaspar_empty"))
    httpx_mock.add_response(url=_ARGILES_URL_RE, json=_load_fixture("argiles_empty"))

    results = await fetch_risques(lat=_LAT, lng=_LNG)

    assert results == []


async def test_degraded_mode_gaspar_fails(httpx_mock: HTTPXMock) -> None:
    """When GASPAR fails, argiles results are still returned (mode dégradé)."""
    httpx_mock.add_response(url=_GASPAR_URL_RE, status_code=503)
    httpx_mock.add_response(url=_ARGILES_URL_RE, json=_load_fixture("argiles_nogent"))

    results = await fetch_risques(lat=_LAT, lng=_LNG)

    # Only argiles result should be present
    assert len(results) == 1
    assert results[0].type == "argiles"


async def test_degraded_mode_argiles_fails(httpx_mock: HTTPXMock) -> None:
    """When argiles fails, GASPAR results are still returned (mode dégradé)."""
    httpx_mock.add_response(url=_GASPAR_URL_RE, json=_load_fixture("gaspar_nogent"))
    httpx_mock.add_response(url=_ARGILES_URL_RE, status_code=500)

    results = await fetch_risques(lat=_LAT, lng=_LNG)

    assert len(results) == 1
    assert results[0].type == "ppri"
