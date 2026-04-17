import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class PluDocumentRow(Base):
    __tablename__ = "plu_documents"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code_insee: Mapped[str] = mapped_column(String(5), nullable=False)
    gpu_doc_id: Mapped[str | None] = mapped_column(Text, unique=True, nullable=True)
    partition: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # PLU, PLUi, PLUbioclim, POS, RNU, CC
    nomfic: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    pdf_text_raw: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PluZoneRow(Base):
    __tablename__ = "plu_zones"
    __table_args__ = (UniqueConstraint("plu_doc_id", "code", name="uq_plu_zones_doc_code"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    plu_doc_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("plu_documents.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(Text, nullable=False)
    libelle: Mapped[str | None] = mapped_column(Text, nullable=True)
    libelong: Mapped[str | None] = mapped_column(Text, nullable=True)
    typezone: Mapped[str | None] = mapped_column(Text, nullable=True)
    geom: Mapped[object | None] = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=True)
