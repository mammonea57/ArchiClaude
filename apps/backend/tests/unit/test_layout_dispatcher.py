from shapely.geometry import Polygon

from core.building_model.layout_dispatcher import classify_footprint_topology


def test_rectangle_is_rect():
    footprint = Polygon([(0, 0), (20, 0), (20, 12), (0, 12)])
    assert classify_footprint_topology(footprint) == "rect"


def test_l_canon_is_L():
    # L with inner corner at (6.9, 15): bar south + leg east
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    assert classify_footprint_topology(footprint) == "L"


def test_u_shape_is_other():
    # 2 reflex vertices → not L
    footprint = Polygon([
        (0, 0), (30, 0), (30, 20),
        (20, 20), (20, 10), (10, 10), (10, 20),
        (0, 20),
    ])
    assert classify_footprint_topology(footprint) == "other"
