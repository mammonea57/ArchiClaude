"""Tests for core.feasibility.smart_margin — risk-based SDP margin calculator."""

import pytest

from core.feasibility.smart_margin import compute_smart_margin, SmartMarginResult


def test_very_safe_100pct():
    """Risk 10 → 100% margin."""
    result = compute_smart_margin(risk_score=10, sdp_max=1000.0)
    assert isinstance(result, SmartMarginResult)
    assert result.marge_pct == pytest.approx(100.0)
    assert result.sdp_recommandee == pytest.approx(1000.0)


def test_safe_98pct():
    """Risk 30 → 98% margin."""
    result = compute_smart_margin(risk_score=30, sdp_max=1000.0)
    assert result.marge_pct == pytest.approx(98.0)
    assert result.sdp_recommandee == pytest.approx(980.0)


def test_medium_97pct():
    """Risk 50 → 97% margin."""
    result = compute_smart_margin(risk_score=50, sdp_max=1000.0)
    assert result.marge_pct == pytest.approx(97.0)
    assert result.sdp_recommandee == pytest.approx(970.0)


def test_high_96pct():
    """Risk 70 → 96% margin."""
    result = compute_smart_margin(risk_score=70, sdp_max=1000.0)
    assert result.marge_pct == pytest.approx(96.0)
    assert result.sdp_recommandee == pytest.approx(960.0)


def test_very_high_still_96pct():
    """Risk 95 → still 96% (floor), NEVER below."""
    result = compute_smart_margin(risk_score=95, sdp_max=1000.0)
    assert result.marge_pct == pytest.approx(96.0)
    assert result.sdp_recommandee == pytest.approx(960.0)
    assert result.marge_pct >= 96.0


def test_floor_always_96():
    """Floor at 96% for all risk scores."""
    for score in [80, 90, 95, 100]:
        result = compute_smart_margin(risk_score=score, sdp_max=500.0)
        assert result.marge_pct >= 96.0, f"Margin below floor at risk={score}"


def test_comparables_boost():
    """Risk 50 but comparables at 99% → margin ≥ 98%."""
    result = compute_smart_margin(
        risk_score=50, sdp_max=1000.0, comparables_max_pct_accepted=99.0
    )
    assert result.marge_pct >= 98.0
    assert result.ajustement_comparables is True


def test_comparables_below_97_no_boost():
    """Comparables < 97% do not boost."""
    result = compute_smart_margin(
        risk_score=50, sdp_max=1000.0, comparables_max_pct_accepted=95.0
    )
    assert result.marge_pct == pytest.approx(97.0)
    assert result.ajustement_comparables is False


def test_comparables_exactly_97_boost():
    """Comparables exactly 97% → boost applied (>= 97)."""
    result = compute_smart_margin(
        risk_score=50, sdp_max=1000.0, comparables_max_pct_accepted=97.0
    )
    assert result.ajustement_comparables is True


def test_zero_sdp():
    result = compute_smart_margin(risk_score=30, sdp_max=0.0)
    assert result.sdp_recommandee == pytest.approx(0.0)


def test_sdp_recommandee_formula():
    """sdp_recommandee = sdp_max * marge_pct / 100."""
    result = compute_smart_margin(risk_score=30, sdp_max=500.0)
    expected = 500.0 * result.marge_pct / 100
    assert result.sdp_recommandee == pytest.approx(expected)


def test_result_has_sdp_max():
    result = compute_smart_margin(risk_score=20, sdp_max=750.0)
    assert result.sdp_max == pytest.approx(750.0)


def test_result_has_raison():
    result = compute_smart_margin(risk_score=20, sdp_max=750.0)
    assert isinstance(result.raison, str)
    assert len(result.raison) > 0


def test_no_comparables_no_adjustment():
    result = compute_smart_margin(risk_score=20, sdp_max=750.0, comparables_max_pct_accepted=None)
    assert result.ajustement_comparables is False


def test_result_is_dataclass():
    result = compute_smart_margin(risk_score=10, sdp_max=1000.0)
    assert isinstance(result, SmartMarginResult)
