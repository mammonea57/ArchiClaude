"""Unit tests for core.sources.google_streetview — Street View Static API client.

HTTP calls are intercepted at transport level by pytest-httpx.
"""

from __future__ import annotations

import re

import pytest
from pytest_httpx import HTTPXMock

from core.sources.google_streetview import StreetViewImage, fetch_streetview_image

_METADATA_URL_RE = re.compile(
    r"https://maps\.googleapis\.com/maps/api/streetview/metadata.*"
)

_LAT = 48.8375
_LNG = 2.4833

_OK_METADATA = {
    "status": "OK",
    "pano_id": "pano_abc123",
    "location": {"lat": 48.8376, "lng": 2.4834},
    "date": "2023-04",
    "copyright": "© 2023 Google",
    "links": [],
}

_ZERO_METADATA = {
    "status": "ZERO_RESULTS",
}


async def test_image_found(httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns StreetViewImage with pano_id and constructed image URL when status is OK."""
    monkeypatch.setenv("GOOGLE_STREETVIEW_API_KEY", "gsv_key_xyz")
    httpx_mock.add_response(url=_METADATA_URL_RE, json=_OK_METADATA)

    result = await fetch_streetview_image(lat=_LAT, lng=_LNG, heading=90, fov=90)

    assert result is not None
    assert isinstance(result, StreetViewImage)
    assert result.pano_id == "pano_abc123"
    assert result.lat == pytest.approx(48.8376)
    assert result.lng == pytest.approx(2.4834)
    assert result.date == "2023-04"
    assert "streetview" in result.image_url.lower() or "maps.googleapis.com" in result.image_url
    assert "pano_abc123" in result.image_url or "gsv_key_xyz" in result.image_url


async def test_no_coverage(httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns None when Street View has no coverage (ZERO_RESULTS)."""
    monkeypatch.setenv("GOOGLE_STREETVIEW_API_KEY", "gsv_key_xyz")
    httpx_mock.add_response(url=_METADATA_URL_RE, json=_ZERO_METADATA)

    result = await fetch_streetview_image(lat=_LAT, lng=_LNG)

    assert result is None


async def test_no_api_key_returns_none(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returns None without making any HTTP call when API key is absent."""
    monkeypatch.delenv("GOOGLE_STREETVIEW_API_KEY", raising=False)

    result = await fetch_streetview_image(lat=_LAT, lng=_LNG)

    assert result is None
    assert len(httpx_mock.get_requests()) == 0
