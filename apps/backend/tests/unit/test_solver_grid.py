from shapely.geometry import Polygon

from core.building_model.solver import build_modular_grid, classify_cells


def test_build_modular_grid_rectangular_footprint():
    footprint = Polygon([(0,0),(12,0),(12,9),(0,9)])  # 12×9m
    grid = build_modular_grid(footprint, cell_size_m=3.0)
    # 4 columns × 3 rows = 12 cells
    assert grid.columns == 4
    assert grid.rows == 3
    assert len(grid.cells) == 12
    # Each cell should be 3×3m
    assert all(abs(c.polygon.area - 9.0) < 0.01 for c in grid.cells)


def test_classify_cells_voirie_vs_cour():
    footprint = Polygon([(0,0),(12,0),(12,9),(0,9)])
    grid = build_modular_grid(footprint, cell_size_m=3.0)
    # Voirie au nord (y=9 côté) → cells where y_max >= 8 are voirie-side
    classified = classify_cells(grid, voirie_side="nord")
    voirie_cells = [c for c in classified.cells if c.on_voirie]
    cour_cells = [c for c in classified.cells if not c.on_voirie]
    # Nord = top row → 4 cells
    assert len(voirie_cells) == 4
    assert len(cour_cells) == 8
