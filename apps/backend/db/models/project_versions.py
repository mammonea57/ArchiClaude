"""DB model for project_versions — immutable snapshots of a project at each revision."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

import db.models.projects  # noqa: F401 — ensure FK target is in Base.metadata
from db.base import Base


class ProjectVersionRow(Base):
    """An immutable snapshot of a project brief and feasibility result."""

    __tablename__ = "project_versions"
    __table_args__ = (UniqueConstraint("project_id", "version_number"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    version_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("project_versions.id", ondelete="SET NULL"),
        nullable=True,
    )
    brief_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    feasibility_result_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feasibility_results.id", ondelete="SET NULL"),
        nullable=True,
    )
    # pdf_report_id deferred — FK to reports table (Phase 7)
    pdf_report_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), nullable=True
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
