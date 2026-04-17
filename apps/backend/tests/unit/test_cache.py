"""Unit tests for core.cache.RedisCache using fakeredis."""

from __future__ import annotations

import pytest
import fakeredis.aioredis

from core.cache import RedisCache


@pytest.fixture
async def redis():
    """Return a fresh FakeRedis instance per test."""
    r = await fakeredis.aioredis.FakeRedis()
    yield r
    await r.aclose()


@pytest.fixture
def cache(redis) -> RedisCache:
    return RedisCache(redis, prefix="test:")


# ---------------------------------------------------------------------------
# Basic get / set
# ---------------------------------------------------------------------------


async def test_get_miss(cache: RedisCache) -> None:
    result = await cache.get("nonexistent")
    assert result is None


async def test_set_and_get(cache: RedisCache) -> None:
    await cache.set("mykey", {"hello": "world"}, ttl_seconds=60)
    result = await cache.get("mykey")
    assert result == {"hello": "world"}


# ---------------------------------------------------------------------------
# Prefix isolation
# ---------------------------------------------------------------------------


async def test_prefix_isolation(redis) -> None:
    cache_a = RedisCache(redis, prefix="ns_a:")
    cache_b = RedisCache(redis, prefix="ns_b:")

    await cache_a.set("k", "value_a", ttl_seconds=60)
    await cache_b.set("k", "value_b", ttl_seconds=60)

    assert await cache_a.get("k") == "value_a"
    assert await cache_b.get("k") == "value_b"


# ---------------------------------------------------------------------------
# get_or_fetch
# ---------------------------------------------------------------------------


async def test_get_or_fetch_cache_hit(cache: RedisCache) -> None:
    """When the key is already cached the fetcher should NOT be called."""
    called = {"count": 0}

    async def fetcher() -> str:
        called["count"] += 1
        return "fresh_value"

    await cache.set("hit_key", "cached_value", ttl_seconds=60)

    result = await cache.get_or_fetch("hit_key", fetcher(), ttl_seconds=60)
    assert result == "cached_value"
    assert called["count"] == 0


async def test_get_or_fetch_cache_miss(cache: RedisCache) -> None:
    """On a cache miss the fetcher is called and the result is stored."""
    called = {"count": 0}

    async def fetcher() -> dict:
        called["count"] += 1
        return {"computed": True}

    result = await cache.get_or_fetch("miss_key", fetcher(), ttl_seconds=60)
    assert result == {"computed": True}
    assert called["count"] == 1

    # Second call must hit the cache without calling fetcher again.
    async def fetcher2() -> dict:
        raise AssertionError("fetcher should not be called on second access")

    result2 = await cache.get_or_fetch("miss_key", fetcher2(), ttl_seconds=60)
    assert result2 == {"computed": True}
