"""Redis cache utility with cache-aside pattern.

Usage::

    from redis.asyncio import Redis
    from core.cache import RedisCache

    redis = Redis.from_url("redis://localhost:6379")
    cache = RedisCache(redis, prefix="ban:")

    result = await cache.get_or_fetch(
        "geocode:12-rue-de-la-paix",
        fetcher_coroutine=some_async_fn(),
        ttl_seconds=3600,
    )
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from redis.asyncio import Redis


class RedisCache:
    """Thin async Redis wrapper with JSON serialisation and prefix isolation."""

    def __init__(self, redis: Redis, prefix: str) -> None:  # type: ignore[type-arg]
        self._redis = redis
        self._prefix = prefix

    def _key(self, key: str) -> str:
        """Prepend the namespace prefix to *key*."""
        return f"{self._prefix}{key}"

    async def get(self, key: str) -> Any | None:
        """Return the cached value for *key*, or ``None`` on a miss."""
        raw = await self._redis.get(self._key(key))
        if raw is None:
            return None
        return json.loads(raw)

    async def set(self, key: str, value: Any, *, ttl_seconds: int) -> None:
        """Serialise *value* to JSON and store it with the given TTL."""
        await self._redis.set(self._key(key), json.dumps(value), ex=ttl_seconds)

    async def get_or_fetch(
        self,
        key: str,
        fetcher_coroutine: Coroutine[Any, Any, Any],
        *,
        ttl_seconds: int,
    ) -> Any:
        """Cache-aside: return cached value when present, otherwise await *fetcher_coroutine*,
        store the result, and return it.

        Args:
            key: Cache key (prefix will be prepended).
            fetcher_coroutine: An *already created* coroutine to await on a cache miss.
            ttl_seconds: TTL applied when writing a fresh value.

        Returns:
            The cached or freshly fetched value.
        """
        cached = await self.get(key)
        if cached is not None:
            fetcher_coroutine.close()  # avoid "coroutine was never awaited" warning
            return cached
        value = await fetcher_coroutine
        await self.set(key, value, ttl_seconds=ttl_seconds)
        return value
