"""Tests for core.analysis.shadow — solar position + shadow projection."""

import math
import pytest
from shapely.geometry import Polygon, box

from core.analysis.shadow import (
    compute_sun_position,
    compute_shadow_polygon,
    compute_shadow_mode_a,
    compute_shadow_mode_b,
    ShadowModeAResult,
    ShadowModeBResult,
)


# ── solar position ────────────────────────────────────────────────────────────

def test_paris_winter_noon():
    """Dec 21 at noon Paris → altitude ~18°, azimuth ~180°."""
    alt, az = compute_sun_position(lat=48.8566, lng=2.3522, month=12, day=21, hour=12)
    assert 15.0 <= alt <= 25.0, f"Expected winter noon altitude 15-25°, got {alt:.1f}°"
    assert 160.0 <= az <= 200.0, f"Expected azimuth ~180°, got {az:.1f}°"


def test_paris_summer_noon():
    """Jun 21 at noon Paris → altitude ~60-70°."""
    alt, az = compute_sun_position(lat=48.8566, lng=2.3522, month=6, day=21, hour=12)
    assert 60.0 <= alt <= 70.0, f"Expected summer noon altitude 60-70°, got {alt:.1f}°"


def test_sun_altitude_positive_at_noon():
    alt, az = compute_sun_position(lat=48.8566, lng=2.3522, month=6, day=21, hour=12)
    assert alt > 0


def test_sun_altitude_higher_summer_than_winter():
    alt_w, _ = compute_sun_position(lat=48.8566, lng=2.3522, month=12, day=21, hour=12)
    alt_s, _ = compute_sun_position(lat=48.8566, lng=2.3522, month=6, day=21, hour=12)
    assert alt_s > alt_w


# ── shadow projection ─────────────────────────────────────────────────────────

def test_shadow_projects_north():
    """Sun from south (azimuth=180) → shadow projects north (opposite direction)."""
    building = box(0, 0, 10, 10)
    shadow = compute_shadow_polygon(building, hauteur_m=10, sun_altitude=30.0, sun_azimuth=180.0)
    # Shadow centroid should be north (positive y) of building centroid
    assert shadow.centroid.y > building.centroid.y


def test_shadow_length_45deg():
    """At 45° altitude, shadow length ≈ building height (tan(45)=1)."""
    building = box(0, 0, 1, 1)
    shadow = compute_shadow_polygon(building, hauteur_m=10.0, sun_altitude=45.0, sun_azimuth=180.0)
    # Bounding box height should extend ~10m north of building
    minx, miny, maxx, maxy = shadow.bounds
    shadow_extent = maxy - 1.0  # metres north of building (building is 0..1)
    assert 8.0 <= shadow_extent <= 12.0, f"Expected ~10m shadow, got {shadow_extent:.1f}m"


def test_shadow_is_polygon():
    building = box(0, 0, 10, 10)
    shadow = compute_shadow_polygon(building, hauteur_m=15.0, sun_altitude=20.0, sun_azimuth=180.0)
    assert shadow.geom_type in ("Polygon", "MultiPolygon")


def test_shadow_longer_at_low_altitude():
    building = box(0, 0, 10, 10)
    s_low = compute_shadow_polygon(building, hauteur_m=10, sun_altitude=10.0, sun_azimuth=180.0)
    s_high = compute_shadow_polygon(building, hauteur_m=10, sun_altitude=60.0, sun_azimuth=180.0)
    _, miny_low, _, maxy_low = s_low.bounds
    _, miny_high, _, maxy_high = s_high.bounds
    assert maxy_low > maxy_high


# ── Mode A ───────────────────────────────────────────────────────────────────

def test_mode_a_critical_shadows():
    """Mode A: Dec 21 at 10h, 12h, 14h → exactly 3 shadows."""
    building = box(0, 0, 20, 20)
    result = compute_shadow_mode_a(building, hauteur_m=12.0)
    assert isinstance(result, ShadowModeAResult)
    assert len(result.shadows) == 3


def test_mode_a_returns_polygons():
    building = box(0, 0, 20, 20)
    result = compute_shadow_mode_a(building, hauteur_m=12.0)
    for entry in result.shadows:
        assert "shadow" in entry
        assert entry["shadow"].geom_type in ("Polygon", "MultiPolygon")


def test_mode_a_has_hours():
    building = box(0, 0, 20, 20)
    result = compute_shadow_mode_a(building, hauteur_m=12.0)
    hours = {entry["hour"] for entry in result.shadows}
    assert hours == {10, 12, 14}


# ── Mode B ───────────────────────────────────────────────────────────────────

def test_mode_b_aggravation():
    """With 1 neighbor, pct_aggravation > 0."""
    building = box(0, 0, 20, 20)
    neighbor = {"geometry": box(0, 25, 15, 40).__geo_interface__, "hauteur_m": 10.0}
    result = compute_shadow_mode_b(building, hauteur_m=15.0, voisins=[neighbor])
    assert isinstance(result, ShadowModeBResult)
    assert result.pct_aggravation > 0


def test_mode_b_no_voisins():
    """No neighbors → aggravation may still be positive (all new shadow)."""
    building = box(0, 0, 20, 20)
    result = compute_shadow_mode_b(building, hauteur_m=15.0, voisins=[])
    assert isinstance(result, ShadowModeBResult)
    # All shadow is new when there are no neighbors
    assert result.ombre_existante_m2 == pytest.approx(0.0, abs=1e-6)


def test_mode_b_fields_present():
    building = box(0, 0, 20, 20)
    result = compute_shadow_mode_b(building, hauteur_m=10.0, voisins=[])
    assert hasattr(result, "ombre_existante_m2")
    assert hasattr(result, "ombre_future_m2")
    assert hasattr(result, "ombre_ajoutee_m2")
    assert hasattr(result, "pct_aggravation")
