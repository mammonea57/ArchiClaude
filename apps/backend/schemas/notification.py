from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class NotificationOut(BaseModel):
    id: UUID
    type: str
    title: str
    body: str | None
    link: str | None
    extra: dict[str, Any] | None
    read_at: datetime | None
    created_at: datetime


class NotificationsResponse(BaseModel):
    items: list[NotificationOut]
    total: int
    unread: int


class UnreadCountResponse(BaseModel):
    count: int


class NotificationPreferencesOut(BaseModel):
    in_app_enabled: bool
    email_workspace_invitations: bool
    email_project_analyzed: bool
    email_project_ready_for_pc: bool
    email_mentions: bool
    email_comments: bool
    email_pcmi6_generated: bool
    email_weekly_digest: bool


class NotificationPreferencesUpdate(BaseModel):
    in_app_enabled: bool | None = None
    email_workspace_invitations: bool | None = None
    email_project_analyzed: bool | None = None
    email_project_ready_for_pc: bool | None = None
    email_mentions: bool | None = None
    email_comments: bool | None = None
    email_pcmi6_generated: bool | None = None
    email_weekly_digest: bool | None = None
