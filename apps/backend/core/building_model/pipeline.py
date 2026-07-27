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
    EnvelopeMaxPLU,
    Escalier,
    Facade,
    Loggia,
    Metadata,
    Niveau,
    RoomType,
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
from core.building_model.validator.conformite import (
    BusinessRules,
    validate_conformite,
)
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
    # Optional business / commercial constraints (marge bilan, LLS quota,
    # T3+ typologie mix). When set, the post-generation conformite gate
    # also checks them; otherwise only PLU + R.111-18 are enforced.
    business_rules: BusinessRules | None = None
    commune: str | None = None
    # Bâti À L'ALIGNEMENT de voie (UA.6) : le bâtiment est posé en limite
    # séparative de rue → AUCUN jardin privatif extérieur possible (2026-07-03,
    # validé user). Dans ce cas on NE calcule PAS de jardin_polygon_xy au RDC et
    # on pose une LOGGIA (creusée) par logement sur sa façade jour (rue OU void),
    # jamais mitoyen — y compris au RDC. Défaut True : le bâti d'angle Nogent est
    # sur alignement. Passer False pour un bâti en retrait (jardins possibles).
    bati_sur_alignement: bool = True


_DEFAULT_HAUTEUR_ETAGE_M = 2.7
_DEFAULT_HAUTEUR_RDC_M = 3.2
_DEFAULT_CORE_SURFACE_M2 = 22.0
# Largeur PMR STRICTE du couloir de distribution : 1,40 m (largeur réglementaire
# minimale d'un dégagement PMR desservant des logements). Abaissée de 1,6 → 1,40
# (2026-07-06) sur demande user : le couloir doit être un tracé MINCE sans
# renflement (le trait qui relie les 2 cages + dessert chaque entrée), pas un
# gros ruban gris mangeant la SHAB. Universel (toute L).
_CORRIDOR_WIDTH_M = 1.4

_MAX_PLU_HAUTEUR_PAR_NIVEAU_M = 3.0


def compute_max_envelope(
    plu_rules: NumericRules,
    parcelle_geojson: dict,
) -> EnvelopeMaxPLU:
    """Compute the MAX PLU envelope a parcelle can sustain.

    Independent of the designed envelope — answers the question "what is
    the legal ceiling for this parcelle if optimised against the PLU?".

    Algorithm (v1, isotropic retraits):
    1. Apply an isotropic inward buffer using ``max(recul_voirie,
       recul_lat, recul_fond)`` to the parcelle. Asymmetric per-side
       retraits are a TODO once segment classification is wired in here.
    2. Cap the resulting footprint by ``emprise_max_pct`` (centroid-based
       scaling) so the footprint never exceeds the PLU emprise ceiling.
    3. Resolve the binding height: ``min(hauteur_max_m, niveaux_max *
       3 m + 0.5 m floor thickness)``. Falls back to a single niveau
       when neither rule is supplied.
    4. Derive ``niveaux_max_plu = floor(hauteur_max / 3 m)``.
    5. ``sdp_max_plu_m2 = footprint_area * niveaux``, then cap by
       ``sdp_max_m2`` and ``cos × terrain`` when provided (same logic as
       ``core.feasibility.capacity.compute_sdp``).

    Parcelle CRS:
    Accepts either WGS84 GeoJSON (reprojected to Lambert-93 here) or a
    geometry already in metric CRS. Heuristic: if the input bbox spans
    less than 1 degree, treat as WGS84 and reproject.
    """
    import math

    from shapely.geometry import mapping, shape

    from core.feasibility.footprint import compute_footprint
    from core.geo.surface import _reproject

    notes: list[str] = []

    # ------------------------------------------------------------------
    # 1. Parcelle → metric CRS (Lambert-93)
    # ------------------------------------------------------------------
    parcelle_geom = shape(parcelle_geojson)
    minx, miny, maxx, maxy = parcelle_geom.bounds
    dx = maxx - minx
    dy = maxy - miny
    if dx < 1.0 and dy < 1.0:
        # Looks like WGS84 (degrees) — reproject to metric.
        parcelle_metric = _reproject(parcelle_geom, "EPSG:4326", "EPSG:2154")
        was_wgs84 = True
    else:
        parcelle_metric = parcelle_geom
        was_wgs84 = False

    terrain_area = parcelle_metric.area

    # ------------------------------------------------------------------
    # 2. Retraits — isotropic with max(recul_*)
    # ------------------------------------------------------------------
    recul_voirie = plu_rules.recul_voirie_m or 0.0
    recul_lat = plu_rules.recul_limite_lat_m or 0.0
    recul_fond = plu_rules.recul_fond_m or 0.0
    retrait_applique = max(recul_voirie, recul_lat, recul_fond)
    if recul_voirie != recul_lat or recul_lat != recul_fond:
        notes.append(
            "Retraits asymétriques aplatis en isotrope (max). "
            "TODO: appliquer recul par côté via classification segments."
        )

    emprise_max_pct = plu_rules.emprise_max_pct or 100.0

    footprint_res = compute_footprint(
        terrain=parcelle_metric,
        recul_voirie_m=recul_voirie,
        recul_lat_m=recul_lat,
        recul_fond_m=recul_fond,
        emprise_max_pct=emprise_max_pct,
    )
    emprise_max_m2 = footprint_res.surface_emprise_m2
    footprint_geom = footprint_res.footprint_geom

    # ------------------------------------------------------------------
    # 3. Hauteur max + niveaux
    # ------------------------------------------------------------------
    hauteur_candidates: list[float] = []
    if plu_rules.hauteur_max_m is not None:
        hauteur_candidates.append(plu_rules.hauteur_max_m)
    if plu_rules.hauteur_max_niveaux is not None:
        hauteur_candidates.append(
            plu_rules.hauteur_max_niveaux * _MAX_PLU_HAUTEUR_PAR_NIVEAU_M + 0.5
        )
    if hauteur_candidates:
        hauteur_max_plu_m = min(hauteur_candidates)
    else:
        hauteur_max_plu_m = _MAX_PLU_HAUTEUR_PAR_NIVEAU_M  # single niveau fallback
        notes.append(
            "Aucune contrainte de hauteur PLU — fallback R+0 (3 m)."
        )

    niveaux_max_plu = (
        math.floor(hauteur_max_plu_m / _MAX_PLU_HAUTEUR_PAR_NIVEAU_M)
        if hauteur_max_plu_m > 0
        else 0
    )

    # ------------------------------------------------------------------
    # 4. SDP max — capped by sdp_max_m2 and cos × terrain if provided
    # ------------------------------------------------------------------
    sdp_candidates: list[float] = [emprise_max_m2 * niveaux_max_plu]
    if plu_rules.sdp_max_m2 is not None:
        sdp_candidates.append(plu_rules.sdp_max_m2)
    if plu_rules.cos is not None:
        sdp_candidates.append(plu_rules.cos * terrain_area)
    sdp_max_plu_m2 = min(sdp_candidates) if sdp_candidates else 0.0

    # ------------------------------------------------------------------
    # 5. Footprint geometry → GeoJSON in same CRS as input
    # ------------------------------------------------------------------
    if footprint_geom is not None and not footprint_geom.is_empty:
        if was_wgs84:
            footprint_out = _reproject(footprint_geom, "EPSG:2154", "EPSG:4326")
        else:
            footprint_out = footprint_geom
        footprint_geojson_out: dict = dict(mapping(footprint_out))
    else:
        footprint_geojson_out = {}
        notes.append(
            "Footprint vide après retraits — parcelle trop petite ou retraits trop sévères."
        )

    if plu_rules.bandes_constructibles:
        notes.append(
            "Bandes constructibles présentes mais non appliquées (v1). "
            "TODO: clipper le footprint par bande."
        )
    notes.append("Gabarit (recul progressif par tranche) non appliqué — TODO.")

    return EnvelopeMaxPLU(
        footprint_max_plu_geojson=footprint_geojson_out,
        emprise_max_m2=max(emprise_max_m2, 1e-9),
        emprise_max_pct=emprise_max_pct,
        niveaux_max_plu=niveaux_max_plu,
        hauteur_max_plu_m=hauteur_max_plu_m,
        sdp_max_plu_m2=sdp_max_plu_m2,
        retrait_applique_m=retrait_applique,
        notes=notes,
    )


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


_ENTRY_HALL_WIDTH_M = 1.4   # narrow PMR corridor — no wasted space


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

    # Pick the wing corridor (couloir_*) closest to the voirie wall. Exclude
    # cages (cage_* : esc+ASC blocks, formerly "palier_*") — the hall must land
    # on a walkable corridor, not on a stair core.
    wing_circs = [
        c for c in circulations
        if not (c.id.startswith("palier") or c.id.startswith("cage"))
        and len(c.polygon_xy) >= 3
    ]
    if not wing_circs:
        # Fall back to any non-cage circulation (couloir may itself reach voirie).
        wing_circs = [
            c for c in circulations
            if not c.id.startswith("cage") and len(c.polygon_xy) >= 3
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
    # HALL MINIMAL, ZÉRO VIDE (2026-07-06, demande user) : plus AUCUN élargissement
    # « snap ». Le hall est STRICTEMENT `_ENTRY_HALL_WIDTH_M` de large (1,40 m PMR),
    # de la rue jusqu'au couloir. Le reliquat de la colonne (ex. x[0, 3,6] moins le
    # hall) n'est PAS laissé vide : il est récupéré en aval par `_fill_pockets_with
    # _apts` / `_reclaim_pockets` dans l'apt de coin adjacent → SHAB, pas de « palier
    # 160/140 vide » côté rue. Universel (toute L / toute voirie).
    core_cx, core_cy = core.position_xy
    if voirie_side in ("sud", "nord"):
        # Bord du hall = coin du couloir le plus proche du core (carve propre le
        # long d'une seule limite d'apt), largeur stricte, aucun snap.
        if abs(core_cx - n_minx) < abs(core_cx - n_maxx):
            lo, hi = n_minx, n_minx + _ENTRY_HALL_WIDTH_M
        else:
            lo, hi = n_maxx - _ENTRY_HALL_WIDTH_M, n_maxx
        y0, y1 = (fymin, n_miny) if voirie_side == "sud" else (n_maxy, fymax)
        hall = ShapelyPoly([(lo, y0), (hi, y0), (hi, y1), (lo, y1)])
    else:
        if abs(core_cy - n_miny) < abs(core_cy - n_maxy):
            lo, hi = n_miny, n_miny + _ENTRY_HALL_WIDTH_M
        else:
            lo, hi = n_maxy - _ENTRY_HALL_WIDTH_M, n_maxy
        x0, x1 = (n_maxx, fxmax) if voirie_side == "est" else (fxmin, n_minx)
        hall = ShapelyPoly([(x0, lo), (x1, lo), (x1, hi), (x0, hi)])

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
    parcelle=None,
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
        # Build list of polygons of neighbour apts + pocket apts already
        # emitted, so the jardin-depth ranker inside the wall-openings
        # builder can avoid extruding into their territory.
        _neighbour_polys_pocket = [
            ShapelyPoly(c.polygon_xy) for c in cells if len(c.polygon_xy) >= 3
        ] + [
            ShapelyPoly(c.polygon_xy) for c in new_cells if len(c.polygon_xy) >= 3
        ]
        walls, openings = build_walls_and_openings(
            rooms,
            (rxmin, rymin, rxmax, rymax),
            palier_side,  # type: ignore[arg-type]
            slot_id,
            orientations=pocket_orients,
            footprint=footprint,
            parcelle=parcelle,
            other_cells_polys=_neighbour_polys_pocket,
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
        # Clip the apt's ROOMS to the carved polygon too, else rooms overhang
        # the corridor and the declared habitable surface is wrong (rooms sum >
        # apt polygon). Drop rooms that vanish; keep the largest piece.
        if getattr(apt, "rooms", None):
            kept = []
            for rm in apt.rooms:
                if not rm.polygon_xy or len(rm.polygon_xy) < 3:
                    continue
                rp = ShapelyPoly(rm.polygon_xy)
                for cp in circ_polys:
                    rp = rp.difference(cp)
                if rp.is_empty or rp.area < 0.5:
                    continue
                if rp.geom_type == "MultiPolygon":
                    rp = max(rp.geoms, key=lambda g: g.area)
                if rp.geom_type != "Polygon":
                    continue
                rm.polygon_xy = list(rp.exterior.coords)[:-1]
                rm.surface_m2 = round(rp.area, 1)
                kept.append(rm)
            apt.rooms = kept
        survivors.append(apt)
    cells[:] = survivors


def _fill_intra_apt_pockets(
    cells: list[Cellule],
    footprint,
    voiries: tuple,
) -> None:
    """Fill any un-roomed pocket INSIDE an apartment with a real room.

    An L-shaped apt (e.g. the corner unit wrapping the core) can be laid out
    with rooms tiling only its main rectangle, leaving the return arm as white
    space INSIDE the apt polygon (rooms sum < apt surface — a RÈGLE #3 defect
    the footprint-level VIDE check misses). Each pocket ≥ 4 m² that touches a
    non-party-wall façade (street voirie or cour) becomes a CHAMBRE with a
    window on that façade; a blind pocket becomes a CELLIER. Typologie is then
    recomputed from the new bedroom count.
    """
    from shapely.geometry import Polygon as ShapelyPoly
    from shapely.ops import unary_union
    from core.building_model.schemas import Room, RoomType

    fxmin, fymin, fxmax, fymax = footprint.bounds
    # A cardinal side is a party wall (no window) if it is NOT a voirie AND lies
    # on the footprint's outer bbox edge. Cour-facing edges touch the exterior
    # ring but are interior (U-notch) → windows allowed.
    _MIT = {"nord", "sud", "est", "ouest"} - set(voiries)

    def _pocket_orientation(pc) -> str | None:
        """Return a façade orientation for a window, or None if fully blind."""
        pxmin, pymin, pxmax, pymax = pc.bounds
        ext = footprint.exterior
        cand = []
        # side touches the exterior ring?
        if pc.distance(ext) < 0.35 or True:
            # test each side by a mid-edge sample just outside the pocket
            tests = [
                ("nord", (pxmin + pxmax) / 2, pymax, abs(pymax - fymax) < 0.6),
                ("sud", (pxmin + pxmax) / 2, pymin, abs(pymin - fymin) < 0.6),
                ("est", pxmax, (pymin + pymax) / 2, abs(pxmax - fxmax) < 0.6),
                ("ouest", pxmin, (pymin + pymax) / 2, abs(pxmin - fxmin) < 0.6),
            ]
            from shapely.geometry import Point as _Pt
            for ori, sx, sy, on_outer_bbox in tests:
                p = _Pt(sx, sy)
                if p.distance(ext) > 0.4:
                    continue  # this side is interior to the apt, not a façade
                if on_outer_bbox and ori in _MIT:
                    continue  # party wall → no window
                cand.append(ori)
        return cand[0] if cand else None

    for cell in cells:
        if cell.type != CelluleType.LOGEMENT or not cell.polygon_xy:
            continue
        ap = ShapelyPoly(cell.polygon_xy).buffer(0)
        rooms_u = unary_union([ShapelyPoly(r.polygon_xy) for r in cell.rooms]) \
            if cell.rooms else None
        pocket = ap.difference(rooms_u) if rooms_u is not None else ap
        if pocket.is_empty:
            continue
        pieces = [pocket] if pocket.geom_type == "Polygon" else [
            g for g in pocket.geoms if g.geom_type == "Polygon"]
        n_added = 0
        for pc in pieces:
            pc = pc.buffer(0)
            if pc.area < 4.0 or pc.geom_type != "Polygon":
                continue
            ori = _pocket_orientation(pc)
            if ori is not None:
                rtype, label = RoomType.CHAMBRE_SUPP, "Chambre"
            else:
                rtype, label = RoomType.CELLIER, "Cellier"
            cell.rooms.append(Room(
                id=f"{cell.id}_pocket{n_added}",
                type=rtype,
                surface_m2=round(pc.area, 1),
                polygon_xy=list(pc.exterior.coords)[:-1],
                orientation=[ori] if ori else [],
                label_fr=label,
            ))
            n_added += 1
        if n_added:
            # Recompute typologie from the real bedroom count.
            _nb_ch = sum(1 for r in cell.rooms if r.type in (
                RoomType.CHAMBRE_PARENTS, RoomType.CHAMBRE_ENFANT,
                RoomType.CHAMBRE_SUPP))
            _by_ch = {0: "T1", 1: "T2", 2: "T3", 3: "T4", 4: "T5", 5: "T5"}
            try:
                cell.typologie = type(cell.typologie)(_by_ch.get(_nb_ch, "T5"))
            except Exception:
                pass


def _emit_wing_corridors(
    niveau_idx: int,
    core,
    footprint,
    cells: list[Cellule],
    voiries: tuple = ("sud",),
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
    from shapely.ops import unary_union
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

    def _connector_to_core(poly, axis: str, target_bb=None) -> ShapelyPoly:
        """Build a short axis-aligned rectangle linking `poly` to `target_bb`.

        `target_bb` defaults to the core's bounds but can be any network
        element (e.g. an adjacent corridor) so a wing attaches to the NEAREST
        circulation instead of always reaching across the plan to the core.
        """
        tb = core_bb if target_bb is None else target_bb
        pb = poly.bounds
        pxmin, pymin, pxmax, pymax = pb
        if axis == "horizontal":
            # Corridor is horizontal; connector runs VERTICAL to target.
            x_overlap_min = max(pxmin, tb[0])
            x_overlap_max = min(pxmax, tb[2])
            # Require a MEANINGFUL overlap (>= one corridor width); a razor-thin
            # sliver (corridor ends exactly where the target begins, e.g. floating
            # 31.0 vs 31.0000001) must NOT be treated as an overlap, else the
            # connector collapses to a zero-area line and the wing is orphaned.
            if x_overlap_max - x_overlap_min >= half:
                cx_lo, cx_hi = x_overlap_min, x_overlap_max
            else:
                mid = max(tb[0], min(tb[2], (pxmin + pxmax) / 2))
                cx_lo, cx_hi = mid - half, mid + half
            cy_lo = min(pymin, tb[1])
            cy_hi = max(pymax, tb[3])
        else:
            # Corridor is vertical; connector runs HORIZONTAL to target.
            y_overlap_min = max(pymin, tb[1])
            y_overlap_max = min(pymax, tb[3])
            # See horizontal branch: require a real overlap, not a sliver.
            if y_overlap_max - y_overlap_min >= half:
                cy_lo, cy_hi = y_overlap_min, y_overlap_max
            else:
                mid = max(tb[1], min(tb[3], (pymin + pymax) / 2))
                cy_lo, cy_hi = mid - half, mid + half
            cx_lo = min(pxmin, tb[0])
            cx_hi = max(pxmax, tb[2])
        return ShapelyPoly([
            (cx_lo, cy_lo), (cx_hi, cy_lo),
            (cx_hi, cy_hi), (cx_lo, cy_hi),
        ])

    DUAL_THRESHOLD = 14.5
    # Growing circulation network (core + emitted adjacent corridors). Non-
    # adjacent wings defer emission so each can attach to the NEAREST network
    # element (usually a sibling corridor at the U's inner corner), keeping the
    # connector short instead of reaching across the whole plan to the core.
    network_polys = [core.polygon]
    pending: list = []
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
            network_polys.append(corridor_poly)
            continue

        # Non-adjacent wing: always emit a corridor (never skip).
        # Dual-loaded → centred along long axis; single-loaded → along
        # the edge closest to the core (minimises connector length).
        wing_long_horizontal = ww >= wh
        perp_span = wh if wing_long_horizontal else ww
        is_dual = perp_span >= DUAL_THRESHOLD

        # MITOYEN-aware side (mirror of solver._compute_circulation_network):
        # a wing whose OUTER perimeter side is a party wall (not voirie) gets
        # its corridor on that mitoyen side so apts open onto the cour/rue.
        _fxmin, _fymin, _fxmax, _fymax = footprint.bounds
        mit = None
        if wing_long_horizontal:
            if abs(wymin - _fymin) < 0.6 and "sud" not in voiries:
                mit = "south"
            elif abs(wymax - _fymax) < 0.6 and "nord" not in voiries:
                mit = "north"
        else:
            if abs(wxmin - _fxmin) < 0.6 and "ouest" not in voiries:
                mit = "west"
            elif abs(wxmax - _fxmax) < 0.6 and "est" not in voiries:
                mit = "east"

        if wing_long_horizontal:
            axis = "horizontal"
            if mit == "south":
                cy_axis = wymin + half
            elif mit == "north":
                cy_axis = wymax - half
            elif is_dual:
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
            if mit == "west":
                cx_axis = wxmin + half
            elif mit == "east":
                cx_axis = wxmax - half
            elif is_dual:
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
        # Defer: attach to the nearest network element in a second pass so a
        # wing can hook onto a sibling corridor (short connector) rather than
        # always reaching to the core.
        pending.append((i, main_clipped, axis))

    # Second pass: connect each deferred wing corridor to the NEAREST network
    # element (core or an already-emitted corridor). Process nearest-first so
    # arms attach to the bar before other arms chain off them.
    def _clean_largest(poly):
        if poly.is_empty:
            return None
        if poly.geom_type in ("MultiPolygon", "GeometryCollection"):
            ps = [g for g in poly.geoms
                  if g.geom_type in ("Polygon", "MultiPolygon") and not g.is_empty]
            if not ps:
                return None
            poly = max(ps, key=lambda g: g.area)
            if poly.geom_type == "MultiPolygon":
                poly = max(poly.geoms, key=lambda g: g.area)
        return poly if poly.geom_type == "Polygon" and not poly.is_empty else None

    remaining = list(pending)
    while remaining:
        network = unary_union(network_polys)
        # Pick the pending corridor closest to the current network.
        remaining.sort(key=lambda t: t[1].distance(network))
        i, main_clipped, axis = remaining.pop(0)
        if main_clipped.distance(network) > 0.2:
            # Nearest network element to hook onto.
            nearest = min(network_polys, key=lambda p: main_clipped.distance(p))
            connector = _connector_to_core(
                main_clipped, axis, nearest.bounds).intersection(footprint)
            corridor_poly = unary_union([main_clipped, connector]).buffer(0)
        else:
            corridor_poly = main_clipped
        corridor_poly = corridor_poly.difference(core.polygon).buffer(0)
        corridor_poly = _clean_largest(corridor_poly)
        if corridor_poly is None:
            continue
        coords = list(corridor_poly.exterior.coords)[:-1]
        corridors.append(Circulation(
            id=f"couloir_w{i}_R{niveau_idx}",
            polygon_xy=coords,
            surface_m2=corridor_poly.area,
            largeur_min_cm=int(_CORRIDOR_WIDTH_M * 100),
        ))
        network_polys.append(corridor_poly)
    return corridors


# Balcony saillie depth (m). Kept modest so the street-side projection stays
# defensible as a balcon filant; over the cour it could be deeper. Exact
# street saillie must be checked against the commune's règlement (Nogent UA).
_BALCON_DEPTH_M = 1.20
_BALCON_MAX_W_M = 3.20
_BALCON_MIN_W_M = 1.80


def _dir_of_normal(nx: float, ny: float) -> str:
    """Cardinal label of an outward edge normal (north_angle_deg=0 frame:
    +y=nord, -y=sud, +x=est, -x=ouest)."""
    if abs(nx) >= abs(ny):
        return "est" if nx > 0 else "ouest"
    return "nord" if ny > 0 else "sud"


def _attach_balconies(
    niveaux: list[Niveau],
    footprint,
    voirie_orientations: list[str],
    include_rdc: bool = False,
) -> int:
    """Give every upper-floor logement one balcony on a façade facing the
    STREET (voirie) or the interior COUR — NEVER a mitoyen (party-wall) side.

    Hard user rule: balconies on every floor, rue + cour, never on mitoyen.
    ``cell.orientation`` alone is NOT a safe signal — it lists every exterior
    wall direction INCLUDING mitoyen ones (a corner apt on the parcelle
    boundary reports "nord"/"ouest" even when those are party walls). So a
    façade is balcony-eligible only when:
      • its outward normal points to a voirie direction (street side), OR
      • the balcony projects INTO the footprint bbox (i.e. toward the inner
        cour / L-notch — a private courtyard façade).
    A perimeter edge on a non-voirie side projects OUTSIDE the bbox and is
    rejected as mitoyen. RDC apts get jardins, so this runs on index >= 1.
    Returns the number of balconies attached (for verification/logging).
    """
    import math

    voirie = {v for v in (voirie_orientations or [])}
    fxmin, fymin, fxmax, fymax = footprint.bounds
    eps = 0.05

    def _in_bbox(x: float, y: float) -> bool:
        return (fxmin - eps) <= x <= (fxmax + eps) and \
               (fymin - eps) <= y <= (fymax + eps)

    attached = 0
    for niv in niveaux:
        if niv.index < 0:
            continue  # sous-sols : pas de loggia
        if niv.index < 1 and not include_rdc:
            continue  # RDC en retrait : jardins, pas de loggia (comportement legacy)
        # RDC sur alignement (include_rdc) : loggia comme les étages (0 jardin).
        for cell in niv.cellules:
            if cell.type != CelluleType.LOGEMENT:
                continue
            # RDC : un logt avec JARDIN privatif a DÉJÀ son extérieur au sol → pas
            # de balcon/loggia. Les logts RDC côté RUE (sans jardin) reçoivent une
            # LOGGIA en retrait (jamais un balcon saillant au-dessus du trottoir).
            if niv.index == 0 and getattr(cell, "jardin_polygon_xy", None):
                continue
            poly = cell.polygon_xy
            if not poly or len(poly) < 3:
                continue
            cx = sum(p[0] for p in poly) / len(poly)
            cy = sum(p[1] for p in poly) / len(poly)
            # Séjour polygon (main living room) — the balcony/loggia belongs in
            # front of IT, not the longest façade edge (which may be a chambre).
            from shapely.geometry import Polygon as _SejP, LineString as _SejL
            _sej_r = next((r for r in cell.rooms
                           if r.type in (RoomType.SEJOUR, RoomType.SEJOUR_CUISINE)
                           and len(r.polygon_xy) >= 3), None)
            _sej_poly = _SejP(_sej_r.polygon_xy) if _sej_r else None
            best = None  # (score_tuple, A, B, normal)
            n = len(poly)
            for i in range(n):
                ax, ay = poly[i]
                bx, by = poly[(i + 1) % n]
                ex, ey = bx - ax, by - ay
                length = math.hypot(ex, ey)
                if length < _BALCON_MIN_W_M + 0.4:
                    continue
                # Outward normal = the perpendicular pointing away from centroid.
                mx, my = (ax + bx) / 2, (ay + by) / 2
                for nrm in ((ey, -ex), (-ey, ex)):
                    nlen = math.hypot(*nrm)
                    if nlen < 1e-6:
                        continue
                    nxu, nyu = nrm[0] / nlen, nrm[1] / nlen
                    if (mx - cx) * nxu + (my - cy) * nyu > 0:  # points outward
                        break
                # Where does a balcony off this edge land? It must project into
                # EMPTY space: the STREET (outside the footprint, on a voirie
                # side) or the inner COUR (inside the bbox but OUTSIDE the built
                # volume). "Inside the bbox" alone was WRONG — the bbox also
                # contains the building, so an apt whose façade faces another
                # wing got a balcony landing INSIDE a neighbouring apartment.
                from shapely.geometry import Point as _BPoint
                proj_x, proj_y = mx + nxu * _BALCON_DEPTH_M, my + nyu * _BALCON_DEPTH_M
                lands_in_void = not footprint.contains(_BPoint(proj_x, proj_y))
                faces_cour = _in_bbox(proj_x, proj_y) and lands_in_void
                faces_rue = (_dir_of_normal(nxu, nyu) in voirie) and lands_in_void
                if not (faces_cour or faces_rue):
                    continue  # mitoyen, or facing into the building → no balcony
                if niv.index == 0 and faces_cour:
                    continue  # RDC : pas de balcon saillant projeté (on est au sol)
                # LOGGIA/BALCON = TOUTE LA LONGUEUR DE FAÇADE (défaut user
                # 2026-07-09 : « la loggia doit faire toute la longueur de façade de
                # chaque appartement qui en a une »). On choisit donc l'ARÊTE
                # EXTÉRIEURE LA PLUS LONGUE de l'apt (rue ou cour) ; ce sont les
                # PIÈCES qui RECULENT pour lui laisser la place, PAS la loggia qui
                # rétrécit.
                _score = (length,)
                if best is None or _score > best[0]:
                    best = (_score, (ax, ay), (bx, by), (nxu, nyu))
            if best is None:
                continue
            _score, (ax, ay), (bx, by), (nxu, nyu) = best
            length = math.hypot(bx - ax, by - ay)
            ex, ey = (bx - ax) / length, (by - ay) / length  # unit edge dir
            d = _BALCON_DEPTH_M
            # Cour (saillie, +1) vs rue (loggia en retrait, -1). Testé au milieu.
            _emx, _emy = (ax + bx) / 2, (ay + by) / 2
            faces_cour = _in_bbox(_emx + nxu * d, _emy + nyu * d)
            sign = 1.0 if faces_cour else -1.0
            # Bande PLEINE LARGEUR de la façade (léger inset = trait de séparation
            # entre voisins). Profondeur = _BALCON_DEPTH_M sur toute la longueur.
            inset = 0.15
            w = max(_BALCON_MIN_W_M, length - 2 * inset)
            t0 = inset
            p1 = (ax + ex * t0, ay + ey * t0)
            p2 = (ax + ex * (t0 + w), ay + ey * (t0 + w))
            p2o = (p2[0] + nxu * d * sign, p2[1] + nyu * d * sign)
            p1o = (p1[0] + nxu * d * sign, p1[1] + nyu * d * sign)
            _lg_poly = [p1, p2, p2o, p1o]
            _kind = "balcon" if faces_cour else "loggia"
            cell.loggia = Loggia(
                surface_m2=round(w * d, 2), polygon_xy=_lg_poly, kind=_kind,
            )
            # LOGGIA (retrait, rue) : elle occupe TOUTE la façade → on RECULE toutes
            # les pièces qui la bordent (chaque pièce moins la bande) et on l'émet
            # comme PIÈCE (type loggia) tuilant exactement la bande DANS l'apt. Ainsi
            # la loggia fait toute la longueur, rien ne la chevauche, aucun trou. Le
            # BALCON cour, lui, est en SAILLIE hors bâti → aucune pièce ne recule.
            if _kind == "loggia":
                from shapely.geometry import Polygon as _CarvePoly
                from shapely.ops import unary_union as _uuC
                from shapely.affinity import translate as _translate
                from core.building_model.schemas import Room as _Room
                try:
                    _apt_g = _CarvePoly(cell.polygon_xy)
                    _lgg = _CarvePoly(_lg_poly).buffer(0).intersection(_apt_g)
                    if _lgg.geom_type == "MultiPolygon":
                        _lgg = max(_lgg.geoms, key=lambda g: g.area)
                    _aprime = _apt_g.difference(_lgg).buffer(0)   # apt SANS la loggia
                    if _aprime.geom_type == "MultiPolygon":
                        _aprime = max(_aprime.geoms, key=lambda g: g.area)
                    if (_lgg.geom_type == "Polygon" and _lgg.area > 1.0
                            and _aprime.geom_type == "Polygon"):
                        # Bloc SERVICE (wc/sdb) — les chambres reculées ne doivent pas
                        # le recouvrir.
                        _svc = _uuC([_CarvePoly(r.polygon_xy) for r in cell.rooms
                                     if r.polygon_xy and len(r.polygon_xy) >= 3
                                     and r.type.value in ("wc", "sdb", "salle_de_douche",
                                                          "wc_sdb")]).buffer(0)
                        # On RECULE (translation) les CHAMBRES bordant la loggia :
                        # elles CONSERVENT leur taille réglementaire, se décalent vers
                        # l'intérieur ; c'est le SÉJOUR (le « reste ») qui absorbe la
                        # profondeur loggia (défaut user 2026-07-09 : « recule les
                        # chambres », « redimensionne au besoin, cohérent/réglementaire »).
                        _shift = (-nxu * d, -nyu * d)   # vers l'intérieur, derrière la loggia
                        _sej_r = next((r for r in cell.rooms
                                       if r.type in (RoomType.SEJOUR, RoomType.SEJOUR_CUISINE)
                                       and r.polygon_xy), None)
                        # LOGGIA : DISSOLUTION du dégagement (open-plan). Un hall mangerait
                        # trop de profondeur (loggia 1,2 + chambres + hall → SdB ~1 m de
                        # profond = INUTILISABLE, testé 2026-07-16). L'anti-enclavement de la
                        # chambre au-dessus du bloc SdB (défaut salon large) est traité plus
                        # bas en RÉTRÉCISSANT le SdB en LARGEUR (il garde sa profondeur
                        # utilisable ~2,2 m). Les T4/T5 BALCON gardent leur hall (non décalés).
                        cell.rooms = [r for r in cell.rooms
                                      if r.type != RoomType.DEGAGEMENT_NUIT]
                        _deg_r = next((r for r in cell.rooms
                                       if r.type == RoomType.DEGAGEMENT_NUIT
                                       and r.polygon_xy and len(r.polygon_xy) >= 3), None)
                        if _deg_r is not None:
                            _degp = _translate(_CarvePoly(_deg_r.polygon_xy),
                                               xoff=_shift[0], yoff=_shift[1])
                            _degp = _degp.intersection(_aprime).buffer(0)
                            if _degp.geom_type == "MultiPolygon":
                                _degp = max(_degp.geoms, key=lambda g: g.area)
                            if _degp.geom_type == "Polygon" and _degp.area > 1.0:
                                _deg_r.polygon_xy = [(round(x, 2), round(y, 2))
                                                     for x, y in list(_degp.exterior.coords)[:-1]]
                                _deg_r.surface_m2 = round(_degp.area, 1)
                                for _wr in cell.rooms:
                                    if _wr.type.value not in ("wc", "sdb",
                                                              "salle_de_douche", "wc_sdb"):
                                        continue
                                    if not _wr.polygon_xy or len(_wr.polygon_xy) < 3:
                                        continue
                                    _wp = _CarvePoly(_wr.polygon_xy).difference(_degp).buffer(0)
                                    if _wp.geom_type == "MultiPolygon":
                                        _wp = max(_wp.geoms, key=lambda g: g.area)
                                    if _wp.geom_type == "Polygon" and _wp.area > 1.5:
                                        _wr.polygon_xy = [(round(x, 2), round(y, 2))
                                                          for x, y in list(_wp.exterior.coords)[:-1]]
                                        _wr.surface_m2 = round(_wp.area, 1)
                                # ── SdB ÉLARGIE (option 2, user 2026-07-10) : sous le
                                # dégagement décalé la SdB a rétréci → on l'ÉLARGIT vers
                                # le SÉJOUR (qui absorbe ~0,5 m²) pour rester ≥ 3,8 m²
                                # (H7), en gardant les CHAMBRES pleines. Chambres +
                                # dégagement + WC = obstacles ; on teste les 4 directions
                                # et on garde le 1ᵉʳ rectangle propre ≥ 3,95 m².
                                _sdb_r = next((r for r in cell.rooms
                                               if r.type.value in ("sdb", "salle_de_douche")
                                               and r.polygon_xy and len(r.polygon_xy) >= 3), None)
                                if _sdb_r is not None and _sdb_r.surface_m2 < 3.9:
                                    _avoid = _uuC([_CarvePoly(r.polygon_xy) for r in cell.rooms
                                                   if r is not _sdb_r and r.polygon_xy
                                                   and len(r.polygon_xy) >= 3
                                                   and ("chambre" in r.type.value
                                                        or r.type == RoomType.DEGAGEMENT_NUIT
                                                        or r.type.value in ("wc", "wc_sdb"))]
                                                  ).buffer(0)
                                    _sb = _CarvePoly(_sdb_r.polygon_xy).bounds
                                    _done_w = False
                                    for _ext in (0.4, 0.8, 1.2, 1.8):
                                        for _bx in ((_sb[0] - _ext, _sb[1], _sb[2], _sb[3]),
                                                    (_sb[0], _sb[1], _sb[2] + _ext, _sb[3]),
                                                    (_sb[0], _sb[1] - _ext, _sb[2], _sb[3]),
                                                    (_sb[0], _sb[1], _sb[2], _sb[3] + _ext)):
                                            _cd = _CarvePoly([(_bx[0], _bx[1]), (_bx[2], _bx[1]),
                                                              (_bx[2], _bx[3]), (_bx[0], _bx[3])])
                                            _cd = _cd.intersection(_aprime).difference(_avoid).buffer(0)
                                            if _cd.geom_type == "MultiPolygon":
                                                _cd = max(_cd.geoms, key=lambda g: g.area)
                                            _cdb = _cd.bounds if _cd.geom_type == "Polygon" else None
                                            if (_cd.geom_type == "Polygon" and _cd.area >= 3.95
                                                    and _cdb and _cd.area / max(1e-6,
                                                    (_cdb[2] - _cdb[0]) * (_cdb[3] - _cdb[1])) > 0.9):
                                                _sdb_r.polygon_xy = [(round(x, 2), round(y, 2))
                                                                     for x, y in list(_cd.exterior.coords)[:-1]]
                                                _sdb_r.surface_m2 = round(_cd.area, 1)
                                                _done_w = True
                                                break
                                        if _done_w:
                                            break
                                _svc = _uuC([_CarvePoly(r.polygon_xy) for r in cell.rooms
                                             if r.polygon_xy and len(r.polygon_xy) >= 3
                                             and r.type.value in ("wc", "sdb",
                                                                  "salle_de_douche", "wc_sdb")]
                                            ).buffer(0).union(_degp).buffer(0)
                        for _r in cell.rooms:
                            if not _r.polygon_xy or len(_r.polygon_xy) < 3:
                                continue
                            if "chambre" not in _r.type.value:
                                continue
                            _rp = _CarvePoly(_r.polygon_xy)
                            if _rp.intersection(_lgg).area < 0.2:
                                continue
                            _rt = _translate(_rp, xoff=_shift[0], yoff=_shift[1]).buffer(0)
                            _rt = _rt.intersection(_aprime).buffer(0)
                            if not _svc.is_empty:
                                _rt = _rt.difference(_svc).buffer(0)
                            if _rt.geom_type == "MultiPolygon":
                                _rt = max(_rt.geoms, key=lambda g: g.area)
                            # RECTANGULARISER : si la chambre reculée s'enroule en L
                            # autour du bloc SdB (défaut user 2026-07-10 : « SdB
                            # empiète sur la chambre »), on garde le PLUS GRAND
                            # RECTANGLE qui ÉVITE le SdB (le résidu revient au séjour).
                            if (_rt.geom_type == "Polygon" and not _svc.is_empty):
                                _rbx = _rt.bounds
                                _rratio = _rt.area / max(1e-6, (_rbx[2] - _rbx[0])
                                                         * (_rbx[3] - _rbx[1]))
                                if _rratio < 0.94:
                                    _sbx = _svc.bounds
                                    _cands = []
                                    for _cbox in (
                                        (_sbx[2], _rbx[1], _rbx[2], _rbx[3]),  # à droite du svc
                                        (_rbx[0], _rbx[1], _sbx[0], _rbx[3]),  # à gauche
                                        (_rbx[0], _sbx[3], _rbx[2], _rbx[3]),  # au-dessus
                                        (_rbx[0], _rbx[1], _rbx[2], _sbx[1]),  # en-dessous
                                    ):
                                        if _cbox[2] - _cbox[0] > 1.8 and _cbox[3] - _cbox[1] > 1.8:
                                            _cd = _CarvePoly([
                                                (_cbox[0], _cbox[1]), (_cbox[2], _cbox[1]),
                                                (_cbox[2], _cbox[3]), (_cbox[0], _cbox[3])
                                            ]).intersection(_rt)
                                            if _cd.geom_type == "MultiPolygon":
                                                _cd = max(_cd.geoms, key=lambda g: g.area)
                                            if _cd.geom_type == "Polygon":
                                                _cands.append(_cd)
                                    if _cands:
                                        _best_rect = max(_cands, key=lambda g: g.area)
                                        if _best_rect.area > 8.0:
                                            _rt = _best_rect
                            if _rt.geom_type == "Polygon" and _rt.area > 3.0:
                                _r.polygon_xy = [(round(x, 2), round(y, 2))
                                                 for x, y in list(_rt.exterior.coords)[:-1]]
                                _r.surface_m2 = round(_rt.area, 1)
                        # ── APPROFONDIT UNE CHAMBRE BRIDÉE PAR LE SdB (défaut user
                        #    2026-07-14 : chambre reculée derrière loggia < 10,5 m² car le
                        #    bloc SdB/WC SURDIMENSIONNÉ posé sous elle la clippe). On la
                        #    pousse vers l'INTÉRIEUR (sens _shift) ; la bande gagnée est
                        #    RETIRÉE au SdB/WC (qui reste ≥ 3,85 / 1,3 m² rectangle) et au
                        #    séjour (recalculé plus bas). Chambre reste RECTANGLE. Si le SdB
                        #    ne peut pas rétrécir sans devenir inutilisable → on ne touche
                        #    à rien (pas de casse). Universel (dépend de _shift réel).
                        _un2 = math.hypot(_shift[0], _shift[1]) or 1.0
                        _ux2, _uy2 = _shift[0] / _un2, _shift[1] / _un2
                        for _r in cell.rooms:
                            if "chambre" not in _r.type.value or not _r.polygon_xy \
                                    or len(_r.polygon_xy) < 3 or _r.surface_m2 >= 10.6:
                                continue
                            _pg2 = _CarvePoly(_r.polygon_xy)
                            _blk = _uuC([_CarvePoly(r.polygon_xy) for r in cell.rooms
                                         if r is not _r and r.polygon_xy
                                         and len(r.polygon_xy) >= 3
                                         and "chambre" in r.type.value] + [_lgg]).buffer(0)
                            for _dd2 in (0.25, 0.45, 0.7):
                                _gr = _uuC([_pg2, _translate(_pg2, xoff=_ux2 * _dd2,
                                                             yoff=_uy2 * _dd2)]).buffer(0)
                                _gr = _gr.intersection(_aprime).buffer(0)
                                if _gr.geom_type == "MultiPolygon":
                                    _gr = max(_gr.geoms, key=lambda g: g.area)
                                _gb2 = _gr.bounds if _gr.geom_type == "Polygon" else None
                                if not _gb2:
                                    continue
                                _rc = _CarvePoly([(_gb2[0], _gb2[1]), (_gb2[2], _gb2[1]),
                                                  (_gb2[2], _gb2[3]), (_gb2[0], _gb2[3])])
                                _rc = _rc.intersection(_aprime).difference(_blk).buffer(0)
                                if _rc.geom_type == "MultiPolygon":
                                    _rc = max(_rc.geoms, key=lambda g: g.area)
                                _rcb = _rc.bounds if _rc.geom_type == "Polygon" else None
                                if not _rcb:
                                    continue
                                _rcrr = _rc.area / max(1e-6, (_rcb[2] - _rcb[0])
                                                       * (_rcb[3] - _rcb[1]))
                                if _rc.area < 10.6 or _rcrr < 0.95:
                                    continue
                                _ok2, _shr = True, []
                                for _wr in cell.rooms:
                                    if _wr.type.value not in ("wc", "sdb",
                                                              "salle_de_douche", "wc_sdb"):
                                        continue
                                    if not _wr.polygon_xy or len(_wr.polygon_xy) < 3:
                                        continue
                                    _wp2 = _CarvePoly(_wr.polygon_xy)
                                    if _wp2.intersection(_rc).area < 0.02:
                                        continue
                                    # RECONSTRUIRE le bloc humide en RECTANGLE PROPRE trimmé
                                    # du côté qui fait face à la chambre (sens _shift), au lieu
                                    # de soustraire son polygone : le SdB peut être déjà notché
                                    # (L) par un carving amont → une simple différence garde le
                                    # L (rr<0,9) et bloquait l'approfondissement (apt loggia 02).
                                    # On coupe la bande où la chambre a avancé et on garde une
                                    # boîte pleine largeur → rr≈1,0 garanti.
                                    _pb = _wp2.bounds
                                    if abs(_ux2) >= abs(_uy2):
                                        _wnbox = ((max(_pb[0], _rcb[2]), _pb[1], _pb[2], _pb[3])
                                                  if _ux2 >= 0 else
                                                  (_pb[0], _pb[1], min(_pb[2], _rcb[0]), _pb[3]))
                                    else:
                                        _wnbox = ((_pb[0], max(_pb[1], _rcb[3]), _pb[2], _pb[3])
                                                  if _uy2 >= 0 else
                                                  (_pb[0], _pb[1], _pb[2], min(_pb[3], _rcb[1])))
                                    _wn = _CarvePoly([(_wnbox[0], _wnbox[1]),
                                                      (_wnbox[2], _wnbox[1]),
                                                      (_wnbox[2], _wnbox[3]),
                                                      (_wnbox[0], _wnbox[3])]
                                                     ).intersection(_aprime).buffer(0)
                                    if _wn.geom_type == "MultiPolygon":
                                        _wn = max(_wn.geoms, key=lambda g: g.area)
                                    _wnb = _wn.bounds if _wn.geom_type == "Polygon" else None
                                    _minar = 3.85 if _wr.type.value in (
                                        "sdb", "salle_de_douche") else 1.25
                                    _wnrr = (_wn.area / max(1e-6, (_wnb[2] - _wnb[0])
                                             * (_wnb[3] - _wnb[1]))) if _wnb else 0.0
                                    if _wn.geom_type != "Polygon" or _wn.area < _minar \
                                            or _wnrr < 0.9:
                                        _ok2 = False
                                        break
                                    _shr.append((_wr, _wn))
                                if not _ok2:
                                    continue
                                _r.polygon_xy = [(round(x, 2), round(y, 2))
                                                 for x, y in list(_rc.exterior.coords)[:-1]]
                                _r.surface_m2 = round(_rc.area, 1)
                                for _wr, _wn in _shr:
                                    _wr.polygon_xy = [(round(x, 2), round(y, 2))
                                                      for x, y in list(_wn.exterior.coords)[:-1]]
                                    _wr.surface_m2 = round(_wn.area, 1)
                                break
                        # PRIMAUTÉ PARENTS (gate H10) + SUITE PARENTALE (user
                        # 2026-07-27) : la parents doit RESTER la chambre COLLÉE au
                        # bloc SdB (accessibilité, porte en-suite = intention
                        # « suite parentale » du tiler), PAS devenir « la plus
                        # grande n'importe où » (l'ancien relabel-par-taille
                        # éloignait la parents de la SdB sur les T3 loggia). On
                        # étiquette parents = chambre AU CONTACT du bloc humide ;
                        # sa primauté de SURFACE (H10) est assurée ensuite par le
                        # grow-vers-séjour ci-dessous, appliqué à ELLE.
                        _beds = [r for r in cell.rooms if "chambre" in r.type.value]
                        if len(_beds) >= 2:
                            _par = next((r for r in _beds
                                         if r.type == RoomType.CHAMBRE_PARENTS), None)
                            _wetu2 = _uuC(
                                [_CarvePoly(r.polygon_xy) for r in cell.rooms
                                 if r.type.value in ("wc", "sdb",
                                                     "salle_de_douche", "wc_sdb")
                                 and r.polygon_xy and len(r.polygon_xy) >= 3]
                            ).buffer(0)
                            _tgt = None
                            if not _wetu2.is_empty:
                                _byc = max(
                                    _beds,
                                    key=lambda r: (_CarvePoly(r.polygon_xy)
                                                   .buffer(0.06)
                                                   .intersection(_wetu2).area
                                                   if r.polygon_xy
                                                   and len(r.polygon_xy) >= 3
                                                   else 0.0))
                                if (_CarvePoly(_byc.polygon_xy).buffer(0.06)
                                        .intersection(_wetu2).area > 0.04):
                                    _tgt = _byc
                            if _tgt is None:   # aucun contact SdB → plus grande
                                _tgt = max(_beds, key=lambda r: r.surface_m2)
                            if _par is not None and _tgt is not _par:
                                _par.type, _tgt.type = _tgt.type, _par.type
                                _par.label_fr, _tgt.label_fr = _tgt.label_fr, _par.label_fr
                            # Parents doit être STRICTEMENT > secondaires (H10). En cas
                            # d'ÉGALITÉ (chambres identiques après rectangularisation),
                            # on fait GROSSIR la parents de ~0,6 m vers le séjour (qui
                            # absorbe), en la gardant rectangulaire et sans mordre les
                            # autres pièces.
                            _par = next((r for r in _beds
                                         if r.type == RoomType.CHAMBRE_PARENTS), None)
                            _maxsec = max((r.surface_m2 for r in _beds
                                           if r.type != RoomType.CHAMBRE_PARENTS), default=0.0)
                            if (_par is not None and _par.surface_m2 <= _maxsec + 0.1):
                                _un = math.hypot(_shift[0], _shift[1]) or 1.0
                                _ux, _uy = _shift[0] / _un, _shift[1] / _un
                                _pg = _CarvePoly(_par.polygon_xy)
                                _occ = _uuC(
                                    [_CarvePoly(r.polygon_xy) for r in cell.rooms
                                     if r is not _par and r.polygon_xy
                                     and len(r.polygon_xy) >= 3
                                     and ("chambre" in r.type.value
                                          or r.type.value in ("wc", "sdb",
                                                              "salle_de_douche", "wc_sdb"))]
                                    + [_lgg]).buffer(0)
                                _grown = _uuC([_pg, _translate(
                                    _pg, xoff=_ux * 0.6, yoff=_uy * 0.6)]).buffer(0)
                                _grown = _grown.intersection(_aprime).difference(_occ).buffer(0)
                                if _grown.geom_type == "MultiPolygon":
                                    _grown = max(_grown.geoms, key=lambda g: g.area)
                                _gb = _grown.bounds if _grown.geom_type == "Polygon" else None
                                if (_grown.geom_type == "Polygon"
                                        and _grown.area > _par.surface_m2 + 0.2
                                        and _gb and _grown.area / max(1e-6, (_gb[2] - _gb[0])
                                        * (_gb[3] - _gb[1])) > 0.9):
                                    _par.polygon_xy = [(round(x, 2), round(y, 2))
                                                       for x, y in list(_grown.exterior.coords)[:-1]]
                                    _par.surface_m2 = round(_grown.area, 1)
                            # H10 FINISHER (suite parentale, user 2026-07-27) : si
                            # malgré le grow la parents (collée SdB) reste ≤ une
                            # secondaire, on RABOTE la secondaire côté INTÉRIEUR
                            # (sens _shift = vers le séjour, JAMAIS côté loggia =
                            # sa fenêtre) d'une bande pleine largeur : elle reste
                            # RECTANGLE et ≥ 10,5 ; le séjour (recalculé plus bas)
                            # absorbe la bande. Préférable à déplacer l'étiquette
                            # parents loin de la SdB (accessibilité perdue).
                            _par = next((r for r in _beds
                                         if r.type == RoomType.CHAMBRE_PARENTS), None)
                            if _par is not None:
                                _unf = math.hypot(_shift[0], _shift[1]) or 1.0
                                _uxf, _uyf = _shift[0] / _unf, _shift[1] / _unf
                                for _sr in sorted(
                                        (r for r in _beds if r is not _par),
                                        key=lambda r: -r.surface_m2):
                                    if _par.surface_m2 > _sr.surface_m2 + 0.05:
                                        break        # ordre décroissant → terminé
                                    if not _sr.polygon_xy or len(_sr.polygon_xy) < 3:
                                        continue
                                    _sp = _CarvePoly(_sr.polygon_xy)
                                    _sb = _sp.bounds
                                    _wper = ((_sb[3] - _sb[1])
                                             if abs(_uxf) >= abs(_uyf)
                                             else (_sb[2] - _sb[0]))
                                    _need = _sr.surface_m2 - _par.surface_m2 + 0.25
                                    _cut = _need / max(_wper, 0.5)
                                    if _sr.surface_m2 - _cut * _wper < 10.55:
                                        continue     # pas de marge → ne pas casser
                                    if abs(_uxf) >= abs(_uyf):
                                        _cb = ((_sb[0] + _cut, _sb[1], _sb[2], _sb[3])
                                               if _uxf < 0 else
                                               (_sb[0], _sb[1], _sb[2] - _cut, _sb[3]))
                                    else:
                                        _cb = ((_sb[0], _sb[1] + _cut, _sb[2], _sb[3])
                                               if _uyf < 0 else
                                               (_sb[0], _sb[1], _sb[2], _sb[3] - _cut))
                                    _newp = _sp.intersection(_CarvePoly([
                                        (_cb[0], _cb[1]), (_cb[2], _cb[1]),
                                        (_cb[2], _cb[3]), (_cb[0], _cb[3])])).buffer(0)
                                    if _newp.geom_type != "Polygon" or _newp.area < 10.5:
                                        continue
                                    _sr.polygon_xy = [(round(x, 2), round(y, 2))
                                                      for x, y in
                                                      list(_newp.exterior.coords)[:-1]]
                                    _sr.surface_m2 = round(_newp.area, 1)
                        # ── SNAP RECTANGLE (chambre/wc/sdb) : le recul + la
                        #    rectangularisation laissent des micro-notches (contour à
                        #    8 sommets pour un rectangle quasi-plein rr≥0,99) jamais
                        #    nettoyés (le _clean_ring du tiler a tourné AVANT ce recul).
                        #    On snappe à la bbox EXACTE (aire +≤1 %, comblée côté séjour
                        #    qui est recalculé juste après → aucun chevauchement). Le
                        #    séjour (rr~0,4) n'est PAS touché.
                        from shapely.geometry import box as _snbx
                        for _sr in cell.rooms:
                            if _sr.type in (RoomType.SEJOUR, RoomType.SEJOUR_CUISINE) \
                                    or not _sr.polygon_xy or len(_sr.polygon_xy) < 5:
                                continue
                            _scp = _CarvePoly(_sr.polygon_xy).buffer(0)
                            if _scp.geom_type != "Polygon" or _scp.is_empty:
                                continue
                            _scb = _scp.bounds
                            _scba = (_scb[2] - _scb[0]) * (_scb[3] - _scb[1])
                            if _scba <= 0 or _scp.area / _scba < 0.955:
                                continue
                            _snp = _snbx(*_scb)
                            # ne snappe QUE si la bbox ne mord aucune AUTRE pièce non-séjour
                            # (chambre/service/loggia) ; sinon on garde le contour d'origine.
                            _oth = _uuC([_CarvePoly(r.polygon_xy) for r in cell.rooms
                                         if r is not _sr and r.polygon_xy
                                         and len(r.polygon_xy) >= 3
                                         and r.type not in (RoomType.SEJOUR,
                                                            RoomType.SEJOUR_CUISINE)]).buffer(0)
                            if _snp.intersection(_oth).area > 0.05:
                                continue
                            _sr.polygon_xy = [(round(x, 2), round(y, 2))
                                              for x, y in list(_snp.exterior.coords)[:-1]]
                            _sr.surface_m2 = round(_snp.area, 1)
                        # ── ANTI-ENCLAVEMENT (salon large loggia 2026-07-16) : une chambre
                        #    dont le bloc SdB/WC couvre presque toute l'arête intérieure n'a
                        #    plus assez de contact avec le futur séjour pour SA porte. On
                        #    RÉTRÉCIT le bloc humide EN LARGEUR (bande côté chambre → vers le
                        #    refend) pour rendre ≥ 1,0 m de contact, en gardant la PROFONDEUR
                        #    du SdB (donc utilisable, ≥ 3,8 m²). La bande revient au séjour.
                        _wc_e = next((r for r in cell.rooms if r.type.value in ("wc", "wc_sdb")
                                      and r.polygon_xy and len(r.polygon_xy) >= 3), None)
                        _sdb_e = next((r for r in cell.rooms if r.type.value in
                                       ("sdb", "salle_de_douche")
                                       and r.polygon_xy and len(r.polygon_xy) >= 3), None)
                        if _sdb_e is not None:
                            _wetE = [w for w in (_wc_e, _sdb_e) if w is not None]
                            _wu = _uuC([_CarvePoly(w.polygon_xy) for w in _wetE]).buffer(0)
                            _wbb = _wu.bounds
                            _apb = _apt_g.bounds
                            # axe PROFONDEUR = celui du recul loggia (_shift) ; axe LARGEUR = l'autre.
                            _depth_y = abs(_shift[1]) >= abs(_shift[0])
                            for _b in [r for r in cell.rooms if "chambre" in r.type.value
                                       and r.polygon_xy and len(r.polygon_xy) >= 3]:
                                _bbb = _CarvePoly(_b.polygon_xy).bounds
                                if _depth_y:
                                    _u0b, _u1b, _u0w, _u1w = _bbb[0], _bbb[2], _wbb[0], _wbb[2]
                                    _vBcen = 0.5 * (_bbb[1] + _bbb[3])
                                    _vWcen = 0.5 * (_wbb[1] + _wbb[3])
                                else:
                                    _u0b, _u1b, _u0w, _u1w = _bbb[1], _bbb[3], _wbb[1], _wbb[3]
                                    _vBcen = 0.5 * (_bbb[0] + _bbb[2])
                                    _vWcen = 0.5 * (_wbb[0] + _wbb[2])
                                _uov = min(_u1b, _u1w) - max(_u0b, _u0w)     # recouvrement largeur
                                _freeL = _u0w - _u0b
                                _freeR = _u1b - _u1w
                                if _uov < 0.6 or max(_freeL, _freeR) >= 0.9:
                                    continue      # pas sous le bloc / déjà assez de contact
                                # nouvelle LARGEUR : rendre 1,0 m de libre du plus grand côté
                                if _freeL >= _freeR:
                                    _nU0, _nU1 = _u0b + 1.0, _u1w
                                else:
                                    _nU0, _nU1 = _u0w, _u1b - 1.0
                                _nW = _nU1 - _nU0
                                if _nW < 1.4:
                                    continue
                                # nouvelle PROFONDEUR : arête bloc côté chambre = arête chambre
                                # (0 chevauchement) ; on approfondit VERS LE COULOIR pour l'aire.
                                _need = (3.9 + 1.3) / _nW      # SdB≥3,9 + WC~1,3
                                if _depth_y:
                                    if _vBcen > _vWcen:        # chambre au-dessus (loggia = +y)
                                        _vHi = _bbb[1]; _vLo = max(_apb[1] + 0.05, _vHi - _need)
                                    else:
                                        _vLo = _bbb[3]; _vHi = min(_apb[3] - 0.05, _vLo + _need)
                                    _wcbox = (_nU0, _vLo, _nU1, _vLo + min(0.95, max(0.6, 1.3 / _nW))) \
                                        if _vBcen > _vWcen else \
                                        (_nU0, _vHi - min(0.95, max(0.6, 1.3 / _nW)), _nU1, _vHi)
                                    _sdbbox = (_nU0, _wcbox[3], _nU1, _vHi) if _vBcen > _vWcen \
                                        else (_nU0, _vLo, _nU1, _wcbox[1])
                                else:
                                    if _vBcen > _vWcen:
                                        _vHi = _bbb[0]; _vLo = max(_apb[0] + 0.05, _vHi - _need)
                                    else:
                                        _vLo = _bbb[2]; _vHi = min(_apb[2] - 0.05, _vLo + _need)
                                    _wcbox = (_vLo, _nU0, _vLo + min(0.95, max(0.6, 1.3 / _nW)), _nU1) \
                                        if _vBcen > _vWcen else \
                                        (_vHi - min(0.95, max(0.6, 1.3 / _nW)), _nU0, _vHi, _nU1)
                                    _sdbbox = (_wcbox[2], _nU0, _vHi, _nU1) if _vBcen > _vWcen \
                                        else (_vLo, _nU0, _wcbox[0], _nU1)
                                from shapely.geometry import box as _bxE
                                _sdbp = _bxE(*_sdbbox).intersection(_aprime).buffer(0)
                                if _sdbp.geom_type != "Polygon" or _sdbp.area < 3.85:
                                    continue
                                _sdb_e.polygon_xy = [(round(x, 2), round(y, 2))
                                                     for x, y in list(_sdbp.exterior.coords)[:-1]]
                                _sdb_e.surface_m2 = round(_sdbp.area, 1)
                                if _wc_e is not None:
                                    _wcp = _bxE(*_wcbox).intersection(_aprime).buffer(0)
                                    if _wcp.geom_type == "Polygon" and _wcp.area > 0.8:
                                        _wc_e.polygon_xy = [(round(x, 2), round(y, 2))
                                                            for x, y in list(_wcp.exterior.coords)[:-1]]
                                        _wc_e.surface_m2 = round(_wcp.area, 1)
                                break

                        # Le SÉJOUR absorbe : séjour = (apt − loggia) − toutes les
                        # autres pièces (chambres reculées + service).
                        if _sej_r is not None:
                            _others = _uuC([_CarvePoly(r.polygon_xy) for r in cell.rooms
                                            if r is not _sej_r and r.polygon_xy
                                            and len(r.polygon_xy) >= 3]).buffer(0)
                            _sej_new = _aprime.difference(_others).buffer(0)
                            if _sej_new.geom_type == "MultiPolygon":
                                _sej_new = max(_sej_new.geoms, key=lambda g: g.area)
                            if _sej_new.geom_type == "Polygon" and _sej_new.area > 6.0:
                                _sej_r.polygon_xy = [(round(x, 2), round(y, 2))
                                                     for x, y in list(_sej_new.exterior.coords)[:-1]]
                                _sej_r.surface_m2 = round(_sej_new.area, 1)
                            # ROBUSTESSE : si le séjour recouvre ENCORE une pièce (ex. bloc
                            # SdB déplacé + trou avalé par exterior.coords), on re-soustrait
                            # et on garde la plus grande composante SANS trou (le résidu part
                            # au fallback). Empêche « séjour ∩ SdB » (chevauch, apt loggia 11).
                            _spov = _CarvePoly(_sej_r.polygon_xy).buffer(0)
                            if _spov.intersection(_others).area > 0.3:
                                _spd = _spov.difference(_others).buffer(0)
                                _spd = (max(_spd.geoms, key=lambda g: g.area)
                                        if _spd.geom_type == "MultiPolygon" else _spd)
                                if _spd.geom_type == "Polygon" and _spd.area > 6.0:
                                    _sej_r.polygon_xy = [(round(x, 2), round(y, 2))
                                                         for x, y in list(_spd.exterior.coords)[:-1]]
                                    _sej_r.surface_m2 = round(_spd.area, 1)
                        cell.rooms.append(_Room(
                            id=f"{cell.id}_loggia", type=RoomType.LOGGIA,
                            surface_m2=round(_lgg.area, 1),
                            polygon_xy=[(round(x, 2), round(y, 2))
                                        for x, y in list(_lgg.exterior.coords)[:-1]],
                            orientation=None, label_fr="Loggia", furniture=[]))
                        cell.loggia.polygon_xy = [(round(x, 2), round(y, 2))
                                                  for x, y in list(_lgg.exterior.coords)[:-1]]
                        cell.loggia.surface_m2 = round(_lgg.area, 1)
                        # PORTES/MURS RÉGÉNÉRÉS depuis les pièces DÉCALÉES : sinon les
                        # portes des chambres restent à l'ancienne position (« porte
                        # sur vide ») et une chambre reculée se retrouve « sans porte ».
                        # On rappelle le même moteur que le tiling sur les pièces réelles.
                        try:
                            from core.templates_library.layout_generator import (
                                build_walls_and_openings as _bwo)
                            _bb = _apt_g.bounds
                            # palier_side = côté de la PORTE D'ENTRÉE existante (elle
                            # encode le mur couloir). L'ancienne détection « cour »
                            # renvoyait None pour les apts non adjacents à la cour →
                            # _bwo jamais relancé → portes stale. La porte d'entrée,
                            # elle, existe pour tout logement.
                            _palier = None
                            _pe = next((o for o in (cell.openings or [])
                                        if getattr(o.type, "value", str(o.type)).split(".")[-1]
                                        == "porte_entree"),
                                       None)
                            if _pe is not None:
                                _pw = next((w for w in (cell.walls or [])
                                            if w.id == _pe.wall_id), None)
                                _cc2 = ((_pw.geometry or {}).get("coords")
                                        or (_pw.geometry or {}).get("coordinates")
                                        if _pw is not None else None) or []
                                if len(_cc2) >= 2:
                                    _wax, _way = _cc2[0]
                                    _wbx, _wby = _cc2[-1]
                                    _wdx = _wbx - _wax
                                    _wdy = _wby - _way
                                    _wl = math.hypot(_wdx, _wdy)
                                    _wmx = (_wax + _wbx) / 2
                                    _wmy = (_way + _wby) / 2
                                    if _wl > 1e-6:
                                        for _nn in ((_wdy / _wl, -_wdx / _wl),
                                                    (-_wdy / _wl, _wdx / _wl)):
                                            if (_wmx - cx) * _nn[0] + (_wmy - cy) * _nn[1] > 0:
                                                _palier = _dir_of_normal(_nn[0], _nn[1])
                                                break
                            if _palier is not None:
                                _OPPd = {"sud": "nord", "nord": "sud",
                                         "ouest": "est", "est": "ouest"}
                                _w2, _o2 = _bwo(
                                    cell.rooms, (_bb[0], _bb[1], _bb[2], _bb[3]),
                                    _palier, cell.id, orientations=[_OPPd[_palier]],
                                    footprint=footprint, parcelle=None,
                                    other_cells_polys=None,
                                    voiries=tuple(voirie_orientations)
                                    if voirie_orientations else None)
                                cell.walls = _w2
                                cell.openings = _o2
                        except Exception:
                            pass
                except Exception:
                    pass
            attached += 1
    return attached


def _populate_furniture(rooms) -> None:
    """Pose un mobilier minimal (symbole au centroïde) par type de pièce.

    Données modèle uniquement — le frontend meuble déjà procéduralement chaque
    pièce (FurnitureInRoom switch room.type). Sert aux consommateurs serveur du
    modèle. Idempotent : n'écrase pas un mobilier déjà présent.
    """
    from core.building_model.schemas import Furniture
    from shapely.geometry import Polygon as _FPoly, Point as _FPt
    _BY_TYPE = {
        RoomType.SEJOUR: ["canape", "table"],
        RoomType.SEJOUR_CUISINE: ["canape", "table", "cuisine"],
        RoomType.CUISINE: ["cuisine"],
        RoomType.CHAMBRE_PARENTS: ["lit_double", "armoire"],
        RoomType.CHAMBRE_ENFANT: ["lit_simple", "armoire"],
        RoomType.CHAMBRE_SUPP: ["lit_simple", "armoire"],
        RoomType.SDB: ["lavabo", "douche"],
        RoomType.SALLE_DE_DOUCHE: ["lavabo", "douche"],
        RoomType.WC_SDB: ["lavabo", "wc"],
        RoomType.WC: ["wc"],
    }
    # ANCRE MEUBLE (2026-07-09, prépa 3D) : chaque type occupe une position
    # RELATIVE distincte (fx, fy ∈ [0,1] dans la bbox pièce) + une rotation, pour
    # que le mobilier NE S'EMPILE PLUS au centroïde (rendu 3D inexploitable sinon).
    # Meubles plaqués aux murs (lit/armoire/canapé/cuisine), table au centre, points
    # d'eau répartis. Positions clampées À L'INTÉRIEUR du polygone réel de la pièce.
    _ANCHOR = {
        "canape":     (0.30, 0.80, 0.0),
        "table":      (0.64, 0.52, 0.0),
        "cuisine":    (0.14, 0.35, 90.0),
        "lit_double": (0.33, 0.26, 0.0),
        "lit_simple": (0.28, 0.24, 0.0),
        "armoire":    (0.85, 0.22, 0.0),
        "lavabo":     (0.26, 0.30, 0.0),
        "douche":     (0.74, 0.74, 0.0),
        "wc":         (0.78, 0.30, 0.0),
    }
    for r in rooms:
        if getattr(r, "furniture", None):
            continue  # déjà meublé
        kinds = _BY_TYPE.get(r.type)
        if not kinds or not r.polygon_xy or len(r.polygon_xy) < 3:
            continue
        try:
            pg = _FPoly(r.polygon_xy)
            if not pg.is_valid:
                pg = pg.buffer(0)
        except Exception:
            pg = None
        if pg is None or pg.is_empty:
            continue
        x0, y0, x1, y1 = pg.bounds
        w, h = (x1 - x0), (y1 - y0)
        _inside = pg.representative_point()
        out = []
        for k in kinds:
            fx, fy, rot = _ANCHOR.get(k, (0.5, 0.5, 0.0))
            px, py = x0 + fx * w, y0 + fy * h
            # clamp DANS la pièce : si l'ancre tombe hors du polygone (pièce en L
            # ou étroite), on tire vers un point intérieur jusqu'à être dedans.
            if not pg.buffer(-0.05).contains(_FPt(px, py)):
                placed = False
                for t in (0.35, 0.6, 0.85):
                    qx, qy = px + (_inside.x - px) * t, py + (_inside.y - py) * t
                    if pg.contains(_FPt(qx, qy)):
                        px, py, placed = qx, qy, True
                        break
                if not placed:
                    px, py = _inside.x, _inside.y
            out.append(Furniture(type=k, position_xy=(round(px, 2), round(py, 2)),
                                 rotation_deg=rot))
        r.furniture = out


def _relayout_mono_facade_apts(cells, footprint, voiries=None, circulations=None) -> None:
    """Ré-agence chaque logement MONO-FAÇADE (U : toutes les pièces éclairent la
    cour) selon la logique déterministe figée (LOGIQUE_LAYOUT_MONOFACADE.md) :

    APT = rectangle en repère local (u,v) : u le long de la façade cour (0..W),
    v = profondeur (0 = couloir/accès AVEUGLE ; D = COUR, ~7,8 m).

      - Bande AVANT v∈[D−CHD, D], CHD=min(3,9 ; D−3,0) : PEIGNE sur la cour =
        N chambres (colonnes chw∈[2,7;3,4]) + un NEZ DE SÉJOUR (colonne salon
        avec baie). Tout touche la cour → 0 chambre borgne.
      - Bande ARRIÈRE v∈[0, D−CHD] : le séjour/cuisine s'y prolonge (open-plan,
        borgne acceptée = cuisine ouverte) + bloc service (entrée+SdB~5+WC~1,5)
        collé au nez. PAS de cellier.
      - SÉJOUR_CUISINE = nez (pleine hauteur, touche cour ET couloir=entrée) ∪
        prolongement arrière → un seul volume en L qui distribue les chambres
        (chacune ouvre sur l'arête v=D−CHD) → 0 dégagement.
      - Fermeture largeur : Wns = W − N·chw ; si Wns<2,0 → chw=(W−2,0)/N.
      - Plafond séjour par typo : T2≤30, T3≤34, T4≤42, T5≤48.
      - TYPO = f(façade cour) : nb_ch = clamp(floor(W_util/3,0), surface). Un T4
        exige ~12-13 m de façade → sinon retype T3.
      - Coin en L : la poche arrière profonde (derrière la cage, hors projection
        cour) est absorbée dans le séjour ouvert (bornée au plafond typo).

    Universel (4 orientations) : la façade cour = ``c.orientation`` (posée par le
    dispatcher). Tuilage 100 % (union pièces = contour apt, 0 trou), 0 chevauch.
    """
    from shapely.geometry import Polygon as _P
    from shapely.geometry import box as _box
    from shapely.ops import unary_union as _uu
    from core.building_model.schemas import Room

    # Union brute de la CIRCULATION COMMUNE (couloir/palier/cages) — sert à
    # RECULER tout bloc humide qui fronterait le palier (défaut #2 user) : on
    # rogne la SdB/WC de _CORR_INSET sur toute arête au contact du couloir, le
    # strip libéré revenant au séjour (qui devient le seul à toucher le palier).
    _corr_u = None
    if circulations:
        _cp = [_P(cc.polygon_xy) for cc in circulations
               if getattr(cc, "polygon_xy", None) and len(cc.polygon_xy) >= 3]
        if _cp:
            _corr_u = _uu(_cp)
    _CORR_INSET = 0.4  # bande séjour insérée entre couloir et bloc humide (m)

    _lights = footprint.boundary
    # CHAMBRES RÉÉQUILIBRÉES (défaut user 2026-07-06) : une chambre ne doit pas être
    # une cellule de 10,2 m² pendant que le séjour fait 60 m². On relève la largeur
    # MINI d'une chambre à 2,72 m (≥ 2,72 × 4,0 ≈ 10,9 m²) — au-dessus du plancher
    # gate 10,5 et du seuil « tunnel » 2,6 m — sans exiger 2,85 m qui ne loge plus
    # 4 chambres dans une façade T5 étroite (12,6 m). La profondeur CHD (~4,0-4,3 m)
    # porte l'aire à ~11-12 m² ; la Ch.PARENTS élargie dépasse 13 m².
    _CHW_MIN, _CHW_MAX = 2.72, 3.6
    _WNS_MIN = 2.0
    _SVC = [(RoomType.ENTREE, 3.0), (RoomType.SDB, 5.0), (RoomType.WC, 1.5)]
    _SVC_AREA = sum(a for _, a in _SVC)
    # Plafonds séjour SOUS le seuil de la vérif (T2 34/T3 40/T4 58/T5 70) avec
    # ~2 m² de marge. Caps RELEVÉS : l'apt de coin garde son grand séjour ouvert
    # (coin aveugle absorbé, T4 haut de gamme) SANS carve — la séparation d'une
    # cuisine ne se déclenche qu'au-delà de ces plafonds (cas très gros coin).
    # Caps RESSERRÉS (2026-07-03, validé user) : un séjour ne doit pas être obèse.
    # Le gate exige T4≤40 / T5≤48 ; on plafonne ~1,5 m² en dessous pour rester
    # sous le seuil après arrondi. Au-delà, une cuisine ouverte est séparée (cf.
    # bloc plus bas) → mais avec l'anti-coin-obèse (layout_l), les slots ne sont
    # plus assez gros pour déclencher ce carve : séjours dimensionnés d'emblée.
    # Caps SÉJOUR/CUISINE RÉÉQUILIBRÉS (défaut user 2026-07-06) : un séjour de
    # promoteur, pas un séjour obèse qui affame les chambres. Cibles indicatives
    # user : T2 ~32 / T3 ~34 / T4 ~42 / T5 ~50 m². On plafonne À la cible ; la
    # fermeture surface (plus bas) APPROFONDIT les chambres jusqu'à passer sous ce
    # cap → l'excédent va aux chambres (~12 m²). Une seule pièce à vivre (open-plan).
    _SEJ_CAP = {Typologie.T2: 32.0, Typologie.T3: 34.0,
                Typologie.T4: 42.0, Typologie.T5: 50.0}
    # ── HARNAIS DE NON-RÉGRESSION (env-gated, INERT en production) ──────────────
    # REVERT_V8_SIZE reproduit le dimensionnement v8 (séjours obèses T5 62 / T4 52,
    # chambres 10,2 m² au plancher 2,6 m, pas de profondeur relevée) → prouve que
    # les gates H-SEJ-CAP et H-CH-MIN FIRENT sur l'état v8. Jamais actif en prod.
    import os as _os_sz
    if _os_sz.environ.get("REVERT_V8_SIZE"):
        _SEJ_CAP = {Typologie.T2: 40.0, Typologie.T3: 42.0,
                    Typologie.T4: 52.0, Typologie.T5: 62.0}
        _CHW_MIN, _CHW_MAX = 2.6, 3.4
    _TYPO_NCH = {Typologie.T2: 1, Typologie.T3: 2, Typologie.T4: 3, Typologie.T5: 4}
    _NCH_TYPO = {1: Typologie.T2, 2: Typologie.T3, 3: Typologie.T4, 4: Typologie.T5}
    _CH_TYPES = [RoomType.CHAMBRE_PARENTS, RoomType.CHAMBRE_ENFANT,
                 RoomType.CHAMBRE_SUPP, RoomType.CHAMBRE_SUPP]

    for c in cells:
        if c.type != CelluleType.LOGEMENT or len(c.polygon_xy) < 3:
            continue
        apt = _P(c.polygon_xy)
        mnx, mny, mxx, mxy = apt.bounds
        # apt ~rectangulaire (les apts U le sont). Sinon on laisse.
        bbox_area = (mxx - mnx) * (mxy - mny)
        if bbox_area <= 0 or apt.area / bbox_area < 0.72:
            continue
        cour_side = (c.orientation or [None])[0]
        if cour_side not in ("sud", "nord", "est", "ouest"):
            continue

        # ── Repère local (u,v). v=0 au COULOIR (côté opposé à la cour), v=D à la
        #    COUR. u le long de la façade. Mapping (u,v)->monde selon cour_side.
        if cour_side in ("sud", "nord"):
            W = mxx - mnx           # façade le long de x
            D = mxy - mny
        else:
            W = mxy - mny           # façade le long de y
            D = mxx - mnx

        def _wbox(u0, u1, v0, v1):
            """u le long de la façade (0..W), v profondeur (0=couloir, D=cour)."""
            if cour_side == "sud":     # cour = mny (bas) ; v croît vers -y ? non :
                # cour au bord y le plus proche du pourtour. Pour 'sud' la cour
                # est au sud (y=mny) : v=D -> y=mny, v=0 -> y=mxy.
                return _box(mnx + u0, mxy - v1, mnx + u1, mxy - v0)
            if cour_side == "nord":    # cour = mxy (haut) : v=D -> y=mxy
                return _box(mnx + u0, mny + v0, mnx + u1, mny + v1)
            if cour_side == "ouest":   # cour = mnx : v=D -> x=mnx
                return _box(mxx - v1, mny + u0, mxx - v0, mny + u1)
            return _box(mnx + v0, mny + u0, mnx + v1, mny + u1)  # est : cour=mxx

        # segment ÉCLAIRÉ le long de la façade (là où l'arête cour touche le
        # pourtour extérieur) : borne la largeur utile W_util et son offset u0.
        _EPS = 0.15
        if cour_side == "sud":
            fac = _box(mnx, mny, mxx, mny + _EPS)
        elif cour_side == "nord":
            fac = _box(mnx, mxy - _EPS, mxx, mxy)
        elif cour_side == "ouest":
            fac = _box(mnx, mny, mnx + _EPS, mxy)
        else:
            fac = _box(mxx - _EPS, mny, mxx, mxy)
        lit = fac.intersection(_lights.buffer(0.2))
        if lit.is_empty:
            continue
        lb = lit.bounds
        if cour_side in ("sud", "nord"):
            u_lo, u_hi = lb[0] - mnx, lb[2] - mnx
        else:
            u_lo, u_hi = lb[1] - mny, lb[3] - mny
        W_util = u_hi - u_lo
        if W_util < _CHW_MIN + 0.5 or D < 5.0:
            continue

        # ── CÔTÉ DU BLOC SERVICE (SdB+WC) : jamais sur une FAÇADE (défaut apt de
        #    coin, H-TYPE 2026-07-06). Le service est posé par défaut à l'extrémité
        #    HAUTE de u (suite parentale). Mais dans un apt de COIN, l'extrémité
        #    haute de u peut être une SECONDE façade (ex. le T3 d'angle nord+est :
        #    u-max = arête est = rue) → la SdB y volerait le jour. On teste les 2
        #    extrémités u contre le pourtour du footprint ; si le côté HAUT-u est une
        #    façade et le côté BAS-u ne l'est pas, on ANCRE le service en BAS-u.
        #    Les chambres restent sur la façade cour ; seule la position du bloc
        #    service borgne bascule → SdB/WC toujours côté aveugle. Universel.
        _EDGE = 0.25
        if cour_side in ("sud", "nord"):
            _lo_edge = _box(mnx - _EDGE, mny, mnx + _EDGE, mxy)     # u=0 → ouest
            _hi_edge = _box(mxx - _EDGE, mny, mxx + _EDGE, mxy)     # u=W → est
        else:
            _lo_edge = _box(mnx, mny - _EDGE, mxx, mny + _EDGE)     # u=0 → sud
            _hi_edge = _box(mnx, mxy - _EDGE, mxx, mxy + _EDGE)     # u=W → nord
        # LONGUEUR de façade sur chaque extrémité u (pas booléen : un apt de coin
        # a un petit bout de façade cour aux DEUX extrémités, mais un seul côté est
        # une VRAIE seconde façade pleine hauteur = rue). On compare les longueurs.
        _lo_flen = _lo_edge.intersection(_lights.buffer(0.2)).length
        _hi_flen = _hi_edge.intersection(_lights.buffer(0.2)).length
        # service au BAS-u si le HAUT-u porte NETTEMENT plus de façade (seconde
        # façade rue au bout haut) → la SdB borgne bascule côté aveugle (bas-u).
        _svc_at_low_u = _hi_flen > _lo_flen + 1.5

        # ── ANCRAGE DU BLOC HORS COULOIR (défaut #2, Family 2 : bras
        #    perpendiculaire du L touchant le côté de l'apt). Le bloc humide est
        #    ancré au bout u opposé au nez de séjour : HAUT-u par défaut, BAS-u si
        #    _svc_at_low_u. Il doit s'appuyer sur un mur VOISIN/MITOYEN, JAMAIS sur
        #    la circulation commune (sinon il fronte le couloir latéralement, ou
        #    devient un îlot entouré de séjour = trou en anneau non rendable). On
        #    MESURE le contact couloir de chaque arête u-extrême ; si le côté
        #    d'ancrage courant borde le couloir et l'autre non, on BASCULE l'ancrage.
        if _corr_u is not None and not _corr_u.is_empty:
            if cour_side in ("sud", "nord"):
                _lo_uedge = _box(mnx - 0.20, mny, mnx + 0.20, mxy)   # u=0
                _hi_uedge = _box(mxx - 0.20, mny, mxx + 0.20, mxy)   # u=W
            else:
                _lo_uedge = _box(mnx, mny - 0.20, mxx, mny + 0.20)   # u=0
                _hi_uedge = _box(mnx, mxy - 0.20, mxx, mxy + 0.20)   # u=W
            try:
                _lo_corr = _lo_uedge.intersection(_corr_u).area
                _hi_corr = _hi_uedge.intersection(_corr_u).area
            except Exception:
                _lo_corr = _hi_corr = 0.0
            _anchor_hi = not _svc_at_low_u    # côté d'ancrage courant
            _anchor_corr = _lo_corr if not _anchor_hi else _hi_corr
            _other_corr = _hi_corr if not _anchor_hi else _lo_corr
            # bascule si le côté d'ancrage borde le couloir et l'autre nettement moins.
            if _anchor_corr > 0.15 and _other_corr < _anchor_corr - 0.15:
                _svc_at_low_u = not _svc_at_low_u

        # ── TYPO = f(façade cour utile) + surface. N = nb chambres tenables (+
        #    nez séjour). On utilise un pas de 2,6 m (chambre mini réaliste, un
        #    poil sous _CHW_MIN) pour le COMPTAGE : ainsi ~10,5 m de cour tient 3
        #    chambres → T4 (les chambres réelles restent ≥ 2,6 m). Sinon ~12-13 m
        #    seraient exigés et le bandeau ne sortirait jamais de T4.
        _CH_COUNT_STEP = 2.6
        n_by_facade = int((W_util - _WNS_MIN + 0.35) / _CH_COUNT_STEP)  # chambres + nez
        area = c.surface_m2 or apt.area
        n_by_area = int((area - 22.0) / 18.0) + 1
        # PLAFOND 3 CHAMBRES (décision user 2026-07-15) : plus de T5 d'angle. Sur
        # 12,6 m mono-façade, 4 chambres ne laissent ~1,5 m de nez = pas de vrai
        # salon devant la fenêtre. En T4 le linéaire libéré va au SALON (bloc
        # « SALON GÉNÉREUX » + `_nez_floor` plus bas → nez ~4,3 m).
        N = max(1, min(3, n_by_facade, n_by_area))
        typo = _NCH_TYPO[N]

        # Profondeur bande avant (chambres) RELEVÉE (défaut user 2026-07-06) :
        # chambres ~12 m² au lieu de 10,2. On part plus profond (4,0 m). La fermeture
        # surface peut monter jusqu'à _CHD_MAX (4,3 m) : au-delà, une chambre
        # deviendrait un tunnel profond disproportionné. Le reste de l'excédent séjour
        # est absorbé en LARGEUR (chambres élargies), pas en profondeur infinie.
        _CHD_MAX = 4.3
        CHD = min(4.0, D - 3.0)           # profondeur bande avant (chambres)
        CHD = max(3.6, CHD)               # au moins 3,6 m de profondeur chambre
        if _os_sz.environ.get("REVERT_V8_SIZE"):   # v8 : chambres plus fines/moins profondes
            _CHD_MAX = 3.9
            CHD = max(3.4, min(3.9, D - 3.0))

        # ── Fermeture largeur (spec §2/§3). Wns = nez séjour ; chw = chambres.
        chw = (W_util - _WNS_MIN) / N
        chw = max(_CHW_MIN, min(_CHW_MAX, chw))
        Wns = W_util - N * chw
        if Wns < _WNS_MIN:
            chw = (W_util - _WNS_MIN) / N
            Wns = _WNS_MIN
        if chw < _CHW_MIN - 0.15:
            # trop étroit pour N chambres → descend la typo
            N = max(1, int((W_util - _WNS_MIN) / _CHW_MIN))
            typo = _NCH_TYPO[N]
            chw = max(_CHW_MIN, (W_util - _WNS_MIN) / N)
            Wns = max(_WNS_MIN, W_util - N * chw)

        # ── SALON GÉNÉREUX DEVANT LA FENÊTRE (user 2026-07-15) : le nez de séjour
        #    (colonne éclairée = le salon) vise ~3,0-4,4 m (canapé + TV). Le surplus
        #    de façade va au SALON, pas à des chambres obèses. `_nez_floor` = plancher
        #    que NI la fermeture-surface NI le grow parents ne franchissent. Clampé
        #    pour garder les chambres ≥ _CHW_MIN.
        # SALON LARGE DEVANT LA LOGGIA sur TOUS les apts avec chambres (N≥2, T3
        # inclus — décision user 2026-07-16) : logique LARGEUR↔PROFONDEUR. On vise un
        # nez de salon ~2,8-3 m (canapé + recul TV) sur la façade éclairée ; les
        # chambres RÉTRÉCISSENT jusqu'au mini (_CHW_MIN) pour le libérer, et le
        # plancher CHD plus bas les APPROFONDIT pour rester ≥ 10,5 m² (surface
        # récupérée en longueur). `_nez_floor` = plancher que NI la fermeture-surface
        # NI le grow parents ne franchissent.
        if N >= 2:
            _SALON_TARGET = min(4.4, max(2.9, 0.34 * W_util))
            _nez_floor = max(_WNS_MIN, min(_SALON_TARGET, W_util - N * _CHW_MIN))
        else:
            _nez_floor = _WNS_MIN
        if Wns < _nez_floor:
            chw = max(_CHW_MIN, (W_util - _nez_floor) / N)
            Wns = W_util - N * chw

        # ── SALON GÉNÉREUX DEVANT LA FENÊTRE (user 2026-07-15 : « créer un vrai
        #    espace salon, assez large pour canapé + TV sans se casser la nuque »).
        #    Le surplus de façade va au NEZ DE SÉJOUR (le salon éclairé), PAS à des
        #    chambres obèses : on RÉTRÉCIT les chambres jusqu'à _CHW_MIN pour élargir
        #    le nez vers une cible ~3,0-4,4 m (canapé + recul TV). Sans effet quand
        #    les chambres sont déjà au mini (façade étroite) ni sur les T2 (déjà
        #    grand salon). Garantit chambres ≥ _CHW_MIN (≥ 11 m² à CHD ~4,1).

        # ── FERMETURE SURFACE (spec §2 « règle de fermeture ») : on estime le
        #    séjour = nez (Wns×D) + cuisine arrière ((W_util−Wns)×back_d) − svc,
        #    et on APPROFONDIT les chambres (↑ CHD, ↓ back_d) jusqu'à passer sous
        #    le plafond typo. Cela transfère l'excédent de la cuisine vers la
        #    profondeur des chambres (qui gardent leur fenêtre) → séjour ≤ cap
        #    SANS trou ni chambre borgne. Chambre profondeur bornée à 4,9 m.
        _svc_est = _SVC_AREA
        _cap0 = _SEJ_CAP[typo]
        for _ in range(12):
            back_d = D - CHD
            _sej_est = Wns * D + (W_util - Wns) * back_d - _svc_est
            if _sej_est <= _cap0 + 0.5 or CHD >= _CHD_MAX or back_d <= 2.6:
                break
            CHD = min(_CHD_MAX, CHD + 0.2)
        # si toujours trop (apt très profond / nez large), on rogne le nez Wns
        # jusqu'au PLANCHER SALON `_nez_floor` (PAS en dessous : le salon éclairé
        # reste large — user 2026-07-15). Le reste de façade va aux chambres.
        for _ in range(12):
            back_d = D - CHD
            _sej_est = Wns * D + (W_util - Wns) * back_d - _svc_est
            if _sej_est <= _cap0 + 0.5 or Wns <= _nez_floor + 0.05:
                break
            Wns = max(_nez_floor, Wns - 0.2)
            chw = (W_util - Wns) / N

        # ── Construit les rectangles en (u,v). u part de u_lo (segment éclairé).
        rects = []          # (kind, u0, u1, v0, v1)  kind: 'sej'|('ch',i)|RoomType
        # NEZ DE SÉJOUR : colonne pleine hauteur (v 0..D), fenêtre cour (v=D),
        # entrée en bas (v=0, couloir). Il DÉMARRE au bord de l'apt (u=0) pour
        # ABSORBER le coin aveugle (u[0, u_lo], derrière la cage) dans le séjour
        # ouvert profond → tuilage 100 % même sur l'apt d'extrémité du bandeau.
        # ── LARGEURS CHAMBRES DIFFÉRENCIÉES parents > secondaires (défaut #4, H10) ─
        # La Ch.PARENTS (posée en DERNIER dans le peigne, cf. _ch_seq plus bas :
        # u max = collée au bloc SdB → suite parentale) doit être STRICTEMENT plus
        # grande que les ENFANT/SUPP. Toutes partageant la profondeur CHD, on
        # différencie par la LARGEUR. Deux leviers, appliqués AVANT de poser le nez
        # (pour préserver le tuilage 100 %) :
        #   (a) on retire _dw à chaque secondaire (bornée ≥ _CHW_SEC_FLOOR, au-
        #       dessus du seuil « tunnel » 2,6 m du gate) → donné à la parents ;
        #   (b) si chw est déjà au plancher (T4/T5 étroits, aucune marge en (a)),
        #       la parents EMPRUNTE _grow au NEZ de séjour (Wns), qui reste ≥
        #       _WNS_MIN. Le nez rétréci reste un grand séjour ouvert profond.
        # Garantit parents > secondaires pour tout N≥2 (largeur ou nez). N==1 (T2,
        # 1 chambre = parents) : rien à différencier. Universel (toute L).
        _ch_widths = [chw] * N
        if N >= 2:
            # Parents ≤ 3,8 m de large (× CHD ~4,2 ≈ 16 m² max) : une chambre
            # parentale généreuse (≥13 m²) mais PAS une pièce obèse de 22 m².
            _CHW_PARENTS_MAX = 3.8
            # Plancher secondaire = 2,62 m (juste au-dessus du seuil « tunnel » 2,60 m
            # du gate) : une secondaire ≥ 2,62 × CHD(~4,1) ≈ 10,7 m² (rétrécie MAIS
            # rallongée en profondeur — logique largeur↔profondeur user 2026-07-16).
            # Ce plancher BAS est essentiel : il permet à la PRIMAUTÉ PARENTS de se
            # faire par REDISTRIBUTION de largeur (2163, nez PRÉSERVÉ) au lieu de
            # l'EMPRUNT AU NEZ (2182) qui rétrécissait le salon de la loggia (2,71→2,31).
            _CHW_SEC_FLOOR = 2.62
            _dw = min(0.7, max(0.40, chw * 0.16))
            _dw = min(_dw, max(0.0, chw - _CHW_SEC_FLOOR))             # secondaire ≥ plancher
            _dw = min(_dw, max(0.0, (_CHW_PARENTS_MAX - chw) / max(1, N - 1)))  # parents ≤ max
            if _dw > 0.015:
                _ch_widths = [chw - _dw] * (N - 1) + [chw + _dw * (N - 1)]
            # ── PRIMAUTÉ PARENTS PAR LARGEUR, robuste (défaut user 2026-07-06) ──
            # Le gate H10 exige Ch.PARENTS > secondaires. Sur les apts à façade
            # ÉTROITE (T5 12,6 m : chw ≤ plancher, aucune marge en (a)), on ÉLARGIT
            # la parents en EMPRUNTANT au NEZ de séjour (Wns), abaissé jusqu'à un
            # plancher SÉJOUR ouvert de 1,4 m (le nez reste ouvert, le gros séjour est
            # derrière). La parents (u-max, collée au bloc SdB = suite parentale) passe
            # ainsi de 10,6 à ~12,6 m² > secondaires. Pas de bonus de PROFONDEUR : le
            # bloc SdB/WC plaqué au refend occupe la bande arrière sous la parents →
            # un bonus vertical la ferait chevaucher le bloc. Universel (tout N≥2).
            _par_w_now = _ch_widths[-1]
            _sec_w_now = max(_ch_widths[:-1]) if N >= 2 else 0.0
            # Le grow parents (H10 : parents > secondaires) peut emprunter au nez, mais
            # PAS sous (_nez_floor − 0,4) : le salon reste large (~3,9 m) tout en laissant
            # ~0,4 m pour élargir la parentale et satisfaire H10.
            _NEZ_SEJOUR_FLOOR = (2.0 if _os_sz.environ.get("REVERT_V8_SIZE")
                                 else max(1.4, _nez_floor - 0.4))
            if (not _os_sz.environ.get("REVERT_V8_SIZE")) \
                    and _par_w_now <= _sec_w_now + 0.10 and Wns > _NEZ_SEJOUR_FLOOR + 0.05:
                _grow = min(0.6, _CHW_PARENTS_MAX - _par_w_now, Wns - _NEZ_SEJOUR_FLOOR)
                if _grow > 0.08:
                    Wns = Wns - _grow
                    _ch_widths = [chw] * (N - 1) + [_ch_widths[-1] + _grow]
        # ── PLANCHER SURFACE CHAMBRE (défaut user 2026-07-14 : chambres 10,0-10,1
        #    < 10,5 sur apts étroits). La chambre la PLUS ÉTROITE (largeur min du
        #    peigne) doit atteindre ≥ 10,7 m². On APPROFONDIT CHD juste ce qu'il
        #    faut, borné pour que la bande arrière loge encore le bloc service
        #    (back_d ≥ 2,6 m) et sans tunnel (≤ 4,6 m). Universel (dépend de la
        #    largeur réelle du peigne, jamais figé). N'abaisse JAMAIS CHD.
        _min_chw = min(_ch_widths) if _ch_widths else _CHW_MIN
        _chd_need = 10.7 / max(_min_chw, 1.0)
        CHD = max(CHD, min(_chd_need, D - 2.6, 4.6))
        back_d = D - CHD
        # NEZ DE SÉJOUR : colonne pleine hauteur (v 0..D), fenêtre cour (v=D),
        # entrée en bas (v=0, couloir). Il DÉMARRE au bord de l'apt (u=0) pour
        # ABSORBER le coin aveugle (u[0, u_lo], derrière la cage) dans le séjour
        # ouvert profond → tuilage 100 % même sur l'apt d'extrémité du bandeau.
        u = u_lo
        rects.append(("sej", 0.0, u + Wns, 0.0, D))
        _nez0, _nez1 = 0.0, u + Wns
        u += Wns
        # CHAMBRES : peigne sur la cour, v [D−CHD, D]. La DERNIÈRE (i=N−1) = parents,
        # collée au bloc SdB (u-max) = suite parentale ; sa primauté vient de la
        # LARGEUR (cf. différenciation ci-dessus), pas d'un bonus de profondeur.
        _ch_u0 = u
        for i in range(N):
            _cw = _ch_widths[i]
            rects.append((("ch", i), u, u + _cw, D - CHD, D))
            u += _cw
        _ch_u1 = u
        # BANDE ARRIÈRE derrière les chambres v [0, D−CHD] : cuisine ouverte
        # (rattachée séjour) + service compact collé au nez. Service dans un
        # coin de la bande arrière côté nez (u proche de _ch_u0), profondeur
        # ajustée ; le reste = prolongement séjour (open-plan).
        back_d = D - CHD
        # ── BLOC SERVICE OPEN-PLAN (gabarit validé user 2026-07-06) ──────────
        # PLUS DE PIÈCE « ENTRÉE » FERMÉE. L'entrée = une PORTE_ENTREE sur le mur
        # COULOIR (v=0) qui ouvre DIRECTEMENT dans le SÉJOUR/CUISINE (pas de sas).
        # Le service = UN BLOC COMPACT BORGNE (SdB ~4,7 m² + WC ~1,6 m²), collé au
        # mur couloir (v=0, là où arrive la porte) dans le coin haut-u (côté
        # aveugle, sous la Ch.PARENTS), JAMAIS sur une arête façade (v=D=cour).
        #   - Le bloc occupe u[_cuis_u1, _ch_u1] × v[0, svc_d] avec svc_d COMPACT
        #     (~2,3 m) → SdB+WC ≈ 6,3 m² (pas 11 m²), un vrai petit bloc humide.
        #   - WC (bas-u, étroit) + SdB (haut-u, large, collée Ch.PARENTS =
        #     suite parentale) côte à côte, tous deux touchant le couloir (v=0).
        #   - Le SÉJOUR_CUISINE absorbe TOUT le reste de la bande arrière
        #     (u[_ch_u0, _cuis_u1] pleine profondeur + le strip v[svc_d, back_d]
        #     au-dessus du bloc) → il touche À LA FOIS la façade (nez, v=D) ET le
        #     mur couloir (v=0) sur toute la largeur hors bloc humide. C'EST LA
        #     PREUVE DE L'OPEN-PLAN : rien de fermé entre la porte et le séjour.
        # Universel (4 orientations ; miroir U appliqué en aval).
        _svc_bandw = (_ch_u1 - _ch_u0)     # largeur dispo de la bande arrière
        # LARGEUR du bloc service = ~1 colonne de chambre (côté haut-u, sous la
        # Ch.PARENTS). Le bloc ne couvre QU'UNE chambre : les autres chambres
        # gardent leur arête basse au contact du séjour (desservies, 0 borgne).
        _chw_svc = _svc_bandw / max(N, 1)
        # RECUL du couloir (v) : le bloc perd ~0,5 m de profondeur → on relève la
        # cible d'aire pour que SdB reste ≥3,8 m² (H7) après recul (profondeur ~2,1 m).
        _SVC_TARGET_AREA = 7.4
        _SVC_DEPTH = min(2.6, max(1.8, back_d))        # bloc humide compact (borgne)
        svc_w = _SVC_TARGET_AREA / _SVC_DEPTH           # largeur pour ~7,4 m²
        svc_w = min(max(2.4, svc_w), _chw_svc * 1.6, _svc_bandw)
        if N == 1:
            # T2 : 1 seule chambre = la parents. Bloc adossé à côté (haut-u) ;
            # la chambre reste desservie par le séjour sur son autre arête.
            svc_w = min(max(2.4, _SVC_TARGET_AREA / _SVC_DEPTH),
                        _svc_bandw * 0.8, _svc_bandw)
        svc_d = min(_SVC_DEPTH, back_d)                # profondeur réelle du bloc
        # WC étroit ~1,6 m² (bas-u) ; SdB prend le reste (haut-u, collée Ch.PARENTS).
        _wc_w0 = min(max(1.6 / max(svc_d, 1.4), 0.8), 1.3,
                     max(0.8, svc_w - (4.4 / max(svc_d, 1.4))))
        if svc_w > 1.0 and back_d > 1.6:
            _cuis_u1 = _ch_u1 - svc_w
            import os as _os_rt
            if _os_rt.environ.get("REVERT_V6"):
                # ── ÉTAT v6 (revert-test UNIQUEMENT) : sas ENTREE fermé + SdB
                #    pleine profondeur (8,6 m²). Reproduit le défaut que le
                #    H-TYPE durci DOIT faire FIRER. Jamais actif en production.
                _E_D = max(1.3, min(1.7, back_d * 0.38))
                if _cuis_u1 - _ch_u0 > 0.3:
                    rects.append(("sej", _ch_u0, _cuis_u1, 0.0, back_d))
                rects.append((RoomType.ENTREE, _cuis_u1, _ch_u1, 0.0, _E_D))
                _wc_u1 = _cuis_u1 + _wc_w0
                rects.append((RoomType.WC, _cuis_u1, _wc_u1, _E_D, back_d))
                rects.append((RoomType.SDB, _wc_u1, _ch_u1, _E_D, back_d))
            else:
                # ── BLOC HUMIDE PLAQUÉ CONTRE LE REFEND, BORGNE (défaut user 2026-07-06) ──
                # RÈGLE user : le WC/SdB ne DOIT PAS flotter en îlot au milieu du
                # séjour (entouré de séjour sur ~4 côtés). Il doit être PLAQUÉ contre
                # un mur (≥1 arête pleine partagée avec le périmètre de l'apt), tout en
                # restant BORGNE : pas sur le couloir commun, pas sur façade.
                # SOLUTION : bloc TALL-NARROW flush contre l'arête u-max (_ch_u1) =
                # mur mitoyen/refend/voisin. Le bloc est ÉTROIT en u (svc_wU ≈ 1,9 m)
                # et PROFOND en v (svc_dV ≈ 3,9 m) → sa GRANDE arête (v, longueur
                # svc_dV) est COLLÉE au refend sur toute sa hauteur. Il partage donc
                # une arête pleine ≥ svc_dV avec le périmètre → PLAQUÉ, plus d'îlot.
                # Il garde un petit RETRAIT du mur couloir (v=0, _SVC_V0_GAP) et de la
                # façade (v=D) : borgne côté couloir, ne vole pas le jour. WC (bas-v)
                # + SdB (haut-v, collée à la Ch.PARENTS = suite parentale) EMPILÉS le
                # long du refend. Le SÉJOUR occupe TOUTE la colonne u-min du bloc
                # (u[_cuis_u1, _ch_u1] est le bloc ; u<_cuis_u1 = séjour) → les portes
                # WC/SdB ouvrent vers le séjour (arête u=_cuis_u1). Le séjour touche le
                # couloir (v=0) via le nez + la bande cuisine → open-plan préservé.
                # Universel (4 orientations ; miroir U en aval).
                _SVC_V0_GAP = 0.35          # retrait mur couloir (borgne, pas plaqué palier)
                # Fallback : si le refend u-max est en réalité le couloir commun à ce u
                # (cas dégénéré non attendu vu _svc_at_low_u), H-SVC-CORR bloque ; ici
                # on garde le design refend-plaqué (universel).
                svc_wU = min(max(1.7, _SVC_TARGET_AREA / max(back_d - _SVC_V0_GAP - 0.2, 1.8)),
                             _svc_bandw)     # largeur en u (contre le refend)
                svc_dV = min(_SVC_TARGET_AREA / max(svc_wU, 1.0),
                             back_d - _SVC_V0_GAP - 0.15)   # profondeur en v
                svc_dV = max(svc_dV, 2.8)   # SdB+WC empilés tiennent (≥2,8 m)
                svc_dV = min(svc_dV, back_d - _SVC_V0_GAP - 0.10)
                _svc_v0 = _SVC_V0_GAP
                _svc_v1 = _svc_v0 + svc_dV
                _cuis_u1 = _ch_u1 - svc_wU   # bord u-min du bloc (côté séjour)
                # ÉTAT v8 (revert-test UNIQUEMENT) : bloc COMPACT-CARRÉ RECULÉ, entouré
                # de séjour sur ~4 côtés (îlot flottant) = le défaut que le gate
                # H-SVC-PLAQUE DOIT faire FIRER. Jamais actif en production.
                if _os_rt.environ.get("REVERT_V7_SVC"):
                    # ── ÉTAT « bloc FRONTE le couloir » (revert-test UNIQUEMENT) : le
                    #    bloc humide est posé à v=0 côté SÉJOUR/ENTRÉE (u-min du peigne),
                    #    là où la circulation commune longe l'arête v=0 → le WC/SdB
                    #    FRONTE le palier commun. C'est le défaut #2 que le gate
                    #    H-SVC-CORR DOIT faire FIRER. Jamais actif en production.
                    svc_wU_c = min(max(2.4, _SVC_TARGET_AREA / 2.6), _svc_bandw)
                    svc_dV_c = min(2.6, back_d - 0.1)
                    _cuis_u1 = _ch_u0 + svc_wU_c
                    if _ch_u1 - _cuis_u1 > 0.3:
                        rects.append(("sej", _cuis_u1, _ch_u1, 0.0, back_d))
                    _wc_u1_c = _ch_u0 + _wc_w0
                    rects.append((RoomType.WC, _ch_u0, _wc_u1_c, 0.0, svc_dV_c))
                    rects.append((RoomType.SDB, _wc_u1_c, _cuis_u1, 0.0, svc_dV_c))
                elif _os_rt.environ.get("REVERT_V8_FLOAT"):
                    svc_wU_f = min(max(2.4, _SVC_TARGET_AREA / 2.6), _svc_bandw)
                    svc_dV_f = min(2.6, back_d - 0.5 - 0.1)
                    _svc_v0 = 0.5
                    _svc_v1 = _svc_v0 + svc_dV_f
                    _cuis_u1 = _ch_u1 - svc_wU_f
                    if _cuis_u1 - _ch_u0 > 0.3:
                        rects = [r for r in rects
                                 if not (r[0] == "sej" and r[1] == _ch_u0)]
                        rects.append(("sej", _ch_u0, _cuis_u1, 0.0, back_d))
                    # strips séjour AUTOUR (devant + derrière) → îlot flottant
                    rects.append(("sej", _cuis_u1, _ch_u1, 0.0, _svc_v0))
                    if back_d - _svc_v1 > 0.25:
                        rects.append(("sej", _cuis_u1, _ch_u1, _svc_v1, back_d))
                    _wc_u1_f = _cuis_u1 + _wc_w0
                    rects.append((RoomType.WC, _cuis_u1, _wc_u1_f, _svc_v0, _svc_v1))
                    rects.append((RoomType.SDB, _wc_u1_f, _ch_u1, _svc_v0, _svc_v1))
                else:
                    # ── PARTITION PROPRE + GARDE-FOUS (2026-07-14) : le SERVICE remplit
                    # TOUTE sa colonne (jusqu'au dégagement si T4/T5, sinon back_d) → PAS
                    # de strip séjour « derrière » → séjour = nez + UNE bande gauche = L
                    # SIMPLE (≤ ~8 sommets, plus 16). CHAQUE rect testé (largeur ET hauteur
                    # > 0.3 m) AVANT append → JAMAIS de rectangle dégénéré/inversé (cause
                    # du hang shapely). Dégagement (T4/T5) seulement si la profondeur laisse
                    # une SdB ≥ 1,5 m après le hall.
                    # DÉGAGEMENT NUIT (T4/T5, défaut user validé : « le dégagement doit
                    # servir TOUTES les chambres ») : hall 1,05 m entre le séjour et la
                    # rangée de chambres. Seuil de profondeur service RECALIBRÉ à 2,75 m
                    # (l'ancien 3,1 laissait back_d=4,40 sous le fil de 0,15 m → hall
                    # jamais posé). À 2,75 m de profondeur service, la SdB reste ~5 m²
                    # (WC ~0,9 m de profond + SdB le reste × largeur ~2,5 m ≥ 3,8, H7).
                    _HALL_D = 0.92   # dégagement AFFINÉ (user 2026-07-15 : « plus petit
                    #                  mais agréable ») : 0,92 m = passage confortable
                    #                  (norme couloir ≥ 0,90) sans gaspiller de SHAB.
                    _use_hall = (N >= 3 and back_d - _HALL_D - _svc_v0 >= 2.75)
                    _svc_v1 = (back_d - _HALL_D) if _use_hall else back_d
                    svc_dV = _svc_v1 - _svc_v0
                    if svc_dV < 1.8:                       # trop peu profond → pas de hall
                        _use_hall = False
                        _svc_v1 = back_d
                        svc_dV = _svc_v1 - _svc_v0
                    svc_wU = min(max(1.9, _SVC_TARGET_AREA / max(svc_dV, 0.9)), _svc_bandw)
                    _cuis_u1 = _ch_u1 - svc_wU
                    _svc_ok = (_ch_u1 - _cuis_u1 > 0.3)   # le bloc service a une largeur
                    # séjour/cuisine = UNE bande arrière gauche (L simple avec le nez)
                    if _cuis_u1 - _ch_u0 > 0.3:
                        rects = [r for r in rects
                                 if not (r[0] == "sej" and abs(r[1] - _ch_u0) < 1e-6)]
                        rects.append(("sej", _ch_u0, _cuis_u1, 0.0, back_d))
                    # front sliver (borgne du service côté couloir)
                    if _svc_ok and _svc_v0 > 0.2:
                        rects.append(("sej", _cuis_u1, _ch_u1, 0.0, _svc_v0))
                    # WC (bas-v) + SdB (haut-v) EMPILÉS, remplissent v[_svc_v0,_svc_v1].
                    # SdB garde ≥ 1,5 m de profondeur (utilisable) ; WC prend le reste bas.
                    _wc_dV = min(max(1.6 / max(svc_wU, 1.4), 0.9), 1.5)
                    _wc_dV = min(_wc_dV, max(0.0, svc_dV - 1.5))
                    _wc_v1 = _svc_v0 + _wc_dV
                    if _svc_ok and _wc_v1 - _svc_v0 > 0.3:
                        rects.append((RoomType.WC, _cuis_u1, _ch_u1, _svc_v0, _wc_v1))
                    if _svc_ok and _svc_v1 - _wc_v1 > 0.3:
                        rects.append((RoomType.SDB, _cuis_u1, _ch_u1, _wc_v1, _svc_v1))
                    # DÉGAGEMENT NUIT (T4/T5) : bande pleine largeur peigne, au-dessus du service.
                    if _use_hall and (_ch_u1 - _ch_u0 > 0.3) and (back_d - _svc_v1 > 0.3):
                        rects.append((RoomType.DEGAGEMENT_NUIT, _ch_u0, _ch_u1,
                                      _svc_v1, back_d))
        else:
            rects.append(("sej", _ch_u0, _ch_u1, 0.0, back_d))

        # ── MIROIR U (apt de coin) : si le service doit aller côté BAS-u pour ne pas
        #    poser la SdB sur une seconde façade, on MIROITE toutes les coordonnées u
        #    (u -> W - u) de la maquette. Le nez de séjour bascule en HAUT-u, le bloc
        #    service en BAS-u, et TOUTES les adjacences (parents↔SdB, cuisine↔chambres)
        #    sont préservées par construction. On inverse aussi l'ordre de la liste
        #    pour que l'itération reste u-croissante → _ch_seq garde parents collée
        #    à la SdB. Aucun autre changement de logique. Universel (4 orientations).
        if _svc_at_low_u:
            rects = [(k, W - u1, W - u0, v0, v1) for (k, u0, u1, v0, v1) in rects]
            rects.sort(key=lambda t: (t[1], t[3]))   # u croissant, puis v

        # ── Pièces FIXES (chambres + service) en monde. Le SÉJOUR sera tout le
        #    RESTE (apt − fixes) → tuilage 100 %, 0 trou par construction.
        #
        # ORDRE CHAMBRES (défaut user #2, 2026-07-03) : le bloc SERVICE (entrée+
        # SdB+WC) est posé à l'extrémité HAUTE de u (côté _ch_u1), donc la
        # chambre la plus proche de la SdB est la DERNIÈRE (u max). Pour une
        # SUITE PARENTALE (Ch. PARENTS contiguë à la SdB), on type les chambres
        # dans l'ordre secondaires d'abord (ENFANT/SUPP, u bas) puis PARENTS en
        # DERNIER (u haut = collé au service/SdB). nb chambres = N.
        # Après miroir, le service est en BAS-u : la parents doit être collée à lui
        # ⇒ parents en PREMIER (u bas). On construit _ch_seq en conséquence.
        _n_ch = sum(1 for k, *_ in rects if isinstance(k, tuple))
        _sec = [RoomType.CHAMBRE_ENFANT, RoomType.CHAMBRE_SUPP, RoomType.CHAMBRE_SUPP]
        # séquence u-croissante : (N-1) secondaires, puis PARENTS collée à la SdB
        # (haut-u par défaut). Après MIROIR (service en bas-u), la parents doit être
        # en PREMIER (bas-u) pour rester collée à la SdB → on inverse la séquence.
        _ch_seq = (_sec[:max(0, _n_ch - 1)]) + [RoomType.CHAMBRE_PARENTS]
        _ch_seq = _ch_seq[-_n_ch:] if _n_ch >= 1 else []
        if _svc_at_low_u:
            _ch_seq = _ch_seq[::-1]
        _fixed_rooms = []
        _ch_i = 0
        for kind, u0, u1, v0, v1 in rects:
            if kind == "sej":
                continue
            poly = _wbox(u0, u1, v0, v1).intersection(apt)
            if poly.is_empty or poly.area < 0.4:
                continue
            if poly.geom_type == "MultiPolygon":
                poly = max(poly.geoms, key=lambda g: g.area)
            if isinstance(kind, tuple):     # chambre
                rt = _ch_seq[min(_ch_i, len(_ch_seq) - 1)] if _ch_seq \
                    else _CH_TYPES[min(_ch_i, len(_CH_TYPES) - 1)]
                _ch_i += 1
                _fixed_rooms.append((rt, poly))
            else:
                _fixed_rooms.append((kind, poly))

        def _touch_cour(g):
            try:
                return g.boundary.intersection(_lights.buffer(0.15)).length >= 0.8
            except Exception:
                return False

        # SÉJOUR = apt − (chambres + service). Capture TOUT le reste (nez +
        # cuisine + poche de coin) → aucun trou. On garde la composante qui
        # touche la cour ; toute part détachée (poche derrière une chambre) est
        # recollée à la chambre voisine (jamais un trou, jamais un cellier).
        _fixed_u = _uu([p for _, p in _fixed_rooms]) if _fixed_rooms else None
        _sej_all = apt.difference(_fixed_u).buffer(0) if _fixed_u is not None else apt
        _sej_geoms = (list(_sej_all.geoms) if _sej_all.geom_type == "MultiPolygon"
                      else [_sej_all])
        _sej_geoms = [g for g in _sej_geoms if not g.is_empty and g.area >= 0.3]
        if not _sej_geoms:
            continue
        _cap = _SEJ_CAP[typo]
        _sej_main = max((g for g in _sej_geoms if _touch_cour(g)),
                        key=lambda g: g.area, default=None)
        if _sej_main is None:
            _sej_main = max(_sej_geoms, key=lambda g: g.area)

        # Petites parts DÉTACHÉES du séjour principal (poche derrière une
        # chambre) : on les recolle d'abord à une chambre adjacente (≤19 m²,
        # reste éclairée) ; sinon on les garde de côté comme BLOB à traiter.
        _detached = []
        for g in _sej_geoms:
            if g is _sej_main or g.area < 0.3:
                continue
            _done = False
            if _fixed_rooms:
                k = min(range(len(_fixed_rooms)),
                        key=lambda i: _fixed_rooms[i][1].distance(g))
                _rt, _pp = _fixed_rooms[k]
                if (_rt in (RoomType.CHAMBRE_PARENTS, RoomType.CHAMBRE_ENFANT,
                            RoomType.CHAMBRE_SUPP) and _pp.distance(g) < 0.3):
                    _m = _uu([_pp, g]).buffer(0.12).buffer(-0.12)
                    if (_m.geom_type == "Polygon" and _m.area <= 19.0
                            and _touch_cour(_m)):
                        _fixed_rooms[k] = (_rt, _m)
                        _done = True
            if not _done:
                _detached.append(g)

        # ── UN SEUL SÉJOUR_CUISINE, connexe. On NE CARVE PAS le coin : l'apt
        # d'extrémité GARDE son contour rectangle/L et son grand séjour ouvert
        # (le coin aveugle derrière la cage = grand séjour/cuisine ouvert, T4
        # haut de gamme). Les caps du gate sont relevés (T4≤58…) pour l'accepter.
        # Toute petite part DÉTACHÉE (poche derrière une chambre) est réunie au
        # séjour si connexe, sinon rendue à la chambre voisine ; jamais un carve
        # en escalier (0 dentelé), jamais de vide footprint.
        _CUISINE_MAX = 15.0
        _cuisine_geoms = []
        _blobs = list(_detached)
        for g in _blobs:
            if g.is_empty or g.area < 0.6:
                continue
            # chambre adjacente éclairée ? sinon → morceau de séjour/cuisine.
            _done = False
            if _fixed_rooms:
                k = min(range(len(_fixed_rooms)),
                        key=lambda i: _fixed_rooms[i][1].distance(g))
                _rt, _pp = _fixed_rooms[k]
                if (_rt in (RoomType.CHAMBRE_PARENTS, RoomType.CHAMBRE_ENFANT,
                            RoomType.CHAMBRE_SUPP) and _pp.distance(g) < 0.3):
                    _m = _uu([_pp, g]).buffer(0.12).buffer(-0.12)
                    if (_m.geom_type == "Polygon" and _m.area <= 19.0
                            and _touch_cour(_m)):
                        _fixed_rooms[k] = (_rt, _m); _done = True
            if _done:
                continue
            # part détachée non absorbable → cuisine ouverte (borgne OK).
            _cuisine_geoms.append(g)

        if _sej_main.is_empty or _sej_main.area < 6.0:
            continue

        # Si le séjour dépasse ENCORE le cap (relevé) — cas très gros coin — on
        # sépare UNE CUISINE ouverte (borgne, open-plan) collée au séjour, prise
        # sur la BANDE côté COULOIR (fond aveugle), pleine largeur, en UN
        # rectangle propre. La cuisine est PLAFONNÉE à _CUISINE_MAX (défaut user
        # #3, 2026-07-03 / H9) : plus jamais de « cuisine 37,5 m² » orpheline. Si
        # une seule cuisine ≤ cap ne suffit pas à ramener le séjour sous le
        # plafond (très gros coin aveugle : apt06), on RETYPE l'apt vers la typo
        # dont le cap couvre son séjour ouvert réel (un grand séjour/cuisine
        # ouvert = 1 pièce, cf. la règle user « UNE seule pièce séjour/cuisine
        # ≤ cap ») — le nb de chambres reste inchangé, la pièce jour reste unique.
        # GABARIT OPEN-PLAN (2026-07-06) : le séjour/cuisine est UNE SEULE pièce
        # ouverte (demande user). On NE FRAGMENTE PLUS en CUISINE séparée : les
        # caps sont relevés pour que les apts tuilés normaux tiennent d'un bloc,
        # et un très gros coin est RETYPÉ vers la typo dont le cap couvre son
        # séjour ouvert (le nb de chambres reste inchangé). Cela GARANTIT que le
        # séjour garde son contact COULOIR (preuve open-plan) : aucun carve ne
        # vient sectionner l'arête couloir de la pièce à vivre.
        if _sej_main.area > _cap:
            for _t2 in (Typologie.T3, Typologie.T4, Typologie.T5):
                if _SEJ_CAP.get(_t2, 0.0) >= _sej_main.area - 0.5:
                    _cap = _SEJ_CAP[_t2]
                    break

        # ── Émet les Room : 1 SEJOUR_CUISINE + (0/1 CUISINE) + chambres + svc. ──
        _rooms_out = []
        if _sej_main.geom_type == "MultiPolygon":
            _sej_main = max(_sej_main.geoms, key=lambda p: p.area)
        if _sej_main.geom_type == "Polygon" and _sej_main.area >= 1.0:
            _rooms_out.append(Room(
                id=f"{c.id}_r_sejour", type=RoomType.SEJOUR_CUISINE,
                surface_m2=round(_sej_main.area, 1),
                polygon_xy=list(_sej_main.exterior.coords)[:-1],
                orientation=None, label_fr="Séjour / cuisine", furniture=[]))
        # UNE cuisine ouverte (borgne) regroupant les blobs recyclés (≤15 m²).
        if _cuisine_geoms:
            _cu = _uu(_cuisine_geoms).difference(_sej_main).buffer(0)
            _cu_parts = (list(_cu.geoms) if _cu.geom_type == "MultiPolygon" else [_cu])
            _cu = max((p for p in _cu_parts if p.geom_type == "Polygon"),
                      key=lambda p: p.area, default=None)
            if _cu is not None and _cu.area >= 2.0:
                _rooms_out.append(Room(
                    id=f"{c.id}_r_cuisine", type=RoomType.CUISINE,
                    surface_m2=round(_cu.area, 1),
                    polygon_xy=list(_cu.exterior.coords)[:-1],
                    orientation=None, label_fr="Cuisine", furniture=[]))
        for rt, poly in _fixed_rooms:
            poly = poly.difference(_sej_main).intersection(apt).buffer(0)
            if poly.is_empty:
                continue
            if poly.geom_type == "MultiPolygon":
                poly = max(poly.geoms, key=lambda g: g.area)
            if poly.geom_type != "Polygon" or poly.area < 0.8:
                continue
            _rooms_out.append(Room(
                id=f"{c.id}_{rt.value}_{len(_rooms_out)}", type=rt,
                surface_m2=round(poly.area, 1),
                polygon_xy=list(poly.exterior.coords)[:-1],
                orientation=None, label_fr=rt.value, furniture=[]))

        # ── NETTOYAGE CONTOURS : retire les sommets colinéaires / doublons
        #    (dentelé numérique) sur l'apt ET chaque pièce → contour propre
        #    (≤10 sommets pour un rectangle/L), exigence du gate.
        def _clean_ring(coords):
            from shapely.geometry import Polygon as _PP
            try:
                pg = _PP(coords)
                if not pg.is_valid:
                    pg = pg.buffer(0)
                    if pg.geom_type == "MultiPolygon":
                        pg = max(pg.geoms, key=lambda g: g.area)
                # simplify enlève les colinéaires ET les micro-artefacts d'angle
                # laissés par le grow parents buffer(0.12).buffer(-0.12) (déviations
                # ~3-5 cm qui faisaient lire un rectangle parfait rr=1.00 comme
                # « 8 sommets »). Tolérance 5 cm : négligeable pour le tuilage.
                pg = pg.simplify(0.05, preserve_topology=True)
                if pg.geom_type != "Polygon" or pg.is_empty:
                    return coords
                # SNAP RECTANGLE : un contour quasi-plein (aire ≈ bbox, rr≥0,995)
                # AVEC des sommets résiduels (>4) est un rectangle parfait dentelé
                # par des micro-artefacts → on le remplace par sa bbox EXACTE (aire
                # inchangée à 0,5 % près, aucun débordement). Ne touche PAS les vrais
                # L (séjour rr~0,4) qui gardent leurs sommets.
                _b = pg.bounds
                _bba = (_b[2] - _b[0]) * (_b[3] - _b[1])
                if _bba > 0 and pg.area / _bba >= 0.995 \
                        and len(pg.exterior.coords) > 5:
                    from shapely.geometry import box as _bx
                    pg = _bx(*_b)
                return list(pg.exterior.coords)[:-1]
            except Exception:
                return coords

        # ── GROW-PASS CHAMBRE SOUS-DIMENSIONNÉE (défaut user : chambres 10,0-10,1
        #    < 10,5 sur apts de coin/étroits où la profondeur peigne est bridée).
        #    Filet universel : toute chambre < 10,6 m² est ÉLARGIE dans le SÉJOUR
        #    adjacent (qui a du mou) par une BANDE pleine largeur → la chambre reste
        #    un RECTANGLE (bbox de l'union de 2 rectangles jointifs), et la bande est
        #    RETIRÉE au séjour. On ne prend QUE de l'espace séjour (≥ 97 % de la bande
        #    ⊂ séjour) → jamais de chevauchement SdB/WC/autre chambre. Si aucune
        #    direction sûre, la chambre est laissée telle quelle (pas de casse).
        from shapely.geometry import Polygon as _PPg, box as _bxg
        _sej_room = next((r for r in _rooms_out
                          if r.type == RoomType.SEJOUR_CUISINE
                          and len(r.polygon_xy) >= 3), None)
        if _sej_room is not None:
            _sejp = _PPg(_sej_room.polygon_xy).buffer(0)
            _CHT = (RoomType.CHAMBRE_PARENTS, RoomType.CHAMBRE_ENFANT,
                    RoomType.CHAMBRE_SUPP)
            for _r in _rooms_out:
                if _r.type not in _CHT or len(_r.polygon_xy) < 3:
                    continue
                _bp = _PPg(_r.polygon_xy).buffer(0)
                if _bp.is_empty or _bp.area >= 10.6:
                    continue
                b = _bp.bounds
                _need = 10.7 - _bp.area
                for _side in ("x0", "x1", "y0", "y1"):
                    if _side in ("x0", "x1"):
                        _ln = b[3] - b[1]
                    else:
                        _ln = b[2] - b[0]
                    if _ln < 1.0:
                        continue
                    _d = _need / _ln + 0.06
                    if _side == "x0":
                        _gs = _bxg(b[0] - _d, b[1], b[0], b[3])
                    elif _side == "x1":
                        _gs = _bxg(b[2], b[1], b[2] + _d, b[3])
                    elif _side == "y0":
                        _gs = _bxg(b[0], b[1] - _d, b[2], b[1])
                    else:
                        _gs = _bxg(b[0], b[3], b[2], b[3] + _d)
                    if _gs.area <= 0.01:
                        continue
                    if _gs.intersection(_sejp).area < _gs.area * 0.97:
                        continue      # cette direction n'est pas du séjour libre
                    _cand = _bxg(*_bp.union(_gs).bounds)
                    if _cand.difference(apt).area > 0.05:
                        continue      # déborderait de l'apt
                    _r.polygon_xy = list(_cand.exterior.coords)[:-1]
                    _r.surface_m2 = round(_cand.area, 1)
                    _sejp = _sejp.difference(_cand).buffer(0)
                    break
            if _sejp.geom_type == "MultiPolygon":
                _sejp = max(_sejp.geoms, key=lambda g: g.area)
            if _sejp.geom_type == "Polygon" and _sejp.area >= 1.0:
                _sej_room.polygon_xy = list(_sejp.exterior.coords)[:-1]
                _sej_room.surface_m2 = round(_sejp.area, 1)

        c.polygon_xy = _clean_ring(c.polygon_xy)
        for _r in _rooms_out:
            if len(_r.polygon_xy) >= 3:
                _r.polygon_xy = _clean_ring(_r.polygon_xy)

        # nb chambres réel == typo ? sinon retype.
        _got = sum(1 for r in _rooms_out if r.type in (
            RoomType.CHAMBRE_PARENTS, RoomType.CHAMBRE_ENFANT, RoomType.CHAMBRE_SUPP))
        if _got in _NCH_TYPO:
            typo = _NCH_TYPO[_got]
        c.rooms = _rooms_out
        c.typologie = typo
        c.surface_m2 = sum(r.surface_m2 for r in c.rooms)

        # ── MOBILIER par pièce (données modèle ; le frontend meuble aussi de
        #    façon procédurale, mais on peuple room.furniture pour tout
        #    consommateur du modèle). Un symbole au centroïde par type. ────────
        _populate_furniture(c.rooms)

        # ── RÉGÉNÈRE walls + openings SUR LES NOUVELLES PIÈCES ──────────────
        # Le relayout mono-façade vient de RÉÉCRIRE c.rooms ; les walls/openings
        # hérités de generate_apartment (avant relayout) sont STALE : leurs
        # PORTE_INTERIEURE pointent sur des cloisons de l'ANCIENNE subdivision →
        # portes sur du vide au rendu. On rappelle le MÊME moteur que le chemin L
        # (build_walls_and_openings) sur les pièces réelles pour que :
        #   - chaque PORTE_INTERIEURE tombe sur une cloison partagée séjour↔pièce,
        #   - la PORTE_ENTREE soit sur le mur couloir (côté opposé à la cour),
        #   - les FENETRE/PORTE_FENETRE soient sur la façade cour uniquement.
        # palier_side = côté couloir = opposé de la façade cour (repère v=0).
        _OPP = {"sud": "nord", "nord": "sud", "ouest": "est", "est": "ouest"}
        palier_side = _OPP[cour_side]
        try:
            from core.templates_library.layout_generator import (
                build_walls_and_openings as _bwo,
            )
            _walls, _openings = _bwo(
                c.rooms,
                (mnx, mny, mxx, mxy),
                palier_side,  # type: ignore[arg-type]
                c.id,
                orientations=[cour_side],
                footprint=footprint,
                parcelle=None,
                other_cells_polys=None,
                voiries=tuple(voiries) if voiries else None,
            )
            c.walls = _walls
            c.openings = _openings
        except Exception:
            # Ne jamais bloquer la génération sur l'enrichissement openings.
            pass


def _reclaim_pockets(cells, footprint, core, circulations, voiries=None) -> float:
    """Merge leftover INTERIOR floor pockets (unassigned space left by corner
    rectification or imperfect tiling around the inner corners) into the
    nearest apartment's séjour — no floor area is wasted, the adjacent (corner)
    apt just gets a bigger living room. Returns m² reclaimed."""
    from shapely.geometry import Polygon as _P
    from shapely.ops import unary_union as _uu
    apts = [c for c in cells if c.type == CelluleType.LOGEMENT and len(c.polygon_xy) >= 3]
    if not apts:
        return 0.0
    _cpoly = _core_poly(core)
    fixed = [_cpoly] if _cpoly is not None else []
    for cc in circulations:
        if cc.polygon_xy and len(cc.polygon_xy) >= 3:
            fixed.append(_P(cc.polygon_xy))
    reclaimed = 0.0

    # A concave-corner pocket often splits into legs that are each nearest to a
    # DIFFERENT apt, and merging only absorbs the leg connected to that apt. So
    # loop: recompute the void, absorb each piece into its nearest apt, repeat
    # until nothing more is adjacent.
    for _pass in range(5):
        occ = _uu([_P(c.polygon_xy) for c in apts] + fixed).buffer(0.03)
        void = footprint.difference(occ)
        pieces = [void] if void.geom_type == "Polygon" else list(getattr(void, "geoms", []))
        did = 0.0
        for pk in pieces:
            if pk.is_empty or pk.area < 2.0:
                continue
            # ANTI-COIN-OBÈSE (2026-07-03) : ne PAS gonfler un apt au-delà d'une
            # taille vendable (~95 m²). Un pocket aveugle profond absorbé ici
            # fabriquerait un séjour/cuisine géant (défaut #2/#3). On le laisse :
            # il sera récupéré par la circulation (couloir/2e cage) en aval, pas
            # transformé en pièce borgne géante d'un logement.
            _MAX_APT_AREA = 95.0
            # Choisir le PLUS PROCHE apt ADJACENT qui reste ≤ cap une fois gonflé
            # (pas juste le plus proche dans l'absolu). Sans ce filtre, un pocket
            # à égale distance d'un apt déjà obèse (109 m²) et d'un apt façade
            # moyen (53 m²) tombait TOUJOURS sur l'obèse → skip → vide non
            # récupéré (le strip de 13 m² au coude du L). On préfère l'apt qui
            # peut réellement l'absorber.
            _adj = [c for c in apts if _P(c.polygon_xy).distance(pk) <= 0.7]
            if not _adj:
                continue  # not adjacent to any apt (genuine light-well) → leave
            _fit = [c for c in _adj if _P(c.polygon_xy).area + pk.area <= _MAX_APT_AREA]
            if not _fit:
                continue  # every adjacent apt would blow past the cap → leave
            best = min(_fit, key=lambda c: (_P(c.polygon_xy).distance(pk),
                                            _P(c.polygon_xy).area))
            # Bridge sub-cm/cm seams between apt and pocket (close small gaps)
            # so the union is a single polygon, then snap back.
            merged = _uu([_P(best.polygon_xy), pk]).buffer(0.2).buffer(-0.2)
            if merged.geom_type == "MultiPolygon":
                merged = max(merged.geoms, key=lambda g: g.area)
            if merged.geom_type != "Polygon":
                continue
            best.polygon_xy = list(merged.exterior.coords)[:-1]
            # RE-LAYOUT the enlarged apt as a PROPER bigger typology instead of
            # bloating the séjour (a T2 with a 54 m² living room is nonsense). We
            # design on the largest inscribed rectangle of the enlarged shape so
            # rooms land on the façade (lit), pick the typo from that area, then
            # give the small non-rectangular remainder to the séjour.
            from core.templates_library.layout_generator import (
                generate_apartment as _gen)
            from shapely.geometry import box as _box2
            _mnx, _mny, _mxx, _mxy = merged.bounds
            _bba = (_mxx - _mnx) * (_mxy - _mny) or 1
            if merged.area / _bba >= 0.9:
                rect = merged
            else:
                _buf = merged.buffer(0.05)
                rect = None
                for _side in ("bottom", "top", "left", "right"):
                    _span = (_mxy - _mny) if _side in ("bottom", "top") else (_mxx - _mnx)
                    _t = 0.0
                    while _t < _span:
                        if _side == "bottom":
                            _c = _box2(_mnx, _mny + _t, _mxx, _mxy)
                        elif _side == "top":
                            _c = _box2(_mnx, _mny, _mxx, _mxy - _t)
                        elif _side == "left":
                            _c = _box2(_mnx + _t, _mny, _mxx, _mxy)
                        else:
                            _c = _box2(_mnx, _mny, _mxx - _t, _mxy)
                        if _buf.contains(_c):
                            if rect is None or _c.area > rect.area:
                                rect = _c
                            break
                        _t += 0.25
                if rect is None:
                    rect = merged
            _rb = rect.bounds
            _area = rect.area
            _typo = (Typologie.T5 if _area >= 90 else Typologie.T4 if _area >= 70
                     else Typologie.T3 if _area >= 52 else Typologie.T2)
            try:
                _voi = set(voiries or ())
                _fb2 = footprint.bounds
                _mit = set()
                if abs(_mnx - _fb2[0]) < 0.6 and "ouest" not in _voi: _mit.add("ouest")
                if abs(_mxx - _fb2[2]) < 0.6 and "est" not in _voi: _mit.add("est")
                if abs(_mny - _fb2[1]) < 0.6 and "sud" not in _voi: _mit.add("sud")
                if abs(_mxy - _fb2[3]) < 0.6 and "nord" not in _voi: _mit.add("nord")
                _lit = [o for o in (best.orientation or []) if o not in _mit] or (best.orientation or [])
                _rooms, _, _, _, _eff = _gen(
                    slot_bounds=(_rb[0], _rb[1], _rb[2], _rb[3]),
                    typologie=_typo, orientations=_lit,
                    slot_id=best.id, palier_side_hint=None,
                )
                if _rooms:
                    # absorb the L-remainder (merged \ rect) into the séjour
                    _rem = merged.difference(rect).buffer(0)
                    _sej = next((r for r in _rooms if r.type in (
                        RoomType.SEJOUR, RoomType.SEJOUR_CUISINE) and len(r.polygon_xy) >= 3), None)
                    if _sej is not None and not _rem.is_empty and _rem.area > 1:
                        _sm = _uu([_P(_sej.polygon_xy), _rem]).buffer(0.2).buffer(-0.2)
                        if _sm.geom_type == "MultiPolygon":
                            _sm = max(_sm.geoms, key=lambda g: g.area)
                        if _sm.geom_type == "Polygon":
                            _sej.polygon_xy = list(_sm.exterior.coords)[:-1]
                            _sej.surface_m2 = round(_sm.area, 1)
                    for _r in _rooms:
                        if not _r.label_fr:
                            _r.label_fr = _r.type.value
                    best.rooms = _rooms
                    best.typologie = _eff
            except Exception:
                pass
            best.surface_m2 = sum(r.surface_m2 for r in best.rooms)
            did += pk.area
        reclaimed += did
        if did < 1.0:
            break
    return reclaimed


def _centered_inscribed_rect(region, ring_m: float = 0.0):
    """Renvoie le plus grand RECTANGLE AXIS-ALIGNED inscrit dans ``region``,
    MAXIMISANT L'AIRE (donc minimisant le résidu de centre mort autour), tout en
    restant à ≥ ``ring_m`` du bord si ``ring_m`` > 0.

    La cour organique (blob décentré issu de l'érosion/dilatation) est remplacée
    par ce rectangle propre : la cour se lit comme un patio net, et l'espace
    (center − rectangle) forme l'ANNEAU MINCE de couloir tout autour reliant les
    entrées + la cage. On MAXIMISE l'aire du rectangle (au lieu de le centrer sur le
    centroïde) pour que le rectangle épouse au mieux le centre mort → le résidu non
    couvert (donc le « bloc plein » du couloir) soit le plus petit possible.
    Universel (toute forme de centre mort).

    Méthode : balayage 2D des lignes de coupe candidates (bords x/y à pas fin) et
    on retient le rectangle d'aire max entièrement contenu dans ``region`` (érodée
    de ``ring_m``). O(nx²·ny²) borné (grille ~0,3 m sur un patio ~9×9 → rapide).
    """
    from shapely.geometry import box as _bx
    if region is None or region.is_empty or region.geom_type != "Polygon":
        return None
    inner = region.buffer(-ring_m) if ring_m > 0 else region
    if inner.is_empty:
        return None
    if inner.geom_type == "MultiPolygon":
        inner = max(inner.geoms, key=lambda g: g.area)
    minx, miny, maxx, maxy = inner.bounds
    # bornes candidates = sommets + grille régulière (0,3 m) : couvre les arêtes du
    # blob et évite d'exploser la combinatoire.
    step = 0.3
    _xs = sorted(set([round(v, 2) for v in
                      [minx, maxx] + [x for x, _ in inner.exterior.coords]] +
                     [round(minx + i * step, 2)
                      for i in range(int((maxx - minx) / step) + 1)]))
    _ys = sorted(set([round(v, 2) for v in
                      [miny, maxy] + [y for _, y in inner.exterior.coords]] +
                     [round(miny + i * step, 2)
                      for i in range(int((maxy - miny) / step) + 1)]))
    best = None
    ip = inner.buffer(1e-6)   # tolérance de contenance
    for i in range(len(_xs)):
        for k in range(i + 1, len(_xs)):
            x0, x1 = _xs[i], _xs[k]
            if x1 - x0 < 2.0:
                continue
            for j in range(len(_ys)):
                for m in range(j + 1, len(_ys)):
                    y0, y1 = _ys[j], _ys[m]
                    if y1 - y0 < 2.0:
                        continue
                    a = (x1 - x0) * (y1 - y0)
                    if best is not None and a <= best[0]:
                        continue
                    r = _bx(x0, y0, x1, y1)
                    if ip.contains(r):
                        best = (a, (x0, y0, x1, y1))
    if best is None:
        return None
    x0, y0, x1, y1 = best[1]
    return _bx(round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2))


def _core_poly(core):
    """Renvoie le Polygon shapely de la CAGE quelle que soit sa représentation.

    ``core`` peut être un ``CorePlacement`` (attribut ``.polygon`` = shapely) OU un
    objet exposant ``.polygon_xy`` (liste de points). Historiquement les helpers de
    poches ne testaient QUE ``.polygon_xy`` → la cage n'était JAMAIS protégée (elle
    n'a pas cet attribut), d'où l'escalier qui finissait DANS la cour. Ce helper
    normalise les deux cas. Renvoie ``None`` si aucune géométrie exploitable.
    """
    from shapely.geometry import Polygon as _P
    if core is None:
        return None
    poly = getattr(core, "polygon", None)
    if poly is not None and getattr(poly, "is_empty", True) is False:
        return poly
    xy = getattr(core, "polygon_xy", None)
    if xy and len(xy) >= 3:
        return _P(xy)
    return None


def _largest_axis_rect_excluding(rect, obstacle, clearance: float = 0.0):
    """Plus grand sous-RECTANGLE axis-aligned de ``rect`` DISJOINT de ``obstacle``
    (avec marge ``clearance``). Sert à sortir la CAGE (escalier+ASC) de la COUR :
    au lieu de MORDRE la cage dans la cour (contour en L), on RECULE un bord de la
    cour jusqu'à ce que le rectangle ne touche plus la cage → la cour reste un
    rectangle PROPRE et ``cour ∩ cage = 0`` (une cage ne peut pas être dans un
    patio à ciel ouvert). On teste les 4 façons de couper (retirer la bande de la
    cour côté N/S/E/O de la cage) et on garde le rectangle d'AIRE MAX. Universel.

    Renvoie un Polygon (rectangle) ou ``rect`` inchangé si ``obstacle`` ne le
    touche pas ; ``None`` si aucun sous-rectangle non nul ne subsiste.
    """
    from shapely.geometry import box as _bx
    if obstacle is None or obstacle.is_empty:
        return rect
    # marge : on RECULE le bord de coupe de ``clearance`` au-delà de la cage pour
    # laisser un vrai jeu bâti entre la cour et l'escalier (pas juste tangence).
    if rect.intersection(obstacle).area <= 1e-6:
        return rect
    rx0, ry0, rx1, ry1 = rect.bounds
    ox0, oy0, ox1, oy1 = obstacle.bounds
    cands = []
    # couper la cour SOUS l'obstacle (garder y ≤ oy0 − clearance) …
    if (oy0 - clearance) - ry0 >= 2.0:
        cands.append(_bx(rx0, ry0, rx1, oy0 - clearance))
    # … AU-DESSUS (garder y ≥ oy1 + clearance) …
    if ry1 - (oy1 + clearance) >= 2.0:
        cands.append(_bx(rx0, oy1 + clearance, rx1, ry1))
    # … à GAUCHE (garder x ≤ ox0 − clearance) …
    if (ox0 - clearance) - rx0 >= 2.0:
        cands.append(_bx(rx0, ry0, ox0 - clearance, ry1))
    # … à DROITE (garder x ≥ ox1 + clearance).
    if rx1 - (ox1 + clearance) >= 2.0:
        cands.append(_bx(ox1 + clearance, ry0, rx1, ry1))
    cands = [c for c in cands
             if not c.is_empty and c.intersection(obstacle).area <= 1e-6]
    if not cands:
        return None
    best = max(cands, key=lambda g: g.area)
    return _bx(round(best.bounds[0], 2), round(best.bounds[1], 2),
               round(best.bounds[2], 2), round(best.bounds[3], 2))


def _expand_rect_in_region(rect, region, obstacle=None, step: float = 0.25):
    """Fait GROSSIR ``rect`` (axis-aligned) bord par bord tant qu'il reste DANS
    ``region`` et DISJOINT de ``obstacle``. Sert à ce que la cour REMPLISSE tout
    le cœur mort du coude (sinon un pan de couloir ÉPAIS subsiste sur les côtés
    non couverts) : après avoir sorti la cage de la cour, on repousse les 4 bords
    de la cour jusqu'aux apts / au footprint / à la cage → le couloir résiduel
    redevient un ANNEAU MINCE et H-COUR passe. La cour reste un RECTANGLE.
    Universel (tout centre mort). Renvoie un Polygon (rectangle)."""
    from shapely.geometry import box as _bx
    reg = region.buffer(0.02)
    ob = obstacle.buffer(0.10) if (obstacle is not None and not obstacle.is_empty) else None
    x0, y0, x1, y1 = rect.bounds

    def _ok(bx):
        if not reg.contains(bx):
            return False
        if ob is not None and bx.intersection(ob).area > 1e-6:
            return False
        return True
    # ordre : on pousse chaque bord au max, plusieurs passes pour laisser les
    # bords se relayer (un bord bloqué par la cage peut se libérer après qu'un
    # autre ait bougé — rare mais robuste).
    for _ in range(3):
        moved = False
        # gauche (x0 ↓)
        while _ok(_bx(x0 - step, y0, x1, y1)):
            x0 -= step; moved = True
        # droite (x1 ↑)
        while _ok(_bx(x0, y0, x1 + step, y1)):
            x1 += step; moved = True
        # bas (y0 ↓)
        while _ok(_bx(x0, y0 - step, x1, y1)):
            y0 -= step; moved = True
        # haut (y1 ↑)
        while _ok(_bx(x0, y0, x1, y1 + step)):
            y1 += step; moved = True
        if not moved:
            break
    return _bx(round(x0, 2), round(y0, 2), round(x1, 2), round(y1, 2))


def _absorb_blind_pockets(cells, footprint, core, circulations, voiries=None):
    """ZÉRO VIDE (2026-07-06, demande user) : après `_reclaim_pockets`, il reste au
    centre profond d'un L la « courette » interne (poche AVEUGLE ceinturée par les
    branches, ex. 62 m² au coude). L'user REFUSE ce vide. On la RÉCUPÈRE ENTIÈREMENT
    en SHAB, sans logement borgne, sans dentelé, sans exploser la circulation :

      - On DÉCOUPE la poche en cellules 0,5 m et on assigne chaque cellule à l'apt
        ADJACENT le plus proche (distance de bord). Chaque apt récupère ainsi le
        bloc de poche qui le jouxte (séjour profond — toléré mono-façade : fenêtre
        sur la cour, profondeur = séjour). L'apt ne grossit que si le résultat
        reste (a) ≤ _CAP m² et (b) un contour PROPRE ≤ 10 sommets (0 dentelé).
      - Rien n'est versé au couloir : le couloir reste le tracé MINCE 1,40 m. La
        poche part 100 % en logements → circulation basse + 0 vide. Universel.

    Modifie ``cells`` en place. Retourne (m2_shab_recuperee, m2_couloir_ajoutee)."""
    from shapely.geometry import Polygon as _P, box as _box, Point as _Pt
    from shapely.ops import unary_union as _uu
    apts = [c for c in cells if c.type == CelluleType.LOGEMENT and len(c.polygon_xy) >= 3]
    if not apts:
        return 0.0, 0.0
    # Plafond d'absorption : un logement récupérant la poche doit rester LAYOUTABLE
    # par le générateur mono-façade (sinon séjour/cuisine géant hors gabarit). Un
    # T5 propre = ~95 m² ; au-delà le relayout produit une cuisine aberrante. On
    # cape donc à 96 m² : les apts restent des T4/T5 sains, et le reliquat VRAIMENT
    # central (au-delà de ce que les apts peuvent absorber proprement) part au
    # couloir (spine du L) — pas de vide, circulation maîtrisée. Universel.
    _CAP = 96.0
    _GRID = 0.5
    _cpoly0 = _core_poly(core)
    fixed = [_cpoly0] if _cpoly0 is not None else []
    corridor_ids = [i for i, cc in enumerate(circulations)
                    if cc.id.startswith("couloir") and len(cc.polygon_xy) >= 3]
    for cc in circulations:
        if cc.polygon_xy and len(cc.polygon_xy) >= 3:
            fixed.append(_P(cc.polygon_xy))
    shab_gain = 0.0
    for _pass in range(6):
        ap_polys = [_P(c.polygon_xy).buffer(0) for c in apts]
        occ = _uu(ap_polys + fixed).buffer(0.02)
        void = footprint.difference(occ)
        pieces = [void] if void.geom_type == "Polygon" else list(getattr(void, "geoms", []))
        did = 0.0
        for pk in pieces:
            if pk.is_empty or pk.area < 2.0:
                continue
            # apts ADJACENTS à cette poche.
            adj = [(c, _P(c.polygon_xy).buffer(0)) for c in apts
                   if _P(c.polygon_xy).distance(pk) <= 0.7]
            if not adj:
                continue
            pminx, pminy, pmaxx, pmaxy = pk.bounds
            # accumulateur des cellules assignées par apt (id -> liste de box).
            assign: dict[str, list] = {c.id: [] for c, _ in adj}
            gy = pminy
            while gy < pmaxy - 1e-6:
                gx = pminx
                while gx < pmaxx - 1e-6:
                    cell = _box(gx, gy, min(gx + _GRID, pmaxx), min(gy + _GRID, pmaxy))
                    gx += _GRID
                    if cell.intersection(pk).area < cell.area * 0.4:
                        continue
                    ctr = cell.centroid
                    best = min(adj, key=lambda t: t[1].distance(ctr))
                    assign[best[0].id].append(cell)
                gy += _GRID
            # étend chaque apt par le RECTANGLE PROPRE de ses cellules assignées.
            # On prend la BBOX des cellules de l'apt (⇒ extension rectangulaire, pas
            # de dentelé de grille), clippée à la poche et PRIVÉE des blocs fixes
            # (cage/couloir) pour ne pas recouvrir un escalier. On garde la plus
            # grande composante rectangulaire dont l'union avec l'apt reste un
            # contour ≤ 10 sommets et ≤ _CAP. Universel.
            fixed_u = _uu(fixed) if fixed else None
            for c, ap in adj:
                boxes = assign.get(c.id) or []
                if not boxes:
                    continue
                bb = _uu(boxes).bounds
                ext = _box(bb[0], bb[1], bb[2], bb[3]).intersection(pk)
                if fixed_u is not None and not fixed_u.is_empty:
                    ext = ext.difference(fixed_u.buffer(0.02))
                if ext.is_empty:
                    continue
                if ext.geom_type == "MultiPolygon":
                    ext = max(ext.geoms, key=lambda g: g.area)
                if ext.area < 2.0:
                    continue
                merged = _uu([ap, ext]).buffer(0.1).buffer(-0.1)
                if merged.geom_type == "MultiPolygon":
                    merged = max(merged.geoms, key=lambda g: g.area)
                if merged.geom_type != "Polygon":
                    continue
                merged = merged.simplify(0.12, preserve_topology=True)
                if merged.geom_type != "Polygon":
                    continue
                gain = merged.area - ap.area
                if gain < 1.0 or merged.area > _CAP + 0.5:
                    continue
                if len(merged.exterior.coords) > 11:   # ≤10 sommets réels
                    continue
                c.polygon_xy = list(merged.exterior.coords)[:-1]
                c.surface_m2 = round(merged.area, 1)
                shab_gain += gain
                did += gain
        if did < 1.0:
            break
    # ── CENTRE MORT → VRAIE COUR INTÉRIEURE OUVERTE (2026-07-06, demande user) ──
    # Ce que les apts n'ont pu absorber proprement au CENTRE PROFOND du L est une
    # poche AVEUGLE ceinturée par les 2 branches : c'est le cœur d'un IMMEUBLE SUR
    # COUR. Au lieu de la NOYER dans le couloir (l'ancien « centre mort plein » de
    # ~74 m² qui faisait un couloir de 161 m²), on la PERCE en VRAIE COUR à ciel
    # ouvert (un TROU dans le plancher). Résultat :
    #   - ``cour`` = la plus grande poche centrale, RETRAITÉE de 1,40 m côté apts
    #     pour laisser passer l'ANNEAU de couloir PMR (1,40 m) qui longe les
    #     logements et fait le tour de la cour, reliant toutes les entrées + la cage.
    #   - le couloir reste un ANNEAU MINCE : couloir_L (spine 1,40 m) ∪ le cadre
    #     1,40 m entre apts et cour. AUCUN gros bloc plein (érodé 1,3 m ⇒ ~0 m²).
    #   - la cour est un VIDE : elle est RETIRÉE de surface_plancher_m2 (preuve que
    #     ce n'est pas un renommage) et rendue OUVERTE (plantée, à ciel ouvert).
    # Retour : (shab_gain, cour_polygon | None). Universel (tout L à centre aveugle).
    cour_poly = None
    if corridor_ids:
        i0 = corridor_ids[0]
        thin = _P(circulations[i0].polygon_xy).buffer(0)   # anneau 1,40 m spine L
        apts_u = _uu([_P(c.polygon_xy).buffer(0) for c in apts]).buffer(0.02)
        occ = _uu([apts_u, thin] + fixed).buffer(0.02)
        raw = footprint.difference(occ)
        real = raw.buffer(-0.18).buffer(0.18)   # ignore les hairlines < 0,36 m
        rem = [g for g in (list(real.geoms) if real.geom_type == "MultiPolygon"
                           else ([real] if not real.is_empty else [])) if g.area > 2.0]
        if rem:
            _cp_raw = _core_poly(core)
            core_p = _cp_raw.buffer(0) if _cp_raw is not None else None
            # ── CENTRE = poches aveugles + spine du couloir : la masse au cœur du L.
            center = _uu(rem + [thin]).buffer(0)
            # COUR = la partie « ÉPAISSE » du centre = tout ce qui est plus large
            # qu'un couloir PMR (~1,8 m). Une ÉROSION de 0,9 m PUIS re-dilatation
            # SUPPRIME les rubans minces (l'anneau 1,40 m disparaît) et NE GARDE que
            # le cœur mort large : c'est EXACTEMENT la cour à percer. On la coupe
            # ensuite de la cage (0,3 m) et des apts (0,05 m) pour un contour propre.
            cour = center.buffer(-0.9).buffer(0.9)
            if cour.geom_type == "MultiPolygon":
                cour = max(cour.geoms, key=lambda g: g.area)
            if core_p is not None:
                cour = cour.difference(core_p.buffer(0.3))
            cour = cour.difference(apts_u.buffer(0.05)).buffer(0)
            if cour.geom_type == "MultiPolygon":
                cour = max(cour.geoms, key=lambda g: g.area)
            cour = cour.buffer(-0.1).buffer(0.1).simplify(0.3, preserve_topology=True)
            # ── COUR = RECTANGLE PROPRE (demande user 2026-07-06) ────────────────
            # Le blob organique décentré ci-dessus (cour ~L-notchée, sous-dimensionnée
            # par la sur-érosion) est remplacé par le plus grand RECTANGLE AXIS-ALIGNED
            # inscrit dans le CENTRE MORT RÉEL = (center − cage − apts), rétracté de
            # l'ANNEAU couloir 1,40 m tout autour. Ainsi le rectangle épouse au mieux le
            # cœur aveugle (le résidu de couloir plein autour est minimal, ≤ seuil
            # H-COUR) et l'espace restant (center − cour) forme l'anneau MINCE 1,40 m
            # reliant les entrées + la cage. Si aucun rectangle ≥ 12 m² ne tient, on
            # garde le blob (dégradé gracieux). Universel (tout L/U à centre mort).
            # centre mort RÉEL = tout ce qui, dans le footprint, n'est ni apt ni
            # cage : le cœur aveugle du coude, borné par les apts qui l'entourent et
            # par la cage. On y inscrit le plus grand rectangle laissant l'anneau
            # 1,40 m côté apts. On N'EXCLUT PAS la cage de la région d'inscription :
            # la cage est « au bord » de la cour (escalier au bord, demande user) ; on
            # DÉCOUPE ensuite la cage du rectangle (morsure de coin) pour que le
            # plancher cour ne recouvre pas l'escalier. Le rectangle épouse ainsi tout
            # le coude → le résidu de couloir plein est minimal (< seuil H-COUR).
            _mort_full = footprint.difference(apts_u.buffer(0.02)).buffer(0)
            if _mort_full.geom_type == "MultiPolygon":
                _mort_full = max(_mort_full.geoms, key=lambda g: g.area)
            # CONTRAINDRE au coude : on borne la région d'inscription à un large
            # voisinage de la cour organique (le cœur du L), sinon le rectangle max
            # pourrait se poser dans un couloir d'aile. Le voisinage (cour ⊕ 6 m)
            # couvre tout le centre mort du coude sans déborder dans les ailes.
            _elbow_zone = cour.buffer(6.0)
            _mort_full = _mort_full.intersection(_elbow_zone).buffer(0)
            if _mort_full.geom_type == "MultiPolygon":
                _mort_full = max(_mort_full.geoms, key=lambda g: g.area)
            _rect_cour = _centered_inscribed_rect(_mort_full, ring_m=1.40)
            if _rect_cour is None:
                _rect_cour = _centered_inscribed_rect(cour, ring_m=0.0)
            if _rect_cour is not None and _rect_cour.area >= 12.0:
                # CAGE HORS COUR (2026-07-06, demande user) : une cage escalier+ASC
                # est un volume BÂTI FERMÉ — elle NE PEUT PAS être dans un patio à
                # ciel ouvert. On ne MORD donc plus la cage dans la cour (ancien
                # contour en L où la cage flottait dans le vide) : on RECULE un bord
                # de la cour jusqu'à ce que le rectangle soit DISJOINT de la cage.
                # La cour reste un rectangle PROPRE, la cage retombe dans l'ANNEAU
                # de couloir bâti qui la ceinture (accès à tous les apts conservé).
                # ``cour ∩ cage = 0`` garanti. Universel (tout L/U à centre mort).
                # ── COUR RECTANGLE MAX, CAGE HORS COUR (2026-07-06) ──────────────
                # La cage est BÂTIE : la cour ne peut pas la contenir. On teste les
                # 4 façons de reculer un bord de la cour pour EXCLURE la cage, on
                # DILATE chaque candidat dans le cœur mort (footprint − apts) jusqu'à
                # remplir un côté du coude, et on garde le rectangle d'AIRE MAX. Ainsi
                # la cour épouse le plus grand pan LIBRE du coude (ex. tout le flanc à
                # gauche de la cage, pleine hauteur) et le couloir résiduel autour de
                # la cage redevient un ANNEAU MINCE. cour ∩ cage = 0 garanti.
                _mort_region = footprint.difference(apts_u.buffer(0.02)).buffer(0)
                if _mort_region.geom_type == "MultiPolygon":
                    _mort_region = max(_mort_region.geoms, key=lambda g: g.area)
                if core_p is not None:
                    _rx0, _ry0, _rx1, _ry1 = _rect_cour.bounds
                    _ox0, _oy0, _ox1, _oy1 = core_p.bounds
                    _cl = 0.20
                    from shapely.geometry import box as _bx0
                    _seed_cands = []
                    if (_oy0 - _cl) - _ry0 >= 2.0:      # sous la cage
                        _seed_cands.append(_bx0(_rx0, _ry0, _rx1, _oy0 - _cl))
                    if _ry1 - (_oy1 + _cl) >= 2.0:       # au-dessus
                        _seed_cands.append(_bx0(_rx0, _oy1 + _cl, _rx1, _ry1))
                    if (_ox0 - _cl) - _rx0 >= 2.0:       # à gauche
                        _seed_cands.append(_bx0(_rx0, _ry0, _ox0 - _cl, _ry1))
                    if _rx1 - (_ox1 + _cl) >= 2.0:       # à droite
                        _seed_cands.append(_bx0(_ox1 + _cl, _ry0, _rx1, _ry1))
                    _grown = []
                    for _seed in _seed_cands:
                        if _seed.is_empty or _seed.intersection(core_p).area > 1e-6:
                            continue
                        _g = _expand_rect_in_region(_seed, _mort_region, obstacle=core_p)
                        if _g.intersection(core_p).area <= 1e-6 and _g.area >= 12.0:
                            _grown.append(_g)
                    if _grown:
                        # On NE choisit PAS la plus grande cour, mais celle qui (1)
                        # est la plus ADJACENTE à la cage — la cage est une tour sur
                        # cour INTÉGRÉE, la cour doit longer une de ses faces (≥ 2 m) →
                        # sinon la cage flotte dans le couloir (défaut 2026-07-08) — PUIS
                        # (2) laisse le plus PETIT résidu ÉPAIS de couloir autour de la
                        # cage : le couloir résiduel = (cœur mort − cour − cage), érodé
                        # de 1,1 m (un vrai couloir ≤ 2,2 m DISPARAÎT ; il ne reste que
                        # les slabs plein > corridor). Minimiser ce résidu = anneau
                        # mince, PAS de pan de couloir plein résiduel (H-COUR).
                        # Zone d'ÉVALUATION du bloc résiduel = le COUDE seul (cour ⊕ 4 m),
                        # sinon la spine de l'aile domine la mesure et masque la poche
                        # morte à côté de la cage. On réplique le blob H-COUR DANS ce
                        # voisinage : (cœur mort du coude − cour), érodé 1,30 m puis
                        # re-dilaté, MOINS la cage + 1,40 m de palier PMR.
                        _elbow_eval = _mort_region.intersection(cour.buffer(4.0)).buffer(0)
                        def _fat_residual(_g):
                            _reg = _elbow_eval.union(_g).buffer(0)  # inclut la cour candidate
                            _r = _reg.difference(_g)
                            _r = _r.buffer(-1.30).buffer(1.30)
                            if not _r.is_empty:
                                _r = _r.difference(core_p.buffer(1.40))
                            return _r.area if not _r.is_empty else 0.0
                        def _cage_adjacency(_g):
                            # longueur du contour cage qui longe la cour candidate (gap
                            # ≤ 0,25 m = mur cage/cour). Bornée à _CONTACT_MIN : au-delà
                            # elles sont équivalentes → on laisse le fat trancher.
                            _adj = core_p.boundary.intersection(
                                _g.boundary.buffer(0.25)).length
                            return min(_adj, 2.0)
                        # Clé : d'ABORD min bloc plein résiduel (H-COUR) — c'est le
                        # BLOQUANT le plus dur — ENSUITE max adjacence cage↔cour (cage
                        # intégrée, tour sur cour), ENSUITE max aire.
                        _rect_cour = max(
                            _grown,
                            key=lambda g: (-round(_fat_residual(g), 1),
                                           round(_cage_adjacency(g), 1),
                                           g.area))
                    else:
                        _rect_cour = _expand_rect_in_region(
                            _rect_cour, _mort_region, obstacle=core_p)
                else:
                    _rect_cour = _expand_rect_in_region(_rect_cour, _mort_region)
                cour = _rect_cour

                # ── COULOIR CONTINU : RÉSERVER LES LANES D'ACCÈS (2026-07-08) ──────
                # Confort habitant (demande user) : la cour ne doit JAMAIS couper la
                # circulation. Le cœur mort du L a une CHAMBRE large (le coude) où
                # arrivent PLUSIEURS bras de couloir MINCES (le bandeau supérieur qui
                # relie les ailes + la SPINE verticale qui remonte la jambe droite).
                # Si la cour rectangle occupe TOUTE la largeur de la chambre, elle
                # SÉPARE la spine du bandeau → un habitant qui monte la jambe ne peut
                # plus rejoindre le couloir (défaut v22). On RÉSERVE donc, pour CHAQUE
                # bras mince, une LANE de largeur PMR qui traverse la chambre dans l'axe
                # du bras jusqu'au bord opposé, et on la SOUSTRAIT de la cour. La cour
                # reste un RECTANGLE (on recoupe ensuite au plus grand rectangle inscrit
                # dans le résidu) mais elle LAISSE PASSER le couloir. Universel : dérivé
                # des bras réels du cœur mort (aucune coordonnée en dur).
                _LANE = 1.60   # largeur PMR réservée + petit jeu
                from shapely.geometry import box as _bx
                try:
                    _chamber = _mort_region.buffer(-1.6).buffer(1.6)  # partie LARGE = coude
                    if _chamber.geom_type == "MultiPolygon":
                        _chamber = max(_chamber.geoms, key=lambda g: g.area)
                    _arms = _mort_region.difference(_chamber.buffer(0.05)).buffer(0)
                    _arm_list = ([_arms] if _arms.geom_type == "Polygon"
                                 else list(getattr(_arms, "geoms", [])))
                    _cxx0, _cyy0, _cxx1, _cyy1 = _chamber.bounds
                    _lanes = []
                    for _arm in _arm_list:
                        if _arm.is_empty or _arm.area < 2.0:
                            continue
                        _ax0, _ay0, _ax1, _ay1 = _arm.bounds
                        _aw, _ah = _ax1 - _ax0, _ay1 - _ay0
                        # axe du bras : horizontal (large en x) ou vertical (large en y).
                        # La lane traverse la chambre dans cet axe, centrée sur le bras,
                        # de la largeur PMR, jusqu'aux bords de la chambre.
                        if _aw >= _ah:      # bras horizontal → lane horizontale
                            _cy = (_ay0 + _ay1) / 2.0
                            _lanes.append(_bx(_cxx0 - 0.5, _cy - _LANE / 2,
                                              _cxx1 + 0.5, _cy + _LANE / 2))
                        else:               # bras vertical → lane verticale
                            _cx = (_ax0 + _ax1) / 2.0
                            _lanes.append(_bx(_cx - _LANE / 2, _cyy0 - 0.5,
                                              _cx + _LANE / 2, _cyy1 + 0.5))
                    if _lanes:
                        # RÉGION LIBRE pour la cour = CHAMBRE (bornée au coude) − lanes
                        # réservées − EMPRISE cage (+ 0,25 m d'épaisseur de mur, PAS un
                        # palier : la cage est ADOSSÉE à la cour, elles partagent un mur).
                        # On inscrit le plus grand RECTANGLE NET dans ce libre : la cour
                        # grossit au max (haut/large) sans recouvrir lane ni cage. La
                        # cage garde son pan de couloir à côté (la JONCTION escalier), le
                        # couloir reste CONTINU (lanes non recouvertes). On part du
                        # _mort_region PLEIN (pas l'érodé, qui perd de l'aire → vides).
                        # Universel (dérivé chambre/lanes/cage, aucune coord en dur).
                        _lane_u = _uu(_lanes)
                        _free = (_mort_region.intersection(_chamber.buffer(2.0))
                                 .difference(_lane_u))
                        if core_p is not None:
                            _free = _free.difference(core_p.buffer(0.25))
                        _free = _free.buffer(0)
                        if _free.geom_type == "MultiPolygon":
                            _free = max(_free.geoms, key=lambda g: g.area)
                        _rc = _centered_inscribed_rect(_free, ring_m=0.0)
                        if (_rc is not None and _rc.area >= 12.0
                                and _rc.intersection(_lane_u).area < 0.5
                                and (core_p is None
                                     or _rc.intersection(core_p).area < 0.5)):
                            cour = _rc
                        # REVERT-TEST (COUR_BLOCK_LANE=1) : on GONFLE la cour pour qu'elle
                        # AVALE une lane de couloir (mur → mur), SÉVRANT un bras (la spine)
                        # du reste → un habitant ne peut plus rejoindre le couloir. Sert
                        # à PROUVER que H-COULOIR-CONNEXE FIRE (cour en travers du couloir).
                        # En prod : flag absent → cour rectangle qui laisse passer.
                        import os as _os_blk
                        if _os_blk.environ.get("COUR_BLOCK_LANE") == "1" and _lanes:
                            # avale UNIQUEMENT les lanes qui JOUXTENT la cour (union reste
                            # un seul polygone valide) → la cour déborde en travers d'un
                            # bras, sévrant la spine du reste. H-COULOIR-CONNEXE doit FIRE.
                            _touch = [ln for ln in _lanes
                                      if ln.buffer(0.1).intersects(cour)]
                            if _touch:
                                _blk = cour.union(_uu(_touch)).buffer(0)
                                if _blk.geom_type == "Polygon" and not _blk.is_empty:
                                    cour = _blk
                except Exception:
                    pass

                # ── ABSORBER LE PAN DE COULOIR ÉPAIS RÉSIDUEL EN SHAB ─────────────
                # Une cage CENTRÉE au coude laisse, à côté d'elle, une poche de
                # couloir ÉPAISSE (ex. ~18 m² à gauche de la cage, entre la cour et le
                # spine) : ni cour (la cour est un rectangle qui s'arrête à la cage),
                # ni cage, ni corridor mince. On la REND en SHAB : chaque pan épais est
                # fusionné dans l'apt ADJACENT le plus proche (borné au CAP + contour
                # propre ≤ 10 sommets). Résultat : anneau VRAIMENT mince + SHAB
                # récupérée + cour rectangle net. Universel (tout coude à cage centrée).
                _fat = _mort_region.difference(cour.buffer(0.02)).buffer(0)
                if core_p is not None:
                    _fat = _fat.difference(core_p.buffer(0.10))
                _fat = _fat.intersection(cour.buffer(3.0)).buffer(0)
                # ne garder QUE les slabs ÉPAIS (> couloir ~1,8 m de large) : érosion
                # 0,9 m puis re-dilatation → les couloirs minces disparaissent.
                _fat_thick = _fat.buffer(-0.9).buffer(0.95).intersection(_fat).buffer(0)
                _fat_pieces = (list(_fat_thick.geoms)
                               if _fat_thick.geom_type == "MultiPolygon"
                               else ([_fat_thick] if not _fat_thick.is_empty else []))
                for _pk in sorted(_fat_pieces, key=lambda g: -g.area):
                    if _pk.is_empty or _pk.area < 3.0:
                        continue
                    if _pk.geom_type != "Polygon":
                        _pk = max(_pk.geoms, key=lambda g: g.area)
                    _adj = [c for c in apts
                            if _P(c.polygon_xy).buffer(0).distance(_pk) <= 0.7]
                    if not _adj:
                        continue
                    _best = min(_adj, key=lambda c: _P(c.polygon_xy).distance(_pk))
                    _ap = _P(_best.polygon_xy).buffer(0)
                    _merged = _uu([_ap, _pk]).buffer(0.15).buffer(-0.15)
                    if _merged.geom_type == "MultiPolygon":
                        _merged = max(_merged.geoms, key=lambda g: g.area)
                    if _merged.geom_type != "Polygon":
                        continue
                    _merged = _merged.simplify(0.15, preserve_topology=True)
                    if (_merged.geom_type != "Polygon"
                            or _merged.area > _CAP + 0.5
                            or len(_merged.exterior.coords) > 12):
                        continue
                    _best.polygon_xy = list(_merged.exterior.coords)[:-1]
                    _best.surface_m2 = round(_merged.area, 1)
                    shab_gain += _merged.area - _ap.area
            # une cour n'a de sens qu'au-delà d'un vrai patio (≥ 12 m²). En deçà, on
            # retombe sur l'ancien comportement (verser au couloir) : pas de cour.
            if (not cour.is_empty and cour.geom_type == "Polygon"
                    and cour.area >= 12.0 and len(cour.exterior.coords) <= 12):
                cour_poly = cour
                # COULOIR = l'ANNEAU MINCE qui reste = center − cour. On le STOCKE
                # comme le contour EXTÉRIEUR du centre (polygone simple, sans trou :
                # le schéma n'accepte pas d'anneau) et la COUR, rendue OUVERTE
                # (verte, à ciel ouvert) PAR-DESSUS, masque le centre. La surface
                # WALKABLE réelle (contour − cour) est un vrai anneau 1,40 m (érodé
                # à 1,3 m ⇒ 0 bloc plein) : c'est ce que mesure le gate. On stocke
                # surface_m2 = anneau réel (contour − cour) pour l'honnêteté du bilan.
                # le couloir = centre MOINS ce qui vient d'être absorbé en apt (sinon
                # le couloir recouvrirait la SHAB récupérée). On re-soustrait donc les
                # apts (agrandis) du centre avant de stocker l'anneau.
                _apts_now = _uu([_P(c.polygon_xy).buffer(0) for c in apts]).buffer(0.02)
                # COULOIR = TOUT le cœur mort MOINS les apts MOINS la cage : c'est le
                # walkable réel (la cour, rendue verte PAR-DESSUS, y creuse son trou).
                # On part du _mort_region PLEIN (footprint − apts, borné au coude) pour
                # que la bande dégagée à côté de la cage rétrécie (défaut « VIDE » quand
                # on shrink la cour) soit BIEN couverte par le couloir : aucun blanc.
                # On PONTE les hairlines (+0,2/−0,2) pour garder le couloir d'un SEUL
                # tenant (sinon un lobe pincé par cour+cage serait droppé → VIDE).
                _mort_cov = _mort_full if "_mort_full" in dir() else center
                _cover = center.union(_mort_cov).difference(_apts_now)
                if core_p is not None:
                    _cover = _cover.difference(core_p.buffer(0.02))
                ring_ext = _cover.buffer(0.2).buffer(-0.2).buffer(0)
                if ring_ext.geom_type == "MultiPolygon":
                    ring_ext = max(ring_ext.geoms, key=lambda g: g.area)
                if ring_ext.geom_type == "Polygon" and not ring_ext.is_empty:
                    ring_ext = _P(list(ring_ext.exterior.coords)).simplify(
                        0.2, preserve_topology=True)
                if ring_ext.geom_type == "Polygon" and not ring_ext.is_empty:
                    circulations[i0].polygon_xy = list(ring_ext.exterior.coords)[:-1]
                    circulations[i0].surface_m2 = round(
                        max(1.0, ring_ext.area - cour.area), 1)
            else:
                cour_poly = None
                # pas de cour propre → ancien comportement : verser au couloir.
                base = _P(circulations[i0].polygon_xy).buffer(0)
                add = [g.intersection(footprint).buffer(0) for g in rem]
                merged = _uu([base] + add).buffer(0.08).buffer(-0.08)
                if merged.geom_type == "MultiPolygon":
                    merged = max(merged.geoms, key=lambda g: g.area)
                if merged.geom_type == "Polygon":
                    merged = merged.simplify(0.25, preserve_topology=True)
                    if merged.geom_type == "Polygon" and list(merged.interiors):
                        merged = _P(list(merged.exterior.coords))
                if merged.geom_type == "Polygon":
                    circulations[i0].polygon_xy = list(merged.exterior.coords)[:-1]
                    circulations[i0].surface_m2 = round(merged.area, 1)
    return shab_gain, cour_poly


def _harmonize_court_gardens(cells, jardin_commun_poly):
    """PAVAGE PROPRE EN MOULIN (pinwheel) des jardins RDC bordant la cour (défaut user 2026-07-08).

    OBJECTIF (mesuré sur 80 Héros v18, à corriger) :
      - 05 (T4) et 10 (T4) NE SE TOUCHAIENT PAS (2,00 m d'écart) ;
      - le COMMUN avait un BRAS de 1 m (11 sommets, forme en L) = bande inutilisable ;
      - pavage non tuilé proprement.
    CIBLE : chaque apt-cour reçoit un jardin RECTANGLE NET devant SA façade ; les jardins de
    MÊME typologie sont CONCORDANTS (mêmes dimensions) ET, quand ils tournent autour du coin
    des mitoyens, SE TOUCHENT à l'angle (distance = 0) ; le COMMUN = un RECTANGLE net (≤ 6
    sommets, min-largeur ≥ _MIN_W, aucun bras) logé dans le coin des deux mitoyens ; toute la
    cour est tuilée, résidu négligeable.

    LOGIQUE UNIVERSELLE (aucune coordonnée en dur — tout dérivé de la géométrie réelle) :
      1. COUR = bbox de l'union (jardins-cour ∪ commun). Ses 4 arêtes sont soit des FAÇADES
         (une arête d'apt y coïncide), soit des MITOYENS (aucune façade). Chaque apt-cour est
         rattaché à SON arête de cour (façade) + son SPAN le long de cette arête.
      2. Le COIN COMMUN = l'intersection des DEUX arêtes MITOYENS (les 2 côtés sans façade).
         C'est là que loge le jardin commun (le fond de cour que personne ne fronte).
      3. PINWHEEL : on choisit un PIVOT (cx, cy) dans la cour. Le commun = le quadrant du coin
         mitoyen jusqu'au pivot. Chaque apt prend, DEVANT sa façade, la bande pleine profondeur
         jusqu'au pivot (le long de sa moitié de cour), de sorte que les jardins tournent autour
         du pivot en moulin et se touchent aux angles. Le pivot est calé pour que :
           - les DEUX apts de MÊME typo qui se disputent le coin aient la MÊME profondeur
             (concordants) et se touchent au pivot (distance 0) ;
           - le commun soit ≥ _MIN_W × _MIN_W ;
           - les jardins des autres façades (06/08) restent DÉCENTS (≥ _MIN_DECENT).
      4. Le pivot par défaut = milieu de cour ; on l'ajuste vers le coin mitoyen tant que la
         profondeur des apts de coin dépasse leur plafond d'aire _AREA_MAX, sans descendre
         sous _MIN_W pour le commun. Si la structure pinwheel ne se détecte pas (cour non
         rectangulaire, < 2 façades perpendiculaires), on retourne l'entrée inchangée.

    Écrit ``cell.jardin_polygon_xy``. Retourne le jardin_commun (Polygon rectangle) mis à jour.
    """
    from shapely.geometry import Polygon as _P, box as _bx
    from shapely.ops import unary_union as _uu

    _AREA_MAX = {"T1": 45.0, "T2": 42.0, "T3": 48.0, "T4": 72.0, "T5": 78.0}
    _MIN_W = 4.0
    _EDGE_TOL = 0.6

    # ── 1. jardins-cour privatifs (cellule, typo, bbox). On ne PAVE que les jardins
    #    RECTANGLES (4 sommets) ; les L déjà réglés restent tels quels mais comptent
    #    dans la cour.
    _gardens = []
    for _c in cells:
        if getattr(_c, "type", None) != CelluleType.LOGEMENT:
            continue
        _j = getattr(_c, "jardin_polygon_xy", None)
        if not (_j and len(_j) >= 3):
            continue
        _poly = _P(_j)
        if _poly.is_empty or _poly.geom_type != "Polygon":
            continue
        _typ = str(getattr(_c, "typologie", "")).split(".")[-1]
        _is_rect = (len(_poly.exterior.coords) - 1 == 4)
        _gardens.append([_c, _typ, list(_poly.bounds), _is_rect])

    if len(_gardens) < 2:
        return jardin_commun_poly

    # ── 2. COUR = bbox de tout (jardins + commun).
    _all = [_bx(*g[2]) for g in _gardens]
    if jardin_commun_poly is not None and not jardin_commun_poly.is_empty:
        _all.append(jardin_commun_poly)
    _court_u = _uu(_all)
    _cx0, _cy0, _cx1, _cy1 = _court_u.bounds
    _cour = _bx(_cx0, _cy0, _cx1, _cy1)

    # ── 3. Pour chaque apt, détecte SON arête de cour (FAÇADE = côté où le BÂTI de l'apt
    #    est adossé) + son span le long de cette arête. La FAÇADE n'est PAS déductible de
    #    la seule bbox jardin (un jardin de coin touche 2 arêtes de cour : sa vraie façade
    #    ET un mitoyen). On la dérive du POLYGONE DE L'APT : la façade = l'arête de la cour
    #    la plus PROCHE du corps de l'apt (l'apt fronte la cour DEPUIS ce côté). Le jardin
    #    s'extrude DEPUIS cette façade vers l'intérieur de la cour. Universel.
    #    side ∈ {"S","N","O","E"} = arête de la COUR contre laquelle l'apt fronte.
    _facs = []   # (apt_idx, side, span_lo, span_hi)
    _side_present = set()
    from shapely.geometry import LineString as _Ls
    for _gi, (_c, _typ, _bb, _isr) in enumerate(_gardens):
        _x0, _y0, _x1, _y1 = _bb
        # La FAÇADE = l'arête de la bbox jardin adossée au CORPS de l'apt (là où le jardin
        # jouxte le bâtiment). On mesure, pour chaque arête de bbox jardin coïncidant avec
        # une arête de la COUR, la LONGUEUR partagée avec la frontière de l'apt. La façade
        # est l'arête à plus grand recouvrement (le jardin s'extrude DEPUIS elle vers la
        # cour). Robuste au cas du jardin de coin (2 arêtes sur la cour, mais une seule
        # jouxte vraiment le corps de l'apt). Universel.
        _apb = _P(_c.polygon_xy).boundary.buffer(0.25)
        _cand = []
        _edges = [
            ("S", _y0, _cy0, _Ls([(_x0, _y0), (_x1, _y0)]), _x0, _x1),
            ("N", _y1, _cy1, _Ls([(_x0, _y1), (_x1, _y1)]), _x0, _x1),
            ("O", _x0, _cx0, _Ls([(_x0, _y0), (_x0, _y1)]), _y0, _y1),
            ("E", _x1, _cx1, _Ls([(_x1, _y0), (_x1, _y1)]), _y0, _y1),
        ]
        for _s, _pos, _cedge, _ln, _lo, _hi in _edges:
            if abs(_pos - _cedge) >= _EDGE_TOL:
                continue  # cette arête du jardin ne coïncide pas avec la cour
            _shared = _ln.intersection(_apb).length
            _cand.append((_s, _shared, _lo, _hi))
        if not _cand:
            continue
        # façade = arête jardin qui longe le plus le corps de l'apt.
        _side, _sh, _lo, _hi = max(_cand, key=lambda t: t[1])
        _facs.append([_gi, _side, _lo, _hi])
        _side_present.add(_side)

    # ── 4. arêtes MITOYENNES = les 2 côtés SANS façade. Le coin commun est leur jonction.
    _mit = [s for s in ("S", "N", "O", "E") if s not in _side_present]
    # on n'active le pavage moulin QUE si exactement 2 façades perpendiculaires + 2 mitoyens
    # perpendiculaires (structure en L classique). Sinon on laisse tel quel (universalité :
    # ne casse pas une topologie non-pinwheel).
    _perp = lambda a, b: {a, b} in ({"S", "O"}, {"S", "E"}, {"N", "O"}, {"N", "E"})
    _facade_sides = sorted(_side_present)
    if len(_mit) != 2 or not _perp(_mit[0], _mit[1]):
        return jardin_commun_poly
    if len(_facade_sides) != 2 or not _perp(_facade_sides[0], _facade_sides[1]):
        return jardin_commun_poly

    # coin commun = intersection des 2 mitoyens : (mx, my) ∈ {cx0/cx1} × {cy0/cy1}.
    _mx = _cx0 if "O" in _mit else _cx1
    _my = _cy0 if "S" in _mit else _cy1
    # pivot : point autour duquel tournent les jardins. Sa position (px,py) fixe la
    # profondeur du commun = |px-mx| × |py-my|. Départ = milieu de cour.
    _W = _cx1 - _cx0
    _H = _cy1 - _cy0

    # apts de COIN = les 2 apts (un par façade) dont le jardin est ADJACENT au commun
    # (span touchant le coin commun). Ils doivent SE TOUCHER au pivot et être concordants.
    #   - façade horizontale (S/N) adjacente au coin : span en x touchant _mx.
    #   - façade verticale (O/E) adjacente au coin : span en y touchant _my.
    def _adj_coin(_f):
        _gi, _side, _lo, _hi = _f
        if _side in ("S", "N"):
            return min(abs(_lo - _mx), abs(_hi - _mx)) < _EDGE_TOL + 1e-6
        return min(abs(_lo - _my), abs(_hi - _my)) < _EDGE_TOL + 1e-6

    _coin_h = next((f for f in _facs if f[1] in ("S", "N") and _adj_coin(f)), None)
    _coin_v = next((f for f in _facs if f[1] in ("O", "E") and _adj_coin(f)), None)

    # pivot (px, py) : point de contact des jardins de coin, autour duquel ils tournent en
    # moulin. Il fixe : le commun = [mx→px]×[my→py] ; le coin-H = [mx→px]×[fyH→py-strip] ;
    # le coin-V = [px→far_x]×[my→py]. Les deux jardins de coin SE TOUCHENT en (px, py).
    #
    # CONCORDANCE : quand les 2 apts de coin sont de MÊME typologie (ex. 05 & 10 = T4), on
    # veut des jardins CONGRUENTS (mêmes dimensions bbox). Avec les défs ci-dessus :
    #   coin-H dims = (|px-mx|, |cy_facadeH - py|) ; coin-V dims = (|far_x - px|, |py-my|).
    #   far_x = cx1 si façade V à droite (E) sinon cx0 ; cy_facadeH = cy1 si façade H en haut.
    # Congruence ⇒ |px-mx| = |far_x - px| ET |cy_fH - py| = |py-my|, dont la solution est le
    # MILIEU de cour : px = (cx0+cx1)/2, py = (cy0+cy1)/2. C'est le pivot par défaut quand
    # les coins sont de même typo → 05 = 10 = W/2 × H/2, contact exact, commun = W/2 × H/2.
    _same_typo_coins = (
        _coin_h is not None and _coin_v is not None
        and _gardens[_coin_h[0]][1] == _gardens[_coin_v[0]][1])
    if _same_typo_coins:
        _px = (_cx0 + _cx1) / 2
        _py = (_cy0 + _cy1) / 2
    else:
        # typos différentes : on garde une profondeur proportionnée (~moitié de cour) tout en
        # dérivant du span réel de chaque coin (le jardin le mieux servi donne la ligne). On
        # part du milieu et on laisse le plafond d'aire ajuster.
        _px = (_cx0 + _cx1) / 2
        _py = (_cy0 + _cy1) / 2
        if _coin_h is not None:
            _lo, _hi = _coin_h[2], _coin_h[3]
            _far = _hi if abs(_lo - _mx) < abs(_hi - _mx) else _lo
            _px = (_mx + _far) / 2 if abs(_far - _mx) >= 2 * _MIN_W else _px
        if _coin_v is not None:
            _lo, _hi = _coin_v[2], _coin_v[3]
            _far = _hi if abs(_lo - _my) < abs(_hi - _my) else _lo
            _py = (_my + _far) / 2 if abs(_far - _my) >= 2 * _MIN_W else _py

    # ── plafond d'aire des apts de coin : si un jardin de coin dépasse son cap, on RAPPROCHE
    #    le pivot du coin mitoyen (réduit sa profondeur) — mais jamais sous _MIN_W pour le
    #    commun. On borne aussi la profondeur au plafond d'aire de l'apt de coin.
    def _cap_pivot():
        nonlocal _px, _py
        # apt-H de coin : jardin = x∈[mx,px] × profondeur (façade_y → py). aire = |px-mx|×|py-fy_H|.
        if _coin_h is not None:
            _fy = _cy1 if _coin_h[1] == "N" else _cy0        # y de la façade (bâti)
            _cap = _AREA_MAX.get(_gardens[_coin_h[0]][1], 65.0)
            _wx = abs(_px - _mx)
            if _wx > 0:
                _max_depth = _cap / _wx
                # profondeur = |py - fy| ; rapproche py de fy si trop profond.
                if abs(_py - _fy) > _max_depth:
                    _py = _fy + _max_depth * (1 if _py > _fy else -1)
        if _coin_v is not None:
            _fx = _cx1 if _coin_v[1] == "E" else _cx0
            _cap = _AREA_MAX.get(_gardens[_coin_v[0]][1], 65.0)
            _hy = abs(_py - _my)
            if _hy > 0:
                _max_depth = _cap / _hy
                if abs(_px - _fx) > _max_depth:
                    _px = _fx + _max_depth * (1 if _px > _fx else -1)
    _cap_pivot()

    # commun ≥ _MIN_W : garantit |px-mx| ≥ _MIN_W et |py-my| ≥ _MIN_W.
    if abs(_px - _mx) < _MIN_W:
        _px = _mx + _MIN_W * (1 if _px > _mx else -1)
    if abs(_py - _my) < _MIN_W:
        _py = _my + _MIN_W * (1 if _py > _my else -1)

    _pxlo, _pxhi = sorted((_mx, _px))
    _pylo, _pyhi = sorted((_my, _py))

    # ── 5. PAVAGE EN 4 ZONES + RÉSIDU. La cour rectangulaire se découpe au pivot en 4
    #    quadrants autour du coin mitoyen :
    #      • COMMUN   = [mx→px] × [my→py]                (coin des 2 mitoyens)
    #      • COIN-H   = [mx→px] × [py→façade_H]          (au-dessus/dessous du commun)
    #      • COIN-V   = [px→façade_V] × [my→py]          (à côté du commun)
    #      • RÉSIDU   = [px→façade_V] × [py→façade_H]     (quadrant opposé au coin mitoyen)
    #    Les 2 coins se touchent EXACTEMENT au pivot (px,py) et, à typo égale, sont congruents.
    #    Le RÉSIDU (quadrant NE ici) est partagé entre les apts NON-COIN, chacun DEVANT SA
    #    façade : on le découpe en bandes le long de son GRAND axe, une bande par apt non-coin,
    #    proportionnelle à la longueur de sa façade dans le quadrant. Chaque bande couvre la
    #    pleine profondeur du quadrant → rectangle plein, tuilage complet, 0 bande fine.
    _fxH = _cy1 if (_coin_h is not None and _coin_h[1] == "N") else _cy0  # y façade H
    _fxV = _cx1 if (_coin_v is not None and _coin_v[1] == "E") else _cx0  # x façade V
    # bords du commun / des colonnes.
    _cm_xlo, _cm_xhi = sorted((_mx, _px))
    _cm_ylo, _cm_yhi = sorted((_my, _py))
    # quadrant résidu = côté OPPOSÉ au coin mitoyen sur les 2 axes.
    _rq_xlo, _rq_xhi = sorted((_px, _fxV))
    _rq_ylo, _rq_yhi = sorted((_py, _fxH))

    _new_rects = {}   # gi -> box
    # 5a. les 2 apts de COIN.
    if _coin_h is not None:
        _y0, _y1 = sorted((_fxH, _py))
        _new_rects[_coin_h[0]] = _bx(_cm_xlo, _y0, _cm_xhi, _y1)
    if _coin_v is not None:
        _x0, _x1 = sorted((_fxV, _px))
        _new_rects[_coin_v[0]] = _bx(_x0, _cm_ylo, _x1, _cm_yhi)

    # 5b. RÉSIDU partagé entre les apts non-coin, chacun devant SA façade. On projette
    #     chaque apt non-coin sur le GRAND axe du quadrant (celui le long des façades qui le
    #     bordent) et on lui donne une bande pleine-profondeur. Ordre = position de façade.
    _noncoin = [f for f in _facs if f is not _coin_h and f is not _coin_v]
    _qw = _rq_xhi - _rq_xlo
    _qh = _rq_yhi - _rq_ylo
    if _noncoin and _qw > 1e-6 and _qh > 1e-6:
        # axe de découpe = le plus LONG côté du quadrant (bandes le long de cet axe).
        _split_x = _qw >= _qh
        # position de chaque apt non-coin le long de l'axe de découpe = milieu de son span
        # projeté. Pour une façade H (span en x) l'axe naturel est x ; pour une façade V
        # (span en y) l'axe est y. On projette sur l'axe de découpe commun.
        def _apt_key(_f):
            _gi, _side, _lo, _hi = _f
            _mid = (_lo + _hi) / 2
            if _split_x:
                # bandes en x : ordonne par x. façade H → span déjà en x ; façade V → x = _fxV.
                return _mid if _side in ("S", "N") else (_rq_xlo + _rq_xhi) / 2
            return _mid if _side in ("O", "E") else (_rq_ylo + _rq_yhi) / 2
        _noncoin_sorted = sorted(_noncoin, key=_apt_key)
        _n = len(_noncoin_sorted)
        for _k, _f in enumerate(_noncoin_sorted):
            _gi = _f[0]
            if _split_x:
                _bx0 = _rq_xlo + _qw * _k / _n
                _bx1 = _rq_xlo + _qw * (_k + 1) / _n
                _new_rects[_gi] = _bx(_bx0, _rq_ylo, _bx1, _rq_yhi)
            else:
                _by0 = _rq_ylo + _qh * _k / _n
                _by1 = _rq_ylo + _qh * (_k + 1) / _n
                _new_rects[_gi] = _bx(_rq_xlo, _by0, _rq_xhi, _by1)

    # drop les rectangles trop minces (< _MIN_W).
    for _gi in list(_new_rects.keys()):
        _rb = _new_rects[_gi].bounds
        if _rb[2] - _rb[0] < _MIN_W - 1e-6 or _rb[3] - _rb[1] < _MIN_W - 1e-6:
            del _new_rects[_gi]

    # ── 5c. GARDE D'ATOMICITÉ (universalité, zéro corruption). Le pavage moulin n'est écrit
    #    QUE s'il est COMPLET et propre :
    #      • les 2 apts de COIN ont été détectés + pavés (le moulin a bien 2 coins) ;
    #      • CHAQUE apt-façade a reçu un rectangle valide (aucun jardin perdu) ;
    #      • les rects ne se CHEVAUCHENT pas et couvrent la cour (résidu < 10 % de la cour).
    #    Sinon (topologie miroir/atypique mal captée, entrée dégénérée) on N'ÉCRIT RIEN et on
    #    RETOURNE le commun d'origine inchangé → jamais de pavage partiel incohérent.
    _complete = (
        _coin_h is not None and _coin_v is not None
        and _coin_h[0] in _new_rects and _coin_v[0] in _new_rects
        and len(_new_rects) == len(_facs))
    if _complete:
        _pv = list(_new_rects.values())
        _ov = sum(_pv[_i].intersection(_pv[_k]).area
                  for _i in range(len(_pv)) for _k in range(_i + 1, len(_pv)))
        _cover = _uu(_pv + [_bx(min(_mx, _px), min(_my, _py),
                                max(_mx, _px), max(_my, _py))]).area
        if _ov > 1.0 or _cover < 0.90 * _cour.area:
            _complete = False
    if not _complete:
        return jardin_commun_poly

    # ── 6. Écrit les jardins pavés (rectangles nets).
    for _gi, _rect in _new_rects.items():
        _rb = _rect.bounds
        _gardens[_gi][0].jardin_polygon_xy = [
            (round(float(x), 2), round(float(y), 2))
            for x, y in list(_bx(*_rb).exterior.coords)[:-1]]

    # ── 7. COMMUN = rectangle net (coin mitoyen → pivot), + tout résidu de cour non couvert
    #    par les jardins pavés reversé, MAIS on ne garde que le PLUS GRAND RECTANGLE inscrit
    #    (pas de bras). On part du rectangle-coin et on absorbe le résidu voisin s'il agrandit
    #    proprement une des 2 dimensions.
    _commun = _bx(_pxlo, _pylo, _pxhi, _pyhi)
    _priv = [r for r in _new_rects.values() if r is not None]
    # résidu = cour − (privés ∪ commun) : normalement négligeable. Si une bande propre
    # jouxte le commun sur toute une arête, on l'y ajoute (rectangle agrandi, pas de bras).
    _resid = _cour.difference(_uu(_priv + [_commun])) if _priv else _cour.difference(_commun)
    if not _resid.is_empty:
        _bits = [_resid] if _resid.geom_type == "Polygon" else list(_resid.geoms)
        for _b in _bits:
            if _b.area < 2.0:
                continue
            _u = _uu([_commun, _b])
            if _u.geom_type == "Polygon" and len(_u.exterior.coords) - 1 <= 4:
                _ub = _u.bounds
                if min(_ub[2] - _ub[0], _ub[3] - _ub[1]) >= _MIN_W - 1e-6:
                    _commun = _bx(*_ub)
    return _commun


def _compute_jardin_polygons_u(cells, footprint, parcelle) -> None:
    """Jardins privatifs RDC pour un footprint en U.

    La cour intérieure du U (l'échancrure) est l'espace vert commun ; chaque
    logement RDC reçoit une BANDE de jardin dans la cour, DEVANT sa façade cour
    (le côté ``c.orientation``), pleine largeur de l'apt, profondeur ~gardenDepth
    bornée à la cour. Écrit ``cell.jardin_polygon_xy`` sur chaque apt RDC.

    Universel (4 orientations d'ouverture) : la cour = ``decompose_u(...).court``.
    """
    from shapely.geometry import Polygon as _P
    from shapely.geometry import box as _box
    try:
        from core.building_model.layout_u import decompose_u
    except Exception:
        return
    d = decompose_u(footprint)
    if d is None:
        return
    court = d.court
    cminx, cminy, cmaxx, cmaxy = court.bounds
    _GARDEN_DEPTH = 4.0  # profondeur de bande jardin visée (m)

    apts = [c for c in cells
            if c.type == CelluleType.LOGEMENT and c.polygon_xy and len(c.polygon_xy) >= 3]
    for c in apts:
        cour_side = (c.orientation or [None])[0]
        if cour_side not in ("sud", "nord", "est", "ouest"):
            continue
        axmin = min(p[0] for p in c.polygon_xy)
        aymin = min(p[1] for p in c.polygon_xy)
        axmax = max(p[0] for p in c.polygon_xy)
        aymax = max(p[1] for p in c.polygon_xy)
        # La bande jardin part de la façade cour de l'apt et s'enfonce dans la
        # cour, sur la profondeur _GARDEN_DEPTH bornée aux bounds de la cour.
        if cour_side == "sud":      # cour sous l'apt (y décroît)
            y1 = aymin
            y0 = max(cminy, aymin - _GARDEN_DEPTH)
            rect = _box(max(axmin, cminx), y0, min(axmax, cmaxx), y1)
        elif cour_side == "nord":   # cour au-dessus de l'apt
            y0 = aymax
            y1 = min(cmaxy, aymax + _GARDEN_DEPTH)
            rect = _box(max(axmin, cminx), y0, min(axmax, cmaxx), y1)
        elif cour_side == "ouest":  # cour à gauche de l'apt
            x1 = axmin
            x0 = max(cminx, axmin - _GARDEN_DEPTH)
            rect = _box(x0, max(aymin, cminy), x1, min(aymax, cmaxy))
        else:                       # est : cour à droite
            x0 = axmax
            x1 = min(cmaxx, axmax + _GARDEN_DEPTH)
            rect = _box(x0, max(aymin, cminy), x1, min(aymax, cmaxy))
        # Clip à la cour réelle (jamais dans le bâti) et à la parcelle si fournie.
        try:
            g = rect.intersection(court)
            if parcelle is not None:
                g = g.intersection(parcelle)
        except Exception:
            g = rect
        if g.is_empty or g.geom_type != "Polygon" or g.area < 2.0:
            continue
        c.jardin_polygon_xy = list(g.exterior.coords)[:-1]


def _compute_jardin_polygons(
    cells: list[Cellule],
    footprint,
    parcelle,
    voirie_orientations: tuple[str, ...] | None = None,
    *,
    void_only: bool = False,
) -> None:
    """Tile exterior zones (L-notch, etc.) among adjacent RDC apts.

    ``void_only`` : bâti à l'alignement de voie (UA.6). Les jardins côté RUE
    sont IMPOSSIBLES (le bâti est en limite séparative) → seuls les jardins
    donnant sur le VOID (l'échancrure / coin ouvert = fond de parcelle, côté
    mitoyens) sont émis. Décision user 2026-07-03 : jardins côté rue remplacés
    par loggias, MAIS « jardin au fond » reste un invariant. Le tuilage du notch
    (angle rentrant) reste actif car il vit déjà dans le void.

    Writes the result directly to ``cell.jardin_polygon_xy`` on each apt
    that should receive an explicit tiled jardin polygon.

    Zone-tiling rules:
    - Detect the L-notch rectangle from the footprint via the layout_l
      decomposition (missing bbox quadrant).
    - Find RDC apts adjacent to each edge of the notch.
    - If exactly 2 adjacent apts with walls on perpendicular notch edges,
      partition the notch rectangle in HALF along the axis that splits
      the two apts fairly (vertical cut when one apt is east, other south).
    - Each apt's jardin = its half of the notch rect.

    Apts not adjacent to the notch retain the legacy per-wall extrusion
    handling downstream in the frontend.

    Non-L footprints currently receive no explicit jardins from this
    helper (frontend extrusion continues to work).
    """
    from shapely.geometry import Polygon as ShapelyPoly

    try:
        from core.building_model.layout_dispatcher import classify_footprint_topology
        from core.building_model.layout_l import decompose_l
    except Exception:
        return

    _topo = classify_footprint_topology(footprint)
    if _topo == "U":
        _compute_jardin_polygons_u(cells, footprint, parcelle)
        return
    if _topo != "L":
        return
    d = decompose_l(footprint)
    if d is None:
        return

    # The L-notch rectangle = the bbox quadrant missing from the L.
    # From the decomposition: bar covers full bbox width at one y-strip,
    # leg is a vertical strip on one side. The notch is the rectangle
    # on the OPPOSITE side of the leg within the bar's "other" y-strip.
    fminx, fminy, fmaxx, fmaxy = footprint.bounds
    bx0, by0, bx1, by1 = d.bar.bounds
    lx0, ly0, lx1, ly1 = d.leg.bounds

    # Notch spans the leg's y-range but the x-range NOT occupied by the
    # leg within the full bbox.
    notch_y0 = ly0
    notch_y1 = ly1
    # Leg is either at x=[lx0, lx1] ⊂ [fminx, fmaxx]. Notch x-range is
    # the complement within bbox on the side OPPOSITE to the leg.
    if lx0 - fminx > fmaxx - lx1:
        # Leg is on the east side → notch is west side
        notch_x0 = fminx
        notch_x1 = lx0
    else:
        # Leg is on the west side → notch is east side
        notch_x0 = lx1
        notch_x1 = fmaxx

    notch_w = notch_x1 - notch_x0
    notch_h = notch_y1 - notch_y0
    if notch_w < 1.0 or notch_h < 1.0:
        return

    notch_rect = ShapelyPoly([
        (notch_x0, notch_y0), (notch_x1, notch_y0),
        (notch_x1, notch_y1), (notch_x0, notch_y1),
    ])

    # ══ JARDINS RDC GÉNÉREUX — PARTITION DU VOID PAR FAÇADE (défaut user 2026-07-06) ══
    # DÉFAUT : le coin ouvert arrière (échancrure SO, ~288 m²) était découpé en bandes
    # FINES en L (05→44, 06→14 « lichette », 08→30, 10→50 ; ~150 m² du void restaient
    # NUS). RÈGLE user : chaque apt RDC donnant sur l'ARRIÈRE reçoit un VRAI jardin
    # privatif GÉNÉREUX (profond), un par apt, sans chevauchement, dans l'emprise
    # parcelle. On PARTITIONNE tout le void entre les apts qui le bordent, par
    # PROXIMITÉ à leur façade (Voronoi discret sur grille) → chaque apt prend la part
    # du void la plus proche de SA façade. Puis on rectangularise (bbox de la part
    # clippée au void ∩ parcelle) pour un jardin propre au plan. Universel (tout L).
    _void_env = notch_rect
    if parcelle is not None and not parcelle.is_empty:
        _void_env = _void_env.intersection(parcelle.buffer(0))
    # apts RDC bordant le void : une de leurs arêtes coïncide avec une arête du void.
    _EDGE_TOL = 0.35

    def _void_facade_seg(apt):
        """Retourne (cx, cy) = milieu de l'arête de l'apt qui borde le void, ou None.
        On teste les 4 côtés de la bbox de l'apt contre les 4 arêtes du void."""
        xs = [p[0] for p in apt.polygon_xy]; ys = [p[1] for p in apt.polygon_xy]
        ax0, ay0, ax1, ay1 = min(xs), min(ys), max(xs), max(ys)
        _ox0 = max(ax0, notch_x0); _ox1 = min(ax1, notch_x1)
        _oy0 = max(ay0, notch_y0); _oy1 = min(ay1, notch_y1)
        # sud de l'apt sur arête nord du void (y=notch_y1) : apt AU-DESSUS du void.
        if abs(ay0 - notch_y1) < _EDGE_TOL and _ox1 - _ox0 > 1.0:
            return ("h", (_ox0 + _ox1) / 2, notch_y1, _ox0, _ox1)
        # nord de l'apt sur arête sud du void (y=notch_y0) : apt SOUS le void.
        if abs(ay1 - notch_y0) < _EDGE_TOL and _ox1 - _ox0 > 1.0:
            return ("h", (_ox0 + _ox1) / 2, notch_y0, _ox0, _ox1)
        # ouest de l'apt sur arête est du void (x=notch_x1) : apt À DROITE du void.
        if abs(ax0 - notch_x1) < _EDGE_TOL and _oy1 - _oy0 > 1.0:
            return ("v", notch_x1, (_oy0 + _oy1) / 2, _oy0, _oy1)
        # est de l'apt sur arête ouest du void (x=notch_x0) : apt À GAUCHE du void.
        if abs(ax1 - notch_x0) < _EDGE_TOL and _oy1 - _oy0 > 1.0:
            return ("v", notch_x0, (_oy0 + _oy1) / 2, _oy0, _oy1)
        return None

    _void_apts = []   # (apt, kind, seg_lo, seg_hi, axis_coord)
    for apt in cells:
        if apt.type != CelluleType.LOGEMENT or not apt.polygon_xy:
            continue
        seg = _void_facade_seg(apt)
        if seg is not None:
            _void_apts.append((apt, seg))

    if _void_apts:
        # ══ JARDINS RDC — CONFORT DE L'HABITANT, PAS ÉGALITÉ DES m² (user 2026-07-07 v15) ══
        # PRINCIPE (se mettre à la place de l'habitant RDC) : chaque apt sort de SON séjour
        # directement sur SON jardin (porte-fenêtre), un jardin COMPACT et USABLE (table +
        # pelouse + arbre), JAMAIS un bras d'herbe en escalier. Taille PROPORTIONNÉE au
        # logement (T2 petit, T4 grand) = naturel et accepté. Pas d'égalité stricte.
        #
        # DÉFAUT v14 (abandonné) : on égalisait les AIRES (~cour/4 chacun) par croissance de
        # régions → jardins en formes escalier/bras enroulant le coin rentrant (16-18 sommets)
        # = INHABITABLES. On avait optimisé la mauvaise chose.
        #
        # MÉTHODE v15 : chaque apt-cour reçoit UN RECTANGLE devant SA façade séjour/cour,
        # profondeur proportionnelle à sa typologie, largeur = l'étendue de SA façade. On
        # résout le SEUL conflit (coin rentrant, où 2 façades perpendiculaires se disputent
        # le carré du coin) en COUPANT le carré entre les 2 apts contigus (chacun garde un
        # rectangle ≥ MIN_W, adjacent à SA façade). Le RÉSIDU profond (fond de coin que
        # personne n'atteint proprement) devient un ESPACE VERT COMMUN planté. Universel :
        # dérivé des SEULES façades cour, aucun cas en dur. Retourne le polygone commun (ou
        # None si résidu négligeable) pour que l'appelant le pose sur le Niveau.
        import numpy as _np
        from shapely.geometry import box as _boxJ, Point as _PtJ
        from shapely.ops import unary_union
        vx0, vy0, vx1, vy1 = _void_env.bounds
        _vcx, _vcy = (vx0 + vx1) / 2, (vy0 + vy1) / 2

        _MIN_W = 4.0            # largeur minimale usable partout (aucun bras étroit)
        # profondeur de jardin MAX par typologie. Au-delà (fond de coin non atteignable
        # devant sa façade) → ESPACE VERT COMMUN, pas du privatif. T2 = 8 pour que les
        # apts de coin atteignent tout de même un jardin usable (≥ ~24-32 m²).
        _DEPTH = {"T1": 7.0, "T2": 8.0, "T3": 8.0, "T4": 9.0, "T5": 9.0}
        # AIRE MAX de jardin privatif par typologie (défaut user 2026-07-08) : un jardin
        # devant une façade LARGE peut SPRAWLER (05 = 86 m²) et affamer le fond commun. On
        # PLAFONNE l'aire ; le résidu profond (loin de la façade) revient à l'ESPACE VERT
        # COMMUN. Appliqué APRÈS le partage de coin pour ne pas perturber l'équilibre 06/08.
        # Proportionné : T2 petit … T4/T5 généreux mais borné. Universel.
        _AREA_MAX = {"T1": 45.0, "T2": 42.0, "T3": 48.0, "T4": 65.0, "T5": 70.0}

        def _typo_of(_apt):
            _t = getattr(_apt, "typologie", None)
            return getattr(_t, "value", None) or "T3"

        # Façade de chaque apt : (apt, kind, fixed, lo, hi, inward_sign, depth).
        _facs = []
        for _apt, _seg in _void_apts:
            _kind, _cx, _cy, _lo, _hi = _seg
            _d = _DEPTH.get(_typo_of(_apt), 8.0)
            if _kind == "h":
                _flo, _fhi = max(_lo, vx0), min(_hi, vx1)
                _fixed, _sign = _cy, (-1 if _cy > _vcy else 1)
            else:
                _flo, _fhi = max(_lo, vy0), min(_hi, vy1)
                _fixed, _sign = _cx, (-1 if _cx > _vcx else 1)
            if _fhi - _flo < 1.0:
                continue
            _facs.append([_apt, _kind, _fixed, _flo, _fhi, _sign, _d])
        if not _facs:
            _ = parcelle
            return None

        # ── 1. RECTANGLE IDÉAL par apt : façade extrudée vers l'intérieur du void par
        #    sa profondeur-typo, clippé au void. C'est le jardin « rêvé » avant conflits.
        def _extr(_f):
            _apt, _kind, _fixed, _flo, _fhi, _sign, _d = _f
            if _kind == "h":
                _y0, _y1 = (_fixed, _fixed + _d) if _sign > 0 else (_fixed - _d, _fixed)
                return _boxJ(_flo, max(vy0, _y0), _fhi, min(vy1, _y1))
            _x0, _x1 = (_fixed, _fixed + _d) if _sign > 0 else (_fixed - _d, _fixed)
            return _boxJ(max(vx0, _x0), _flo, min(vx1, _x1), _fhi)
        _ideal = [_extr(_f) for _f in _facs]

        # ── 2. PARTAGE DU COIN RENTRANT. Deux façades PERPENDICULAIRES se disputent le
        #    carré du coin (ex. façade nord de 06 × façade est de 08). On coupe ce carré
        #    par une GUILLOTINE au milieu : chaque apt s'INTERDIT la moitié adjacente à la
        #    façade de l'AUTRE. Résultat : chacun garde un RECTANGLE compact devant SA
        #    façade (≥ _MIN_W), 0 forme en L/escalier. Universel (dérivé des seules façades).
        _forbid = [_boxJ(0, 0, 0, 0) for _ in _facs]
        for _a in range(len(_facs)):
            for _b in range(_a + 1, len(_facs)):
                if _facs[_a][1] == _facs[_b][1]:
                    continue  # façades parallèles : pas de coin partagé (traité par la grille)
                _ov = _ideal[_a].intersection(_ideal[_b])
                if _ov.area < 0.05:
                    continue
                _ob = _ov.bounds
                _hid = _a if _facs[_a][1] == "h" else _b       # apt façade horizontale
                _vid = _b if _hid == _a else _a                # apt façade verticale
                _vfx = _facs[_vid][2]                          # x de la façade verticale
                _xc = (_ob[0] + _ob[2]) / 2                    # coupe au milieu du coin
                if _vfx > _vcx:      # façade V à DROITE → V garde la droite, H la gauche
                    _f_v = _boxJ(_ob[0], _ob[1], _xc, _ob[3])  # interdit à V (moitié gauche)
                    _f_h = _boxJ(_xc, _ob[1], _ob[2], _ob[3])  # interdit à H (moitié droite)
                else:                # façade V à GAUCHE → V garde la gauche, H la droite
                    _f_v = _boxJ(_xc, _ob[1], _ob[2], _ob[3])
                    _f_h = _boxJ(_ob[0], _ob[1], _xc, _ob[3])
                if not _f_v.is_empty:
                    _forbid[_vid] = _forbid[_vid].union(_f_v)
                if not _f_h.is_empty:
                    _forbid[_hid] = _forbid[_hid].union(_f_h)

        # ── 3. GRILLE du void + masques d'interdiction (le coin réservé à l'autre apt).
        _STEP = 0.5
        _nx = max(1, int(round((vx1 - vx0) / _STEP)))
        _ny = max(1, int(round((vy1 - vy0) / _STEP)))
        _envb = _void_env.buffer(0.01)
        _free = _np.ones((_ny, _nx), dtype=bool)
        _fmask = [_np.zeros((_ny, _nx), dtype=bool) for _ in _facs]
        _fb = [_fo.buffer(-0.01) if (not _fo.is_empty and _fo.area > 0.05) else None
               for _fo in _forbid]
        for j in range(_ny):
            _py = vy0 + (j + 0.5) * _STEP
            for i in range(_nx):
                _px = vx0 + (i + 0.5) * _STEP
                if not _envb.contains(_PtJ(_px, _py)):
                    _free[j, i] = False
                    continue
                _pt = _PtJ(_px, _py)
                for _fi in range(len(_facs)):
                    if _fb[_fi] is not None and not _fb[_fi].is_empty and _fb[_fi].contains(_pt):
                        _fmask[_fi][j, i] = True

        # ── 4. Chaque apt EXTRAIT SON PLUS GRAND RECTANGLE devant sa façade, dans les
        #    cellules encore LIBRES et NON INTERDITES. On carve (retire du libre) au fur
        #    et à mesure → jardins DISJOINTS par construction. Ordre = façade la plus
        #    COURTE d'abord (apt de coin sert en premier, jamais starvé). Histogramme :
        #    pour chaque colonne de largeur, profondeur contiguë possédée ; plus grand
        #    rectangle largeur×profondeur avec les deux ≥ _MIN_W. Rectangle propre garanti.
        def _largest_rect(_fi):
            _apt, _kind, _fixed, _flo, _fhi, _sign, _d = _facs[_fi]
            _fm = _fmask[_fi]
            _maxdepth = int(round(_d / _STEP))
            if _kind == "h":
                _wlo = max(0, int(round((_flo - vx0) / _STEP)))
                _whi = min(_nx, int(round((_fhi - vx0) / _STEP)))
                _bj = int(round((_fixed - vy0) / _STEP)) + (0 if _sign > 0 else -1)

                def _cell(_w, _ds):
                    _j = _bj + _ds * _sign
                    return (0 <= _j < _ny and 0 <= _w < _nx
                            and _free[_j, _w] and not _fm[_j, _w])
            else:
                _wlo = max(0, int(round((_flo - vy0) / _STEP)))
                _whi = min(_ny, int(round((_fhi - vy0) / _STEP)))
                _bi = int(round((_fixed - vx0) / _STEP)) + (0 if _sign > 0 else -1)

                def _cell(_w, _ds):
                    _i = _bi + _ds * _sign
                    return (0 <= _w < _ny and 0 <= _i < _nx
                            and _free[_w, _i] and not _fm[_w, _i])
            _depth_at = []
            for _w in range(_wlo, _whi):
                _dd = 0
                while _dd < _maxdepth and _cell(_w, _dd):
                    _dd += 1
                _depth_at.append(_dd)
            _best_area, _best = 0.0, None
            for _s in range(len(_depth_at)):
                _mind = _depth_at[_s]
                for _e in range(_s, len(_depth_at)):
                    _mind = min(_mind, _depth_at[_e])
                    if _mind == 0:
                        break
                    _wc = _e - _s + 1
                    if (_wc * _STEP >= _MIN_W - 1e-6 and _mind * _STEP >= _MIN_W - 1e-6
                            and _wc * _mind > _best_area):
                        _best_area = _wc * _mind
                        _best = (_wlo + _s, _wlo + _e + 1, _mind)
            if _best is None:
                return None, None
            _ws, _we, _dd = _best
            if _kind == "h":
                _x0, _x1 = vx0 + _ws * _STEP, vx0 + _we * _STEP
                _y0, _y1 = ((_fixed, _fixed + _dd * _STEP) if _sign > 0
                            else (_fixed - _dd * _STEP, _fixed))
                _rows = [_bj + _k * _sign for _k in range(_dd)]
                _cols = list(range(_ws, _we))
            else:
                _y0, _y1 = vy0 + _ws * _STEP, vy0 + _we * _STEP
                _x0, _x1 = ((_fixed, _fixed + _dd * _STEP) if _sign > 0
                            else (_fixed - _dd * _STEP, _fixed))
                _cols = [_bi + _k * _sign for _k in range(_dd)]
                _rows = list(range(_ws, _we))
            return _boxJ(_x0, _y0, _x1, _y1), (_rows, _cols)

        # ── 5. Extrait le rectangle de CHAQUE apt (ordre : façade la plus courte
        #    d'abord), en carvant le libre → jardins disjoints.
        _rects = {}
        _order = sorted(range(len(_facs)), key=lambda _fi: _facs[_fi][4] - _facs[_fi][3])
        for _fi in _order:
            _r, _cells = _largest_rect(_fi)
            if _r is None or _r.is_empty or _r.area < 5.0:
                continue
            _rows, _cols = _cells
            for _j in _rows:
                for _i in _cols:
                    if 0 <= _j < _ny and 0 <= _i < _nx:
                        _free[_j, _i] = False
            _rects[_fi] = _boxJ(*_r.bounds)

        # ── 5b. PARTAGE ÉQUILIBRÉ DU COIN RENTRANT (max du min, défaut user 2026-07-08) ══
        #    Deux apts frontant deux arêtes PERPENDICULAIRES adjacentes (l'angle rentrant)
        #    se disputent le carré du coin. Le partage à la GRILLE ci-dessus donne à chacun
        #    un rectangle devant SA façade, mais l'apt à façade HORIZONTALE (ex. 06) est
        #    STRANGULÉ en LARGEUR par le rectangle-colonne de l'apt à façade VERTICALE
        #    (ex. 08), et réciproquement l'apt VERTICAL reste ÉTRIQUÉ (juste sa colonne).
        #    On RÉÉQUILIBRE : l'apt V, qui n'atteint que sa colonne de façade (largeur
        #    figée par _MIN_W), gagne une EXTENSION en L qui DESCEND sous le coin dans le
        #    void encore LIBRE devant/sous sa colonne — un vrai jardin usable, sans voler
        #    la largeur de l'apt H. L'extension est INSETÉE de la façade cour des autres
        #    apts (jamais elle ne fronte le voisin du dessous) et reste ORTHOGONALE (L ≤ 6
        #    sommets). On maximise le PLUS PETIT des deux jardins. Universel : dérivé des
        #    seules façades cour (détection de la paire perpendiculaire au coin partagé).
        import os as _os_rt
        # Flag de REVERT-TEST uniquement (JARDIN_REVERT_V15=1) : saute le partage équilibré
        # 5b + le plafond d'aire 5c pour reproduire l'état v15 (08 étranglé) et PROUVER que
        # le gate durci FIRE. En prod le flag est absent → comportement v16 (équilibré).
        _JARDIN_REVERT_V15 = _os_rt.environ.get("JARDIN_REVERT_V15") == "1"
        # arêtes de façade cour des AUTRES apts (pour ne jamais fronter un voisin).
        _other_vfacades = [(f[2], min(f[3], vy1), max(f[3], vy0), f[4]) for f in _facs
                           if f[1] == "v"]   # (x, ylo, yhi) des colonnes verticales
        for _vi, _vf in enumerate(_facs):
            if _JARDIN_REVERT_V15:
                break
            if _vf[1] != "v" or _vi not in _rects:
                continue
            _vx, _vlo, _vhi, _vsg = _vf[2], _vf[3], _vf[4], _vf[5]
            _rv = _rects[_vi]
            _b = _rv.bounds
            # l'apt V touche-t-il un coin partagé ? = un apt H a une façade adjacente
            # (à y == une extrémité de la colonne de V) qui borde le void juste au-dessus.
            _v_on_right = _vx > _vcx
            # côté « intérieur » du void devant la colonne V (là où on peut descendre).
            # profondeur de descente visée = profondeur-typo de V (jardin usable).
            _drop = _DEPTH.get(_typo_of(_vf[0]), 8.0)
            # la colonne actuelle de V occupe y[_b1,_b3] contre x=_vx. On DESCEND sous
            # _b1 (ou monte au-dessus _b3) dans le void libre, en insetant de _INSET_SIDE
            # de l'arête x=_vx pour ne pas fronter le voisin V du dessous.
            _INSET_SIDE = 0.2
            # rectangle d'extension : même x-span que la colonne, y de (_b1 - _drop) à _b1.
            _ext_y0 = max(vy0, _b[1] - _drop)
            if _ext_y0 >= _b[1] - 0.5:
                continue
            # x-span de l'extension = MÊME colonne que la façade de V (jamais élargie vers
            # l'apt H voisin, qui garde SA largeur). La descente passe SOUS la façade de V,
            # donc son bord x=_vx tomberait sur la façade cour du VOISIN V du dessous (ex. 10)
            # → on INSETTE ce bord de _INSET_SIDE pour que l'extension ne fronte QUE V. Le
            # jardin fusionné reste un L propre ; son enveloppe (bbox) garde ≥ _MIN_W de large
            # (le petit liseré inseté est INTERNE à la bbox, invisible au check largeur). On
            # ne récupère PAS de largeur côté H (pas de vol). Universel.
            _ext_x0, _ext_x1 = _b[0], _b[2]
            for _ovx, _oylo, _oyhi, _o4 in _other_vfacades:
                if abs(_ovx - _vx) > 0.05:
                    continue
                _ny0 = min(_oylo, _o4); _ny1 = max(_oylo, _o4)
                if _ny1 > _ext_y0 and _ny0 < _b[1]:
                    if _v_on_right:
                        _ext_x1 = min(_ext_x1, _vx - _INSET_SIDE)
                    else:
                        _ext_x0 = max(_ext_x0, _vx + _INSET_SIDE)
            if _ext_x1 - _ext_x0 < 1.0:
                continue
            _ext = _boxJ(_ext_x0, _ext_y0, _ext_x1, _b[1])
            # ne pas empiéter sur un jardin déjà attribué (carve contre les autres rects).
            for _oj, _orj in _rects.items():
                if _oj == _vi:
                    continue
                if _ext.intersects(_orj):
                    _ext = _ext.difference(_orj)
            if _ext.is_empty:
                continue
            if _ext.geom_type == "MultiPolygon":
                _ext = max(_ext.geoms, key=lambda g: g.area)
            # extension utile ≥ 8 m² (elle PROLONGE le jardin de V, ce n'est pas un jardin
            # autonome — sa largeur locale peut être < _MIN_W tant que la BBOX du L fusionné
            # reste ≥ _MIN_W, ce que le gate vérifie sur la bbox).
            if _ext.area < 8.0 - 1e-6:
                continue
            _merged = unary_union([_rv, _ext]).buffer(0.02).buffer(-0.02)
            if _merged.geom_type != "Polygon":
                continue
            _merged = _merged.simplify(0.05, preserve_topology=True)
            _mb = _merged.bounds
            # garde-fous : L propre (≤ 6 sommets) ET enveloppe ≥ _MIN_W de large partout
            # (tolérance 0,05 m pour absorber le retrait du close morphologique buffer±).
            if (len(_merged.exterior.coords) - 1 <= 6
                    and min(_mb[2] - _mb[0], _mb[3] - _mb[1]) >= _MIN_W - 0.05):
                # INSET du bord PERPENDICULAIRE partagé : le sommet du L (y-haut) longe la
                # façade HORIZONTALE de l'apt H voisin (ex. la façade sud de 06 à y=notch_y1).
                # On RECULE ce bord de _INSET_SIDE pour que le L ne fronte QUE la façade de V.
                _hi_edge = _mb[3]
                for _hf in _facs:
                    if _hf[1] != "h":
                        continue
                    _hy2 = _hf[2]
                    if abs(_hi_edge - _hy2) < 0.15 and min(_mb[2], _hf[4]) - max(_mb[0], _hf[3]) > 0.5:
                        _merged = _merged.intersection(
                            _boxJ(_mb[0], _mb[1], _mb[2], _hy2 - _INSET_SIDE))
                        break
                if _merged.geom_type == "MultiPolygon":
                    _merged = max(_merged.geoms, key=lambda g: g.area)
                _merged = _merged.simplify(0.05, preserve_topology=True)
                if _merged.geom_type != "Polygon" or len(_merged.exterior.coords) - 1 > 6:
                    continue
                _rects[_vi] = _merged
                # marque les cellules de grille de l'extension comme prises.
                _eb = _ext.bounds
                for _j in range(_ny):
                    _py = vy0 + (_j + 0.5) * _STEP
                    if not (_eb[1] <= _py <= _eb[3]):
                        continue
                    for _i in range(_nx):
                        _px = vx0 + (_i + 0.5) * _STEP
                        if _eb[0] <= _px <= _eb[2] and 0 <= _j < _ny and 0 <= _i < _nx:
                            _free[_j, _i] = False

        # ── 5c. PLAFOND D'AIRE par typologie : on ROGNE la profondeur (bord le plus loin
        #    de la façade cour de l'apt) pour ramener l'aire sous _AREA_MAX. Le résidu
        #    profond deviendra ESPACE VERT COMMUN (étape 4/8). On ne rogne QUE les jardins
        #    RECTANGLES (les L de coin sont déjà petits, sous cap). La façade cour de l'apt
        #    est fixe (kind/fixed) → on recule le bord OPPOSÉ. Universel.
        for _fi, _r in ([] if _JARDIN_REVERT_V15 else list(_rects.items())):
            if _r.geom_type != "Polygon" or len(_r.exterior.coords) - 1 != 4:
                continue
            _cap = _AREA_MAX.get(_typo_of(_facs[_fi][0]), 60.0)
            if _r.area <= _cap + 1e-6:
                continue
            _kind, _fixed = _facs[_fi][1], _facs[_fi][2]
            _sign = _facs[_fi][5]
            _bb = list(_r.bounds)  # x0,y0,x1,y1
            if _kind == "h":
                _w = _bb[2] - _bb[0]
                _new_depth = max(_MIN_W, _cap / _w) if _w > 0 else 0
                if _sign > 0:   # façade en bas → rogne le haut
                    _bb[3] = min(_bb[3], _fixed + _new_depth)
                else:           # façade en haut → rogne le bas
                    _bb[1] = max(_bb[1], _fixed - _new_depth)
            else:
                _h = _bb[3] - _bb[1]
                _new_depth = max(_MIN_W, _cap / _h) if _h > 0 else 0
                if _sign > 0:   # façade à gauche → rogne la droite
                    _bb[2] = min(_bb[2], _fixed + _new_depth)
                else:           # façade à droite → rogne la gauche
                    _bb[0] = max(_bb[0], _fixed - _new_depth)
            if _bb[2] - _bb[0] >= _MIN_W - 1e-6 and _bb[3] - _bb[1] >= _MIN_W - 1e-6:
                _rects[_fi] = _boxJ(*_bb)

        # ── 6. INSET des arêtes qui longent la façade cour d'un AUTRE apt. Au coin
        #    rentrant, l'arête d'un jardin (ex. le haut du jardin de 08) peut coïncider
        #    avec la façade cour d'un autre apt (ex. la façade sud de 06) → ce voisin
        #    verrait le jardin d'autrui sous ses fenêtres, et H-JARDIN-EXCLUSIF le
        #    signalerait. On RECULE cette arête de _INSET pour dégager un mince liseré
        #    (versé au commun). Le jardin reste un RECTANGLE, ne fronte plus QUE sa
        #    propre façade. Universel (dérivé des façades cour des autres apts).
        # NB : ne s'applique qu'aux jardins RECTANGLES (4 sommets) ; les L issus du
        # partage de coin (5b) sont déjà insetés et gardés tels quels.
        _INSET = 0.6
        # segments de façade cour de chaque apt (kind, fixed, lo, hi).
        _facade_lines = [(f[1], f[2], f[3], f[4]) for f in _facs]
        for _fi, _r in list(_rects.items()):
            # jardins NON rectangulaires (L du partage de coin 5b, déjà insetés) : on
            # ne les rectangularise PAS via bbox (cela les regonflerait et re-frontrait
            # le voisin). Ils sont laissés tels quels.
            if _r.geom_type != "Polygon" or len(_r.exterior.coords) - 1 != 4:
                continue
            _b = list(_r.bounds)  # [x0,y0,x1,y1]
            for _fj, (_ok, _of, _olo, _ohi) in enumerate(_facade_lines):
                if _fj == _fi:
                    continue
                if _ok == "h":   # façade horizontale d'un autre apt à y=_of
                    for _ei, _ey in ((1, _b[1]), (3, _b[3])):   # bas / haut du rect
                        if abs(_ey - _of) < 0.05 and min(_b[2], _ohi) - max(_b[0], _olo) > 0.5:
                            if _ei == 1:
                                _b[1] = min(_b[1] + _INSET, _b[3] - 0.5)
                            else:
                                _b[3] = max(_b[3] - _INSET, _b[1] + 0.5)
                else:            # façade verticale d'un autre apt à x=_of
                    for _ei, _ex in ((0, _b[0]), (2, _b[2])):
                        if abs(_ex - _of) < 0.05 and min(_b[3], _ohi) - max(_b[1], _olo) > 0.5:
                            if _ei == 0:
                                _b[0] = min(_b[0] + _INSET, _b[2] - 0.5)
                            else:
                                _b[2] = max(_b[2] - _INSET, _b[0] + 0.5)
            _rects[_fi] = _boxJ(*_b)

        # ── 7. Écrit chaque jardin privatif (rectangle compact) sur SON apt.
        _priv = []
        for _fi, _r in _rects.items():
            if _r.is_empty or _r.area < 5.0:
                continue
            _facs[_fi][0].jardin_polygon_xy = [(round(float(x), 2), round(float(y), 2))
                                               for x, y in list(_r.exterior.coords)[:-1]]
            _priv.append(_r)

        # ── 4. ESPACE VERT COMMUN = résidu du void non couvert par les privatifs.
        #    On garde la composante principale si elle est significative (≥ 8 m²) et
        #    au moins _MIN_W de large quelque part (sinon c'est une bande morte → on
        #    l'ignore, la cour est alors entièrement privatisée).
        _jardin_commun = None
        if _priv:
            _resid = _void_env.difference(unary_union(_priv))
            if not _resid.is_empty:
                if _resid.geom_type == "MultiPolygon":
                    _resid = max(_resid.geoms, key=lambda g: g.area)
                if _resid.geom_type == "Polygon" and _resid.area >= 8.0:
                    _rb = _resid.bounds
                    if (_rb[2] - _rb[0]) >= _MIN_W - 0.5 and (_rb[3] - _rb[1]) >= _MIN_W - 0.5:
                        _jardin_commun = _resid
        _ = parcelle
        return _jardin_commun


    # ── fallback legacy (aucun apt ne borde le void) : tuilage historique ────────
    # Identify RDC logement apts adjacent to the notch. An apt is
    # "adjacent" if one of its axis-aligned walls coincides with one of
    # the notch's edges (within 0.3 m tolerance).
    TOL = 0.3

    def _apt_bbox(apt):
        xs = [p[0] for p in apt.polygon_xy]
        ys = [p[1] for p in apt.polygon_xy]
        return min(xs), min(ys), max(xs), max(ys)

    # Which notch edge does this apt's wall sit on?
    # Returns one of "north" (y=notch_y1), "south" (y=notch_y0),
    # "west" (x=notch_x0), "east" (x=notch_x1), or None.
    def _notch_edge_for(apt) -> str | None:
        axmin, aymin, axmax, aymax = _apt_bbox(apt)
        # Apt is adjacent to notch's SOUTH edge if its NORTH wall is at
        # y=notch_y0 AND its x-range overlaps the notch x-range.
        if abs(aymax - notch_y0) < TOL and axmax > notch_x0 + TOL and axmin < notch_x1 - TOL:
            return "south"
        if abs(aymin - notch_y1) < TOL and axmax > notch_x0 + TOL and axmin < notch_x1 - TOL:
            return "north"
        if abs(axmax - notch_x0) < TOL and aymax > notch_y0 + TOL and aymin < notch_y1 - TOL:
            return "west"
        if abs(axmin - notch_x1) < TOL and aymax > notch_y0 + TOL and aymin < notch_y1 - TOL:
            return "east"
        return None

    # Per-edge list of adjacent apts
    edge_apts: dict[str, list] = {"north": [], "south": [], "west": [], "east": []}
    for apt in cells:
        if apt.type != CelluleType.LOGEMENT or not apt.polygon_xy:
            continue
        edge = _notch_edge_for(apt)
        if edge is not None:
            edge_apts[edge].append(apt)

    # Find the BEST (south-apt, east-apt) pair where the two apts'
    # walls define a clean rectangular sub-zone of the notch. Pick the
    # south-edge apt with the smallest y-gap to the notch and the
    # east-edge apt with the smallest y (closest to the south apt) so
    # the tiled zone sits in the notch's corner nearest to both walls.
    south_apts = sorted(
        edge_apts["south"], key=lambda a: _apt_bbox(a)[0],  # by min x
    )
    east_apts = sorted(
        edge_apts["east"], key=lambda a: _apt_bbox(a)[1],  # by min y
    )
    west_apts = sorted(
        edge_apts["west"], key=lambda a: _apt_bbox(a)[1],
    )

    def _tile_corner(
        corner_apt, side_apt, *, side_is_east: bool,
    ) -> None:
        """Tile the rectangle defined by side_apt's wall and
        corner_apt's wall on the OPPOSITE notch corner.

        If side_is_east: side_apt's west wall is at notch_x1 (right
        edge of notch). corner_apt's north wall is at notch_y0
        (bottom edge). The tiled rectangle spans:
           x = [max(notch_x0, side_apt.xmin_overlap_ancrage), notch_x1]
           y = [notch_y0, min(notch_y1, side_apt.ymax)]
        But constrained to the OVERLAP between the two apts' wall
        extents so the cut yields two square-ish halves.
        """
        cbx0, cby0, cbx1, cby1 = _apt_bbox(corner_apt)
        sbx0, sby0, sbx1, sby1 = _apt_bbox(side_apt)
        if side_is_east:
            # Side apt's west wall at x=notch_x1.
            # Side apt occupies y-range [sby0, sby1] along the notch edge.
            zone_y0 = notch_y0
            zone_y1 = min(notch_y1, sby1)
            # Corner apt's north wall at y=notch_y0.
            # Corner apt occupies x-range [cbx0, cbx1].
            zone_x0 = max(notch_x0, cbx0)
            zone_x1 = notch_x1
        else:
            # West side apt's east wall at x=notch_x0.
            zone_y0 = notch_y0
            zone_y1 = min(notch_y1, sby1)
            zone_x0 = notch_x0
            zone_x1 = min(notch_x1, cbx1)
        # Clip to the zone intersection: the sub-zone's max y must also
        # be ≤ the corner apt's north-wall clearance; make it square-ish.
        zone_y1 = min(zone_y1, zone_y0 + (zone_x1 - zone_x0) * 1.1)
        if zone_x1 - zone_x0 < 2.0 or zone_y1 - zone_y0 < 2.0:
            return
        # Vertical cut at the zone's x-midpoint.
        cut_x = (zone_x0 + zone_x1) / 2
        if side_is_east:
            # east-wall apt owns east half (adjacent to its wall)
            side_apt.jardin_polygon_xy = [
                (cut_x, zone_y0), (zone_x1, zone_y0),
                (zone_x1, zone_y1), (cut_x, zone_y1),
            ]
            # corner (south-wall) apt owns west half
            corner_apt.jardin_polygon_xy = [
                (zone_x0, zone_y0), (cut_x, zone_y0),
                (cut_x, zone_y1), (zone_x0, zone_y1),
            ]
        else:
            side_apt.jardin_polygon_xy = [
                (zone_x0, zone_y0), (cut_x, zone_y0),
                (cut_x, zone_y1), (zone_x0, zone_y1),
            ]
            corner_apt.jardin_polygon_xy = [
                (cut_x, zone_y0), (zone_x1, zone_y0),
                (zone_x1, zone_y1), (cut_x, zone_y1),
            ]

    # East-side corner: the south-wall apt whose x-range overlaps the
    # notch AND the east-wall apt closest to the notch's south edge.
    if south_apts and east_apts:
        # Pick the south-wall apt whose x-range lies on the west side
        # of the notch (closest to notch_x0). We want the PAIR whose
        # walls form the NW corner of the notch.
        best_south = south_apts[0]  # smallest xmin → leftmost
        best_east = east_apts[0]    # smallest ymin → closest to notch south
        _tile_corner(best_south, best_east, side_is_east=True)
    elif south_apts and west_apts:
        best_south = south_apts[-1]  # rightmost
        best_west = west_apts[0]
        _tile_corner(best_south, best_west, side_is_east=False)

    # Remaining edge-apts (not yet tiled in the corner pair) get their OWN
    # slice of the rest of the notch, mais BORNÉE en profondeur (≤ NOTCH_BAND_M
    # depuis leur mur) pour ne pas s'accaparer tout le void : le reste doit
    # rester disponible pour les apts bordant les AUTRES arêtes du notch (ex.
    # nw_bar dont le mur sud borde le haut du void). Sans ce cap, les 2 apts de
    # la 1re arête mangeaient tout le jardin.
    side_apts = (east_apts if east_apts else west_apts)
    NOTCH_BAND_M = 5.0
    for apt in side_apts:
        if apt.jardin_polygon_xy is not None:
            continue  # already tiled in corner pair
        ay0 = max(notch_y0, _apt_bbox(apt)[1])
        ay1 = min(notch_y1, _apt_bbox(apt)[3])
        if ay1 - ay0 < 2.0:
            continue
        # bande adjacente au mur de l'apt (east_apts → mur à notch_x1, la bande
        # part vers l'ouest ; west_apts → mur à notch_x0, bande vers l'est).
        if east_apts:
            jx0 = max(notch_x0, notch_x1 - NOTCH_BAND_M)
            jx1 = notch_x1
        else:
            jx0 = notch_x0
            jx1 = min(notch_x1, notch_x0 + NOTCH_BAND_M)
        apt.jardin_polygon_xy = [
            (jx0, ay0), (jx1, ay0), (jx1, ay1), (jx0, ay1),
        ]

    # ── D2 : CHAQUE logement RDC doit avoir un jardin (SPEC_PLAN D2). ──
    # Le tuilage du notch ci-dessus ne sert QUE les ~2 apts bordant l'angle
    # rentrant. Ici on généralise : tout apt RDC encore sans jardin reçoit une
    # BANDE de jardin le long de SA façade jour (bord donnant sur le void/jardin
    # OU sur la rue = voirie), extrudée vers l'extérieur, bornée à la parcelle,
    # sans recouvrir le footprint ni les autres jardins/apts. Universel (toute
    # orientation, tout L).
    voi = {v for v in (voirie_orientations or ())}
    fminx2, fminy2, fmaxx2, fmaxy2 = footprint.bounds
    bbox = ShapelyPoly([
        (fminx2, fminy2), (fmaxx2, fminy2), (fmaxx2, fmaxy2), (fminx2, fmaxy2),
    ])
    void_zone = bbox.difference(footprint).buffer(0)  # angle rentrant (jardin)
    # Enveloppe où poser les jardins = parcelle si dispo, sinon bbox élargie.
    if parcelle is not None and not parcelle.is_empty:
        garden_env = parcelle.buffer(0)
    else:
        garden_env = bbox.buffer(6.0)
    footprint_buf = footprint.buffer(-0.05)
    # Aire déjà prise par des jardins (tuilage notch) — on n'empiète pas dessus.
    taken = []
    for apt in cells:
        j = getattr(apt, "jardin_polygon_xy", None)
        if j and len(j) >= 3:
            try:
                taken.append(ShapelyPoly(j))
            except Exception:
                pass

    def _daylight_edges(apt):
        """Retourne [(side, band_polygon)] : côtés de l'apt donnant sur le void
        (jardin) ou sur une voirie (rue), avec la bande extrudée vers l'ext."""
        ax0, ay0, ax1, ay1 = _apt_bbox(apt)
        DEPTH = 4.5  # profondeur de la bande jardin
        cand = []
        # side, edge-probe-outside, extruded band
        specs = [
            ("sud",  ShapelyPoly([(ax0, ay0 - DEPTH), (ax1, ay0 - DEPTH), (ax1, ay0), (ax0, ay0)]), (( (ax0+ax1)/2, ay0 - 0.4))),
            ("nord", ShapelyPoly([(ax0, ay1), (ax1, ay1), (ax1, ay1 + DEPTH), (ax0, ay1 + DEPTH)]), (( (ax0+ax1)/2, ay1 + 0.4))),
            ("ouest",ShapelyPoly([(ax0 - DEPTH, ay0), (ax0, ay0), (ax0, ay1), (ax0 - DEPTH, ay1)]), ((ax0 - 0.4, (ay0+ay1)/2))),
            ("est",  ShapelyPoly([(ax1, ay0), (ax1 + DEPTH, ay0), (ax1 + DEPTH, ay1), (ax1, ay1)]), ((ax1 + 0.4, (ay0+ay1)/2))),
        ]
        for side, band, probe in specs:
            px, py = probe
            from shapely.geometry import Point as _P
            outside_fp = not footprint_buf.contains(_P(px, py))
            if not outside_fp:
                continue
            faces_void = void_zone.contains(_P(px, py)) or void_zone.distance(_P(px, py)) < 0.3
            faces_street = (side in voi) and not void_only
            if not (faces_void or faces_street):
                continue  # mitoyen / intérieur / (rue si void_only) → pas de jardin ici
            cand.append((side, band, faces_void))
        return cand

    for apt in cells:
        if apt.type != CelluleType.LOGEMENT or not apt.polygon_xy:
            continue
        if getattr(apt, "jardin_polygon_xy", None):
            continue
        edges = _daylight_edges(apt)
        # priorité au void (vrai jardin cœur d'îlot) puis à la rue.
        edges.sort(key=lambda e: (0 if e[2] else 1))
        best = None
        for _side, band, _fv in edges:
            g = band.intersection(garden_env).difference(footprint)
            for t in taken:
                g = g.difference(t)
            if g.is_empty:
                continue
            if g.geom_type == "MultiPolygon":
                g = max(g.geoms, key=lambda p: p.area)
            if g.area < 4.0:
                continue
            # rectangularise (bbox du morceau) puis re-clip pour rester propre.
            gx0, gy0, gx1, gy1 = g.bounds
            rect = ShapelyPoly([(gx0, gy0), (gx1, gy0), (gx1, gy1), (gx0, gy1)])
            rect = rect.intersection(garden_env).difference(footprint)
            for t in taken:
                rect = rect.difference(t)
            if rect.geom_type == "MultiPolygon":
                rect = max(rect.geoms, key=lambda p: p.area)
            if rect.is_empty or rect.area < 4.0:
                continue
            best = rect
            break
        if best is None:
            continue
        coords = list(best.exterior.coords)[:-1]
        apt.jardin_polygon_xy = [(float(x), float(y)) for x, y in coords]
        taken.append(best)

    _ = parcelle


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
            voirie_orientations=tuple(inputs.voirie_orientations or (voirie,)),
            corridor_width=_CORRIDOR_WIDTH_M,   # 1,40 m — cohérent couloir/slots (0 seam)
        )
    except Exception:
        _l_preview = None
    l_core_polygon = None
    if _l_preview is not None and _l_preview.core is not None:
        l_core_polygon = _l_preview.core
        # ── CAGE INTÉGRÉE AU BÂTI (2026-07-08) : le dispatcher L place désormais la
        # cage dans un COIN BÂTI de l'anneau de la cour (2 faces sur murs d'apt, 2
        # faces intérieures sur cour + couloir) — cf. _place_core_in_landlocked_slot.
        # On NE la GLISSE PLUS vers le spine du couloir : l'ancien « plaqué spine »
        # (2026-07-06) la re-poussait au bord du couloir → cage FLOTTANTE, entourée
        # de gris, sans contact ni cour ni apt (défaut mesuré : 0,44 m² cour, 0 apt).
        # La position du dispatcher est CONSERVÉE telle quelle (intégrée). Universel.
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
    # Polygone de la cage APRÈS recollage au coin cour∩apt (cf.
    # _snap_cage_to_courtyard_corner). Sert à aligner ``core`` (schéma + rendu)
    # sur la cage intégrée, pas sur sa position brute au centre du couloir.
    _snapped_cage_poly = None

    # Build a parcelle shape once for downstream jardin-depth ranking.
    # Falls back to None if the input geojson is malformed; the layout
    # generator already handles a missing parcelle by using a generous
    # buffer around the footprint as proxy.
    parcelle_shape = None
    try:
        parcelle_shape = shape(inputs.parcelle_geojson) if inputs.parcelle_geojson else None
    except Exception:
        parcelle_shape = None

    # Topologie du footprint, calculée une fois (indépendante de l'étage).
    # Sert à décider si les slots viennent d'un dispatcher FAISANT AUTORITÉ
    # (L / U) : dans ce cas la typologie CIBLE du slot prime sur l'heuristique
    # legacy de re-classement par nombre de chambres.
    try:
        from core.building_model.layout_dispatcher import (
            classify_footprint_topology as _classify_topo,
        )
        _topo = _classify_topo(footprint)
    except Exception:
        _topo = None
    _dispatcher_topo = _topo in ("L", "U")

    for idx in range(inputs.niveaux_recommandes):
        # Per-floor mix: ground floors favour smaller typos, top floors
        # skew larger. Each floor thus shows a distinct typology mix while
        # the building as a whole respects the brief's target ratios.
        floor_mix = _mix_for_floor(base_mix, idx, inputs.niveaux_recommandes)
        slots_per_floor = compute_apartment_slots(
            grid, core, mix_typologique=floor_mix, voirie_side=voirie,
            voirie_orientations=tuple(inputs.voirie_orientations or (voirie,)),
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
            _pre_corridors = _emit_wing_corridors(idx, core, footprint, [], tuple(inputs.voirie_orientations or (voirie,)))
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
                # The FAÇADE is the side OPPOSITE the palier, and that is where
                # every living room gets its window. So never pick a palier
                # whose opposite side is a MITOYEN (bbox-perimeter side that is
                # not a voirie) — that would face all living rooms onto a blind
                # party wall. Prefer paliers whose façade lands on rue/cour.
                _OPP = {"sud": "nord", "nord": "sud", "ouest": "est", "est": "ouest"}
                _voi = set(inputs.voirie_orientations or (voirie,))
                _fxmin, _fymin, _fxmax, _fymax = footprint.bounds

                def _facade_is_mitoyen(s):
                    d = _OPP[s]
                    b = slot.polygon.bounds
                    on_perim = {
                        "ouest": abs(b[0] - _fxmin) < 0.6, "est": abs(b[2] - _fxmax) < 0.6,
                        "sud": abs(b[1] - _fymin) < 0.6, "nord": abs(b[3] - _fymax) < 0.6,
                    }
                    return on_perim.get(d, False) and d not in _voi

                # Best paliers: those whose FAÇADE (opposite side) is an actual
                # EXTERIOR orientation (rue/cour) AND not mitoyen. This forces
                # e.g. a bar apt (orientation ['sud']) to take palier=nord →
                # façade=sud (rue), instead of an interior side between apts.
                _good = [s for s in interior_sides
                         if _OPP[s] in exterior and not _facade_is_mitoyen(s)]
                _ok = [s for s in interior_sides if not _facade_is_mitoyen(s)]
                candidate_sides = _good or _ok or interior_sides
                # Prefer closest to the CORE specifically — that's where
                # the stairs + palier are; a wing corridor far from core
                # isn't a real palier.
                core_poly = _corridor_shapes[0]  # by construction core is first
                best = min(
                    candidate_sides,
                    key=lambda s: side_pts[s].distance(core_poly),
                )
                if side_pts[best].distance(core_poly) > 3.0:
                    # Core is far — fall back to closest corridor overall
                    best = min(
                        candidate_sides,
                        key=lambda s: min(side_pts[s].distance(p) for p in _corridor_shapes),
                    )
                return best

            def _rectify_corner(poly):
                """A CONCAVE inner-corner slot (L-shape where a wing meets the
                bar around the cour) confuses the layout: the séjour lands on
                the interior leg instead of the street façade → windowless. Snap
                such slots (fill ratio < 0.85) to the LARGER of the two axis-
                aligned rectangles that keep a full façade (full-width×reduced-
                height OR reduced-width×full-height), so the layout designs on a
                clean rectangle with its living rooms on the exterior wall."""
                from shapely.geometry import box as _box
                mnx, mny, mxx, mxy = poly.bounds
                ba = (mxx - mnx) * (mxy - mny)
                if ba <= 0 or poly.area / ba >= 0.85:
                    return poly
                buf = poly.buffer(0.05)
                best = None
                for side in ("bottom", "top", "left", "right"):
                    span = (mxy - mny) if side in ("bottom", "top") else (mxx - mnx)
                    s = 0.0
                    while s < span:
                        if side == "bottom":
                            c = _box(mnx, mny + s, mxx, mxy)
                        elif side == "top":
                            c = _box(mnx, mny, mxx, mxy - s)
                        elif side == "left":
                            c = _box(mnx + s, mny, mxx, mxy)
                        else:
                            c = _box(mnx, mny, mxx - s, mxy)
                        if buf.contains(c):
                            if best is None or c.area > best.area:
                                best = c
                            break
                        s += 0.25
                return best if (best is not None and best.area >= 30.0) else poly

            for slot in slots_per_floor:
                # Drop landlocked slots (no exterior façade) — real-estate
                # logic: an apt without any exterior wall can't have windows
                # and is not a legitimate logement.
                if not slot.orientations:
                    continue
                # Rectify ONLY the layout footprint (so living rooms land on the
                # street façade, lit) but remember the FULL slot: the L-leg that
                # the rectangle drops is reclaimed into the séjour afterwards so
                # no floor area is wasted (the corner apt just gets a bigger
                # living room).
                slot._orig_poly = slot.polygon  # type: ignore[attr-defined]
                slot.polygon = _rectify_corner(slot.polygon)
                sel = await selector.select_for_slot(slot)
                # Un slot qui vient d'un dispatcher topologique faisant autorité
                # (layout_l / layout_u) ne doit JAMAIS être jeté silencieusement.
                # Le sélecteur peut renvoyer None parce que la géométrie du slot
                # (ex. aile mono-façade single-loaded ~5,7 m de profond) tombe
                # hors des plages dimensionnelles des templates seedés — pas
                # parce que le logement est infaisable. On retombe alors sur un
                # template de secours (même typo ou voisine) et on force le
                # générateur de layout à dessiner l'appartement dans la
                # géométrie exacte du slot. Sans ce fallback, l'aile entière est
                # dropée puis re-fusionnée par le pocket-fill en une cellule
                # géante (le T5 de 375 m² observé sur le U).
                _bypass_dim = False
                if sel is None:
                    sel = await selector.select_fallback_for_slot(slot)
                    if sel is None:
                        continue  # aucune typo n'a de template en base
                    _bypass_dim = True
                # Attach the corridor-facing side so generate_apartment
                # orients the layout (entree on palier side).
                slot.palier_side_hint = _palier_side_for(slot)  # type: ignore[attr-defined]
                # Neighbour apt polygons already placed on this floor — the
                # layout generator uses them to discount jardin extrusions
                # that would intrude into another apt's territory.
                _neighbour_polys = [
                    _ShapelyPoly(c.polygon_xy)
                    for c in cells_for_niveau
                    if len(c.polygon_xy) >= 3
                ]
                fit = adapter.fit_to_slot(
                    sel.template, slot, footprint=footprint,
                    parcelle=parcelle_shape,
                    other_cells_polys=_neighbour_polys,
                    voiries=tuple(inputs.voirie_orientations or (voirie,)),
                    bypass_dim_check=_bypass_dim,
                )
                if fit.success and fit.apartment is not None:
                    # Label the apartment by its ACTUAL number of bedrooms
                    # (T2=1, T3=2, T4=3, T5=4) — the room layout is the truth,
                    # not the slot surface. A 73 m² 2-bedroom is a big T3, not a
                    # T4; labelling by surface produced "T4 with 2 bedrooms".
                    _nb_ch = sum(1 for _r in (fit.apartment.rooms or [])
                                 if _r.type in (RoomType.CHAMBRE_PARENTS,
                                                RoomType.CHAMBRE_ENFANT,
                                                RoomType.CHAMBRE_SUPP))
                    _BY_CH = {1: Typologie.T2, 2: Typologie.T3, 3: Typologie.T4, 4: Typologie.T5}
                    from core.building_model.solver import (
                        _reclassify_by_surface, _TYPO_SURFACE_RANGE,
                    )
                    if _nb_ch in _BY_CH:
                        fit.apartment.typologie = _BY_CH[_nb_ch]
                    else:
                        fit.apartment.typologie = _reclassify_by_surface(
                            fit.apartment.surface_m2, fit.apartment.typologie or slot.target_typologie,
                        )
                    # DÉFAUT MIX : quand les slots viennent d'un dispatcher
                    # FAISANT AUTORITÉ (L / U), sa typologie CIBLE prime sur le
                    # re-classement par nombre de chambres. Le générateur de
                    # layout perd parfois une chambre sur une largeur knife-edge
                    # (une aile T3 de 7,8 m ne case qu'1 chambre → serait
                    # dégradée en T2), ce qui écrasait TOUT le mix en T2 (zéro
                    # T3). On restaure la typo cible du dispatcher DÈS LORS que
                    # la surface réelle est cohérente avec elle (garde-fou : on
                    # ne rebaptise pas un 45 m² en T3). Le dispatcher a
                    # dimensionné l'aile pour cette typo : on lui fait confiance.
                    if _dispatcher_topo:
                        _tgt = slot.target_typologie
                        _rng = _TYPO_SURFACE_RANGE.get(_tgt)
                        _surf = fit.apartment.surface_m2 or 0.0
                        # Tolérance basse de 2 m² : un slot T3 de 53,5 m² est
                        # pile dans [52,65) ; on accepte aussi le bord bas.
                        if _rng is not None and (_rng[0] - 2.0) <= _surf < _rng[1]:
                            fit.apartment.typologie = _tgt
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
        # CAGE #1 (esc + ASC + palier PMR ABSORBÉ dans son emprise). Ce bloc est
        # la cage d'escalier principale : le palier d'arrivée est INCLUS dans son
        # polygone, ce n'est PAS une cellule « palier » autonome. Nommé "cage_"
        # (2026-07-06, demande user) pour que le rendu dessine esc+ASC dedans au
        # lieu d'un gros rectangle gris « palier » vide. Le gate --l refuse toute
        # circulation « palier » hors cage.
        circulations = [
            Circulation(
                id=f"cage_R{idx}_1",
                polygon_xy=list(core.polygon.exterior.coords)[:-1],
                surface_m2=core.polygon.area,
                largeur_min_cm=140,
            ),
        ]
        # Circulation faisant autorité : pour un footprint en U, le couloir ⊓
        # du dispatcher dessert TOUT l'étage (3 ailes + 2 cages fusionnées) et
        # colle exactement à la tuile des slots. On l'utilise tel quel au lieu
        # des couloirs legacy aile-par-aile de ``_emit_wing_corridors`` : ceux-ci
        # ne collaient pas à la tuile du dispatcher et laissaient un vide de
        # ~58 m² le long de l'aile droite, ré-absorbé ensuite en un logement
        # obèse (le T2 de 102 m² observé). Le L garde son chemin historique
        # (``_emit_wing_corridors`` émet déjà le couloir_L_ unique attendu par
        # test_l_layout_endtoend).
        _disp_corridor = (
            _l_preview.corridor
            if (_l_preview is not None and _topo == "U")
            else None
        )
        if _disp_corridor is not None and not _disp_corridor.is_empty:
            # Le couloir du dispatcher peut être un multipolygone (⊓) : on émet
            # une Circulation par composante pour que les 2 cages du U restent
            # visibles (elles sont fusionnées dans ce couloir par choix de
            # layout_u).
            _parts = (
                list(_disp_corridor.geoms)
                if _disp_corridor.geom_type == "MultiPolygon"
                else [_disp_corridor]
            )
            for _ci, _part in enumerate(_parts):
                if _part.is_empty or _part.area < 1.0:
                    continue
                # Retire l'emprise du core pour ne pas doubler le palier.
                _p = _part.difference(core.polygon).buffer(0)
                if _p.is_empty:
                    _p = _part
                if _p.geom_type == "MultiPolygon":
                    for _pj, _sub in enumerate(_p.geoms):
                        if _sub.is_empty or _sub.area < 1.0:
                            continue
                        circulations.append(Circulation(
                            id=f"couloir_disp_{_ci}_{_pj}_R{idx}",
                            polygon_xy=list(_sub.exterior.coords)[:-1],
                            surface_m2=_sub.area, largeur_min_cm=120,
                        ))
                else:
                    circulations.append(Circulation(
                        id=f"couloir_disp_{_ci}_R{idx}",
                        polygon_xy=list(_p.exterior.coords)[:-1],
                        surface_m2=_p.area, largeur_min_cm=120,
                    ))
            # 2e CAGE (esc + asc) : le U a 2 cages aux 2 angles intérieurs. La
            # principale est le ``core`` (palier). La 2e, fusionnée dans le
            # couloir, est ré-émise ici comme Circulation DISTINCTE identifiable
            # "cage" pour être visible au plan et compter comme égress #2.
            for _si, _cage in enumerate(getattr(_l_preview, "secondary_cores", ()) or ()):
                if _cage is None or _cage.is_empty or _cage.area < 1.0:
                    continue
                _cg = _cage if _cage.geom_type == "Polygon" else max(
                    _cage.geoms, key=lambda g: g.area)
                circulations.append(Circulation(
                    id=f"cage_R{idx}_{_si + 2}",  # cage #2, #3, …
                    polygon_xy=list(_cg.exterior.coords)[:-1],
                    surface_m2=_cg.area, largeur_min_cm=140,
                ))
        else:
            circulations.extend(_emit_wing_corridors(idx, core, footprint, cells_for_niveau, tuple(inputs.voirie_orientations or (voirie,))))
            # 2e CAGE pour le L (SPEC_PLAN A2) : le dispatcher L expose une cage
            # secondaire au bout d'aile ; on l'émet comme Circulation "cage_"
            # DISTINCTE (égress #2) sur tous les niveaux. Universel (n'émet rien
            # si le layout n'a pas produit de cage secondaire, ex. rect).
            if _topo == "L":
                for _si, _cage in enumerate(
                    getattr(_l_preview, "secondary_cores", ()) or ()
                ):
                    if _cage is None or _cage.is_empty or _cage.area < 1.0:
                        continue
                    _cg = _cage if _cage.geom_type == "Polygon" else max(
                        _cage.geoms, key=lambda g: g.area)
                    circulations.append(Circulation(
                        id=f"cage_R{idx}_{_si + 2}",
                        polygon_xy=list(_cg.exterior.coords)[:-1],
                        surface_m2=_cg.area, largeur_min_cm=140,
                    ))

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
                parcelle=parcelle_shape,
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

        # RDC only: tile exterior notch zones (L-notch, etc.) among the
        # adjacent apts so each apt gets an explicit jardin polygon. The
        # frontend will render these directly instead of extruding the
        # jardin from the exterior walls.
        # Jardins RDC. Bâti sur alignement (UA.6) : les jardins côté RUE sont
        # impossibles (limite séparative de voie) → on ne pose QUE les jardins
        # donnant sur le VOID (échancrure / coin ouvert = fond de parcelle, côté
        # mitoyens). C'est l'invariant « jardin au fond » (user 2026-07-03) ; les
        # façades rue reçoivent une LOGGIA à la place (cf. _attach_balconies).
        # Bâti en retrait : on tuile toute la poche extérieure (void + rue).
        _jardin_commun_poly = None
        if is_rdc:
            try:
                _jardin_commun_poly = _compute_jardin_polygons(
                    cells_for_niveau, footprint, parcelle_shape,
                    voirie_orientations=tuple(inputs.voirie_orientations or (voirie,)),
                    void_only=getattr(inputs, "bati_sur_alignement", False),
                )
            except Exception:
                pass

        # Reclaim any leftover interior floor pocket (corner rectification /
        # tiling gaps) into the nearest apt's séjour — no wasted space.
        _reclaim_pockets(cells_for_niveau, footprint, core, circulations,
                         tuple(inputs.voirie_orientations or (voirie,)))

        # ZÉRO VIDE (2026-07-06, demande user) : le centre profond du L (ancienne
        # « courette » de 62 m² au coude) est désormais RÉCUPÉRÉ — bande par bande
        # dans les apts voisins (séjour profond) et, pour le reliquat vraiment
        # central, fusionné dans le couloir (spine du L). Plus AUCUN grand bloc
        # gris vide non attribué (défaut user). Universel (toute L).
        _shab_gain, _cour_poly = _absorb_blind_pockets(
            cells_for_niveau, footprint, core, circulations,
            tuple(inputs.voirie_orientations or (voirie,)))

        # Carve circulation out of every apartment so no logement ever overlaps
        # a common corridor (a corridor buried under an apt is unreachable — the
        # exact "can't reach the west wing without crossing the corner apt"
        # defect). Keep the largest remaining piece.
        _carve_circulations_from_cells(cells_for_niveau, circulations)

        # Fill any white pocket left INSIDE an apartment (L-shaped corner units
        # whose rooms tile only the main rectangle) with a real room, so rooms
        # tile the apt (RÈGLE #3) and no in-apt space is wasted.
        _fill_intra_apt_pockets(
            cells_for_niveau, footprint,
            tuple(inputs.voirie_orientations or (voirie,)))

        # Ré-agence PROPREMENT les logements MONO-FAÇADE (U) : retype selon la
        # largeur de façade cour réelle + génère nb_chambres==typo, séjour
        # plafonné, 0 cellier, 0 dégagement, chambres toutes sur la cour. Corrige
        # les apts de coin dégénérés (T4 sans chambre / séjour obèse / celliers).
        _relayout_mono_facade_apts(
            cells_for_niveau, footprint,
            tuple(inputs.voirie_orientations or (voirie,)),
            circulations=circulations)

        hauteur_hsp = _DEFAULT_HAUTEUR_RDC_M - 0.25 if is_rdc else _DEFAULT_HAUTEUR_ETAGE_M - 0.25
        # COUR INTÉRIEURE = trou traversant : on RETIRE son aire du plancher (preuve
        # que c'est un vrai vide, pas un renommage). La cour est un vide vertical
        # présent à TOUS les niveaux → cour_polygon_xy posé sur chaque Niveau.
        _cour_xy = None
        _cour_area = 0.0
        _atrium_active = False   # (opt-in ATRIUM_MODE=1) noyau planté DANS la cour
        _cage_vitree_cour = False  # v23 : escalier encloisonné VITRÉ adossé à la cour
        if _cour_poly is not None and not _cour_poly.is_empty \
                and _cour_poly.geom_type == "Polygon":
            _cour_xy = [(round(x, 2), round(y, 2))
                        for x, y in list(_cour_poly.exterior.coords)[:-1]]
            _cour_area = _cour_poly.area
            # ── CAGE INTÉGRÉE À LA COUR (2026-07-08, demande user) ───────────────
            # La cage esc+ASC ne doit PAS flotter au milieu du couloir : on la
            # RECOLLE à un coin de l'anneau de la cour (≥ 2 m sur la cour + ≥ 2 m
            # sur un mur d'apt), sans toucher au tuilage des logements (leur gabarit
            # casse si on les re-tuile). On ne déplace QUE le polygone de la cage.
            # Flag REVERT-TEST (CAGE_NO_SNAP=1) : saute le recollage → cage flottante
            # au centre du couloir (état v20) pour PROUVER que le gate durci
            # H-CAGE-BATIE (contact cour + apt ≥ 2 m) FIRE. En prod, flag absent.
            import os as _os_snap
            # ── PARTI v23 : ESCALIER ENCLOISONNÉ VITRÉ + COUR PLANTÉE OUVERTE ─────
            # (2026-07-09, décision user APRÈS chiffrage — l'atrium couvert est CADUC).
            # Raison : un escalier OUVERT reliant 6 niveaux dans un volume commun n'est
            # pas conforme comme escalier d'évacuation en habitation R+5 (arrêté du
            # 31/01/1986) → il forcerait un 2ᵉ escalier encloisonné + un désenfumage
            # d'atrium + une verrière structurelle = SHAB perdue à chaque étage + coût,
            # bilan sous les 12 %. Parti retenu, FINANÇABLE : UN seul escalier
            # ENCLOISONNÉ (conforme), adossé à un ANGLE de la cour (via
            # `_snap_cage_to_courtyard_corner`), avec sa PAROI VITRÉE côté cour (on voit
            # le vert en montant) ; la cour reste À CIEL OUVERT, richement PLANTÉE
            # (cœur d'îlot). Le confort « monter à travers un jardin » est conservé
            # SANS le régime atrium. Flag OPT-IN (ATRIUM_MODE=1) : réactive l'ancien
            # parti atrium couvert (noyau PLANTÉ dans la cour) — sert de REVERT-TEST
            # pour PROUVER que les checks H-ATRIUM FIRENT. En prod, flag absent → v23.
            _atrium_on = _os_snap.environ.get("ATRIUM_MODE") == "1"
            try:
                if _os_snap.environ.get("CAGE_NO_SNAP") == "1":
                    raise RuntimeError("cage snap disabled (revert-test)")
                from core.building_model.layout_l import (
                    _place_cage_in_atrium,
                    _snap_cage_to_courtyard_corner,
                )
                from shapely.geometry import Polygon as _SnapPoly
                from shapely.ops import unary_union as _snap_uu
                _apts_poly = _snap_uu([
                    _SnapPoly(c.polygon_xy) for c in cells_for_niveau
                    if c.type == CelluleType.LOGEMENT and c.polygon_xy
                    and len(c.polygon_xy) >= 3])
                _corr_poly = _snap_uu([
                    _SnapPoly(cc.polygon_xy) for cc in circulations
                    if not cc.id.startswith("cage") and cc.polygon_xy
                    and len(cc.polygon_xy) >= 3])
                for _cc in circulations:
                    if not _cc.id.startswith("cage") or not _cc.polygon_xy:
                        continue
                    _cage_g = _SnapPoly(_cc.polygon_xy)
                    if _atrium_on:
                        # ATRIUM : noyau DANS la cour, plaqué au couloir sur 1 face.
                        # REVERT-TEST (ATRIUM_CAGE_OUT=1) : on GARDE atrium_verriere=True
                        # mais on place le noyau HORS cour (snap tangent v23) → cage ∩
                        # cour ≈ 0. Sert à PROUVER que H-ATRIUM (a) « noyau ⊂ cour » FIRE
                        # (l'atrium annoncé mais le noyau posé à côté = incohérent). En
                        # prod : flag absent → noyau réellement planté dans l'atrium.
                        if _os_snap.environ.get("ATRIUM_CAGE_OUT") == "1":
                            _snapped = _snap_cage_to_courtyard_corner(
                                _cage_g, _cour_poly, _apts_poly, _corr_poly)
                            _atrium_active = True   # flag posé MAIS noyau hors cour
                        else:
                            _snapped = _place_cage_in_atrium(
                                _cage_g, _cour_poly, _corr_poly)
                            if _snapped is None:      # cour trop petite → fallback v23
                                _snapped = _snap_cage_to_courtyard_corner(
                                    _cage_g, _cour_poly, _apts_poly, _corr_poly)
                            elif _snapped is not _cage_g:
                                _atrium_active = True   # noyau planté dans l'atrium
                    else:
                        _snapped = _snap_cage_to_courtyard_corner(
                            _cage_g, _cour_poly, _apts_poly, _corr_poly)
                        # v23 : la cage encloisonnée est recollée à un angle de la
                        # cour → sa face côté cour est VITRÉE (on voit le vert en
                        # montant). Flag porté sur le niveau (rendu 2D + base 3D).
                        if _snapped is not None and _snapped is not _cage_g:
                            _cage_vitree_cour = True
                    if _snapped is not None and _snapped is not _cage_g:
                        _cc.polygon_xy = [
                            (round(x, 2), round(y, 2))
                            for x, y in list(_snapped.exterior.coords)[:-1]]
                        _cc.surface_m2 = _snapped.area
                        _snapped_cage_poly = _snapped
                        # ── CONFORT COULOIR (2026-07-08, demande user) ────────────────
                        # ANCIENNE logique (v22, RETIRÉE) : on GONFLAIT la cour dans la
                        # bande de couloir vacantée par la cage → la cour devenait un L
                        # (7 sommets) dont le BRAS remontait dans la bande de couloir et
                        # BLOQUAIT la circulation (cour ∩ couloir = tout, spine du L
                        # scindée du bandeau supérieur). L'user : « une partie de la cour
                        # bloque l'accès au couloir + escalier au hasard ».
                        # NOUVELLE logique : la cour RESTE un RECTANGLE NET. On NE la
                        # gonfle PAS. Le pan de couloir résiduel à côté de la cage est
                        # traité en AMONT (absorbé en SHAB dans l'apt adjacent par
                        # `_absorb_blind_pockets`) — PAS versé à la cour. Le couloir
                        # reste ainsi un ANNEAU d'un seul tenant reliant le bandeau
                        # supérieur, le coude et la spine, SANS vert en travers.
                        # Flag REVERT-TEST (COUR_GROW_L=1) : réactive l'ancien gonflement
                        # en L pour PROUVER que le gate durci (H-COUR-RECT +
                        # H-COULOIR-CONNEXE) FIRE sur l'état v22. En prod : flag absent.
                        if _os_snap.environ.get("COUR_GROW_L") != "1":
                            raise RuntimeError("cour-grow-L off (garde la cour rectangle)")
                        _cx0, _cy0, _cx1, _cy1 = _cour_poly.bounds
                        _sx0, _sy0, _sx1, _sy1 = _snapped.bounds
                        _apts_in = _apts_poly.buffer(-0.05)
                        # La bande à absorber est du côté de la cour où est la cage
                        # (cage tangente à une arête cour). On étend la cour vers la
                        # cage jusqu'au bord LIBRE de la cage, en x-range EXCLUANT la
                        # cage (bande latérale libre), et en profondeur = hauteur cage.
                        # Détecter l'arête cour tangente à la cage :
                        _touch_n = abs(_sy0 - _cy1) < 0.6   # cage au-dessus de la cour
                        _touch_s = abs(_sy1 - _cy0) < 0.6   # cage en-dessous
                        _touch_e = abs(_sx0 - _cx1) < 0.6   # cage à droite
                        _touch_w = abs(_sx1 - _cx0) < 0.6   # cage à gauche
                        _ext = None
                        # On laisse un COULOIR d'accès de _GAP m entre l'extension et
                        # la cage → la cage garde UNE seule arête sur la cour (son côté
                        # cour), l'autre côté restant desservi par le couloir.
                        _GAP = 1.6
                        if _touch_n or _touch_s:
                            # bande horizontale à la hauteur de la cage, x HORS cage+gap.
                            _ny0 = _cy1 if _touch_n else _sy0
                            _ny1 = _sy1 if _touch_n else _cy0
                            for _bx0, _bx1 in ((_cx0, _sx0 - _GAP), (_sx1 + _GAP, _cx1)):
                                if _bx1 - _bx0 < 1.0:
                                    continue
                                _c = _SnapPoly([(_bx0, _ny0), (_bx1, _ny0),
                                                (_bx1, _ny1), (_bx0, _ny1)])
                                if _c.intersection(_apts_in).area < 0.3 and footprint.buffer(0.05).contains(_c):
                                    _ext = _c if _ext is None else _ext.union(_c)
                        elif _touch_e or _touch_w:
                            _nx0 = _cx1 if _touch_e else _sx0
                            _nx1 = _sx1 if _touch_e else _cx0
                            for _by0, _by1 in ((_cy0, _sy0 - _GAP), (_sy1 + _GAP, _cy1)):
                                if _by1 - _by0 < 1.0:
                                    continue
                                _c = _SnapPoly([(_nx0, _by0), (_nx1, _by0),
                                                (_nx1, _by1), (_nx0, _by1)])
                                if _c.intersection(_apts_in).area < 0.3 and footprint.buffer(0.05).contains(_c):
                                    _ext = _c if _ext is None else _ext.union(_c)
                        if _ext is not None and not _ext.is_empty:
                            _grown = _cour_poly.union(_ext).buffer(0)
                            if (_grown.geom_type == "Polygon"
                                    and _grown.intersection(_apts_in).area < 1.0
                                    and _grown.intersection(_snapped).area < 0.5):
                                _cour_poly = _grown
                                _cour_xy = [(round(x, 2), round(y, 2))
                                            for x, y in list(_grown.exterior.coords)[:-1]]
                                _cour_area = _grown.area
            except Exception:
                pass
        # HARMONISATION des jardins-cour de MÊME typologie (défaut user 2026-07-08) :
        # après le relayout (typologies FINALES fixées), on rend CONCORDANTS les jardins
        # de même typo bordant la cour (mêmes dimensions + arêtes adjacentes calées). Ex.
        # 05 & 10 (T4) → 9×7 identiques, bords à x=9. Le résidu rogné revient au commun.
        # Flag de REVERT-TEST uniquement (JARDIN_NO_HARMONIZE=1) : saute l'harmonisation
        # pour reproduire l'état v17 (05=9,5×6,84 ≠ 10=9,0×7,0) et PROUVER que le gate
        # durci H-JARDIN-CONCORDE FIRE. En prod le flag est absent → comportement harmonisé.
        import os as _os_h
        if is_rdc and _os_h.environ.get("JARDIN_NO_HARMONIZE") != "1":
            try:
                _jardin_commun_poly = _harmonize_court_gardens(
                    cells_for_niveau, _jardin_commun_poly)
            except Exception:
                pass

        # ESPACE VERT COMMUN (RDC) : le résidu de la cour non couvert par les jardins
        # privatifs (fond de coin). Posé sur le Niveau, rendu vert distinct + label.
        _jardin_commun_xy = None
        if is_rdc and _jardin_commun_poly is not None \
                and not _jardin_commun_poly.is_empty \
                and _jardin_commun_poly.geom_type == "Polygon":
            _jardin_commun_xy = [(round(x, 2), round(y, 2))
                                 for x, y in list(_jardin_commun_poly.exterior.coords)[:-1]]
        # ATRIUM : le noyau esc+ASC est un VOLUME BÂTI qui occupe une part de la
        # cour à CHAQUE niveau — l'atrium est un vide vertical SAUF la colonne du
        # noyau. Le plancher reprend donc l'aire du noyau logée dans la cour (le
        # vide réel = cour − noyau = l'anneau planté). Sinon on retirerait le noyau
        # du plancher (faux : on y marche pour prendre l'escalier).
        _void_area = _cour_area
        if _atrium_active and _cour_xy:
            from shapely.geometry import Polygon as _VP
            _cour_g_v = _VP(_cour_xy)
            _cage_in_cour = 0.0
            for _cc in circulations:
                if _cc.id.startswith("cage") and _cc.polygon_xy \
                        and len(_cc.polygon_xy) >= 3:
                    _cage_in_cour += _VP(_cc.polygon_xy).intersection(_cour_g_v).area
            _void_area = max(0.0, _cour_area - _cage_in_cour)
        niveaux.append(Niveau(
            index=idx, code=f"R+{idx}",
            usage_principal=usage,
            hauteur_sous_plafond_m=hauteur_hsp,
            surface_plancher_m2=max(1.0, footprint.area - _void_area),
            cellules=cells_for_niveau,
            circulations_communes=circulations,
            cour_polygon_xy=_cour_xy,
            jardin_commun_polygon_xy=_jardin_commun_xy,
            atrium_verriere=_atrium_active,
            cage_vitree_cour=_cage_vitree_cour,
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

    # --- Build max PLU envelope (legal ceiling, independent of design) ---
    envelope_max_plu: EnvelopeMaxPLU | None = None
    try:
        envelope_max_plu = compute_max_envelope(
            plu_rules=inputs.plu_rules,
            parcelle_geojson=inputs.parcelle_geojson,
        )
    except Exception:
        # Max envelope is informational — never block BM generation.
        envelope_max_plu = None

    # --- Core with optional ascenseur ---
    ascenseur = None
    if inputs.niveaux_recommandes - 1 >= 2:
        ascenseur = Ascenseur(type="Schindler 3300", cabine_l_cm=110, cabine_p_cm=140, norme_pmr=True)

    # Extract the 4 rectangular corners of the core polygon so the
    # frontend can render a true rect (not a sqrt(surface) square).
    _core_polygon_xy: list[tuple[float, float]] | None = None
    # Aligner le core sur la cage RECOLLÉE au coin cour∩apt (si le snap a eu lieu),
    # sinon sur le core brut du dispatcher.
    _core_src_poly = _snapped_cage_poly if _snapped_cage_poly is not None else core.polygon
    try:
        if _core_src_poly is not None and not _core_src_poly.is_empty:
            _cx0, _cy0, _cx1, _cy1 = _core_src_poly.bounds
            _core_polygon_xy = [
                (_cx0, _cy0), (_cx1, _cy0), (_cx1, _cy1), (_cx0, _cy1),
            ]
    except Exception:
        _core_polygon_xy = None

    _core_pos = core.position_xy
    if _snapped_cage_poly is not None and not _snapped_cage_poly.is_empty:
        _sc = _snapped_cage_poly.bounds
        _core_pos = ((_sc[0] + _sc[2]) / 2, (_sc[1] + _sc[3]) / 2)
    core_schema = Core(
        position_xy=_core_pos,
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
        envelope_max_plu=envelope_max_plu,
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

    # --- Balcons: 1 par logement d'étage sur façade rue (voirie) ou cour,
    # jamais sur mitoyen. Règle user permanente (balcons tous les étages). ---
    _attach_balconies(
        bm.niveaux,
        shape(inputs.footprint_recommande_geojson),
        inputs.voirie_orientations,
        include_rdc=getattr(inputs, "bati_sur_alignement", False),
    )

    # --- Étape 6: Validation ---
    # Run the conformite gate (PLU + R.111-18 + business). It internally
    # re-runs the legacy validators (PMR / incendie / ventilation /
    # lumière) so the single resulting ConformiteCheck is the source of
    # truth for the API and the frontend.
    business_rules = inputs.business_rules
    if business_rules is None and inputs.commune is not None:
        business_rules = BusinessRules.for_commune(inputs.commune)
    bm.conformite_check = validate_conformite(
        bm, inputs.plu_rules, business_rules,
    )

    return bm
