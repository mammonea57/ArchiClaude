"""DB model for recours_cases — third-party appeals against building permits."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import ARRAY, Date, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class RecoursCaseRow(Base):
    """A recours contentieux or gracieux filed against a building permit."""

    __tablename__ = "recours_cases"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    commune_insee: Mapped[str] = mapped_column(String(5), nullable=False)
    date_depot: Mapped[date | None] = mapped_column(Date, nullable=True)
    association: Mapped[str | None] = mapped_column(Text, nullable=True)
    projet_conteste: Mapped[str | None] = mapped_column(Text, nullable=True)
    motifs: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True)
    resultat: Mapped[str | None] = mapped_column(Text, nullable=True)
    resume: Mapped[str | None] = mapped_column(Text, nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536), nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
