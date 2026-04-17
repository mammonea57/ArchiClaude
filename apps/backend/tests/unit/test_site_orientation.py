"""Unit tests for core.site.orientation — parcel segment orientation analysis."""

from __future__ import annotations

import math

import pytest
from shapely.geometry import Polygon

from core.site.orientation import SegmentOrientation, compute_orientations

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# A 100×100 m axis-aligned square in Lambert-93 (projected, metres)
# Bottom-left: (0, 0), going CCW: BL → BR → TR → TL → BL
_SQUARE_CCW = Polygon([(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])

# Validate shapely's default is CCW for positive-area polygon
assert _SQUARE_CCW.exterior.is_ccw


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_square_parcel_4_segments() -> None:
    """An axis-aligned square must yield exactly 4 segments with valid qualifications."""
    segments = compute_orientations(_SQUARE_CCW)

    assert len(segments) == 4
    valid_quals = {"N", "NE", "E", "SE", "S", "SO", "O", "NO"}
    for seg in segments:
        assert isinstance(seg, SegmentOrientation)
        assert seg.qualification in valid_quals
        assert 0.0 <= seg.azimut < 360.0
        assert seg.longueur_m > 0.0


def test_south_facing_segment() -> None:
    """The bottom segment of the square (y=0, going from left to right) faces south.

    Bottom segment: (0,0) → (100,0)
    dx=100, dy=0  →  outward normal (dy, -dx) = (0, -100)
    azimuth = atan2(0, -100) = 180° → "S"
    """
    segments = compute_orientations(_SQUARE_CCW)

    # Bottom segment: start=(0,0) end=(100,0)
    bottom = next(
        (s for s in segments if math.isclose(s.start_y, 0) and math.isclose(s.start_x, 0)),
        None,
    )
    assert bottom is not None, "Bottom segment not found"
    assert bottom.qualification == "S"
    assert bottom.azimut == pytest.approx(180.0)


def test_segment_lengths_correct() -> None:
    """All four sides of the 100m square must have length ~100m."""
    segments = compute_orientations(_SQUARE_CCW)

    for seg in segments:
        assert seg.longueur_m == pytest.approx(100.0, abs=1e-6)


def test_degenerate_segment_skipped() -> None:
    """Segments shorter than 0.01m must be skipped."""
    # Build a polygon with a near-zero extra vertex on one side
    tiny = Polygon(
        [
            (0, 0),
            (100, 0),
            (100, 0.001),   # near-zero segment from (100,0) to (100,0.001)
            (100, 100),
            (0, 100),
            (0, 0),
        ]
    )
    segments = compute_orientations(tiny)
    # The degenerate segment (0.001 m) must be filtered out
    lengths = [s.longueur_m for s in segments]
    assert all(length >= 0.01 for length in lengths)


def test_north_facing_segment() -> None:
    """The top segment of the square (y=100, going right to left) faces north.

    Top segment: (100,100) → (0,100)
    dx=-100, dy=0  →  outward normal (dy, -dx) = (0, 100)
    azimuth = atan2(0, 100) = 0° → "N"
    """
    segments = compute_orientations(_SQUARE_CCW)

    top = next(
        (s for s in segments if math.isclose(s.start_y, 100) and math.isclose(s.start_x, 100)),
        None,
    )
    assert top is not None, "Top segment not found"
    assert top.qualification == "N"
    assert top.azimut == pytest.approx(0.0, abs=1e-6)
