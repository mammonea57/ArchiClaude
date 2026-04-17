"""Unit tests for core.site.bruit — aggregated noise classification."""

from __future__ import annotations

import pytest

from core.site.bruit import BruitSiteResult, aggregate_bruit
from core.sources.bruitparif import BruitparifResult
from core.sources.cerema_bruit import ClassementSonore


def _cerema(categorie: int, lden: float | None = None) -> ClassementSonore:
    return ClassementSonore(
        categorie=categorie,
        type_infra="route",
        nom_voie="Test voie",
        lden=lden,
    )


def _bruitparif(lden: float) -> BruitparifResult:
    return BruitparifResult(
        lden=lden,
        lnight=None,
        source_type="routier",
        code_insee="75001",
    )


def test_cerema_only_cat3_isolation_required() -> None:
    """Cerema cat 3 → isolation_acoustique_obligatoire = True."""
    result = aggregate_bruit(cerema=[_cerema(3)], bruitparif=None)

    assert isinstance(result, BruitSiteResult)
    assert result.classement_sonore == 3
    assert result.source == "cerema"
    assert result.isolation_acoustique_obligatoire is True


def test_bruitparif_overrides_cerema() -> None:
    """Bruitparif lden=72 → cat 3, overrides cerema cat 4 → cat 3 wins (worse)."""
    result = aggregate_bruit(
        cerema=[_cerema(4)],
        bruitparif=_bruitparif(72.0),
    )

    assert result.classement_sonore == 3
    assert result.source == "bruitparif"
    assert result.isolation_acoustique_obligatoire is True
    assert result.lden_dominant == pytest.approx(72.0)


def test_cerema_wins_when_worse() -> None:
    """When Cerema is worse (lower category), it must be selected."""
    # Cerema cat 2 vs bruitparif lden=60 → cat 5
    result = aggregate_bruit(
        cerema=[_cerema(2)],
        bruitparif=_bruitparif(60.0),
    )

    assert result.classement_sonore == 2
    assert result.source == "cerema"
    assert result.isolation_acoustique_obligatoire is True


def test_no_data_returns_none() -> None:
    """No data → classement=None, isolation=False."""
    result = aggregate_bruit(cerema=[], bruitparif=None)

    assert result.classement_sonore is None
    assert result.source is None
    assert result.lden_dominant is None
    assert result.isolation_acoustique_obligatoire is False


def test_category_5_no_obligation() -> None:
    """Category 5 (quiet) → no acoustic insulation obligation."""
    result = aggregate_bruit(cerema=[_cerema(5)], bruitparif=None)

    assert result.classement_sonore == 5
    assert result.isolation_acoustique_obligatoire is False


def test_bruitparif_only() -> None:
    """Bruitparif alone (no Cerema data) is correctly handled."""
    result = aggregate_bruit(cerema=[], bruitparif=_bruitparif(78.0))

    # lden=78 → cat 2
    assert result.classement_sonore == 2
    assert result.source == "bruitparif"
    assert result.lden_dominant == pytest.approx(78.0)
    assert result.isolation_acoustique_obligatoire is True


def test_multiple_cerema_picks_worst() -> None:
    """Multiple Cerema segments → worst (lowest) category is selected."""
    result = aggregate_bruit(
        cerema=[_cerema(4), _cerema(2), _cerema(5)],
        bruitparif=None,
    )

    assert result.classement_sonore == 2
    assert result.isolation_acoustique_obligatoire is True


def test_equal_categories_combined_source() -> None:
    """Equal cat from cerema and bruitparif → source is 'cerema+bruitparif'."""
    # Cerema cat 3, bruitparif lden=70 → cat 3 (equal)
    result = aggregate_bruit(
        cerema=[_cerema(3)],
        bruitparif=_bruitparif(70.0),
    )

    assert result.classement_sonore == 3
    assert result.source == "cerema+bruitparif"
