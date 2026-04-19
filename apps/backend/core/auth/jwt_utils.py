"""JWT emission and verification (HS256, 7 days default)."""
from __future__ import annotations
import time
from typing import Any
from uuid import UUID

import jwt as pyjwt

DEFAULT_EXPIRY_SECONDS = 7 * 86400  # 7 days
REFRESH_THRESHOLD_SECONDS = 24 * 3600  # refresh if <24h remaining


class JWTError(Exception):
    """Raised when JWT is invalid, expired or malformed."""


def emit_jwt(
    *,
    user_id: UUID,
    email: str,
    workspace_id: UUID,
    secret: str,
    expires_in_seconds: int = DEFAULT_EXPIRY_SECONDS,
) -> str:
    """Emit a signed HS256 JWT with user_id, email, workspace_id, exp, iat."""
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "email": email,
        "workspace_id": str(workspace_id),
        "iat": now,
        "exp": now + expires_in_seconds,
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


def decode_jwt(token: str, *, secret: str) -> dict[str, Any]:
    """Decode and validate a JWT. Raises JWTError on invalid/expired."""
    try:
        return pyjwt.decode(token, secret, algorithms=["HS256"])
    except pyjwt.ExpiredSignatureError as e:
        raise JWTError("Token expired") from e
    except pyjwt.InvalidTokenError as e:
        raise JWTError(f"Invalid token: {e}") from e


def needs_refresh(token: str, *, secret: str) -> bool:
    """True if token expires within REFRESH_THRESHOLD_SECONDS.

    Returns False for invalid/expired tokens — caller must still call
    decode_jwt to enforce validity. This is a convenience helper for
    already-validated sessions, not a validation primitive.
    """
    try:
        payload = decode_jwt(token, secret=secret)
    except JWTError:
        return False
    return payload["exp"] - int(time.time()) < REFRESH_THRESHOLD_SECONDS
