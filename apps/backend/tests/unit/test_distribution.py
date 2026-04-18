"""Unit tests for core.programming.distribution — interior layout module.

Tests follow TDD order: all written before implementation.
All geometries are synthetic in metric CRS.
"""

from __future__ import annotations

import pytest
from shapely.geometry import Polygon

from core.programming.distribution import (
    distribute_logements,
    place_noyaux,
    select_template,
)
from core.programming.schemas import (
    SURFACE_CENTRE,
    DistributionResult,
    NiveauFootprint,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rect(w: float, h: float) -> Polygon:
    return Polygon([(0, 0), (w, 0), (w, h), (0, h)])


def _niveau_footprint(w: float, h: float, niveau: int = 0) -> NiveauFootprint:
    poly = _rect(w, h)
    return NiveauFootprint(
        niveau=niveau,
        hauteur_plancher_m=(niveau + 1) * 3.0,
        footprint=poly,
        surface_m2=poly.area,
    )


# ---------------------------------------------------------------------------
# test_select_template
# ---------------------------------------------------------------------------


class TestSelectTemplate:
    def test_compact_is_plot(self) -> None:
        """A near-square footprint → 'plot'."""
        poly = _rect(20.0, 18.0)  # ratio ~1.1
        assert select_template(poly) == "plot"

    def test_elongated_is_barre_simple(self) -> None:
        """Ratio 2–3.5 → 'barre_simple'."""
        poly = _rect(40.0, 15.0)  # ratio ~2.67
        assert select_template(poly) == "barre_simple"

    def test_very_long_is_barre_double(self) -> None:
        """Ratio > 3.5 → 'barre_double'."""
        poly = _rect(80.0, 15.0)  # ratio ~5.3
        assert select_template(poly) == "barre_double"

    def test_exact_ratio_35_is_barre_double(self) -> None:
        """Ratio exactly 3.5 should NOT be barre_double (strictly >3.5 threshold)."""
        poly = _rect(35.0, 10.0)  # ratio = 3.5 exactly
        # At exactly 3.5, ratio > 3.5 is False → should be barre_simple
        assert select_template(poly) == "barre_simple"

    def test_square_is_plot(self) -> None:
        """Perfect square → 'plot'."""
        poly = _rect(20.0, 20.0)
        assert select_template(poly) == "plot"


# ---------------------------------------------------------------------------
# test_place_noyaux_single
# ---------------------------------------------------------------------------


class TestPlaceNoyaux:
    def test_plot_single_noyau(self) -> None:
        """plot template → 1 noyau at or near centroid."""
        poly = _rect(20.0, 18.0)
        noyaux = place_noyaux(poly, template="plot", nb_noyaux_requis=1)
        assert len(noyaux) == 1
        assert noyaux[0].surface_m2 == pytest.approx(35.0)

    def test_barre_simple_single_noyau(self) -> None:
        """barre_simple template → 1 noyau."""
        poly = _rect(40.0, 15.0)
        noyaux = place_noyaux(poly, template="barre_simple", nb_noyaux_requis=1)
        assert len(noyaux) == 1
        assert noyaux[0].surface_m2 == pytest.approx(35.0)

    def test_barre_double_two_noyaux(self) -> None:
        """barre_double template → 2 noyaux along long axis."""
        poly = _rect(80.0, 15.0)
        noyaux = place_noyaux(poly, template="barre_double", nb_noyaux_requis=2)
        assert len(noyaux) == 2
        for n in noyaux:
            assert n.surface_m2 == pytest.approx(35.0)

    def test_noyau_positions_differ_for_double(self) -> None:
        """Two noyaux in barre_double should be at different positions."""
        poly = _rect(80.0, 15.0)
        noyaux = place_noyaux(poly, template="barre_double", nb_noyaux_requis=2)
        p0 = (noyaux[0].position.x, noyaux[0].position.y)
        p1 = (noyaux[1].position.x, noyaux[1].position.y)
        dist = ((p0[0] - p1[0]) ** 2 + (p0[1] - p1[1]) ** 2) ** 0.5
        assert dist > 5.0  # must be significantly apart

    def test_noyau_ids_are_unique(self) -> None:
        """Each noyau has a unique id."""
        poly = _rect(80.0, 15.0)
        noyaux = place_noyaux(poly, template="barre_double", nb_noyaux_requis=2)
        ids = [n.id for n in noyaux]
        assert len(set(ids)) == len(ids)


# ---------------------------------------------------------------------------
# test_distribute_produces_logements
# ---------------------------------------------------------------------------


class TestDistributeLogements:
    def _run_distribution(
        self,
        *,
        w: float = 30.0,
        d: float = 20.0,
        nb_niveaux: int = 3,
        mix: dict[str, float] | None = None,
        nb_logements_total: int = 12,
        template: str = "barre_simple",
        nb_noyaux: int = 1,
        lls_pct: float = 0.0,
    ) -> DistributionResult:
        if mix is None:
            mix = {"T2": 0.3, "T3": 0.4, "T4": 0.3}
        niveaux = [_niveau_footprint(w, d, n) for n in range(nb_niveaux)]
        return distribute_logements(
            niveaux=niveaux,
            mix=mix,
            nb_logements_total=nb_logements_total,
            template=template,
            nb_noyaux=nb_noyaux,
            lls_pct=lls_pct,
        )

    def test_produces_logements(self) -> None:
        """Result contains logements and total > 0."""
        result = self._run_distribution()
        assert result.total_logements > 0
        all_logements = [lg for nv in result.niveaux for lg in nv.logements]
        assert len(all_logements) == result.total_logements

    def test_total_matches_request(self) -> None:
        """Total logements in result matches nb_logements_total."""
        result = self._run_distribution(nb_logements_total=9)
        assert result.total_logements == 9

    def test_niveaux_count(self) -> None:
        """Number of NiveauDistribution matches number of footprints."""
        result = self._run_distribution(nb_niveaux=3)
        assert len(result.niveaux) == 3

    def test_template_stored(self) -> None:
        """Template name is stored on result."""
        result = self._run_distribution(template="plot")
        assert result.template == "plot"


# ---------------------------------------------------------------------------
# test_coefficient_utile_reasonable
# ---------------------------------------------------------------------------


class TestCoefficientUtile:
    def test_between_60_and_95(self) -> None:
        """Coefficient utile must be between 0.6 and 0.95."""
        niveaux = [_niveau_footprint(30.0, 20.0, n) for n in range(3)]
        result = distribute_logements(
            niveaux=niveaux,
            mix={"T2": 0.3, "T3": 0.4, "T4": 0.3},
            nb_logements_total=12,
            template="barre_simple",
            nb_noyaux=1,
        )
        assert 0.6 <= result.coefficient_utile <= 0.95

    def test_total_utile_equals_sum_niveaux(self) -> None:
        """total_surface_utile_m2 equals sum across all NiveauDistribution."""
        niveaux = [_niveau_footprint(30.0, 20.0, n) for n in range(3)]
        result = distribute_logements(
            niveaux=niveaux,
            mix={"T2": 0.3, "T3": 0.4, "T4": 0.3},
            nb_logements_total=12,
            template="barre_simple",
            nb_noyaux=1,
        )
        assert result.total_surface_utile_m2 == pytest.approx(
            sum(nv.surface_utile_m2 for nv in result.niveaux), rel=0.001
        )


# ---------------------------------------------------------------------------
# test_lls_logements_marked
# ---------------------------------------------------------------------------


class TestLlsLogements:
    def test_25pct_lls_marked(self) -> None:
        """With lls_pct=25, approximately 25% of logements are marked est_lls=True."""
        niveaux = [_niveau_footprint(40.0, 20.0, n) for n in range(4)]
        result = distribute_logements(
            niveaux=niveaux,
            mix={"T2": 0.5, "T3": 0.5},
            nb_logements_total=20,
            template="barre_simple",
            nb_noyaux=1,
            lls_pct=25.0,
        )
        all_logements = [lg for nv in result.niveaux for lg in nv.logements]
        lls_count = sum(1 for lg in all_logements if lg.est_lls)
        # ~25% of 20 = 5; allow ±1 for rounding
        assert 4 <= lls_count <= 6

    def test_zero_lls_when_pct_zero(self) -> None:
        """With lls_pct=0, no logements marked as LLS."""
        niveaux = [_niveau_footprint(30.0, 20.0, n) for n in range(2)]
        result = distribute_logements(
            niveaux=niveaux,
            mix={"T2": 0.5, "T3": 0.5},
            nb_logements_total=8,
            template="barre_simple",
            nb_noyaux=1,
            lls_pct=0.0,
        )
        all_logements = [lg for nv in result.niveaux for lg in nv.logements]
        lls_count = sum(1 for lg in all_logements if lg.est_lls)
        assert lls_count == 0


# ---------------------------------------------------------------------------
# test_surface_within_target
# ---------------------------------------------------------------------------


class TestSurfaceTarget:
    def test_logement_surfaces_within_10pct_of_cible(self) -> None:
        """Each logement surface should be within ±10% of SURFACE_CENTRE for its type."""
        niveaux = [_niveau_footprint(40.0, 20.0, n) for n in range(3)]
        result = distribute_logements(
            niveaux=niveaux,
            mix={"T2": 0.4, "T3": 0.4, "T4": 0.2},
            nb_logements_total=12,
            template="barre_simple",
            nb_noyaux=1,
        )
        all_logements = [lg for nv in result.niveaux for lg in nv.logements]
        for lg in all_logements:
            cible = SURFACE_CENTRE.get(lg.typologie)
            if cible is not None:
                assert lg.surface_m2 >= cible * 0.9, (
                    f"{lg.typologie} surface {lg.surface_m2:.1f} m² < 90% of cible {cible}"
                )
                assert lg.surface_m2 <= cible * 1.10, (
                    f"{lg.typologie} surface {lg.surface_m2:.1f} m² > 110% of cible {cible}"
                )

    def test_all_logements_have_pieces(self) -> None:
        """Each logement must have at least one piece."""
        niveaux = [_niveau_footprint(30.0, 20.0, n) for n in range(2)]
        result = distribute_logements(
            niveaux=niveaux,
            mix={"T2": 0.5, "T3": 0.5},
            nb_logements_total=6,
            template="barre_simple",
            nb_noyaux=1,
        )
        all_logements = [lg for nv in result.niveaux for lg in nv.logements]
        for lg in all_logements:
            assert len(lg.pieces) > 0, f"Logement {lg.id} has no pieces"

    def test_logement_has_geometry(self) -> None:
        """Each logement must have a valid (non-empty) Polygon geometry."""
        niveaux = [_niveau_footprint(30.0, 20.0, n) for n in range(2)]
        result = distribute_logements(
            niveaux=niveaux,
            mix={"T2": 0.5, "T3": 0.5},
            nb_logements_total=6,
            template="barre_simple",
            nb_noyaux=1,
        )
        all_logements = [lg for nv in result.niveaux for lg in nv.logements]
        for lg in all_logements:
            assert isinstance(lg.geometry, Polygon)
            assert not lg.geometry.is_empty
            assert lg.geometry.area > 0
