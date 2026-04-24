"""L-shape layout handler.

Produces a single continuous L-corridor (inverted-T topology where the
two arms meet), core at the junction, dual-loaded apartment slots on
both branches. Works for all 4 canonical L orientations (inner corner
at NW, NE, SW, or SE of the bounding box) via a single axis-aligned
decomposition.
"""
from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Polygon as ShapelyPolygon
from shapely.geometry import box as shp_box


@dataclass(frozen=True)
class LDecomposition:
    """Result of splitting an L footprint into its two rectangular arms.

    - bar: horizontal arm (the one spanning the full bbox width OR the
      longer of the two along x)
    - leg: vertical arm (narrower in x, taller in y)
    - reflex: inner-corner vertex of the L
    - elbow: corridor junction point (cx_leg, cy_bar), where the
      horizontal bar-corridor meets the vertical leg-corridor
    """
    bar: ShapelyPolygon
    leg: ShapelyPolygon
    reflex: tuple[float, float]
    elbow: tuple[float, float]


def _find_reflex(footprint: ShapelyPolygon) -> tuple[float, float] | None:
    poly = footprint.simplify(0.8)
    if poly.geom_type != "Polygon" or poly.area < footprint.area * 0.9:
        poly = footprint
    coords = list(poly.exterior.coords)[:-1]
    if not poly.exterior.is_ccw:
        coords = coords[::-1]
    n = len(coords)
    for i in range(n):
        p0 = coords[(i - 1) % n]
        p1 = coords[i]
        p2 = coords[(i + 1) % n]
        cross = (p1[0] - p0[0]) * (p2[1] - p1[1]) - (p1[1] - p0[1]) * (p2[0] - p1[0])
        if cross < -0.5:
            return (p1[0], p1[1])
    return None


def _find_notch(footprint: ShapelyPolygon) -> tuple[float, float] | None:
    """The bbox corner that the L footprint does NOT cover."""
    from shapely.geometry import Point as _Point
    minx, miny, maxx, maxy = footprint.bounds
    buf = footprint.buffer(0.1)
    cx, cy = (minx + maxx) / 2, (miny + maxy) / 2
    for corner in ((minx, miny), (maxx, miny), (minx, maxy), (maxx, maxy)):
        probe = _Point(
            corner[0] + (0.5 if corner[0] < cx else -0.5),
            corner[1] + (0.5 if corner[1] < cy else -0.5),
        )
        if not buf.contains(probe):
            return corner
    return None


def decompose_l(footprint: ShapelyPolygon) -> LDecomposition | None:
    """Split an axis-aligned L footprint into bar + leg + elbow.

    Returns None if the footprint is not a clean L (use fallback layout).

    The "bar" is always the arm whose long axis is horizontal (wider
    than tall); the "leg" is the arm whose long axis is vertical. For
    L-shapes where both arms are oriented the same (rare — near-square
    arms), we pick the arm with larger x-span as bar.
    """
    minx, miny, maxx, maxy = footprint.bounds
    reflex = _find_reflex(footprint)
    notch = _find_notch(footprint)
    if reflex is None or notch is None:
        return None

    rx, ry = reflex
    nx, ny = notch

    # Horizontal decomposition: bar = full bottom strip OR full top strip
    # (the one NOT on the notch side), leg = the other strip narrowed to
    # exclude the notch x-range.
    if ny < (miny + maxy) / 2:
        # Notch on bottom → bar is the TOP strip (full width),
        # leg is the BOTTOM strip minus the notch corner
        bar_y0, bar_y1 = ry, maxy
        leg_y0, leg_y1 = miny, ry
        if nx < (minx + maxx) / 2:
            leg_x0, leg_x1 = rx, maxx
        else:
            leg_x0, leg_x1 = minx, rx
        bar = shp_box(minx, bar_y0, maxx, bar_y1)
        leg = shp_box(leg_x0, leg_y0, leg_x1, leg_y1)
    else:
        # Notch on top → bar is the BOTTOM strip (full width),
        # leg is the TOP strip minus the notch corner
        bar_y0, bar_y1 = miny, ry
        leg_y0, leg_y1 = ry, maxy
        if nx < (minx + maxx) / 2:
            leg_x0, leg_x1 = rx, maxx
        else:
            leg_x0, leg_x1 = minx, rx
        bar = shp_box(minx, bar_y0, maxx, bar_y1)
        leg = shp_box(leg_x0, leg_y0, leg_x1, leg_y1)

    # "bar" as computed is the full-width strip, "leg" is the narrowed
    # strip. But if the full-width strip is taller than wide (tall-L),
    # swap roles so bar is always the horizontally-long arm.
    bar_w = bar.bounds[2] - bar.bounds[0]
    bar_h = bar.bounds[3] - bar.bounds[1]
    leg_w = leg.bounds[2] - leg.bounds[0]
    leg_h = leg.bounds[3] - leg.bounds[1]
    if bar_w < bar_h and leg_w > leg_h:
        bar, leg = leg, bar

    # Elbow = (cx_leg, cy_bar) — intersection of leg's vertical axis
    # and bar's horizontal axis.
    cx_leg = (leg.bounds[0] + leg.bounds[2]) / 2
    cy_bar = (bar.bounds[1] + bar.bounds[3]) / 2

    return LDecomposition(
        bar=bar, leg=leg, reflex=(rx, ry), elbow=(cx_leg, cy_bar),
    )
