"""
Tests for core.geo.surface — CRS-aware area and buffer calculations.

All area assertions assume reprojection to Lambert-93 (EPSG:2154), a
conformal conic projection that preserves area well for metropolitan France.
"""

import math

import pytest
from shapely.geometry import Point, Polygon

from core.geo.surface import buffer_point_m, polygon_area_m2


# ---------------------------------------------------------------------------
# polygon_area_m2
# ---------------------------------------------------------------------------


def test_known_square_100m_in_lambert93() -> None:
    """A 100 m × 100 m square already in Lambert-93 must report ~10 000 m²."""
    # Build square at a plausible L93 origin (near Paris)
    origin_x, origin_y = 648000.0, 6862000.0
    square = Polygon([
        (origin_x, origin_y),
        (origin_x + 100, origin_y),
        (origin_x + 100, origin_y + 100),
        (origin_x, origin_y + 100),
    ])
    area = polygon_area_m2(square, source_crs="EPSG:2154")
    assert abs(area - 10_000) < 1.0, f"area={area} far from 10 000 m²"


def test_wgs84_polygon_is_reprojected() -> None:
    """A small polygon in WGS84 must be reprojected; result must be > 0 and realistic."""
    # Rough 200 m × 200 m bounding box around Tour Eiffel in WGS84
    # 0.002° latitude ≈ 222 m; 0.003° longitude ≈ 205 m at this latitude
    poly_wgs84 = Polygon([
        (2.2920, 48.8570),
        (2.2950, 48.8570),
        (2.2950, 48.8590),
        (2.2920, 48.8590),
    ])
    area = polygon_area_m2(poly_wgs84, source_crs="EPSG:4326")
    # This rough box should be somewhere between 10 000 and 50 000 m²
    assert 10_000 < area < 50_000, f"area={area} outside expected range"


def test_wgs84_polygon_area_is_positive() -> None:
    """Area must always be positive regardless of ring orientation."""
    poly = Polygon([
        (2.2920, 48.8570),
        (2.2920, 48.8590),
        (2.2950, 48.8590),
        (2.2950, 48.8570),
    ])
    area = polygon_area_m2(poly, source_crs="EPSG:4326")
    assert area > 0, "polygon_area_m2 must return positive area"


# ---------------------------------------------------------------------------
# buffer_point_m
# ---------------------------------------------------------------------------


def test_50m_radius_buffer_area() -> None:
    """Buffer 50 m around a WGS84 point → area ≈ π × 50² = 7 854 m² within 100 m²."""
    pt = Point(2.2945, 48.8584)  # Tour Eiffel, lng/lat order for Shapely
    buffered = buffer_point_m(pt, radius_m=50, source_crs="EPSG:4326")
    # Compute area of the returned geometry (already in Lambert-93)
    area = buffered.area
    expected = math.pi * 50**2  # 7 853.98…
    assert abs(area - expected) < 100, f"area={area}, expected≈{expected}"


def test_buffer_returns_polygon() -> None:
    """buffer_point_m must return a Shapely Polygon."""
    pt = Point(2.2945, 48.8584)
    result = buffer_point_m(pt, radius_m=100, source_crs="EPSG:4326")
    assert isinstance(result, Polygon), f"Expected Polygon, got {type(result)}"


def test_buffer_already_l93_point() -> None:
    """Buffer works correctly when input point is already in Lambert-93."""
    pt = Point(648252, 6862057)
    buffered = buffer_point_m(pt, radius_m=50, source_crs="EPSG:2154")
    area = buffered.area
    expected = math.pi * 50**2
    assert abs(area - expected) < 100, f"area={area}, expected≈{expected}"


def test_buffer_scales_with_radius() -> None:
    """Doubling the radius should roughly quadruple the area."""
    pt = Point(2.2945, 48.8584)
    small = buffer_point_m(pt, radius_m=50, source_crs="EPSG:4326")
    large = buffer_point_m(pt, radius_m=100, source_crs="EPSG:4326")
    ratio = large.area / small.area
    assert abs(ratio - 4.0) < 0.05, f"area ratio={ratio}, expected≈4.0"
