import math

from shapely.geometry import Polygon

from core.building_model.layout_l import build_l_corridor, decompose_l, LDecomposition


def test_decompose_l_inner_corner_nw():
    # Inner corner at (6.9, 15): bar is south rectangle spanning full
    # width, leg is east rectangle spanning y=15..32.4 at x=6.9..21.9
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    d = decompose_l(footprint)
    assert d is not None
    # Bar (horizontal arm) bounds
    bx0, by0, bx1, by1 = d.bar.bounds
    assert math.isclose(bx0, 0.0, abs_tol=0.1)
    assert math.isclose(bx1, 21.9, abs_tol=0.1)
    assert math.isclose(by0, 0.0, abs_tol=0.1)
    assert math.isclose(by1, 15.0, abs_tol=0.1)
    # Leg (vertical arm) bounds
    lx0, ly0, lx1, ly1 = d.leg.bounds
    assert math.isclose(lx0, 6.9, abs_tol=0.1)
    assert math.isclose(lx1, 21.9, abs_tol=0.1)
    assert math.isclose(ly0, 15.0, abs_tol=0.1)
    assert math.isclose(ly1, 32.4, abs_tol=0.1)
    # Reflex at inner corner
    assert math.isclose(d.reflex[0], 6.9, abs_tol=0.1)
    assert math.isclose(d.reflex[1], 15.0, abs_tol=0.1)
    # Elbow = (leg centerline x, bar centerline y) = (14.4, 7.5)
    assert math.isclose(d.elbow[0], (6.9 + 21.9) / 2, abs_tol=0.1)
    assert math.isclose(d.elbow[1], (0.0 + 15.0) / 2, abs_tol=0.1)


def test_decompose_l_rotated_all_four_orientations():
    # Template L at inner-corner NW (= outer corner SE)
    base = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    # Rotate 0/90/180/270 degrees → all 4 orientations must decompose
    from shapely.affinity import rotate
    for angle in (0, 90, 180, 270):
        rotated = rotate(base, angle, origin=(10, 10))
        # snap bounds to axis-aligned form (rotation preserves axis-alignment
        # for multiples of 90°)
        d = decompose_l(rotated)
        assert d is not None, f"decompose_l failed at angle={angle}"
        assert d.bar.area > 0 and d.leg.area > 0
        # Elbow must lie inside the footprint
        from shapely.geometry import Point
        assert rotated.buffer(0.2).contains(Point(d.elbow))


def test_build_l_corridor_is_single_connected_polygon():
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    d = decompose_l(footprint)
    corridor = build_l_corridor(d, corridor_width=1.6)
    # Single polygon (not MultiPolygon) → corridor is continuous
    assert corridor.geom_type == "Polygon"
    # Corridor area ≈ (bar width × 1.6) + (leg height × 1.6) − junction overlap
    # Bar: 21.9 × 1.6 = 35.04. Leg strip in bar: (15 − 7.5 − 0.8) × 1.6 ≈ 6.7 × 1.6 = 10.72
    # Leg above bar: 17.4 × 1.6 = 27.84. Total ≈ 35.04 + 10.72 + 27.84 ≈ 73.6 m²
    # Minus overlap at junction (1.6 × 1.6 = 2.56) → ~71 m²
    assert 60.0 < corridor.area < 90.0
    # Corridor must lie inside footprint (with small tolerance for rounding)
    assert footprint.buffer(0.1).contains(corridor.buffer(-0.05))


def test_build_l_corridor_touches_both_arm_ends():
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    d = decompose_l(footprint)
    corridor = build_l_corridor(d, corridor_width=1.6)
    cxmin, cymin, cxmax, cymax = corridor.bounds
    # Corridor spans from bar's west end (x=0) to leg's top (y=32.4)
    assert abs(cxmin - 0.0) < 0.5
    assert abs(cymax - 32.4) < 0.5
