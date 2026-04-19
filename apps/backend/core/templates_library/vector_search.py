# apps/backend/core/templates_library/vector_search.py
"""pgvector search for templates — cosine similarity."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.templates_library.schemas import Template
from db.models.templates import TemplateRow


@dataclass
class TemplateCandidate:
    template: Template
    similarity: float


async def search_compatible_templates(
    session: AsyncSession,
    query_embedding: list[float],
    typologie: str,
    limit: int = 10,
) -> list[TemplateCandidate]:
    """Return top-k templates matching typologie, ordered by cosine similarity."""
    stmt = (
        select(TemplateRow, TemplateRow.embedding.cosine_distance(query_embedding).label("cd"))
        .where(TemplateRow.typologie == typologie)
        .order_by("cd")
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [
        TemplateCandidate(
            template=Template.model_validate(r[0].json_data),
            similarity=1.0 - float(r[1]),  # cosine distance → similarity
        )
        for r in rows
    ]
