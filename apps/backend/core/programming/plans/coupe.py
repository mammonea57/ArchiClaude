"""Coupe (section) plan generator — all levels stacked vertically.

Shows height dimensions, NGF cotes, foundation schematic, acroterè.
"""

from __future__ import annotations

from core.programming.plans.renderer_dxf import DxfCanvas
from core.programming.plans.renderer_svg import SvgCanvas
from core.programming.schemas import NiveauFootprint

# Scale: 1m = _SCALE mm on drawing (1:100)
_SCALE = 10.0
_MARGIN = 20.0


def generate_coupe(
    *,
    footprints: list[NiveauFootprint],
    hauteur_par_niveau: float = 3.0,
    altitude_sol_m: float = 0.0,
    detail: str = "pc_norme",
    format: str = "svg",
) -> str | bytes:
    """Generate a section (coupe) plan.

    Parameters
    ----------
    footprints:
        List of NiveauFootprint (one per storey level), ordered bottom to top.
    hauteur_par_niveau:
        Floor-to-floor height in metres (default 3.0m).
    altitude_sol_m:
        NGF altitude of ground floor slab, for NGF cote annotations.
    detail:
        'schematique' | 'pc_norme' | 'execution'
    format:
        'svg' | 'dxf'
    """
    if format == "dxf":
        return _generate_dxf(footprints=footprints, hauteur_par_niveau=hauteur_par_niveau)
    return _generate_svg(
        footprints=footprints,
        hauteur_par_niveau=hauteur_par_niveau,
        altitude_sol_m=altitude_sol_m,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------


def _generate_svg(
    *,
    footprints: list[NiveauFootprint],
    hauteur_par_niveau: float,
    altitude_sol_m: float,
    detail: str,
) -> str:
    nb = len(footprints)
    total_height_m = nb * hauteur_par_niveau
    # Width from the widest footprint
    max_width_m = max(
        (fp.footprint.bounds[2] - fp.footprint.bounds[0]) for fp in footprints
    ) if footprints else 10.0

    canvas_w = max_width_m * _SCALE + 2 * _MARGIN + 40  # extra space for annotations
    canvas_h = (total_height_m + 3.0) * _SCALE + 2 * _MARGIN  # +3m for foundation + acroterè

    canvas = SvgCanvas(width_mm=canvas_w, height_mm=canvas_h)

    # Foundation base line y (SVG top-down)
    foundation_y = canvas_h - _MARGIN - 1.0 * _SCALE
    ground_y = canvas_h - _MARGIN - 1.5 * _SCALE  # ground slab

    # Foundation schematic (hatched box)
    canvas.draw_rect(
        _MARGIN, foundation_y,
        max_width_m * _SCALE, 1.0 * _SCALE,
        stroke="#000", fill="#d4d4d4", stroke_width=0.5, layer="fondation"
    )
    canvas.draw_text(
        _MARGIN + max_width_m * _SCALE / 2,
        foundation_y + 0.6 * _SCALE,
        "Fondation",
        font_size=7, layer="textes"
    )

    # Draw each level from bottom to top
    for i, fp in enumerate(footprints):
        level_bottom_y = ground_y - i * hauteur_par_niveau * _SCALE
        level_top_y = level_bottom_y - hauteur_par_niveau * _SCALE
        fp_width_m = fp.footprint.bounds[2] - fp.footprint.bounds[0]

        # Center the footprint
        offset_x = _MARGIN + (max_width_m - fp_width_m) * _SCALE / 2

        # Floor slab
        canvas.draw_rect(
            offset_x, level_bottom_y - 0.25 * _SCALE,
            fp_width_m * _SCALE, 0.25 * _SCALE,
            stroke="#000", fill="#888", stroke_width=0.35, layer="dalles"
        )

        # Wall outlines for the level
        canvas.draw_rect(
            offset_x, level_top_y,
            fp_width_m * _SCALE, hauteur_par_niveau * _SCALE,
            stroke="#000", fill="none", stroke_width=0.5, layer="murs"
        )

        # Level label
        label = "RDC" if i == 0 else f"R+{i}"
        canvas.draw_text(
            offset_x - 10,
            (level_bottom_y + level_top_y) / 2,
            label,
            font_size=8, anchor="end", layer="textes"
        )

        # Height dimension
        dim_x = offset_x + fp_width_m * _SCALE + 8
        canvas.draw_dimension(
            dim_x, level_bottom_y,
            dim_x, level_top_y,
            f"{hauteur_par_niveau:.2f}m",
            offset=4, layer="cotations"
        )

        # NGF annotation
        if altitude_sol_m > 0 or i == 0:
            ngf = altitude_sol_m + i * hauteur_par_niveau
            canvas.draw_text(
                offset_x + fp_width_m * _SCALE + 30,
                level_bottom_y,
                f"NGF +{ngf:.2f}",
                font_size=7, anchor="start", layer="textes"
            )

    # Acroterè / faîtage at top
    top_level = len(footprints)
    acrotere_y = ground_y - top_level * hauteur_par_niveau * _SCALE
    fp_top = footprints[-1] if footprints else None
    if fp_top is not None:
        top_w = fp_top.footprint.bounds[2] - fp_top.footprint.bounds[0]
        offset_x = _MARGIN + (max_width_m - top_w) * _SCALE / 2
        canvas.draw_rect(
            offset_x, acrotere_y - 0.5 * _SCALE,
            top_w * _SCALE, 0.5 * _SCALE,
            stroke="#000", fill="#aaa", stroke_width=0.35, layer="acrotere"
        )
        canvas.draw_text(
            offset_x + top_w * _SCALE / 2,
            acrotere_y - 0.7 * _SCALE,
            "Acroterè",
            font_size=7, layer="textes"
        )

    # Title
    canvas.draw_text(
        canvas_w / 2, _MARGIN / 2,
        f"Coupe — {nb} niveaux × {hauteur_par_niveau:.1f}m",
        font_size=10, layer="textes"
    )

    return canvas.to_string()


# ---------------------------------------------------------------------------
# DXF
# ---------------------------------------------------------------------------


def _generate_dxf(
    *,
    footprints: list[NiveauFootprint],
    hauteur_par_niveau: float,
) -> bytes:
    canvas = DxfCanvas()

    max_width_m = max(
        (fp.footprint.bounds[2] - fp.footprint.bounds[0]) for fp in footprints
    ) if footprints else 10.0

    ground_y = 0.0
    for i, fp in enumerate(footprints):
        fp_width = fp.footprint.bounds[2] - fp.footprint.bounds[0]
        offset_x = (max_width_m - fp_width) / 2
        level_y = ground_y + i * hauteur_par_niveau

        canvas.draw_polygon(
            [
                (offset_x, level_y),
                (offset_x + fp_width, level_y),
                (offset_x + fp_width, level_y + hauteur_par_niveau),
                (offset_x, level_y + hauteur_par_niveau),
            ],
            layer="MURS_PORTEURS",
        )
        label = "RDC" if i == 0 else f"R+{i}"
        canvas.draw_text(offset_x - 2, level_y + hauteur_par_niveau / 2, label, layer="TEXTES")

    return canvas.to_bytes()
