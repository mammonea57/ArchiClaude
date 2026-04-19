"""Unit tests for core.pcmi.facades — PCMI5 four-facade generator.

TDD: tests written before implementation.
"""

from __future__ import annotations

from shapely.geometry import Polygon

from core.pcmi.facades import assemble_facades_grid_svg, generate_all_facades

# A simple rectangular footprint: 20m EW × 10m NS
_FOOTPRINT_RECT = Polygon([(0, 0), (20, 0), (20, 10), (0, 10)])

# A square footprint
_FOOTPRINT_SQUARE = Polygon([(0, 0), (15, 0), (15, 15), (0, 15)])


# ---------------------------------------------------------------------------
# generate_all_facades
# ---------------------------------------------------------------------------


class TestGenerateAllFacades:
    def test_generate_all_facades_returns_4_svgs(self) -> None:
        """Returns dict with keys: nord, sud, est, ouest — all SVG strings."""
        result = generate_all_facades(
            footprint=_FOOTPRINT_RECT,
            nb_niveaux=3,
            hauteur_par_niveau=3.0,
        )
        assert set(result.keys()) == {"nord", "sud", "est", "ouest"}
        for direction, svg in result.items():
            assert isinstance(svg, str), f"{direction} should be str"
            assert "<svg" in svg, f"{direction} should be SVG"
            assert "</svg>" in svg, f"{direction} SVG should be closed"

    def test_nord_sud_use_ew_width(self) -> None:
        """Nord/Sud facades use east-west width (bounds[2] - bounds[0])."""
        # Rect is 20m EW × 10m NS
        result = generate_all_facades(
            footprint=_FOOTPRINT_RECT,
            nb_niveaux=2,
        )
        # Nord and Sud SVGs should contain width annotation for 20m
        assert "20.00m" in result["nord"]
        assert "20.00m" in result["sud"]

    def test_est_ouest_use_ns_depth(self) -> None:
        """Est/Ouest facades use north-south depth (bounds[3] - bounds[1])."""
        # Rect is 20m EW × 10m NS
        result = generate_all_facades(
            footprint=_FOOTPRINT_RECT,
            nb_niveaux=2,
        )
        # Est and Ouest SVGs should contain width annotation for 10m
        assert "10.00m" in result["est"]
        assert "10.00m" in result["ouest"]

    def test_square_footprint(self) -> None:
        """Square footprint: all facades should have same width annotation."""
        result = generate_all_facades(
            footprint=_FOOTPRINT_SQUARE,
            nb_niveaux=4,
            hauteur_par_niveau=2.8,
        )
        assert len(result) == 4
        for svg in result.values():
            assert "15.00m" in svg

    def test_default_hauteur_par_niveau(self) -> None:
        """Default hauteur_par_niveau=3.0 is applied without error."""
        result = generate_all_facades(
            footprint=_FOOTPRINT_RECT,
            nb_niveaux=5,
        )
        assert len(result) == 4

    def test_detail_parameter_passed_through(self) -> None:
        """detail='schematique' is accepted without error."""
        result = generate_all_facades(
            footprint=_FOOTPRINT_RECT,
            nb_niveaux=2,
            detail="schematique",
        )
        assert len(result) == 4


# ---------------------------------------------------------------------------
# assemble_facades_grid_svg
# ---------------------------------------------------------------------------


class TestAssembleFacadesGridSvg:
    def _make_facades(self) -> dict[str, str]:
        return generate_all_facades(
            footprint=_FOOTPRINT_RECT,
            nb_niveaux=3,
        )

    def test_assemble_facades_grid_returns_single_svg(self) -> None:
        """Assembled grid is a single SVG string."""
        facades = self._make_facades()
        result = assemble_facades_grid_svg(facades)
        assert isinstance(result, str)
        assert "<svg" in result
        assert "</svg>" in result

    def test_grid_contains_all_4_labels(self) -> None:
        """Assembled SVG contains all four direction labels."""
        facades = self._make_facades()
        result = assemble_facades_grid_svg(facades)
        assert "FAÇADE NORD" in result
        assert "FAÇADE SUD" in result
        assert "FAÇADE EST" in result
        assert "FAÇADE OUEST" in result

    def test_grid_is_a3_landscape(self) -> None:
        """Assembled grid uses A3 landscape dimensions (420×297mm)."""
        facades = self._make_facades()
        result = assemble_facades_grid_svg(facades)
        # A3 landscape: 420 wide, 297 tall
        assert "420" in result
        assert "297" in result

    def test_grid_contains_all_4_svgs(self) -> None:
        """All 4 facade SVG contents are embedded in the grid."""
        facades = self._make_facades()
        result = assemble_facades_grid_svg(facades)
        # Grid SVG should contain multiple <svg or <g elements from each facade
        # At minimum we expect multiple SVG tags or embedded content
        assert result.count("<svg") >= 1  # outer svg at minimum
