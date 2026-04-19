"""Workspaces + invitations (admin-side) routes."""
from __future__ import annotations

import re
import secrets
import time
from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import CurrentUserDep
from db.models.users import UserRow
from db.models.workspace_invitations import WorkspaceInvitationRow
from db.models.workspace_members import WorkspaceMemberRow
from db.models.workspaces import WorkspaceRow
from db.session import SessionDep
from schemas.invitation import InvitationCreate, InvitationOut
from schemas.workspace import (
    MemberOut,
    MembershipUpdate,
    WorkspaceCreate,
    WorkspaceListItem,
    WorkspaceOut,
    WorkspaceUpdate,
)

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{base}-{int(time.time())}"


def _to_out(w: WorkspaceRow) -> WorkspaceOut:
    return WorkspaceOut(
        id=w.id,
        name=w.name,
        slug=w.slug,
        description=w.description,
        logo_url=w.logo_url,
        is_personal=w.is_personal,
        created_at=w.created_at,
    )


async def _require_role(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    required: set[str],
) -> str:
    member = (
        await session.execute(
            select(WorkspaceMemberRow).where(
                WorkspaceMemberRow.workspace_id == workspace_id,
                WorkspaceMemberRow.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if not member or member.role not in required:
        raise HTTPException(403, "Forbidden")
    return member.role


_ANY_ROLE = {"admin", "member", "viewer"}


@router.post("", response_model=WorkspaceOut, status_code=201)
async def create_workspace(
    body: WorkspaceCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> WorkspaceOut:
    ws = WorkspaceRow(
        name=body.name,
        slug=_slugify(body.name),
        description=body.description,
        is_personal=False,
        created_by=current_user.id,
    )
    session.add(ws)
    await session.flush()
    session.add(
        WorkspaceMemberRow(
            workspace_id=ws.id,
            user_id=current_user.id,
            role="admin",
        )
    )
    await session.commit()
    await session.refresh(ws)
    return _to_out(ws)


@router.get("", response_model=list[WorkspaceListItem])
async def list_workspaces(
    session: SessionDep,
    current_user: CurrentUserDep,
) -> list[WorkspaceListItem]:
    rows = (
        await session.execute(
            select(WorkspaceRow, WorkspaceMemberRow.role)
            .join(
                WorkspaceMemberRow,
                WorkspaceMemberRow.workspace_id == WorkspaceRow.id,
            )
            .where(WorkspaceMemberRow.user_id == current_user.id)
            .order_by(WorkspaceRow.created_at.asc())
        )
    ).all()
    return [
        WorkspaceListItem(workspace=_to_out(ws), role=role) for ws, role in rows
    ]


@router.get("/{workspace_id}", response_model=WorkspaceOut)
async def get_workspace(
    workspace_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> WorkspaceOut:
    await _require_role(session, workspace_id, current_user.id, _ANY_ROLE)
    ws = await session.get(WorkspaceRow, workspace_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    return _to_out(ws)


@router.patch("/{workspace_id}", response_model=WorkspaceOut)
async def update_workspace(
    workspace_id: UUID,
    body: WorkspaceUpdate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> WorkspaceOut:
    await _require_role(session, workspace_id, current_user.id, {"admin"})
    ws = await session.get(WorkspaceRow, workspace_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")

    if body.name is not None:
        ws.name = body.name
    if body.description is not None:
        ws.description = body.description
    if body.logo_url is not None:
        ws.logo_url = body.logo_url

    await session.commit()
    await session.refresh(ws)
    return _to_out(ws)


@router.delete("/{workspace_id}", status_code=204, response_class=Response)
async def delete_workspace(
    workspace_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Response:
    await _require_role(session, workspace_id, current_user.id, {"admin"})
    ws = await session.get(WorkspaceRow, workspace_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")
    if ws.is_personal:
        raise HTTPException(400, "Cannot delete personal workspace")
    await session.delete(ws)
    await session.commit()
    return Response(status_code=204)


@router.get("/{workspace_id}/members", response_model=list[MemberOut])
async def list_members(
    workspace_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> list[MemberOut]:
    await _require_role(session, workspace_id, current_user.id, _ANY_ROLE)
    rows = (
        await session.execute(
            select(WorkspaceMemberRow, UserRow)
            .join(UserRow, UserRow.id == WorkspaceMemberRow.user_id)
            .where(WorkspaceMemberRow.workspace_id == workspace_id)
            .order_by(WorkspaceMemberRow.invited_at.asc())
        )
    ).all()
    return [
        MemberOut(
            user_id=u.id,
            email=u.email,
            full_name=u.full_name,
            role=m.role,
            joined_at=m.joined_at,
        )
        for m, u in rows
    ]


@router.patch(
    "/{workspace_id}/members/{user_id}", response_model=MemberOut
)
async def update_member_role(
    workspace_id: UUID,
    user_id: UUID,
    body: MembershipUpdate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> MemberOut:
    await _require_role(session, workspace_id, current_user.id, {"admin"})
    member = (
        await session.execute(
            select(WorkspaceMemberRow).where(
                WorkspaceMemberRow.workspace_id == workspace_id,
                WorkspaceMemberRow.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if not member:
        raise HTTPException(404, "Member not found")
    member.role = body.role
    await session.commit()

    user = await session.get(UserRow, user_id)
    assert user is not None
    return MemberOut(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=member.role,
        joined_at=member.joined_at,
    )


@router.delete(
    "/{workspace_id}/members/{user_id}",
    status_code=204,
    response_class=Response,
)
async def remove_member(
    workspace_id: UUID,
    user_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Response:
    await _require_role(session, workspace_id, current_user.id, {"admin"})
    if user_id == current_user.id:
        raise HTTPException(400, "Cannot remove yourself")
    member = (
        await session.execute(
            select(WorkspaceMemberRow).where(
                WorkspaceMemberRow.workspace_id == workspace_id,
                WorkspaceMemberRow.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if not member:
        raise HTTPException(404, "Member not found")
    await session.delete(member)
    await session.commit()
    return Response(status_code=204)


@router.post(
    "/{workspace_id}/invitations",
    response_model=InvitationOut,
    status_code=201,
)
async def create_invitation(
    workspace_id: UUID,
    body: InvitationCreate,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> InvitationOut:
    await _require_role(session, workspace_id, current_user.id, {"admin"})
    ws = await session.get(WorkspaceRow, workspace_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")

    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(UTC) + timedelta(days=7)

    inv = WorkspaceInvitationRow(
        workspace_id=workspace_id,
        email=str(body.email),
        role=body.role,
        invited_by=current_user.id,
        token=token,
        expires_at=expires_at,
    )
    session.add(inv)
    await session.commit()
    await session.refresh(inv)

    # Email send side-effect — dispatcher may not exist yet (Task 6).
    try:
        from core.notifications.dispatcher import send_invitation_email

        await send_invitation_email(
            to_email=str(body.email),
            workspace_name=ws.name,
            invited_by_email=current_user.email,
            token=token,
        )
    except Exception:
        pass

    return InvitationOut(
        id=inv.id,
        workspace_id=inv.workspace_id,
        workspace_name=ws.name,
        email=inv.email,
        role=inv.role,
        invited_by_email=current_user.email,
        created_at=inv.created_at,
        expires_at=inv.expires_at,
    )


@router.get(
    "/{workspace_id}/invitations", response_model=list[InvitationOut]
)
async def list_invitations(
    workspace_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> list[InvitationOut]:
    await _require_role(session, workspace_id, current_user.id, {"admin"})
    ws = await session.get(WorkspaceRow, workspace_id)
    if not ws:
        raise HTTPException(404, "Workspace not found")

    rows = (
        await session.execute(
            select(WorkspaceInvitationRow, UserRow)
            .join(UserRow, UserRow.id == WorkspaceInvitationRow.invited_by)
            .where(
                WorkspaceInvitationRow.workspace_id == workspace_id,
                WorkspaceInvitationRow.accepted_at.is_(None),
            )
            .order_by(WorkspaceInvitationRow.created_at.desc())
        )
    ).all()
    return [
        InvitationOut(
            id=inv.id,
            workspace_id=inv.workspace_id,
            workspace_name=ws.name,
            email=inv.email,
            role=inv.role,
            invited_by_email=inviter.email,
            created_at=inv.created_at,
            expires_at=inv.expires_at,
        )
        for inv, inviter in rows
    ]


@router.delete(
    "/{workspace_id}/invitations/{invitation_id}",
    status_code=204,
    response_class=Response,
)
async def cancel_invitation(
    workspace_id: UUID,
    invitation_id: UUID,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Response:
    await _require_role(session, workspace_id, current_user.id, {"admin"})
    inv = (
        await session.execute(
            select(WorkspaceInvitationRow).where(
                WorkspaceInvitationRow.id == invitation_id,
                WorkspaceInvitationRow.workspace_id == workspace_id,
            )
        )
    ).scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Invitation not found")
    await session.delete(inv)
    await session.commit()
    return Response(status_code=204)
