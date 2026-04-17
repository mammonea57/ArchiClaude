"""Unit tests for core.reports.versioning — version management."""

from __future__ import annotations

import pytest

from core.reports.versioning import build_version_diff, compute_next_version


# ---------------------------------------------------------------------------
# compute_next_version
# ---------------------------------------------------------------------------


def test_first_version() -> None:
    assert compute_next_version([]) == 1


def test_increment() -> None:
    assert compute_next_version([1, 2, 3]) == 4


def test_increment_non_sequential() -> None:
    # max + 1 regardless of gaps
    assert compute_next_version([1, 5, 3]) == 6


def test_increment_single() -> None:
    assert compute_next_version([7]) == 8


def test_increment_large() -> None:
    assert compute_next_version([1, 2, 100]) == 101


# ---------------------------------------------------------------------------
# build_version_diff
# ---------------------------------------------------------------------------


def test_sdp_change() -> None:
    v_old = {"sdp_brute_m2": 2000.0, "niveaux": 4, "commune": "Vincennes"}
    v_new = {"sdp_brute_m2": 2400.0, "niveaux": 4, "commune": "Vincennes"}
    diff = build_version_diff(v_old, v_new)
    assert "sdp_brute_m2" in diff
    assert diff["sdp_brute_m2"]["old"] == 2000.0
    assert diff["sdp_brute_m2"]["new"] == 2400.0
    # unchanged fields not in diff
    assert "niveaux" not in diff
    assert "commune" not in diff


def test_no_changes() -> None:
    v = {"sdp_brute_m2": 2000.0, "niveaux": 4}
    diff = build_version_diff(v, v)
    assert diff == {}


def test_new_field() -> None:
    v_old = {"sdp_brute_m2": 2000.0}
    v_new = {"sdp_brute_m2": 2000.0, "emprise_sol_m2": 400.0}
    diff = build_version_diff(v_old, v_new)
    assert "emprise_sol_m2" in diff
    assert diff["emprise_sol_m2"]["old"] is None
    assert diff["emprise_sol_m2"]["new"] == 400.0


def test_removed_field() -> None:
    v_old = {"sdp_brute_m2": 2000.0, "emprise_sol_m2": 400.0}
    v_new = {"sdp_brute_m2": 2000.0}
    diff = build_version_diff(v_old, v_new)
    assert "emprise_sol_m2" in diff
    assert diff["emprise_sol_m2"]["old"] == 400.0
    assert diff["emprise_sol_m2"]["new"] is None


def test_multiple_changes() -> None:
    v_old = {"a": 1, "b": 2, "c": 3}
    v_new = {"a": 10, "b": 2, "c": 30}
    diff = build_version_diff(v_old, v_new)
    assert set(diff.keys()) == {"a", "c"}
    assert diff["a"] == {"old": 1, "new": 10}
    assert diff["c"] == {"old": 3, "new": 30}


def test_returns_dict() -> None:
    diff = build_version_diff({}, {})
    assert isinstance(diff, dict)
