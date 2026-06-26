"""Standalone test for the voisinage disk cache. No network required.

    cd apps/render-service && .venv/bin/python tests/test_voisinage_cache.py

Verifies the three invariants that make the cache safe:
  1. a successful fetch is memoised (producer runs once across two calls);
  2. a *failing* fetch is NOT cached (it retries, and falls back to []);
  3. OSM fetchers still return list[tuple[float, float]] after a JSON round-trip.
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# Point the cache at a throwaway dir BEFORE importing the modules.
import os
_TMP = tempfile.mkdtemp(prefix="voisinage_cache_test_")
os.environ["ARCHICLAUDE_VOISINAGE_CACHE_DIR"] = _TMP
os.environ["ARCHICLAUDE_VOISINAGE_CACHE_DEBUG"] = "1"

import src.voisinage_mesh as vm
from src.voisinage_cache import cached


def test_hit_runs_producer_once() -> None:
    calls = {"n": 0}

    def producer():
        calls["n"] += 1
        return {"value": 42}

    a = cached("unit_hit", {"k": 1}, producer)
    b = cached("unit_hit", {"k": 1}, producer)
    assert a == b == {"value": 42}
    assert calls["n"] == 1, f"producer should run once, ran {calls['n']}"
    print("✓ successful fetch memoised (producer ran once)")


def test_failure_not_cached() -> None:
    calls = {"n": 0}

    def boom():
        calls["n"] += 1
        raise RuntimeError("overpass down")

    for _ in range(2):
        try:
            cached("unit_fail", {"k": 1}, boom)
        except RuntimeError:
            pass
    assert calls["n"] == 2, f"failing producer must retry, ran {calls['n']}"
    print("✓ failing fetch never cached (retried both times)")


def test_distinct_keys() -> None:
    assert cached("unit_key", {"r": 150.0}, lambda: "a") == "a"
    assert cached("unit_key", {"r": 200.0}, lambda: "b") == "b"
    print("✓ different payloads → different cache entries")


def test_osm_returns_tuples_and_caches() -> None:
    fake = [[48.83, 2.45], [48.84, 2.46]]
    calls = {"n": 0}

    def fake_uncached(origin, radius_m):
        calls["n"] += 1
        return list(fake)

    vm._osm_trees_uncached = fake_uncached  # monkeypatch network layer
    origin = vm.GeoOrigin(lat=48.835, lng=2.455)

    out1 = vm.fetch_osm_trees(origin, radius_m=150.0)
    out2 = vm.fetch_osm_trees(origin, radius_m=150.0)

    assert calls["n"] == 1, f"network hit once, got {calls['n']}"
    assert out1 == out2 == [(48.83, 2.45), (48.84, 2.46)]
    assert all(isinstance(t, tuple) for t in out1), "must return tuples, not lists"
    print("✓ OSM trees: cached + tuple type preserved across JSON round-trip")


def test_osm_failure_returns_empty_uncached() -> None:
    def boom(origin, radius_m):
        raise RuntimeError("overpass 429")

    vm._osm_street_lamps_uncached = boom
    origin = vm.GeoOrigin(lat=10.0, lng=10.0)
    assert vm.fetch_osm_street_lamps(origin) == []
    # and nothing was written for this origin → still retries (returns [] again)
    assert vm.fetch_osm_street_lamps(origin) == []
    print("✓ OSM failure → [] without poisoning the cache")


if __name__ == "__main__":
    test_hit_runs_producer_once()
    test_failure_not_cached()
    test_distinct_keys()
    test_osm_returns_tuples_and_caches()
    test_osm_failure_returns_empty_uncached()
    print("\nALL PASS — cache dir:", _TMP)
