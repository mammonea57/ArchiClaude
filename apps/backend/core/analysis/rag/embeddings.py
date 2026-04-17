"""Embedding generation for RAG — wraps OpenAI or Voyage AI text-embedding API."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
_EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL")  # override for Voyage AI
_OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
_VOYAGE_API_KEY = os.getenv("VOYAGE_API_KEY")


def _get_client():  # type: ignore[return]
    """Return an AsyncOpenAI client if a key is available, else None."""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        logger.warning("openai package not installed — embeddings disabled")
        return None

    api_key = _OPENAI_API_KEY or _VOYAGE_API_KEY
    if not api_key:
        return None

    kwargs: dict = {"api_key": api_key}
    if _EMBEDDING_BASE_URL:
        kwargs["base_url"] = _EMBEDDING_BASE_URL
    return AsyncOpenAI(**kwargs)


async def generate_embedding(text: str) -> list[float] | None:
    """Generate a 1536-dimensional embedding for *text*.

    Returns ``None`` if:
    - *text* is empty or whitespace-only
    - no API key is configured
    - the ``openai`` package is not installed
    """
    if not text or not text.strip():
        return None

    client = _get_client()
    if client is None:
        return None

    response = await client.embeddings.create(
        input=text,
        model=_EMBEDDING_MODEL,
    )
    return response.data[0].embedding


async def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a list of texts in a single API call.

    Filters out empty strings before sending. Returns an empty list if no
    API key is configured or the package is missing.
    """
    non_empty = [t for t in texts if t and t.strip()]
    if not non_empty:
        return []

    client = _get_client()
    if client is None:
        return []

    response = await client.embeddings.create(
        input=non_empty,
        model=_EMBEDDING_MODEL,
    )
    # Preserve original order as returned by API (already ordered)
    return [item.embedding for item in response.data]
