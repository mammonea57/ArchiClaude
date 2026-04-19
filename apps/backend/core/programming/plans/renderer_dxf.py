"""DXF rendering canvas for architectural plans via ezdxf.

Layers follow French PC dossier conventions.
"""

from __future__ import annotations

import io


class DxfCanvas:
    """DXF canvas with standard architectural layers."""

    STANDARD_LAYERS: list[str] = [
        "MURS_PORTEURS",
        "CLOISONS",
        "COTATIONS",
        "MENUISERIES",
        "TEXTES",
        "CIRCULATION",
        "MOBILIER",
    ]

    def __init__(self) -> None:
        import ezdxf

        self._doc = ezdxf.new("R2010")
        self._msp = self._doc.modelspace()
        for layer in self.STANDARD_LAYERS:
            self._doc.layers.add(layer)

    # ------------------------------------------------------------------
    # Drawing primitives
    # ------------------------------------------------------------------

    def draw_polygon(
        self,
        coords: list[tuple[float, float]],
        *,
        layer: str = "MURS_PORTEURS",
    ) -> None:
        """Add a closed 2D polyline (LWPOLYLINE)."""
        points = list(coords)
        self._msp.add_lwpolyline(points, dxfattribs={"layer": layer, "closed": True})

    def draw_line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        layer: str = "MURS_PORTEURS",
    ) -> None:
        """Add a LINE entity."""
        self._msp.add_line(
            start=(x1, y1, 0),
            end=(x2, y2, 0),
            dxfattribs={"layer": layer},
        )

    def draw_text(
        self,
        x: float,
        y: float,
        text: str,
        *,
        height: float = 0.3,
        layer: str = "TEXTES",
    ) -> None:
        """Add a TEXT entity."""
        self._msp.add_text(
            text,
            dxfattribs={
                "insert": (x, y, 0),
                "height": height,
                "layer": layer,
            },
        )

    def draw_dimension(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        *,
        layer: str = "COTATIONS",
    ) -> None:
        """Add a horizontal/vertical aligned dimension entity."""
        import contextlib
        with contextlib.suppress(Exception):
            # Register dim style — silently ignored if already exists or unsupported
            self._doc.add_dimstyle("ARCHICLAUDE_DIM")
        # Fallback: represent dimension as a line + two short ticks
        self._msp.add_line(
            start=(x1, y1, 0),
            end=(x2, y2, 0),
            dxfattribs={"layer": layer},
        )
        # Extension tick at start
        self._msp.add_line(
            start=(x1, y1 - 0.1, 0),
            end=(x1, y1 + 0.1, 0),
            dxfattribs={"layer": layer},
        )
        # Extension tick at end
        self._msp.add_line(
            start=(x2, y2 - 0.1, 0),
            end=(x2, y2 + 0.1, 0),
            dxfattribs={"layer": layer},
        )

    # ------------------------------------------------------------------
    # Output
    # ------------------------------------------------------------------

    def get_layers(self) -> list[str]:
        """Return list of layer names (excluding default '0')."""
        return [
            layer.dxf.name
            for layer in self._doc.layers
            if layer.dxf.name != "0" and layer.dxf.name != "Defpoints"
        ]

    def to_bytes(self) -> bytes:
        """Serialize DXF document to bytes."""
        stream = io.StringIO()
        self._doc.write(stream)
        return stream.getvalue().encode("utf-8")
