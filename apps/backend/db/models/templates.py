# apps/backend/db/models/templates.py
"""SQLAlchemy model for templates table with pgvector embedding."""
from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class TemplateRow(Base):
    __tablename__ = "templates"
    __table_args__ = (
        CheckConstraint(
            "source IN ('manual','scraped','llm_gen','llm_augmented')",
            name="templates_source_check",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    typologie: Mapped[str] = mapped_column(String(10), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    json_data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    preview_svg: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    rating_avg: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    usage_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_by: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
