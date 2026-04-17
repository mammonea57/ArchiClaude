"""Unit tests for core.analysis.rag.jurisprudences."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from core.analysis.rag.jurisprudences import JurisprudenceMatch, search_jurisprudences

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_EMBEDDING = [0.0] * 1536


def _make_row(**kwargs) -> dict:  # type: ignore[type-arg]
    defaults: dict = {
        "id": str(uuid.uuid4()),
        "reference": "TA Paris 2023-001",
        "source": "Légifrance",
        "motif_principal": "Dépassement COS",
        "resume": "Le tribunal annule le permis en raison du dépassement du COS.",
        "decision": "Annulation",
        "commune_insee": "75056",
        "similarity": 0.87,
    }
    defaults.update(kwargs)
    return defaults


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_returns_matches() -> None:
    """search_jurisprudences maps DB rows to JurisprudenceMatch dataclasses."""
    row = _make_row()

    with (
        patch(
            "core.analysis.rag.jurisprudences.generate_embedding",
            new=AsyncMock(return_value=_FAKE_EMBEDDING),
        ),
        patch(
            "core.analysis.rag.jurisprudences._vector_search",
            new=AsyncMock(return_value=[row]),
        ),
    ):
        results = await search_jurisprudences(query="dépassement COS zone UB")

    assert len(results) == 1
    match = results[0]
    assert isinstance(match, JurisprudenceMatch)
    assert match.reference == "TA Paris 2023-001"
    assert match.source == "Légifrance"
    assert match.motif_principal == "Dépassement COS"
    assert match.decision == "Annulation"
    assert match.commune_insee == "75056"
    assert match.similarity == pytest.approx(0.87)


async def test_empty_query_returns_empty() -> None:
    """search_jurisprudences returns [] immediately for an empty query."""
    results = await search_jurisprudences(query="")
    assert results == []

    results = await search_jurisprudences(query="   ")
    assert results == []


async def test_no_embedding_returns_empty() -> None:
    """search_jurisprudences returns [] when the embedding call returns None."""
    with patch(
        "core.analysis.rag.jurisprudences.generate_embedding",
        new=AsyncMock(return_value=None),
    ):
        results = await search_jurisprudences(query="hauteur maximale")

    assert results == []


async def test_commune_filter_passed_to_search() -> None:
    """commune_insee is forwarded to _vector_search as-is."""
    captured: list = []

    async def _mock_vector_search(embedding, commune_insee, limit):  # type: ignore[override]
        captured.append(commune_insee)
        return []

    with (
        patch(
            "core.analysis.rag.jurisprudences.generate_embedding",
            new=AsyncMock(return_value=_FAKE_EMBEDDING),
        ),
        patch(
            "core.analysis.rag.jurisprudences._vector_search",
            side_effect=_mock_vector_search,
        ),
    ):
        await search_jurisprudences(query="recul voirie", commune_insee="92012")

    assert captured == ["92012"]


async def test_multiple_matches_preserve_order() -> None:
    """Multiple rows are mapped in order, preserving similarity ranking."""
    rows = [_make_row(reference=f"REF-{i}", similarity=0.9 - i * 0.1) for i in range(3)]

    with (
        patch(
            "core.analysis.rag.jurisprudences.generate_embedding",
            new=AsyncMock(return_value=_FAKE_EMBEDDING),
        ),
        patch(
            "core.analysis.rag.jurisprudences._vector_search",
            new=AsyncMock(return_value=rows),
        ),
    ):
        results = await search_jurisprudences(query="hauteur toiture", limit=3)

    assert len(results) == 3
    assert results[0].reference == "REF-0"
    assert results[0].similarity == pytest.approx(0.9)
    assert results[2].reference == "REF-2"
