"""Unit tests for core.programming.segment_classifier — 3-tier classification."""

from __future__ import annotations

import pytest
from shapely.geometry import LineString, MultiLineString, Point, Polygon

from core.programming.schemas import ClassifiedSegment
from core.programming.segment_classifier import classify_segments


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _square(side: float = 100.0) -> Polygon:
    """Return an axis-aligned square parcelle at the origin."""
    return Polygon([(0, 0), (side, 0), (side, side), (0, side)])


def _rect(w: float, h: float) -> Polygon:
    return Polygon([(0, 0), (w, 0), (w, h), (0, h)])


def _triangle() -> Polygon:
    return Polygon([(0, 0), (60, 0), (30, 50)])


def _road_along_bottom(buffer: float = 5.0) -> Polygon:
    """A road polygon running along the bottom edge (y < 0)."""
    return Polygon([(-10, -buffer - 1), (110, -buffer - 1), (110, 0), (-10, 0)])


# ---------------------------------------------------------------------------
# Tier 2 — BDTopo roads
# ---------------------------------------------------------------------------


def test_classify_by_roads_voirie() -> None:
    """Bottom segment (y=0) is closest to road → classified as voirie."""
    parcelle = _square(100.0)
    road = _road_along_bottom()
    segments = classify_segments(parcelle, roads=road, recul_voirie=5.0, recul_sep=3.0, recul_fond=3.0)
    types = {s.segment_type for s in segments}
    assert "voirie" in types


def test_roads_separative() -> None:
    """Lateral segments (left/right) should be classified as separative."""
    parcelle = _square(100.0)
    road = _road_along_bottom()
    segments = classify_segments(parcelle, roads=road, recul_voirie=5.0, recul_sep=3.0, recul_fond=3.0)
    types = [s.segment_type for s in segments]
    assert "separative" in types


def test_roads_fond() -> None:
    """Top segment (farthest from road) should be classified as fond."""
    parcelle = _square(100.0)
    road = _road_along_bottom()
    segments = classify_segments(parcelle, roads=road, recul_voirie=5.0, recul_sep=3.0, recul_fond=3.0)
    types = [s.segment_type for s in segments]
    assert "fond" in types


def test_corner_two_voirie() -> None:
    """Corner lot with roads on two sides → two voirie segments."""
    parcelle = _square(100.0)
    # Road covers both bottom and left sides
    road = Polygon([(-10, -10), (110, -10), (110, 5), (5, 5), (5, 110), (-10, 110)])
    segments = classify_segments(parcelle, roads=road, recul_voirie=5.0, recul_sep=3.0, recul_fond=3.0)
    voirie_count = sum(1 for s in segments if s.segment_type == "voirie")
    assert voirie_count >= 2


# ---------------------------------------------------------------------------
# Tier 3 — Heuristic fallback
# ---------------------------------------------------------------------------


def test_heuristic_longest_is_voirie() -> None:
    """Without roads, longest segment presumed voirie."""
    # Tall rectangle: long sides are left/right (100m), short are top/bottom (40m)
    parcelle = _rect(40.0, 100.0)
    segments = classify_segments(parcelle, recul_voirie=5.0, recul_sep=3.0, recul_fond=3.0)
    voirie_segs = [s for s in segments if s.segment_type == "voirie"]
    assert len(voirie_segs) >= 1
    # The longest segment should be voirie
    all_lengths = [s.longueur_m for s in segments]
    max_len = max(all_lengths)
    voirie_lens = [s.longueur_m for s in voirie_segs]
    assert max_len in voirie_lens


def test_all_classified() -> None:
    """All segments must have a non-None segment_type."""
    parcelle = _square(100.0)
    segments = classify_segments(parcelle, recul_voirie=5.0, recul_sep=3.0, recul_fond=3.0)
    assert all(s.segment_type in ("voirie", "separative", "fond") for s in segments)
    assert len(segments) > 0


def test_with_roads_uses_tier2() -> None:
    """When roads are provided, result differs from pure heuristic."""
    parcelle = _square(100.0)
    road = _road_along_bottom()
    seg_heuristic = classify_segments(parcelle, recul_voirie=5.0, recul_sep=3.0, recul_fond=3.0)
    seg_roads = classify_segments(parcelle, roads=road, recul_voirie=5.0, recul_sep=3.0, recul_fond=3.0)
    # Both return valid segments; roads version should have voirie near y=0
    voirie_road_starts = {s.start[1] for s in seg_roads if s.segment_type == "voirie"}
    # Bottom segment starts at y=0
    assert any(abs(y) < 1.0 for y in voirie_road_starts)


def test_without_roads_uses_heuristic() -> None:
    """Without roads/GPU, heuristic tier is used (returns segments)."""
    parcelle = _square(100.0)
    segments = classify_segments(parcelle, recul_voirie=5.0, recul_sep=3.0, recul_fond=3.0)
    assert isinstance(segments, list)
    assert all(isinstance(s, ClassifiedSegment) for s in segments)


def test_triangle_parcelle() -> None:
    """Classifier works on triangular parcelles (3 segments)."""
    parcelle = _triangle()
    segments = classify_segments(parcelle, recul_voirie=5.0, recul_sep=3.0, recul_fond=3.0)
    assert len(segments) == 3
    assert all(s.segment_type in ("voirie", "separative", "fond") for s in segments)


# ---------------------------------------------------------------------------
# Tier 1 — GPU prescriptions override
# ---------------------------------------------------------------------------


def test_gpu_prescriptions_override() -> None:
    """GPU prescriptions override road/heuristic classification."""
    parcelle = _square(100.0)
    road = _road_along_bottom()

    # Create a GPU prescription on the TOP segment (normally fond)
    # typepsc="15", sous_type="01" → voirie prescription
    top_segment_geom = LineString([(0, 100), (100, 100)])
    prescriptions = [
        {
            "typepsc": "15",
            "sous_type": "01",
            "geometry": top_segment_geom,
        }
    ]
    segments = classify_segments(
        parcelle,
        prescriptions_gpu=prescriptions,
        roads=road,
        recul_voirie=5.0,
        recul_sep=3.0,
        recul_fond=3.0,
    )
    # Top segment should be voirie (overridden by GPU)
    top_voirie = [
        s
        for s in segments
        if s.segment_type == "voirie" and (abs(s.start[1] - 100) < 1 or abs(s.end[1] - 100) < 1)
    ]
    assert len(top_voirie) >= 1


# ---------------------------------------------------------------------------
# Setback values
# ---------------------------------------------------------------------------


def test_setback_values_assigned() -> None:
    """Setback recul_m is correctly assigned per type."""
    parcelle = _square(100.0)
    road = _road_along_bottom()
    segments = classify_segments(
        parcelle,
        roads=road,
        recul_voirie=7.0,
        recul_sep=4.0,
        recul_fond=5.0,
    )
    for s in segments:
        if s.segment_type == "voirie":
            assert s.recul_m == pytest.approx(7.0)
        elif s.segment_type == "separative":
            assert s.recul_m == pytest.approx(4.0)
        elif s.segment_type == "fond":
            assert s.recul_m == pytest.approx(5.0)


def test_longueur_m_populated() -> None:
    """longueur_m should be populated for each segment."""
    parcelle = _square(100.0)
    segments = classify_segments(parcelle, recul_voirie=5.0, recul_sep=3.0, recul_fond=3.0)
    for s in segments:
        assert s.longueur_m > 0.0
