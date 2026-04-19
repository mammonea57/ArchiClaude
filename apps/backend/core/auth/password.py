"""Password hashing with bcrypt (rounds=12)."""
from __future__ import annotations
from passlib.context import CryptContext

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


def hash_password(plain: str) -> str:
    """Hash a plaintext password using bcrypt."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    return _pwd_context.verify(plain, hashed)
