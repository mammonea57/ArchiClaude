"""Unit tests for core.programming.solver — multi-scenario optimizer.

Tests follow TDD order: all written before implementation.
All geometries are synthetic rectangles in Lambert-93 (EPSG:2154, metric CRS).
"""

from __future__ import annotations

import pytest
from shapely.geometry import Polygon

from core.programming.schemas import NiveauFootprint, SolverResult, Scenario
from core.programming.solver import solve_scenarios


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rect_footprint(w: float, h: float, niveau: int = 0) -> NiveauFootprint:
    poly = Polygon([(0, 0), (w, 0), (w, h), (0, h)])
    return NiveauFootprint(
        niveau=niveau,
        hauteur_plancher_m=(niveau + 1) * 3.0,
        footprint=poly,
        surface_m2=poly.area,
    )


def _footprints_3_levels(w: float = 30.0, h: float = 20.0) -> list[NiveauFootprint]:
    """Three identical rectangular footprints — 600 m² per level."""
    return [_rect_footprint(w, h, n) for n in range(3)]


_MIX_BRIEF = {"T2": 0.3, "T3": 0.4, "T4": 0.3}


# ---------------------------------------------------------------------------
# test_returns_3_scenarios
# ---------------------------------------------------------------------------


def test_returns_3_scenarios() -> None:
    """solve_scenarios must return exactly three scenarios."""
    result = solve_scenarios(
        footprints=_footprints_3_levels(),
        surface_terrain_m2=800.0,
        mix_brief=_MIX_BRIEF,
        stationnement_par_logement=0.5,
        risk_score=30,
    )
    assert isinstance(result, SolverResult)
    assert len(result.scenarios) == 3
    noms = {s.nom for s in result.scenarios}
    assert noms == {"max_sdp", "max_logements", "max_confort"}


# ---------------------------------------------------------------------------
# test_max_sdp_uses_brief_mix
# ---------------------------------------------------------------------------


def test_max_sdp_uses_brief_mix() -> None:
    """max_sdp scenario must use the brief mix unchanged."""
    result = solve_scenarios(
        footprints=_footprints_3_levels(),
        surface_terrain_m2=800.0,
        mix_brief=_MIX_BRIEF,
        stationnement_par_logement=0.5,
        risk_score=20,
    )
    max_sdp = next(s for s in result.scenarios if s.nom == "max_sdp")
    assert max_sdp.mix_utilise == pytest.approx(_MIX_BRIEF)


# ---------------------------------------------------------------------------
# test_max_logements_more_units
# ---------------------------------------------------------------------------


def test_max_logements_more_units() -> None:
    """max_logements scenario must yield ≥ nb_logements of max_sdp."""
    result = solve_scenarios(
        footprints=_footprints_3_levels(),
        surface_terrain_m2=800.0,
        mix_brief=_MIX_BRIEF,
        stationnement_par_logement=0.5,
        risk_score=30,
    )
    max_sdp = next(s for s in result.scenarios if s.nom == "max_sdp")
    max_log = next(s for s in result.scenarios if s.nom == "max_logements")
    assert max_log.nb_logements >= max_sdp.nb_logements


# ---------------------------------------------------------------------------
# test_max_confort_fewer_units
# ---------------------------------------------------------------------------


def test_max_confort_fewer_units() -> None:
    """max_confort scenario must yield ≤ nb_logements of max_sdp."""
    result = solve_scenarios(
        footprints=_footprints_3_levels(),
        surface_terrain_m2=800.0,
        mix_brief=_MIX_BRIEF,
        stationnement_par_logement=0.5,
        risk_score=30,
    )
    max_sdp = next(s for s in result.scenarios if s.nom == "max_sdp")
    max_conf = next(s for s in result.scenarios if s.nom == "max_confort")
    assert max_conf.nb_logements <= max_sdp.nb_logements


# ---------------------------------------------------------------------------
# test_margin_applied
# ---------------------------------------------------------------------------


def test_margin_applied() -> None:
    """risk_score=50 → 97% margin applied to SDP."""
    footprints = _footprints_3_levels(30.0, 20.0)  # 600 m² per level, total brute 1800 m²
    result = solve_scenarios(
        footprints=footprints,
        surface_terrain_m2=800.0,
        mix_brief=_MIX_BRIEF,
        stationnement_par_logement=0.5,
        risk_score=50,
    )
    max_sdp = next(s for s in result.scenarios if s.nom == "max_sdp")
    expected_sdp = 1800.0 * 0.97
    assert max_sdp.sdp_m2 == pytest.approx(expected_sdp, rel=0.001)
    assert max_sdp.marge_pct == pytest.approx(97.0)


# ---------------------------------------------------------------------------
# test_lls_separate_access_variant
# ---------------------------------------------------------------------------


def test_lls_separate_access_variant() -> None:
    """With lls_obligatoire=True and small perte, variante_acces_separes=True."""
    # Large footprints so perte_sdp < 3% of sdp
    footprints = [_rect_footprint(80.0, 60.0, n) for n in range(4)]  # 4800 m² per level
    result = solve_scenarios(
        footprints=footprints,
        surface_terrain_m2=5000.0,
        mix_brief=_MIX_BRIEF,
        stationnement_par_logement=0.5,
        risk_score=20,
        lls_obligatoire=True,
    )
    # At least one scenario should have variante_acces_separes evaluated
    for s in result.scenarios:
        assert s.perte_sdp_acces_separes_m2 is not None
    # With a large SDP the perte should be < 3% → variante auto-recommended
    for s in result.scenarios:
        assert s.variante_acces_separes is True


def test_lls_separate_access_no_auto_when_large_perte() -> None:
    """With lls_obligatoire=True and large perte (>3%), variante_acces_separes=False."""
    # Tiny footprints so perte > 3% of sdp
    footprints = [_rect_footprint(8.0, 6.0, n) for n in range(2)]  # 48 m² per level
    result = solve_scenarios(
        footprints=footprints,
        surface_terrain_m2=100.0,
        mix_brief=_MIX_BRIEF,
        stationnement_par_logement=0.5,
        risk_score=20,
        lls_obligatoire=True,
    )
    for s in result.scenarios:
        assert s.variante_acces_separes is False


# ---------------------------------------------------------------------------
# test_mix_adjustments_populated
# ---------------------------------------------------------------------------


def test_mix_adjustments_populated() -> None:
    """max_logements and max_confort must have non-empty mix_ajustements."""
    result = solve_scenarios(
        footprints=_footprints_3_levels(),
        surface_terrain_m2=800.0,
        mix_brief=_MIX_BRIEF,
        stationnement_par_logement=0.5,
        risk_score=30,
    )
    for nom in ("max_logements", "max_confort"):
        s = next(sc for sc in result.scenarios if sc.nom == nom)
        assert len(s.mix_ajustements) > 0, f"mix_ajustements empty for {nom}"


# ---------------------------------------------------------------------------
# test_scenario_recommande_is_max_sdp
# ---------------------------------------------------------------------------


def test_scenario_recommande_is_max_sdp() -> None:
    """scenario_recommande should be 'max_sdp' by default."""
    result = solve_scenarios(
        footprints=_footprints_3_levels(),
        surface_terrain_m2=800.0,
        mix_brief=_MIX_BRIEF,
        stationnement_par_logement=0.5,
        risk_score=30,
    )
    assert result.scenario_recommande == "max_sdp"
    assert len(result.raison_recommandation) > 0


def test_scenario_recommande_high_risk_still_max_sdp() -> None:
    """Even with risk_score > 60, recommendation is max_sdp (but raison mentions risk)."""
    result = solve_scenarios(
        footprints=_footprints_3_levels(),
        surface_terrain_m2=800.0,
        mix_brief=_MIX_BRIEF,
        stationnement_par_logement=0.5,
        risk_score=75,
    )
    assert result.scenario_recommande == "max_sdp"
    assert "risque" in result.raison_recommandation.lower()


# ---------------------------------------------------------------------------
# test_stationnement_computed
# ---------------------------------------------------------------------------


def test_stationnement_computed() -> None:
    """All scenarios have stationnement computed from nb_logements × ratio."""
    result = solve_scenarios(
        footprints=_footprints_3_levels(),
        surface_terrain_m2=800.0,
        mix_brief=_MIX_BRIEF,
        stationnement_par_logement=1.0,
        risk_score=20,
    )
    for s in result.scenarios:
        assert s.nb_places_stationnement >= s.nb_logements
        assert s.nb_places_pmr >= 1


# ---------------------------------------------------------------------------
# test_nb_niveaux_correct
# ---------------------------------------------------------------------------


def test_nb_niveaux_correct() -> None:
    """nb_niveaux in each scenario matches the number of footprints."""
    footprints = _footprints_3_levels()
    result = solve_scenarios(
        footprints=footprints,
        surface_terrain_m2=800.0,
        mix_brief=_MIX_BRIEF,
        stationnement_par_logement=0.5,
        risk_score=20,
    )
    for s in result.scenarios:
        assert s.nb_niveaux == len(footprints)
        assert len(s.footprints_par_niveau) == len(footprints)


# ---------------------------------------------------------------------------
# test_mix_sums_to_one
# ---------------------------------------------------------------------------


def test_mix_sums_to_one() -> None:
    """All scenario mixes must sum to 1.0 (±0.01 tolerance)."""
    result = solve_scenarios(
        footprints=_footprints_3_levels(),
        surface_terrain_m2=800.0,
        mix_brief=_MIX_BRIEF,
        stationnement_par_logement=0.5,
        risk_score=30,
    )
    for s in result.scenarios:
        total = sum(s.mix_utilise.values())
        assert abs(total - 1.0) < 0.01, f"Mix sum {total} for {s.nom}"
