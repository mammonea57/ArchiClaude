"""Unit tests for core.programming.plans.plan_masse — plan de masse generator.

TDD: tests written before implementation.
"""

from __future__ import annotations

from shapely.geometry import Polygon

from core.programming.plans.plan_masse import generate_plan_masse

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parcelle() -> Polygon:
    """20×30m rectangular plot."""
    return Polygon([(0, 0), (20, 0), (20, 30), (0, 30)])


def _footprint() -> Polygon:
    """10×15m building footprint with 5m setbacks on all sides."""
    return Polygon([(5, 5), (15, 5), (15, 25), (5, 25)])


# ---------------------------------------------------------------------------
# test_returns_svg
# ---------------------------------------------------------------------------


class TestReturnsSvg:
    def test_returns_svg_string(self) -> None:
        result = generate_plan_masse(
            parcelle=_parcelle(),
            footprint=_footprint(),
            voirie_name="Rue de la Paix",
            format="svg",
        )
        assert isinstance(result, str)
        assert "<svg" in result

    def test_voirie_name_in_output(self) -> None:
        result = generate_plan_masse(
            parcelle=_parcelle(),
            footprint=_footprint(),
            voirie_name="Avenue Montaigne",
            format="svg",
        )
        assert "Avenue Montaigne" in result

    def test_svg_closes_properly(self) -> None:
        result = generate_plan_masse(
            parcelle=_parcelle(),
            footprint=_footprint(),
            format="svg",
        )
        assert "</svg>" in result

    def test_emprise_annotation_in_output(self) -> None:
        result = generate_plan_masse(
            parcelle=_parcelle(),
            footprint=_footprint(),
            emprise_pct=25.0,
            format="svg",
        )
        assert "25" in result

    def test_pleine_terre_annotation_in_output(self) -> None:
        result = generate_plan_masse(
            parcelle=_parcelle(),
            footprint=_footprint(),
            surface_pleine_terre_m2=350.0,
            format="svg",
        )
        assert "350" in result


# ---------------------------------------------------------------------------
# test_contains_north_arrow
# ---------------------------------------------------------------------------


class TestNorthArrow:
    def test_north_arrow_N_in_svg(self) -> None:
        result = generate_plan_masse(
            parcelle=_parcelle(),
            footprint=_footprint(),
            format="svg",
        )
        assert "N" in result

    def test_north_angle_zero(self) -> None:
        result = generate_plan_masse(
            parcelle=_parcelle(),
            footprint=_footprint(),
            north_angle=0.0,
            format="svg",
        )
        assert "<svg" in result

    def test_north_angle_nonzero(self) -> None:
        result = generate_plan_masse(
            parcelle=_parcelle(),
            footprint=_footprint(),
            north_angle=45.0,
            format="svg",
        )
        assert "<svg" in result


# ---------------------------------------------------------------------------
# test_dxf_format
# ---------------------------------------------------------------------------


class TestDxfFormat:
    def test_returns_bytes_for_dxf(self) -> None:
        result = generate_plan_masse(
            parcelle=_parcelle(),
            footprint=_footprint(),
            format="dxf",
        )
        assert isinstance(result, bytes)
        assert len(result) > 0

    def test_dxf_contains_dxf_marker(self) -> None:
        result = generate_plan_masse(
            parcelle=_parcelle(),
            footprint=_footprint(),
            format="dxf",
        )
        assert isinstance(result, bytes)
        # DXF files contain group codes
        assert b"0\n" in result[:100] or b"0\r\n" in result[:100]


# ---------------------------------------------------------------------------
# test_geometry_in_output
# ---------------------------------------------------------------------------


class TestGeometry:
    def test_parcelle_outline_in_svg(self) -> None:
        result = generate_plan_masse(
            parcelle=_parcelle(),
            footprint=_footprint(),
            format="svg",
        )
        # Should contain polygon elements for parcelle and footprint
        assert "<polygon" in result or "<path" in result

    def test_footprint_drawn(self) -> None:
        result = generate_plan_masse(
            parcelle=_parcelle(),
            footprint=_footprint(),
            format="svg",
        )
        assert "<polygon" in result or "<path" in result
