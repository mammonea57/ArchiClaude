from datetime import datetime
from uuid import UUID

from sqlalchemy import ARRAY, TIMESTAMP, Boolean, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class FeatureFlagRow(Base):
    __tablename__ = "feature_flags"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    enabled_globally: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    enabled_for_user_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PgUUID(as_uuid=True)),
        nullable=False,
        server_default="{}",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
