"""Invitation acceptance routes (invitee side)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from api.deps import CurrentUserDep
from db.models.users import UserRow
from db.models.workspace_invitations import WorkspaceInvitationRow
from db.models.workspace_members import WorkspaceMemberRow
from db.models.workspaces import WorkspaceRow
from db.session import SessionDep
from schemas.invitation import AcceptInvitationResponse, InvitationOut

router = APIRouter(tags=["invitations"])


@router.get("/me/invitations", response_model=list[InvitationOut])
async def my_invitations(
    session: SessionDep,
    current_user: CurrentUserDep,
) -> list[InvitationOut]:
    now = datetime.now(timezone.utc)
    rows = (
        await session.execute(
            select(WorkspaceInvitationRow, WorkspaceRow, UserRow)
            .join(
                WorkspaceRow,
                WorkspaceRow.id == WorkspaceInvitationRow.workspace_id,
            )
            .join(UserRow, UserRow.id == WorkspaceInvitationRow.invited_by)
            .where(
                WorkspaceInvitationRow.email == current_user.email,
                WorkspaceInvitationRow.accepted_at.is_(None),
                WorkspaceInvitationRow.expires_at > now,
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
        for inv, ws, inviter in rows
    ]


@router.post(
    "/invitations/{token}/accept", response_model=AcceptInvitationResponse
)
async def accept_invitation(
    token: str,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> AcceptInvitationResponse:
    inv = (
        await session.execute(
            select(WorkspaceInvitationRow).where(
                WorkspaceInvitationRow.token == token
            )
        )
    ).scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Invitation not found")
    if inv.accepted_at is not None:
        raise HTTPException(400, "Invitation already accepted")
    now = datetime.now(timezone.utc)
    if inv.expires_at <= now:
        raise HTTPException(400, "Invitation expired")
    if inv.email.lower() != current_user.email.lower():
        raise HTTPException(403, "Invitation is for a different email")

    existing = (
        await session.execute(
            select(WorkspaceMemberRow).where(
                WorkspaceMemberRow.workspace_id == inv.workspace_id,
                WorkspaceMemberRow.user_id == current_user.id,
            )
        )
    ).scalar_one_or_none()
    if not existing:
        session.add(
            WorkspaceMemberRow(
                workspace_id=inv.workspace_id,
                user_id=current_user.id,
                role=inv.role,
                invited_by=inv.invited_by,
                joined_at=now,
            )
        )

    inv.accepted_at = now
    await session.commit()
    return AcceptInvitationResponse(
        workspace_id=inv.workspace_id, role=inv.role
    )


@router.post(
    "/invitations/{token}/decline",
    status_code=204,
    response_class=Response,
)
async def decline_invitation(
    token: str,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> Response:
    inv = (
        await session.execute(
            select(WorkspaceInvitationRow).where(
                WorkspaceInvitationRow.token == token
            )
        )
    ).scalar_one_or_none()
    if not inv:
        raise HTTPException(404, "Invitation not found")
    if inv.email.lower() != current_user.email.lower():
        raise HTTPException(403, "Invitation is for a different email")
    await session.delete(inv)
    await session.commit()
    return Response(status_code=204)
