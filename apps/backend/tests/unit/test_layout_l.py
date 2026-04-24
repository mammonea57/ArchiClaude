import math

from shapely.geometry import Polygon

from core.building_model.layout_l import build_l_corridor, compute_l_quadrants, decompose_l, LDecomposition, place_core_at_elbow


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


def test_place_core_at_elbow_size_and_position():
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    d = decompose_l(footprint)
    core_poly = place_core_at_elbow(d, core_surface_m2=22.0)
    # Core placed in ne_bar SW corner; area slightly less than 22 allowed
    # when constrained by ne_bar height.
    assert 18.0 <= core_poly.area <= 22.5, f"got area {core_poly.area}"
    # Rectangular core: 3m wide × ~7.3m long (length may be clamped)
    cx0, cy0, cx1, cy1 = core_poly.bounds
    width = cx1 - cx0
    assert abs(width - 3.0) < 0.1, f"core width should be 3m, got {width}"
    # SW corner at corridor intersection (cx_leg + half, cy_bar + half)
    # = (14.4 + 0.8, 7.5 + 0.8) = (15.2, 8.3)
    assert core_poly.bounds[0] >= 15.0, f"west edge should be ≥ 15.0, got {core_poly.bounds[0]}"
    assert core_poly.bounds[1] >= 8.0, f"south edge should be ≥ 8.0, got {core_poly.bounds[1]}"
    assert core_poly.bounds[2] <= 21.9 + 0.1, f"east edge inside bar, got {core_poly.bounds[2]}"
    assert core_poly.bounds[3] <= 15.0 + 0.1, f"north edge inside bar, got {core_poly.bounds[3]}"
    # Core lies inside footprint
    assert footprint.buffer(0.1).contains(core_poly)


def test_compute_l_quadrants_five_rects():
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    d = decompose_l(footprint)
    quadrants = compute_l_quadrants(d, footprint, corridor_width=1.6)
    assert len(quadrants) == 5
    names = {q.name for q in quadrants}
    assert names == {"south_bar", "nw_bar", "ne_bar", "leg_west", "leg_east"}
    # south_bar runs full bar width below corridor
    south = next(q for q in quadrants if q.name == "south_bar")
    sx0, sy0, sx1, sy1 = south.rect.bounds
    assert abs(sx1 - sx0 - 21.9) < 0.2  # full bar width
    assert abs(sy1 - sy0 - (7.5 - 0.8)) < 0.2  # depth ≈ 6.7 m
    # leg_east: 6.7m deep, 17.4m long
    le = next(q for q in quadrants if q.name == "leg_east")
    ex0, ey0, ex1, ey1 = le.rect.bounds
    assert abs(ex1 - ex0 - (21.9 - 14.4 - 0.8)) < 0.2
    assert abs(ey1 - ey0 - 17.4) < 0.2


from core.building_model.schemas import Typologie
from core.building_model.layout_l import slice_quadrant_into_apts


def test_slice_south_bar_into_T2_gives_3_apts():
    # south_bar: 21.9m wide × 6.7m deep = 147 m². 3 T2 target.
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    d = decompose_l(footprint)
    quads = compute_l_quadrants(d, footprint, corridor_width=1.6)
    south = next(q for q in quads if q.name == "south_bar")
    slots = slice_quadrant_into_apts(
        south, target_typo=Typologie.T2, target_surface=48.0,
    )
    assert 2 <= len(slots) <= 4
    # Each slot's polygon lies inside south_bar
    for s in slots:
        assert south.rect.buffer(0.1).contains(s.polygon)


def test_slice_leg_east_into_T3():
    # leg_east: 6.7m wide × 17.4m deep = ~117 m². ~2 T3 (58 m² target).
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    d = decompose_l(footprint)
    quads = compute_l_quadrants(d, footprint, corridor_width=1.6)
    le = next(q for q in quads if q.name == "leg_east")
    slots = slice_quadrant_into_apts(
        le, target_typo=Typologie.T3, target_surface=58.0,
    )
    assert len(slots) >= 2


from core.building_model.layout_l import compute_l_layout


def test_compute_l_layout_nogent_style_footprint():
    # User's real project: L canonical inner-corner NW
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    result = compute_l_layout(
        footprint,
        mix_typologique={Typologie.T2: 0.4, Typologie.T3: 0.6},
        core_surface_m2=22.0,
        corridor_width=1.6,
    )
    # Core placed at the RIGHT HALF of the sacrificed landlocked slot.
    # The slot is roughly (6.9, 8.3)-(21.9, 15) so the right half is
    # roughly (14.4, 8.3)-(21.9, 15) = ~7.5 × 6.7 m.
    cx0, cy0, cx1, cy1 = result.core.bounds
    assert cx1 - cx0 > 1.5, f"core width too small: {cx1 - cx0}"
    assert cy1 - cy0 > 1.5, f"core height too small: {cy1 - cy0}"
    # Corridor is a single connected polygon
    assert result.corridor.geom_type == "Polygon"
    # Apartment count: target 9/niveau (one less than 10 since ne_bar
    # is no longer sliced into apt slots).
    assert 7 <= len(result.slots) <= 11, f"got {len(result.slots)} slots"
    # All slots inside footprint
    for s in result.slots:
        assert footprint.buffer(0.1).contains(s.polygon)
    # No slot overlaps corridor or core
    occupied = result.corridor.union(result.core)
    for s in result.slots:
        overlap = s.polygon.intersection(occupied).area
        assert overlap < 0.5, f"slot {s.id} overlaps circulation"


def test_compute_l_layout_no_landlocked_apts():
    """No apartment slot may have zero exterior façades.

    The landlocked-detection algorithm must sacrifice exactly the
    landlocked slot for the core, not a slot-by-name-only rule.
    """
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    result = compute_l_layout(
        footprint,
        mix_typologique={Typologie.T2: 0.3, Typologie.T3: 0.4, Typologie.T4: 0.2, Typologie.T5: 0.1},
        core_surface_m2=22.0,
        corridor_width=1.6,
    )
    # Every surviving slot has at least one exterior side.
    for s in result.slots:
        assert len(s.orientations) >= 1, (
            f"slot {s.id} is landlocked (orientations={s.orientations}) "
            f"at bounds={s.polygon.bounds}"
        )
    # Core lies inside footprint and doesn't overlap any slot.
    assert footprint.buffer(0.1).contains(result.core)
    for s in result.slots:
        assert s.polygon.intersection(result.core).area < 0.5, (
            f"slot {s.id} overlaps core"
        )


def test_ne_bar_facade_excludes_interior_north():
    """Regression: ne_bar's north edge is shared with leg (interior), not exterior."""
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    d = decompose_l(footprint)
    quads = compute_l_quadrants(d, footprint, corridor_width=1.6)
    ne = next(q for q in quads if q.name == "ne_bar")
    # ne_bar is at x∈[15.2, 21.9], y∈[8.3, 15]. The north edge (y=15) is
    # shared with leg (leg x∈[6.9, 21.9] for y∈[15, 32.4]), so it's INTERIOR.
    # Only "est" (x=21.9 = footprint east edge) is exterior.
    assert "nord" not in ne.facade_sides, f"ne_bar north is interior, not facade: got {ne.facade_sides}"
    assert "est" in ne.facade_sides, f"ne_bar east must be exterior facade: got {ne.facade_sides}"
