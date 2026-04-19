"""Structural solver: modular grid, core placement, apartment slots.

Deterministic Python pipeline producing a StructuralGrid from footprint+rules.
Used upstream of template selection.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from shapely.geometry import Polygon as ShapelyPolygon

from core.building_model.schemas import Typologie


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
        if voirie_side == "nord" and ccy >= maxy - threshold_m or voirie_side == "sud" and ccy <= miny + threshold_m or voirie_side == "est" and ccx >= maxx - threshold_m or voirie_side == "ouest" and ccx <= minx + threshold_m:
            cell.on_voirie = True

    return grid



@dataclass
class CorePlacement:
    position_xy: tuple[float, float]
    polygon: ShapelyPolygon
    surface_m2: float


_INCENDIE_DIST_MAX_M = 25.0
_CORE_ASPECT_MIN_LW = 0.6  # core cabine 1.1×1.4 ~ 0.7 aspect min


def place_core(grid: ModularGrid, core_surface_m2: float) -> CorePlacement:
    """Place core (stairs + elevator + shafts) optimally to minimise circulation waste.

    Uses a simple grid search: try each grid cell as center, score = max distance
    to all footprint corners. Pick minimum.
    """
    if grid.footprint is None:
        raise ValueError("grid.footprint is None")
    corners = list(grid.footprint.exterior.coords)[:-1]
    best: tuple[float, GridCell | None] = (float("inf"), None)
    for cell in grid.cells:
        ccx, ccy = cell.polygon.centroid.x, cell.polygon.centroid.y
        max_dist = max(((cx-ccx)**2 + (cy-ccy)**2) ** 0.5 for cx, cy in corners)
        if max_dist < best[0]:
            best = (max_dist, cell)
    if best[1] is None:
        raise ValueError("no grid cells available to place core")

    ccx, ccy = best[1].polygon.centroid.x, best[1].polygon.centroid.y
    # Core spans roughly sqrt(surface) × sqrt(surface) ~ 4.5 × 4.5 for 20m²
    side = (core_surface_m2 ** 0.5)
    core_poly = ShapelyPolygon([
        (ccx - side/2, ccy - side/2), (ccx + side/2, ccy - side/2),
        (ccx + side/2, ccy + side/2), (ccx - side/2, ccy + side/2),
    ])
    return CorePlacement(
        position_xy=(ccx, ccy),
        polygon=core_poly,
        surface_m2=core_surface_m2,
    )


_TYPO_TARGET_SURFACE_M2 = {
    Typologie.STUDIO: 22.0,
    Typologie.T1: 32.0,
    Typologie.T2: 48.0,
    Typologie.T3: 68.0,
    Typologie.T4: 85.0,
    Typologie.T5: 108.0,
}


@dataclass
class ApartmentSlot:
    id: str
    polygon: ShapelyPolygon
    surface_m2: float
    target_typologie: Typologie
    orientations: list[str]
    position_in_floor: str  # "angle" | "milieu" | "extremite"


def compute_apartment_slots(
    grid: ModularGrid,
    core: CorePlacement,
    mix_typologique: dict[Typologie, float],
    voirie_side: str,
) -> list[ApartmentSlot]:
    """Divide footprint minus core minus circulation into slots per mix."""
    if grid.footprint is None:
        raise ValueError("grid.footprint is None")

    # Subtract core from footprint
    usable = grid.footprint.difference(core.polygon.buffer(1.4))  # +1.4m circulation
    usable_area = usable.area

    # Normalise mix (should sum to ~1.0)
    total_ratio = sum(mix_typologique.values())
    mix_norm = {k: v / total_ratio for k, v in mix_typologique.items()}

    # Compute target surfaces per typo
    typo_surface_targets = {t: _TYPO_TARGET_SURFACE_M2[t] for t in mix_norm}

    # Average apartment surface
    avg_surface = sum(mix_norm[t] * typo_surface_targets[t] for t in mix_norm)
    nb_apartments = max(1, int(usable_area / avg_surface))

    # Distribute typologies according to mix
    typos_expanded: list[Typologie] = []
    for typo, ratio in mix_norm.items():
        n = max(1, round(nb_apartments * ratio))
        typos_expanded.extend([typo] * n)
    # Keep at least one slot per distinct typo in the mix
    min_slots = len(mix_typologique)
    typos_expanded = typos_expanded[:max(nb_apartments, min_slots)]

    # Strip-divide usable area along longest axis, assign a typo to each strip
    minx, miny, maxx, maxy = usable.bounds
    width = maxx - minx
    height = maxy - miny

    slots: list[ApartmentSlot] = []
    if width >= height:
        # Slice along X
        total_surface = sum(typo_surface_targets[t] for t in typos_expanded)
        x_cursor = minx
        for i, typo in enumerate(typos_expanded):
            slot_w = width * (typo_surface_targets[typo] / total_surface)
            slot_poly = ShapelyPolygon([
                (x_cursor, miny), (x_cursor + slot_w, miny),
                (x_cursor + slot_w, maxy), (x_cursor, maxy),
            ]).intersection(usable)
            orientations = _infer_orientations(slot_poly, grid.footprint, voirie_side)
            position = _infer_position(i, len(typos_expanded))
            slots.append(ApartmentSlot(
                id=f"slot_{i}", polygon=slot_poly, surface_m2=slot_poly.area,
                target_typologie=typo, orientations=orientations,
                position_in_floor=position,
            ))
            x_cursor += slot_w
    else:
        # Slice along Y
        total_surface = sum(typo_surface_targets[t] for t in typos_expanded)
        y_cursor = miny
        for i, typo in enumerate(typos_expanded):
            slot_h = height * (typo_surface_targets[typo] / total_surface)
            slot_poly = ShapelyPolygon([
                (minx, y_cursor), (maxx, y_cursor),
                (maxx, y_cursor + slot_h), (minx, y_cursor + slot_h),
            ]).intersection(usable)
            orientations = _infer_orientations(slot_poly, grid.footprint, voirie_side)
            position = _infer_position(i, len(typos_expanded))
            slots.append(ApartmentSlot(
                id=f"slot_{i}", polygon=slot_poly, surface_m2=slot_poly.area,
                target_typologie=typo, orientations=orientations,
                position_in_floor=position,
            ))
            y_cursor += slot_h

    return slots


def _infer_orientations(slot_poly: ShapelyPolygon, footprint: ShapelyPolygon, voirie_side: str) -> list[str]:
    """Infer which cardinal sides the slot faces."""
    minx, miny, maxx, maxy = footprint.bounds
    s_minx, s_miny, s_maxx, s_maxy = slot_poly.bounds
    threshold = 0.5  # 50cm tolerance
    orientations = []
    if abs(s_miny - miny) < threshold:
        orientations.append("sud")
    if abs(s_maxy - maxy) < threshold:
        orientations.append("nord")
    if abs(s_minx - minx) < threshold:
        orientations.append("ouest")
    if abs(s_maxx - maxx) < threshold:
        orientations.append("est")
    return orientations


def _infer_position(idx: int, total: int) -> str:
    if total <= 1:
        return "milieu"
    if idx == 0 or idx == total - 1:
        return "angle" if total >= 3 else "extremite"
    return "milieu"
