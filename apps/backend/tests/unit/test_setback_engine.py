"""Unit tests for core.programming.setback_engine — half-plane intersection."""

from __future__ import annotations

import pytest
from shapely.geometry import Polygon

from core.programming.schemas import ClassifiedSegment
from core.programming.setback_engine import compute_footprint_by_segments


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _square(side: float = 100.0) -> Polygon:
    return Polygon([(0, 0), (side, 0), (side, side), (0, side)])


def _rect(w: float, h: float) -> Polygon:
    return Polygon([(0, 0), (w, 0), (w, h), (0, h)])


def _segments_uniform(parcelle: Polygon, recul: float) -> list[ClassifiedSegment]:
    """Return ClassifiedSegment list with uniform setback on all sides."""
    coords = list(parcelle.exterior.coords)
    segs = []
    for i in range(len(coords) - 1):
        start = tuple(coords[i])
        end = tuple(coords[i + 1])
        segs.append(
            ClassifiedSegment(
                start=start,
                end=end,
                segment_type="separative",
                recul_m=recul,
                longueur_m=0.0,
            )
        )
    return segs


def _segments_100x80(
    recul_bottom: float = 5.0,
    recul_right: float = 3.0,
    recul_top: float = 3.0,
    recul_left: float = 3.0,
) -> tuple[Polygon, list[ClassifiedSegment]]:
    """100×80 rectangle with per-side setbacks (bottom=voirie, rest=sep/fond)."""
    parcelle = Polygon([(0, 0), (100, 0), (100, 80), (0, 80)])
    seg_types = [
        # bottom (voirie)
        ((0.0, 0.0), (100.0, 0.0), "voirie", recul_bottom),
        # right (sep)
        ((100.0, 0.0), (100.0, 80.0), "separative", recul_right),
        # top (fond)
        ((100.0, 80.0), (0.0, 80.0), "fond", recul_top),
        # left (sep)
        ((0.0, 80.0), (0.0, 0.0), "separative", recul_left),
    ]
    segments = [
        ClassifiedSegment(
            start=s,
            end=e,
            segment_type=t,  # type: ignore[arg-type]
            recul_m=r,
            longueur_m=0.0,
        )
        for s, e, t, r in seg_types
    ]
    return parcelle, segments


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_square_uniform_setback() -> None:
    """100×80 with 5/3/3/3 m setbacks → inner rect approx 94×72 = 6768 m²."""
    parcelle, segments = _segments_100x80(5.0, 3.0, 3.0, 3.0)
    footprint = compute_footprint_by_segments(parcelle=parcelle, segments=segments)
    assert not footprint.is_empty
    # voirie=5, others=3 → width 100-3-3=94, height 80-5-3=72
    expected = 94.0 * 72.0
    assert footprint.area == pytest.approx(expected, rel=0.02)


def test_different_setbacks() -> None:
    """voirie 10m, others 3-5m → asymmetric smaller footprint."""
    parcelle = _rect(80.0, 60.0)
    seg_types = [
        ((0.0, 0.0), (80.0, 0.0), "voirie", 10.0),
        ((80.0, 0.0), (80.0, 60.0), "separative", 5.0),
        ((80.0, 60.0), (0.0, 60.0), "fond", 3.0),
        ((0.0, 60.0), (0.0, 0.0), "separative", 4.0),
    ]
    segments = [
        ClassifiedSegment(start=s, end=e, segment_type=t, recul_m=r, longueur_m=0.0)  # type: ignore[arg-type]
        for s, e, t, r in seg_types
    ]
    footprint = compute_footprint_by_segments(parcelle=parcelle, segments=segments)
    assert not footprint.is_empty
    # width: 80-5-4=71, height: 60-10-3=47
    expected = 71.0 * 47.0
    assert footprint.area == pytest.approx(expected, rel=0.02)


def test_triangle_parcelle() -> None:
    """Setback engine works on triangular parcelles."""
    parcelle = Polygon([(0, 0), (60, 0), (30, 50)])
    segments_raw = list(parcelle.exterior.coords)
    segments = []
    for i in range(len(segments_raw) - 1):
        s, e = tuple(segments_raw[i]), tuple(segments_raw[i + 1])
        segments.append(
            ClassifiedSegment(
                start=s, end=e,
                segment_type="separative",  # type: ignore[arg-type]
                recul_m=2.0,
                longueur_m=0.0,
            )
        )
    footprint = compute_footprint_by_segments(parcelle=parcelle, segments=segments)
    # After setback the inner triangle should be smaller but non-empty
    assert not footprint.is_empty
    assert footprint.area < parcelle.area


def test_large_setback_empty() -> None:
    """Setback larger than parcel dimensions → empty result."""
    parcelle = _rect(10.0, 10.0)
    segments = _segments_uniform(parcelle, recul=20.0)
    footprint = compute_footprint_by_segments(parcelle=parcelle, segments=segments)
    assert footprint.is_empty or footprint.area < 0.01


def test_emprise_cap() -> None:
    """50% emprise cap is applied correctly."""
    parcelle = _square(100.0)
    segments = _segments_uniform(parcelle, recul=1.0)
    footprint = compute_footprint_by_segments(
        parcelle=parcelle, segments=segments, emprise_max_pct=50.0
    )
    assert not footprint.is_empty
    # Must be ≤ 50% of parcel area (with tolerance)
    assert footprint.area <= parcelle.area * 0.50 + 1.0


def test_ebc_subtraction() -> None:
    """EBC geometry is subtracted from the footprint."""
    parcelle = _square(100.0)
    segments = _segments_uniform(parcelle, recul=2.0)
    # Large EBC covering most of the interior
    ebc = Polygon([(20, 20), (80, 20), (80, 80), (20, 80)])
    footprint_no_ebc = compute_footprint_by_segments(parcelle=parcelle, segments=segments)
    footprint_ebc = compute_footprint_by_segments(
        parcelle=parcelle, segments=segments, ebc_geom=ebc
    )
    assert footprint_ebc.area < footprint_no_ebc.area


def test_zero_setback() -> None:
    """Zero setback → footprint equals parcelle."""
    parcelle = _square(100.0)
    segments = _segments_uniform(parcelle, recul=0.0)
    footprint = compute_footprint_by_segments(parcelle=parcelle, segments=segments)
    assert footprint.area == pytest.approx(parcelle.area, rel=0.001)


def test_returns_polygon() -> None:
    """Return type is always a Shapely Polygon (or empty geometry)."""
    from shapely.geometry.base import BaseGeometry

    parcelle = _square(100.0)
    segments = _segments_uniform(parcelle, recul=5.0)
    footprint = compute_footprint_by_segments(parcelle=parcelle, segments=segments)
    assert isinstance(footprint, BaseGeometry)
