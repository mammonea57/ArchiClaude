"""PCMI5 — Four-facade generator for permit dossier.

Generates the four cardinal elevation drawings (nord, sud, est, ouest)
from a building footprint polygon, then assembles them into an A3 landscape
2×2 grid suitable for the PCMI5 page.
"""

from __future__ import annotations

import re

from shapely.geometry import Polygon

from core.programming.plans.facade import generate_facade

# A3 landscape dimensions in mm
_A3_WIDTH_MM = 420.0
_A3_HEIGHT_MM = 297.0

# Grid cell label height in mm
_LABEL_H_MM = 8.0

# Cell padding in mm
_CELL_PAD_MM = 3.0

# Cell dimensions (2 columns × 2 rows within A3)
_CELL_W_MM = _A3_WIDTH_MM / 2.0
_CELL_H_MM = _A3_HEIGHT_MM / 2.0

# Inner SVG viewport for each facade (minus label and padding)
_INNER_W_MM = _CELL_W_MM - 2 * _CELL_PAD_MM
_INNER_H_MM = _CELL_H_MM - _LABEL_H_MM - 2 * _CELL_PAD_MM


def generate_all_facades(
    *,
    footprint: Polygon,
    nb_niveaux: int,
    hauteur_par_niveau: float = 3.0,
    detail: str = "pc_norme",
) -> dict[str, str]:
    """Generate 4 facades (nord, sud, est, ouest) as SVG strings.

    Uses the footprint bounding box to derive facade widths:
    - Nord / Sud facades use the east-west span (bounds[2] - bounds[0]).
    - Est / Ouest facades use the north-south span (bounds[3] - bounds[1]).

    Args:
        footprint: Shapely Polygon representing the building footprint.
        nb_niveaux: Number of storeys.
        hauteur_par_niveau: Floor-to-floor height in metres (default 3.0).
        detail: Drawing detail level — 'schematique' | 'pc_norme' | 'execution'.

    Returns:
        Dict with keys 'nord', 'sud', 'est', 'ouest', each an SVG string.
    """
    minx, miny, maxx, maxy = footprint.bounds
    ew_width_m = maxx - minx   # east-west span → nord/sud facades
    ns_depth_m = maxy - miny   # north-south span → est/ouest facades

    facings: dict[str, float] = {
        "nord": ew_width_m,
        "sud": ew_width_m,
        "est": ns_depth_m,
        "ouest": ns_depth_m,
    }

    result: dict[str, str] = {}
    for direction, width_m in facings.items():
        svg = generate_facade(
            footprint_width_m=width_m,
            nb_niveaux=nb_niveaux,
            hauteur_par_niveau=hauteur_par_niveau,
            detail=detail,
            format="svg",
        )
        result[direction] = str(svg)

    return result


def assemble_facades_grid_svg(facades: dict[str, str]) -> str:
    """Assemble 4 facade SVGs into a 2×2 grid for the PCMI5 page.

    Layout on A3 landscape (420×297 mm):

        | FAÇADE NORD  | FAÇADE SUD   |
        | FAÇADE EST   | FAÇADE OUEST |

    Each cell contains a border, a label, and the embedded facade SVG
    scaled to fit the cell.

    Args:
        facades: Dict with keys 'nord', 'sud', 'est', 'ouest' — SVG strings.

    Returns:
        A single SVG string (A3 landscape) containing all four facades.
    """
    # Grid cell positions: (direction, col, row)
    grid: list[tuple[str, int, int]] = [
        ("nord", 0, 0),
        ("sud", 1, 0),
        ("est", 0, 1),
        ("ouest", 1, 1),
    ]

    label_map = {
        "nord": "FAÇADE NORD",
        "sud": "FAÇADE SUD",
        "est": "FAÇADE EST",
        "ouest": "FAÇADE OUEST",
    }

    # Build SVG pieces
    cells: list[str] = []

    for direction, col, row in grid:
        svg_content = facades.get(direction, "")
        cell_x = col * _CELL_W_MM
        cell_y = row * _CELL_H_MM
        label = label_map[direction]

        # Cell border
        cells.append(
            f'<rect x="{cell_x}" y="{cell_y}" '
            f'width="{_CELL_W_MM}" height="{_CELL_H_MM}" '
            f'fill="white" stroke="#333" stroke-width="0.3"/>'
        )

        # Label
        label_x = cell_x + _CELL_W_MM / 2
        label_y = cell_y + _LABEL_H_MM - 1.5
        cells.append(
            f'<text x="{label_x}" y="{label_y}" '
            f'font-family="Helvetica,Arial,sans-serif" font-size="5" '
            f'font-weight="bold" fill="#1a7a7a" text-anchor="middle" '
            f'letter-spacing="0.5">{label}</text>'
        )

        # Separator line under label
        sep_y = cell_y + _LABEL_H_MM
        cells.append(
            f'<line x1="{cell_x}" y1="{sep_y}" '
            f'x2="{cell_x + _CELL_W_MM}" y2="{sep_y}" '
            f'stroke="#ccc" stroke-width="0.2"/>'
        )

        # Embed facade SVG as a nested <svg> using a foreignObject-free approach:
        # Extract inner SVG content and wrap in a <g> with transform.
        inner_svg_x = cell_x + _CELL_PAD_MM
        inner_svg_y = cell_y + _LABEL_H_MM + _CELL_PAD_MM

        # Extract viewBox from generated facade SVG for proper scaling
        vb_match = re.search(r'viewBox=["\']([^"\']+)["\']', svg_content)
        if vb_match:
            vb_parts = vb_match.group(1).split()
            if len(vb_parts) == 4:
                vb_w = float(vb_parts[2])
                vb_h = float(vb_parts[3])
                scale_x = _INNER_W_MM / vb_w if vb_w > 0 else 1.0
                scale_y = _INNER_H_MM / vb_h if vb_h > 0 else 1.0
                scale = min(scale_x, scale_y)
            else:
                scale = 1.0
        else:
            scale = 1.0

        cells.append(
            f'<svg x="{inner_svg_x}" y="{inner_svg_y}" '
            f'width="{_INNER_W_MM}" height="{_INNER_H_MM}" '
            f'overflow="hidden">'
        )
        # Embed the facade SVG content (strip its outer <svg> wrapper)
        inner_content = _extract_svg_body(svg_content)
        cells.append(f'<g transform="scale({scale:.4f})">{inner_content}</g>')
        cells.append("</svg>")

    # Assemble full A3 SVG
    inner_svg = "\n  ".join(cells)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'viewBox="0 0 {_A3_WIDTH_MM} {_A3_HEIGHT_MM}" '
        f'width="{_A3_WIDTH_MM}mm" height="{_A3_HEIGHT_MM}mm">\n'
        f'  <rect width="{_A3_WIDTH_MM}" height="{_A3_HEIGHT_MM}" fill="white"/>\n'
        f"  {inner_svg}\n"
        f"</svg>"
    )


def _extract_svg_body(svg_str: str) -> str:
    """Extract the inner content of an SVG string (strips outer <svg> tags).

    Returns the content between the first ``>`` of the root <svg> element
    and the closing ``</svg>``.
    """
    # Find opening tag end
    open_end = svg_str.find(">")
    if open_end == -1:
        return svg_str
    # Find closing tag
    close_start = svg_str.rfind("</svg>")
    if close_start == -1:
        return svg_str[open_end + 1 :]
    return svg_str[open_end + 1 : close_start]
