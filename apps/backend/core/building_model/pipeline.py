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

    mix = {
        Typologie(k): v
        for k, v in inputs.brief.mix_typologique.items()
    }
    slots_per_floor = compute_apartment_slots(grid, core, mix_typologique=mix, voirie_side=voirie)

    # --- Étape 3-4: Select template per slot + adapt ---
    selector = TemplateSelector(session=session)
    adapter = TemplateAdapter()
    niveaux: list[Niveau] = []

    for idx in range(inputs.niveaux_recommandes):
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
