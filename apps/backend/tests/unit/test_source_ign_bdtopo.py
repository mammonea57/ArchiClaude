"""Unit tests for core.sources.ign_bdtopo — IGN BDTopo WFS client.

HTTP calls are intercepted at transport level by pytest-httpx, so the
module-level singleton in core.http_client is transparently mocked.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from pytest_httpx import HTTPXMock

from core.sources.ign_bdtopo import BatimentResult, fetch_batiments_around

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

_FIXTURES_PATH = Path(__file__).parent.parent / "fixtures" / "ign_bdtopo_responses.json"


def _load_fixture(key: str) -> dict:  # type: ignore[type-arg]
    with _FIXTURES_PATH.open() as f:
        return json.load(f)[key]  # type: ignore[no-any-return]


_WFS_URL_RE = re.compile(r"https://data\.geopf\.fr/wfs/ows.*")

_LAT = 48.8375
_LNG = 2.4833

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_buildings_found(httpx_mock: HTTPXMock) -> None:
    """WFS response with one building is parsed into a correct BatimentResult."""
    httpx_mock.add_response(url=_WFS_URL_RE, json=_load_fixture("batiments_nogent"))

    results = await fetch_batiments_around(lat=_LAT, lng=_LNG, radius_m=100)

    assert len(results) == 1
    b: BatimentResult = results[0]
    assert b.hauteur == pytest.approx(12.5)
    assert b.nb_etages == 3
    assert b.usage == "Résidentiel"
    assert b.altitude_sol == pytest.approx(48.2)
    assert b.altitude_toit == pytest.approx(60.7)
    assert b.geometry is not None
    assert b.geometry["type"] == "Polygon"

    # Verify WFS params were sent correctly
    requests = httpx_mock.get_requests()
    assert len(requests) == 1
    req_params = requests[0].url.params
    assert req_params["SERVICE"] == "WFS"
    assert req_params["REQUEST"] == "GetFeature"
    assert req_params["TYPENAMES"] == "BDTOPO_V3:batiment"
    assert req_params["SRSNAME"] == "EPSG:4326"
    assert req_params["OUTPUTFORMAT"] == "application/json"
    # BBOX should be present and non-empty
    assert "BBOX" in req_params
    bbox_parts = req_params["BBOX"].split(",")
    assert len(bbox_parts) == 4


async def test_empty_area(httpx_mock: HTTPXMock) -> None:
    """WFS response with no features returns an empty list."""
    httpx_mock.add_response(url=_WFS_URL_RE, json=_load_fixture("batiments_empty"))

    results = await fetch_batiments_around(lat=_LAT, lng=_LNG)

    assert results == []
