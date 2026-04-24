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
from shapely.ops import unary_union


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


def build_l_corridor(
    d: LDecomposition, corridor_width: float = 1.6,
) -> ShapelyPolygon:
    """Build the continuous L-shaped corridor.

    Geometry (for inner-corner-NW orientation):
    - Horizontal strip in bar at y=cy_bar, spanning full bar width
    - Vertical strip in leg at x=cx_leg, spanning full leg height
    - Connector strip inside bar from leg.y_min down to cy_bar, at x=cx_leg,
      so the bar corridor and leg corridor meet physically

    The connector is always needed because the leg (after L decomposition)
    starts at y = bar.y_max, while the bar corridor runs at y = cy_bar
    (middle of bar). Without the connector the two strips would be parallel
    with a gap of (bar height / 2). The connector closes that gap inside
    the bar material.
    """
    half = corridor_width / 2
    bx0, by0, bx1, by1 = d.bar.bounds
    lx0, ly0, lx1, ly1 = d.leg.bounds
    cx_leg, cy_bar = d.elbow

    # Bar horizontal strip (full bar width at cy_bar)
    bar_strip = shp_box(bx0, cy_bar - half, bx1, cy_bar + half)

    # Leg vertical strip (full leg height at cx_leg)
    leg_strip = shp_box(cx_leg - half, ly0, cx_leg + half, ly1)

    # Connector inside bar: from leg's base (ly0) down to cy_bar, at x=cx_leg.
    # If leg starts above bar centerline (inner corner NW/NE) this is a
    # downward segment; if leg starts below (inner corner SW/SE) it's upward.
    if ly0 > cy_bar:
        conn_y0, conn_y1 = cy_bar, ly0
    else:
        conn_y0, conn_y1 = ly1, cy_bar
    connector = shp_box(cx_leg - half, conn_y0, cx_leg + half, conn_y1)

    corridor = unary_union([bar_strip, leg_strip, connector])
    # Ensure result is Polygon (should be after union of overlapping rects)
    if corridor.geom_type != "Polygon":
        # Fallback: pick largest
        corridor = max(corridor.geoms, key=lambda g: g.area)
    return corridor
