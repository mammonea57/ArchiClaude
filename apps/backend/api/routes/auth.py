"""Auth routes — register, login, OAuth callback, me, logout."""
from __future__ import annotations

import os
import re
import time

from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import CurrentUserDep
from core.auth.jwt_utils import emit_jwt
from core.auth.password import hash_password, verify_password
from db.models.oauth_accounts import OAuthAccountRow
from db.models.users import UserRow
from db.models.workspace_members import WorkspaceMemberRow
from db.models.workspaces import WorkspaceRow
from db.session import SessionDep
from schemas.auth import (
    AuthResponse,
    LoginRequest,
    OAuthCallbackRequest,
    RegisterRequest,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


def _get_secret() -> str:
    s = os.environ.get("JWT_SECRET", "")
    if not s:
        raise HTTPException(500, "JWT_SECRET not configured")
    return s


def _slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{base}-{int(time.time())}"


async def _create_personal_workspace(
    session: AsyncSession, user: UserRow
) -> WorkspaceRow:
    ws = WorkspaceRow(
        name=f"{user.full_name or user.email} — Espace personnel",
        slug=_slugify(user.email),
        is_personal=True,
        created_by=user.id,
    )
    session.add(ws)
    await session.flush()
    session.add(
        WorkspaceMemberRow(workspace_id=ws.id, user_id=user.id, role="admin")
    )
    await session.flush()
    return ws


def _to_user_out(u: UserRow) -> UserOut:
    return UserOut(
        id=u.id, email=u.email, full_name=u.full_name, created_at=u.created_at
    )


@router.post("/register", response_model=AuthResponse, status_code=201)
async def register(body: RegisterRequest, session: SessionDep) -> AuthResponse:
    existing = (
        await session.execute(
            select(UserRow).where(UserRow.email == body.email)
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(409, "Email already registered")

    user = UserRow(
        email=body.email,
        full_name=body.full_name,
        password_hash=hash_password(body.password),
    )
    session.add(user)
    await session.flush()

    ws = await _create_personal_workspace(session, user)
    await session.commit()
    await session.refresh(user)

    token = emit_jwt(
        user_id=user.id, email=user.email, workspace_id=ws.id, secret=_get_secret()
    )
    return AuthResponse(
        access_token=token, user=_to_user_out(user), default_workspace_id=ws.id
    )


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, session: SessionDep) -> AuthResponse:
    user = (
        await session.execute(
            select(UserRow).where(UserRow.email == body.email)
        )
    ).scalar_one_or_none()
    if not user or not user.password_hash:
        raise HTTPException(401, "Invalid credentials")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")

    ws_id = (
        await session.execute(
            select(WorkspaceMemberRow.workspace_id)
            .where(WorkspaceMemberRow.user_id == user.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if not ws_id:
        ws = await _create_personal_workspace(session, user)
        ws_id = ws.id
        await session.commit()

    token = emit_jwt(
        user_id=user.id, email=user.email, workspace_id=ws_id, secret=_get_secret()
    )
    return AuthResponse(
        access_token=token, user=_to_user_out(user), default_workspace_id=ws_id
    )


@router.post("/oauth/callback", response_model=AuthResponse)
async def oauth_callback(
    body: OAuthCallbackRequest, session: SessionDep
) -> AuthResponse:
    oauth_row = (
        await session.execute(
            select(OAuthAccountRow).where(
                OAuthAccountRow.provider == body.provider,
                OAuthAccountRow.provider_user_id == body.provider_user_id,
            )
        )
    ).scalar_one_or_none()

    if oauth_row:
        user = await session.get(UserRow, oauth_row.user_id)
    else:
        user = (
            await session.execute(
                select(UserRow).where(UserRow.email == body.email)
            )
        ).scalar_one_or_none()
        if not user:
            user = UserRow(
                email=body.email,
                full_name=body.name,
                password_hash=None,
            )
            session.add(user)
            await session.flush()
            await _create_personal_workspace(session, user)

        session.add(
            OAuthAccountRow(
                user_id=user.id,
                provider=body.provider,
                provider_user_id=body.provider_user_id,
            )
        )
        await session.commit()
        await session.refresh(user)

    ws_id = (
        await session.execute(
            select(WorkspaceMemberRow.workspace_id)
            .where(WorkspaceMemberRow.user_id == user.id)
            .limit(1)
        )
    ).scalar_one_or_none()
    if not ws_id:
        ws = await _create_personal_workspace(session, user)
        ws_id = ws.id
        await session.commit()

    token = emit_jwt(
        user_id=user.id, email=user.email, workspace_id=ws_id, secret=_get_secret()
    )
    return AuthResponse(
        access_token=token, user=_to_user_out(user), default_workspace_id=ws_id
    )


@router.get("/me", response_model=UserOut)
async def me(current_user: CurrentUserDep) -> UserOut:
    return _to_user_out(current_user)


@router.post("/logout", status_code=204, response_class=Response)
async def logout(current_user: CurrentUserDep) -> Response:
    return Response(status_code=204)
