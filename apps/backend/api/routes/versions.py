"""Versions API routes — project snapshot management."""

from __future__ import annotations

import uuid

from fastapi import APIRouter

from schemas.version import VersionCompareResponse, VersionOut

router = APIRouter(prefix="/projects/{project_id}/versions", tags=["versions"])


@router.post("", status_code=201, response_model=VersionOut)
async def create_version(
    project_id: str,
    label: str | None = None,
    notes: str | None = None,
) -> VersionOut:
    """Create a new version snapshot for the project.

    v1: Returns a placeholder version. Actual snapshot logic is wired
    when the full versioning pipeline is complete.
    """
    return VersionOut(
        id=str(uuid.uuid4()),
        version_number=1,
        version_label=label,
        created_at="2026-04-18T00:00:00Z",
    )


@router.get("", response_model=list[VersionOut])
async def list_versions(project_id: str) -> list[VersionOut]:
    """List all versions for a project. v1: placeholder returns empty list."""
    return []


@router.get("/compare", response_model=VersionCompareResponse)
async def compare_versions(
    project_id: str,
    a: int,
    b: int,
) -> VersionCompareResponse:
    """Compare two versions of a project. v1: placeholder returns empty diff."""
    return VersionCompareResponse(diff={})
