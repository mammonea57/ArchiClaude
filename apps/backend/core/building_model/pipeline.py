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
                    cells_for_niveau.append(fit.apartment)

        circ = Circulation(
            id=f"palier_R{idx}",
            polygon_xy=list(core.polygon.exterior.coords)[:-1],
            surface_m2=core.polygon.area * 0.3,
            largeur_min_cm=140,
        )

        hauteur_hsp = _DEFAULT_HAUTEUR_RDC_M - 0.25 if is_rdc else _DEFAULT_HAUTEUR_ETAGE_M - 0.25
        niveaux.append(Niveau(
            index=idx, code=f"R+{idx}",
            usage_principal=usage,
            hauteur_sous_plafond_m=hauteur_hsp,
            surface_plancher_m2=footprint.area,
            cellules=cells_for_niveau,
            circulations_communes=[circ],
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
