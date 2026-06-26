"""Disk cache for the voisinage network fetches (BAN geocode, BDTopo WFS,
OSM Overpass).

The voisinage of a parcelle is near-static : the neighbouring buildings,
streets, trees and street lamps around a project do not change between two
renders of the same project. Yet ``voisinage_mesh`` re-hits BAN / IGN WFS /
Overpass on *every* render request — 3-7 s of network latency per call, plus
the risk of an Overpass rate-limit failing a render outright.

This module memoises every successful response on disk under
``refs/cache/voisinage/<namespace>/`` for 30 days, mirroring the idiom already
used by ``apps/backend/core/sources/gpu_wfs.py``.

Design rule (important) : **only successful responses are cached.** The OSM
fetchers swallow transient Overpass failures and return ``[]``; if we cached
that empty result, a one-off network blip would make trees / lamps silently
disappear from renders for the whole TTL. So the producer must *raise* on
failure — the caller catches it and falls back to ``[]`` *outside* the cache,
leaving nothing written.

Cache can be disabled with ``ARCHICLAUDE_VOISINAGE_CACHE_DISABLE=1`` and made
verbose with ``ARCHICLAUDE_VOISINAGE_CACHE_DEBUG=1``.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path
from typing import Any, Callable

_DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[3] / "refs" / "cache" / "voisinage"
_CACHE_TTL_SECONDS = 30 * 24 * 3600  # 30 days — geo context is near-static


def _cache_dir() -> Path:
    """Cache root, overridable via env (tests / CI / ephemeral Modal FS)."""
    override = os.environ.get("ARCHICLAUDE_VOISINAGE_CACHE_DIR", "")
    return Path(override) if override else _DEFAULT_CACHE_DIR


def _disabled() -> bool:
    return os.environ.get("ARCHICLAUDE_VOISINAGE_CACHE_DISABLE", "") not in ("", "0", "false")


def _debug() -> bool:
    return os.environ.get("ARCHICLAUDE_VOISINAGE_CACHE_DEBUG", "") not in ("", "0", "false")


def _cache_path(namespace: str, payload: dict[str, Any]) -> Path:
    """Stable SHA-1 path for (namespace, payload). Floats are rounded so two
    geocodes that agree to ~1 mm hit the same entry."""
    rounded = {k: (round(v, 7) if isinstance(v, float) else v) for k, v in payload.items()}
    raw = json.dumps(rounded, sort_keys=True, separators=(",", ":"))
    key = hashlib.sha1(raw.encode("utf-8")).hexdigest()
    return _cache_dir() / namespace / f"{key}.json"


def cached(
    namespace: str,
    payload: dict[str, Any],
    producer: Callable[[], Any],
    *,
    ttl_s: int = _CACHE_TTL_SECONDS,
) -> Any:
    """Return ``producer()``'s JSON-serialisable result, memoised on disk.

    A fresh entry (age < ``ttl_s``) is returned without calling ``producer``.
    On a miss, ``producer`` is invoked; if it raises, the exception propagates
    and **nothing** is written (so failures are never cached). A successful
    result is written atomically.
    """
    if _disabled():
        return producer()

    path = _cache_path(namespace, payload)
    if path.exists() and (time.time() - path.stat().st_mtime) <= ttl_s:
        try:
            with path.open("r", encoding="utf-8") as fh:
                value = json.load(fh)
            if _debug():
                print(f"  [voisinage_cache] HIT  {namespace} {path.name}")
            return value
        except (OSError, json.JSONDecodeError):
            print(f"!! [voisinage_cache] corrupt entry {path} — refetching")

    value = producer()  # may raise → nothing cached

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(value, fh)
        tmp.replace(path)
        if _debug():
            print(f"  [voisinage_cache] MISS {namespace} {path.name} — wrote")
    except OSError as exc:  # cache write must never break a render
        print(f"!! [voisinage_cache] could not write {path}: {exc}")

    return value
