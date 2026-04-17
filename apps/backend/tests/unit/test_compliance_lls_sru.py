"""Unit tests for core.compliance.lls_sru — SRU law social housing obligations."""

from __future__ import annotations

import pytest

from core.compliance.lls_sru import compute_lls_obligation


def test_conforme_no_obligation() -> None:
    """Commune conforme → no obligation pct."""
    obligation, bonus, warnings = compute_lls_obligation(
        commune_statut="conforme",
        sdp_m2=2000.0,
        nb_logements=30,
    )
    assert obligation is None
    assert isinstance(warnings, list)


def test_non_soumise_no_obligation() -> None:
    """Commune non_soumise → no obligation."""
    obligation, bonus, warnings = compute_lls_obligation(
        commune_statut="non_soumise",
        sdp_m2=500.0,
        nb_logements=5,
    )
    assert obligation is None


def test_rattrapage_above_threshold() -> None:
    """Rattrapage + sdp > 800 → obligation applies."""
    obligation, bonus, warnings = compute_lls_obligation(
        commune_statut="rattrapage",
        sdp_m2=1000.0,
        nb_logements=15,
    )
    assert obligation is not None
    assert obligation > 0


def test_rattrapage_below_threshold_no_obligation() -> None:
    """Rattrapage but sdp ≤ 800 AND nb_logements ≤ 12 → no obligation."""
    obligation, bonus, warnings = compute_lls_obligation(
        commune_statut="rattrapage",
        sdp_m2=600.0,
        nb_logements=8,
    )
    assert obligation is None


def test_carencee() -> None:
    """Commune carencée → reinforced (higher) obligation."""
    obligation_rattrapage, _, _ = compute_lls_obligation(
        commune_statut="rattrapage",
        sdp_m2=2000.0,
        nb_logements=30,
    )
    obligation_carencee, _, _ = compute_lls_obligation(
        commune_statut="carencee",
        sdp_m2=2000.0,
        nb_logements=30,
    )
    assert obligation_carencee is not None
    assert obligation_rattrapage is not None
    assert obligation_carencee >= obligation_rattrapage


def test_bonus_constructibilite_returned() -> None:
    """bonus_constructibilite_pct is a float or None."""
    _, bonus, _ = compute_lls_obligation(
        commune_statut="rattrapage",
        sdp_m2=2000.0,
        nb_logements=30,
    )
    assert bonus is None or isinstance(bonus, float)


def test_warnings_are_list() -> None:
    """Warnings are always a list (may be empty)."""
    for statut in ["conforme", "rattrapage", "carencee", "non_soumise"]:
        _, _, warnings = compute_lls_obligation(
            commune_statut=statut,
            sdp_m2=1000.0,
            nb_logements=20,
        )
        assert isinstance(warnings, list)
