"""Pydantic schemas for project version endpoints."""

from __future__ import annotations

from pydantic import BaseModel


class VersionCreate(BaseModel):
    label: str | None = None
    notes: str | None = None


class VersionOut(BaseModel):
    id: str
    version_number: int
    version_label: str | None
    created_at: str


class VersionCompareResponse(BaseModel):
    diff: dict
