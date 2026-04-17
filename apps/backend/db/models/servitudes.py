import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class ServitudeRow(Base):
    __tablename__ = "servitudes"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    type: Mapped[str] = mapped_column(Text, nullable=False)
    sous_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    libelle: Mapped[str | None] = mapped_column(Text, nullable=True)
    geom: Mapped[object | None] = mapped_column(Geometry("GEOMETRY", srid=4326), nullable=True)
    attributes: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
