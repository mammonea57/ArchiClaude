"""Plan de niveau generator — floor plate layout.

Three detail levels:
  - schematique: thick walls, room names only
  - pc_norme: wall thicknesses, doors, windows, room names + surfaces, dimensions
  - execution: pc_norme + furniture symbols + gaine symbols
"""

from __future__ import annotations

from shapely.geometry import Polygon

from core.drawing.conventions import TRAIT_EPAISSEURS
from core.programming.schemas import NiveauDistribution
from core.programming.plans.renderer_svg import SvgCanvas
from core.programming.plans.renderer_dxf import DxfCanvas


# Scale: 1m in world = _SCALE mm on drawing (1:50)
_SCALE = 20.0
_MARGIN = 15.0

# Wall thicknesses in metres
_MURS_PORTEUR_M = 0.20
_CLOISON_M = 0.07


def generate_plan_niveau(
    niveau: NiveauDistribution,
    *,
    detail: str = "pc_norme",
    format: str = "svg",
) -> str | bytes:
    """Generate a plan de niveau SVG or DXF.

    Parameters
    ----------
    niveau:
        Full floor plate distribution for one level.
    detail:
        'schematique' | 'pc_norme' | 'execution'
    format:
        'svg' | 'dxf'
    """
    if format == "dxf":
        return _generate_dxf(niveau)
    return _generate_svg(niveau, detail=detail)


# ---------------------------------------------------------------------------
# SVG
# ---------------------------------------------------------------------------


def _world_to_svg(
    x: float, y: float, minx: float, miny: float, maxy: float
) -> tuple[float, float]:
    """Convert world metre coords to SVG mm, flipping Y."""
    return (
        (x - minx) * _SCALE + _MARGIN,
        (maxy - y) * _SCALE + _MARGIN,
    )


def _coords_to_svg(
    coords: list[tuple[float, float]], minx: float, miny: float, maxy: float
) -> list[tuple[float, float]]:
    return [_world_to_svg(x, y, minx, miny, maxy) for x, y in coords]


def _generate_svg(niveau: NiveauDistribution, *, detail: str) -> str:
    fp = niveau.footprint
    minx, miny, maxx, maxy = fp.bounds
    world_w = maxx - minx
    world_h = maxy - miny

    canvas_w = world_w * _SCALE + 2 * _MARGIN
    canvas_h = world_h * _SCALE + 2 * _MARGIN

    canvas = SvgCanvas(width_mm=canvas_w, height_mm=canvas_h)

    def to_svg(coords: list[tuple[float, float]]) -> list[tuple[float, float]]:
        return _coords_to_svg(coords, minx, miny, maxy)

    def pt(x: float, y: float) -> tuple[float, float]:
        return _world_to_svg(x, y, minx, miny, maxy)

    # --- Outer footprint (exterior wall) ---
    fp_pts = to_svg(list(fp.exterior.coords))
    wall_sw = TRAIT_EPAISSEURS["mur_porteur"] if detail == "pc_norme" else TRAIT_EPAISSEURS["mur_porteur"] * 1.5
    canvas.draw_polygon(fp_pts, stroke="#000", fill="#e8e8e8", stroke_width=wall_sw, layer="murs")

    # --- Logements ---
    for logement in niveau.logements:
        geom = logement.geometry
        lg_pts = to_svg(list(geom.exterior.coords))
        canvas.draw_polygon(lg_pts, stroke="#333", fill="#f9f9f9", stroke_width=TRAIT_EPAISSEURS["cloison"], layer="cloisons")

        # Room label: typology + surface
        cx = geom.centroid.x
        cy = geom.centroid.y
        sx, sy = pt(cx, cy)

        if detail == "schematique":
            canvas.draw_text(sx, sy, logement.typologie, font_size=8, layer="textes")
        else:
            # pc_norme: room name + surface
            canvas.draw_text(sx, sy - 3, logement.typologie, font_size=8, layer="textes")
            canvas.draw_text(sx, sy + 4, f"{logement.surface_m2:.0f} m²", font_size=7, layer="textes")

            # Draw individual pieces
            for piece in logement.pieces:
                # Approximate piece as rectangle inside logement geometry
                bx, by, bx2, by2 = geom.bounds
                pw = piece.largeur_m
                ph = piece.longueur_m
                piece_x = bx + 0.2
                piece_y = by + 0.2
                svgx, svgy = pt(piece_x, piece_y)
                pw_mm = pw * _SCALE
                ph_mm = ph * _SCALE
                canvas.draw_rect(svgx, svgy - ph_mm, pw_mm, ph_mm, stroke="#666", fill="none", stroke_width=0.13, layer="cloisons")
                # Piece name
                cx_p = piece_x + pw / 2
                cy_p = piece_y + ph / 2
                spx, spy = pt(cx_p, cy_p)
                canvas.draw_text(spx, spy, piece.nom, font_size=6, layer="textes")

            # Dimensions for pc_norme
            bx, by, bx2, by2 = geom.bounds
            sx1, sy1 = pt(bx, miny)
            sx2, sy2 = pt(bx2, miny)
            # Only add if meaningful width
            if bx2 - bx > 0.5:
                canvas.draw_dimension(sx1, sy1 + _MARGIN * 0.5, sx2, sy2 + _MARGIN * 0.5,
                                      f"{bx2 - bx:.2f}m", offset=3, layer="cotations")

        # execution: furniture symbols
        if detail == "execution":
            bx, by, bx2, by2 = geom.bounds
            furn_x, furn_y = pt(bx + 0.5, by2 - 1.0)
            # Bed symbol (rectangle)
            canvas.draw_rect(furn_x, furn_y, 0.9 * _SCALE, 0.2 * _SCALE,
                              stroke="#999", fill="#ddd", stroke_width=0.13, layer="mobilier")

        # Door symbols (pc_norme+)
        if detail in ("pc_norme", "execution"):
            bx, by, bx2, by2 = geom.bounds
            dx, dy = pt(bx, by2)
            canvas.draw_door(dx, dy, width_m=0.04, direction="left", layer="menuiseries")

    # --- Noyaux (core: staircase + lift) ---
    for noyau in niveau.noyaux:
        px, py = noyau.position.x, noyau.position.y
        r = 2.5  # core radius in m
        nx1, ny1 = pt(px - r, py + r)
        canvas.draw_rect(nx1, ny1, r * 2 * _SCALE, r * 2 * _SCALE,
                         stroke="#000", fill="#ccc", stroke_width=0.5, layer="noyaux")
        tx, ty = pt(px, py)
        canvas.draw_text(tx, ty, "ESC/ASC", font_size=7, layer="textes")

    # --- Couloirs ---
    for couloir in niveau.couloirs:
        col_pts = to_svg(list(couloir.exterior.coords))
        canvas.draw_polygon(col_pts, stroke="#888", fill="#f0f0f0", stroke_width=0.18, layer="circulation")

        if detail in ("pc_norme", "execution"):
            # Couloir width dimension
            cb = couloir.bounds
            cw = cb[2] - cb[0]
            ch = cb[3] - cb[1]
            mid_x = (cb[0] + cb[2]) / 2
            bot_y = cb[1]
            top_y = cb[3]
            if ch > 0.5:
                sx1, sy1 = pt(mid_x, bot_y)
                sx2, sy2 = pt(mid_x, top_y)
                canvas.draw_dimension(sx1, sy1, sx2, sy2, f"{ch:.2f}m", layer="cotations")

    # --- Level label ---
    niveau_label = "RDC" if niveau.niveau == 0 else f"R+{niveau.niveau}"
    canvas.draw_text(_MARGIN + world_w * _SCALE / 2, _MARGIN / 2, niveau_label, font_size=11, layer="textes")

    return canvas.to_string()


# ---------------------------------------------------------------------------
# DXF
# ---------------------------------------------------------------------------


def _generate_dxf(niveau: NiveauDistribution) -> bytes:
    canvas = DxfCanvas()

    fp = niveau.footprint
    canvas.draw_polygon(list(fp.exterior.coords)[:-1], layer="MURS_PORTEURS")

    for logement in niveau.logements:
        canvas.draw_polygon(list(logement.geometry.exterior.coords)[:-1], layer="CLOISONS")
        cx = logement.geometry.centroid.x
        cy = logement.geometry.centroid.y
        canvas.draw_text(cx, cy, logement.typologie, layer="TEXTES")

    for noyau in niveau.noyaux:
        px, py = noyau.position.x, noyau.position.y
        r = 2.5
        canvas.draw_polygon(
            [(px - r, py - r), (px + r, py - r), (px + r, py + r), (px - r, py + r)],
            layer="CIRCULATION",
        )

    for couloir in niveau.couloirs:
        canvas.draw_polygon(list(couloir.exterior.coords)[:-1], layer="CIRCULATION")

    return canvas.to_bytes()
