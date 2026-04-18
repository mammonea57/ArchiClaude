"""Unit tests for core.programming.plans.renderer_dxf — DXF canvas.

TDD: tests written before implementation.
"""

from __future__ import annotations

from core.programming.plans.renderer_dxf import DxfCanvas

# ---------------------------------------------------------------------------
# test_creates_valid_dxf
# ---------------------------------------------------------------------------


class TestCreatesDxf:
    def test_to_bytes_returns_nonempty(self) -> None:
        c = DxfCanvas()
        data = c.to_bytes()
        assert isinstance(data, bytes)
        assert len(data) > 0

    def test_to_bytes_starts_with_dxf_marker(self) -> None:
        """DXF files start with '  0\nSECTION' or similar group codes."""
        c = DxfCanvas()
        data = c.to_bytes()
        # DXF starts with group code 0
        assert b"0\n" in data[:50] or b"  0\r\n" in data[:50] or b"0\r\n" in data[:50]


# ---------------------------------------------------------------------------
# test_has_standard_layers
# ---------------------------------------------------------------------------


class TestStandardLayers:
    def test_has_all_seven_layers(self) -> None:
        c = DxfCanvas()
        layers = c.get_layers()
        expected = {
            "MURS_PORTEURS",
            "CLOISONS",
            "COTATIONS",
            "MENUISERIES",
            "TEXTES",
            "CIRCULATION",
            "MOBILIER",
        }
        assert expected.issubset(set(layers))

    def test_get_layers_returns_list(self) -> None:
        c = DxfCanvas()
        assert isinstance(c.get_layers(), list)

    def test_layer_count_at_least_seven(self) -> None:
        c = DxfCanvas()
        assert len(c.get_layers()) >= 7


# ---------------------------------------------------------------------------
# test_draw_polygon
# ---------------------------------------------------------------------------


class TestDrawPolygon:
    def test_draw_polygon_adds_entity(self) -> None:
        c = DxfCanvas()
        c.draw_polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        data = c.to_bytes()
        # LWPOLYLINE is the DXF entity for 2D polylines
        assert b"LWPOLYLINE" in data or b"POLYLINE" in data

    def test_draw_polygon_on_custom_layer(self) -> None:
        c = DxfCanvas()
        c.draw_polygon([(0, 0), (5, 0), (5, 5)], layer="CLOISONS")
        data = c.to_bytes()
        assert b"CLOISONS" in data


# ---------------------------------------------------------------------------
# test_draw_line
# ---------------------------------------------------------------------------


class TestDrawLine:
    def test_draw_line_adds_line_entity(self) -> None:
        c = DxfCanvas()
        c.draw_line(0, 0, 10, 10)
        data = c.to_bytes()
        assert b"LINE" in data

    def test_draw_line_on_cotations_layer(self) -> None:
        c = DxfCanvas()
        c.draw_line(0, 0, 5, 5, layer="COTATIONS")
        data = c.to_bytes()
        assert b"COTATIONS" in data


# ---------------------------------------------------------------------------
# test_draw_text
# ---------------------------------------------------------------------------


class TestDrawText:
    def test_draw_text_adds_entity(self) -> None:
        c = DxfCanvas()
        c.draw_text(5, 5, "Séjour")
        data = c.to_bytes()
        # TEXT or MTEXT entity
        assert b"TEXT" in data or b"MTEXT" in data

    def test_draw_text_content_in_bytes(self) -> None:
        c = DxfCanvas()
        c.draw_text(0, 0, "T2-A")
        data = c.to_bytes()
        assert b"T2-A" in data

    def test_draw_text_on_textes_layer(self) -> None:
        c = DxfCanvas()
        c.draw_text(0, 0, "Hello", layer="TEXTES")
        data = c.to_bytes()
        assert b"TEXTES" in data


# ---------------------------------------------------------------------------
# test_draw_dimension
# ---------------------------------------------------------------------------


class TestDrawDimension:
    def test_draw_dimension_adds_entity(self) -> None:
        c = DxfCanvas()
        c.draw_dimension(0, 0, 10, 0)
        data = c.to_bytes()
        # DIMENSION entity or at least a LINE
        assert b"DIMENSION" in data or b"LINE" in data

    def test_draw_dimension_on_cotations_layer(self) -> None:
        c = DxfCanvas()
        c.draw_dimension(0, 0, 5, 0, layer="COTATIONS")
        data = c.to_bytes()
        assert b"COTATIONS" in data


# ---------------------------------------------------------------------------
# Multiple entities
# ---------------------------------------------------------------------------


class TestMultipleEntities:
    def test_multiple_draws_accumulate(self) -> None:
        c = DxfCanvas()
        c.draw_line(0, 0, 10, 0)
        c.draw_line(10, 0, 10, 10)
        c.draw_polygon([(0, 0), (10, 0), (10, 10)])
        c.draw_text(5, 5, "ok")
        data = c.to_bytes()
        assert len(data) > 200  # non-trivial content
