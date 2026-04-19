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


def _decompose_into_wings(footprint: ShapelyPolygon) -> list[ShapelyPolygon]:
    """Split an L / T / cross footprint into rectangular wings.

    Greedy axis-aligned decomposition: iteratively carve the largest
    bounding rectangle from the footprint until only slivers remain.
    For a simple rectangular footprint returns [footprint]. For an L
    returns 2 rectangles that union to the L. Works for axis-aligned
    polygons with right-angle corners (typical cadastral shapes).
    """
    remaining = footprint
    wings: list[ShapelyPolygon] = []
    safety = 10
    while remaining.area > 1.0 and safety > 0:
        safety -= 1
        minx, miny, maxx, maxy = remaining.bounds
        # Try both axis slices: horizontal sweep + vertical sweep, pick whichever
        # yields the largest fully-contained rectangle.
        best_rect: ShapelyPolygon | None = None
        best_area = 0.0
        # Vertical strips: find longest horizontal strip of full footprint height
        step = 0.5
        x = minx
        while x < maxx:
            x2 = x + step
            # Strip from x to x2, full y range, intersected with remaining
            strip = ShapelyPolygon([(x, miny), (x2, miny), (x2, maxy), (x, maxy)]).intersection(remaining)
            # Extend x2 as long as strip is a clean rectangle (no reflex)
            while x2 + step <= maxx:
                next_strip = ShapelyPolygon(
                    [(x, miny), (x2 + step, miny), (x2 + step, maxy), (x, maxy)]
                ).intersection(remaining)
                if _is_rectangle(next_strip, tol=0.5):
                    strip = next_strip
                    x2 += step
                else:
                    break
            if _is_rectangle(strip, tol=0.5) and strip.area > best_area:
                # Fit strip to its own minimal bbox
                sxmin, symin, sxmax, symax = strip.bounds
                rect = ShapelyPolygon([(sxmin, symin), (sxmax, symin), (sxmax, symax), (sxmin, symax)])
                if rect.within(remaining.buffer(0.01)):
                    best_rect = rect
                    best_area = rect.area
            x = x2 if x2 > x else x + step

        # Horizontal strips for the other axis
        y = miny
        while y < maxy:
            y2 = y + step
            strip = ShapelyPolygon([(minx, y), (maxx, y), (maxx, y2), (minx, y2)]).intersection(remaining)
            while y2 + step <= maxy:
                next_strip = ShapelyPolygon(
                    [(minx, y), (maxx, y), (maxx, y2 + step), (minx, y2 + step)]
                ).intersection(remaining)
                if _is_rectangle(next_strip, tol=0.5):
                    strip = next_strip
                    y2 += step
                else:
                    break
            if _is_rectangle(strip, tol=0.5) and strip.area > best_area:
                sxmin, symin, sxmax, symax = strip.bounds
                rect = ShapelyPolygon([(sxmin, symin), (sxmax, symin), (sxmax, symax), (sxmin, symax)])
                if rect.within(remaining.buffer(0.01)):
                    best_rect = rect
                    best_area = rect.area
            y = y2 if y2 > y else y + step

        if best_rect is None or best_area < 1.0:
            break
        wings.append(best_rect)
        remaining = remaining.difference(best_rect.buffer(0.001))
        if remaining.geom_type == "MultiPolygon":
            # Keep working on the biggest piece
            remaining = max(remaining.geoms, key=lambda g: g.area)

    return wings or [footprint]


def _is_rectangle(poly: ShapelyPolygon, tol: float = 0.5) -> bool:
    """Is this polygon close to a rectangle (= bbox area ≈ polygon area)?"""
    if poly.is_empty or poly.geom_type != "Polygon":
        return False
    minx, miny, maxx, maxy = poly.bounds
    bbox_area = (maxx - minx) * (maxy - miny)
    if bbox_area <= 0:
        return False
    return abs(bbox_area - poly.area) < tol


def compute_apartment_slots(
    grid: ModularGrid,
    core: CorePlacement,
    mix_typologique: dict[Typologie, float],
    voirie_side: str,
) -> list[ApartmentSlot]:
    """Divide footprint into slots per mix.

    For rectangular footprints: slice the whole footprint along its longer
    axis. For L-shaped / non-convex footprints: decompose into rectangular
    wings and slice each wing independently, so a mairie-compliant corner
    building (L-shape at the angle of two streets) produces coherent
    apartments on both arms.
    """
    if grid.footprint is None:
        raise ValueError("grid.footprint is None")

    # Compute usable area (footprint minus core + 1.4m palier) only for
    # apartment count sizing. Slot polygons themselves stay as clean
    # rectangles — the core + circulation are drawn as separate niveau
    # elements so the plan renderer gets regular apartment shapes.
    usable = grid.footprint.difference(core.polygon.buffer(1.4))
    usable_area = usable.area

    # Drop typologies with ratio <= 0 — they don't belong in the programme and
    # would otherwise inflate min_slots and produce unplaceable narrow strips.
    active_mix = {k: v for k, v in mix_typologique.items() if v > 0}
    if not active_mix:
        return []

    # Normalise mix (should sum to ~1.0)
    total_ratio = sum(active_mix.values())
    mix_norm = {k: v / total_ratio for k, v in active_mix.items()}

    # Compute target surfaces per typo
    typo_surface_targets = {t: _TYPO_TARGET_SURFACE_M2[t] for t in mix_norm}

    # Average apartment surface
    avg_surface = sum(mix_norm[t] * typo_surface_targets[t] for t in mix_norm)
    # Round up so we don't under-pack — adapter will reject slots that are
    # genuinely too narrow. Better to try more slots than leave the footprint
    # underutilized.
    import math
    nb_apartments = max(1, math.ceil(usable_area / avg_surface))

    # Distribute typologies according to mix
    typos_expanded: list[Typologie] = []
    for typo, ratio in mix_norm.items():
        n = max(1, round(nb_apartments * ratio))
        typos_expanded.extend([typo] * n)
    # Keep at least one slot per distinct active typo
    min_slots = len(active_mix)
    typos_expanded = typos_expanded[:max(nb_apartments, min_slots)]

    # Decompose footprint into rectangular wings (1 for rectangle, 2+ for L).
    wings = _decompose_into_wings(grid.footprint)

    slots: list[ApartmentSlot] = []
    slot_idx = 0

    for wing in wings:
        wxmin, wymin, wxmax, wymax = wing.bounds
        wing_w = wxmax - wxmin
        wing_h = wymax - wymin

        # Decide slice axis (longer side) and how many slots fit the template
        # depth constraints. Template profondeur ranges are [7, 11.5]m across
        # T1-T5, so a wing depth in that range is what we want. If the wing is
        # deeper than 12m along the slicing axis, we slice MORE strips to make
        # each strip ~8-10m along the slicing direction.
        slice_x = wing_w >= wing_h
        slice_length = wing_w if slice_x else wing_h
        perp_length = wing_h if slice_x else wing_w

        # Pick #slots so each slot's slicing-length ≈ 8m (common apartment width)
        # OR ≈ 10m (apartment depth) depending on wing orientation.
        target_slot_len = 8.5 if perp_length <= 10.5 else 6.8
        nb_slots_in_wing = max(1, round(slice_length / target_slot_len))

        # Pick typologies for this wing based on wing dimensions:
        # - If perp_length ∈ [T4 depth ~9-11.5], can use T4
        # - If ∈ [T3 depth ~8.5-10.5], T3
        # - Else T2
        # Prefer the dominant typo from the active mix that fits.
        candidates: list[Typologie] = []
        for typo, ratio in sorted(mix_norm.items(), key=lambda kv: -kv[1]):
            dim_range = _TYPO_DIM_RANGE.get(typo)
            if dim_range is None:
                continue
            lw_min, lw_max, ld_min, ld_max = dim_range
            slot_width_if = target_slot_len if slice_x else perp_length
            slot_depth_if = perp_length if slice_x else target_slot_len
            if (lw_min * 0.85 <= slot_width_if <= lw_max * 1.15
                    and ld_min * 0.85 <= slot_depth_if <= ld_max * 1.15):
                candidates.append(typo)
        if not candidates:
            # No typo fits — skip this wing
            continue

        # Distribute slots across candidate typologies proportional to mix
        wing_typos: list[Typologie] = []
        total_cand_ratio = sum(mix_norm[t] for t in candidates)
        for typo in candidates:
            share = round(nb_slots_in_wing * mix_norm[typo] / total_cand_ratio)
            wing_typos.extend([typo] * max(0, share))
        # Trim/pad to nb_slots_in_wing
        if len(wing_typos) < nb_slots_in_wing:
            wing_typos.extend([candidates[0]] * (nb_slots_in_wing - len(wing_typos)))
        wing_typos = wing_typos[:nb_slots_in_wing]

        n = len(wing_typos)
        if slice_x:
            slot_w = wing_w / n
            for i, typo in enumerate(wing_typos):
                x_cursor = wxmin + i * slot_w
                rect = ShapelyPolygon([
                    (x_cursor, wymin), (x_cursor + slot_w, wymin),
                    (x_cursor + slot_w, wymax), (x_cursor, wymax),
                ])
                slot_poly = rect.intersection(grid.footprint)
                if slot_poly.is_empty or slot_poly.area < 10:
                    continue
                if slot_poly.geom_type == "MultiPolygon":
                    slot_poly = max(slot_poly.geoms, key=lambda g: g.area)
                orientations = _infer_orientations(slot_poly, grid.footprint, voirie_side)
                position = _infer_position(i, n)
                slots.append(ApartmentSlot(
                    id=f"slot_{slot_idx}", polygon=slot_poly, surface_m2=slot_poly.area,
                    target_typologie=typo, orientations=orientations,
                    position_in_floor=position,
                ))
                slot_idx += 1
        else:
            slot_h = wing_h / n
            for i, typo in enumerate(wing_typos):
                y_cursor = wymin + i * slot_h
                rect = ShapelyPolygon([
                    (wxmin, y_cursor), (wxmax, y_cursor),
                    (wxmax, y_cursor + slot_h), (wxmin, y_cursor + slot_h),
                ])
                slot_poly = rect.intersection(grid.footprint)
                if slot_poly.is_empty or slot_poly.area < 10:
                    continue
                if slot_poly.geom_type == "MultiPolygon":
                    slot_poly = max(slot_poly.geoms, key=lambda g: g.area)
                orientations = _infer_orientations(slot_poly, grid.footprint, voirie_side)
                position = _infer_position(i, n)
                slots.append(ApartmentSlot(
                    id=f"slot_{slot_idx}", polygon=slot_poly, surface_m2=slot_poly.area,
                    target_typologie=typo, orientations=orientations,
                    position_in_floor=position,
                ))
                slot_idx += 1

    return slots


# Width & depth min/max per typology, read from the seed templates to keep
# per-wing candidate selection in sync with the adapter tolerances.
_TYPO_DIM_RANGE: dict[Typologie, tuple[float, float, float, float]] = {
    Typologie.STUDIO: (4.0, 5.5, 5.5, 7.0),
    Typologie.T1: (4.5, 6.0, 6.0, 7.5),
    Typologie.T2: (6.0, 7.5, 7.0, 8.5),
    Typologie.T3: (7.2, 9.0, 8.5, 10.5),
    Typologie.T4: (8.5, 11.0, 9.0, 11.5),
    Typologie.T5: (8.5, 11.0, 9.0, 11.5),  # no T5 seed — use T4 bounds
}


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
