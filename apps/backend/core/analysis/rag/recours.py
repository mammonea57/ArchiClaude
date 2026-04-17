"""RAG search over recours_cases — third-party appeals against building permits."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.analysis.rag.embeddings import generate_embedding

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecoursMatch:
    """A recours case retrieved by semantic similarity."""

    id: str
    commune_insee: str
    association: str | None
    projet_conteste: str | None
    motifs: list[str]
    resultat: str | None
    resume: str | None
    similarity: float


async def _vector_search_recours(
    embedding: list[float],
    commune_insee: str,
    limit: int,
) -> list[dict]:
    """Placeholder vector search — returns empty list until DB session is wired.

    Will be replaced in Phase 6 Task 4 with a real pgvector query.
    """
    return []


async def search_recours(
    *,
    commune_insee: str,
    limit: int = 3,
) -> list[RecoursMatch]:
    """Retrieve recours cases for a commune by similarity to the commune context.

    Args:
        commune_insee: INSEE code of the commune (required — recours are
            highly location-specific).
        limit: Maximum number of matches to return.

    Returns:
        Ordered list of ``RecoursMatch`` (most similar first).
        Returns an empty list if *commune_insee* is empty or no embedding key is set.
    """
    if not commune_insee or not commune_insee.strip():
        return []

    # Use commune_insee as the search query for context-aware retrieval
    embedding = await generate_embedding(commune_insee)
    if embedding is None:
        return []

    rows = await _vector_search_recours(embedding, commune_insee, limit)

    return [
        RecoursMatch(
            id=str(row["id"]),
            commune_insee=row["commune_insee"],
            association=row.get("association"),
            projet_conteste=row.get("projet_conteste"),
            motifs=list(row.get("motifs") or []),
            resultat=row.get("resultat"),
            resume=row.get("resume"),
            similarity=float(row["similarity"]),
        )
        for row in rows
    ]
