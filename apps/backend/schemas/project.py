"""Pydantic schemas for projects API."""

from __future__ import annotations

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    """Request body for creating a new project."""

    name: str
    brief: dict


class ProjectOut(BaseModel):
    """Minimal project representation returned in list and create responses."""

    id: str
    name: str
    status: str


class ProjectDetail(BaseModel):
    """Full project detail including brief."""

    id: str
    name: str
    brief: dict
    status: str


class AnalyzeJobResponse(BaseModel):
    """Response for POST /projects/{id}/analyze — job has been queued."""

    job_id: str
    status: str


class AnalyzeStatusResponse(BaseModel):
    """Response for GET /projects/{id}/analyze/status."""

    job_id: str
    status: str
    progress: str | None = None
