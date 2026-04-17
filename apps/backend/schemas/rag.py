"""Pydantic response models for /rag/* endpoints."""

from __future__ import annotations

from pydantic import BaseModel


# ---------------------------------------------------------------------------
# Jurisprudences
# ---------------------------------------------------------------------------


class JurisprudenceOut(BaseModel):
    id: str
    reference: str
    source: str
    motif_principal: str | None
    resume: str
    decision: str | None
    commune_insee: str | None
    similarity: float


class JurisprudencesSearchResponse(BaseModel):
    items: list[JurisprudenceOut]


# ---------------------------------------------------------------------------
# Recours
# ---------------------------------------------------------------------------


class RecoursOut(BaseModel):
    id: str
    commune_insee: str
    association: str | None
    projet_conteste: str | None
    motifs: list[str]
    resultat: str | None
    resume: str | None
    similarity: float


class RecoursSearchResponse(BaseModel):
    items: list[RecoursOut]
