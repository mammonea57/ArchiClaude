"""Pending workspace invitations (email + token + expires_at)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class WorkspaceInvitationRow(Base):
    __tablename__ = "workspace_invitations"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    invited_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'member', 'viewer')",
            name="workspace_invitations_role_check",
        ),
    )
