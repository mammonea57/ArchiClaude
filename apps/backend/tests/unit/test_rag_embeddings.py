"""Unit tests for core.analysis.rag.embeddings."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_mock_client(vectors: list[list[float]]) -> MagicMock:
    """Build a minimal AsyncOpenAI mock that returns *vectors* from embeddings.create."""
    client = MagicMock()
    # Build response objects matching openai SDK shape
    data = [MagicMock(embedding=v) for v in vectors]
    response = MagicMock(data=data)
    client.embeddings.create = AsyncMock(return_value=response)
    return client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_returns_vector() -> None:
    """generate_embedding returns a 1536-dim list when the client succeeds."""
    expected = [0.1] * 1536
    mock_client = _make_mock_client([expected])

    with patch("core.analysis.rag.embeddings._get_client", return_value=mock_client):
        from core.analysis.rag.embeddings import generate_embedding

        result = await generate_embedding("hauteur maximale autorisée zone UB")

    assert result is not None
    assert len(result) == 1536
    assert result[0] == pytest.approx(0.1)


async def test_empty_text_returns_none() -> None:
    """generate_embedding returns None for empty or whitespace-only text."""
    from core.analysis.rag.embeddings import generate_embedding

    assert await generate_embedding("") is None
    assert await generate_embedding("   ") is None


async def test_no_key_returns_none() -> None:
    """generate_embedding returns None when no API key is configured."""
    with patch("core.analysis.rag.embeddings._get_client", return_value=None):
        from core.analysis.rag.embeddings import generate_embedding

        result = await generate_embedding("some text")

    assert result is None


async def test_batch_returns_list_of_vectors() -> None:
    """generate_embeddings_batch returns one embedding per non-empty input text."""
    vecs = [[float(i)] * 1536 for i in range(3)]
    mock_client = _make_mock_client(vecs)

    with patch("core.analysis.rag.embeddings._get_client", return_value=mock_client):
        from core.analysis.rag.embeddings import generate_embeddings_batch

        result = await generate_embeddings_batch(["a", "b", "c"])

    assert len(result) == 3
    assert result[0] == vecs[0]
    assert result[2] == vecs[2]


async def test_batch_empty_list_returns_empty() -> None:
    """generate_embeddings_batch returns [] for an all-empty input list."""
    from core.analysis.rag.embeddings import generate_embeddings_batch

    result = await generate_embeddings_batch(["", "  "])
    assert result == []


async def test_batch_no_key_returns_empty() -> None:
    """generate_embeddings_batch returns [] when no API key is configured."""
    with patch("core.analysis.rag.embeddings._get_client", return_value=None):
        from core.analysis.rag.embeddings import generate_embeddings_batch

        result = await generate_embeddings_batch(["some text", "other text"])

    assert result == []
