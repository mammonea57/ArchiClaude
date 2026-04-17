"""RAG search API routes — jurisprudences and recours endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Query

from core.analysis.rag.jurisprudences import search_jurisprudences
from core.analysis.rag.recours import search_recours
from schemas.rag import (
    JurisprudenceOut,
    JurisprudencesSearchResponse,
    RecoursOut,
    RecoursSearchResponse,
)

router = APIRouter(prefix="/rag", tags=["rag"])


@router.get("/jurisprudences/search", response_model=JurisprudencesSearchResponse)
async def search_jurisprudences_endpoint(
    q: str = Query(..., min_length=3, description="Texte de recherche (min 3 caractères)"),
    commune_insee: str | None = Query(
        None,
        pattern=r"^\d{5}$",
        description="Code INSEE de la commune (optionnel)",
    ),
    limit: int = Query(5, ge=1, le=20, description="Nombre maximum de résultats"),
) -> JurisprudencesSearchResponse:
    """Search jurisprudences (court decisions) by semantic similarity.

    Returns the most relevant jurisprudences for a given query text,
    optionally filtered by commune INSEE code.
    """
    matches = await search_jurisprudences(
        query=q,
        commune_insee=commune_insee,
        limit=limit,
    )

    items = [
        JurisprudenceOut(
            id=m.id,
            reference=m.reference,
            source=m.source,
            motif_principal=m.motif_principal,
            resume=m.resume,
            decision=m.decision,
            commune_insee=m.commune_insee,
            similarity=m.similarity,
        )
        for m in matches
    ]

    return JurisprudencesSearchResponse(items=items)


@router.get("/recours/search", response_model=RecoursSearchResponse)
async def search_recours_endpoint(
    commune_insee: str = Query(
        ...,
        pattern=r"^\d{5}$",
        description="Code INSEE de la commune (obligatoire)",
    ),
    limit: int = Query(5, ge=1, le=20, description="Nombre maximum de résultats"),
) -> RecoursSearchResponse:
    """Search recours cases (third-party appeals) for a commune.

    Returns the most relevant recours cases for a given commune,
    identified by its INSEE code.
    """
    matches = await search_recours(commune_insee=commune_insee, limit=limit)

    items = [
        RecoursOut(
            id=m.id,
            commune_insee=m.commune_insee,
            association=m.association,
            projet_conteste=m.projet_conteste,
            motifs=m.motifs,
            resultat=m.resultat,
            resume=m.resume,
            similarity=m.similarity,
        )
        for m in matches
    ]

    return RecoursSearchResponse(items=items)
