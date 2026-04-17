"""Unit tests for core.compliance.incendie — fire safety classification."""

from __future__ import annotations

import pytest

from core.compliance.incendie import classify_incendie


def test_1ere_individuel_r1() -> None:
    """Individuel ≤ R+1 (2 niveaux) → 1ère famille."""
    classement, coef = classify_incendie(
        hauteur_plancher_haut_m=5.0,
        nb_niveaux=2,
        destination="logement_individuel",
    )
    assert classement == "1ere"
    assert coef == pytest.approx(1.0)


def test_2eme_collectif_r3() -> None:
    """Collectif ≤ R+3 (plancher haut ≤ 8 m) → 2ème famille."""
    classement, coef = classify_incendie(
        hauteur_plancher_haut_m=8.0,
        nb_niveaux=4,
        destination="logement_collectif",
    )
    assert classement == "2eme"
    assert coef == pytest.approx(1.0)


def test_3a_collectif_below_28m() -> None:
    """Collectif plancher haut ≤ 28 m → 3A."""
    classement, coef = classify_incendie(
        hauteur_plancher_haut_m=20.0,
        nb_niveaux=7,
        destination="logement_collectif",
    )
    assert classement == "3A"
    assert coef == pytest.approx(1.0)


def test_4eme_28_to_50m() -> None:
    """Plancher haut between 28 m and 50 m → 4ème famille."""
    classement, coef = classify_incendie(
        hauteur_plancher_haut_m=35.0,
        nb_niveaux=12,
        destination="logement_collectif",
    )
    assert classement == "4eme"
    assert coef == pytest.approx(1.0)


def test_igh_above_50m() -> None:
    """Plancher haut > 50 m → IGH."""
    classement, coef = classify_incendie(
        hauteur_plancher_haut_m=55.0,
        nb_niveaux=18,
        destination="logement_collectif",
    )
    assert classement == "IGH"
    assert coef == pytest.approx(1.0)


def test_coef_always_1() -> None:
    """Coefficient is always 1.0 — unsourced, escalated to BET."""
    for h in [5.0, 15.0, 30.0, 55.0]:
        _, coef = classify_incendie(
            hauteur_plancher_haut_m=h,
            nb_niveaux=4,
            destination="logement_collectif",
        )
        assert coef == pytest.approx(1.0)


def test_2eme_individuel_r2_r3() -> None:
    """Individuel R+2 to R+3 → 2ème famille."""
    classement, _ = classify_incendie(
        hauteur_plancher_haut_m=7.0,
        nb_niveaux=3,
        destination="logement_individuel",
    )
    assert classement == "2eme"
