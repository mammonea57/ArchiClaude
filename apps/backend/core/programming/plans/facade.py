"""Facade (elevation) plan generator — front elevation of the building.

Shows building outline, windows per level, height annotations, material legend.
"""

from __future__ import annotations

from core.programming.plans.renderer_dxf import DxfCanvas
from core.programming.plans.renderer_svg import SvgCanvas

# Scale: 1m = _SCALE mm on drawing (1:100)
_SCALE = 10.0
_MARGIN = 20.0


def generate_facade(
    *,
    footprint_width_m: float,
    nb_niveaux: int,
    hauteur_par_niveau: float = 3.0,
    fenestration: list[dict] | None = None,
    detail: str = "pc_norme",
    format: str = "svg",  # noqa: A002
) -> str | bytes:
    """Generate a facade (front elevation) plan.

    Parameters
    ----------
    footprint_width_m:
        Building facade width in metres.
    nb_niveaux:
        Number of storeys.
    hauteur_par_niveau:
        Floor-to-floor height in metres (default 3.0m).
    fenestration:
        List of window/door dicts: {niveau, x_m, width_m, height_m}.
        If None, a default grid of windows is generated.
    detail:
        'schematique' | 'pc_norme' | 'execution'
    format:
        'svg' | 'dxf'
    """
    if format == "dxf":
        return _generate_dxf(
            footprint_width_m=footprint_width_m,
            nb_niveaux=nb_niveaux,
            hauteur_par_niveau=hauteur_par_niveau,
            fenestration=fenestration,
        )
    return _generate_svg(
        footprint_width_m=footprint_width_m,
        nb_niveaux=nb_niveaux,
        hauteur_par_niveau=hauteur_par_niveau,
        fenestration=fenestration,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------


def _default_fenestration(
    footprint_width_m: float, nb_niveaux: int, hauteur_par_niveau: float
) -> list[dict]:
    """Generate a default window grid if none provided."""
    wins: list[dict] = []
    window_w = 1.2
    window_h = 1.2
    window_sill = 0.9  # sill height above floor
    # Number of windows per level based on width
    n_wins = max(1, int(footprint_width_m / 3.5))
    spacing = footprint_width_m / (n_wins + 1)
    for lvl in range(nb_niveaux):
        for i in range(n_wins):
            wins.append({
                "niveau": lvl,
                "x_m": spacing * (i + 1) - window_w / 2,
                "width_m": window_w,
                "height_m": window_h,
                "sill_m": window_sill,
            })
    return wins


def _generate_svg(
    *,
    footprint_width_m: float,
    nb_niveaux: int,
    hauteur_par_niveau: float,
    fenestration: list[dict] | None,
    detail: str,
) -> str:
    total_height_m = nb_niveaux * hauteur_par_niveau
    canvas_w = footprint_width_m * _SCALE + 2 * _MARGIN + 40
    canvas_h = total_height_m * _SCALE + 2 * _MARGIN + 20

    canvas = SvgCanvas(width_mm=canvas_w, height_mm=canvas_h)

    bldg_x = _MARGIN
    bldg_bottom_y = canvas_h - _MARGIN
    bldg_top_y = bldg_bottom_y - total_height_m * _SCALE
    bldg_w = footprint_width_m * _SCALE
    bldg_h = total_height_m * _SCALE

    # Building outline
    canvas.draw_rect(
        bldg_x, bldg_top_y,
        bldg_w, bldg_h,
        stroke="#000", fill="#f5f5f5", stroke_width=0.5, layer="batiment"
    )

    # Floor lines
    for i in range(1, nb_niveaux):
        floor_y = bldg_bottom_y - i * hauteur_par_niveau * _SCALE
        canvas.draw_line(
            bldg_x, floor_y,
            bldg_x + bldg_w, floor_y,
            stroke="#aaa", stroke_width=0.18, dash="4 2", layer="dalles"
        )
        label = "RDC" if i == 0 else f"R+{i}"
        canvas.draw_text(
            bldg_x - 5, floor_y,
            label,
            font_size=7, anchor="end", layer="textes"
        )

    # Ground line
    canvas.draw_line(
        bldg_x - 5, bldg_bottom_y,
        bldg_x + bldg_w + 5, bldg_bottom_y,
        stroke="#000", stroke_width=0.35, layer="terrain"
    )

    # Windows / fenestration
    wins = fenestration if fenestration is not None else _default_fenestration(
        footprint_width_m, nb_niveaux, hauteur_par_niveau
    )
    for win in wins:
        lvl = win.get("niveau", 0)
        wx_m = win.get("x_m", 1.0)
        ww_m = win.get("width_m", 1.2)
        wh_m = win.get("height_m", 1.2)
        sill_m = win.get("sill_m", 0.9)

        # SVG coordinates
        wx = bldg_x + wx_m * _SCALE
        # Bottom of window at sill height above floor of that level
        floor_y = bldg_bottom_y - lvl * hauteur_par_niveau * _SCALE
        wy_bottom = floor_y - sill_m * _SCALE
        wy_top = wy_bottom - wh_m * _SCALE

        canvas.draw_rect(
            wx, wy_top,
            ww_m * _SCALE, wh_m * _SCALE,
            stroke="#000", fill="#cce8f4", stroke_width=0.25, layer="menuiseries"
        )
        # Cross glass lines
        canvas.draw_line(
            wx, wy_top + wh_m * _SCALE / 2,
            wx + ww_m * _SCALE, wy_top + wh_m * _SCALE / 2,
            stroke="#000", stroke_width=0.13, layer="menuiseries"
        )
        canvas.draw_line(
            wx + ww_m * _SCALE / 2, wy_top,
            wx + ww_m * _SCALE / 2, wy_top + wh_m * _SCALE,
            stroke="#000", stroke_width=0.13, layer="menuiseries"
        )

    # Height annotations (total + per level)
    dim_x = bldg_x + bldg_w + 10

    # Per-level height dimension
    canvas.draw_dimension(
        dim_x, bldg_bottom_y,
        dim_x, bldg_bottom_y - hauteur_par_niveau * _SCALE,
        f"{hauteur_par_niveau:.2f}m",
        offset=4, layer="cotations"
    )

    # Total height dimension
    total_h_m = nb_niveaux * hauteur_par_niveau
    dim_x2 = dim_x + 12
    canvas.draw_dimension(
        dim_x2, bldg_bottom_y,
        dim_x2, bldg_top_y,
        f"{total_h_m:.0f}m",
        offset=4, layer="cotations"
    )

    # Width annotation
    canvas.draw_dimension(
        bldg_x, bldg_bottom_y + 10,
        bldg_x + bldg_w, bldg_bottom_y + 10,
        f"{footprint_width_m:.2f}m",
        offset=4, layer="cotations"
    )

    # Material legend (pc_norme+)
    if detail in ("pc_norme", "execution"):
        legend_x = bldg_x
        legend_y = _MARGIN / 2
        canvas.draw_text(legend_x, legend_y, "Façade — Béton enduit", font_size=8, anchor="start", layer="textes")

    # Level labels on left side
    for i in range(nb_niveaux):
        floor_y = bldg_bottom_y - i * hauteur_par_niveau * _SCALE
        label = "RDC" if i == 0 else f"R+{i}"
        canvas.draw_text(
            bldg_x - 5, floor_y - hauteur_par_niveau * _SCALE / 2,
            label,
            font_size=8, anchor="end", layer="textes"
        )

    return canvas.to_string()


# ---------------------------------------------------------------------------
# DXF
# ---------------------------------------------------------------------------


def _generate_dxf(
    *,
    footprint_width_m: float,
    nb_niveaux: int,
    hauteur_par_niveau: float,
    fenestration: list[dict] | None,
) -> bytes:
    canvas = DxfCanvas()

    total_h = nb_niveaux * hauteur_par_niveau

    # Building outline
    canvas.draw_polygon(
        [
            (0, 0),
            (footprint_width_m, 0),
            (footprint_width_m, total_h),
            (0, total_h),
        ],
        layer="MURS_PORTEURS",
    )

    # Floor lines
    for i in range(1, nb_niveaux):
        floor_y = i * hauteur_par_niveau
        canvas.draw_line(0, floor_y, footprint_width_m, floor_y, layer="COTATIONS")

    # Windows
    wins = fenestration or []
    for win in wins:
        lvl = win.get("niveau", 0)
        wx = win.get("x_m", 1.0)
        ww = win.get("width_m", 1.2)
        wh = win.get("height_m", 1.2)
        sill = win.get("sill_m", 0.9)
        wy = lvl * hauteur_par_niveau + sill
        canvas.draw_polygon(
            [(wx, wy), (wx + ww, wy), (wx + ww, wy + wh), (wx, wy + wh)],
            layer="MENUISERIES",
        )

    canvas.draw_text(0, -1.0, f"Façade {footprint_width_m:.1f}m × {total_h:.1f}m", layer="TEXTES")

    return canvas.to_bytes()
