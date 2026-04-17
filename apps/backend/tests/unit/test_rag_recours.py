"""Unit tests for core.analysis.rag.recours."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from core.analysis.rag.recours import RecoursMatch, search_recours

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_EMBEDDING = [0.0] * 1536


def _make_row(**kwargs) -> dict:  # type: ignore[type-arg]
    defaults: dict = {
        "id": str(uuid.uuid4()),
        "commune_insee": "75056",
        "association": "SOS Paris Vert",
        "projet_conteste": "Tour de logements R+12 rue de la Paix",
        "motifs": ["hauteur excessive", "non-conformité PLU zone UA"],
        "resultat": "rejeté",
        "resume": "Le recours a été rejeté pour défaut d'intérêt à agir.",
        "similarity": 0.78,
    }
    defaults.update(kwargs)
    return defaults


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_returns_matches() -> None:
    """search_recours maps DB rows to RecoursMatch dataclasses."""
    row = _make_row()

    with (
        patch(
            "core.analysis.rag.recours.generate_embedding",
            new=AsyncMock(return_value=_FAKE_EMBEDDING),
        ),
        patch(
            "core.analysis.rag.recours._vector_search_recours",
            new=AsyncMock(return_value=[row]),
        ),
    ):
        results = await search_recours(commune_insee="75056")

    assert len(results) == 1
    match = results[0]
    assert isinstance(match, RecoursMatch)
    assert match.commune_insee == "75056"
    assert match.association == "SOS Paris Vert"
    assert match.motifs == ["hauteur excessive", "non-conformité PLU zone UA"]
    assert match.resultat == "rejeté"
    assert match.similarity == pytest.approx(0.78)


async def test_empty_commune_returns_empty() -> None:
    """search_recours returns [] immediately for an empty commune_insee."""
    results = await search_recours(commune_insee="")
    assert results == []

    results = await search_recours(commune_insee="   ")
    assert results == []


async def test_no_embedding_returns_empty() -> None:
    """search_recours returns [] when the embedding call returns None."""
    with patch(
        "core.analysis.rag.recours.generate_embedding",
        new=AsyncMock(return_value=None),
    ):
        results = await search_recours(commune_insee="92012")

    assert results == []


async def test_motifs_none_becomes_empty_list() -> None:
    """A row with motifs=None yields RecoursMatch.motifs == []."""
    row = _make_row(motifs=None)

    with (
        patch(
            "core.analysis.rag.recours.generate_embedding",
            new=AsyncMock(return_value=_FAKE_EMBEDDING),
        ),
        patch(
            "core.analysis.rag.recours._vector_search_recours",
            new=AsyncMock(return_value=[row]),
        ),
    ):
        results = await search_recours(commune_insee="75056")

    assert results[0].motifs == []


async def test_multiple_matches_preserve_order() -> None:
    """Multiple rows are mapped in order, preserving similarity ranking."""
    rows = [_make_row(id=str(uuid.uuid4()), similarity=0.9 - i * 0.1) for i in range(3)]

    with (
        patch(
            "core.analysis.rag.recours.generate_embedding",
            new=AsyncMock(return_value=_FAKE_EMBEDDING),
        ),
        patch(
            "core.analysis.rag.recours._vector_search_recours",
            new=AsyncMock(return_value=rows),
        ),
    ):
        results = await search_recours(commune_insee="93001", limit=3)

    assert len(results) == 3
    assert results[0].similarity == pytest.approx(0.9)
    assert results[2].similarity == pytest.approx(0.7)
