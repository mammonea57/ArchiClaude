"""Unit tests for core.sources.bruitparif — Bruitparif IDF noise client.

HTTP calls are intercepted at transport level by pytest-httpx.
"""

from __future__ import annotations

import re

import pytest
from pytest_httpx import HTTPXMock

from core.sources.bruitparif import BruitparifResult, fetch_bruit_idf

_BRUITPARIF_URL_RE = re.compile(r"https://rumeur\.bruitparif\.fr/api/v1/noise.*")

_LAT = 48.8375
_LNG = 2.4833

_DATA_RESPONSE = {
    "lden": 65.2,
    "lnight": 57.8,
    "source_type": "routier",
    "code_insee": "94052",
}

_EMPTY_RESPONSE = {}


async def test_data_found(httpx_mock: HTTPXMock) -> None:
    """Returns BruitparifResult when the API returns noise data."""
    httpx_mock.add_response(url=_BRUITPARIF_URL_RE, json=_DATA_RESPONSE)

    result = await fetch_bruit_idf(lat=_LAT, lng=_LNG)

    assert result is not None
    assert isinstance(result, BruitparifResult)
    assert result.lden == pytest.approx(65.2)
    assert result.lnight == pytest.approx(57.8)
    assert result.source_type == "routier"
    assert result.code_insee == "94052"


async def test_no_data(httpx_mock: HTTPXMock) -> None:
    """Returns None when the API returns no noise data."""
    httpx_mock.add_response(url=_BRUITPARIF_URL_RE, json=_EMPTY_RESPONSE)

    result = await fetch_bruit_idf(lat=_LAT, lng=_LNG)

    assert result is None


async def test_error_returns_none(httpx_mock: HTTPXMock) -> None:
    """Returns None (graceful degradation) when the API returns an error."""
    httpx_mock.add_response(url=_BRUITPARIF_URL_RE, status_code=503)

    result = await fetch_bruit_idf(lat=_LAT, lng=_LNG)

    assert result is None
