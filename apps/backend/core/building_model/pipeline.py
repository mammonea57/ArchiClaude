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
    """Replace each apt's porte_entree with one on the wall closest to a
    circulation polygon. Called after the solver + adapter so it uses the
    real placed geometry."""
    from core.building_model.schemas import Opening, OpeningType, Wall, WallType
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
        # Find closest circulation polygon to this apt
        closest = min(circ_polys, key=lambda p: p.distance(apt_poly))
        # Compute the apt's bbox sides and see which one is closest to the
        # circulation
        xs = [p[0] for p in apt.polygon_xy]
        ys = [p[1] for p in apt.polygon_xy]
        minx, miny, maxx, maxy = min(xs), min(ys), max(xs), max(ys)
        # Test each side's midpoint distance to closest circulation
        from shapely.geometry import Point
        sides = {
            "sud":   Point((minx + maxx) / 2, miny),
            "nord":  Point((minx + maxx) / 2, maxy),
            "ouest": Point(minx, (miny + maxy) / 2),
            "est":   Point(maxx, (miny + maxy) / 2),
        }
        best_side = min(sides.keys(), key=lambda s: sides[s].distance(closest))

        # Remove existing porte_entree(s)
        apt.openings = [op for op in apt.openings if op.type != OpeningType.PORTE_ENTREE]

        # Build/find the wall on that side
        if best_side == "sud":
            p0, p1 = (minx, miny), (maxx, miny)
        elif best_side == "nord":
            p0, p1 = (minx, maxy), (maxx, maxy)
        elif best_side == "ouest":
            p0, p1 = (minx, miny), (minx, maxy)
        else:
            p0, p1 = (maxx, miny), (maxx, maxy)

        wall_id = f"{apt.id}_w_corridor"
        apt.walls.append(Wall(
            id=wall_id,
            type=WallType.PORTEUR,
            thickness_cm=20,
            geometry={"type": "LineString", "coords": [list(p0), list(p1)]},
            hauteur_cm=260,
            materiau="beton_banche",
        ))
        wall_len_cm = int(((p1[0] - p0[0]) ** 2 + (p1[1] - p0[1]) ** 2) ** 0.5 * 100)
        apt.openings.append(Opening(
            id=f"{apt.id}_op_entree",
            type=OpeningType.PORTE_ENTREE,
            wall_id=wall_id,
            position_along_wall_cm=max(50, wall_len_cm // 2),
            width_cm=93,
            height_cm=220,
            allege_cm=None,
            swing="interior_right",
        ))


def _emit_wing_corridors(
    niveau_idx: int,
    core,
    footprint,
    cells: list[Cellule],
) -> list[Circulation]:
    """Emit one corridor per wing of the footprint.

    Each wing is a rectangle (from the same decomposition used by the
    solver). The corridor runs along the wing's longer axis, centered on
    its shorter axis → it lies exactly between the two rows of apts in a
    dual-loaded layout, touching every apt.
    """
    from shapely.geometry import Polygon as ShapelyPoly
    from core.building_model.solver import _decompose_into_wings

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
                # Horizontal connector at core's Y level, from core east/west
                # edge toward the corridor.
                if wxmin_c > core_bb[2]:
                    cx0_conn = core_bb[2]; cx1_conn = (wxmin_c + wxmax_c) / 2 + half
                elif wxmax_c < core_bb[0]:
                    cx0_conn = (wxmin_c + wxmax_c) / 2 - half; cx1_conn = core_bb[0]
                else:
                    cx0_conn = core_bb[2]; cx1_conn = (wxmin_c + wxmax_c) / 2 + half
                connector = ShapelyPoly([
                    (min(cx0_conn, cx1_conn), core_cy - half),
                    (max(cx0_conn, cx1_conn), core_cy - half),
                    (max(cx0_conn, cx1_conn), core_cy + half),
                    (min(cx0_conn, cx1_conn), core_cy + half),
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
