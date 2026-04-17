"""Unit tests for core.sources.ign_bd_alti — IGN BD ALTI altitude client.

HTTP calls are intercepted at transport level by pytest-httpx, so the
module-level singleton in core.http_client is transparently mocked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from core.sources.ign_bd_alti import AltitudeResult, fetch_altitude

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

_FIXTURES_PATH = Path(__file__).parent.parent / "fixtures" / "ign_bd_alti_responses.json"


def _load_fixture(key: str) -> dict:  # type: ignore[type-arg]
    with _FIXTURES_PATH.open() as f:
        return json.load(f)[key]  # type: ignore[no-any-return]


_ALTI_URL_RE = re.compile(
    r"https://data\.geopf\.fr/altimetrie/1\.0/calcul/alti/rest/elevation\.json.*"
)

_LAT = 48.8375
_LNG = 2.4833

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_altitude_found(httpx_mock: HTTPXMock) -> None:
    """Valid elevation response is parsed into a correct AltitudeResult."""
    httpx_mock.add_response(url=_ALTI_URL_RE, json=_load_fixture("altitude_nogent"))

    result = await fetch_altitude(lat=_LAT, lng=_LNG)

    assert result is not None
    assert isinstance(result, AltitudeResult)
    assert result.lat == pytest.approx(48.8375)
    assert result.lng == pytest.approx(2.4833)
    assert result.altitude_m == pytest.approx(52.3)

    # Verify query params
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    params = requests[0].url.params
    assert float(params["lat"]) == pytest.approx(_LAT)
    assert float(params["lon"]) == pytest.approx(_LNG)
    assert params["zonly"] == "false"


async def test_no_data(httpx_mock: HTTPXMock) -> None:
    """Response with z == -99999 sentinel returns None."""
    httpx_mock.add_response(url=_ALTI_URL_RE, json=_load_fixture("altitude_no_data"))

    result = await fetch_altitude(lat=48.0, lng=2.0)

    assert result is None


async def test_empty_elevations(httpx_mock: HTTPXMock) -> None:
    """Response with empty elevations list returns None."""
    httpx_mock.add_response(url=_ALTI_URL_RE, json=_load_fixture("altitude_empty"))

    result = await fetch_altitude(lat=_LAT, lng=_LNG)

    assert result is None
