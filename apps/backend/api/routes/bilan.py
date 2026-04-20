"""API routes for promoteur bilan (P&L) resource.

Public GET (like /projects/{id}) in v1 MVP: reads the latest BuildingModel
for the project, derives a BilanProgramme from it, applies the default IDF
2025 rates, and returns the computed BilanResult.

For custom rates (multi-scenario "Opt2", "Opt3"), POST accepts a full
BilanInputs override.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from core.building_model.schemas import BuildingModel
from core.feasibility.bilan_promoteur import (
    BilanInputs,
    BilanProgramme,
    BilanResult,
    compute_bilan,
    programme_from_building_model,
)
from db.models.building_models import BuildingModelRow
from db.session import SessionDep

router = APIRouter(prefix="/projects/{project_id}/feasibility", tags=["bilan"])


class BilanOverrides(BaseModel):
    """Partial overrides on top of the default IDF 2025 inputs."""

    mix_social_pct: float | None = None
    shab_commerce_m2: float | None = None
    inputs: BilanInputs | None = None


def _default_inputs_from_programme(p: BilanProgramme) -> BilanInputs:
    """Reasonable defaults when the user hasn't bought the terrain yet."""
    # Default charge foncière target: 30% of Nogent-style 6750 €/m² × SHAB
    default_terrain_price = max(p.sdp_m2 * 1800.0, 500_000.0)
    return BilanInputs(
        prix_terrain_total_ht=default_terrain_price,
        fonds_propres_ht=default_terrain_price * 1.2,
        frais_financiers_total=default_terrain_price * 0.05,
        taxe_amenagement_assiette_m2=p.sdp_m2 * 1.244,
    )


async def _load_building_model(
    project_id: UUID, session
) -> BuildingModel:
    row = (await session.execute(
        select(BuildingModelRow)
        .where(BuildingModelRow.project_id == project_id)
        .order_by(BuildingModelRow.version.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(
            status_code=404,
            detail="No building model for this project — generate one first",
        )
    return BuildingModel.model_validate(row.model_json)


@router.get("/bilan", response_model=BilanResult)
async def get_bilan(
    project_id: UUID,
    session: SessionDep,
) -> BilanResult:
    bm = await _load_building_model(project_id, session)
    programme = programme_from_building_model(bm)
    inputs = _default_inputs_from_programme(programme)
    return compute_bilan(programme, inputs, option_label="opt1")


@router.post("/bilan", response_model=BilanResult)
async def post_bilan(
    project_id: UUID,
    overrides: BilanOverrides,
    session: SessionDep,
) -> BilanResult:
    bm = await _load_building_model(project_id, session)
    programme = programme_from_building_model(
        bm,
        mix_social_pct=overrides.mix_social_pct or 0.0,
        shab_commerce_m2=overrides.shab_commerce_m2 or 0.0,
    )
    inputs = overrides.inputs or _default_inputs_from_programme(programme)
    return compute_bilan(programme, inputs, option_label="custom")
