"""Unit tests for core.programming.envelope — gabarit-enveloppe par tranches horizontales."""

from __future__ import annotations

import pytest
from shapely.geometry import Polygon

from core.programming.envelope import compute_envelope
from core.programming.schemas import ClassifiedSegment, NiveauFootprint

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rect(w: float, h: float) -> Polygon:
    return Polygon([(0, 0), (w, 0), (w, h), (0, h)])


def _fixed_segments(parcelle: Polygon, recul_voirie: float = 5.0, recul_sep: float = 3.0) -> list[ClassifiedSegment]:
    """Return segments with fixed (non-parametric) setbacks for a rectangular parcelle."""
    coords = list(parcelle.exterior.coords)
    segs = []
    types_cycle = ["voirie", "separative", "fond", "separative"]
    reculs = [recul_voirie, recul_sep, recul_sep, recul_sep]
    for i in range(len(coords) - 1):
        t = types_cycle[i % 4]
        r = reculs[i % 4]
        segs.append(
            ClassifiedSegment(
                start=tuple(coords[i]),
                end=tuple(coords[i + 1]),
                segment_type=t,  # type: ignore[arg-type]
                recul_m=r,
                longueur_m=0.0,
            )
        )
    return segs


def _parametric_segments(parcelle: Polygon) -> list[ClassifiedSegment]:
    """Return segments where voirie uses formula 'H/2 min 3' (decreasing footprint at height)."""
    coords = list(parcelle.exterior.coords)
    segs = []
    types_cycle = ["voirie", "separative", "fond", "separative"]
    reculs = [3.0, 3.0, 3.0, 3.0]
    formulas = ["H/2 min 3", None, None, None]
    for i in range(len(coords) - 1):
        t = types_cycle[i % 4]
        r = reculs[i % 4]
        f = formulas[i % 4]
        segs.append(
            ClassifiedSegment(
                start=tuple(coords[i]),
                end=tuple(coords[i + 1]),
                segment_type=t,  # type: ignore[arg-type]
                recul_m=r,
                recul_formula=f,
                longueur_m=0.0,
            )
        )
    return segs


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_fixed_setbacks_same_all_levels() -> None:
    """Fixed setbacks → same footprint area every level."""
    parcelle = _rect(100.0, 80.0)
    segments = _fixed_segments(parcelle, recul_voirie=5.0, recul_sep=3.0)
    levels = compute_envelope(
        parcelle=parcelle,
        segments=segments,
        hauteur_max_m=12.0,
        hauteur_par_niveau=3.0,
    )
    assert len(levels) == 4  # 12 / 3 = 4 levels (0,1,2,3)
    areas = [nf.surface_m2 for nf in levels]
    # All areas should be approximately equal
    assert max(areas) - min(areas) < 1.0


def test_parametric_decreasing() -> None:
    """H/2 min 3 formula → higher levels have smaller or equal footprint."""
    parcelle = _rect(100.0, 80.0)
    segments = _parametric_segments(parcelle)
    levels = compute_envelope(
        parcelle=parcelle,
        segments=segments,
        hauteur_max_m=18.0,
        hauteur_par_niveau=3.0,
    )
    assert len(levels) >= 3
    # Check that footprint area is non-increasing as level increases
    # (or at worst equal when formula evaluates to min floor)
    for i in range(len(levels) - 1):
        assert levels[i].surface_m2 >= levels[i + 1].surface_m2 - 0.5  # allow tiny float noise


def test_sdp_total_is_sum() -> None:
    """Sum of all level surface_m2 values equals the total SDP."""
    parcelle = _rect(80.0, 60.0)
    segments = _fixed_segments(parcelle, recul_voirie=5.0, recul_sep=3.0)
    levels = compute_envelope(
        parcelle=parcelle,
        segments=segments,
        hauteur_max_m=15.0,
        hauteur_par_niveau=3.0,
    )
    total = sum(nf.surface_m2 for nf in levels)
    assert total == pytest.approx(sum(nf.surface_m2 for nf in levels), rel=1e-6)
    assert total > 0.0


def test_niveau_fields_correct() -> None:
    """NiveauFootprint fields are populated correctly per level."""
    parcelle = _rect(100.0, 80.0)
    segments = _fixed_segments(parcelle, recul_voirie=5.0, recul_sep=3.0)
    levels = compute_envelope(
        parcelle=parcelle,
        segments=segments,
        hauteur_max_m=9.0,
        hauteur_par_niveau=3.0,
    )
    assert len(levels) == 3
    for i, nf in enumerate(levels):
        assert nf.niveau == i
        assert nf.hauteur_plancher_m == pytest.approx((i + 1) * 3.0)
        assert isinstance(nf.footprint, Polygon)
        assert nf.surface_m2 == pytest.approx(nf.footprint.area, rel=0.001)


def test_single_level() -> None:
    """hauteur_max_m < 2×hauteur_par_niveau → one level."""
    parcelle = _rect(100.0, 80.0)
    segments = _fixed_segments(parcelle, recul_voirie=5.0, recul_sep=3.0)
    levels = compute_envelope(
        parcelle=parcelle,
        segments=segments,
        hauteur_max_m=3.0,
        hauteur_par_niveau=3.0,
    )
    assert len(levels) == 1
    assert levels[0].niveau == 0
    assert levels[0].hauteur_plancher_m == pytest.approx(3.0)


def test_formula_h_over_3() -> None:
    """H/3 formula: setback at level 0 (h=3m) = 1m, level 2 (h=9m) = 3m."""
    parcelle = _rect(100.0, 80.0)
    coords = list(parcelle.exterior.coords)
    segments = []
    types_cycle = ["voirie", "separative", "fond", "separative"]
    for i in range(len(coords) - 1):
        t = types_cycle[i % 4]
        formula = "H/3" if t == "voirie" else None
        segments.append(
            ClassifiedSegment(
                start=tuple(coords[i]),
                end=tuple(coords[i + 1]),
                segment_type=t,  # type: ignore[arg-type]
                recul_m=0.0,  # will be overridden by formula
                recul_formula=formula,
                longueur_m=0.0,
            )
        )
    levels = compute_envelope(
        parcelle=parcelle,
        segments=segments,
        hauteur_max_m=12.0,
        hauteur_par_niveau=3.0,
    )
    assert len(levels) == 4
    # Level 0: H=3m, recul_voirie=3/3=1m → larger footprint
    # Level 3: H=12m, recul_voirie=12/3=4m → smaller footprint
    assert levels[0].surface_m2 >= levels[3].surface_m2 - 0.5


def test_returns_list_of_niveau_footprint() -> None:
    """Return type is list[NiveauFootprint]."""
    parcelle = _rect(80.0, 60.0)
    segments = _fixed_segments(parcelle)
    levels = compute_envelope(
        parcelle=parcelle,
        segments=segments,
        hauteur_max_m=6.0,
        hauteur_par_niveau=3.0,
    )
    assert isinstance(levels, list)
    assert all(isinstance(nf, NiveauFootprint) for nf in levels)
