"""Workspace: multi-tenant scoping unit."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class WorkspaceRow(Base):
    __tablename__ = "workspaces"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_personal: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
