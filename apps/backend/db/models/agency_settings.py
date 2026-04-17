"""DB model for agency_settings — per-user agency branding and contact details."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

import db.models.users  # noqa: F401 — ensure FK target is in Base.metadata
from db.base import Base


class AgencySettingsRow(Base):
    """Agency branding and contact settings for a user."""

    __tablename__ = "agency_settings"
    __table_args__ = (UniqueConstraint("user_id", name="uq_agency_settings_user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    agency_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo_r2_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_email: Mapped[str | None] = mapped_column(Text, nullable=True)
    contact_phone: Mapped[str | None] = mapped_column(Text, nullable=True)
    archi_ordre_number: Mapped[str | None] = mapped_column(Text, nullable=True)
    default_cartouche_footer: Mapped[str | None] = mapped_column(Text, nullable=True)
    brand_primary_color: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
