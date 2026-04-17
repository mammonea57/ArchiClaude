"""Architect analysis pipeline — RAG enrichment + Claude Opus call."""

from __future__ import annotations

import logging
from typing import Any

from core.analysis.architect_prompt import SYSTEM_PROMPT, build_architect_prompt
from core.analysis.rag.jurisprudences import JurisprudenceMatch, search_jurisprudences
from core.analysis.rag.recours import RecoursMatch, search_recours

logger = logging.getLogger(__name__)

_MODEL = "claude-opus-4-6-20250514"
_MAX_TOKENS = 4000


# ---------------------------------------------------------------------------
# LLM call
# ---------------------------------------------------------------------------


async def _call_opus(system: str, user: str) -> str:
    """Send a message to Claude Opus and return the text response.

    Args:
        system: System prompt.
        user: User prompt.

    Returns:
        The model's text response as a string.
    """
    import anthropic

    client = anthropic.AsyncAnthropic()
    message = await client.messages.create(
        model=_MODEL,
        max_tokens=_MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return message.content[0].text


# ---------------------------------------------------------------------------
# RAG formatting helpers
# ---------------------------------------------------------------------------


def _format_jurisprudences(matches: list[JurisprudenceMatch]) -> str | None:
    """Format a list of JurisprudenceMatch into a tagged context block."""
    if not matches:
        return None
    lines: list[str] = []
    for m in matches:
        lines.append(f"- **{m.reference}** ({m.source})")
        if m.motif_principal:
            lines.append(f"  Motif : {m.motif_principal}")
        lines.append(f"  Résumé : {m.resume}")
        if m.decision:
            lines.append(f"  Décision : {m.decision}")
        if m.commune_insee:
            lines.append(f"  Commune INSEE : {m.commune_insee}")
        lines.append(f"  Similarité : {m.similarity:.2f}")
        lines.append("")
    return "\n".join(lines).strip()


def _format_recours(matches: list[RecoursMatch]) -> str | None:
    """Format a list of RecoursMatch into a tagged context block."""
    if not matches:
        return None
    lines: list[str] = []
    for m in matches:
        assoc = m.association or "Association inconnue"
        lines.append(f"- **{assoc}** (commune {m.commune_insee})")
        if m.projet_conteste:
            lines.append(f"  Projet contesté : {m.projet_conteste}")
        if m.motifs:
            lines.append(f"  Motifs : {', '.join(m.motifs)}")
        if m.resultat:
            lines.append(f"  Résultat : {m.resultat}")
        if m.resume:
            lines.append(f"  Résumé : {m.resume}")
        lines.append(f"  Similarité : {m.similarity:.2f}")
        lines.append("")
    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


async def run_architect_analysis(
    *,
    feasibility_summary: dict[str, Any],
    zone_code: str,
    commune_name: str,
    commune_insee: str | None = None,
    site_context: dict[str, Any] | None = None,
    compliance_summary: dict[str, Any] | None = None,
    comparables: list[dict[str, Any]] | None = None,
    alerts: list[str] | None = None,
) -> str:
    """Run the full architect analysis pipeline.

    Pipeline:
    1. RAG enrichment — fetch jurisprudences and recours cases in parallel.
    2. Format RAG results as tagged context strings.
    3. Build the user prompt via build_architect_prompt().
    4. Call Claude Opus via _call_opus(system, user).
    5. Return the markdown response string.

    Args:
        feasibility_summary: Feasibility engine output dict.
        zone_code: PLU zone code.
        commune_name: Human-readable commune name.
        commune_insee: Optional INSEE code for RAG context retrieval.
        site_context: Optional site analysis results.
        compliance_summary: Optional compliance check summary.
        comparables: Optional list of comparable projects.
        alerts: Optional list of alert strings.

    Returns:
        Markdown analysis string from Claude Opus.
    """
    import asyncio

    # --- Step 1: RAG enrichment ---
    jurisprudences: list[JurisprudenceMatch] = []
    recours: list[RecoursMatch] = []

    if commune_insee:
        # Build project description for jurisprudence search
        sdp = feasibility_summary.get("sdp_max_m2", "")
        project_desc = (
            f"Projet de construction neuve zone {zone_code} {commune_name} "
            f"SDP {sdp} m² commune {commune_insee}"
        )

        jur_task = search_jurisprudences(
            query=project_desc,
            commune_insee=commune_insee,
            limit=5,
        )
        rec_task = search_recours(commune_insee=commune_insee, limit=3)

        jurisprudences, recours = await asyncio.gather(jur_task, rec_task)
        logger.debug(
            "RAG: %d jurisprudences, %d recours for commune %s",
            len(jurisprudences),
            len(recours),
            commune_insee,
        )

    # --- Step 2: Format RAG context ---
    jurisprudences_context = _format_jurisprudences(jurisprudences)
    recours_context = _format_recours(recours)

    # --- Step 3: Build prompt ---
    user_prompt = build_architect_prompt(
        feasibility_summary=feasibility_summary,
        zone_code=zone_code,
        commune_name=commune_name,
        site_context=site_context,
        compliance_summary=compliance_summary,
        comparables=comparables,
        alerts=alerts,
        jurisprudences_context=jurisprudences_context,
        recours_context=recours_context,
    )

    # --- Step 4: Call Opus ---
    logger.info("Calling Claude Opus for architect analysis — commune %s zone %s", commune_name, zone_code)
    result = await _call_opus(system=SYSTEM_PROMPT, user=user_prompt)

    return result
