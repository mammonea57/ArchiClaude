#!/usr/bin/env python3
"""
ArchiClaude post-deployment smoke test.

Usage:
    python scripts/smoke_test.py [BASE_URL]

Defaults to http://localhost:8000 if no BASE_URL is provided.
Exits 0 if all tests pass, 1 if any fail.
"""
from __future__ import annotations

import sys
import urllib.error
import urllib.request
from typing import NamedTuple


class Check(NamedTuple):
    label: str
    path: str


CHECKS: list[Check] = [
    Check("GET /api/v1/health", "/api/v1/health"),
    Check("GET /api/v1/parcels/search?q=Paris", "/api/v1/parcels/search?q=Paris"),
    Check("GET /api/v1/plu/at-point?lat=48.8566&lng=2.3522", "/api/v1/plu/at-point?lat=48.8566&lng=2.3522"),
    Check("GET /api/v1/site/bruit?lat=48.8566&lng=2.3522", "/api/v1/site/bruit?lat=48.8566&lng=2.3522"),
    Check("GET /api/v1/site/transports?lat=48.8566&lng=2.3522", "/api/v1/site/transports?lat=48.8566&lng=2.3522"),
    Check("GET /api/v1/projects", "/api/v1/projects"),
    Check("GET /api/v1/admin/feature-flags", "/api/v1/admin/feature-flags"),
    Check("GET /api/v1/rag/jurisprudences/search?q=hauteur", "/api/v1/rag/jurisprudences/search?q=hauteur"),
    Check("GET /api/v1/agency/settings", "/api/v1/agency/settings"),
]


def run_smoke_tests(base_url: str) -> bool:
    """Run all smoke tests. Returns True if all pass."""
    base_url = base_url.rstrip("/")
    all_passed = True
    col_width = max(len(c.label) for c in CHECKS) + 2

    print(f"\nArchiClaude smoke tests — {base_url}\n{'=' * 60}")

    for check in CHECKS:
        url = f"{base_url}{check.path}"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                status = resp.status
        except urllib.error.HTTPError as exc:
            status = exc.code
        except Exception as exc:
            print(f"  FAIL  {check.label:{col_width}}  ERROR: {exc}")
            all_passed = False
            continue

        if status == 200:
            print(f"  OK    {check.label}")
        else:
            print(f"  FAIL  {check.label:{col_width}}  HTTP {status}")
            all_passed = False

    print("=" * 60)
    if all_passed:
        print("All checks passed.\n")
    else:
        print("One or more checks failed.\n")

    return all_passed


if __name__ == "__main__":
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    success = run_smoke_tests(base_url)
    sys.exit(0 if success else 1)
