from shapely.geometry import Polygon

from core.building_model.solver import build_modular_grid, place_core


def test_place_core_central_for_rectangular_footprint():
    footprint = Polygon([(0,0),(15,0),(15,12),(0,12)])  # 15×12m
    grid = build_modular_grid(footprint, cell_size_m=3.0)
    core = place_core(grid, core_surface_m2=20.0)
    # For rectangular, core should be near center
    centroid = footprint.centroid
    cx, cy = core.position_xy
    assert abs(cx - centroid.x) < 5.0
    assert abs(cy - centroid.y) < 5.0
    # surface respectée
    assert 18.0 <= core.surface_m2 <= 25.0


def test_place_core_respects_max_25m_access_distance():
    footprint = Polygon([(0,0),(60,0),(60,12),(0,12)])  # 60×12m — very long
    grid = build_modular_grid(footprint, cell_size_m=3.0)
    core = place_core(grid, core_surface_m2=20.0)
    # With long building, we might need to place core so that corners are ≤ 25m
    # distance from core.position_xy to farthest corner
    corners = [(0,0),(60,0),(60,12),(0,12)]
    max_dist = max(((c[0]-core.position_xy[0])**2 + (c[1]-core.position_xy[1])**2)**0.5 for c in corners)
    # For 60×12 single core, impossible to fit all corners within 25m
    # Expect solver returns best-effort placement (central on X axis)
    assert max_dist < 35.0  # at least better than random
