import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class ComparableProjectRow(Base):
    __tablename__ = "comparable_projects"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    source: Mapped[str] = mapped_column(Text, nullable=False)
    commune_insee: Mapped[str] = mapped_column(String(5), nullable=False)
    date_arrete: Mapped[object] = mapped_column(
        "date_arrete", Text, nullable=True
    )  # stored as text for flexibility; cast to Date in queries
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    geom: Mapped[object] = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    sdp_m2: Mapped[object] = mapped_column(Numeric, nullable=True)
    nb_logements: Mapped[int | None] = mapped_column(Integer, nullable=True)
    destination: Mapped[str | None] = mapped_column(Text, nullable=True)
    hauteur_niveaux: Mapped[int | None] = mapped_column(Integer, nullable=True)
    url_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
