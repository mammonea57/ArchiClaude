"""Unit tests for core.analysis.architect_analysis."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from core.analysis.rag.jurisprudences import JurisprudenceMatch
from core.analysis.rag.recours import RecoursMatch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FEASIBILITY_SUMMARY = {
    "sdp_max_m2": 2400,
    "nb_logements_max": 28,
    "emprise_sol_m2": 600,
    "hauteur_max_m": 18.0,
}

_FAKE_MARKDOWN = """## Synthèse

Ce projet présente une bonne faisabilité pour la zone UB de Vincennes.

## Opportunités

- Marché DVF favorable
- Bonne desserte en transports

## Contraintes

- Gabarit-enveloppe limité à R+4
- Emprise sol max 600 m²

## Alertes

- Vérifier prospect vis-à-vis du voisinage

## Recommandations

1. Optimiser le faîtage
2. Prévoir l'acrotère végétalisé
3. Maximiser la pleine terre
"""


def _make_jurisprudence_match() -> JurisprudenceMatch:
    return JurisprudenceMatch(
        id=str(uuid.uuid4()),
        reference="TA Paris 2023-042",
        source="Légifrance",
        motif_principal="Dépassement emprise",
        resume="Annulation pour dépassement d'emprise au sol en zone UB.",
        decision="Annulation",
        commune_insee="94078",
        similarity=0.88,
    )


def _make_recours_match() -> RecoursMatch:
    return RecoursMatch(
        id=str(uuid.uuid4()),
        commune_insee="94078",
        association="Défense de Vincennes",
        projet_conteste="Résidence R+5 avenue de Paris",
        motifs=["hauteur excessive", "vis-à-vis"],
        resultat="rejeté",
        resume="Recours rejeté pour défaut d'intérêt à agir.",
        similarity=0.75,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_returns_markdown() -> None:
    """run_architect_analysis returns a string containing '## Synthèse'."""
    from core.analysis.architect_analysis import run_architect_analysis

    with (
        patch(
            "core.analysis.architect_analysis._call_opus",
            new=AsyncMock(return_value=_FAKE_MARKDOWN),
        ),
        patch(
            "core.analysis.architect_analysis.search_jurisprudences",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "core.analysis.architect_analysis.search_recours",
            new=AsyncMock(return_value=[]),
        ),
    ):
        result = await run_architect_analysis(
            feasibility_summary=_FEASIBILITY_SUMMARY,
            zone_code="UB",
            commune_name="Vincennes",
            commune_insee="94078",
        )

    assert isinstance(result, str)
    assert "## Synthèse" in result


async def test_includes_rag_if_available() -> None:
    """run_architect_analysis succeeds and returns markdown when RAG returns results."""
    from core.analysis.architect_analysis import run_architect_analysis

    jur_match = _make_jurisprudence_match()
    rec_match = _make_recours_match()

    with (
        patch(
            "core.analysis.architect_analysis._call_opus",
            new=AsyncMock(return_value=_FAKE_MARKDOWN),
        ),
        patch(
            "core.analysis.architect_analysis.search_jurisprudences",
            new=AsyncMock(return_value=[jur_match]),
        ),
        patch(
            "core.analysis.architect_analysis.search_recours",
            new=AsyncMock(return_value=[rec_match]),
        ),
    ):
        result = await run_architect_analysis(
            feasibility_summary=_FEASIBILITY_SUMMARY,
            zone_code="UB",
            commune_name="Vincennes",
            commune_insee="94078",
        )

    assert isinstance(result, str)
    assert len(result) > 0


async def test_rag_called_with_correct_params() -> None:
    """RAG functions are called with expected arguments."""
    from core.analysis.architect_analysis import run_architect_analysis

    jur_mock = AsyncMock(return_value=[])
    rec_mock = AsyncMock(return_value=[])

    with (
        patch(
            "core.analysis.architect_analysis._call_opus",
            new=AsyncMock(return_value=_FAKE_MARKDOWN),
        ),
        patch("core.analysis.architect_analysis.search_jurisprudences", new=jur_mock),
        patch("core.analysis.architect_analysis.search_recours", new=rec_mock),
    ):
        await run_architect_analysis(
            feasibility_summary=_FEASIBILITY_SUMMARY,
            zone_code="UB",
            commune_name="Vincennes",
            commune_insee="94078",
        )

    # search_jurisprudences must have been called with commune_insee
    jur_call_kwargs = jur_mock.call_args.kwargs
    assert jur_call_kwargs.get("commune_insee") == "94078"
    assert jur_call_kwargs.get("limit") == 5

    # search_recours must have been called with commune_insee
    rec_call_kwargs = rec_mock.call_args.kwargs
    assert rec_call_kwargs.get("commune_insee") == "94078"
    assert rec_call_kwargs.get("limit") == 3


async def test_no_commune_insee_skips_rag() -> None:
    """Without commune_insee, run_architect_analysis still returns markdown (no RAG error)."""
    from core.analysis.architect_analysis import run_architect_analysis

    with (
        patch(
            "core.analysis.architect_analysis._call_opus",
            new=AsyncMock(return_value=_FAKE_MARKDOWN),
        ),
        patch(
            "core.analysis.architect_analysis.search_jurisprudences",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "core.analysis.architect_analysis.search_recours",
            new=AsyncMock(return_value=[]),
        ),
    ):
        result = await run_architect_analysis(
            feasibility_summary=_FEASIBILITY_SUMMARY,
            zone_code="UA",
            commune_name="Paris 11e",
        )

    assert isinstance(result, str)


async def test_opus_called_with_system_and_user() -> None:
    """_call_opus is invoked with a non-empty system and user prompt."""
    from core.analysis.architect_analysis import run_architect_analysis

    opus_mock = AsyncMock(return_value=_FAKE_MARKDOWN)

    with (
        patch("core.analysis.architect_analysis._call_opus", new=opus_mock),
        patch(
            "core.analysis.architect_analysis.search_jurisprudences",
            new=AsyncMock(return_value=[]),
        ),
        patch(
            "core.analysis.architect_analysis.search_recours",
            new=AsyncMock(return_value=[]),
        ),
    ):
        await run_architect_analysis(
            feasibility_summary=_FEASIBILITY_SUMMARY,
            zone_code="UB",
            commune_name="Vincennes",
            commune_insee="94078",
        )

    assert opus_mock.called
    args = opus_mock.call_args
    system_arg = args.args[0] if args.args else args.kwargs.get("system")
    user_arg = args.args[1] if len(args.args) > 1 else args.kwargs.get("user")
    assert system_arg and len(system_arg) > 50
    assert user_arg and len(user_arg) > 50
