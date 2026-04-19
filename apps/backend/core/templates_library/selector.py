# apps/backend/core/templates_library/selector.py
"""Template selector — choose best template for a slot.

v1: rule-based filtering + scoring (OpenAI embedding query).
v2 (next): add Claude Opus ranking + justification.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

from openai import OpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from core.building_model.solver import ApartmentSlot
from core.templates_library.schemas import Template
from core.templates_library.vector_search import TemplateCandidate, search_compatible_templates


@dataclass
class SelectionResult:
    template: Template
    confidence: float  # 0..1
    alternatives: list[str]  # other template IDs
    rationale: str


class TemplateSelector:
    def __init__(self, session: AsyncSession, openai_client: OpenAI | None = None):
        self.session = session
        self.openai = openai_client or OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))

    async def select_for_slot(self, slot: ApartmentSlot) -> SelectionResult | None:
        # 1. Describe slot → embedding
        orient = " ".join(slot.orientations) if slot.orientations else "non défini"
        description = (
            f"Appartement {slot.target_typologie.value}, {slot.surface_m2:.1f}m², "
            f"orientation {orient}, position {slot.position_in_floor} dans l'étage."
        )
        emb = self.openai.embeddings.create(
            model="text-embedding-3-small",
            input=description,
            dimensions=1536,
        ).data[0].embedding

        # 2. Vector search
        candidates = await search_compatible_templates(
            self.session, query_embedding=emb,
            typologie=slot.target_typologie.value, limit=10,
        )
        if not candidates:
            return None

        # 3. Filter by hard constraints
        minx, miny, maxx, maxy = slot.polygon.bounds
        slot_width = maxx - minx
        slot_depth = maxy - miny

        filtered: list[TemplateCandidate] = []
        for c in candidates:
            dim = c.template.dimensions_grille
            if not (dim.largeur_min_m <= slot_width <= dim.largeur_max_m):
                continue
            if not (dim.profondeur_min_m <= slot_depth <= dim.profondeur_max_m):
                continue
            lo, hi = c.template.surface_shab_range
            if not (lo * 0.9 <= slot.surface_m2 <= hi * 1.1):
                continue
            filtered.append(c)

        if not filtered:
            return None

        # 4. Rank by similarity + rating
        def score(c: TemplateCandidate) -> float:
            return c.similarity * 0.7 + (c.template.rating.success_rate or 0.0) * 0.3

        ranked = sorted(filtered, key=score, reverse=True)
        best = ranked[0]
        alternatives = [c.template.id for c in ranked[1:3]]

        return SelectionResult(
            template=best.template,
            confidence=score(best),
            alternatives=alternatives,
            rationale=f"Selected {best.template.id} (similarity {best.similarity:.2f}, "
                      f"matches typologie {slot.target_typologie.value} and dimensions).",
        )
