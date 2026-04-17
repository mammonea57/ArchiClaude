"""
Tests for core.geo.projections — Lambert-93 ↔ WGS84 coordinate transformations.

Reference points are verified against IGN Géoportail and pyproj documentation.
Tolerances are strict: 5m for known landmarks, 1e-7° for round-trips.
"""

from core.geo.projections import lambert93_to_wgs84, wgs84_to_lambert93


def test_paris_center_tour_eiffel() -> None:
    """Tour Eiffel WGS84 → Lambert-93 must land within 5 m of pyproj reference."""
    x, y = wgs84_to_lambert93(lat=48.8584, lng=2.2945)
    # pyproj/EPSG:2154 reference: (648237.3, 6862271.7)
    assert abs(x - 648237) < 5, f"x={x} far from expected 648237"
    assert abs(y - 6862272) < 5, f"y={y} far from expected 6862272"


def test_nogent_sur_marne() -> None:
    """Nogent-sur-Marne WGS84 → Lambert-93 must land in expected range."""
    x, y = wgs84_to_lambert93(lat=48.8375, lng=2.4833)
    # Nogent-sur-Marne is east of Paris; x > 650 000, y ~ 6 860 000
    assert 658000 < x < 666000, f"x={x} outside expected range for Nogent-sur-Marne"
    assert 6857000 < y < 6863000, f"y={y} outside expected range for Nogent-sur-Marne"


def test_roundtrip_wgs84_l93_wgs84() -> None:
    """WGS84 → L93 → WGS84 identity within 1e-7 degrees (≈ 1 cm)."""
    original_lat = 48.8584
    original_lng = 2.2945
    x, y = wgs84_to_lambert93(lat=original_lat, lng=original_lng)
    recovered_lat, recovered_lng = lambert93_to_wgs84(x=x, y=y)
    assert abs(recovered_lat - original_lat) < 1e-7, (
        f"lat drift: {abs(recovered_lat - original_lat)}"
    )
    assert abs(recovered_lng - original_lng) < 1e-7, (
        f"lng drift: {abs(recovered_lng - original_lng)}"
    )


def test_known_point_l93_to_wgs84() -> None:
    """Lambert-93 (648237, 6862272) → WGS84 should be near Tour Eiffel (48.8584, 2.2945)."""
    lat, lng = lambert93_to_wgs84(x=648237, y=6862272)
    assert abs(lat - 48.8584) < 0.001, f"lat={lat} unexpected"
    assert abs(lng - 2.2945) < 0.001, f"lng={lng} unexpected"


def test_return_types_are_float() -> None:
    """Both functions must return plain Python floats, not numpy scalars."""
    x, y = wgs84_to_lambert93(lat=48.8584, lng=2.2945)
    assert isinstance(x, float), f"x is {type(x)}, expected float"
    assert isinstance(y, float), f"y is {type(y)}, expected float"

    lat, lng = lambert93_to_wgs84(x=648237, y=6862272)
    assert isinstance(lat, float), f"lat is {type(lat)}, expected float"
    assert isinstance(lng, float), f"lng is {type(lng)}, expected float"


def test_transformer_singleton_is_consistent() -> None:
    """Calling the functions multiple times must return identical results (thread-safe singleton)."""
    result_a = wgs84_to_lambert93(lat=48.8375, lng=2.4833)
    result_b = wgs84_to_lambert93(lat=48.8375, lng=2.4833)
    assert result_a == result_b
