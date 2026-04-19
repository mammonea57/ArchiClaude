# apps/backend/db/models/building_models.py
"""SQLAlchemy model for building_models table."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB  # noqa: N811
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class BuildingModelRow(Base):
    __tablename__ = "building_models"
    __table_args__ = (
        UniqueConstraint("project_id", "version", name="uq_building_models_project_version"),
        CheckConstraint(
            "source IN ('auto','user_edit','regen')",
            name="building_models_source_check",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    model_json: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    conformite_check: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    generated_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("building_models.id"), nullable=True
    )
    dirty: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
