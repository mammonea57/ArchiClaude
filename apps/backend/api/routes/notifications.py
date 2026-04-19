"""Notifications + notification preferences routes."""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import func, select

from api.deps import CurrentUserDep
from core.notifications import preferences as prefs_module
from db.models.notification_preferences import NotificationPreferencesRow
from db.models.notifications import NotificationRow
from db.session import SessionDep
from schemas.notification import (
    NotificationOut,
    NotificationPreferencesOut,
    NotificationPreferencesUpdate,
    NotificationsResponse,
    UnreadCountResponse,
)

router = APIRouter(tags=["notifications"])


def _to_out(n: NotificationRow) -> NotificationOut:
    return NotificationOut(
        id=n.id,
        type=n.type,
        title=n.title,
        body=n.body,
        link=n.link,
        extra=n.extra,
        read_at=n.read_at,
        created_at=n.created_at,
    )


def _prefs_to_out(p: NotificationPreferencesRow) -> NotificationPreferencesOut:
    return NotificationPreferencesOut(
        in_app_enabled=p.in_app_enabled,
        email_workspace_invitations=p.email_workspace_invitations,
        email_project_analyzed=p.email_project_analyzed,
        email_project_ready_for_pc=p.email_project_ready_for_pc,
        email_mentions=p.email_mentions,
        email_comments=p.email_comments,
        email_pcmi6_generated=p.email_pcmi6_generated,
        email_weekly_digest=p.email_weekly_digest,
    )


@router.get("/notifications", response_model=NotificationsResponse)
async def list_notifications(
    session: SessionDep,
    current_user: CurrentUserDep,
    unread_only: bool = False,
    limit: int = 20,
) -> NotificationsResponse:
    base = select(NotificationRow).where(
        NotificationRow.user_id == current_user.id
    )
    if unread_only:
        base = base.where(NotificationRow.read_at.is_(None))

    rows = (
        await session.execute(
            base.order_by(NotificationRow.created_at.desc()).limit(limit)
        )
    ).scalars().all()

    total = (
        await session.execute(
            select(func.count())
            .select_from(NotificationRow)
            .where(NotificationRow.user_id == current_user.id)
        )
    ).scalar_one()

    unread = (
        await session.execute(
            select(func.count())
            .select_from(NotificationRow)
            .where(
                NotificationRow.user_id == current_user.id,
                NotificationRow.read_at.is_(None),
            )
        )
    ).scalar_one()

    return NotificationsResponse(
        items=[_to_out(r) for r in rows],
        total=int(total),
        unread=int(unread),
    )


@router.get("/notifications/unread-count", response_model=UnreadCountResponse)
async def unread_count(
    session: SessionDep,
    current_user: CurrentUserDep,
) -> UnreadCountResponse:
    count = (
        await session.execute(
            select(func.count())
            .select_from(NotificationRow)
            .where(
                NotificationRow.user_id == current_user.id,
                NotificationRow.read_at.is_(None),
            )
        )
    ).scalar_one()
    return UnreadCountResponse(count=int(count))


@router.patch(
    "/notifications/{notification_id}/read",
    status_code=204,
    response_class=Response,
)
async def mark_read(
    notification_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Response:
    row = (
        await session.execute(
            select(NotificationRow).where(
                NotificationRow.id == notification_id,
                NotificationRow.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if not row:
        raise HTTPException(404, "Notification not found")
    if row.read_at is None:
        row.read_at = datetime.now(UTC)
    await session.commit()
    return Response(status_code=204)


@router.post(
    "/notifications/mark-all-read",
    status_code=204,
    response_class=Response,
)
async def mark_all_read(
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Response:
    now = datetime.now(UTC)
    rows = (
        await session.execute(
            select(NotificationRow).where(
                NotificationRow.user_id == current_user.id,
                NotificationRow.read_at.is_(None),
            )
        )
    ).scalars().all()
    for r in rows:
        r.read_at = now
    await session.commit()
    return Response(status_code=204)


@router.get(
    "/account/notifications", response_model=NotificationPreferencesOut
)
async def get_preferences(
    session: SessionDep,
    current_user: CurrentUserDep,
) -> NotificationPreferencesOut:
    prefs = await prefs_module.get_or_create(session, current_user.id)
    await session.commit()
    return _prefs_to_out(prefs)


@router.patch(
    "/account/notifications", response_model=NotificationPreferencesOut
)
async def update_preferences(
    body: NotificationPreferencesUpdate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> NotificationPreferencesOut:
    prefs = await prefs_module.get_or_create(session, current_user.id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(prefs, field, value)
    await session.commit()
    await session.refresh(prefs)
    return _prefs_to_out(prefs)
