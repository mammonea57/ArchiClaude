"""Unit tests for core.programming.plans.renderer_svg — SVG canvas.

TDD: tests written before implementation.
"""

from __future__ import annotations

from core.programming.plans.renderer_svg import SvgCanvas

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _canvas() -> SvgCanvas:
    return SvgCanvas(width_mm=297, height_mm=210, scale=100)


# ---------------------------------------------------------------------------
# test_creates_valid_svg
# ---------------------------------------------------------------------------


class TestCreatesSvg:
    def test_creates_valid_svg(self) -> None:
        c = _canvas()
        out = c.to_string()
        assert "<svg" in out

    def test_svg_has_dimensions(self) -> None:
        c = _canvas()
        out = c.to_string()
        # width/height attributes present
        assert "297" in out
        assert "210" in out

    def test_svg_closes_tag(self) -> None:
        c = _canvas()
        out = c.to_string()
        assert "</svg>" in out


# ---------------------------------------------------------------------------
# test_draw_polygon
# ---------------------------------------------------------------------------


class TestDrawPolygon:
    def test_draw_polygon_emits_polygon_tag(self) -> None:
        c = _canvas()
        c.draw_polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        assert "<polygon" in c.to_string()

    def test_draw_polygon_coords_in_output(self) -> None:
        c = _canvas()
        c.draw_polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        out = c.to_string()
        assert "points=" in out

    def test_draw_polygon_custom_fill(self) -> None:
        c = _canvas()
        c.draw_polygon([(0, 0), (5, 0), (5, 5)], fill="#abc123")
        assert "#abc123" in c.to_string()

    def test_draw_polygon_custom_stroke(self) -> None:
        c = _canvas()
        c.draw_polygon([(0, 0), (5, 0), (5, 5)], stroke="#ff0000")
        assert "#ff0000" in c.to_string()


# ---------------------------------------------------------------------------
# test_draw_line
# ---------------------------------------------------------------------------


class TestDrawLine:
    def test_draw_line_emits_line_tag(self) -> None:
        c = _canvas()
        c.draw_line(0, 0, 10, 10)
        assert "<line" in c.to_string()

    def test_draw_line_has_coordinates(self) -> None:
        c = _canvas()
        c.draw_line(3.0, 4.0, 7.0, 8.0)
        out = c.to_string()
        assert "x1=" in out
        assert "y1=" in out

    def test_draw_line_dash_parameter(self) -> None:
        c = _canvas()
        c.draw_line(0, 0, 10, 10, dash="4 2")
        assert "stroke-dasharray" in c.to_string()


# ---------------------------------------------------------------------------
# test_draw_text
# ---------------------------------------------------------------------------


class TestDrawText:
    def test_draw_text_content_in_output(self) -> None:
        c = _canvas()
        c.draw_text(50, 50, "Séjour")
        assert "Séjour" in c.to_string()

    def test_draw_text_has_text_tag(self) -> None:
        c = _canvas()
        c.draw_text(10, 20, "Test")
        assert "<text" in c.to_string()

    def test_draw_text_font_size(self) -> None:
        c = _canvas()
        c.draw_text(10, 20, "X", font_size=12)
        assert "12" in c.to_string()


# ---------------------------------------------------------------------------
# test_draw_dimension
# ---------------------------------------------------------------------------


class TestDrawDimension:
    def test_draw_dimension_label_in_output(self) -> None:
        c = _canvas()
        c.draw_dimension(0, 0, 10, 0, "5.00m")
        assert "5.00m" in c.to_string()

    def test_draw_dimension_emits_line_and_text(self) -> None:
        c = _canvas()
        c.draw_dimension(0, 0, 20, 0, "10m")
        out = c.to_string()
        assert "<line" in out
        assert "<text" in out


# ---------------------------------------------------------------------------
# test_draw_door
# ---------------------------------------------------------------------------


class TestDrawDoor:
    def test_draw_door_emits_path_or_arc(self) -> None:
        c = _canvas()
        c.draw_door(10, 10, width_m=0.90, direction="left")
        out = c.to_string()
        # Door arc rendered as <path> with arc command
        assert "<path" in out or "arc" in out.lower()

    def test_draw_door_with_right_direction(self) -> None:
        c = _canvas()
        c.draw_door(10, 10, width_m=0.90, direction="right")
        assert "<path" in c.to_string()


# ---------------------------------------------------------------------------
# test_draw_window
# ---------------------------------------------------------------------------


class TestDrawWindow:
    def test_draw_window_emits_element(self) -> None:
        c = _canvas()
        c.draw_window(20, 5, width_m=1.20)
        out = c.to_string()
        # Window may be lines or rect
        assert any(tag in out for tag in ["<line", "<rect", "<path"])


# ---------------------------------------------------------------------------
# test_draw_rect
# ---------------------------------------------------------------------------


class TestDrawRect:
    def test_draw_rect_emits_rect_tag(self) -> None:
        c = _canvas()
        c.draw_rect(5, 5, 20, 10)
        assert "<rect" in c.to_string()


# ---------------------------------------------------------------------------
# test_draw_north_arrow
# ---------------------------------------------------------------------------


class TestDrawNorthArrow:
    def test_draw_north_arrow_contains_N(self) -> None:
        c = _canvas()
        c.draw_north_arrow(250, 20, angle=0)
        assert "N" in c.to_string()


# ---------------------------------------------------------------------------
# test_layers_as_groups
# ---------------------------------------------------------------------------


class TestLayersAsGroups:
    def test_layer_creates_named_group(self) -> None:
        c = _canvas()
        c.draw_line(0, 0, 10, 10, layer="cotations")
        out = c.to_string()
        assert "<g" in out
        assert "cotations" in out

    def test_multiple_layers_create_multiple_groups(self) -> None:
        c = _canvas()
        c.draw_line(0, 0, 10, 10, layer="murs")
        c.draw_text(5, 5, "R+1", layer="textes")
        out = c.to_string()
        assert "murs" in out
        assert "textes" in out

    def test_elements_without_layer_go_to_default(self) -> None:
        c = _canvas()
        c.draw_line(0, 0, 5, 5)  # no layer
        out = c.to_string()
        assert "<line" in out

    def test_same_layer_elements_in_single_group(self) -> None:
        c = _canvas()
        c.draw_line(0, 0, 10, 0, layer="murs")
        c.draw_line(10, 0, 10, 10, layer="murs")
        out = c.to_string()
        # Should have exactly one group with id murs, not two
        assert out.count('id="murs"') == 1
