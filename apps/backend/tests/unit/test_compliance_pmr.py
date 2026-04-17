"""Unit tests for core.compliance.pmr — accessibility obligations."""

from __future__ import annotations

import math

import pytest

from core.compliance.pmr import compute_pmr


def test_ascenseur_r3_plus() -> None:
    """4 niveaux (R+3) → ascenseur obligatoire."""
    ascenseur, surface, nb_pmr = compute_pmr(
        nb_niveaux=4,
        nb_places=20,
        destination="logement_collectif",
    )
    assert ascenseur is True


def test_no_ascenseur_r2() -> None:
    """3 niveaux (R+2) → pas d'ascenseur obligatoire."""
    ascenseur, surface, nb_pmr = compute_pmr(
        nb_niveaux=3,
        nb_places=10,
        destination="logement_collectif",
    )
    assert ascenseur is False


def test_ascenseur_triggers_circulation_surface() -> None:
    """When ascenseur required, surface_circulations > 0."""
    ascenseur, surface, _ = compute_pmr(
        nb_niveaux=5,
        nb_places=20,
        destination="logement_collectif",
    )
    assert ascenseur is True
    assert surface > 0


def test_no_ascenseur_zero_surface() -> None:
    """When no ascenseur, circulation surface is 0."""
    _, surface, _ = compute_pmr(
        nb_niveaux=2,
        nb_places=10,
        destination="logement_collectif",
    )
    assert surface == pytest.approx(0.0)


def test_places_pmr_2pct() -> None:
    """nb_places_pmr = ceil(nb_places * 0.02)."""
    _, _, nb_pmr = compute_pmr(
        nb_niveaux=4,
        nb_places=100,
        destination="logement_collectif",
    )
    assert nb_pmr == math.ceil(100 * 0.02)


def test_places_pmr_minimum_1() -> None:
    """At least 1 PMR place when nb_places > 0."""
    _, _, nb_pmr = compute_pmr(
        nb_niveaux=4,
        nb_places=10,
        destination="logement_collectif",
    )
    assert nb_pmr >= 1


def test_zero_places() -> None:
    """Zero parking places → 0 PMR places."""
    _, _, nb_pmr = compute_pmr(
        nb_niveaux=4,
        nb_places=0,
        destination="logement_collectif",
    )
    assert nb_pmr == 0


def test_surface_circulations_15m2_per_niveau() -> None:
    """With ascenseur: ~15 m² per niveau."""
    nb_niveaux = 6
    _, surface, _ = compute_pmr(
        nb_niveaux=nb_niveaux,
        nb_places=20,
        destination="logement_collectif",
    )
    assert surface == pytest.approx(15.0 * nb_niveaux)
