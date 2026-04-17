"""DB models for projects, project_parcels, and feasibility_results."""

from __future__ import annotations

import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import (
    ARRAY,
    DateTime,
    ForeignKey,
    Numeric,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB  # noqa: N811
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

import db.models.parcels  # noqa: F401, E402

# Ensure FK targets are in Base.metadata regardless of import order
import db.models.users  # noqa: F401, E402
from db.base import Base


class ProjectRow(Base):
    """A developer feasibility project."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    brief: Mapped[dict] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="draft"
    )  # draft | analyzed | archived
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ProjectParcelRow(Base):
    """Association table between a project and one or more cadastral parcels."""

    __tablename__ = "project_parcels"

    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        primary_key=True,
    )
    parcel_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("parcels.id"),
        primary_key=True,
    )
    ordering: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)


class FeasibilityResultRow(Base):
    """Persisted output of the feasibility engine for a project."""

    __tablename__ = "feasibility_results"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    footprint_geom: Mapped[object | None] = mapped_column(
        Geometry("MULTIPOLYGON", srid=4326), nullable=True
    )
    zone_rules_used: Mapped[list] = mapped_column(
        ARRAY(PgUUID(as_uuid=True)), nullable=False
    )
    confidence_score: Mapped[float | None] = mapped_column(Numeric(3, 2), nullable=True)
    warnings: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
