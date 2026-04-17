"""Unit tests for core.compliance.re2020 — RE2020 environmental regulation."""

from __future__ import annotations

import pytest

from core.compliance.re2020 import estimate_re2020


def test_seuil_2022() -> None:
    """Année cible 2022 → seuil ic_construction ≤ 760."""
    ic_const, ic_ener, seuil, warnings = estimate_re2020(
        destination="logement_collectif",
        annee_cible=2022,
    )
    assert seuil == "2022"
    assert isinstance(warnings, list)


def test_seuil_2025() -> None:
    """Année cible 2025 → seuil label '2025'."""
    ic_const, ic_ener, seuil, warnings = estimate_re2020(
        destination="logement_collectif",
        annee_cible=2025,
    )
    assert seuil == "2025"


def test_seuil_2028() -> None:
    """Année cible 2028 → seuil label '2028'."""
    ic_const, ic_ener, seuil, warnings = estimate_re2020(
        destination="logement_collectif",
        annee_cible=2028,
    )
    assert seuil == "2028"


def test_seuil_2026_uses_2025_threshold() -> None:
    """Année 2026 (between 2025 and 2028) → seuil '2025'."""
    _, _, seuil, _ = estimate_re2020(
        destination="logement_collectif",
        annee_cible=2026,
    )
    assert seuil == "2025"


def test_always_has_warning() -> None:
    """Always includes a warning about BET thermique validation."""
    for year in [2022, 2025, 2028, 2030]:
        _, _, _, warnings = estimate_re2020(
            destination="logement_collectif",
            annee_cible=year,
        )
        assert len(warnings) > 0
        assert any("BET" in w or "thermique" in w.lower() or "affiner" in w.lower() for w in warnings)


def test_returns_none_or_float_for_ic_values() -> None:
    """IC values are either None or float (indicatif estimates)."""
    ic_const, ic_ener, _, _ = estimate_re2020(
        destination="logement_collectif",
        annee_cible=2025,
    )
    assert ic_const is None or isinstance(ic_const, float)
    assert ic_ener is None or isinstance(ic_ener, float)
