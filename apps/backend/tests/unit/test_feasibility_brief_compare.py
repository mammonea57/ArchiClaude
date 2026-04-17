"""Unit tests for core.feasibility.brief_compare — gap analysis brief vs regulatory max."""

from __future__ import annotations

import pytest

from core.feasibility.brief_compare import classify_ratio, compare_brief_to_max
from core.feasibility.schemas import EcartItem


# ---------------------------------------------------------------------------
# classify_ratio
# ---------------------------------------------------------------------------


def test_classify_tres_sous_exploite() -> None:
    assert classify_ratio(0.50) == "tres_sous_exploite"


def test_classify_sous_exploite() -> None:
    assert classify_ratio(0.70) == "sous_exploite"


def test_classify_coherent() -> None:
    assert classify_ratio(0.92) == "coherent"


def test_classify_limite() -> None:
    assert classify_ratio(1.02) == "limite"


def test_classify_infaisable() -> None:
    assert classify_ratio(1.10) == "infaisable"


def test_classify_boundary_060() -> None:
    """Exactly 0.60 is sous_exploite (lower bound inclusive)."""
    assert classify_ratio(0.60) == "sous_exploite"


def test_classify_boundary_100() -> None:
    """Exactly 1.00 is limite (1.00-1.05 range)."""
    assert classify_ratio(1.00) == "limite"


def test_classify_boundary_105() -> None:
    """Exactly 1.05 is infaisable (> 1.05 threshold)."""
    assert classify_ratio(1.05) == "infaisable"


# ---------------------------------------------------------------------------
# compare_brief_to_max
# ---------------------------------------------------------------------------


def test_all_targets() -> None:
    """All four brief targets are present → four EcartItem entries."""
    result = compare_brief_to_max(
        brief_nb_logements=20,
        max_nb_logements=25,
        brief_sdp_m2=1500.0,
        max_sdp_m2=2000.0,
        brief_hauteur_niveaux=4,
        max_niveaux=5,
        brief_emprise_pct=60.0,
        max_emprise_pct=70.0,
    )
    assert set(result.keys()) == {"nb_logements", "sdp_m2", "hauteur_niveaux", "emprise_pct"}
    for key, item in result.items():
        assert isinstance(item, EcartItem)
        assert item.ratio > 0


def test_infaisable() -> None:
    """Brief exceeds max by more than 5 % → infaisable classification."""
    result = compare_brief_to_max(
        brief_nb_logements=30,
        max_nb_logements=25,
    )
    assert "nb_logements" in result
    assert result["nb_logements"].classification == "infaisable"
    assert result["nb_logements"].ratio == pytest.approx(30 / 25)


def test_none_skipped() -> None:
    """None brief values are not included in the output dict."""
    result = compare_brief_to_max(
        brief_nb_logements=None,
        max_nb_logements=25,
        brief_sdp_m2=1500.0,
        max_sdp_m2=2000.0,
    )
    assert "nb_logements" not in result
    assert "sdp_m2" in result


def test_zero_max_skipped() -> None:
    """max = 0 is skipped to avoid division by zero."""
    result = compare_brief_to_max(
        brief_nb_logements=20,
        max_nb_logements=0,
        brief_sdp_m2=1500.0,
        max_sdp_m2=2000.0,
    )
    assert "nb_logements" not in result
    assert "sdp_m2" in result


def test_ecart_item_fields() -> None:
    """EcartItem fields are correctly populated."""
    result = compare_brief_to_max(
        brief_sdp_m2=900.0,
        max_sdp_m2=1000.0,
    )
    item = result["sdp_m2"]
    assert item.target == "sdp_m2"
    assert item.brief_value == pytest.approx(900.0)
    assert item.max_value == pytest.approx(1000.0)
    assert item.ratio == pytest.approx(0.9)
    assert item.classification == "coherent"
    assert isinstance(item.commentaire, str)
    assert len(item.commentaire) > 0
