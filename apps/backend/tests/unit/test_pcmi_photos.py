"""Unit tests for core.pcmi.photos — PCMI7/8 environment photo fetcher.

TDD: tests written before implementation.
asyncio_mode = "auto" so no explicit @pytest.mark.asyncio needed.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.pcmi.photos import (
    _download_image,
    fetch_photo_environnement_lointain,
    fetch_photo_environnement_proche,
)

_LAT = 48.8375
_LNG = 2.4833

_FAKE_IMAGE_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # fake JPEG header


# ---------------------------------------------------------------------------
# _download_image
# ---------------------------------------------------------------------------


class TestDownloadImage:
    async def test_download_returns_bytes(self) -> None:
        """_download_image fetches bytes from URL via http_client."""
        mock_response = MagicMock()
        mock_response.content = _FAKE_IMAGE_BYTES

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)

        with patch("core.pcmi.photos.get_http_client", return_value=mock_client):
            result = await _download_image("https://example.com/photo.jpg")

        assert result == _FAKE_IMAGE_BYTES

    async def test_download_exception_returns_none(self) -> None:
        """_download_image returns None on network exception."""
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=Exception("network error"))

        with patch("core.pcmi.photos.get_http_client", return_value=mock_client):
            result = await _download_image("https://example.com/photo.jpg")

        assert result is None


# ---------------------------------------------------------------------------
# fetch_photo_environnement_proche (PCMI7)
# ---------------------------------------------------------------------------


class TestFetchPhotoEnvironnementProche:
    async def test_uses_mapillary_when_available(self) -> None:
        """PCMI7: returns bytes from Mapillary when photos are found."""
        from core.sources.mapillary import MapillaryPhoto

        fake_photo = MapillaryPhoto(
            image_id="photo_001",
            thumb_url="https://cdn.mapillary.com/photo_001/thumb.jpg",
            captured_at=1680000200000,
            compass_angle=90.0,
            lat=_LAT,
            lng=_LNG,
        )

        with (
            patch(
                "core.pcmi.photos.fetch_photos_around",
                new=AsyncMock(return_value=[fake_photo]),
            ),
            patch(
                "core.pcmi.photos._download_image",
                new=AsyncMock(return_value=_FAKE_IMAGE_BYTES),
            ),
        ):
            result = await fetch_photo_environnement_proche(lat=_LAT, lng=_LNG)

        assert result == _FAKE_IMAGE_BYTES

    async def test_uses_radius_30m_for_proche(self) -> None:
        """PCMI7: Mapillary is called with radius_m=30."""
        mock_fetch = AsyncMock(return_value=[])

        with (
            patch("core.pcmi.photos.fetch_photos_around", new=mock_fetch),
            patch(
                "core.pcmi.photos.fetch_streetview_image",
                new=AsyncMock(return_value=None),
            ),
        ):
            await fetch_photo_environnement_proche(lat=_LAT, lng=_LNG)

        mock_fetch.assert_called_once()
        call_kwargs = mock_fetch.call_args.kwargs
        assert call_kwargs.get("radius_m") == 30

    async def test_fallback_to_streetview(self) -> None:
        """PCMI7: falls back to Street View when Mapillary returns no photos."""
        from core.sources.google_streetview import StreetViewImage

        fake_sv = StreetViewImage(
            pano_id="pano_abc",
            lat=_LAT,
            lng=_LNG,
            date="2024-01",
            image_url="https://maps.googleapis.com/api/streetview?pano=pano_abc",
        )

        with (
            patch(
                "core.pcmi.photos.fetch_photos_around",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "core.pcmi.photos.fetch_streetview_image",
                new=AsyncMock(return_value=fake_sv),
            ),
            patch(
                "core.pcmi.photos._download_image",
                new=AsyncMock(return_value=_FAKE_IMAGE_BYTES),
            ),
        ):
            result = await fetch_photo_environnement_proche(lat=_LAT, lng=_LNG)

        assert result == _FAKE_IMAGE_BYTES

    async def test_returns_none_when_no_source(self) -> None:
        """PCMI7: returns None when both Mapillary and Street View fail."""
        with (
            patch(
                "core.pcmi.photos.fetch_photos_around",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "core.pcmi.photos.fetch_streetview_image",
                new=AsyncMock(return_value=None),
            ),
        ):
            result = await fetch_photo_environnement_proche(lat=_LAT, lng=_LNG)

        assert result is None

    async def test_mapillary_exception_triggers_fallback(self) -> None:
        """PCMI7: Mapillary exception falls back to Street View gracefully."""
        from core.sources.google_streetview import StreetViewImage

        fake_sv = StreetViewImage(
            pano_id="pano_fallback",
            lat=_LAT,
            lng=_LNG,
            date=None,
            image_url="https://maps.googleapis.com/api/streetview?pano=pano_fallback",
        )

        with (
            patch(
                "core.pcmi.photos.fetch_photos_around",
                new=AsyncMock(side_effect=Exception("Mapillary down")),
            ),
            patch(
                "core.pcmi.photos.fetch_streetview_image",
                new=AsyncMock(return_value=fake_sv),
            ),
            patch(
                "core.pcmi.photos._download_image",
                new=AsyncMock(return_value=_FAKE_IMAGE_BYTES),
            ),
        ):
            result = await fetch_photo_environnement_proche(lat=_LAT, lng=_LNG)

        assert result == _FAKE_IMAGE_BYTES


# ---------------------------------------------------------------------------
# fetch_photo_environnement_lointain (PCMI8)
# ---------------------------------------------------------------------------


class TestFetchPhotoEnvironnementLointain:
    async def test_fetch_photo_lointaine_uses_radius_200m(self) -> None:
        """PCMI8: Mapillary is called with radius_m=200."""
        mock_fetch = AsyncMock(return_value=[])

        with (
            patch("core.pcmi.photos.fetch_photos_around", new=mock_fetch),
            patch(
                "core.pcmi.photos.fetch_streetview_image",
                new=AsyncMock(return_value=None),
            ),
        ):
            await fetch_photo_environnement_lointain(lat=_LAT, lng=_LNG)

        mock_fetch.assert_called_once()
        call_kwargs = mock_fetch.call_args.kwargs
        assert call_kwargs.get("radius_m") == 200

    async def test_fetch_photo_lointaine_uses_fov_120(self) -> None:
        """PCMI8: Street View fallback uses fov=120."""
        mock_sv = AsyncMock(return_value=None)

        with (
            patch(
                "core.pcmi.photos.fetch_photos_around",
                new=AsyncMock(return_value=[]),
            ),
            patch("core.pcmi.photos.fetch_streetview_image", new=mock_sv),
        ):
            await fetch_photo_environnement_lointain(lat=_LAT, lng=_LNG)

        mock_sv.assert_called_once()
        call_kwargs = mock_sv.call_args.kwargs
        assert call_kwargs.get("fov") == 120

    async def test_fetch_photo_lointaine_mapillary_success(self) -> None:
        """PCMI8: returns Mapillary bytes when photos available at wide radius."""
        from core.sources.mapillary import MapillaryPhoto

        fake_photo = MapillaryPhoto(
            image_id="photo_far",
            thumb_url="https://cdn.mapillary.com/photo_far/thumb.jpg",
            captured_at=1680000000000,
            compass_angle=270.0,
            lat=_LAT + 0.001,
            lng=_LNG + 0.001,
        )

        with (
            patch(
                "core.pcmi.photos.fetch_photos_around",
                new=AsyncMock(return_value=[fake_photo]),
            ),
            patch(
                "core.pcmi.photos._download_image",
                new=AsyncMock(return_value=_FAKE_IMAGE_BYTES),
            ),
        ):
            result = await fetch_photo_environnement_lointain(lat=_LAT, lng=_LNG)

        assert result == _FAKE_IMAGE_BYTES

    async def test_returns_none_when_no_source_lointain(self) -> None:
        """PCMI8: returns None when both sources fail."""
        with (
            patch(
                "core.pcmi.photos.fetch_photos_around",
                new=AsyncMock(return_value=[]),
            ),
            patch(
                "core.pcmi.photos.fetch_streetview_image",
                new=AsyncMock(return_value=None),
            ),
        ):
            result = await fetch_photo_environnement_lointain(lat=_LAT, lng=_LNG)

        assert result is None
