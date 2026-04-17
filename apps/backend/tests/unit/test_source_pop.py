"""Unit tests for core.sources.pop — POP monuments historiques client.

HTTP calls are intercepted at transport level by pytest-httpx, so the
module-level singleton in core.http_client is transparently mocked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from core.sources.pop import MonumentResult, fetch_monuments_around

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

_FIXTURES_PATH = Path(__file__).parent.parent / "fixtures" / "pop_responses.json"


def _load_fixture(key: str) -> dict:  # type: ignore[type-arg]
    with _FIXTURES_PATH.open() as f:
        return json.load(f)[key]  # type: ignore[no-any-return]


_POP_URL_RE = re.compile(r"https://api\.pop\.culture\.gouv\.fr/search/.*")

_LAT = 48.8444
_LNG = 2.4352

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_monument_found(httpx_mock: HTTPXMock) -> None:
    """POP response with one monument is parsed into a correct MonumentResult."""
    httpx_mock.add_response(url=_POP_URL_RE, json=_load_fixture("monuments_vincennes"))

    results = await fetch_monuments_around(lat=_LAT, lng=_LNG, radius_m=500)

    assert len(results) == 1
    m: MonumentResult = results[0]
    assert m.reference == "PA00079781"
    assert m.nom == "Château de Vincennes"
    assert m.date_protection is not None
    assert "classé MH" in m.date_protection
    assert m.commune == "Vincennes"
    assert m.departement == "94"
    assert m.lat == pytest.approx(48.8444)
    assert m.lng == pytest.approx(2.4352)

    # Verify POST was used with correct geo_distance body
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    body = json.loads(requests[0].content)
    geo_dist = body["query"]["bool"]["filter"][0]["geo_distance"]
    assert geo_dist["distance"] == "500m"
    assert geo_dist["POP_COORDONNEES"]["lat"] == pytest.approx(_LAT)
    assert geo_dist["POP_COORDONNEES"]["lon"] == pytest.approx(_LNG)


async def test_no_monuments(httpx_mock: HTTPXMock) -> None:
    """POP response with no hits returns an empty list."""
    httpx_mock.add_response(url=_POP_URL_RE, json=_load_fixture("monuments_empty"))

    results = await fetch_monuments_around(lat=_LAT, lng=_LNG)

    assert results == []
