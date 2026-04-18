"""Unit tests for core.analysis.risk_score."""

import pytest

from core.analysis.risk_score import compute_risk_score_calcule, compute_risk_score_final


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ZERO_KWARGS = dict(
    nb_recours_commune=0,
    nb_recours_500m=0,
    associations_actives=0,
    projet_depasse_gabarit=False,
    depassement_niveaux=0,
    abf_obligatoire=False,
    nb_conflits_vue=0,
)


def _calc(**overrides):
    kwargs = {**_ZERO_KWARGS, **overrides}
    return compute_risk_score_calcule(**kwargs)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_zero_risk():
    score, detail = _calc()
    assert score == 0
    assert all(v == 0 for v in detail.values())


def test_high_risk():
    # Many recours + gabarit overshoot + ABF + vue conflicts → should exceed 60
    score, _ = _calc(
        nb_recours_commune=10,
        nb_recours_500m=3,
        associations_actives=2,
        projet_depasse_gabarit=True,
        depassement_niveaux=3,
        abf_obligatoire=True,
        nb_conflits_vue=3,
    )
    assert 60 < score <= 100


def test_abf_adds_10():
    score_without, _ = _calc()
    score_with, detail = _calc(abf_obligatoire=True)
    assert detail["abf"] == 10
    assert score_with == score_without + 10


def test_vue_conflicts_points():
    # 3 conflicts → 3*15 = 45 pts
    score, detail = _calc(nb_conflits_vue=3)
    assert detail["vue_conflicts"] == 45
    assert score == 45


def test_vue_conflicts_capped():
    # 4 conflicts would be 60 but cap is 45
    _, detail = _calc(nb_conflits_vue=4)
    assert detail["vue_conflicts"] == 45


def test_weighted_average():
    # 40 calc + 60 opus → 0.4*40 + 0.6*60 = 16 + 36 = 52
    result = compute_risk_score_final(score_calcule=40, score_opus=60)
    assert result == 52


def test_opus_none_uses_calcule():
    result = compute_risk_score_final(score_calcule=75, score_opus=None)
    assert result == 75


def test_clamped_100():
    # Force a sum > 100 to verify cap
    score, _ = _calc(
        nb_recours_commune=100,
        nb_recours_500m=100,
        associations_actives=100,
        projet_depasse_gabarit=True,
        depassement_niveaux=100,
        abf_obligatoire=True,
        nb_conflits_vue=100,
    )
    assert score == 100


def test_final_score_clamped_100():
    result = compute_risk_score_final(score_calcule=100, score_opus=100)
    assert result == 100
