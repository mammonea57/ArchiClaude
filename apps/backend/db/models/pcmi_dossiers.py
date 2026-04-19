"""DB model for PCMI dossiers — generated PC dossier PDFs/ZIPs per project."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

import db.models.projects  # noqa: F401 — ensure FK target is in Base.metadata
from db.base import Base


class PcmiDossierRow(Base):
    """One PCMI dossier generation record per (project_id, indice_revision)."""

    __tablename__ = "pcmi_dossiers"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="queued"
    )
    indice_revision: Mapped[str] = mapped_column(
        String(2), nullable=False
    )
    map_base: Mapped[str | None] = mapped_column(
        Text, nullable=True, server_default="scan25"
    )
    pdf_unique_r2_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    zip_r2_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    pieces_status: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_msg: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("project_id", "indice_revision", name="uq_pcmi_project_indice"),
    )
