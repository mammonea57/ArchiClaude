"""Unit tests for core.programming.plans.facade — facade plan generator.

TDD: tests written before implementation.
"""

from __future__ import annotations

from core.programming.plans.facade import generate_facade

# ---------------------------------------------------------------------------
# test_returns_svg
# ---------------------------------------------------------------------------


class TestReturnsSvg:
    def test_returns_svg_string(self) -> None:
        result = generate_facade(
            footprint_width_m=20.0,
            nb_niveaux=3,
            format="svg",
        )
        assert isinstance(result, str)
        assert "<svg" in result

    def test_svg_closes_properly(self) -> None:
        result = generate_facade(
            footprint_width_m=20.0,
            nb_niveaux=3,
            format="svg",
        )
        assert "</svg>" in result

    def test_returns_bytes_for_dxf(self) -> None:
        result = generate_facade(
            footprint_width_m=20.0,
            nb_niveaux=3,
            format="dxf",
        )
        assert isinstance(result, bytes)
        assert len(result) > 0


# ---------------------------------------------------------------------------
# test_height_annotations
# ---------------------------------------------------------------------------


class TestHeightAnnotations:
    def test_height_value_in_output(self) -> None:
        result = generate_facade(
            footprint_width_m=20.0,
            nb_niveaux=3,
            hauteur_par_niveau=3.0,
            format="svg",
        )
        assert "3" in result

    def test_total_height_annotation(self) -> None:
        result = generate_facade(
            footprint_width_m=20.0,
            nb_niveaux=4,
            hauteur_par_niveau=3.0,
            format="svg",
        )
        # total = 4 × 3 = 12m
        assert "12" in result

    def test_single_level_works(self) -> None:
        result = generate_facade(
            footprint_width_m=10.0,
            nb_niveaux=1,
            format="svg",
        )
        assert "<svg" in result


# ---------------------------------------------------------------------------
# test_fenestration
# ---------------------------------------------------------------------------


class TestFenestration:
    def test_with_fenestration_list(self) -> None:
        fenestration = [
            {"niveau": 0, "x_m": 3.0, "width_m": 1.5, "height_m": 1.2},
            {"niveau": 1, "x_m": 3.0, "width_m": 1.5, "height_m": 1.2},
        ]
        result = generate_facade(
            footprint_width_m=20.0,
            nb_niveaux=3,
            fenestration=fenestration,
            format="svg",
        )
        assert "<svg" in result

    def test_without_fenestration_still_works(self) -> None:
        result = generate_facade(
            footprint_width_m=15.0,
            nb_niveaux=2,
            fenestration=None,
            format="svg",
        )
        assert "<svg" in result


# ---------------------------------------------------------------------------
# test_building_outline
# ---------------------------------------------------------------------------


class TestBuildingOutline:
    def test_has_polygon_or_rect_for_building(self) -> None:
        result = generate_facade(
            footprint_width_m=20.0,
            nb_niveaux=3,
            format="svg",
        )
        assert "<polygon" in result or "<rect" in result or "<path" in result

    def test_has_text_for_annotations(self) -> None:
        result = generate_facade(
            footprint_width_m=20.0,
            nb_niveaux=3,
            format="svg",
        )
        assert "<text" in result
