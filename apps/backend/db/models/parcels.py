import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class ParcelRow(Base):
    __tablename__ = "parcels"
    __table_args__ = (UniqueConstraint("code_insee", "section", "numero", name="uq_parcels_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    code_insee: Mapped[str] = mapped_column(String(5), nullable=False)
    section: Mapped[str] = mapped_column(String(3), nullable=False)
    numero: Mapped[str] = mapped_column(String(5), nullable=False)
    contenance_m2: Mapped[int | None] = mapped_column(Integer, nullable=True)
    geom: Mapped[object] = mapped_column(Geometry("MULTIPOLYGON", srid=4326), nullable=False)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
