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


from core.building_model.schemas import Typologie
from core.building_model.layout_dispatcher import dispatch_layout


def test_dispatch_l_returns_l_result():
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    result = dispatch_layout(
        footprint,
        mix_typologique={Typologie.T2: 0.4, Typologie.T3: 0.6},
        core_surface_m2=22.0,
    )
    assert result is not None
    assert len(result.slots) >= 8


def test_dispatch_rect_returns_none():
    footprint = Polygon([(0, 0), (20, 0), (20, 12), (0, 12)])
    result = dispatch_layout(
        footprint,
        mix_typologique={Typologie.T2: 0.5, Typologie.T3: 0.5},
        core_surface_m2=22.0,
    )
    assert result is None  # rect → caller uses legacy wing-par-wing


def test_circulation_network_on_l_uses_dispatcher_corridor():
    from shapely.geometry import Polygon
    from core.building_model.solver import (
        _compute_circulation_network, _decompose_into_wings,
        build_modular_grid, place_core,
    )
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    grid = build_modular_grid(footprint, cell_size_m=3.0)
    core = place_core(grid, core_surface_m2=22.0)
    wings = _decompose_into_wings(footprint)
    network = _compute_circulation_network(footprint, wings, core)
    # Network includes both arms of the L (corridor touches x=0 and y=32.4)
    nxmin, nymin, nxmax, nymax = network.bounds
    assert nxmin < 1.0, "corridor must reach bar west end"
    assert nymax > 31.0, "corridor must reach leg north end"


def test_pipeline_emit_l_corridor_is_single_circulation():
    from shapely.geometry import Polygon
    from core.building_model.solver import build_modular_grid, place_core
    from core.building_model.pipeline import _emit_wing_corridors
    footprint = Polygon([
        (0, 0), (21.9, 0), (21.9, 32.4),
        (6.9, 32.4), (6.9, 15), (0, 15),
    ])
    grid = build_modular_grid(footprint, cell_size_m=3.0)
    core = place_core(grid, core_surface_m2=22.0)
    circulations = _emit_wing_corridors(0, core, footprint, [])
    # Expect exactly one Circulation for the L corridor
    couloirs = [c for c in circulations if c.id.startswith("couloir_")]
    assert len(couloirs) == 1
    # Its polygon spans both arms
    from shapely.geometry import Polygon as SP
    poly = SP(couloirs[0].polygon_xy)
    bx0, by0, bx1, by1 = poly.bounds
    assert bx0 < 1.0  # reaches bar west end
    assert by1 > 31.0  # reaches leg north end
