"""In-app notification creation + conditional email dispatch."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.notifications import email_sender, preferences
from db.models.notifications import NotificationRow

logger = logging.getLogger(__name__)


async def notify(
    *,
    session: AsyncSession,
    user_id: UUID,
    type: str,  # noqa: A002 — intentional public API name
    title: str,
    body: str | None = None,
    link: str | None = None,
    extra: dict[str, Any] | None = None,
    email_to: str | None = None,
    email_vars: dict[str, Any] | None = None,
) -> None:
    """Create in-app notification + send email according to user preferences."""
    row = NotificationRow(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        link=link,
        extra=extra,
    )
    session.add(row)
    await session.flush()

    prefs = await preferences.get_or_create(session, user_id)
    email_pref = getattr(prefs, f"email_{type}", False)
    if email_pref and email_to:
        await email_sender.send(
            to=email_to, template=type, variables=email_vars or {}
        )


async def send_invitation_email(
    *,
    to_email: str,
    workspace_name: str,
    invited_by_email: str,
    token: str,
) -> None:
    """Send invitation email (recipient may not have an account)."""
    await email_sender.send(
        to=to_email,
        template="workspace_invitation",
        variables={
            "workspace_name": workspace_name,
            "invited_by_email": invited_by_email,
            "token": token,
        },
    )
