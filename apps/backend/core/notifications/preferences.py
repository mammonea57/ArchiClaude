"""Notification preferences — get or create per-user defaults."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models.notification_preferences import NotificationPreferencesRow


async def get_or_create(
    session: AsyncSession, user_id: UUID
) -> NotificationPreferencesRow:
    row = (
        await session.execute(
            select(NotificationPreferencesRow).where(
                NotificationPreferencesRow.user_id == user_id
            )
        )
    ).scalar_one_or_none()
    if row:
        return row
    row = NotificationPreferencesRow(user_id=user_id)
    session.add(row)
    await session.flush()
    return row
