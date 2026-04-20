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
    """Vary the typology mix floor-by-floor — DISCRETE buckets.

    Real residential buildings stack distinct floor types:
      - RDC      : T2 dominant (smaller, easier to sell / rent)
      - R+1..2   : T3 dominant (family standard, balanced market)
      - R+3..n-2 : T4 dominant (larger family, higher price/m²)
      - Top floor: T5 / duplex (premium, views, rooftop setbacks)

    Each floor thus shows a distinct visual + commercial character.
    The TOTAL across floors still approximates the brief's base_mix via
    the count balance between floor types.
    """
    # Which mix bucket does this floor belong to?
    if nb_floors <= 1:
        bucket = "standard"
    elif floor_idx == 0:
        bucket = "rdc"
    elif floor_idx == nb_floors - 1:
        bucket = "top"
    elif floor_idx <= (nb_floors - 1) // 3:
        bucket = "low"
    elif floor_idx >= 2 * (nb_floors - 1) // 3:
        bucket = "high"
    else:
        bucket = "mid"

    # Bucket → target mix (covers T2 → T5)
    buckets: dict[str, dict[Typologie, float]] = {
        "rdc":       {Typologie.T2: 0.55, Typologie.T3: 0.45},
        "low":       {Typologie.T2: 0.30, Typologie.T3: 0.60, Typologie.T4: 0.10},
        "mid":       {Typologie.T3: 0.60, Typologie.T4: 0.40},
        "high":      {Typologie.T3: 0.25, Typologie.T4: 0.55, Typologie.T5: 0.20},
        "top":       {Typologie.T4: 0.40, Typologie.T5: 0.60},
        "standard":  {Typologie(k): v for k, v in base_mix.items()},
    }
    result = buckets[bucket]
    # Keep only typologies present in the original brief (don't invent)
    allowed = {Typologie(k) for k, v in base_mix.items() if v > 0}
    if allowed:
        filtered = {t: v for t, v in result.items() if t in allowed}
        if filtered:
            result = filtered
        else:
            # No overlap — fall back to the brief mix unchanged
            result = {Typologie(k): v for k, v in base_mix.items()}
    # Renormalise
    total = sum(result.values())
    if total > 0:
        result = {k: v / total for k, v in result.items()}
    return result


def _relocate_entries_to_corridor(
    cells: list[Cellule], circulations: list[Circulation],
) -> None:
    """Place each apt's porte_entree on the wall of the ENTREE room
    that faces the nearest corridor.

    The door must land INSIDE the apt's entrée room — never on a bathroom
    or bedroom wall. We find the ENTREE room's bbox, identify which of its
    sides is closest to a circulation polygon, and place the door at the
    midpoint of that side.
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

        # Prefer the ENTREE room's bbox. If missing, fall back to the apt
        # bbox (keeps backward-compatible behaviour for apts without an
        # explicit entrée — e.g. small studios).
        entree = next(
            (r for r in apt.rooms if r.type == RoomType.ENTREE and r.polygon_xy),
            None,
        )
        if entree is not None:
            xs_r = [p[0] for p in entree.polygon_xy]
            ys_r = [p[1] for p in entree.polygon_xy]
        else:
            xs_r = [p[0] for p in apt.polygon_xy]
            ys_r = [p[1] for p in apt.polygon_xy]
        r_minx, r_miny, r_maxx, r_maxy = min(xs_r), min(ys_r), max(xs_r), max(ys_r)

        # Test each side of the entree room against the closest circulation
        from shapely.geometry import Point
        sides = {
            "sud":   Point((r_minx + r_maxx) / 2, r_miny),
            "nord":  Point((r_minx + r_maxx) / 2, r_maxy),
            "ouest": Point(r_minx, (r_miny + r_maxy) / 2),
            "est":   Point(r_maxx, (r_miny + r_maxy) / 2),
        }
        best_side = min(sides.keys(), key=lambda s: sides[s].distance(closest))

        # Remove existing porte_entree(s)
        apt.openings = [
            op for op in apt.openings if op.type != OpeningType.PORTE_ENTREE
        ]

        # Build a wall along the ENTREE room's corridor-facing side. The door
        # will live on this wall, guaranteed to be inside the entrée room.
        if best_side == "sud":
            p0, p1 = (r_minx, r_miny), (r_maxx, r_miny)
        elif best_side == "nord":
            p0, p1 = (r_minx, r_maxy), (r_maxx, r_maxy)
        elif best_side == "ouest":
            p0, p1 = (r_minx, r_miny), (r_minx, r_maxy)
        else:  # est
            p0, p1 = (r_maxx, r_miny), (r_maxx, r_maxy)

        wall_id = f"{apt.id}_w_corridor"
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
        # Position the 93 cm door *inside* the ENTREE room, not at the
        # geometric midpoint of the wall which may sit on the boundary
        # with the adjacent SdB. We project the entrée's CENTROID onto
        # the wall and use that as the door's position.
        if entree is not None:
            e_cx = sum(x for x, _ in entree.polygon_xy) / len(entree.polygon_xy)
            e_cy = sum(y for _, y in entree.polygon_xy) / len(entree.polygon_xy)
            if best_side in ("sud", "nord"):
                proj_along = e_cx - p0[0]
            else:
                proj_along = e_cy - p0[1]
            # Keep the door at least 60 cm from either jamb so the 93 cm
            # leaf fully fits inside the entrée room bbox.
            pos_raw_cm = int(abs(proj_along) * 100)
            door_pos_cm = max(60, min(wall_len_cm - 60, pos_raw_cm))
        else:
            door_pos_cm = max(50, wall_len_cm // 2)
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


_ENTRY_HALL_WIDTH_M = 3.0   # lobby visible depth
_ENTRY_HALL_DEPTH_M = 4.0   # hall reaches in from voirie wall


def _build_entry_hall(
    footprint,
    core,
    circulations: list[Circulation],
    *,
    voirie_side: str,
) -> Circulation | None:
    """Build a lobby polygon that touches the voirie-facing wall.

    The hall is a ~3 m × 4 m rectangle placed against the voirie edge of the
    footprint, aligned with the core on the perpendicular axis. It is then
    extended to reach the core + the nearest corridor so the main door always
    opens into an unbroken circulation network.
    """
    from shapely.geometry import Polygon as ShapelyPoly

    if footprint.is_empty:
        return None
    fxmin, fymin, fxmax, fymax = footprint.bounds
    core_cx, core_cy = core.position_xy
    half_w = _ENTRY_HALL_WIDTH_M / 2

    # 1. Initial hall rectangle sitting against the voirie wall
    if voirie_side == "sud":
        hall = ShapelyPoly([
            (core_cx - half_w, fymin),
            (core_cx + half_w, fymin),
            (core_cx + half_w, fymin + _ENTRY_HALL_DEPTH_M),
            (core_cx - half_w, fymin + _ENTRY_HALL_DEPTH_M),
        ])
        # Extend towards the core if core is further north than the initial hall
        extend_to = max(core_cy, fymin + _ENTRY_HALL_DEPTH_M)
        hall = ShapelyPoly([
            (core_cx - half_w, fymin),
            (core_cx + half_w, fymin),
            (core_cx + half_w, extend_to),
            (core_cx - half_w, extend_to),
        ])
    elif voirie_side == "nord":
        extend_to = min(core_cy, fymax - _ENTRY_HALL_DEPTH_M)
        hall = ShapelyPoly([
            (core_cx - half_w, extend_to),
            (core_cx + half_w, extend_to),
            (core_cx + half_w, fymax),
            (core_cx - half_w, fymax),
        ])
    elif voirie_side == "est":
        extend_to = min(core_cx, fxmax - _ENTRY_HALL_DEPTH_M)
        hall = ShapelyPoly([
            (extend_to, core_cy - half_w),
            (fxmax, core_cy - half_w),
            (fxmax, core_cy + half_w),
            (extend_to, core_cy + half_w),
        ])
    else:  # ouest
        extend_to = max(core_cx, fxmin + _ENTRY_HALL_DEPTH_M)
        hall = ShapelyPoly([
            (fxmin, core_cy - half_w),
            (extend_to, core_cy - half_w),
            (extend_to, core_cy + half_w),
            (fxmin, core_cy + half_w),
        ])

    hall = hall.intersection(footprint)
    if hall.is_empty:
        return None
    # Merge with the core so the hall reaches the stairs block
    hall = hall.union(core.polygon.buffer(0.02))
    hall = hall.difference(core.polygon)
    if hall.geom_type == "MultiPolygon":
        hall = max(hall.geoms, key=lambda g: g.area)
    if hall.is_empty or hall.area < 2.0:
        return None

    _ = circulations  # could later be used to bridge to an existing corridor
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

    # Largest axis-aligned rectangle that fits entirely inside the pocket.
    # We scan the bbox at 0.5 m steps and try each candidate rectangle,
    # keeping the biggest one whose full area is inside the pocket.
    def _inscribed_rect(poly) -> ShapelyPoly | None:
        minx, miny, maxx, maxy = poly.bounds
        buffered = poly.buffer(0.05)
        best: ShapelyPoly | None = None
        best_area = _POCKET_NEW_APT_MIN_M2
        step = 0.5
        # Try every axis-aligned rectangle of width ≥ 5 m and depth ≥ 5 m
        # fitting inside the bbox. This is O(n^4) on a bbox grid but the
        # bbox is small (~10 m) and step is 0.5 m so ≤ 20^4 ≈ 160k tests.
        xs = [minx + i * step for i in range(int((maxx - minx) / step) + 1)]
        ys = [miny + i * step for i in range(int((maxy - miny) / step) + 1)]
        for x0 in xs:
            for x1 in xs:
                if x1 - x0 < 5.0:
                    continue
                for y0 in ys:
                    for y1 in ys:
                        if y1 - y0 < 5.0:
                            continue
                        area = (x1 - x0) * (y1 - y0)
                        if area <= best_area:
                            continue
                        # Aspect filter
                        w, h = x1 - x0, y1 - y0
                        if max(w, h) / min(w, h) > 2.8:
                            continue
                        trial = ShapelyPoly([
                            (x0, y0), (x1, y0), (x1, y1), (x0, y1),
                        ])
                        if buffered.contains(trial):
                            best = trial
                            best_area = area
        return best

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

        slot_id = f"pocket_R{niveau_idx}_{p_idx}"
        try:
            rooms, _, _, actual_palier = generate_apartment(
                slot_bounds=(rxmin, rymin, rxmax, rymax),
                typologie=typo,
                orientations=[],
                slot_id=slot_id,
                template_id="pocket_infill",
            )
        except Exception:
            continue
        # Override palier_side with the one we inferred from the adjacent
        # circulation (generate_apartment picks based on orientations)
        walls, openings = build_walls_and_openings(
            rooms,
            (rxmin, rymin, rxmax, rymax),
            palier_side,  # type: ignore[arg-type]
            slot_id,
        )
        _ = actual_palier

        apt = CelluleSchema(
            id=slot_id,
            type=CelluleType.LOGEMENT,
            typologie=typo,
            surface_m2=sum(r.surface_m2 for r in rooms),
            polygon_xy=[(rxmin, rymin), (rxmax, rymin),
                        (rxmax, rymax), (rxmin, rymax)],
            orientation=[],
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
    """Emit one corridor per wing of the footprint.

    Two corridor modes:
    - Core-adjacent wing (edge flush with core): corridor runs along the
      SHARED edge → connects to the core directly, no cross-wing
      connector needed. All the wing's apts stay on the other side of
      the corridor, with exterior façades preserved.
    - Legacy central corridor: dual-loaded when the perpendicular span
      is large enough; otherwise single-loaded (apt opens on wing edge).
    """
    from shapely.geometry import Polygon as ShapelyPoly
    from core.building_model.solver import _core_adjacent_edge, _decompose_into_wings

    corridors: list[Circulation] = []
    if not cells:
        return corridors

    half = _CORRIDOR_WIDTH_M / 2
    wings = _decompose_into_wings(footprint)

    core_cx, core_cy = core.position_xy
    core_bb = core.polygon.bounds  # minx, miny, maxx, maxy

    DUAL_THRESHOLD = 15.0
    for i, wing in enumerate(wings):
        wxmin, wymin, wxmax, wymax = wing.bounds
        ww = wxmax - wxmin
        wh = wymax - wymin

        # Core-adjacent wing: put the corridor along the shared edge.
        adj = _core_adjacent_edge(wing, tuple(core_bb))
        if adj is not None:
            if adj == "west":
                corridor_poly = ShapelyPoly([
                    (wxmin, wymin), (wxmin + _CORRIDOR_WIDTH_M, wymin),
                    (wxmin + _CORRIDOR_WIDTH_M, wymax), (wxmin, wymax),
                ]).intersection(footprint)
            elif adj == "east":
                corridor_poly = ShapelyPoly([
                    (wxmax - _CORRIDOR_WIDTH_M, wymin), (wxmax, wymin),
                    (wxmax, wymax), (wxmax - _CORRIDOR_WIDTH_M, wymax),
                ]).intersection(footprint)
            elif adj == "south":
                corridor_poly = ShapelyPoly([
                    (wxmin, wymin), (wxmax, wymin),
                    (wxmax, wymin + _CORRIDOR_WIDTH_M), (wxmin, wymin + _CORRIDOR_WIDTH_M),
                ]).intersection(footprint)
            else:  # north
                corridor_poly = ShapelyPoly([
                    (wxmin, wymax - _CORRIDOR_WIDTH_M), (wxmax, wymax - _CORRIDOR_WIDTH_M),
                    (wxmax, wymax), (wxmin, wymax),
                ]).intersection(footprint)
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
            continue

        # Only dual-loaded wings get a dedicated inner corridor
        if min(ww, wh) < DUAL_THRESHOLD:
            continue
        if ww >= wh:
            # Horizontal corridor along the wing's length, centered vertically
            cy_mid = (wymin + wymax) / 2
            corridor_poly = ShapelyPoly([
                (wxmin, cy_mid - half), (wxmax, cy_mid - half),
                (wxmax, cy_mid + half), (wxmin, cy_mid + half),
            ]).intersection(footprint)
            axis = "horizontal"
        else:
            cx_mid = (wxmin + wxmax) / 2
            corridor_poly = ShapelyPoly([
                (cx_mid - half, wymin), (cx_mid + half, wymin),
                (cx_mid + half, wymax), (cx_mid - half, wymax),
            ]).intersection(footprint)
            axis = "vertical"

        if corridor_poly.is_empty:
            continue

        # Ensure the corridor CONNECTS to the core. If the wing's corridor
        # polygon doesn't touch the core, add a short connector segment in
        # the opposite axis from the corridor's closest point to the core.
        if corridor_poly.distance(core.polygon) > 0.2:
            # Closest point on the corridor to the core
            wxmin_c, wymin_c, wxmax_c, wymax_c = corridor_poly.bounds
            if axis == "horizontal":
                # Connector is vertical from corridor to core
                connector_cx = max(core_bb[0], min(core_bb[2], (wxmin_c + wxmax_c) / 2))
                # If corridor is east of core, connect from core east edge
                # going east to corridor west edge
                if wxmin_c > core_bb[2]:
                    cx0 = core_bb[2]
                    cx1 = wxmin_c
                elif wxmax_c < core_bb[0]:
                    cx0 = wxmax_c
                    cx1 = core_bb[0]
                else:
                    cx0 = core_bb[2]
                    cx1 = wxmax_c
                cy_conn = (wymin_c + wymax_c) / 2
                connector = ShapelyPoly([
                    (min(cx0, cx1), cy_conn - half), (max(cx0, cx1), cy_conn - half),
                    (max(cx0, cx1), cy_conn + half), (min(cx0, cx1), cy_conn + half),
                ]).intersection(footprint)
                corridor_poly = corridor_poly.union(connector)
                _ = connector_cx
            else:
                # Vertical corridor: connector is horizontal from corridor to core
                if wymin_c > core_bb[3]:
                    cy0 = core_bb[3]; cy1 = wymin_c
                elif wymax_c < core_bb[1]:
                    cy0 = wymax_c; cy1 = core_bb[1]
                else:
                    cy0 = core_bb[3]; cy1 = wymax_c
                # Horizontal connector running along the SOUTH edge of the
                # core. This is the core's palier strip — renders below the
                # escalier/ASC in the frontend so the corridor opens cleanly
                # into the palier without the stairs blocking visual flow.
                if wxmin_c > core_bb[2]:
                    cx0_conn = core_bb[2]; cx1_conn = (wxmin_c + wxmax_c) / 2 + half
                elif wxmax_c < core_bb[0]:
                    cx0_conn = (wxmin_c + wxmax_c) / 2 - half; cx1_conn = core_bb[0]
                else:
                    cx0_conn = core_bb[2]; cx1_conn = (wxmin_c + wxmax_c) / 2 + half
                # Connector sits at core_bb[1] (south edge) up to +1.6 m
                # to stay inside the palier strip (bottom 38 % of the core).
                connector = ShapelyPoly([
                    (min(cx0_conn, cx1_conn), core_bb[1]),
                    (max(cx0_conn, cx1_conn), core_bb[1]),
                    (max(cx0_conn, cx1_conn), core_bb[1] + _CORRIDOR_WIDTH_M),
                    (min(cx0_conn, cx1_conn), core_bb[1] + _CORRIDOR_WIDTH_M),
                ]).intersection(footprint)
                corridor_poly = corridor_poly.union(connector)
                _ = (cy0, cy1)

        # Subtract the core so the corridor doesn't overlap the stairs block
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
            for slot in slots_per_floor:
                # Drop landlocked slots (no exterior façade) — real-estate
                # logic: an apt without any exterior wall can't have windows
                # and is not a legitimate logement.
                if not slot.orientations:
                    continue
                sel = await selector.select_for_slot(slot)
                if sel is None:
                    continue  # Fallback solver would go here (Sprint 2 task)
                fit = adapter.fit_to_slot(sel.template, slot)
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

        # RDC only: add an ENTRY HALL that touches the voirie-facing wall so
        # the main door opens into circulation (never into an apt wall). The
        # hall runs from the voirie wall to the nearest corridor / core.
        if is_rdc:
            entry_hall = _build_entry_hall(
                footprint, core, circulations, voirie_side=voirie,
            )
            if entry_hall is not None:
                circulations.append(entry_hall)
                # The hall overlaps one or more apt rectangles — carve it out
                # of every cellule so nothing stays under the lobby.
                _carve_circulations_from_cells(cells_for_niveau, [entry_hall])

        # Densify: any empty pocket ≥ 40 m² that sits against a circulation
        # becomes a new apartment. Without this step, carving leaves wasted
        # space the user would see as dead zones.
        new_pocket_apts = _fill_pockets_with_apts(
            niveau_idx=idx,
            footprint=footprint,
            cells=cells_for_niveau,
            circulations=circulations,
            voirie_side=voirie,
        )
        cells_for_niveau.extend(new_pocket_apts)

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

    core_schema = Core(
        position_xy=core.position_xy,
        surface_m2=core.surface_m2,
        escalier=Escalier(type="quart_tournant", giron_cm=28, hauteur_marche_cm=17, nb_marches_par_niveau=18),
        ascenseur=ascenseur,
        gaines_techniques=[],
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
