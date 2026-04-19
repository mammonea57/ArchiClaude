from __future__ import annotations
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, Field


Role = Literal["admin", "member", "viewer"]


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None


class WorkspaceUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    logo_url: str | None = None


class WorkspaceOut(BaseModel):
    id: UUID
    name: str
    slug: str
    description: str | None
    logo_url: str | None
    is_personal: bool
    created_at: datetime


class WorkspaceListItem(BaseModel):
    workspace: WorkspaceOut
    role: Role


class MemberOut(BaseModel):
    user_id: UUID
    email: str
    full_name: str | None
    role: Role
    joined_at: datetime | None


class MembershipUpdate(BaseModel):
    role: Role
