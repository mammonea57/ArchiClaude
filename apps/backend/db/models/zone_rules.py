"""DB models for zone rule extraction results."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class ZoneRulesTextRow(Base):
    """Stores verbatim parsed rules text extracted from a PLU PDF for a zone."""

    __tablename__ = "zone_rules_text"
    __table_args__ = (
        UniqueConstraint(
            "plu_zone_id",
            "commune_insee",
            "pdf_text_hash",
            name="uq_zone_rules_text_zone_commune_hash",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    plu_zone_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("plu_zones.id", ondelete="CASCADE"),
        nullable=False,
    )
    commune_insee: Mapped[str | None] = mapped_column(String(5), nullable=True)
    parsed_rules: Mapped[dict] = mapped_column(JSONB, nullable=False)
    pdf_text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )  # llm_sonnet, llm_haiku, paris_bioclim_parser, manual
    model_used: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_cost_cents: Mapped[float | None] = mapped_column(
        Numeric(10, 4), nullable=True
    )
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()",
    )


class ZoneRulesNumericRow(Base):
    """Stores structured numeric rules derived from ZoneRulesTextRow."""

    __tablename__ = "zone_rules_numeric"
    __table_args__ = (
        CheckConstraint(
            "extraction_confidence >= 0 AND extraction_confidence <= 1",
            name="chk_zone_rules_numeric_confidence_range",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    zone_rules_text_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("zone_rules_text.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    numeric_rules: Mapped[dict] = mapped_column(JSONB, nullable=False)
    extraction_confidence: Mapped[float | None] = mapped_column(
        Numeric(3, 2), nullable=True
    )
    warnings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    validated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    validation_edits: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
