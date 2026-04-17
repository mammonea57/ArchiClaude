"""Unit tests for core.analysis.architect_prompt."""

from __future__ import annotations

import pytest

from core.analysis.architect_prompt import SYSTEM_PROMPT, build_architect_prompt

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FEASIBILITY_SUMMARY = {
    "sdp_max_m2": 2400,
    "nb_logements_max": 28,
    "emprise_sol_m2": 600,
    "hauteur_max_m": 18.0,
    "shon_m2": 2400,
}


# ---------------------------------------------------------------------------
# SYSTEM_PROMPT tests
# ---------------------------------------------------------------------------


def test_system_prompt_is_string() -> None:
    """SYSTEM_PROMPT is a non-empty string."""
    assert isinstance(SYSTEM_PROMPT, str)
    assert len(SYSTEM_PROMPT) > 100


def test_system_prompt_mentions_idf() -> None:
    """SYSTEM_PROMPT positions the model as an IDF expert."""
    assert "Île-de-France" in SYSTEM_PROMPT or "IDF" in SYSTEM_PROMPT


def test_system_prompt_mentions_dplg() -> None:
    """SYSTEM_PROMPT mentions DPLG architect credential."""
    assert "DPLG" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Task 4 core tests
# ---------------------------------------------------------------------------


def test_contains_structure_sections() -> None:
    """build_architect_prompt includes all 5 required structural sections."""
    prompt = build_architect_prompt(
        feasibility_summary=_FEASIBILITY_SUMMARY,
        zone_code="UB",
        commune_name="Vincennes",
    )
    for section in ["Synthèse", "Opportunités", "Contraintes", "Alertes", "Recommandations"]:
        assert section in prompt, f"Section '{section}' manquante dans le prompt"


def test_includes_rag_context() -> None:
    """build_architect_prompt tags jurisprudences and recours context correctly."""
    prompt = build_architect_prompt(
        feasibility_summary=_FEASIBILITY_SUMMARY,
        zone_code="UC",
        commune_name="Montreuil",
        jurisprudences_context="TA Paris 2022 — annulation pour dépassement COS.",
        recours_context="Recours Association Voisins — rejeté 2023.",
    )
    assert "[jurisprudence]" in prompt
    assert "[recours_local]" in prompt
    assert "TA Paris 2022" in prompt
    assert "Recours Association Voisins" in prompt


def test_no_rag_graceful() -> None:
    """build_architect_prompt returns a valid prompt without any RAG context."""
    prompt = build_architect_prompt(
        feasibility_summary=_FEASIBILITY_SUMMARY,
        zone_code="UA",
        commune_name="Paris 11e",
    )
    assert isinstance(prompt, str)
    assert len(prompt) > 50
    # Should not contain orphaned tags
    assert "[jurisprudence]" not in prompt
    assert "[recours_local]" not in prompt


def test_includes_feasibility_data() -> None:
    """build_architect_prompt embeds feasibility numbers in the prompt."""
    prompt = build_architect_prompt(
        feasibility_summary=_FEASIBILITY_SUMMARY,
        zone_code="UB",
        commune_name="Vincennes",
    )
    # Key figures must appear
    assert "2400" in prompt or "sdp" in prompt.lower()
    assert "Vincennes" in prompt
    assert "UB" in prompt


def test_optional_site_context_included() -> None:
    """Optional site_context appears in the prompt when provided."""
    prompt = build_architect_prompt(
        feasibility_summary=_FEASIBILITY_SUMMARY,
        zone_code="UB",
        commune_name="Vincennes",
        site_context={"orientation": "Sud", "bruit_lden": 65},
    )
    assert "site" in prompt.lower() or "orientation" in prompt.lower() or "Sud" in prompt


def test_optional_comparables_included() -> None:
    """Optional comparables appear in the prompt when provided."""
    comparables = [{"adresse": "12 rue de la Paix", "nb_logements": 20}]
    prompt = build_architect_prompt(
        feasibility_summary=_FEASIBILITY_SUMMARY,
        zone_code="UB",
        commune_name="Vincennes",
        comparables=comparables,
    )
    assert "comparable" in prompt.lower() or "12 rue de la Paix" in prompt


def test_optional_alerts_included() -> None:
    """Optional alerts appear in the prompt when provided."""
    prompt = build_architect_prompt(
        feasibility_summary=_FEASIBILITY_SUMMARY,
        zone_code="UB",
        commune_name="Vincennes",
        alerts=["ABF périmètre 500m", "PPRI zone inondable"],
    )
    assert "ABF" in prompt or "alert" in prompt.lower()


def test_contains_lexique_metier() -> None:
    """SYSTEM_PROMPT or returned prompt references required architectural vocabulary."""
    # The lexique must appear in the system prompt (as instructions to the model)
    combined = SYSTEM_PROMPT
    lexique = [
        "faîtage",
        "acrotère",
        "gabarit",
        "prospect",
        "emprise",
        "pleine terre",
    ]
    found = [term for term in lexique if term in combined]
    assert len(found) >= 4, f"Seulement {len(found)} termes du lexique trouvés: {found}"
