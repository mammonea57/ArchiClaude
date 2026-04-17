"""Unit tests for core.sources.ban — BAN geocoding client.

HTTP calls are intercepted at transport level by pytest-httpx, so the
module-level singleton in core.http_client is transparently mocked.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pytest_httpx import HTTPXMock

from core.sources.ban import GeocodingResult, geocode

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

_FIXTURES_PATH = Path(__file__).parent.parent / "fixtures" / "ban_responses.json"


def _load_fixture(key: str) -> dict:  # type: ignore[type-arg]
    with _FIXTURES_PATH.open() as f:
        return json.load(f)[key]  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_paris_address(httpx_mock: HTTPXMock) -> None:
    """BAN response for a Paris address is parsed into a correct GeocodingResult."""
    httpx_mock.add_response(
        url="https://api-adresse.data.gouv.fr/search/?q=12+Rue+de+la+Paix+75002+Paris&limit=5",
        json=_load_fixture("geocode_12_rue_paix_paris"),
    )

    results = await geocode("12 Rue de la Paix 75002 Paris")

    assert len(results) == 1
    r: GeocodingResult = results[0]
    assert r.label == "12 Rue de la Paix 75002 Paris"
    assert r.score == pytest.approx(0.95)
    assert r.lat == pytest.approx(48.869)
    assert r.lng == pytest.approx(2.331)
    assert r.citycode == "75102"
    assert r.city == "Paris"
    assert r.postcode == "75002"
    assert r.housenumber == "12"
    assert r.street == "Rue de la Paix"


async def test_empty_query_returns_empty(httpx_mock: HTTPXMock) -> None:
    """Empty / whitespace query must return [] without making any HTTP call."""
    results = await geocode("")
    assert results == []

    # whitespace-only must also return early
    results_ws = await geocode("   ")
    assert results_ws == []

    # No HTTP requests should have been made
    requests = httpx_mock.get_requests()
    assert len(requests) == 0


async def test_api_error_raises(httpx_mock: HTTPXMock) -> None:
    """A 500 response from BAN must propagate as httpx.HTTPStatusError."""
    httpx_mock.add_response(
        status_code=500,
        url="https://api-adresse.data.gouv.fr/search/?q=adresse+invalide&limit=5",
    )

    with pytest.raises(httpx.HTTPStatusError):
        await geocode("adresse invalide")
