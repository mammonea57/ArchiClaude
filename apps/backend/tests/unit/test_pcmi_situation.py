"""Unit tests for core.pcmi.situation — PCMI1 plan de situation."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from shapely.geometry import Polygon  # noqa: TCH002

from core.pcmi.situation import (
    LAYERS,
    _choose_wmts_layer,
    _compute_map_bounds,
    generate_pcmi1,
)

# ---------------------------------------------------------------------------
# Helper: simple square parcel centred at a known point
# ---------------------------------------------------------------------------

def _square_parcel(lng: float, lat: float, size_deg: float = 0.001) -> Polygon:
    h = size_deg / 2.0
    return Polygon([
        (lng - h, lat - h),
        (lng + h, lat - h),
        (lng + h, lat + h),
        (lng - h, lat + h),
        (lng - h, lat - h),
    ])


# ---------------------------------------------------------------------------
# Layer selection tests
# ---------------------------------------------------------------------------


def test_scan25_default() -> None:
    layer = _choose_wmts_layer("scan25")
    assert layer == LAYERS["scan25"]
    assert "SCAN25" in layer


def test_planv2() -> None:
    layer = _choose_wmts_layer("planv2")
    assert layer == LAYERS["planv2"]
    assert "PLANIGNV2" in layer


def test_unknown_falls_back_scan25() -> None:
    layer = _choose_wmts_layer("unknown_base_map")
    assert layer == LAYERS["scan25"]


# ---------------------------------------------------------------------------
# Bounds computation tests
# ---------------------------------------------------------------------------


def test_bounds_around_parcel() -> None:
    parcel = _square_parcel(2.3488, 48.8534)
    bounds = _compute_map_bounds([parcel])
    # Bounds must be larger than the parcel itself
    assert bounds["min_lng"] < 2.3488
    assert bounds["max_lng"] > 2.3488
    assert bounds["min_lat"] < 48.8534
    assert bounds["max_lat"] > 48.8534


def test_bounds_centered_on_parcels() -> None:
    """Centre of bounds should equal centroid of input parcels."""
    p1 = _square_parcel(2.3488, 48.8534)
    p2 = _square_parcel(2.3508, 48.8554)
    bounds = _compute_map_bounds([p1, p2])
    centre_lng = (bounds["min_lng"] + bounds["max_lng"]) / 2.0
    centre_lat = (bounds["min_lat"] + bounds["max_lat"]) / 2.0
    # Expected centroid
    expected_lng = (2.3488 + 2.3508) / 2.0
    expected_lat = (48.8534 + 48.8554) / 2.0
    assert abs(centre_lng - expected_lng) < 0.001
    assert abs(centre_lat - expected_lat) < 0.001


def test_bounds_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        _compute_map_bounds([])


# ---------------------------------------------------------------------------
# SVG generation tests (async, tile fetch mocked)
# ---------------------------------------------------------------------------

# Minimal valid 1x1 pixel PNG for mocking tile responses
_FAKE_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x18\xddqb\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.mark.asyncio
async def test_generate_pcmi1_returns_svg() -> None:
    """generate_pcmi1 must return an SVG document string."""
    parcel = _square_parcel(2.3488, 48.8534)
    with patch(
        "core.pcmi.situation._fetch_wmts_tile",
        new=AsyncMock(return_value=_FAKE_PNG),
    ):
        svg = await generate_pcmi1(parcelles=[parcel], map_base="scan25")

    assert isinstance(svg, str)
    assert svg.strip().startswith("<svg")
    assert "</svg>" in svg


@pytest.mark.asyncio
async def test_contains_parcel_polygon() -> None:
    """The SVG must contain at least one <polygon element for the parcel overlay."""
    parcel = _square_parcel(2.3488, 48.8534)
    with patch(
        "core.pcmi.situation._fetch_wmts_tile",
        new=AsyncMock(return_value=_FAKE_PNG),
    ):
        svg = await generate_pcmi1(parcelles=[parcel], map_base="scan25")

    assert "<polygon" in svg


@pytest.mark.asyncio
async def test_contains_red_circle() -> None:
    """SVG must contain a red circle at the parcel centroid."""
    parcel = _square_parcel(2.3488, 48.8534)
    with patch(
        "core.pcmi.situation._fetch_wmts_tile",
        new=AsyncMock(return_value=_FAKE_PNG),
    ):
        svg = await generate_pcmi1(parcelles=[parcel], map_base="scan25")

    assert "<circle" in svg
    assert "#FF0000" in svg


@pytest.mark.asyncio
async def test_contains_scale_text() -> None:
    """SVG must contain the scale label."""
    parcel = _square_parcel(2.3488, 48.8534)
    with patch(
        "core.pcmi.situation._fetch_wmts_tile",
        new=AsyncMock(return_value=_FAKE_PNG),
    ):
        svg = await generate_pcmi1(parcelles=[parcel], map_base="scan25")

    assert "25000" in svg
    assert "IGN" in svg


@pytest.mark.asyncio
async def test_fallback_on_tile_error() -> None:
    """When the tile fetch fails, generate_pcmi1 must still return valid SVG."""
    parcel = _square_parcel(2.3488, 48.8534)
    with patch(
        "core.pcmi.situation._fetch_wmts_tile",
        new=AsyncMock(side_effect=Exception("network error")),
    ):
        svg = await generate_pcmi1(parcelles=[parcel], map_base="scan25")

    assert svg.strip().startswith("<svg")
    assert "<rect" in svg  # white background fallback
    assert "<polygon" in svg  # parcel overlay still present


@pytest.mark.asyncio
async def test_generate_pcmi1_planv2() -> None:
    """generate_pcmi1 must work with map_base='planv2'."""
    parcel = _square_parcel(2.3488, 48.8534)
    with patch(
        "core.pcmi.situation._fetch_wmts_tile",
        new=AsyncMock(return_value=_FAKE_PNG),
    ) as mock_fetch:
        svg = await generate_pcmi1(parcelles=[parcel], map_base="planv2")

    assert svg.strip().startswith("<svg")
    # The layer used must be the planv2 layer
    call_kwargs = mock_fetch.call_args.kwargs
    assert "PLANIGNV2" in call_kwargs["layer"]


@pytest.mark.asyncio
async def test_generate_pcmi1_empty_raises() -> None:
    with pytest.raises(ValueError, match="empty"):
        await generate_pcmi1(parcelles=[], map_base="scan25")
