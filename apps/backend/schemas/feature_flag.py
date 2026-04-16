from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FeatureFlagBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    enabled_globally: bool
    enabled_for_user_ids: list[UUID]
    description: str | None = None


class FeatureFlagRead(FeatureFlagBase):
    updated_at: datetime


class FeatureFlagUpdate(BaseModel):
    enabled_globally: bool | None = None
    enabled_for_user_ids: list[UUID] | None = None
    description: str | None = None


class FeatureFlagCreate(FeatureFlagBase):
    pass
