# apps/backend/api/routes/building_model.py
"""API routes for BuildingModel resource."""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from api.deps import CurrentUserDep
from core.building_model.pipeline import GenerationInputs, generate_building_model
from core.feasibility.schemas import Brief
from core.plu.schemas import NumericRules
from db.models.building_models import BuildingModelRow
from db.models.projects import ProjectRow
from db.session import SessionDep
from schemas.building_model_api import BuildingModelCreate, BuildingModelOut, BuildingModelVersionsOut

router = APIRouter(prefix="/projects/{project_id}/building_model", tags=["building_model"])


def _to_out(row: BuildingModelRow) -> BuildingModelOut:
    return BuildingModelOut(
        id=row.id, project_id=row.project_id, version=row.version,
        model_json=row.model_json, conformite_check=row.conformite_check,
        generated_at=row.generated_at, source=row.source, dirty=row.dirty,
    )


@router.get("", response_model=BuildingModelOut)
async def get_current_building_model(
    project_id: UUID,
    session: SessionDep,
) -> BuildingModelOut:
    # Read-only — public like GET /projects/{id} in v1 MVP. Auth is enforced
    # on mutating endpoints (generate, restore).
    row = (await session.execute(
        select(BuildingModelRow)
        .where(BuildingModelRow.project_id == project_id)
        .order_by(BuildingModelRow.version.desc())
        .limit(1)
    )).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="No building model for this project")
    return _to_out(row)


@router.post("/generate", response_model=BuildingModelOut, status_code=status.HTTP_201_CREATED)
async def generate_endpoint(
    project_id: UUID,
    body: BuildingModelCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> BuildingModelOut:
    project = await session.get(ProjectRow, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="Project not found")

    # Fetch latest feasibility + PLU — MVP: use placeholder from project.brief
    brief_dict = project.brief or {}

    # For v1: hardcode simple parcelle geometry from project (real wiring in Sprint 2)
    # The brief should contain these, but for now we use fallbacks if missing.
    inputs = GenerationInputs(
        project_id=project_id,
        parcelle_geojson=brief_dict.get("parcelle_geojson",
            {"type": "Polygon", "coordinates": [[[0,0],[20,0],[20,18],[0,18],[0,0]]]}),
        parcelle_surface_m2=brief_dict.get("parcelle_surface_m2", 360.0),
        voirie_orientations=brief_dict.get("voirie_orientations", ["sud"]),
        north_angle_deg=0.0,
        plu_rules=NumericRules(
            emprise_max_pct=brief_dict.get("emprise_max_pct", 40.0),
            hauteur_max_m=brief_dict.get("hauteur_max_m", 18.0),
            pleine_terre_min_pct=30.0, retrait_voirie_m=None,
            retrait_limite_m=4.0, stationnement_pct=100.0,
            hauteur_max_niveaux=brief_dict.get("hauteur_max_niveaux", 5),
        ),
        zone_plu=brief_dict.get("zone_plu", "UA"),
        brief=Brief(
            destination=brief_dict.get("destination", "logement_collectif"),
            cible_nb_logements=brief_dict.get("cible_nb_logements", 12),
            cible_sdp_m2=brief_dict.get("cible_sdp_m2", 900),
            mix_typologique=brief_dict.get("mix_typologique", {"T2": 0.4, "T3": 0.4, "T4": 0.2}),
        ),
        footprint_recommande_geojson=brief_dict.get("footprint_recommande_geojson",
            {"type": "Polygon", "coordinates": [[[2,2],[16,2],[16,14],[2,14],[2,2]]]}),
        niveaux_recommandes=brief_dict.get("niveaux_recommandes", 4),
        hauteur_recommandee_m=brief_dict.get("hauteur_recommandee_m", 12.0),
        emprise_pct_recommandee=brief_dict.get("emprise_pct_recommandee", 40.0),
        style_architectural_preference=body.style_architectural_preference,
        facade_style_preference=body.facade_style_preference,
    )

    bm = await generate_building_model(inputs, session=session)

    # Persist
    next_version = ((await session.execute(
        select(BuildingModelRow.version)
        .where(BuildingModelRow.project_id == project_id)
        .order_by(BuildingModelRow.version.desc())
        .limit(1)
    )).scalar_one_or_none() or 0) + 1

    row = BuildingModelRow(
        project_id=project_id,
        version=next_version,
        model_json=bm.model_dump(mode="json"),
        conformite_check=bm.conformite_check.model_dump(mode="json") if bm.conformite_check else None,
        generated_by=current_user.id,
        source="auto",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return _to_out(row)


@router.get("/versions", response_model=BuildingModelVersionsOut)
async def list_versions(
    project_id: UUID,
    session: SessionDep,
) -> BuildingModelVersionsOut:
    rows = (await session.execute(
        select(BuildingModelRow)
        .where(BuildingModelRow.project_id == project_id)
        .order_by(BuildingModelRow.version.desc())
    )).scalars().all()
    return BuildingModelVersionsOut(items=[_to_out(r) for r in rows])


@router.post("/restore/{version}", response_model=BuildingModelOut)
async def restore_version(
    project_id: UUID, version: int,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> BuildingModelOut:
    src = (await session.execute(
        select(BuildingModelRow)
        .where(BuildingModelRow.project_id == project_id, BuildingModelRow.version == version)
    )).scalar_one_or_none()
    if src is None:
        raise HTTPException(status_code=404, detail="Version not found")

    next_version = ((await session.execute(
        select(BuildingModelRow.version)
        .where(BuildingModelRow.project_id == project_id)
        .order_by(BuildingModelRow.version.desc())
        .limit(1)
    )).scalar_one_or_none() or 0) + 1

    new_row = BuildingModelRow(
        project_id=project_id,
        version=next_version,
        model_json=src.model_json,
        conformite_check=src.conformite_check,
        generated_by=current_user.id,
        source="regen",
        parent_version_id=src.id,
    )
    session.add(new_row)
    await session.commit()
    await session.refresh(new_row)
    return _to_out(new_row)
