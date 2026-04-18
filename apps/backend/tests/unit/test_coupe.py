"""Unit tests for core.programming.plans.coupe — section plan generator.

TDD: tests written before implementation.
"""

from __future__ import annotations

import pytest
from shapely.geometry import Polygon

from core.programming.schemas import NiveauFootprint
from core.programming.plans.coupe import generate_coupe


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _rect(w: float, h: float) -> Polygon:
    return Polygon([(0, 0), (w, 0), (w, h), (0, h)])


def _footprints(n: int = 3, width: float = 20.0) -> list[NiveauFootprint]:
    return [
        NiveauFootprint(
            niveau=i,
            hauteur_plancher_m=i * 3.0,
            footprint=_rect(width, width * 0.5),
            surface_m2=width * width * 0.5,
        )
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# test_returns_svg
# ---------------------------------------------------------------------------


class TestReturnsSvg:
    def test_returns_svg_string(self) -> None:
        result = generate_coupe(footprints=_footprints(), format="svg")
        assert isinstance(result, str)
        assert "<svg" in result

    def test_svg_closes_properly(self) -> None:
        result = generate_coupe(footprints=_footprints(), format="svg")
        assert "</svg>" in result

    def test_returns_bytes_for_dxf(self) -> None:
        result = generate_coupe(footprints=_footprints(), format="dxf")
        assert isinstance(result, bytes)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# test_height_dimensions
# ---------------------------------------------------------------------------


class TestHeightDimensions:
    def test_hauteur_par_niveau_annotation_present(self) -> None:
        result = generate_coupe(
            footprints=_footprints(),
            hauteur_par_niveau=3.0,
            format="svg",
        )
        # Height annotation: 3.00 or 3.0 or "3m"
        assert "3" in result

    def test_ngf_annotation_when_altitude_provided(self) -> None:
        result = generate_coupe(
            footprints=_footprints(),
            hauteur_par_niveau=3.0,
            altitude_sol_m=42.5,
            format="svg",
        )
        assert "42" in result

    def test_single_level_works(self) -> None:
        result = generate_coupe(footprints=_footprints(n=1), format="svg")
        assert "<svg" in result

    def test_five_levels_works(self) -> None:
        result = generate_coupe(footprints=_footprints(n=5), format="svg")
        assert "<svg" in result


# ---------------------------------------------------------------------------
# test_structural_elements
# ---------------------------------------------------------------------------


class TestStructuralElements:
    def test_has_polygon_or_rect_for_levels(self) -> None:
        result = generate_coupe(footprints=_footprints(n=3), format="svg")
        assert "<polygon" in result or "<rect" in result or "<path" in result

    def test_has_text_elements(self) -> None:
        result = generate_coupe(footprints=_footprints(n=2), format="svg")
        assert "<text" in result
