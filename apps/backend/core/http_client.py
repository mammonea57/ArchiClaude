"""Shared async HTTP client with retry logic.

A module-level singleton is managed via get_http_client() / close_http_client().
Call close_http_client() during application shutdown (lifespan handler).
"""

from __future__ import annotations

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=5.0, pool=5.0)

_client: httpx.AsyncClient | None = None


def get_http_client() -> httpx.AsyncClient:
    """Return the module-level singleton AsyncClient, creating it on first call."""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=DEFAULT_TIMEOUT)
    return _client


async def close_http_client() -> None:
    """Close the singleton client. Call from app lifespan shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, httpx.ConnectError | httpx.ReadTimeout)


@retry(
    retry=retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=10),
    reraise=True,
)
async def fetch_json(
    url: str,
    *,
    params: dict[str, str | int | float] | None = None,
    timeout: httpx.Timeout | None = None,
) -> dict:  # type: ignore[type-arg]
    """GET request that returns parsed JSON. Retries on ConnectError / ReadTimeout.

    Raises:
        httpx.HTTPStatusError: on non-2xx responses.
    """
    client = get_http_client()
    response = await client.get(url, params=params, timeout=timeout or DEFAULT_TIMEOUT)
    response.raise_for_status()
    return response.json()  # type: ignore[no-any-return]


@retry(
    retry=retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=0.5, min=0.5, max=10),
    reraise=True,
)
async def post_json(
    url: str,
    *,
    json_body: dict | None = None,  # type: ignore[type-arg]
    params: dict[str, str | int | float] | None = None,
) -> dict:  # type: ignore[type-arg]
    """POST request that returns parsed JSON. Retries on ConnectError / ReadTimeout.

    Raises:
        httpx.HTTPStatusError: on non-2xx responses.
    """
    client = get_http_client()
    response = await client.post(url, json=json_body, params=params)
    response.raise_for_status()
    return response.json()  # type: ignore[no-any-return]
