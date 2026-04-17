"""DB model for jurisprudences — court decisions relevant to PLU/permis de construire."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, Date, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class JurisprudenceRow(Base):
    """A court ruling (TA/CAA/CE) related to urban planning or building permits."""

    __tablename__ = "jurisprudences"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    reference: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    date: Mapped[date | None] = mapped_column(Date, nullable=True)
    commune_insee: Mapped[str | None] = mapped_column(String(5), nullable=True)
    motif_principal: Mapped[str | None] = mapped_column(Text, nullable=True)
    articles_plu_cites: Mapped[list[str] | None] = mapped_column(
        ARRAY(Text), nullable=True
    )
    resume: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
