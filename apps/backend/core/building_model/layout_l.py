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


def place_core_at_elbow(
    d: LDecomposition, core_surface_m2: float,
) -> ShapelyPolygon:
    """Place the core (stairs + lift + shafts) at the corridor elbow.

    Square core centred on the elbow. If the elbow is too close to bar
    or leg edges for the square to fit inside the footprint, the core is
    shifted inward minimally to keep it inside.
    """
    side = core_surface_m2 ** 0.5
    cx, cy = d.elbow
    bx0, by0, bx1, by1 = d.bar.bounds
    lx0, ly0, lx1, ly1 = d.leg.bounds

    # Clamp to keep core inside bar (since elbow is in bar for inner-corner-NW)
    # For inner-corner orientations where elbow is in leg, clamp to leg instead.
    # Elbow is always in bar when the L was decomposed with bar = full-width arm.
    cx = max(bx0 + side / 2, min(bx1 - side / 2, cx))
    cy = max(by0 + side / 2, min(by1 - side / 2, cy))

    return shp_box(cx - side / 2, cy - side / 2, cx + side / 2, cy + side / 2)


@dataclass(frozen=True)
class LQuadrant:
    """A rectangular apartment zone surrounding the L-corridor.

    - name: canonical label ("south_bar", "nw_bar", "ne_bar",
      "leg_west", "leg_east")
    - rect: axis-aligned rectangle polygon
    - long_axis: "horizontal" or "vertical" — direction along which
      apts are sliced
    - facade_sides: exterior sides of this quadrant touching a street
      or jardin ("sud", "nord", "est", "ouest")
    """
    name: str
    rect: ShapelyPolygon
    long_axis: str
    facade_sides: tuple[str, ...]


def compute_l_quadrants(
    d: LDecomposition, corridor_width: float = 1.6,
) -> list[LQuadrant]:
    """Return the 5 rectangular apartment zones around the L-corridor.

    Works for all 4 canonical L orientations. The quadrant NAMES are
    always the same (south_bar, nw_bar, etc.) but the actual rectangle
    coordinates reflect the specific orientation of this L.

    For inner-corner NW (bar south, leg east, outer corner NE):
    - south_bar: bar below corridor
    - nw_bar: bar above corridor, west of leg x
    - ne_bar: bar above corridor, east of leg x (small corner)
    - leg_west: leg west of leg corridor
    - leg_east: leg east of leg corridor
    """
    half = corridor_width / 2
    bx0, by0, bx1, by1 = d.bar.bounds
    lx0, ly0, lx1, ly1 = d.leg.bounds
    cx_leg, cy_bar = d.elbow

    # Determine orientation: is leg ABOVE or BELOW bar centerline?
    leg_above = ly0 >= cy_bar
    # Is leg EAST or WEST of bar centerline?
    cx_bar = (bx0 + bx1) / 2
    leg_east_of_center = cx_leg >= cx_bar

    # Bar splits into "below-corridor" and "above-corridor" strips
    bar_south = shp_box(bx0, by0, bx1, cy_bar - half)
    bar_north = shp_box(bx0, cy_bar + half, bx1, by1)
    # Above-bar strip splits at x=cx_leg ± half into west/east
    bar_above_west = shp_box(bx0, cy_bar + half, cx_leg - half, by1)
    bar_above_east = shp_box(cx_leg + half, cy_bar + half, bx1, by1)
    # For inner-corner NW, leg is above bar → nw_bar = bar_above_west,
    # ne_bar = bar_above_east, south_bar = bar_south.
    # For inner-corner SW (leg below bar), swap: south_bar becomes
    # bar_above (above corridor), nw_bar becomes bar_below_west.
    if leg_above:
        south_rect = bar_south
        nw_rect = bar_above_west
        ne_rect = bar_above_east
    else:
        # Leg below: bar's "other" strip is ABOVE the corridor.
        south_rect = bar_north  # "opposite to leg" side
        # Below-corridor splits analogously
        nw_rect = shp_box(bx0, by0, cx_leg - half, cy_bar - half)
        ne_rect = shp_box(cx_leg + half, by0, bx1, cy_bar - half)

    # Leg splits at x=cx_leg ± half into west/east columns
    leg_west_rect = shp_box(lx0, ly0, cx_leg - half, ly1)
    leg_east_rect = shp_box(cx_leg + half, ly0, lx1, ly1)

    # Facade sides (based on bbox orientation — the owner's polygon
    # tells us which sides touch the outside). For inner-corner-NW:
    # south_bar touches "sud", leg_east touches "est", etc. The dispatcher
    # is responsible for translating to voirie/jardin labels upstream.
    quadrants: list[LQuadrant] = []
    # Suppress zero-area rects (when leg_w ≤ corridor_width etc.)
    for name, rect, axis, sides in [
        ("south_bar", south_rect, "horizontal", ("sud",)),
        ("nw_bar", nw_rect, "horizontal", ("ouest", "nord")),
        ("ne_bar", ne_rect, "horizontal", ("est", "nord")),
        ("leg_west", leg_west_rect, "vertical", ("ouest",)),
        ("leg_east", leg_east_rect, "vertical", ("est",)),
    ]:
        if rect.area > 1.0:  # drop slivers
            quadrants.append(LQuadrant(name=name, rect=rect, long_axis=axis, facade_sides=sides))
    return quadrants


from core.building_model.solver import ApartmentSlot
from core.building_model.schemas import Typologie


_MIN_APT_WIDTH_M = 5.5  # below this, apt is unsellable


def slice_quadrant_into_apts(
    quadrant: LQuadrant,
    target_typo: Typologie,
    target_surface: float,
    id_prefix: str = "",
) -> list[ApartmentSlot]:
    """Slice a rectangular quadrant into T2/T3 slots along its long axis.

    Strategy: at the quadrant's fixed depth (perpendicular to long axis),
    the target apt width = target_surface / depth. Compute how many apts
    fit at that width; split the long dimension evenly.

    Returns a list of ApartmentSlot with target_typologie set.
    """
    qx0, qy0, qx1, qy1 = quadrant.rect.bounds
    w = qx1 - qx0
    h = qy1 - qy0

    if quadrant.long_axis == "horizontal":
        long_len = w
        depth = h
    else:
        long_len = h
        depth = w

    if depth <= 0 or long_len <= 0:
        return []

    # Number of apts = round(total area / target surface).
    # This matches the quadrant's real capacity better than width-based
    # counting: a 91 m² quadrant targeted at T2 (48 m²) gets 2 slots
    # (~45 m² each), not 1 oversized slot that would be rejected by the
    # template adapter.
    total_area = long_len * depth
    n_apts = max(1, round(total_area / target_surface))
    actual_width = long_len / n_apts
    # Slivers: if rounding produced sub-minimum width, reduce count
    if actual_width < _MIN_APT_WIDTH_M and n_apts > 1:
        n_apts = max(1, int(long_len / _MIN_APT_WIDTH_M))
        actual_width = long_len / n_apts

    slots: list[ApartmentSlot] = []
    for i in range(n_apts):
        if quadrant.long_axis == "horizontal":
            ax0 = qx0 + i * actual_width
            ax1 = qx0 + (i + 1) * actual_width
            ay0, ay1 = qy0, qy1
        else:
            ay0 = qy0 + i * actual_width
            ay1 = qy0 + (i + 1) * actual_width
            ax0, ax1 = qx0, qx1
        poly = shp_box(ax0, ay0, ax1, ay1)
        position = "extremite" if i == 0 or i == n_apts - 1 else "milieu"
        slots.append(ApartmentSlot(
            id=f"{id_prefix}{quadrant.name}_{i}",
            polygon=poly,
            surface_m2=poly.area,
            target_typologie=target_typo,
            orientations=list(quadrant.facade_sides),
            position_in_floor=position,
        ))
    return slots


@dataclass(frozen=True)
class LLayoutResult:
    core: ShapelyPolygon
    corridor: ShapelyPolygon
    slots: list[ApartmentSlot]
    decomposition: LDecomposition


def compute_l_layout(
    footprint: ShapelyPolygon,
    mix_typologique: dict[Typologie, float],
    core_surface_m2: float,
    corridor_width: float = 1.6,
    id_prefix: str = "",
) -> LLayoutResult | None:
    """Generate core + L-corridor + apt slots for an L-shaped footprint.

    Returns None if the footprint is not a clean L (caller should fall
    back to legacy wing-par-wing layout).
    """
    d = decompose_l(footprint)
    if d is None:
        return None

    corridor = build_l_corridor(d, corridor_width=corridor_width)
    core = place_core_at_elbow(d, core_surface_m2=core_surface_m2)
    quadrants = compute_l_quadrants(d, corridor_width=corridor_width)

    # Assign typology per quadrant based on mix and quadrant size.
    # South bar (large, facing voirie) → T2 priority for units count.
    # Leg arms (medium) → T3 priority for family apts.
    # Small NE corner → T2 fill.
    T2_share = mix_typologique.get(Typologie.T2, 0.0)
    T3_share = mix_typologique.get(Typologie.T3, 0.0)
    total = T2_share + T3_share
    if total <= 0:
        return None

    slots: list[ApartmentSlot] = []
    for q in quadrants:
        # Bar quadrants (horizontal long axis) → T2 target; leg → T3 target
        if q.long_axis == "horizontal":
            typo = Typologie.T2 if T2_share >= T3_share * 0.3 else Typologie.T3
            surface = 48.0 if typo == Typologie.T2 else 58.0
        else:
            typo = Typologie.T3 if T3_share > 0 else Typologie.T2
            surface = 58.0 if typo == Typologie.T3 else 48.0
        slots.extend(slice_quadrant_into_apts(
            quadrant=q, target_typo=typo, target_surface=surface,
            id_prefix=id_prefix,
        ))

    # Clip any slot that overlaps circulation (safety net)
    occupied = corridor.union(core)
    clipped_slots: list[ApartmentSlot] = []
    for s in slots:
        clean = s.polygon.difference(occupied)
        if clean.is_empty or clean.area < 20.0:
            continue
        if clean.geom_type == "MultiPolygon":
            clean = max(clean.geoms, key=lambda g: g.area)
        clipped_slots.append(ApartmentSlot(
            id=s.id,
            polygon=clean,
            surface_m2=clean.area,
            target_typologie=s.target_typologie,
            orientations=s.orientations,
            position_in_floor=s.position_in_floor,
        ))

    return LLayoutResult(
        core=core, corridor=corridor, slots=clipped_slots, decomposition=d,
    )
