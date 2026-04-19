"""Projects API routes — CRUD and feasibility analysis trigger."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from api.deps import CurrentUserDep
from db.models.project_status_history import ProjectStatusHistoryRow
from db.models.projects import ProjectRow
from db.session import SessionDep
from schemas.project import (
    AnalyzeJobResponse,
    AnalyzeStatusResponse,
    ProjectCreate,
    ProjectDetail,
    ProjectOut,
    ProjectStatusChange,
    ProjectStatusHistoryItem,
    ProjectStatusHistoryResponse,
    ProjectStatusResponse,
)

router = APIRouter(prefix="/projects", tags=["projects"])

# Placeholder user ID for v1 (auth integration deferred)
_PLACEHOLDER_USER_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


@router.post("", status_code=201, response_model=ProjectOut)
async def create_project(
    body: ProjectCreate,
    session: SessionDep,
) -> ProjectOut:
    """Create a new feasibility project.

    Returns the created project id, name, and status.
    """
    row = ProjectRow(
        id=uuid.uuid4(),
        user_id=_PLACEHOLDER_USER_ID,
        name=body.name,
        brief=body.brief,
        status="draft",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    return ProjectOut(id=str(row.id), name=row.name, status=row.status)


@router.get("", response_model=list[ProjectOut])
async def list_projects(
    session: SessionDep,
) -> list[ProjectOut]:
    """List all projects (v1: unscoped, returns all projects)."""
    result = await session.execute(select(ProjectRow).order_by(ProjectRow.created_at.desc()))
    rows = result.scalars().all()
    return [ProjectOut(id=str(r.id), name=r.name, status=r.status) for r in rows]


@router.get("/{project_id}", response_model=ProjectDetail)
async def get_project(
    project_id: str,
    session: SessionDep,
) -> ProjectDetail:
    """Get a project by ID, including the brief."""
    try:
        pid = uuid.UUID(project_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Project not found") from None

    result = await session.execute(select(ProjectRow).where(ProjectRow.id == pid))
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")

    return ProjectDetail(
        id=str(row.id),
        name=row.name,
        brief=row.brief,
        status=row.status,
    )


@router.post("/{project_id}/analyze", status_code=202, response_model=AnalyzeJobResponse)
async def analyze_project(
    project_id: str,
    session: SessionDep,
) -> AnalyzeJobResponse:
    """Trigger feasibility analysis for a project.

    v1: Returns a placeholder job_id. Actual ARQ dispatch is wired when
    Redis is available in the deployment environment.
    """
    # Validate project_id is a plausible UUID format (non-existent IDs are
    # acceptable in v1 since ARQ dispatch is stubbed).
    if not project_id:
        raise HTTPException(status_code=404, detail="Project not found")

    job_id = str(uuid.uuid4())
    return AnalyzeJobResponse(job_id=job_id, status="queued")


@router.get("/{project_id}/analyze/status", response_model=AnalyzeStatusResponse)
async def analyze_status(
    project_id: str,
    session: SessionDep,
) -> AnalyzeStatusResponse:
    """Get the analysis job status for a project.

    v1: Returns a static pending status. Real status tracking will query
    the ARQ job store when Redis integration is complete.
    """
    if not project_id:
        raise HTTPException(status_code=404, detail="Project not found")

    # Placeholder job ID derived from project ID (deterministic for v1)
    job_id = f"job-{project_id}"
    return AnalyzeStatusResponse(job_id=job_id, status="pending", progress=None)


ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"analyzed", "archived"},
    "analyzed": {"reviewed", "archived"},
    "reviewed": {"ready_for_pc", "archived"},
    "ready_for_pc": {"archived"},
    "archived": {"draft"},
}


@router.patch("/{project_id}/status", response_model=ProjectStatusResponse)
async def update_project_status(
    project_id: str,
    body: ProjectStatusChange,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> ProjectStatusResponse:
    project = await session.get(ProjectRow, UUID(project_id))
    if not project:
        raise HTTPException(404, "Project not found")

    from_status = project.status
    to_status = body.status

    if to_status not in ALLOWED_TRANSITIONS.get(from_status, set()):
        raise HTTPException(
            400, f"Transition {from_status} -> {to_status} not allowed"
        )

    project.status = to_status
    project.status_changed_at = datetime.now(UTC)
    project.status_changed_by = current_user.id

    session.add(
        ProjectStatusHistoryRow(
            project_id=project.id,
            from_status=from_status,
            to_status=to_status,
            changed_by=current_user.id,
            notes=body.notes,
        )
    )
    await session.commit()
    return ProjectStatusResponse(status=to_status)


@router.get(
    "/{project_id}/status_history", response_model=ProjectStatusHistoryResponse
)
async def get_status_history(
    project_id: str,
    current_user: CurrentUserDep,
    session: SessionDep,
) -> ProjectStatusHistoryResponse:
    rows = (
        await session.execute(
            select(ProjectStatusHistoryRow)
            .where(ProjectStatusHistoryRow.project_id == UUID(project_id))
            .order_by(ProjectStatusHistoryRow.changed_at.desc())
        )
    ).scalars().all()
    return ProjectStatusHistoryResponse(
        items=[
            ProjectStatusHistoryItem(
                id=str(r.id),
                from_status=r.from_status,
                to_status=r.to_status,
                changed_by=str(r.changed_by) if r.changed_by else None,
                changed_at=r.changed_at.isoformat() if r.changed_at else None,
                notes=r.notes,
            )
            for r in rows
        ]
    )
