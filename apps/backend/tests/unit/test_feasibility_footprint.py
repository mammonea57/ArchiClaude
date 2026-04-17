"""Unit tests for core.feasibility.footprint — compute_footprint()."""

from __future__ import annotations

import pytest
from shapely.geometry import MultiPolygon, Polygon

from core.feasibility.footprint import FootprintResult, compute_footprint


def _square(side: float = 100.0) -> Polygon:
    """Return a square polygon in Lambert-93 coordinates (metres)."""
    return Polygon([(0, 0), (side, 0), (side, side), (0, side)])


# ---------------------------------------------------------------------------
# Basic geometry
# ---------------------------------------------------------------------------


def test_square_no_setbacks() -> None:
    terrain = _square(100.0)
    result = compute_footprint(terrain=terrain)
    assert abs(result.surface_emprise_m2 - 10_000.0) < 1.0
    assert result.surface_terrain_m2 == pytest.approx(10_000.0, abs=1.0)


def test_uniform_setbacks() -> None:
    """5 m setback on all sides → 90×90 = 8100 m²."""
    terrain = _square(100.0)
    result = compute_footprint(
        terrain=terrain,
        recul_voirie_m=5.0,
        recul_lat_m=5.0,
        recul_fond_m=5.0,
    )
    # Buffering inward by 5 m on a square → (100-10)² = 8100 m²
    assert abs(result.surface_emprise_m2 - 8_100.0) < 50.0  # buffer tolerance


def test_emprise_cap() -> None:
    """Emprise capped at 60% → ≤ 6000 m²."""
    terrain = _square(100.0)
    result = compute_footprint(terrain=terrain, emprise_max_pct=60.0)
    assert result.surface_emprise_m2 <= 6_000.0 + 1.0  # tiny float tolerance


def test_ebc_subtraction() -> None:
    """A 20×20 EBC polygon removed from terrain → footprint < 9700 m²."""
    terrain = _square(100.0)
    ebc = Polygon([(10, 10), (30, 10), (30, 30), (10, 30)])  # 400 m²
    result = compute_footprint(terrain=terrain, ebc_geom=ebc)
    # Full footprint is 10000, minus ~400 m² EBC
    assert result.surface_emprise_m2 < 9_700.0


def test_pleine_terre() -> None:
    """pleine_terre = terrain.area - footprint.area."""
    terrain = _square(100.0)
    result = compute_footprint(terrain=terrain, emprise_max_pct=60.0)
    expected_pleine_terre = terrain.area - result.surface_emprise_m2
    assert result.surface_pleine_terre_m2 == pytest.approx(expected_pleine_terre, abs=1.0)


def test_empty_after_buffer() -> None:
    """Huge setback on a small parcel → zero emprise."""
    terrain = _square(10.0)  # 10×10 = 100 m²
    result = compute_footprint(
        terrain=terrain,
        recul_voirie_m=20.0,  # larger than parcel
        recul_lat_m=0.0,
        recul_fond_m=0.0,
    )
    assert result.surface_emprise_m2 == 0.0
    assert result.surface_pleine_terre_m2 == pytest.approx(100.0, abs=1.0)


# ---------------------------------------------------------------------------
# Return type and structure
# ---------------------------------------------------------------------------


def test_returns_footprint_result() -> None:
    terrain = _square(100.0)
    result = compute_footprint(terrain=terrain)
    assert isinstance(result, FootprintResult)
    assert result.footprint_geom is not None
    assert result.surface_terrain_m2 == pytest.approx(10_000.0, abs=1.0)


def test_multipolygon_terrain() -> None:
    """compute_footprint should accept MultiPolygon terrains."""
    poly1 = _square(50.0)
    poly2 = Polygon([(100, 0), (150, 0), (150, 50), (100, 50)])
    terrain = MultiPolygon([poly1, poly2])
    result = compute_footprint(terrain=terrain)
    assert result.surface_terrain_m2 == pytest.approx(5_000.0, abs=1.0)
