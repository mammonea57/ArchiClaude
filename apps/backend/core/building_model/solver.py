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


def _compute_circulation_network(
    footprint: ShapelyPolygon,
    wings: list[ShapelyPolygon],
    core: "CorePlacement",
) -> ShapelyPolygon:
    """Union of the core + every wing corridor + connectors core↔corridor.

    Apartment slot polygons are cut by this network so they never overlap
    the circulation area visually or functionally. Must stay in sync with
    pipeline._emit_wing_corridors.
    """
    from shapely.ops import unary_union

    corridor_width = 1.6
    half = corridor_width / 2
    cx, cy = core.position_xy
    core_bb = core.polygon.bounds

    polys = [core.polygon]
    DUAL_THRESHOLD = 15.0
    for wing in wings:
        wxmin, wymin, wxmax, wymax = wing.bounds
        ww = wxmax - wxmin
        wh = wymax - wymin
        perp = wh if ww >= wh else ww
        # Only wings deep enough to host dual-loaded apts get a central corridor.
        # Shallower wings are single-loaded; their palier is the wing edge
        # itself (no dedicated corridor needed, apts open directly onto the
        # palier/landing).
        if perp < DUAL_THRESHOLD:
            continue
        if ww >= wh:
            cy_mid = (wymin + wymax) / 2
            corridor = ShapelyPolygon([
                (wxmin, cy_mid - half), (wxmax, cy_mid - half),
                (wxmax, cy_mid + half), (wxmin, cy_mid + half),
            ])
            axis = "horizontal"
        else:
            cx_mid = (wxmin + wxmax) / 2
            corridor = ShapelyPolygon([
                (cx_mid - half, wymin), (cx_mid + half, wymin),
                (cx_mid + half, wymax), (cx_mid - half, wymax),
            ])
            axis = "vertical"

        # Connector from corridor to core if they don't already overlap
        if corridor.distance(core.polygon) > 0.2:
            cxmin, cymin, cxmax, cymax = corridor.bounds
            if axis == "horizontal":
                # Vertical connector at corridor's mid-x, between core and corridor
                connector_x = max(core_bb[0], min(core_bb[2], (cxmin + cxmax) / 2))
                if cymin > core_bb[3]:
                    y0 = core_bb[3]; y1 = cymin
                elif cymax < core_bb[1]:
                    y0 = cymax; y1 = core_bb[1]
                else:
                    y0 = core_bb[3]; y1 = cymax
                connector = ShapelyPolygon([
                    (connector_x - half, min(y0, y1)), (connector_x + half, min(y0, y1)),
                    (connector_x + half, max(y0, y1)), (connector_x - half, max(y0, y1)),
                ])
            else:
                # Horizontal connector at core's Y level
                if cxmin > core_bb[2]:
                    x0, x1 = core_bb[2], (cxmin + cxmax) / 2 + half
                elif cxmax < core_bb[0]:
                    x0, x1 = (cxmin + cxmax) / 2 - half, core_bb[0]
                else:
                    x0, x1 = core_bb[2], (cxmin + cxmax) / 2 + half
                connector = ShapelyPolygon([
                    (min(x0, x1), cy - half), (max(x0, x1), cy - half),
                    (max(x0, x1), cy + half), (min(x0, x1), cy + half),
                ])
            polys.append(connector.intersection(footprint))
        polys.append(corridor.intersection(footprint))

    network = unary_union(polys)
    return network


def _find_reflex_vertex(footprint: ShapelyPolygon) -> tuple[float, float] | None:
    """Return the concave (reflex) vertex of the footprint if any.

    For an L-shape this is the inner corner — the ideal spot for the
    common core because corridors can extend into both wings from here.
    Returns None for convex footprints (rectangles, etc.).
    """
    coords = list(footprint.exterior.coords)[:-1]
    n = len(coords)
    if n < 5:
        return None
    for i in range(n):
        p_prev = coords[(i - 1) % n]
        p = coords[i]
        p_next = coords[(i + 1) % n]
        # Cross product of (prev→curr) × (curr→next)
        v1 = (p[0] - p_prev[0], p[1] - p_prev[1])
        v2 = (p_next[0] - p[0], p_next[1] - p[1])
        cross = v1[0] * v2[1] - v1[1] * v2[0]
        # For a counter-clockwise-wound polygon, a negative cross is a reflex
        # vertex. Shapely normalizes polygons to CCW so this should hold.
        if cross < -0.01:
            return (p[0], p[1])
    return None


def place_core(grid: ModularGrid, core_surface_m2: float) -> CorePlacement:
    """Place core (stairs + elevator + shafts) so every wing of an L/T/U
    footprint can be reached from it via a short corridor.

    Strategy:
    - For L-shaped footprints, place the core adjacent to the reflex
      (inner corner) vertex. Corridors then extend along BOTH wings
      from this inner-corner position, giving every apartment access
      to the stairs/elevator without crossing another apartment.
    - For convex (rectangular) footprints, fall back to the original
      grid-search minimax to keep the core roughly central.
    """
    if grid.footprint is None:
        raise ValueError("grid.footprint is None")

    side = (core_surface_m2 ** 0.5)
    reflex = _find_reflex_vertex(grid.footprint)
    if reflex is not None:
        rx, ry = reflex
        # Offset the core INWARD from the reflex vertex. The inward direction
        # is toward the centroid of the footprint.
        centroid = grid.footprint.centroid
        dx = centroid.x - rx
        dy = centroid.y - ry
        mag = max(0.01, (dx * dx + dy * dy) ** 0.5)
        ux, uy = dx / mag, dy / mag
        # Push the core so its near corner is ~0.5 m inside the reflex
        offset = side / 2 + 0.5
        ccx = rx + ux * offset
        ccy = ry + uy * offset
        core_poly = ShapelyPolygon([
            (ccx - side / 2, ccy - side / 2), (ccx + side / 2, ccy - side / 2),
            (ccx + side / 2, ccy + side / 2), (ccx - side / 2, ccy + side / 2),
        ])
        if core_poly.within(grid.footprint.buffer(0.1)):
            return CorePlacement(
                position_xy=(ccx, ccy),
                polygon=core_poly,
                surface_m2=core_surface_m2,
            )
        # else fall through to minimax if reflex-based placement lands outside

    # Convex / fallback: minimax distance to all corners
    corners = list(grid.footprint.exterior.coords)[:-1]
    best: tuple[float, GridCell | None] = (float("inf"), None)
    for cell in grid.cells:
        ccx, ccy = cell.polygon.centroid.x, cell.polygon.centroid.y
        max_dist = max(((cx - ccx) ** 2 + (cy - ccy) ** 2) ** 0.5 for cx, cy in corners)
        if max_dist < best[0]:
            best = (max_dist, cell)
    if best[1] is None:
        raise ValueError("no grid cells available to place core")

    ccx, ccy = best[1].polygon.centroid.x, best[1].polygon.centroid.y
    core_poly = ShapelyPolygon([
        (ccx - side / 2, ccy - side / 2), (ccx + side / 2, ccy - side / 2),
        (ccx + side / 2, ccy + side / 2), (ccx - side / 2, ccy + side / 2),
    ])
    return CorePlacement(
        position_xy=(ccx, ccy),
        polygon=core_poly,
        surface_m2=core_surface_m2,
    )


# Typology size hierarchy — strict T2 < T3 < T4 < T5 per user spec.
# T3 ≤ 60 m² target; T4 starts at 70+ m² (never smaller than a T3).
_TYPO_TARGET_SURFACE_M2 = {
    Typologie.STUDIO: 22.0,
    Typologie.T1: 32.0,
    Typologie.T2: 48.0,
    Typologie.T3: 58.0,   # user: T3 entre 55 et 60 m²
    Typologie.T4: 78.0,   # must be > T3 max
    Typologie.T5: 100.0,  # must be > T4 max
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

    # Pre-compute the expected circulation network (corridors + core +
    # core↔corridor connectors) so apt slots can be cut away from it.
    # This guarantees apts never overlap the stairs, lift, or corridors.
    circulation_network = _compute_circulation_network(grid.footprint, wings, core)

    slots: list[ApartmentSlot] = []
    slot_idx = 0

    _CORRIDOR_WIDTH_M = 1.6   # minimum PMR corridor
    # Dual-loaded splits a wing into two rows of apts (≥7 m deep each) plus a
    # 1.6 m corridor in between. Threshold = 2×7 + 1.6 ≈ 15 m. Shallower wings
    # use a single-loaded corridor (one row, corridor on one side).
    _DUAL_LOADED_THRESHOLD_M = 15.0

    for wing_outer in wings:
        wxmin_o, wymin_o, wxmax_o, wymax_o = wing_outer.bounds
        wing_w_o = wxmax_o - wxmin_o
        wing_h_o = wymax_o - wymin_o

        # Dual-loaded corridor: if the perpendicular span exceeds
        # _DUAL_LOADED_THRESHOLD_M, split the wing into two parallel strips
        # (north + south, or east + west) separated by a central corridor so
        # apartments land at architect-appropriate depths on both sides.
        slice_x_outer = wing_w_o >= wing_h_o
        perp_outer = wing_h_o if slice_x_outer else wing_w_o

        if perp_outer > _DUAL_LOADED_THRESHOLD_M:
            half = (perp_outer - _CORRIDOR_WIDTH_M) / 2
            if slice_x_outer:
                # Corridor is horizontal in the middle of the wing
                sub_wings = [
                    ShapelyPolygon([
                        (wxmin_o, wymin_o), (wxmax_o, wymin_o),
                        (wxmax_o, wymin_o + half), (wxmin_o, wymin_o + half),
                    ]),
                    ShapelyPolygon([
                        (wxmin_o, wymax_o - half), (wxmax_o, wymax_o - half),
                        (wxmax_o, wymax_o), (wxmin_o, wymax_o),
                    ]),
                ]
            else:
                sub_wings = [
                    ShapelyPolygon([
                        (wxmin_o, wymin_o), (wxmin_o + half, wymin_o),
                        (wxmin_o + half, wymax_o), (wxmin_o, wymax_o),
                    ]),
                    ShapelyPolygon([
                        (wxmax_o - half, wymin_o), (wxmax_o, wymin_o),
                        (wxmax_o, wymax_o), (wxmax_o - half, wymax_o),
                    ]),
                ]
        else:
            sub_wings = [wing_outer]

        # Process each sub-wing (single or dual strip around the corridor)
        for wing in sub_wings:
            wxmin, wymin, wxmax, wymax = wing.bounds
            wing_w = wxmax - wxmin
            wing_h = wymax - wymin

            # Slice along the longer side; apartments span the perpendicular.
            slice_x = wing_w >= wing_h
            slice_length = wing_w if slice_x else wing_h
            perp_length = wing_h if slice_x else wing_w

            # 1. Typologies whose DEPTH range can host this perp_length
            fitting_typos = [
                t for t in mix_norm
                if _TYPO_DIM_RANGE[t][2] * 0.85 <= perp_length <= _TYPO_DIM_RANGE[t][3] * 1.15
            ]
            if not fitting_typos:
                continue

            # 2. Target slot width = smallest fitting typo to pack more apts
            smallest_typo = min(fitting_typos, key=lambda t: typo_surface_targets[t])
            lw_min, lw_max, _ld_min, _ld_max = _TYPO_DIM_RANGE[smallest_typo]
            target_slot_width = (lw_min + lw_max) / 2
            nb_slots_in_wing = max(1, round(slice_length / target_slot_width))
            max_nb = max(1, int(slice_length / (lw_min * 0.85)))
            min_nb = max(1, math.ceil(slice_length / (lw_max * 1.15)))
            nb_slots_in_wing = max(min_nb, min(nb_slots_in_wing, max_nb))
            actual_slot_width = slice_length / nb_slots_in_wing

            # 3. Re-filter candidates against the ACTUAL slot dimensions
            candidates: list[Typologie] = []
            for typo in sorted(mix_norm.keys(), key=lambda t: -mix_norm[t]):
                wmin, wmax, dmin, dmax = _TYPO_DIM_RANGE[typo]
                if (wmin * 0.85 <= actual_slot_width <= wmax * 1.15
                        and dmin * 0.85 <= perp_length <= dmax * 1.15):
                    candidates.append(typo)
            if not candidates:
                candidates = [smallest_typo]

            # 4. Distribute slots across candidates proportional to mix
            wing_typos: list[Typologie] = []
            total_cand_ratio = sum(mix_norm[t] for t in candidates)
            for typo in candidates:
                share = round(nb_slots_in_wing * mix_norm[typo] / total_cand_ratio)
                wing_typos.extend([typo] * max(0, share))
            if len(wing_typos) < nb_slots_in_wing:
                wing_typos.extend([candidates[0]] * (nb_slots_in_wing - len(wing_typos)))
            wing_typos = wing_typos[:nb_slots_in_wing]

            def _finalise_slot(slot_poly: ShapelyPolygon) -> ShapelyPolygon | None:
                """Clip slot to footprint AND subtract circulation network."""
                clipped = slot_poly.intersection(grid.footprint)
                if clipped.is_empty:
                    return None
                clipped = clipped.difference(circulation_network)
                if clipped.is_empty or clipped.area < 20:
                    return None
                if clipped.geom_type == "MultiPolygon":
                    clipped = max(clipped.geoms, key=lambda g: g.area)
                return clipped

            n = len(wing_typos)
            if slice_x:
                slot_w = wing_w / n
                for i, typo in enumerate(wing_typos):
                    x_cursor = wxmin + i * slot_w
                    rect = ShapelyPolygon([
                        (x_cursor, wymin), (x_cursor + slot_w, wymin),
                        (x_cursor + slot_w, wymax), (x_cursor, wymax),
                    ])
                    slot_poly = _finalise_slot(rect)
                    if slot_poly is None:
                        continue
                    orientations = _infer_orientations(slot_poly, grid.footprint, voirie_side)
                    position = _infer_position(i, n)
                    final_typo = _reclassify_by_surface(slot_poly.area, typo)
                    slots.append(ApartmentSlot(
                        id=f"slot_{slot_idx}", polygon=slot_poly, surface_m2=slot_poly.area,
                        target_typologie=final_typo, orientations=orientations,
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
                    slot_poly = _finalise_slot(rect)
                    if slot_poly is None:
                        continue
                    orientations = _infer_orientations(slot_poly, grid.footprint, voirie_side)
                    position = _infer_position(i, n)
                    final_typo = _reclassify_by_surface(slot_poly.area, typo)
                    slots.append(ApartmentSlot(
                        id=f"slot_{slot_idx}", polygon=slot_poly, surface_m2=slot_poly.area,
                        target_typologie=final_typo, orientations=orientations,
                        position_in_floor=position,
                    ))
                    slot_idx += 1

    return slots


# Width × depth ranges per typology. Allow some depth overlap between typos
# since depth is set by the wing and apts of multiple typologies live in
# similar wings; strict ordering is enforced by _TYPO_SURFACE_RANGE below.
_TYPO_DIM_RANGE: dict[Typologie, tuple[float, float, float, float]] = {
    Typologie.STUDIO: (4.0, 5.5, 5.5, 8.0),
    Typologie.T1:     (4.5, 6.0, 6.0, 9.0),
    Typologie.T2:     (5.8, 7.2, 7.0, 11.0),
    Typologie.T3:     (7.0, 8.5, 7.5, 12.0),
    Typologie.T4:     (8.0, 10.5, 8.0, 12.0),
    Typologie.T5:     (9.5, 12.0, 10.0, 13.0),
}

# Strict surface hierarchy — T2 < T3 < T4 < T5. Any slot outside these bounds
# for a given typology is re-labelled to the correct typo.
_TYPO_SURFACE_RANGE: dict[Typologie, tuple[float, float]] = {
    Typologie.STUDIO: (18.0, 32.0),
    Typologie.T1:     (28.0, 42.0),
    Typologie.T2:     (42.0, 52.0),
    Typologie.T3:     (52.0, 65.0),   # user: ≤60 m²
    Typologie.T4:     (65.0, 90.0),   # > T3 max
    Typologie.T5:     (90.0, 120.0),  # > T4 max
}


def _reclassify_by_surface(surface_m2: float, hint: Typologie) -> Typologie:
    """Pick the typology whose surface range contains the slot area.
    Falls back to the hint when no range matches (e.g. huge slot)."""
    for typo, (lo, hi) in _TYPO_SURFACE_RANGE.items():
        if lo <= surface_m2 < hi:
            return typo
    return hint


def _infer_orientations(slot_poly: ShapelyPolygon, footprint: ShapelyPolygon, voirie_side: str) -> list[str]:
    """Infer which cardinal sides of the slot face the EXTERIOR.

    Tests each of the slot's four sides against the footprint's polygon
    boundary (not just the bbox). Handles non-convex footprints (L, T, U):
    interior strips in dual-loaded corridors pick up the cœur-d'îlot side
    correctly.
    """
    from shapely.geometry import Point

    s_minx, s_miny, s_maxx, s_maxy = slot_poly.bounds
    boundary = footprint.boundary
    threshold = 0.3
    sides = {
        "sud":   [((s_minx + s_maxx) / 2, s_miny),
                  (s_minx + 0.25 * (s_maxx - s_minx), s_miny),
                  (s_minx + 0.75 * (s_maxx - s_minx), s_miny)],
        "nord":  [((s_minx + s_maxx) / 2, s_maxy),
                  (s_minx + 0.25 * (s_maxx - s_minx), s_maxy),
                  (s_minx + 0.75 * (s_maxx - s_minx), s_maxy)],
        "ouest": [(s_minx, (s_miny + s_maxy) / 2),
                  (s_minx, s_miny + 0.25 * (s_maxy - s_miny)),
                  (s_minx, s_miny + 0.75 * (s_maxy - s_miny))],
        "est":   [(s_maxx, (s_miny + s_maxy) / 2),
                  (s_maxx, s_miny + 0.25 * (s_maxy - s_miny)),
                  (s_maxx, s_miny + 0.75 * (s_maxy - s_miny))],
    }
    orientations: list[str] = []
    for name, pts in sides.items():
        if any(Point(px, py).distance(boundary) < threshold for (px, py) in pts):
            orientations.append(name)
    _ = voirie_side
    return orientations


def _infer_position(idx: int, total: int) -> str:
    if total <= 1:
        return "milieu"
    if idx == 0 or idx == total - 1:
        return "angle" if total >= 3 else "extremite"
    return "milieu"
