"""Structural solver: modular grid, core placement, apartment slots.

Deterministic Python pipeline producing a StructuralGrid from footprint+rules.
Used upstream of template selection.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import Polygon as ShapelyPolygon


@dataclass
class GridCell:
    col: int
    row: int
    polygon: ShapelyPolygon
    on_voirie: bool = False


@dataclass
class ModularGrid:
    cell_size_m: float
    columns: int
    rows: int
    cells: list[GridCell] = field(default_factory=list)
    footprint: ShapelyPolygon | None = None


def build_modular_grid(footprint: ShapelyPolygon, cell_size_m: float = 3.0) -> ModularGrid:
    """Overlay a cell_size×cell_size grid on footprint bounds."""
    minx, miny, maxx, maxy = footprint.bounds
    width = maxx - minx
    height = maxy - miny
    columns = max(1, int(round(width / cell_size_m)))
    rows = max(1, int(round(height / cell_size_m)))

    cells: list[GridCell] = []
    for row in range(rows):
        for col in range(columns):
            x0 = minx + col * cell_size_m
            y0 = miny + row * cell_size_m
            cell_poly = ShapelyPolygon([
                (x0, y0), (x0 + cell_size_m, y0),
                (x0 + cell_size_m, y0 + cell_size_m), (x0, y0 + cell_size_m),
            ])
            # Only include cells that overlap footprint substantially
            if cell_poly.intersection(footprint).area >= 0.5 * cell_poly.area:
                cells.append(GridCell(col=col, row=row, polygon=cell_poly))

    return ModularGrid(
        cell_size_m=cell_size_m, columns=columns, rows=rows,
        cells=cells, footprint=footprint,
    )


def classify_cells(grid: ModularGrid, voirie_side: str) -> ModularGrid:
    """Mark cells as on_voirie based on footprint edge touching voirie."""
    minx, miny, maxx, maxy = grid.footprint.bounds
    threshold_m = grid.cell_size_m  # 1 cell depth classified voirie

    for cell in grid.cells:
        ccx, ccy = cell.polygon.centroid.x, cell.polygon.centroid.y
        if voirie_side == "nord" and ccy >= maxy - threshold_m:
            cell.on_voirie = True
        elif voirie_side == "sud" and ccy <= miny + threshold_m:
            cell.on_voirie = True
        elif voirie_side == "est" and ccx >= maxx - threshold_m:
            cell.on_voirie = True
        elif voirie_side == "ouest" and ccx <= minx + threshold_m:
            cell.on_voirie = True

    return grid
