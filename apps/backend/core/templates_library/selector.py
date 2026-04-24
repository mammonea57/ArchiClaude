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
        api_key = os.environ.get("OPENAI_API_KEY")
        self._use_mock = not api_key and openai_client is None
        self.openai = openai_client or (OpenAI(api_key=api_key) if api_key else None)

    async def select_for_slot(self, slot: ApartmentSlot) -> SelectionResult | None:
        # 1. Describe slot → embedding
        if self._use_mock:
            # Mock query embedding — matches seed_templates.py zero-mock fallback
            emb = [0.0] * 1536
        else:
            orient = " ".join(slot.orientations) if slot.orientations else "non défini"
            description = (
                f"Appartement {slot.target_typologie.value}, {slot.surface_m2:.1f}m², "
                f"orientation {orient}, position {slot.position_in_floor} dans l'étage."
            )
            assert self.openai is not None
            emb = self.openai.embeddings.create(
                model="text-embedding-3-small",
                input=description,
                dimensions=1536,
            ).data[0].embedding

        # 2. Vector search — try target typo first, then adjacent typos.
        # A 65 m² slot may be tagged T4 by surface but have a T3-compatible
        # width; widening the typo pool keeps slots that would otherwise
        # be dropped for missing templates.
        minx, miny, maxx, maxy = slot.polygon.bounds
        slot_width = maxx - minx
        slot_depth = maxy - miny

        _TYPO_ORDER = ["studio", "T1", "T2", "T3", "T4", "T5"]
        target = slot.target_typologie.value
        try_order: list[str] = [target]
        if target in _TYPO_ORDER:
            i = _TYPO_ORDER.index(target)
            # Prefer going DOWN one typo first (narrower slot → smaller typo),
            # then UP, then further out.
            for delta in (-1, 1, -2, 2):
                j = i + delta
                if 0 <= j < len(_TYPO_ORDER):
                    try_order.append(_TYPO_ORDER[j])

        filtered: list[TemplateCandidate] = []
        for typo_try in try_order:
            candidates = await search_compatible_templates(
                self.session, query_embedding=emb,
                typologie=typo_try, limit=10,
            )
            for c in candidates:
                dim = c.template.dimensions_grille
                if not (dim.largeur_min_m * 0.85 <= slot_width <= dim.largeur_max_m * 1.15):
                    continue
                if not (dim.profondeur_min_m * 0.85 <= slot_depth <= dim.profondeur_max_m * 1.15):
                    continue
                lo, hi = c.template.surface_shab_range
                if slot.surface_m2 > hi * 1.3:
                    continue
                filtered.append(c)
            if filtered:
                break  # Got matches from this typo tier

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
