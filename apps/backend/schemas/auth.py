from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10)
    full_name: str = Field(min_length=1, max_length=120)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class OAuthCallbackRequest(BaseModel):
    provider: Literal["google", "microsoft"]
    email: EmailStr
    name: str | None = None
    provider_user_id: str


class UserOut(BaseModel):
    id: UUID
    email: EmailStr
    full_name: str | None = None
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    user: UserOut
    default_workspace_id: UUID
