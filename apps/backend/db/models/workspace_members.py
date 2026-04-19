"""Workspace membership with role (admin/member/viewer)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class WorkspaceMemberRow(Base):
    __tablename__ = "workspace_members"

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        primary_key=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role: Mapped[str] = mapped_column(Text, nullable=False)
    invited_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    invited_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    joined_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'member', 'viewer')",
            name="workspace_members_role_check",
        ),
    )
