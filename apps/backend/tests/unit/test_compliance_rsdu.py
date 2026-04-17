"""Unit tests for core.compliance.rsdu — RSDU IDF standard obligations."""

from __future__ import annotations

from core.compliance.rsdu import compute_rsdu_obligations


def test_always_returns_obligations() -> None:
    """Always returns a non-empty list of obligations."""
    obligations = compute_rsdu_obligations()
    assert isinstance(obligations, list)
    assert len(obligations) > 0


def test_contains_velo() -> None:
    """List includes a vélo/bike parking obligation."""
    obligations = compute_rsdu_obligations()
    lower = [o.lower() for o in obligations]
    assert any("vél" in o or "velo" in o or "vélo" in o for o in lower)


def test_contains_poubelles() -> None:
    """List includes a waste sorting obligation."""
    obligations = compute_rsdu_obligations()
    lower = [o.lower() for o in obligations]
    assert any("poubell" in o or "tri" in o or "déchet" in o for o in lower)


def test_contains_vmc() -> None:
    """List includes VMC ventilation obligation."""
    obligations = compute_rsdu_obligations()
    lower = [o.lower() for o in obligations]
    assert any("vmc" in o or "ventilation" in o for o in lower)


def test_contains_garde_corps() -> None:
    """List includes garde-corps/balcon safety obligation."""
    obligations = compute_rsdu_obligations()
    lower = [o.lower() for o in obligations]
    assert any("garde" in o or "balcon" in o for o in lower)


def test_returns_exactly_4_obligations() -> None:
    """Standard RSDU IDF list has exactly 4 obligations."""
    obligations = compute_rsdu_obligations()
    assert len(obligations) == 4


def test_all_strings() -> None:
    """All obligations are non-empty strings."""
    for o in compute_rsdu_obligations():
        assert isinstance(o, str)
        assert len(o.strip()) > 0
