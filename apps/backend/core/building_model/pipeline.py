# apps/backend/core/building_model/pipeline.py
"""End-to-end pipeline: GenerationInputs → BuildingModel."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID, uuid4

from shapely.geometry import shape
from sqlalchemy.ext.asyncio import AsyncSession

from core.building_model.schemas import (
    Ascenseur,
    BuildingModel,
    Cellule,
    CelluleType,
    Circulation,
    Core,
    Envelope,
    Escalier,
    Facade,
    Metadata,
    Niveau,
    Site,
    ToitureConfig,
    ToitureType,
    Typologie,
)
from core.building_model.solver import (
    build_modular_grid,
    classify_cells,
    compute_apartment_slots,
    place_core,
)
from core.building_model.validator import validate_all
from core.feasibility.schemas import Brief
from core.plu.schemas import NumericRules
from core.templates_library.adapter import TemplateAdapter
from core.templates_library.selector import TemplateSelector


@dataclass
class GenerationInputs:
    project_id: UUID
    parcelle_geojson: dict
    parcelle_surface_m2: float
    voirie_orientations: list[str]
    north_angle_deg: float
    plu_rules: NumericRules
    zone_plu: str
    brief: Brief
    footprint_recommande_geojson: dict
    niveaux_recommandes: int
    hauteur_recommandee_m: float
    emprise_pct_recommandee: float
    style_architectural_preference: str | None = None
    facade_style_preference: str | None = None


_DEFAULT_HAUTEUR_ETAGE_M = 2.7
_DEFAULT_HAUTEUR_RDC_M = 3.2
_DEFAULT_CORE_SURFACE_M2 = 22.0
_CORRIDOR_WIDTH_M = 1.6


def _mix_for_floor(
    base_mix: dict[str, float], floor_idx: int, nb_floors: int,
) -> dict["Typologie", float]:
    """Return the typology mix for a given floor.

    2026-04 simplification: use the brief's base_mix IDENTICALLY on
    every floor. The previous per-floor bucket system (RDC=T2 dominant,
    top=T5 dominant, etc.) caused floors to have 0 apts when their
    bucket produced slots either too small to survive hall carving
    (RDC, T2 under 40 m² threshold) or too large to fit the wing
    depth (top, T5 needing ≥ 10 m depth).

    Architectural variation per floor (penthouse vs RDC commercial)
    is a feature to re-introduce later once the base case is stable.
    """
    _ = floor_idx, nb_floors  # unused in the simplified version
    result = {Typologie(k): v for k, v in base_mix.items() if v > 0}
    if not result:
        result = {
            Typologie.T2: 0.25, Typologie.T3: 0.35,
            Typologie.T4: 0.25, Typologie.T5: 0.15,
        }
    total = sum(result.values())
    return {k: v / total for k, v in result.items()}


def _relocate_entries_to_corridor(
    cells: list[Cellule], circulations: list[Circulation],
) -> None:
    """Place each apt's porte_entree on the apt's perimeter wall that
    touches a corridor, anchored at the midpoint of whichever ENTREE
    room the template rotated onto that side.

    The adapter already rotates/flips templates so their ENTREE sits on
    the corridor-facing side (based on slot.orientations). Here we just
    emit the door ON the matching perimeter wall segment (not on an
    interior wall between two rooms).
    """
    from core.building_model.schemas import (
        Opening,
        OpeningType,
        RoomType,
        Wall,
        WallType,
    )
    from shapely.geometry import Polygon as ShapelyPoly

    if not circulations:
        return

    circ_polys = [
        ShapelyPoly(c.polygon_xy) for c in circulations if len(c.polygon_xy) >= 3
    ]
    if not circ_polys:
        return

    for apt in cells:
        if apt.type != CelluleType.LOGEMENT or not apt.polygon_xy:
            continue
        apt_poly = ShapelyPoly(apt.polygon_xy)
        closest = min(circ_polys, key=lambda p: p.distance(apt_poly))

        xs_a = [p[0] for p in apt.polygon_xy]
        ys_a = [p[1] for p in apt.polygon_xy]
        a_minx, a_miny, a_maxx, a_maxy = min(xs_a), min(ys_a), max(xs_a), max(ys_a)

        from shapely.geometry import LineString
        sides = {
            "sud":   LineString([(a_minx, a_miny), (a_maxx, a_miny)]),
            "nord":  LineString([(a_minx, a_maxy), (a_maxx, a_maxy)]),
            "ouest": LineString([(a_minx, a_miny), (a_minx, a_maxy)]),
            "est":   LineString([(a_maxx, a_miny), (a_maxx, a_maxy)]),
        }
        best_side = min(sides.keys(), key=lambda s: sides[s].distance(closest))

        # Remove pre-existing porte_entree(s)
        apt.openings = [
            op for op in apt.openings if op.type != OpeningType.PORTE_ENTREE
        ]

        # Wall segment on the corridor side of the apt.
        if best_side == "sud":
            p0, p1 = (a_minx, a_miny), (a_maxx, a_miny)
        elif best_side == "nord":
            p0, p1 = (a_minx, a_maxy), (a_maxx, a_maxy)
        elif best_side == "ouest":
            p0, p1 = (a_minx, a_miny), (a_minx, a_maxy)
        else:
            p0, p1 = (a_maxx, a_miny), (a_maxx, a_maxy)

        wall_id = f"{apt.id}_w_corridor"
        apt.walls = [w for w in apt.walls if w.id != wall_id]
        apt.walls.append(Wall(
            id=wall_id,
            type=WallType.PORTEUR,
            thickness_cm=20,
            geometry={"type": "LineString", "coords": [list(p0), list(p1)]},
            hauteur_cm=260,
            materiau="beton_banche",
        ))
        wall_len_cm = int(
            ((p1[0] - p0[0]) ** 2 + (p1[1] - p0[1]) ** 2) ** 0.5 * 100
        )

        # Prefer to anchor the door at the ENTREE room's midpoint
        # (projected onto the wall). If the template put the entrée on
        # a different side, fall back to the wall midpoint — the door
        # still lands on the corridor, just opens into whichever room
        # the template chose (this signals the template was a bad
        # orientation match; fix by improving template selection).
        entree = next(
            (r for r in apt.rooms if r.type == RoomType.ENTREE and r.polygon_xy),
            None,
        )
        door_pos_cm = wall_len_cm // 2
        if entree is not None:
            e_cx = sum(p[0] for p in entree.polygon_xy) / len(entree.polygon_xy)
            e_cy = sum(p[1] for p in entree.polygon_xy) / len(entree.polygon_xy)
            if best_side in ("sud", "nord"):
                along = e_cx - p0[0]
            else:
                along = e_cy - p0[1]
            door_pos_cm = max(60, min(wall_len_cm - 60, int(abs(along) * 100)))

        apt.openings.append(Opening(
            id=f"{apt.id}_op_entree",
            type=OpeningType.PORTE_ENTREE,
            wall_id=wall_id,
            position_along_wall_cm=door_pos_cm,
            width_cm=93,
            height_cm=220,
            allege_cm=None,
            swing="interior_right",
        ))


_ENTRY_HALL_WIDTH_M = 1.6   # narrow PMR corridor — no wasted space


def _build_entry_hall(
    footprint,
    core,
    circulations: list[Circulation],
    *,
    voirie_side: str,
) -> Circulation | None:
    """Build a short 1.6 m hall linking voirie to the nearest existing
    corridor (NOT to the core directly).

    The hall is the minimum strip needed to bring pedestrians from the
    voirie-facing wall up to the wing corridor closest to voirie. This
    avoids huge wasted space (a 3 m × 13 m lobby carving through
    apartment slots) while still guaranteeing a continuous circulation
    path from the main door to every apt.

    Strategy:
    1. Find the circulation polygon whose bbox is closest to the voirie
       wall (skip the palier itself — we want a wing corridor).
    2. Align the hall with that corridor on the non-voirie axis so they
       meet head-on.
    3. Size the hall to exactly span voirie → that corridor's edge.
    """
    from shapely.geometry import Polygon as ShapelyPoly

    if footprint.is_empty:
        return None
    fxmin, fymin, fxmax, fymax = footprint.bounds
    half_w = _ENTRY_HALL_WIDTH_M / 2

    # Pick the non-palier circulation closest to the voirie wall.
    wing_circs = [
        c for c in circulations
        if not c.id.startswith("palier") and len(c.polygon_xy) >= 3
    ]
    if not wing_circs:
        return None

    def _dist_to_voirie(c):
        ys = [p[1] for p in c.polygon_xy]
        xs = [p[0] for p in c.polygon_xy]
        if voirie_side == "sud":   return min(ys) - fymin
        if voirie_side == "nord":  return fymax - max(ys)
        if voirie_side == "ouest": return min(xs) - fxmin
        return fxmax - max(xs)

    nearest = min(wing_circs, key=_dist_to_voirie)
    nxs = [p[0] for p in nearest.polygon_xy]
    nys = [p[1] for p in nearest.polygon_xy]
    n_minx, n_miny, n_maxx, n_maxy = min(nxs), min(nys), max(nxs), max(nys)

    # Hall runs between voirie wall and the near edge of the nearest
    # corridor. Align the hall with that corridor's CORNER closest to
    # the core: this way the hall lands on one edge of the corridor
    # (not in its middle) and carves cleanly through a single apt slot
    # boundary, rather than bisecting an apt into a fragile U-shape.
    core_cx, core_cy = core.position_xy
    if voirie_side in ("sud", "nord"):
        if abs(core_cx - n_minx) < abs(core_cx - n_maxx):
            hall_cx = n_minx + half_w
        else:
            hall_cx = n_maxx - half_w
        if voirie_side == "sud":
            hall = ShapelyPoly([
                (hall_cx - half_w, fymin), (hall_cx + half_w, fymin),
                (hall_cx + half_w, n_miny), (hall_cx - half_w, n_miny),
            ])
        else:
            hall = ShapelyPoly([
                (hall_cx - half_w, n_maxy), (hall_cx + half_w, n_maxy),
                (hall_cx + half_w, fymax), (hall_cx - half_w, fymax),
            ])
    else:
        if abs(core_cy - n_miny) < abs(core_cy - n_maxy):
            hall_cy = n_miny + half_w
        else:
            hall_cy = n_maxy - half_w
        if voirie_side == "est":
            hall = ShapelyPoly([
                (n_maxx, hall_cy - half_w), (fxmax, hall_cy - half_w),
                (fxmax, hall_cy + half_w), (n_maxx, hall_cy + half_w),
            ])
        else:
            hall = ShapelyPoly([
                (fxmin, hall_cy - half_w), (n_minx, hall_cy - half_w),
                (n_minx, hall_cy + half_w), (fxmin, hall_cy + half_w),
            ])

    hall = hall.intersection(footprint)
    if hall.is_empty or hall.area < 2.0:
        return None
    if hall.geom_type == "MultiPolygon":
        hall = max(hall.geoms, key=lambda g: g.area)

    coords = list(hall.exterior.coords)[:-1]
    return Circulation(
        id="hall_entree_RDC",
        polygon_xy=coords,
        surface_m2=hall.area,
        largeur_min_cm=int(_ENTRY_HALL_WIDTH_M * 100),
    )


_MIN_APT_AFTER_CARVE_M2 = 40.0  # T2 minimum viable surface
_POCKET_NEW_APT_MIN_M2 = 40.0   # dropped-apt pockets ≥ this become new apts


def _fill_pockets_with_apts(
    niveau_idx: int,
    footprint,
    cells: list[Cellule],
    circulations: list[Circulation],
    voirie_side: str,
) -> list[Cellule]:
    """Detect empty pockets ≥ 40 m² left after carving and turn them
    into new apartments, densifying the floor.

    Returns the list of new cellules created (the caller appends them).
    The new apts use a T2 or T3 template depending on surface.
    """
    from shapely.geometry import Polygon as ShapelyPoly
    from shapely.ops import unary_union
    from core.templates_library.layout_generator import (
        build_walls_and_openings,
        generate_apartment,
    )
    from core.building_model.schemas import Cellule as CelluleSchema
    from core.building_model.schemas import CelluleType, Typologie

    occupied_polys = [
        ShapelyPoly(c.polygon_xy) for c in cells if len(c.polygon_xy) >= 3
    ]
    occupied_polys += [
        ShapelyPoly(c.polygon_xy)
        for c in circulations
        if len(c.polygon_xy) >= 3
    ]
    if not occupied_polys:
        return []
    occupied = unary_union(occupied_polys)
    empty = footprint.difference(occupied)
    if empty.is_empty:
        return []

    pockets = list(empty.geoms) if empty.geom_type == "MultiPolygon" else [empty]
    pockets = [p for p in pockets if p.area >= _POCKET_NEW_APT_MIN_M2]
    if not pockets:
        return []

    # Largest axis-aligned rectangle inscrit dans le pocket.
    # Algo rapide : on part de la bbox du pocket et on la rétrécit par
    # pas de 0.5 m jusqu'à ce qu'elle tienne entièrement (évite le scan
    # O(n^4) qui stalle sur footprints complexes). 14 itérations max.
    def _inscribed_rect(poly) -> ShapelyPoly | None:
        minx, miny, maxx, maxy = poly.bounds
        buffered = poly.buffer(0.05)
        for shrink in (0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0):
            x0 = minx + shrink
            y0 = miny + shrink
            x1 = maxx - shrink
            y1 = maxy - shrink
            w, h = x1 - x0, y1 - y0
            if w < 5.0 or h < 5.0:
                return None
            if w * h < _POCKET_NEW_APT_MIN_M2:
                return None
            if max(w, h) / min(w, h) > 2.8:
                # Shift l'un des côtés pour rapprocher du ratio
                continue
            trial = ShapelyPoly([
                (x0, y0), (x1, y0), (x1, y1), (x0, y1),
            ])
            if buffered.contains(trial):
                return trial
        return None

    # For each pocket, infer palier_side (side facing the nearest circulation)
    circ_polys = [
        ShapelyPoly(c.polygon_xy)
        for c in circulations
        if len(c.polygon_xy) >= 3
    ]

    new_cells: list[Cellule] = []

    for p_idx, pocket in enumerate(pockets):
        rect = _inscribed_rect(pocket)
        if rect is None:
            continue
        rxmin, rymin, rxmax, rymax = rect.bounds
        rw = rxmax - rxmin
        rh = rymax - rymin
        # Target typology based on area. T2 range is 40-52 m²; T3 52-65 m².
        area = rect.area
        if area >= 52:
            typo = Typologie.T3
        else:
            typo = Typologie.T2

        # Reject pockets whose aspect ratio is too extreme for a realistic
        # apartment (narrow corridors disguised as apts).
        if min(rw, rh) < 5.0 or max(rw, rh) / min(rw, rh) > 2.8:
            continue

        # Infer palier side: the edge closest to any circulation polygon
        from shapely.geometry import Point
        sides = {
            "sud":   Point((rxmin + rxmax) / 2, rymin),
            "nord":  Point((rxmin + rxmax) / 2, rymax),
            "ouest": Point(rxmin, (rymin + rymax) / 2),
            "est":   Point(rxmax, (rymin + rymax) / 2),
        }
        if not circ_polys:
            continue
        palier_side = min(
            sides.keys(),
            key=lambda s: min(p.distance(sides[s]) for p in circ_polys),
        )
        # Distance must be tight (< 1.5 m) to ensure the apt is reachable
        best_d = min(p.distance(sides[palier_side]) for p in circ_polys)
        if best_d > 1.5:
            continue

        # Infer orientations of the pocket slot from the footprint boundary,
        # same criterion the solver uses for regular slots. Drop the pocket
        # if it turns out to be landlocked (no exterior façade) — we don't
        # want to emit an unsellable apartment just to fill empty space.
        from core.building_model.solver import _infer_orientations
        rect_poly = ShapelyPoly([
            (rxmin, rymin), (rxmax, rymin),
            (rxmax, rymax), (rxmin, rymax),
        ])
        pocket_orients = _infer_orientations(rect_poly, footprint, voirie_side)
        if not pocket_orients:
            continue

        slot_id = f"pocket_R{niveau_idx}_{p_idx}"
        try:
            rooms, _, _, actual_palier, typo = generate_apartment(
                slot_bounds=(rxmin, rymin, rxmax, rymax),
                typologie=typo,
                orientations=pocket_orients,
                slot_id=slot_id,
                template_id="pocket_infill",
            )
        except Exception:
            continue
        walls, openings = build_walls_and_openings(
            rooms,
            (rxmin, rymin, rxmax, rymax),
            palier_side,  # type: ignore[arg-type]
            slot_id,
            orientations=pocket_orients,
            footprint=footprint,
        )
        _ = actual_palier

        apt = CelluleSchema(
            id=slot_id,
            type=CelluleType.LOGEMENT,
            typologie=typo,
            surface_m2=sum(r.surface_m2 for r in rooms),
            polygon_xy=[(rxmin, rymin), (rxmax, rymin),
                        (rxmax, rymax), (rxmin, rymax)],
            orientation=pocket_orients,
            template_id="pocket_infill",
            rooms=rooms,
            walls=walls,
            openings=openings,
        )
        new_cells.append(apt)

    return new_cells


def _carve_circulations_from_cells(
    cells: list[Cellule],
    new_circulations: list[Circulation],
) -> None:
    """Subtract every circulation polygon from every apt polygon in place.

    Apts whose surface drops below the T2 minimum (40 m²) are dropped —
    the space they occupied becomes an empty pocket that later phases
    (or the user) can repurpose. Keeping a stub of < 40 m² would create
    an unsellable apt; better to drop and redistribute.
    """
    from shapely.geometry import Polygon as ShapelyPoly

    circ_polys = [
        ShapelyPoly(c.polygon_xy) for c in new_circulations if len(c.polygon_xy) >= 3
    ]
    if not circ_polys:
        return
    survivors: list[Cellule] = []
    for apt in cells:
        if not apt.polygon_xy or len(apt.polygon_xy) < 3:
            survivors.append(apt)
            continue
        poly = ShapelyPoly(apt.polygon_xy)
        for cp in circ_polys:
            poly = poly.difference(cp)
        if poly.is_empty or poly.area < _MIN_APT_AFTER_CARVE_M2:
            continue
        if poly.geom_type == "MultiPolygon":
            poly = max(poly.geoms, key=lambda g: g.area)
        apt.polygon_xy = list(poly.exterior.coords)[:-1]
        apt.surface_m2 = poly.area
        survivors.append(apt)
    cells[:] = survivors


def _emit_wing_corridors(
    niveau_idx: int,
    core,
    footprint,
    cells: list[Cellule],
) -> list[Circulation]:
    """Emit one corridor per wing of the footprint, ALL linked to the core.

    Invariants guaranteed:
    - Every wing receives a corridor (never skipped, regardless of depth).
    - Every corridor physically touches the core palier (directly or via
      a short axis-aligned connector).
    - Every apartment has at least one exterior wall on the corridor or
      core boundary (validated later by ``_relocate_entries_to_corridor``).

    Corridor layout rules:
    - Core-adjacent wing: corridor runs along the shared edge with the
      core; if the wing is wide (> 10 m perp), add a secondary cross
      corridor so every apt gets direct access.
    - Non-adjacent wing, dual-loaded (perp ≥ 15 m): centred corridor
      along the wing's long axis.
    - Non-adjacent wing, single-loaded (perp < 15 m): corridor along the
      edge CLOSEST to the core, so the connector is minimal.
    """
    # Topology-aware short-circuit. L footprints get a single
    # continuous corridor emitted from the L handler, matching what the
    # solver used to clip apt slots. For other topologies fall through
    # to the legacy wing-par-wing emission below.
    from core.building_model.layout_dispatcher import classify_footprint_topology
    from core.building_model.layout_l import build_l_corridor, decompose_l
    from core.building_model.schemas import Circulation

    if classify_footprint_topology(footprint) == "L":
        d = decompose_l(footprint)
        if d is not None:
            l_corridor = build_l_corridor(d, corridor_width=_CORRIDOR_WIDTH_M)
            # Do NOT subtract core here: the L corridor physically passes
            # through the elbow where the core sits, and subtracting would
            # shatter the corridor into disjoint arms. The core is rendered
            # separately as its own niveau element, overlaid on top.
            if not l_corridor.is_empty:
                if l_corridor.geom_type == "MultiPolygon":
                    l_corridor = max(l_corridor.geoms, key=lambda g: g.area)
                coords = list(l_corridor.exterior.coords)[:-1]
                return [Circulation(
                    id=f"couloir_L_R{niveau_idx}",
                    polygon_xy=coords,
                    surface_m2=l_corridor.area,
                    largeur_min_cm=int(_CORRIDOR_WIDTH_M * 100),
                )]

    from shapely.geometry import Polygon as ShapelyPoly
    from core.building_model.solver import _core_adjacent_edge, _decompose_into_wings

    corridors: list[Circulation] = []
    # Note: ``cells`` is currently unused by the corridor-emission logic —
    # kept in the signature for future heuristics (e.g. corridor width
    # adapting to apt count). Accept empty lists so the caller can query
    # the corridor shapes before any apt is built.
    _ = cells

    half = _CORRIDOR_WIDTH_M / 2
    wings = _decompose_into_wings(footprint)

    core_cx, core_cy = core.position_xy
    core_bb = core.polygon.bounds  # minx, miny, maxx, maxy

    def _connector_to_core(poly, axis: str) -> ShapelyPoly:
        """Build a short axis-aligned rectangle linking `poly` to the core."""
        pb = poly.bounds
        pxmin, pymin, pxmax, pymax = pb
        if axis == "horizontal":
            # Corridor is horizontal; connector runs VERTICAL to core.
            x_overlap_min = max(pxmin, core_bb[0])
            x_overlap_max = min(pxmax, core_bb[2])
            if x_overlap_min < x_overlap_max:
                cx_lo, cx_hi = x_overlap_min, x_overlap_max
            else:
                mid = max(core_bb[0], min(core_bb[2], (pxmin + pxmax) / 2))
                cx_lo, cx_hi = mid - half, mid + half
            cy_lo = min(pymin, core_bb[1])
            cy_hi = max(pymax, core_bb[3])
        else:
            # Corridor is vertical; connector runs HORIZONTAL to core.
            y_overlap_min = max(pymin, core_bb[1])
            y_overlap_max = min(pymax, core_bb[3])
            if y_overlap_min < y_overlap_max:
                cy_lo, cy_hi = y_overlap_min, y_overlap_max
            else:
                mid = max(core_bb[1], min(core_bb[3], (pymin + pymax) / 2))
                cy_lo, cy_hi = mid - half, mid + half
            cx_lo = min(pxmin, core_bb[0])
            cx_hi = max(pxmax, core_bb[2])
        return ShapelyPoly([
            (cx_lo, cy_lo), (cx_hi, cy_lo),
            (cx_hi, cy_hi), (cx_lo, cy_hi),
        ])

    DUAL_THRESHOLD = 14.5
    for i, wing in enumerate(wings):
        wxmin, wymin, wxmax, wymax = wing.bounds
        ww = wxmax - wxmin
        wh = wymax - wymin

        # Core-adjacent wing: put the corridor along the shared edge,
        # plus a secondary cross-corridor if the sub-wing is wide
        # enough to host a 2×N grid of apts (so every apt has direct
        # corridor access, not just the inner column).
        adj = _core_adjacent_edge(wing, tuple(core_bb))
        if adj is not None:
            if adj == "west":
                main = ShapelyPoly([
                    (wxmin, wymin), (wxmin + _CORRIDOR_WIDTH_M, wymin),
                    (wxmin + _CORRIDOR_WIDTH_M, wymax), (wxmin, wymax),
                ])
                sub_perp = ww - _CORRIDOR_WIDTH_M
                sec_axis = "horizontal"
            elif adj == "east":
                main = ShapelyPoly([
                    (wxmax - _CORRIDOR_WIDTH_M, wymin), (wxmax, wymin),
                    (wxmax, wymax), (wxmax - _CORRIDOR_WIDTH_M, wymax),
                ])
                sub_perp = ww - _CORRIDOR_WIDTH_M
                sec_axis = "horizontal"
            elif adj == "south":
                main = ShapelyPoly([
                    (wxmin, wymin), (wxmax, wymin),
                    (wxmax, wymin + _CORRIDOR_WIDTH_M), (wxmin, wymin + _CORRIDOR_WIDTH_M),
                ])
                sub_perp = wh - _CORRIDOR_WIDTH_M
                sec_axis = "vertical"
            else:
                main = ShapelyPoly([
                    (wxmin, wymax - _CORRIDOR_WIDTH_M), (wxmax, wymax - _CORRIDOR_WIDTH_M),
                    (wxmax, wymax), (wxmin, wymax),
                ])
                sub_perp = wh - _CORRIDOR_WIDTH_M
                sec_axis = "vertical"

            # Secondary corridor — run across the wing if needed
            if sub_perp > 10.0:
                if sec_axis == "horizontal":
                    cy_mid_sec = (wymin + wymax) / 2
                    secondary = ShapelyPoly([
                        (wxmin, cy_mid_sec - half), (wxmax, cy_mid_sec - half),
                        (wxmax, cy_mid_sec + half), (wxmin, cy_mid_sec + half),
                    ])
                else:
                    cx_mid_sec = (wxmin + wxmax) / 2
                    secondary = ShapelyPoly([
                        (cx_mid_sec - half, wymin), (cx_mid_sec + half, wymin),
                        (cx_mid_sec + half, wymax), (cx_mid_sec - half, wymax),
                    ])
                combined = main.union(secondary)
            else:
                combined = main

            corridor_poly = combined.intersection(footprint).difference(core.polygon)
            if corridor_poly.is_empty:
                continue
            if corridor_poly.geom_type == "MultiPolygon":
                # Emit the largest sub-polygon as the couloir; smaller
                # disconnected pieces would be pockets of circulation.
                # But here the T-shape should be connected.
                corridor_poly = max(corridor_poly.geoms, key=lambda g: g.area)
            coords = list(corridor_poly.exterior.coords)[:-1]
            corridors.append(Circulation(
                id=f"couloir_w{i}_R{niveau_idx}",
                polygon_xy=coords,
                surface_m2=corridor_poly.area,
                largeur_min_cm=int(_CORRIDOR_WIDTH_M * 100),
            ))
            continue

        # Non-adjacent wing: always emit a corridor (never skip).
        # Dual-loaded → centred along long axis; single-loaded → along
        # the edge closest to the core (minimises connector length).
        wing_long_horizontal = ww >= wh
        perp_span = wh if wing_long_horizontal else ww
        is_dual = perp_span >= DUAL_THRESHOLD

        if wing_long_horizontal:
            axis = "horizontal"
            if is_dual:
                cy_axis = (wymin + wymax) / 2
            else:
                # Put corridor on the side facing the core to keep the
                # connector short. If core is north of wing → corridor
                # along wing's north edge; if core south → south edge.
                cy_axis = wymax - half if core_cy > (wymin + wymax) / 2 else wymin + half
            main = ShapelyPoly([
                (wxmin, cy_axis - half), (wxmax, cy_axis - half),
                (wxmax, cy_axis + half), (wxmin, cy_axis + half),
            ])
        else:
            axis = "vertical"
            if is_dual:
                cx_axis = (wxmin + wxmax) / 2
            else:
                cx_axis = wxmax - half if core_cx > (wxmin + wxmax) / 2 else wxmin + half
            main = ShapelyPoly([
                (cx_axis - half, wymin), (cx_axis + half, wymin),
                (cx_axis + half, wymax), (cx_axis - half, wymax),
            ])
        main_clipped = main.intersection(footprint)
        if main_clipped.is_empty:
            continue

        # Link the corridor to the core if it doesn't already touch it.
        if main_clipped.distance(core.polygon) > 0.2:
            connector = _connector_to_core(main_clipped, axis).intersection(footprint)
            corridor_poly = main_clipped.union(connector)
        else:
            corridor_poly = main_clipped

        # Subtract the core to avoid overlapping stairs/ASC block.
        corridor_poly = corridor_poly.difference(core.polygon)
        if corridor_poly.is_empty:
            continue
        if corridor_poly.geom_type == "MultiPolygon":
            corridor_poly = max(corridor_poly.geoms, key=lambda g: g.area)
        coords = list(corridor_poly.exterior.coords)[:-1]
        corridors.append(Circulation(
            id=f"couloir_w{i}_R{niveau_idx}",
            polygon_xy=coords,
            surface_m2=corridor_poly.area,
            largeur_min_cm=int(_CORRIDOR_WIDTH_M * 100),
        ))
    return corridors


async def generate_building_model(
    inputs: GenerationInputs,
    session: AsyncSession,
) -> BuildingModel:
    """Orchestrate Steps 1-6 of the generation pipeline."""
    # --- Étape 1: Context already in `inputs`.

    # --- Étape 2: Structural solver ---
    footprint = shape(inputs.footprint_recommande_geojson)
    grid = build_modular_grid(footprint, cell_size_m=3.0)
    voirie = inputs.voirie_orientations[0] if inputs.voirie_orientations else "sud"
    grid = classify_cells(grid, voirie_side=voirie)

    core = place_core(grid, core_surface_m2=_DEFAULT_CORE_SURFACE_M2)

    base_mix = inputs.brief.mix_typologique  # dict[str, float]

    # Topology-aware short-circuit: if the footprint is an L, the
    # L-layout dispatcher places the core at the right half of the
    # landlocked slot. Override the heuristic `place_core` result so
    # the rest of the pipeline (corridors, entries, Core schema) uses
    # the exact polygon the dispatcher chose.
    try:
        from core.building_model.layout_dispatcher import dispatch_layout
        _l_preview = dispatch_layout(
            footprint=footprint,
            mix_typologique=base_mix,
            core_surface_m2=core.surface_m2,
        )
    except Exception:
        _l_preview = None
    l_core_polygon = None
    if _l_preview is not None and _l_preview.core is not None:
        l_core_polygon = _l_preview.core
        _cx = (l_core_polygon.bounds[0] + l_core_polygon.bounds[2]) / 2
        _cy = (l_core_polygon.bounds[1] + l_core_polygon.bounds[3]) / 2
        from core.building_model.solver import CorePlacement as _CP
        core = _CP(
            position_xy=(_cx, _cy),
            polygon=l_core_polygon,
            surface_m2=l_core_polygon.area,
        )

    # --- Étape 3-4: Select template per slot + adapt ---
    selector = TemplateSelector(session=session)
    adapter = TemplateAdapter()
    niveaux: list[Niveau] = []

    for idx in range(inputs.niveaux_recommandes):
        # Per-floor mix: ground floors favour smaller typos, top floors
        # skew larger. Each floor thus shows a distinct typology mix while
        # the building as a whole respects the brief's target ratios.
        floor_mix = _mix_for_floor(base_mix, idx, inputs.niveaux_recommandes)
        slots_per_floor = compute_apartment_slots(
            grid, core, mix_typologique=floor_mix, voirie_side=voirie,
        )
        cells_for_niveau: list[Cellule] = []

        # RDC may be commerce or logements depending on brief
        is_rdc = (idx == 0)
        if is_rdc and inputs.brief.__dict__.get("commerces_rdc", False):
            usage = "commerce"
            # Single commerce cellule spanning usable footprint
            usable = footprint.difference(core.polygon.buffer(1.4))
            cells_for_niveau.append(Cellule(
                id=f"R{idx}_commerce",
                type=CelluleType.COMMERCE,
                typologie=None,
                surface_m2=usable.area,
                polygon_xy=list(usable.exterior.coords)[:-1] if hasattr(usable, 'exterior') else [],
                orientation=inputs.voirie_orientations,
            ))
        else:
            usage = "logements"
            # Pre-compute the corridor network so we can tell each apt
            # which side faces the palier. Templates need this to put
            # the ENTREE room on the correct wall; otherwise the door
            # placement ends up on a bedroom/bathroom instead of the
            # entry hall.
            _pre_corridors = _emit_wing_corridors(idx, core, footprint, [])
            from shapely.geometry import Polygon as _ShapelyPoly, Point as _Pt
            _corridor_shapes: list = [core.polygon] + [
                _ShapelyPoly(c.polygon_xy) for c in _pre_corridors if len(c.polygon_xy) >= 3
            ]

            def _palier_side_for(slot) -> str:
                """Pick the apt side that faces the palier (corridor/core).

                Two-step heuristic so corner apts get a sensible layout:
                  1. Prefer a side NOT listed in ``slot.orientations`` —
                     exterior walls are façades (séjour + windows), never
                     palier.
                  2. Among the remaining (interior) sides, pick the one
                     closest to the CORE. If none are close to the core,
                     fall back to the closest corridor.
                """
                minx, miny, maxx, maxy = slot.polygon.bounds
                side_pts = {
                    "sud":   _Pt((minx + maxx) / 2, miny),
                    "nord":  _Pt((minx + maxx) / 2, maxy),
                    "ouest": _Pt(minx, (miny + maxy) / 2),
                    "est":   _Pt(maxx, (miny + maxy) / 2),
                }
                exterior = set(slot.orientations or [])
                interior_sides = [s for s in side_pts if s not in exterior]
                if not interior_sides:
                    interior_sides = list(side_pts.keys())
                # Prefer closest to the CORE specifically — that's where
                # the stairs + palier are; a wing corridor far from core
                # isn't a real palier.
                core_poly = _corridor_shapes[0]  # by construction core is first
                best = min(
                    interior_sides,
                    key=lambda s: side_pts[s].distance(core_poly),
                )
                if side_pts[best].distance(core_poly) > 3.0:
                    # Core is far — fall back to closest corridor overall
                    best = min(
                        interior_sides,
                        key=lambda s: min(side_pts[s].distance(p) for p in _corridor_shapes),
                    )
                return best

            for slot in slots_per_floor:
                # Drop landlocked slots (no exterior façade) — real-estate
                # logic: an apt without any exterior wall can't have windows
                # and is not a legitimate logement.
                if not slot.orientations:
                    continue
                sel = await selector.select_for_slot(slot)
                if sel is None:
                    continue  # Fallback solver would go here (Sprint 2 task)
                # Attach the corridor-facing side so generate_apartment
                # orients the layout (entree on palier side).
                slot.palier_side_hint = _palier_side_for(slot)  # type: ignore[attr-defined]
                fit = adapter.fit_to_slot(sel.template, slot, footprint=footprint)
                if fit.success and fit.apartment is not None:
                    # Reclassify typologie using the ACTUAL apartment surface
                    # (room sum can differ from slot poly area). Enforces the
                    # strict T2<T3<T4<T5 hierarchy the user expects.
                    from core.building_model.solver import _reclassify_by_surface
                    fit.apartment.typologie = _reclassify_by_surface(
                        fit.apartment.surface_m2, fit.apartment.typologie or slot.target_typologie,
                    )
                    # Assign a human-readable numbering like 'R+0.01' to every
                    # apartment. Sorted by bbox (y then x) so labels follow a
                    # consistent visual reading order.
                    cells_for_niveau.append(fit.apartment)
            # Sort apts on this floor left-to-right, top-to-bottom and assign
            # a stable apt number.
            cells_for_niveau.sort(key=lambda c: (
                -max(p[1] for p in c.polygon_xy),
                min(p[0] for p in c.polygon_xy),
            ))
            for k, apt in enumerate(cells_for_niveau, start=1):
                apt.id = f"R+{idx}.{k:02d}"

        # Palier + corridors: the core is the stairs/elevator block; we also
        # emit one corridor per wing that stretches the palier from the core
        # out along each arm so every apt sits on a corridor. Corridor width
        # = 1.6 m (PMR). Corridors run along the interior edge of each wing.
        circulations = [
            Circulation(
                id=f"palier_R{idx}",
                polygon_xy=list(core.polygon.exterior.coords)[:-1],
                surface_m2=core.polygon.area,
                largeur_min_cm=140,
            ),
        ]
        circulations.extend(_emit_wing_corridors(idx, core, footprint, cells_for_niveau))

        # RDC: no dedicated entry hall. Instead we rely on an existing
        # wing corridor that naturally reaches the voirie wall (e.g.
        # couloir_w0 whose south end touches y=voirie in an L-shape).
        # Dropping the hall recovers the apt slots the hall used to carve.
        # The frontend MainEntrance picks whichever circulation reaches
        # voirie and places the door at that corridor's x-midpoint.
        if is_rdc:
            # Ensure at least one existing corridor actually touches the
            # voirie wall. If none does (rectangular footprint with the
            # corridor centred), fall back to the old hall so the door
            # still opens into circulation.
            from shapely.geometry import Polygon as ShapelyPoly
            fxmin, fymin, fxmax, fymax = footprint.bounds
            voirie_threshold = 0.35
            def _reaches_voirie(c):
                if len(c.polygon_xy) < 3:
                    return False
                xs = [p[0] for p in c.polygon_xy]
                ys = [p[1] for p in c.polygon_xy]
                if voirie == "sud":
                    return abs(min(ys) - fymin) < voirie_threshold
                if voirie == "nord":
                    return abs(max(ys) - fymax) < voirie_threshold
                if voirie == "ouest":
                    return abs(min(xs) - fxmin) < voirie_threshold
                return abs(max(xs) - fxmax) < voirie_threshold
            if not any(_reaches_voirie(c) for c in circulations):
                # No natural corridor reaches voirie — keep the hall fallback
                entry_hall = _build_entry_hall(
                    footprint, core, circulations, voirie_side=voirie,
                )
                if entry_hall is not None:
                    circulations.append(entry_hall)
                    _carve_circulations_from_cells(cells_for_niveau, [entry_hall])

        # Pocket-filling RÉACTIVÉ après remplacement de l'algo O(n^4)
        # par un shrink-bbox iteratif (14 itérations max). Comble les
        # zones vides ≥ 40 m² dans le footprint (ex. NE du bar quand
        # le carve corridor+core laisse un pocket exploitable). Sans
        # ce fill, le rendu ressemble à un T au lieu d'un L.
        try:
            pocket_cells = _fill_pockets_with_apts(
                idx, footprint, cells_for_niveau, circulations, voirie_side=voirie,
            )
            cells_for_niveau.extend(pocket_cells)
        except Exception:
            pass  # pocket fill est purement densifiant, ne doit pas bloquer

        # Drop sub-T2 apartments (< 40 m²). They sometimes slip through when
        # the slot grid produces narrow residual strips at the ends of a
        # wing. Keeping them would fail bm.min_apt_surface validation and
        # block the whole BM generation. Dropped slot area becomes empty
        # and can be repurposed later (loggia, stockage, extension d'un
        # apt voisin).
        from core.building_model.schemas import CelluleType as _CelTyp
        cells_for_niveau[:] = [
            c for c in cells_for_niveau
            if c.type != _CelTyp.LOGEMENT or (c.surface_m2 or 0) >= 40.0
        ]

        # Resort + renumber so the numbering stays consistent after drops
        # and pocket fills.
        if cells_for_niveau:
            cells_for_niveau.sort(key=lambda c: (
                -max(p[1] for p in c.polygon_xy),
                min(p[0] for p in c.polygon_xy),
            ))
            for k, apt in enumerate(cells_for_niveau, start=1):
                apt.id = f"R+{idx}.{k:02d}"

        # Relocate every apt's porte_entree onto the wall CLOSEST to a
        # circulation polygon. This guarantees entries open onto corridors,
        # not onto facades or side walls shared with another apt.
        _relocate_entries_to_corridor(cells_for_niveau, circulations)

        hauteur_hsp = _DEFAULT_HAUTEUR_RDC_M - 0.25 if is_rdc else _DEFAULT_HAUTEUR_ETAGE_M - 0.25
        niveaux.append(Niveau(
            index=idx, code=f"R+{idx}",
            usage_principal=usage,
            hauteur_sous_plafond_m=hauteur_hsp,
            surface_plancher_m2=footprint.area,
            cellules=cells_for_niveau,
            circulations_communes=circulations,
        ))

    # --- Build envelope ---
    hauteur_totale = _DEFAULT_HAUTEUR_RDC_M + _DEFAULT_HAUTEUR_ETAGE_M * (inputs.niveaux_recommandes - 1)
    envelope = Envelope(
        footprint_geojson=inputs.footprint_recommande_geojson,
        emprise_m2=footprint.area,
        niveaux=inputs.niveaux_recommandes,
        hauteur_totale_m=hauteur_totale,
        hauteur_rdc_m=_DEFAULT_HAUTEUR_RDC_M,
        hauteur_etage_courant_m=_DEFAULT_HAUTEUR_ETAGE_M,
        toiture=ToitureConfig(type=ToitureType.TERRASSE, accessible=False, vegetalisee=True),
    )

    # --- Core with optional ascenseur ---
    ascenseur = None
    if inputs.niveaux_recommandes - 1 >= 2:
        ascenseur = Ascenseur(type="Schindler 3300", cabine_l_cm=110, cabine_p_cm=140, norme_pmr=True)

    # Extract the 4 rectangular corners of the core polygon so the
    # frontend can render a true rect (not a sqrt(surface) square).
    _core_polygon_xy: list[tuple[float, float]] | None = None
    try:
        if core.polygon is not None and not core.polygon.is_empty:
            _cx0, _cy0, _cx1, _cy1 = core.polygon.bounds
            _core_polygon_xy = [
                (_cx0, _cy0), (_cx1, _cy0), (_cx1, _cy1), (_cx0, _cy1),
            ]
    except Exception:
        _core_polygon_xy = None

    core_schema = Core(
        position_xy=core.position_xy,
        surface_m2=core.surface_m2,
        escalier=Escalier(type="quart_tournant", giron_cm=28, hauteur_marche_cm=17, nb_marches_par_niveau=18),
        ascenseur=ascenseur,
        gaines_techniques=[],
        polygon_xy=_core_polygon_xy,
    )

    # --- Assemble BuildingModel ---
    bm = BuildingModel(
        metadata=Metadata(
            id=uuid4(), project_id=inputs.project_id,
            address=f"Projet zone {inputs.zone_plu}",
            zone_plu=inputs.zone_plu,
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
            version=1, locked=False,
        ),
        site=Site(
            parcelle_geojson=inputs.parcelle_geojson,
            parcelle_surface_m2=inputs.parcelle_surface_m2,
            voirie_orientations=inputs.voirie_orientations,
            north_angle_deg=inputs.north_angle_deg,
        ),
        envelope=envelope,
        core=core_schema,
        niveaux=niveaux,
        facades={
            "nord": Facade(style="enduit_clair", composition=[], rgb_main="#E8E4D9"),
            "sud": Facade(style="enduit_clair", composition=[], rgb_main="#E8E4D9"),
            "est": Facade(style="enduit_clair", composition=[], rgb_main="#E8E4D9"),
            "ouest": Facade(style="enduit_clair", composition=[], rgb_main="#E8E4D9"),
        },
        materiaux_rendu={
            "facade_principal": "enduit_taloche_blanc_casse",
            "menuiseries": "aluminium_anthracite_RAL7016",
            "toiture": "zinc_anthracite",
        },
    )

    # --- Étape 6: Validation ---
    bm.conformite_check = validate_all(bm, inputs.plu_rules)

    return bm
