"""API dependencies — auth, session, RLS context."""
from __future__ import annotations

import os
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException
from sqlalchemy import select, text

from core.auth.jwt_utils import JWTError, decode_jwt
from db.models.users import UserRow
from db.session import SessionDep


def _get_jwt_secret() -> str:
    secret = os.environ.get("JWT_SECRET", "")
    if not secret:
        raise RuntimeError("JWT_SECRET not configured")
    return secret


async def get_current_user(
    session: SessionDep,
    authorization: str | None = Header(default=None),
) -> UserRow:
    """Validate JWT from Authorization header, return User, set RLS context."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing authorization header")

    token = authorization[7:]
    try:
        payload = decode_jwt(token, secret=_get_jwt_secret())
    except JWTError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    user_id = UUID(payload["sub"])
    user = (
        await session.execute(select(UserRow).where(UserRow.id == user_id))
    ).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    await session.execute(text(f"SET LOCAL app.user_id = '{user.id}'"))
    return user


async def get_current_user_optional(
    session: SessionDep,
    authorization: str | None = Header(default=None),
) -> UserRow | None:
    """Like get_current_user but returns None instead of 401."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    try:
        return await get_current_user(session=session, authorization=authorization)
    except HTTPException:
        return None


CurrentUserDep = Annotated[UserRow, Depends(get_current_user)]
