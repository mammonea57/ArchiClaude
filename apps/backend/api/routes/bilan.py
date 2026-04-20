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
from db.models.projects import ProjectRow
from db.session import SessionDep

router = APIRouter(prefix="/projects/{project_id}/feasibility", tags=["bilan"])


# Local LLS quotas by commune — PLU exigences au-delà du plancher SRU (25 %).
# Storing here for the v1 MVP ; long-term this should come from the PLU rules
# database and be parsed from the commune's règlement.
_COMMUNE_LLS_QUOTA: dict[str, float] = {
    "nogent-sur-marne": 0.30,
}


def _lls_quota_for_project(project: ProjectRow) -> float:
    """Return the PLU-imposed LLS quota for the project's commune.

    The project doesn't have a dedicated ``commune`` column in v1, so we
    scan the ``name`` field (which typically carries the address) and the
    ``brief`` dict for commune hints.
    """
    haystack_parts: list[str] = []
    if getattr(project, "name", None):
        haystack_parts.append(str(project.name))
    brief = getattr(project, "brief", None) or {}
    if isinstance(brief, dict):
        for key in ("commune", "address", "adresse"):
            if isinstance(brief.get(key), str):
                haystack_parts.append(brief[key])
    haystack = " ".join(haystack_parts).lower()
    for commune, quota in _COMMUNE_LLS_QUOTA.items():
        if commune in haystack:
            return quota
    return 0.0


class BilanOverrides(BaseModel):
    """Partial overrides on top of the default IDF 2025 inputs."""

    mix_social_pct: float | None = None
    shab_commerce_m2: float | None = None
    lls_quota_minimum: float | None = None
    inputs: BilanInputs | None = None


def _default_inputs_from_programme(p: BilanProgramme) -> BilanInputs:
    """Reasonable defaults when the user hasn't bought the terrain yet."""
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


async def _load_project(project_id: UUID, session) -> ProjectRow | None:
    return await session.get(ProjectRow, project_id)


@router.get("/bilan", response_model=BilanResult)
async def get_bilan(
    project_id: UUID,
    session: SessionDep,
) -> BilanResult:
    bm = await _load_building_model(project_id, session)
    project = await _load_project(project_id, session)
    quota = _lls_quota_for_project(project) if project else 0.0
    # If the commune imposes a quota, allocate that share to social by
    # default so the warning doesn't fire on a brand-new building model.
    mix_social = quota
    programme = programme_from_building_model(
        bm, mix_social_pct=mix_social, lls_quota_minimum=quota,
    )
    inputs = _default_inputs_from_programme(programme)
    return compute_bilan(programme, inputs, option_label="opt1")


@router.post("/bilan", response_model=BilanResult)
async def post_bilan(
    project_id: UUID,
    overrides: BilanOverrides,
    session: SessionDep,
) -> BilanResult:
    bm = await _load_building_model(project_id, session)
    project = await _load_project(project_id, session)
    default_quota = _lls_quota_for_project(project) if project else 0.0
    quota = overrides.lls_quota_minimum if overrides.lls_quota_minimum is not None else default_quota
    # If the user didn't override mix_social, use the quota so the default
    # bilan respects the commune's LLS obligation.
    mix_social = overrides.mix_social_pct if overrides.mix_social_pct is not None else quota
    programme = programme_from_building_model(
        bm,
        mix_social_pct=mix_social,
        shab_commerce_m2=overrides.shab_commerce_m2 or 0.0,
        lls_quota_minimum=quota,
    )
    inputs = overrides.inputs or _default_inputs_from_programme(programme)
    return compute_bilan(programme, inputs, option_label="custom")
