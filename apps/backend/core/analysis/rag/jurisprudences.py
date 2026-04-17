"""RAG search over jurisprudences — court decisions relevant to PLU/permis de construire."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.analysis.rag.embeddings import generate_embedding

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JurisprudenceMatch:
    """A jurisprudence retrieved by semantic similarity."""

    id: str
    reference: str
    source: str
    motif_principal: str | None
    resume: str
    decision: str | None
    commune_insee: str | None
    similarity: float


async def _vector_search(
    embedding: list[float],
    commune_insee: str | None,
    limit: int,
) -> list[dict]:
    """Placeholder vector search — returns empty list until DB session is wired.

    This will be replaced in Phase 6 Task 4 with a real pgvector cosine-distance
    query using an async SQLAlchemy session injected via FastAPI dependency.
    """
    return []


async def search_jurisprudences(
    *,
    query: str,
    commune_insee: str | None = None,
    limit: int = 5,
) -> list[JurisprudenceMatch]:
    """Retrieve the most semantically similar jurisprudences for *query*.

    Args:
        query: Free-text description of the legal question or project context.
        commune_insee: Optional INSEE code to restrict results to a commune.
        limit: Maximum number of matches to return.

    Returns:
        Ordered list of ``JurisprudenceMatch`` (most similar first).
        Returns an empty list if *query* is empty or no embedding key is set.
    """
    if not query or not query.strip():
        return []

    embedding = await generate_embedding(query)
    if embedding is None:
        return []

    rows = await _vector_search(embedding, commune_insee, limit)

    return [
        JurisprudenceMatch(
            id=str(row["id"]),
            reference=row["reference"],
            source=row["source"],
            motif_principal=row.get("motif_principal"),
            resume=row["resume"],
            decision=row.get("decision"),
            commune_insee=row.get("commune_insee"),
            similarity=float(row["similarity"]),
        )
        for row in rows
    ]
