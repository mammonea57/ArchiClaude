"""Unit tests for core.feasibility.capacity — capacity calculation pipeline."""

from __future__ import annotations

import math

import pytest

from core.feasibility.capacity import (
    CapacityResult,
    compute_capacity,
    compute_hauteur_retenue,
    compute_logements,
    compute_nb_niveaux,
    compute_sdp,
    compute_stationnement,
)

# ---------------------------------------------------------------------------
# compute_hauteur_retenue
# ---------------------------------------------------------------------------


def test_hauteur_min_constraints() -> None:
    """Returns the minimum of all provided constraints."""
    result = compute_hauteur_retenue(
        hauteur_max_m=12.0,
        niveaux_max=3,          # 3*3+0.5 = 9.5
        altitude_sol_m=None,
        hauteur_max_ngf=None,
    )
    assert result == pytest.approx(9.5)


def test_ngf_constraint() -> None:
    """NGF constraint limits height below hauteur_max_m."""
    result = compute_hauteur_retenue(
        hauteur_max_m=15.0,
        niveaux_max=None,
        altitude_sol_m=20.0,
        hauteur_max_ngf=30.0,   # effective = 30-20 = 10
    )
    assert result == pytest.approx(10.0)


def test_no_constraints() -> None:
    """With no constraints, returns a large sentinel (float inf or very large)."""
    result = compute_hauteur_retenue(
        hauteur_max_m=None,
        niveaux_max=None,
        altitude_sol_m=None,
        hauteur_max_ngf=None,
    )
    assert result == math.inf or result >= 1_000.0


def test_hauteur_max_m_only() -> None:
    result = compute_hauteur_retenue(
        hauteur_max_m=18.0,
        niveaux_max=None,
        altitude_sol_m=None,
        hauteur_max_ngf=None,
    )
    assert result == pytest.approx(18.0)


# ---------------------------------------------------------------------------
# compute_nb_niveaux
# ---------------------------------------------------------------------------


def test_nb_niveaux_15() -> None:
    assert compute_nb_niveaux(15.0) == 5


def test_nb_niveaux_12_5() -> None:
    assert compute_nb_niveaux(12.5) == 4


def test_nb_niveaux_3() -> None:
    assert compute_nb_niveaux(3.0) == 1


def test_nb_niveaux_zero() -> None:
    assert compute_nb_niveaux(0.0) == 0


# ---------------------------------------------------------------------------
# compute_sdp
# ---------------------------------------------------------------------------


def test_sdp_basic() -> None:
    """500 m² emprise × 4 niveaux = 2000 m², no PLU cap, no COS cap."""
    result = compute_sdp(
        surface_emprise_m2=500.0,
        nb_niveaux=4,
        sdp_max_plu=None,
        cos=None,
        surface_terrain_m2=1_000.0,
    )
    assert result == pytest.approx(2_000.0)


def test_capped_by_plu() -> None:
    """PLU cap of 1500 m² limits the result."""
    result = compute_sdp(
        surface_emprise_m2=500.0,
        nb_niveaux=4,
        sdp_max_plu=1_500.0,
        cos=None,
        surface_terrain_m2=1_000.0,
    )
    assert result == pytest.approx(1_500.0)


def test_capped_by_cos() -> None:
    """COS 1.5 × terrain 1000 m² = 1500 m², which is less than 2000."""
    result = compute_sdp(
        surface_emprise_m2=500.0,
        nb_niveaux=4,
        sdp_max_plu=None,
        cos=1.5,
        surface_terrain_m2=1_000.0,
    )
    assert result == pytest.approx(1_500.0)


# ---------------------------------------------------------------------------
# compute_logements
# ---------------------------------------------------------------------------


def test_logements_basic_mix() -> None:
    """Sum of nb_par_typo should equal total nb_logements."""
    mix = {"T2": 0.3, "T3": 0.4, "T4": 0.3}
    total, par_typo = compute_logements(sdp_m2=2_000.0, mix=mix)
    assert sum(par_typo.values()) == total
    assert total >= 0
    # With T2=45, T3=65, T4=82 → avg ≈ 45*0.3+65*0.4+82*0.3 = 13.5+26+24.6 = 64.1
    # → floor(2000/64.1) ≈ 31
    assert total > 0


def test_zero_sdp() -> None:
    """Zero SDP → zero logements."""
    total, par_typo = compute_logements(sdp_m2=0.0, mix={"T2": 0.5, "T3": 0.5})
    assert total == 0
    assert all(v == 0 for v in par_typo.values())


def test_logements_proportions() -> None:
    """Distribution respects mix (approximate due to flooring)."""
    mix = {"T2": 0.5, "T3": 0.5}
    total, par_typo = compute_logements(sdp_m2=5_000.0, mix=mix)
    # Each type should have roughly half
    assert abs(par_typo["T2"] - par_typo["T3"]) <= 2


# ---------------------------------------------------------------------------
# compute_stationnement
# ---------------------------------------------------------------------------


def test_stationnement_basic() -> None:
    """20 logements × 1.0 → 20 places, PMR = max(1, ceil(20*0.02)) = 1."""
    total, pmr = compute_stationnement(nb_logements=20, ratio_par_logement=1.0)
    assert total == 20
    assert pmr == 1


def test_stationnement_fractional() -> None:
    """25 × 0.5 = 12.5 → ceil = 13 places."""
    total, pmr = compute_stationnement(nb_logements=25, ratio_par_logement=0.5)
    assert total == 13


def test_stationnement_pmr_minimum() -> None:
    """PMR is always at least 1."""
    total, pmr = compute_stationnement(nb_logements=1, ratio_par_logement=1.0)
    assert pmr >= 1


def test_stationnement_large() -> None:
    """100 logements × 1.5 = 150 places, PMR = ceil(150*0.02) = 3."""
    total, pmr = compute_stationnement(nb_logements=100, ratio_par_logement=1.5)
    assert total == 150
    assert pmr == 3


# ---------------------------------------------------------------------------
# compute_capacity (full pipeline)
# ---------------------------------------------------------------------------


def test_full_pipeline() -> None:
    """End-to-end: produces CapacityResult with all expected fields."""
    result = compute_capacity(
        surface_emprise_m2=500.0,
        surface_terrain_m2=1_000.0,
        hauteur_max_m=15.0,
        niveaux_max=None,
        altitude_sol_m=None,
        hauteur_max_ngf=None,
        sdp_max_plu=None,
        cos=None,
        mix={"T2": 0.3, "T3": 0.4, "T4": 0.3},
        ratio_stationnement=1.0,
    )
    assert isinstance(result, CapacityResult)
    assert result.hauteur_retenue_m == pytest.approx(15.0)
    assert result.nb_niveaux == 5
    assert result.sdp_max_m2 == pytest.approx(2_500.0)  # 500*5
    assert result.nb_logements_max > 0
    assert sum(result.nb_par_typologie.values()) == result.nb_logements_max
    assert result.nb_places_stationnement >= 0
    assert result.nb_places_pmr >= 1
    assert isinstance(result.warnings, list)
    # Must include the indicative-values warning
    assert any("indicatives" in w for w in result.warnings)


def test_full_pipeline_zero_emprise() -> None:
    """Zero emprise → zero everything."""
    result = compute_capacity(
        surface_emprise_m2=0.0,
        surface_terrain_m2=1_000.0,
        hauteur_max_m=15.0,
        niveaux_max=None,
        altitude_sol_m=None,
        hauteur_max_ngf=None,
        sdp_max_plu=None,
        cos=None,
        mix={"T3": 1.0},
        ratio_stationnement=1.0,
    )
    assert result.sdp_max_m2 == 0.0
    assert result.nb_logements_max == 0
