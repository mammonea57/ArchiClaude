from datetime import datetime

from sqlalchemy import DateTime, Integer, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class CommuneSruRow(Base):
    __tablename__ = "commune_sru"

    code_insee: Mapped[str] = mapped_column(String(5), primary_key=True)
    annee_bilan: Mapped[int] = mapped_column(Integer, nullable=False)
    taux_lls_actuel: Mapped[object] = mapped_column(Numeric(5, 2), nullable=True)
    taux_lls_cible: Mapped[object] = mapped_column(Numeric(5, 2), nullable=True)
    statut: Mapped[str | None] = mapped_column(Text, nullable=True)
    penalite_annuelle_eur: Mapped[object] = mapped_column(Numeric, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
