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


_CORE_ADJ_MAX_EDGE_LEN = 18.0  # max length along the shared edge


def _core_adjacent_edge(
    wing: ShapelyPolygon, core_bb: tuple[float, float, float, float],
) -> str | None:
    """Return the wing edge ("west"/"east"/"north"/"south") that the core
    protrudes into, or None.

    A wing is "core-adjacent" on side X when the core's bounding box
    intersects the wing's edge X-line (the core sits on or just inside
    the wing from that side). We also cap the edge length: long wings
    (> 22 m along the shared edge) would produce landlocked middle
    slots after 2-column subdivision, so we fall back to the legacy
    central corridor for those.
    """
    wxmin, wymin, wxmax, wymax = wing.bounds
    c_minx, c_miny, c_maxx, c_maxy = core_bb
    wing_w = wxmax - wxmin
    wing_h = wymax - wymin

    # Check each edge. The core must cross the edge's midline AND be
    # close to the wing edge (not centred in the wing interior).
    if wing_h <= _CORE_ADJ_MAX_EDGE_LEN:
        # West edge (x = wxmin): core must span past x=wxmin on its east side
        if c_minx <= wxmin + 0.5 and c_maxx >= wxmin - 0.5 and c_maxx <= wxmin + wing_w * 0.5:
            if c_miny < wymax and c_maxy > wymin:
                return "west"
        if c_maxx >= wxmax - 0.5 and c_minx <= wxmax + 0.5 and c_minx >= wxmax - wing_w * 0.5:
            if c_miny < wymax and c_maxy > wymin:
                return "east"
    if wing_w <= _CORE_ADJ_MAX_EDGE_LEN:
        if c_miny <= wymin + 0.5 and c_maxy >= wymin - 0.5 and c_maxy <= wymin + wing_h * 0.5:
            if c_minx < wxmax and c_maxx > wxmin:
                return "south"
        if c_maxy >= wymax - 0.5 and c_miny <= wymax + 0.5 and c_miny >= wymax - wing_h * 0.5:
            if c_minx < wxmax and c_maxx > wxmin:
                return "north"
    return None


def _compute_circulation_network(
    footprint: ShapelyPolygon,
    wings: list[ShapelyPolygon],
    core: "CorePlacement",
) -> ShapelyPolygon:
    """Union of the core + every wing corridor + connectors core↔corridor.

    Apartment slot polygons are cut by this network so they never overlap
    the circulation area visually or functionally. Must stay in sync with
    pipeline._emit_wing_corridors.

    Wings that share an edge with the core get their corridor placed
    ALONG that shared edge (no connector needed, no apt-carving); this
    maximises usable apt area + removes landlocked slots.
    """
    from shapely.ops import unary_union

    # Topology-aware short-circuit. If the footprint maps to a known
    # handler (currently: L), that handler produced a coherent corridor
    # polygon — use it directly instead of the legacy wing-par-wing
    # reconstruction (which can't represent a continuous L corridor).
    # Keep the result in sync with compute_apartment_slots.
    from core.building_model.layout_dispatcher import classify_footprint_topology
    from core.building_model.layout_l import build_l_corridor, decompose_l

    if classify_footprint_topology(footprint) == "L":
        d = decompose_l(footprint)
        if d is not None:
            l_corridor = build_l_corridor(d, corridor_width=1.6)
            return unary_union([core.polygon, l_corridor])

    corridor_width = 1.6
    half = corridor_width / 2
    cx, cy = core.position_xy
    core_bb = core.polygon.bounds

    polys = [core.polygon]
    DUAL_THRESHOLD = 14.5
    for wing in wings:
        wxmin, wymin, wxmax, wymax = wing.bounds
        ww = wxmax - wxmin
        wh = wymax - wymin
        perp = wh if ww >= wh else ww

        # Core-adjacent corridor: place along the shared edge so it
        # directly touches the core (no connector cutting through apts).
        # When the sub-wing is wide enough to be subdivided (2 columns),
        # we ALSO add a secondary cross-corridor so the OUTER column of
        # apts has direct circulation access (otherwise they'd only be
        # reachable by crossing the inner column).
        adj = _core_adjacent_edge(wing, core_bb)
        if adj is not None:
            if adj == "west":
                corridor = ShapelyPolygon([
                    (wxmin, wymin), (wxmin + corridor_width, wymin),
                    (wxmin + corridor_width, wymax), (wxmin, wymax),
                ])
                sub_perp = ww - corridor_width  # remaining perp across the wing
                secondary_axis = "horizontal"
            elif adj == "east":
                corridor = ShapelyPolygon([
                    (wxmax - corridor_width, wymin), (wxmax, wymin),
                    (wxmax, wymax), (wxmax - corridor_width, wymax),
                ])
                sub_perp = ww - corridor_width
                secondary_axis = "horizontal"
            elif adj == "south":
                corridor = ShapelyPolygon([
                    (wxmin, wymin), (wxmax, wymin),
                    (wxmax, wymin + corridor_width), (wxmin, wymin + corridor_width),
                ])
                sub_perp = wh - corridor_width
                secondary_axis = "vertical"
            else:  # north
                corridor = ShapelyPolygon([
                    (wxmin, wymax - corridor_width), (wxmax, wymax - corridor_width),
                    (wxmax, wymax), (wxmin, wymax),
                ])
                sub_perp = wh - corridor_width
                secondary_axis = "vertical"
            polys.append(corridor.intersection(footprint))
            # Add the secondary cross-corridor when the sub-wing is wide
            # enough to be split in two columns.
            if sub_perp > 10.0:
                if secondary_axis == "horizontal":
                    # Secondary runs horizontally across the sub-wing
                    # (perpendicular to the main vertical corridor).
                    cy_mid_sec = (wymin + wymax) / 2
                    secondary = ShapelyPolygon([
                        (wxmin, cy_mid_sec - half), (wxmax, cy_mid_sec - half),
                        (wxmax, cy_mid_sec + half), (wxmin, cy_mid_sec + half),
                    ])
                else:
                    cx_mid_sec = (wxmin + wxmax) / 2
                    secondary = ShapelyPolygon([
                        (cx_mid_sec - half, wymin), (cx_mid_sec + half, wymin),
                        (cx_mid_sec + half, wymax), (cx_mid_sec - half, wymax),
                    ])
                polys.append(secondary.intersection(footprint))
            continue

        # Non-adjacent wing: always emit a corridor, plus a connector
        # linking it to the core. Mirror pipeline._emit_wing_corridors so
        # the solver's pre-clip matches what pipeline actually draws.
        wing_long_horizontal = ww >= wh
        is_dual = perp >= DUAL_THRESHOLD
        if wing_long_horizontal:
            axis = "horizontal"
            if is_dual:
                cy_axis = (wymin + wymax) / 2
            else:
                cy_axis = wymax - half if cy > (wymin + wymax) / 2 else wymin + half
            corridor = ShapelyPolygon([
                (wxmin, cy_axis - half), (wxmax, cy_axis - half),
                (wxmax, cy_axis + half), (wxmin, cy_axis + half),
            ])
        else:
            axis = "vertical"
            if is_dual:
                cx_axis = (wxmin + wxmax) / 2
            else:
                cx_axis = wxmax - half if cx > (wxmin + wxmax) / 2 else wxmin + half
            corridor = ShapelyPolygon([
                (cx_axis - half, wymin), (cx_axis + half, wymin),
                (cx_axis + half, wymax), (cx_axis - half, wymax),
            ])

        corridor_clipped = corridor.intersection(footprint)
        if corridor_clipped.distance(core.polygon) > 0.2:
            cxmin, cymin, cxmax, cymax = corridor_clipped.bounds
            if axis == "horizontal":
                x_lo = max(cxmin, core_bb[0])
                x_hi = min(cxmax, core_bb[2])
                if x_lo < x_hi:
                    clo, chi = x_lo, x_hi
                else:
                    mid = max(core_bb[0], min(core_bb[2], (cxmin + cxmax) / 2))
                    clo, chi = mid - half, mid + half
                y_lo = min(cymin, core_bb[1])
                y_hi = max(cymax, core_bb[3])
                connector = ShapelyPolygon([
                    (clo, y_lo), (chi, y_lo), (chi, y_hi), (clo, y_hi),
                ])
            else:
                y_lo = max(cymin, core_bb[1])
                y_hi = min(cymax, core_bb[3])
                if y_lo < y_hi:
                    clo, chi = y_lo, y_hi
                else:
                    mid = max(core_bb[1], min(core_bb[3], (cymin + cymax) / 2))
                    clo, chi = mid - half, mid + half
                x_lo = min(cxmin, core_bb[0])
                x_hi = max(cxmax, core_bb[2])
                connector = ShapelyPolygon([
                    (x_lo, clo), (x_hi, clo), (x_hi, chi), (x_lo, chi),
                ])
            polys.append(connector.intersection(footprint))
        polys.append(corridor_clipped)

    network = unary_union(polys)
    return network


def _find_reflex_vertex(footprint: ShapelyPolygon) -> tuple[float, float] | None:
    """Return the concave (reflex) vertex of the footprint if any.

    For an L-shape this is the inner corner — the ideal spot for the
    common core because corridors can extend into both wings from here.
    Returns None for convex footprints (rectangles, etc.).

    Orients the polygon CCW first so the cross-product sign convention
    holds regardless of how shapely stored the ring.
    """
    if footprint.is_empty or footprint.geom_type != "Polygon":
        return None
    coords = list(footprint.exterior.coords)[:-1]
    n = len(coords)
    if n < 5:
        return None
    # Normalise to CCW (interior on the left of each edge)
    if not footprint.exterior.is_ccw:
        coords = coords[::-1]
        n = len(coords)
    for i in range(n):
        p_prev = coords[(i - 1) % n]
        p = coords[i]
        p_next = coords[(i + 1) % n]
        v1 = (p[0] - p_prev[0], p[1] - p_prev[1])
        v2 = (p_next[0] - p[0], p_next[1] - p[1])
        cross = v1[0] * v2[1] - v1[1] * v2[0]
        if cross < -0.5:
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

    # Topology-aware: L footprints get the core at the corridor elbow so
    # downstream dispatcher-driven slot generation lines up with the
    # caller's core. Matches layout_l.place_core_at_elbow exactly.
    from core.building_model.layout_dispatcher import classify_footprint_topology
    from core.building_model.layout_l import decompose_l, place_core_at_elbow

    if classify_footprint_topology(grid.footprint) == "L":
        d = decompose_l(grid.footprint)
        if d is not None:
            core_poly = place_core_at_elbow(d, core_surface_m2=core_surface_m2)
            return CorePlacement(
                position_xy=(core_poly.centroid.x, core_poly.centroid.y),
                polygon=core_poly,
                surface_m2=core_surface_m2,
            )

    side = (core_surface_m2 ** 0.5)
    reflex = _find_reflex_vertex(grid.footprint)
    if reflex is not None:
        rx, ry = reflex
        # Place the core so its NEAR CORNER sits exactly on the reflex
        # vertex (no offset). This guarantees corridors extending into
        # both wings from that vertex physically touch the core.
        #
        # Quadrant inward = direction du PLUS GRAND WING adjacent au
        # reflex (pas du centroid du footprint entier — avec
        # adossement nord, centroid glisse vers leg et core y va alors
        # que bar — plus grand — reste vide).
        _wings_for_core = _decompose_into_wings(grid.footprint)
        if len(_wings_for_core) >= 2:
            # Plus grand wing = celui où loger le core
            _biggest = max(_wings_for_core, key=lambda w: w.area)
            _bctr = _biggest.centroid
            dx = _bctr.x - rx
            dy = _bctr.y - ry
        else:
            centroid = grid.footprint.centroid
            dx = centroid.x - rx
            dy = centroid.y - ry
        mag = max(0.01, (dx * dx + dy * dy) ** 0.5)
        ux, uy = dx / mag, dy / mag
        # Snap quadrant vers le plus grand wing
        qx = 1 if ux >= 0 else -1
        qy = 1 if uy >= 0 else -1
        ccx = rx + qx * side / 2
        ccy = ry + qy * side / 2
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
    """Split an axis-aligned L / rectangle footprint into up to 2 wings.

    Rewritten 2026-04 after the greedy sweep version kept over-fragmenting
    clean L-shapes into 3-4 degenerate wings (one of which a sliver <
    1 m²). The new algorithm is purely analytical:

    1. If fill_ratio (poly.area / bbox.area) ≥ 0.92 → treat as a plain
       rectangle, return [bbox].
    2. Find the ONE reflex vertex of the axis-aligned polygon (for an
       L, there's exactly one). Polygons with 2+ reflexes (T / U / +
       shapes) fall back to [bbox].
    3. Try horizontal split at reflex.y: bbox is cut into bot/top, each
       intersected with poly and rounded to its own axis-aligned bbox.
    4. Try vertical split at reflex.x: same idea left/right.
    5. Pick the split whose TWO rectangles (a) cover the most area and
       (b) each have the shorter side ≥ 8 m (solver-friendly depth).
       If neither qualifies, fall back to [bbox].
    """
    from shapely.geometry import box as shp_box
    from shapely.geometry import Polygon as _Poly

    minx, miny, maxx, maxy = footprint.bounds
    bbox = shp_box(minx, miny, maxx, maxy)
    if bbox.area == 0:
        return [footprint]

    fill_ratio = footprint.area / bbox.area
    # Near-rectangular → single wing = bbox (clean, solver-friendly).
    if fill_ratio > 0.92:
        return [bbox]

    # Pré-simplification : les footprints issus d'un clip à un polygone
    # buffered (parcelle - 3 m) arrivent souvent avec 8–12 sommets
    # parasites (marches d'escalier de 0,2–0,5 m). Un L canonique n'a
    # que 6 sommets, donc on simplifie à 0,8 m avant de compter les
    # réflexes. Sans ça, on retombe systématiquement sur bbox pour
    # toute forme non rectangulaire et le solver recrée des slots qui
    # débordent du vrai footprint → apts < T2 → droppés.
    pre_simplified = footprint.simplify(0.8)
    if pre_simplified.geom_type != "Polygon" or pre_simplified.area < footprint.area * 0.90:
        pre_simplified = footprint  # trop agressif, reste brut

    # Orient CCW for stable cross-product sign
    coords = list(pre_simplified.exterior.coords)[:-1]
    poly_ccw = pre_simplified if pre_simplified.exterior.is_ccw else _Poly(coords[::-1])
    cc = list(poly_ccw.exterior.coords)[:-1]

    # Find all reflex vertices (inner corners on CCW → cross < 0)
    reflexes: list[tuple[float, float]] = []
    n = len(cc)
    for i in range(n):
        p0 = cc[(i - 1) % n]
        p1 = cc[i]
        p2 = cc[(i + 1) % n]
        cr = (p1[0] - p0[0]) * (p2[1] - p1[1]) - (p1[1] - p0[1]) * (p2[0] - p1[0])
        if cr < -0.5:
            reflexes.append(p1)

    # Only handle the single-reflex (L-shape) case reliably; higher
    # complexity falls back to bbox.
    if len(reflexes) != 1:
        return [bbox]

    rx, ry = reflexes[0]
    MIN_WING_DEPTH = 8.0  # sub-wings thinner than 8 m produce unsellable apts

    # Identify the notch corner: the bbox corner that the polygon does NOT
    # cover. A probe slightly inside each corner tells us: if polygon
    # doesn't contain it → that corner is the notch.
    from shapely.geometry import Point as _Point
    buf_test = footprint.buffer(0.1)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    notch: tuple[float, float] | None = None
    for corner in ((minx, miny), (maxx, miny), (minx, maxy), (maxx, maxy)):
        probe = _Point(
            corner[0] + (0.5 if corner[0] < cx else -0.5),
            corner[1] + (0.5 if corner[1] < cy else -0.5),
        )
        if not buf_test.contains(probe):
            notch = corner
            break

    if notch is None:
        # Can't identify notch → safe fallback to bbox
        return [bbox]

    # Given the notch corner and the reflex (rx, ry), the axis-aligned L
    # splits into two rectangles along either the x=rx or y=ry line.
    # Horizontal split at y=ry: bottom half [minx..maxx, miny..ry],
    # top half [minx..maxx, ry..maxy]. One of them has a notch on one side
    # — we shrink that half's x-span to exclude the notch corner.
    nx, ny = notch
    def _h_wings() -> list[ShapelyPolygon]:
        # Two horizontal bands; whichever contains the notch gets x-shrunk
        bot_x0, bot_x1 = minx, maxx
        top_x0, top_x1 = minx, maxx
        if ny < (miny + maxy) / 2:  # notch on bottom
            if nx < (minx + maxx) / 2:
                bot_x0 = rx
            else:
                bot_x1 = rx
        else:  # notch on top
            if nx < (minx + maxx) / 2:
                top_x0 = rx
            else:
                top_x1 = rx
        return [shp_box(bot_x0, miny, bot_x1, ry), shp_box(top_x0, ry, top_x1, maxy)]

    def _v_wings() -> list[ShapelyPolygon]:
        # Two vertical bands; whichever contains the notch gets y-shrunk
        left_y0, left_y1 = miny, maxy
        right_y0, right_y1 = miny, maxy
        if nx < (minx + maxx) / 2:  # notch on left
            if ny < (miny + maxy) / 2:
                left_y0 = ry
            else:
                left_y1 = ry
        else:  # notch on right
            if ny < (miny + maxy) / 2:
                right_y0 = ry
            else:
                right_y1 = ry
        return [shp_box(minx, left_y0, rx, left_y1), shp_box(rx, right_y0, maxx, right_y1)]

    def _valid(ws: list[ShapelyPolygon]) -> bool:
        for w in ws:
            wb = w.bounds
            if min(wb[2] - wb[0], wb[3] - wb[1]) < MIN_WING_DEPTH:
                return False
            if w.area <= 0:
                return False
        return True

    candidates = [_h_wings(), _v_wings()]
    valid = [c for c in candidates if _valid(c)]
    if not valid:
        return [bbox]
    # Pick the split that better matches the original footprint area
    best = min(valid, key=lambda ws: abs(sum(w.area for w in ws) - footprint.area))
    return best


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

    # Topology-aware short-circuit: if the footprint maps to a known
    # shape handler (currently: L), delegate entirely. The handler
    # returns a coherent (core, corridor, slots) bundle, so we use its
    # slots and move the core to the handler-chosen position upstream
    # if needed. When None, fall through to legacy wing-par-wing logic.
    from core.building_model.layout_dispatcher import dispatch_layout

    l_result = dispatch_layout(
        footprint=grid.footprint,
        mix_typologique=mix_typologique,
        core_surface_m2=core.surface_m2,
    )
    if l_result is not None:
        return l_result.slots

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
    # Dual-loaded splits a wing into two rows of apts (≥ 6.5 m deep each)
    # plus a 1.6 m central corridor. Threshold = 2×6.5 + 1.6 ≈ 14.5 m. À
    # 15 m profondeur (MAX_DEPTH résidentiel), on passe tout juste : 2 ×
    # 6.7 m + 1.6 m = 15 m → dual-loaded. Shallower wings use single-
    # loaded corridor on one side.
    _DUAL_LOADED_THRESHOLD_M = 14.5

    core_bb_tuple = tuple(core.polygon.bounds)

    # Pre-allocate a slot budget per wing proportional to wing area.
    # This keeps apt density consistent across L-shape wings instead of
    # letting each wing pick its own density from mix-weighted slot width
    # (which underpacks narrow / single-loaded wings).
    total_wing_area = sum(w.area for w in wings) or 1.0
    wing_slot_budget = {
        id(w): max(1, round(nb_apartments * w.area / total_wing_area))
        for w in wings
    }
    # Distribute the rounding remainder to the biggest wing
    budget_sum = sum(wing_slot_budget.values())
    if budget_sum != nb_apartments and wings:
        biggest = max(wings, key=lambda w: w.area)
        wing_slot_budget[id(biggest)] += (nb_apartments - budget_sum)
        wing_slot_budget[id(biggest)] = max(1, wing_slot_budget[id(biggest)])

    for wing_outer in wings:
        wxmin_o, wymin_o, wxmax_o, wymax_o = wing_outer.bounds
        wing_w_o = wxmax_o - wxmin_o
        wing_h_o = wymax_o - wymin_o

        # Core-adjacent wing: the corridor runs along the shared edge with
        # the core (not in the middle). This leaves the whole wing minus
        # the 1.6 m strip as USABLE sub-wing. Subdividing that sub-wing
        # normally produces non-landlocked slots because all exterior
        # façades remain accessible.
        adj = _core_adjacent_edge(wing_outer, core_bb_tuple)
        if adj is not None:
            # For wide sub-wings (> 10 m perpendicular to main corridor),
            # we add a SECONDARY cross-corridor splitting the sub-wing
            # into 4 quadrants, so every apt has direct corridor access.
            if adj == "west":
                base = (wxmin_o + _CORRIDOR_WIDTH_M, wymin_o, wxmax_o, wymax_o)
                sub_perp = base[2] - base[0]  # horizontal extent
                sec_axis = "horizontal"
            elif adj == "east":
                base = (wxmin_o, wymin_o, wxmax_o - _CORRIDOR_WIDTH_M, wymax_o)
                sub_perp = base[2] - base[0]
                sec_axis = "horizontal"
            elif adj == "south":
                base = (wxmin_o, wymin_o + _CORRIDOR_WIDTH_M, wxmax_o, wymax_o)
                sub_perp = base[3] - base[1]
                sec_axis = "vertical"
            else:  # north
                base = (wxmin_o, wymin_o, wxmax_o, wymax_o - _CORRIDOR_WIDTH_M)
                sub_perp = base[3] - base[1]
                sec_axis = "vertical"

            bxmin, bymin, bxmax, bymax = base
            has_secondary = sub_perp > 10.0
            if has_secondary:
                if sec_axis == "horizontal":
                    # Secondary runs horizontally; the sub-wing splits
                    # into 4 quadrants: NW/NE above, SW/SE below the
                    # secondary. Each sub-wing's inner edge sits AT the
                    # secondary corridor so an apt's wall is on it.
                    cy_mid_sec = (bymin + bymax) / 2
                    south_s = (bxmin, bymin, bxmax, cy_mid_sec - _CORRIDOR_WIDTH_M / 2)
                    north_s = (bxmin, cy_mid_sec + _CORRIDOR_WIDTH_M / 2, bxmax, bymax)
                    # Each of south_s / north_s split further along x
                    mid_x = (bxmin + bxmax) / 2
                    sub_wings = [
                        ShapelyPolygon([
                            (south_s[0], south_s[1]), (mid_x, south_s[1]),
                            (mid_x, south_s[3]), (south_s[0], south_s[3]),
                        ]),
                        ShapelyPolygon([
                            (mid_x, south_s[1]), (south_s[2], south_s[1]),
                            (south_s[2], south_s[3]), (mid_x, south_s[3]),
                        ]),
                        ShapelyPolygon([
                            (north_s[0], north_s[1]), (mid_x, north_s[1]),
                            (mid_x, north_s[3]), (north_s[0], north_s[3]),
                        ]),
                        ShapelyPolygon([
                            (mid_x, north_s[1]), (north_s[2], north_s[1]),
                            (north_s[2], north_s[3]), (mid_x, north_s[3]),
                        ]),
                    ]
                else:
                    cx_mid_sec = (bxmin + bxmax) / 2
                    west_s = (bxmin, bymin, cx_mid_sec - _CORRIDOR_WIDTH_M / 2, bymax)
                    east_s = (cx_mid_sec + _CORRIDOR_WIDTH_M / 2, bymin, bxmax, bymax)
                    mid_y = (bymin + bymax) / 2
                    sub_wings = [
                        ShapelyPolygon([(west_s[0], west_s[1]), (west_s[2], west_s[1]),
                                        (west_s[2], mid_y), (west_s[0], mid_y)]),
                        ShapelyPolygon([(west_s[0], mid_y), (west_s[2], mid_y),
                                        (west_s[2], west_s[3]), (west_s[0], west_s[3])]),
                        ShapelyPolygon([(east_s[0], east_s[1]), (east_s[2], east_s[1]),
                                        (east_s[2], mid_y), (east_s[0], mid_y)]),
                        ShapelyPolygon([(east_s[0], mid_y), (east_s[2], mid_y),
                                        (east_s[2], east_s[3]), (east_s[0], east_s[3])]),
                    ]
            else:
                sub_wings = [ShapelyPolygon([
                    (bxmin, bymin), (bxmax, bymin), (bxmax, bymax), (bxmin, bymax),
                ])]
        else:
            # Legacy: dual-loaded central corridor splits the wing into two
            # parallel strips when it's deep enough; shallow wings stay as
            # a single strip (single-loaded from the wing's edge).
            slice_x_outer = wing_w_o >= wing_h_o
            perp_outer = wing_h_o if slice_x_outer else wing_w_o
            if perp_outer > _DUAL_LOADED_THRESHOLD_M:
                half = (perp_outer - _CORRIDOR_WIDTH_M) / 2
                if slice_x_outer:
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

        # Compute the slot budget for this outer wing, and distribute it
        # across sub-wings proportional to area.
        wing_budget = wing_slot_budget.get(id(wing_outer), 1)
        total_sub_area = sum(sw.area for sw in sub_wings) or 1.0
        sub_budgets = [
            max(1, round(wing_budget * sw.area / total_sub_area))
            for sw in sub_wings
        ]
        # Fix rounding so sub-budgets sum to wing_budget
        delta = wing_budget - sum(sub_budgets)
        if delta != 0 and sub_budgets:
            biggest_idx = max(range(len(sub_wings)), key=lambda i: sub_wings[i].area)
            sub_budgets[biggest_idx] = max(1, sub_budgets[biggest_idx] + delta)

        # Process each sub-wing (single or dual strip around the corridor)
        for sub_idx, wing in enumerate(sub_wings):
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

            # 2. Compute slot width using the BUDGETED slot count, clamped
            #    to per-typo width ranges. This packs each sub-wing at the
            #    building-level apt density rather than letting mix-weighted
            #    widths under-pack narrow wings.
            min_w_global = min(_TYPO_DIM_RANGE[t][0] * 0.85 for t in fitting_typos)
            max_w_global = max(_TYPO_DIM_RANGE[t][1] * 1.15 for t in fitting_typos)
            budget_here = sub_budgets[sub_idx]
            max_nb = max(1, int(slice_length / min_w_global))
            min_nb = max(1, math.ceil(slice_length / max_w_global))
            nb_slots_in_wing = max(min_nb, min(budget_here, max_nb))
            actual_slot_width = slice_length / nb_slots_in_wing
            smallest_typo_for_fb = min(fitting_typos, key=lambda t: typo_surface_targets[t])

            smallest_typo = smallest_typo_for_fb

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

    # Post-processing: absorb any landlocked dead zones inside the footprint
    # into the nearest apt slot that has an exterior wall. This prevents
    # visually empty (unallocated) patches in the plan and gives one of the
    # existing apts an oversized layout rather than wasting the surface.
    _absorb_dead_zones(slots, grid.footprint, circulation_network)

    return slots


def _absorb_dead_zones(
    slots: list["ApartmentSlot"],
    footprint: ShapelyPolygon,
    circulation_network: ShapelyPolygon,
) -> None:
    """Merge landlocked + leftover pockets into the neighbouring apt.

    Two sources of "dead zones":
      1. Landlocked slots (orientations == [], no exterior wall) — these
         slots were generated but can't be a valid logement because
         they have no windows. Found inline in ``slots``.
      2. Remainder pockets — space inside the footprint not covered by
         any slot and not circulation.

    Both get merged into the nearest slot that DOES have an exterior
    wall, growing that slot (L-shape union when needed). Afterwards the
    landlocked slot entries are removed from ``slots``. This turns a
    "white gap" in the plan into a larger neighbouring apartment.
    """
    from shapely.geometry import Polygon as SP
    from shapely.ops import unary_union

    if not slots:
        return

    # 1. Collect dead-zone polygons: landlocked slots + remainder pockets
    landlocked = [s for s in slots if not s.orientations]
    dead_polys: list = [s.polygon for s in landlocked]
    covered = unary_union([s.polygon for s in slots] + [circulation_network])
    remainder = footprint.difference(covered)
    if not remainder.is_empty:
        dead_polys.extend(
            list(remainder.geoms) if remainder.geom_type == "MultiPolygon" else [remainder]
        )

    # Remove landlocked slots from the active list so they don't end up
    # as apartments — they'll be absorbed below.
    for ll in landlocked:
        if ll in slots:
            slots.remove(ll)

    if not slots:
        return  # nothing left to merge into

    # 2. Merge each dead polygon into the neighbouring non-landlocked slot
    for pocket in dead_polys:
        if pocket.is_empty or pocket.area < 5.0:
            continue

        def _shared_border(s, p=pocket):
            return s.polygon.boundary.intersection(p.boundary).length

        best = max(slots, key=_shared_border)
        if _shared_border(best) < 0.5:
            continue
        merged = unary_union([best.polygon, pocket])
        if merged.geom_type == "MultiPolygon":
            merged = max(merged.geoms, key=lambda g: g.area)
        if not isinstance(merged, SP):
            continue
        best.polygon = merged
        best.surface_m2 = merged.area
        # Re-classify target typologie based on new surface so the
        # template selector picks an appropriate (larger) template.
        best.target_typologie = _reclassify_by_surface(
            merged.area, best.target_typologie,
        )


# Width × depth ranges per typology — ALIGNED with the production template
# library's dimensions_grille (templates_library table). Keeping the solver
# and templates in sync prevents slots that the template selector must
# later reject for being too narrow / too deep to fit any template.
# If new templates with wider ranges are added, bump these values.
_TYPO_DIM_RANGE: dict[Typologie, tuple[float, float, float, float]] = {
    Typologie.STUDIO: (4.0, 5.5, 5.5, 7.0),
    Typologie.T1:     (4.5, 6.0, 6.0, 7.5),
    Typologie.T2:     (6.0, 7.5, 7.0, 8.5),
    Typologie.T3:     (7.2, 9.0, 8.5, 10.5),
    Typologie.T4:     (8.5, 11.0, 9.0, 11.5),
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
    Typologie.T5:     (90.0, 160.0),  # > T4 max; extended to absorb merged landlocked-adjacent slots
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
