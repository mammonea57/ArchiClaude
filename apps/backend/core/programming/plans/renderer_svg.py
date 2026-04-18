"""SVG rendering canvas for architectural plans.

Follows NF EN ISO 128 conventions as defined in core.drawing.conventions.
All coordinates are in millimetres (SVG user units = mm at 1:1 scale).
"""

from __future__ import annotations

import math
from typing import Any


class SvgCanvas:
    """A4-landscape SVG canvas with layer support for architectural plans."""

    def __init__(
        self,
        width_mm: float = 297,
        height_mm: float = 210,
        viewbox: str | None = None,
        scale: float = 100,
    ) -> None:
        """A4 landscape by default. viewbox auto-computed from content if None."""
        self._width_mm = width_mm
        self._height_mm = height_mm
        self._viewbox = viewbox
        self._scale = scale
        # Elements not assigned to a layer
        self._elements: list[str] = []
        # Layer name → list of element strings
        self._groups: dict[str, list[str]] = {}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _add(self, element: str, layer: str | None) -> None:
        if layer is None:
            self._elements.append(element)
        else:
            if layer not in self._groups:
                self._groups[layer] = []
            self._groups[layer].append(element)

    @staticmethod
    def _fmt(v: float) -> str:
        """Format a float to at most 4 decimal places, stripping trailing zeros."""
        return f"{v:.4f}".rstrip("0").rstrip(".")

    # ------------------------------------------------------------------
    # Drawing primitives
    # ------------------------------------------------------------------

    def draw_polygon(
        self,
        coords: list[tuple[float, float]],
        *,
        stroke: str = "#000",
        fill: str = "none",
        stroke_width: float = 0.5,
        layer: str | None = None,
    ) -> None:
        """Draw a closed polygon."""
        pts = " ".join(f"{self._fmt(x)},{self._fmt(y)}" for x, y in coords)
        elem = (
            f'<polygon points="{pts}" '
            f'stroke="{stroke}" fill="{fill}" '
            f'stroke-width="{self._fmt(stroke_width)}"/>'
        )
        self._add(elem, layer)

    def draw_line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        stroke: str = "#000",
        stroke_width: float = 0.5,
        dash: str | None = None,
        layer: str | None = None,
    ) -> None:
        """Draw a straight line."""
        dash_attr = f' stroke-dasharray="{dash}"' if dash else ""
        elem = (
            f'<line x1="{self._fmt(x1)}" y1="{self._fmt(y1)}" '
            f'x2="{self._fmt(x2)}" y2="{self._fmt(y2)}" '
            f'stroke="{stroke}" stroke-width="{self._fmt(stroke_width)}"{dash_attr}/>'
        )
        self._add(elem, layer)

    def draw_rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        *,
        stroke: str = "#000",
        fill: str = "none",
        stroke_width: float = 0.5,
        layer: str | None = None,
    ) -> None:
        """Draw an axis-aligned rectangle."""
        elem = (
            f'<rect x="{self._fmt(x)}" y="{self._fmt(y)}" '
            f'width="{self._fmt(w)}" height="{self._fmt(h)}" '
            f'stroke="{stroke}" fill="{fill}" '
            f'stroke-width="{self._fmt(stroke_width)}"/>'
        )
        self._add(elem, layer)

    def draw_text(
        self,
        x: float,
        y: float,
        text: str,
        *,
        font_size: float = 9,
        font_family: str = "Inter",
        anchor: str = "middle",
        layer: str | None = None,
    ) -> None:
        """Draw a text label."""
        elem = (
            f'<text x="{self._fmt(x)}" y="{self._fmt(y)}" '
            f'font-size="{self._fmt(font_size)}" font-family="{font_family}" '
            f'text-anchor="{anchor}">{text}</text>'
        )
        self._add(elem, layer)

    def draw_dimension(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        label: str,
        *,
        offset: float = 5,
        layer: str = "cotations",
    ) -> None:
        """Dimension line with arrows + text label above/beside."""
        # Midpoint for label
        mx = (x1 + x2) / 2
        my = (y1 + y2) / 2

        # Offset direction: perpendicular to the dimension line
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        if length > 0:
            # Perpendicular unit vector (90° rotation)
            px = -dy / length
            py = dx / length
        else:
            px, py = 0.0, -1.0

        # Offset start/end points
        ox1 = x1 + px * offset
        oy1 = y1 + py * offset
        ox2 = x2 + px * offset
        oy2 = y2 + py * offset
        lx = mx + px * (offset + 3)
        ly = my + py * (offset + 3)

        # Extension lines
        self.draw_line(x1, y1, ox1, oy1, stroke="#888", stroke_width=0.18, layer=layer)
        self.draw_line(x2, y2, ox2, oy2, stroke="#888", stroke_width=0.18, layer=layer)
        # Dimension line
        self.draw_line(ox1, oy1, ox2, oy2, stroke="#555", stroke_width=0.13, layer=layer)
        # Arrowheads (small triangles)
        if length > 0:
            ux = dx / length
            uy = dy / length
            arrow_len = 2.0
            arrow_w = 0.8
            for ax, ay, sign in [(ox1, oy1, 1), (ox2, oy2, -1)]:
                tip_x = ax
                tip_y = ay
                base_x = ax + sign * ux * arrow_len
                base_y = ay + sign * uy * arrow_len
                l_x = base_x + arrow_w * (-uy)
                l_y = base_y + arrow_w * ux
                r_x = base_x - arrow_w * (-uy)
                r_y = base_y - arrow_w * ux
                self.draw_polygon(
                    [(tip_x, tip_y), (l_x, l_y), (r_x, r_y)],
                    fill="#555",
                    stroke="#555",
                    stroke_width=0.05,
                    layer=layer,
                )
        # Label
        self.draw_text(lx, ly, label, font_size=7, layer=layer)

    def draw_door(
        self,
        x: float,
        y: float,
        width_m: float = 0.90,
        direction: str = "left",
        *,
        layer: str = "menuiseries",
    ) -> None:
        """Door arc symbol (quarter-circle sweep)."""
        # Width in mm at drawing scale (1m = scale mm)
        r = width_m * self._scale
        # Arc: from hinge point, sweep 90°
        # direction "left": arc goes left, "right": arc goes right
        if direction == "right":
            # Hinge at (x, y), door opens to the right
            end_x = x + r
            end_y = y
            arc_x = x
            arc_y = y - r
            d = (
                f"M {self._fmt(x)},{self._fmt(y)} "
                f"L {self._fmt(end_x)},{self._fmt(end_y)} "
                f"A {self._fmt(r)},{self._fmt(r)} 0 0 0 "
                f"{self._fmt(arc_x)},{self._fmt(arc_y)} Z"
            )
        else:
            # Hinge at (x, y), door opens to the left
            end_x = x - r
            end_y = y
            arc_x = x
            arc_y = y - r
            d = (
                f"M {self._fmt(x)},{self._fmt(y)} "
                f"L {self._fmt(end_x)},{self._fmt(end_y)} "
                f"A {self._fmt(r)},{self._fmt(r)} 0 0 1 "
                f"{self._fmt(arc_x)},{self._fmt(arc_y)} Z"
            )
        elem = f'<path d="{d}" stroke="#000" fill="none" stroke-width="0.25"/>'
        self._add(elem, layer)

    def draw_window(
        self,
        x: float,
        y: float,
        width_m: float = 1.20,
        *,
        layer: str = "menuiseries",
    ) -> None:
        """Window symbol on wall: three parallel lines."""
        w = width_m * self._scale
        depth = 3.0  # mm symbol depth
        # Outer lines
        self.draw_line(x, y, x + w, y, stroke="#000", stroke_width=0.25, layer=layer)
        self.draw_line(x, y + depth, x + w, y + depth, stroke="#000", stroke_width=0.25, layer=layer)
        # Glass line in middle
        self.draw_line(
            x, y + depth / 2, x + w, y + depth / 2,
            stroke="#000", stroke_width=0.13, layer=layer
        )

    def draw_north_arrow(
        self,
        x: float,
        y: float,
        angle: float = 0,
    ) -> None:
        """North arrow symbol with 'N' label."""
        r = 8.0  # radius in mm
        rad = math.radians(angle)
        # Arrow tip (north)
        tip_x = x + r * math.sin(rad)
        tip_y = y - r * math.cos(rad)
        # Arrow tail
        tail_x = x - r * 0.6 * math.sin(rad)
        tail_y = y + r * 0.6 * math.cos(rad)
        # Arrowhead wings
        perp_rad = math.radians(angle + 90)
        wing_w = 2.5
        lw_x = x + wing_w * math.sin(perp_rad)
        lw_y = y - wing_w * math.cos(perp_rad)
        rw_x = x - wing_w * math.sin(perp_rad)
        rw_y = y + wing_w * math.cos(perp_rad)

        # Draw filled arrowhead triangle
        self.draw_polygon(
            [(tip_x, tip_y), (lw_x, lw_y), (rw_x, rw_y)],
            stroke="#000",
            fill="#000",
            stroke_width=0.25,
        )
        # Draw shaft
        self.draw_line(tail_x, tail_y, x, y, stroke="#000", stroke_width=0.5)
        # Circle around center
        # Approximate circle with polygon (16-gon)
        circle_pts = [
            (x + r * 0.5 * math.cos(math.radians(i * 22.5)),
             y + r * 0.5 * math.sin(math.radians(i * 22.5)))
            for i in range(16)
        ]
        self.draw_polygon(circle_pts, stroke="#000", fill="none", stroke_width=0.25)
        # N label above arrow
        label_x = x + (r + 4) * math.sin(rad)
        label_y = y - (r + 4) * math.cos(rad)
        self.draw_text(label_x, label_y, "N", font_size=8, anchor="middle")

    def to_string(self) -> str:
        """Output complete SVG string with groups for layer toggling."""
        vb = self._viewbox or f"0 0 {self._fmt(self._width_mm)} {self._fmt(self._height_mm)}"
        lines: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'width="{self._fmt(self._width_mm)}mm" '
            f'height="{self._fmt(self._height_mm)}mm" '
            f'viewBox="{vb}">',
        ]
        # Default layer (no layer assigned)
        if self._elements:
            lines.append('<g id="default">')
            lines.extend(self._elements)
            lines.append("</g>")
        # Named layers as groups
        for layer_name, elements in self._groups.items():
            lines.append(f'<g id="{layer_name}">')
            lines.extend(elements)
            lines.append("</g>")
        lines.append("</svg>")
        return "\n".join(lines)
