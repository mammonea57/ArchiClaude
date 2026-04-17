"""Unit tests for core.sources.mapillary — Mapillary Graph API client.

HTTP calls are intercepted at transport level by pytest-httpx.
"""

from __future__ import annotations

import re

import pytest
from pytest_httpx import HTTPXMock

from core.sources.mapillary import fetch_photos_around

_MAPILLARY_URL_RE = re.compile(r"https://graph\.mapillary\.com/images.*")

_LAT = 48.8375
_LNG = 2.4833

_MOCK_RESPONSE = {
    "data": [
        {
            "id": "photo_001",
            "captured_at": 1680000200000,
            "compass_angle": 90.0,
            "thumb_1024_url": "https://cdn.mapillary.com/photo_001/thumb.jpg",
            "geometry": {"type": "Point", "coordinates": [2.4834, 48.8376]},
        },
        {
            "id": "photo_002",
            "captured_at": 1680000100000,
            "compass_angle": 180.0,
            "thumb_1024_url": "https://cdn.mapillary.com/photo_002/thumb.jpg",
            "geometry": {"type": "Point", "coordinates": [2.4835, 48.8374]},
        },
    ]
}

_EMPTY_RESPONSE = {"data": []}


async def test_photos_found(httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns MapillaryPhoto list sorted by captured_at descending when photos exist."""
    monkeypatch.setenv("MAPILLARY_CLIENT_TOKEN", "test_token_abc")
    httpx_mock.add_response(url=_MAPILLARY_URL_RE, json=_MOCK_RESPONSE)

    photos = await fetch_photos_around(lat=_LAT, lng=_LNG, radius_m=50)

    assert len(photos) == 2

    # Most recent first
    assert photos[0].image_id == "photo_001"
    assert photos[0].captured_at == 1680000200000
    assert photos[0].compass_angle == pytest.approx(90.0)
    assert photos[0].thumb_url == "https://cdn.mapillary.com/photo_001/thumb.jpg"
    assert photos[0].lat == pytest.approx(48.8376)
    assert photos[0].lng == pytest.approx(2.4834)

    assert photos[1].image_id == "photo_002"
    assert photos[1].captured_at == 1680000100000


async def test_no_photos(httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch) -> None:
    """Returns empty list when Mapillary returns no photos."""
    monkeypatch.setenv("MAPILLARY_CLIENT_TOKEN", "test_token_abc")
    httpx_mock.add_response(url=_MAPILLARY_URL_RE, json=_EMPTY_RESPONSE)

    photos = await fetch_photos_around(lat=_LAT, lng=_LNG)

    assert photos == []


async def test_no_token_returns_empty(
    httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Returns empty list without making any HTTP call when token is absent."""
    monkeypatch.delenv("MAPILLARY_CLIENT_TOKEN", raising=False)

    photos = await fetch_photos_around(lat=_LAT, lng=_LNG)

    assert photos == []
    assert len(httpx_mock.get_requests()) == 0
