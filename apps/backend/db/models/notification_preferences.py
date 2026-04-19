"""Per-user notification preferences (email channel toggles)."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class NotificationPreferencesRow(Base):
    __tablename__ = "notification_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    in_app_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    email_workspace_invitations: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    email_project_analyzed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    email_project_ready_for_pc: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    email_mentions: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    email_comments: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    email_pcmi6_generated: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    email_weekly_digest: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
