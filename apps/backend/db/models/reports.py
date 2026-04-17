"""DB model for reports — generated HTML/PDF files tied to a feasibility result."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

import db.models.projects  # noqa: F401 — ensure FK target is in Base.metadata
from db.base import Base


class ReportRow(Base):
    """A generated report (HTML or PDF) for a feasibility result."""

    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    feasibility_result_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("feasibility_results.id", ondelete="CASCADE"),
        nullable=False,
    )
    format: Mapped[str] = mapped_column(Text, nullable=False)  # html | pdf
    r2_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
