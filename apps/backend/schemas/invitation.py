from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr


class InvitationCreate(BaseModel):
    email: EmailStr
    role: Literal["admin", "member", "viewer"]


class InvitationOut(BaseModel):
    id: UUID
    workspace_id: UUID
    workspace_name: str
    email: str
    role: str
    invited_by_email: str
    created_at: datetime
    expires_at: datetime


class AcceptInvitationResponse(BaseModel):
    workspace_id: UUID
    role: str
