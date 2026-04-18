"""Plan de masse generator — parcelle + footprint + setback dimensions.

Generates SVG or DXF output following PC dossier conventions.
"""

from __future__ import annotations

from shapely.geometry import Polygon

from core.drawing.conventions import TRAIT_EPAISSEURS
from core.programming.plans.renderer_svg import SvgCanvas
from core.programming.plans.renderer_dxf import DxfCanvas


def generate_plan_masse(
    *,
    parcelle: Polygon,
    footprint: Polygon,
    voirie_name: str = "",
    north_angle: float = 0.0,
    emprise_pct: float = 0.0,
    surface_pleine_terre_m2: float = 0.0,
    detail: str = "pc_norme",
    format: str = "svg",
) -> str | bytes:
    """Generate a plan de masse.

    Parameters
    ----------
    parcelle:
        Parcelle boundary polygon (metric CRS).
    footprint:
        Building footprint polygon (metric CRS).
    voirie_name:
        Name of the street (rue / avenue) for labelling.
    north_angle:
        North arrow rotation in degrees (0 = up).
    emprise_pct:
        Emprise au sol percentage annotation.
    surface_pleine_terre_m2:
        Pleine terre surface area annotation in m².
    detail:
        Level of detail: 'schematique' | 'pc_norme' | 'execution'.
    format:
        Output format: 'svg' | 'dxf'.

    Returns
    -------
    str (SVG) or bytes (DXF).
    """
    if format == "dxf":
        return _generate_dxf(
            parcelle=parcelle,
            footprint=footprint,
            voirie_name=voirie_name,
        )
    return _generate_svg(
        parcelle=parcelle,
        footprint=footprint,
        voirie_name=voirie_name,
        north_angle=north_angle,
        emprise_pct=emprise_pct,
        surface_pleine_terre_m2=surface_pleine_terre_m2,
        detail=detail,
    )


# ---------------------------------------------------------------------------
# SVG implementation
# ---------------------------------------------------------------------------

# Scale factor: 1m in real space → how many mm on the drawing
_DRAWING_SCALE = 5.0  # 1:200 → 1m = 5mm on paper


def _world_to_mm(coords: list[tuple[float, float]], origin_x: float, origin_y: float, max_h: float) -> list[tuple[float, float]]:
    """Convert world metre coords to SVG mm, flipping Y axis."""
    return [
        ((x - origin_x) * _DRAWING_SCALE, (max_h - (y - origin_y)) * _DRAWING_SCALE)
        for x, y in coords
    ]


def _generate_svg(
    *,
    parcelle: Polygon,
    footprint: Polygon,
    voirie_name: str,
    north_angle: float,
    emprise_pct: float,
    surface_pleine_terre_m2: float,
    detail: str,
) -> str:
    # Compute bounding box in world coords
    minx, miny, maxx, maxy = parcelle.bounds
    world_w = maxx - minx
    world_h = maxy - miny

    # Canvas size with margin
    margin_mm = 20.0
    canvas_w = world_w * _DRAWING_SCALE + 2 * margin_mm
    canvas_h = world_h * _DRAWING_SCALE + 2 * margin_mm

    canvas = SvgCanvas(width_mm=canvas_w, height_mm=canvas_h)

    def to_svg(coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return [
            ((x - minx) * _DRAWING_SCALE + margin_mm,
             (world_h - (y - miny)) * _DRAWING_SCALE + margin_mm)
            for x, y in coords
        ]

    # Parcelle outline (thick contour)
    parcelle_pts = to_svg(list(parcelle.exterior.coords))
    canvas.draw_polygon(
        parcelle_pts,
        stroke="#000",
        fill="none",
        stroke_width=TRAIT_EPAISSEURS["contour_parcelle"],
        layer="parcelle",
    )

    # Footprint filled teal
    footprint_pts = to_svg(list(footprint.exterior.coords))
    canvas.draw_polygon(
        footprint_pts,
        stroke="#008080",
        fill="#b2dfdb",
        stroke_width=TRAIT_EPAISSEURS["contour_dalle"],
        layer="batiment",
    )

    # Setback dimension lines (voirie, séparatives, fond de parcelle)
    if detail in ("pc_norme", "execution"):
        _add_setback_dimensions(canvas, parcelle, footprint, to_svg)

    # Voirie label at bottom of parcelle
    if voirie_name:
        label_x = (0 + world_w / 2) * _DRAWING_SCALE + margin_mm
        label_y = world_h * _DRAWING_SCALE + margin_mm + 8
        canvas.draw_text(label_x, label_y, voirie_name, font_size=9, layer="textes")

    # Annotations
    ann_x = margin_mm + world_w * _DRAWING_SCALE + 5
    ann_y = margin_mm + 10
    if emprise_pct > 0:
        canvas.draw_text(ann_x, ann_y, f"Emprise : {emprise_pct:.1f}%", font_size=8, anchor="start", layer="textes")
        ann_y += 6
    if surface_pleine_terre_m2 > 0:
        canvas.draw_text(ann_x, ann_y, f"Pleine terre : {surface_pleine_terre_m2:.0f} m²", font_size=8, anchor="start", layer="textes")

    # North arrow
    na_x = margin_mm + world_w * _DRAWING_SCALE - 15
    na_y = margin_mm + 15
    canvas.draw_north_arrow(na_x, na_y, angle=north_angle)

    return canvas.to_string()


def _add_setback_dimensions(
    canvas: SvgCanvas,
    parcelle: Polygon,
    footprint: Polygon,
    to_svg: object,
) -> None:
    """Add dimension lines for setbacks between parcelle and footprint."""
    import math

    # Get exterior coords
    p_coords = list(parcelle.exterior.coords)[:-1]  # drop repeated last
    f_coords = list(footprint.exterior.coords)[:-1]

    # For each side of the footprint, find the nearest parcelle edge and draw a setback dimension
    # Simplified: draw setback from footprint bounding box to parcelle bounding box edges
    p_minx, p_miny, p_maxx, p_maxy = parcelle.bounds
    f_minx, f_miny, f_maxx, f_maxy = footprint.bounds

    # Only draw if there is a meaningful setback
    eps = 0.05  # 5cm tolerance

    def _to_svg_pt(x: float, y: float) -> tuple[float, float]:
        result = to_svg([(x, y)])  # type: ignore[call-arg]
        return result[0]

    if f_miny - p_miny > eps:  # South setback (voirie side typically)
        mid_x = (f_minx + f_maxx) / 2
        sx1, sy1 = _to_svg_pt(mid_x, p_miny)
        sx2, sy2 = _to_svg_pt(mid_x, f_miny)
        label = f"{f_miny - p_miny:.2f}m"
        canvas.draw_dimension(sx1, sy1, sx2, sy2, label, layer="cotations")

    if p_maxy - f_maxy > eps:  # North setback (fond de parcelle)
        mid_x = (f_minx + f_maxx) / 2
        sx1, sy1 = _to_svg_pt(mid_x, f_maxy)
        sx2, sy2 = _to_svg_pt(mid_x, p_maxy)
        label = f"{p_maxy - f_maxy:.2f}m"
        canvas.draw_dimension(sx1, sy1, sx2, sy2, label, layer="cotations")

    if f_minx - p_minx > eps:  # West setback (séparative)
        mid_y = (f_miny + f_maxy) / 2
        sx1, sy1 = _to_svg_pt(p_minx, mid_y)
        sx2, sy2 = _to_svg_pt(f_minx, mid_y)
        label = f"{f_minx - p_minx:.2f}m"
        canvas.draw_dimension(sx1, sy1, sx2, sy2, label, layer="cotations")

    if p_maxx - f_maxx > eps:  # East setback (séparative)
        mid_y = (f_miny + f_maxy) / 2
        sx1, sy1 = _to_svg_pt(f_maxx, mid_y)
        sx2, sy2 = _to_svg_pt(p_maxx, mid_y)
        label = f"{p_maxx - f_maxx:.2f}m"
        canvas.draw_dimension(sx1, sy1, sx2, sy2, label, layer="cotations")


# ---------------------------------------------------------------------------
# DXF implementation
# ---------------------------------------------------------------------------


def _generate_dxf(
    *,
    parcelle: Polygon,
    footprint: Polygon,
    voirie_name: str,
) -> bytes:
    canvas = DxfCanvas()

    # Parcelle
    canvas.draw_polygon(
        list(parcelle.exterior.coords)[:-1],
        layer="MURS_PORTEURS",
    )
    # Footprint
    canvas.draw_polygon(
        list(footprint.exterior.coords)[:-1],
        layer="CLOISONS",
    )
    # Voirie label
    if voirie_name:
        minx, miny, _, _ = parcelle.bounds
        canvas.draw_text(minx, miny - 2.0, voirie_name, layer="TEXTES")

    return canvas.to_bytes()
