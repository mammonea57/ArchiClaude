# apps/backend/schemas/building_model_api.py
"""API schemas for BuildingModel endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class BuildingModelCreate(BaseModel):
    """Body for POST /projects/{id}/building_model/generate."""
    style_architectural_preference: str | None = None
    facade_style_preference: str | None = None
    toiture_type_preference: str | None = None
    loggias_souhaitees: bool = False
    commerces_rdc: bool = False
    parking_type: str = "souterrain"


class BuildingModelOut(BaseModel):
    """Response body."""
    model_config = ConfigDict(protected_namespaces=())

    id: UUID
    project_id: UUID
    version: int
    model_json: dict[str, Any]
    conformite_check: dict[str, Any] | None
    generated_at: datetime
    source: str
    dirty: bool


class BuildingModelVersionsOut(BaseModel):
    items: list[BuildingModelOut]
