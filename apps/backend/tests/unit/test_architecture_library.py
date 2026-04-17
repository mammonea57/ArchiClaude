"""Unit tests for core.architecture.library — bibliothèque architecturale."""

from __future__ import annotations

import pytest

from core.architecture.library import (
    ASCENSEURS,
    CIRCULATIONS,
    EPAISSEURS_MUR,
    TRAMES_BA,
)


# ---------------------------------------------------------------------------
# TRAMES_BA
# ---------------------------------------------------------------------------


def test_trames_ba_required_keys() -> None:
    required = {"logement", "bureaux", "parking"}
    assert required.issubset(TRAMES_BA.keys())


def test_trames_ba_logement() -> None:
    assert TRAMES_BA["logement"] == pytest.approx(5.40)


def test_trames_ba_bureaux() -> None:
    assert TRAMES_BA["bureaux"] == pytest.approx(7.50)


def test_trames_ba_parking() -> None:
    assert TRAMES_BA["parking"] == pytest.approx(5.00)


def test_trames_ba_values_positive() -> None:
    for key, value in TRAMES_BA.items():
        assert value > 0, f"TRAMES_BA[{key!r}] must be positive, got {value}"


# ---------------------------------------------------------------------------
# EPAISSEURS_MUR
# ---------------------------------------------------------------------------


def test_epaisseurs_mur_required_keys() -> None:
    required = {"porteur", "facade_ite", "cloison"}
    assert required.issubset(EPAISSEURS_MUR.keys())


def test_epaisseurs_mur_porteur() -> None:
    assert EPAISSEURS_MUR["porteur"] == pytest.approx(0.20)


def test_epaisseurs_mur_facade_ite() -> None:
    assert EPAISSEURS_MUR["facade_ite"] == pytest.approx(0.38)


def test_epaisseurs_mur_cloison() -> None:
    assert EPAISSEURS_MUR["cloison"] == pytest.approx(0.07)


def test_epaisseurs_mur_values_positive() -> None:
    for key, value in EPAISSEURS_MUR.items():
        assert value > 0, f"EPAISSEURS_MUR[{key!r}] must be positive, got {value}"


# ---------------------------------------------------------------------------
# CIRCULATIONS
# ---------------------------------------------------------------------------


def test_circulations_required_keys() -> None:
    required = {"couloir_pmr", "escalier", "porte_pmr"}
    assert required.issubset(CIRCULATIONS.keys())


def test_circulations_couloir_pmr() -> None:
    assert CIRCULATIONS["couloir_pmr"] == pytest.approx(1.20)


def test_circulations_escalier() -> None:
    assert CIRCULATIONS["escalier"] == pytest.approx(1.00)


def test_circulations_porte_pmr() -> None:
    assert CIRCULATIONS["porte_pmr"] == pytest.approx(0.90)


def test_circulations_values_positive() -> None:
    for key, value in CIRCULATIONS.items():
        assert value > 0, f"CIRCULATIONS[{key!r}] must be positive, got {value}"


# ---------------------------------------------------------------------------
# ASCENSEURS
# ---------------------------------------------------------------------------


def test_ascenseurs_required_keys() -> None:
    required = {"gaine_m2", "cabine_pmr_largeur_m", "cabine_pmr_profondeur_m"}
    assert required.issubset(ASCENSEURS.keys())


def test_ascenseurs_gaine_m2() -> None:
    assert ASCENSEURS["gaine_m2"] == pytest.approx(4.0)


def test_ascenseurs_cabine_pmr_largeur_m() -> None:
    assert ASCENSEURS["cabine_pmr_largeur_m"] == pytest.approx(1.10)


def test_ascenseurs_cabine_pmr_profondeur_m() -> None:
    assert ASCENSEURS["cabine_pmr_profondeur_m"] == pytest.approx(1.40)


def test_ascenseurs_values_positive() -> None:
    for key, value in ASCENSEURS.items():
        assert value > 0, f"ASCENSEURS[{key!r}] must be positive, got {value}"
