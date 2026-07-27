"""L-shape layout handler.

Produces a single continuous L-corridor (inverted-T topology where the
two arms meet), core at the junction, dual-loaded apartment slots on
both branches. Works for all 4 canonical L orientations (inner corner
at NW, NE, SW, or SE of the bounding box) via a single axis-aligned
decomposition.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from shapely.geometry import LineString
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
    """Place the core (stairs + lift + shafts) inside the ne_bar zone.

    The ne_bar (small corner quadrant at the corridor elbow) is
    sacrificed to host the core. This eliminates lateral intrusion into
    neighboring apartments — the core occupies a zone that is no longer
    sliced into apt slots.

    Position (for inner-corner NW, leg above bar):
    - SW corner of core at (cx_leg + half, cy_bar + half) — the corridor
      intersection point, so the core touches both arms of the L.
    - Width (x-direction) = 3.0 m.
    - Length (y-direction) = core_surface_m2 / 3.0 m, clamped to fit
      inside ne_bar.

    For inner-corner SW (leg below bar) the core is flipped below the
    bar corridor instead.
    """
    CORE_WIDTH = 3.0
    CORRIDOR_WIDTH = 1.6
    half = CORRIDOR_WIDTH / 2
    cx_leg, cy_bar = d.elbow
    bx0, by0, bx1, by1 = d.bar.bounds
    ly0 = d.leg.bounds[1]
    ly1 = d.leg.bounds[3]

    # Detect L orientation: leg above or below bar
    leg_above = ly0 > by1 - 0.5

    # ne_bar corner zone:
    #   leg_above (NW/NE inner corner):
    #       x in [cx_leg + half, bx1], y in [cy_bar + half, by1]
    #   leg_below (SW/SE inner corner):
    #       x in [cx_leg + half, bx1], y in [by0, cy_bar - half]
    ne_x0 = cx_leg + half
    ne_x1 = bx1
    if leg_above:
        ne_y0 = cy_bar + half
        ne_y1 = by1
    else:
        ne_y0 = by0
        ne_y1 = cy_bar - half

    ne_width = ne_x1 - ne_x0
    ne_height = ne_y1 - ne_y0

    # Core fits inside ne_bar. Width perpendicular to leg corridor = 3m,
    # clamped to ne_bar width. Length along leg corridor = target length,
    # clamped to ne_bar height.
    core_w = min(CORE_WIDTH, max(0.1, ne_width))
    target_length = core_surface_m2 / CORE_WIDTH
    core_l = min(target_length, max(0.1, ne_height))

    # Core SW corner at corridor intersection for leg_above;
    # NW corner at corridor intersection for leg_below (flipped upward
    # from cy_bar - half).
    x0 = ne_x0
    x1 = x0 + core_w
    if leg_above:
        y0 = ne_y0
        y1 = y0 + core_l
    else:
        y1 = ne_y1
        y0 = y1 - core_l

    return shp_box(x0, y0, x1, y1)


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


def _compute_exterior_facades(
    rect: ShapelyPolygon, footprint: ShapelyPolygon,
    voirie_orientations: tuple[str, ...] | None = None,
) -> tuple[str, ...]:
    """For an axis-aligned rectangle, return which of its 4 edges
    (sud/nord/ouest/est) coincide with the footprint's EXTERIOR boundary
    AND can carry daylight (street voirie OR the concave garden/void).

    Interior edges (shared with other quadrants of the same footprint) are
    excluded. A probe 0.3m outside an edge must lie outside the footprint
    for that edge to be exterior.

    MITOYEN filtering (2026-07-03) : when ``voirie_orientations`` is given, an
    exterior edge that lies on the footprint's BBOX PERIMETER but is NOT a
    voirie side is a party wall (mur aveugle) — it cannot host windows/doors/
    balconies, so it is dropped. Edges facing the concave notch (the garden/
    void, i.e. interior to the bbox) are kept: they carry daylight toward the
    cour. This is universal for any L / any orientation.
    """
    from shapely.geometry import Point
    qx0, qy0, qx1, qy1 = rect.bounds
    sides: list[str] = []
    PROBE = 0.3
    fp_buf = footprint.buffer(0.1)
    # sud: probe below
    if not fp_buf.contains(Point((qx0 + qx1) / 2, qy0 - PROBE)):
        sides.append("sud")
    # nord: probe above
    if not fp_buf.contains(Point((qx0 + qx1) / 2, qy1 + PROBE)):
        sides.append("nord")
    # ouest: probe left
    if not fp_buf.contains(Point(qx0 - PROBE, (qy0 + qy1) / 2)):
        sides.append("ouest")
    # est: probe right
    if not fp_buf.contains(Point(qx1 + PROBE, (qy0 + qy1) / 2)):
        sides.append("est")

    if voirie_orientations is not None:
        voi = {v for v in voirie_orientations}
        fxmin, fymin, fxmax, fymax = footprint.bounds
        TOL = 0.5
        # An edge is a MITOYEN iff it lies on the bbox perimeter on its side
        # AND that side is not a voirie. Void-facing edges (interior to the
        # bbox) are never on the perimeter → always kept.
        on_perim = {
            "sud": abs(qy0 - fymin) < TOL,
            "nord": abs(qy1 - fymax) < TOL,
            "ouest": abs(qx0 - fxmin) < TOL,
            "est": abs(qx1 - fxmax) < TOL,
        }
        sides = [s for s in sides if not (on_perim.get(s, False) and s not in voi)]

    return tuple(sides)


def compute_l_quadrants(
    d: LDecomposition,
    footprint: ShapelyPolygon,
    corridor_width: float = 1.6,
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

    Facade sides are computed per-quadrant against the footprint exterior:
    an edge counts as a facade only if a probe 0.3m outside it falls
    outside the footprint. This correctly excludes interior boundaries
    shared with other quadrants (e.g. ne_bar's north edge, which is
    shared with the leg above it).
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

    # Facade sides are computed against the FOOTPRINT exterior, not
    # hardcoded per quadrant name. An edge of the quadrant rectangle is
    # a facade only if probing 0.3m outside it falls outside the footprint.
    # This correctly excludes interior edges shared with other quadrants
    # (e.g. ne_bar's north edge is shared with leg above it, so it's
    # INTERIOR, not a facade).
    quadrants: list[LQuadrant] = []
    # Suppress zero-area rects (when leg_w ≤ corridor_width etc.)
    for name, rect, axis in [
        ("south_bar", south_rect, "horizontal"),
        ("nw_bar", nw_rect, "horizontal"),
        ("ne_bar", ne_rect, "horizontal"),
        ("leg_west", leg_west_rect, "vertical"),
        ("leg_east", leg_east_rect, "vertical"),
    ]:
        if rect.area > 1.0:  # drop slivers
            sides = _compute_exterior_facades(rect, footprint)
            quadrants.append(LQuadrant(name=name, rect=rect, long_axis=axis, facade_sides=sides))
    return quadrants


from core.building_model.solver import ApartmentSlot
from core.building_model.schemas import Typologie


_MIN_APT_WIDTH_M = 5.5  # below this, apt is unsellable
# Largeur MAX d'un slot avant scission « anti-coin-obèse ». Calibrée (2026-07-03)
# pour LAISSER PASSER les grandes typos : à profondeur dual-loaded ~8,7 m, un T4
# exige ~9,5 m de façade (3 chambres) et un T5 ~12 m (4 chambres). Un plafond à
# 11 m interdisait tout T5 et étranglait les T4 → mix 55/45/0. Relevé à 13 m :
# les T4/T5 se forment (relayout mono-façade génère N chambres + séjour plafonné),
# et seuls les slots VRAIMENT monstrueux (>13 m, coin après double-merge) sont
# scindés. Universel (toute L) : la largeur reste dérivée de la géométrie.
_MAX_APT_WIDTH_M = 13.0


def slice_quadrant_by_mix(
    quadrant: LQuadrant,
    mix_typologique: dict[Typologie, float],
    id_prefix: str = "",
) -> list[ApartmentSlot]:
    """Slice a quadrant into VARIABLE-WIDTH slots honouring the full mix.

    Root-cause fix (2026-07-03) : à profondeur fixe (~8,7 m dual-loaded), toutes
    les typos ont la même profondeur → seule la LARGEUR distingue T2/T3/T4/T5.
    L'ancien découpage à largeur uniforme sortait tout en T3. Ici on pose une
    SÉQUENCE de largeurs par typo (largeur = surface_cible / profondeur), tirée
    du mix au prorata, le long de l'axe long → le mix émerge vraiment (T4/T5
    larges, T2 étroits). La typo finale est re-labellisée par la surface réelle.
    """
    from core.building_model.solver import (
        _TYPO_TARGET_SURFACE_M2,
        _reclassify_by_surface,
    )

    qx0, qy0, qx1, qy1 = quadrant.rect.bounds
    w, h = qx1 - qx0, qy1 - qy0
    if quadrant.long_axis == "horizontal":
        long_len, depth = w, h
    else:
        long_len, depth = h, w
    if depth <= 0 or long_len <= 0:
        return []

    # Typos éligibles à cette profondeur : largeur ≥ _MIN_APT_WIDTH_M ET
    # ≤ long_len. On garde l'ordre du mix (grandes typos d'abord = priorité aux
    # T4/T5 qui manquent), pondéré par la part du mix.
    order = [Typologie.T5, Typologie.T4, Typologie.T3, Typologie.T2, Typologie.T1,
             Typologie.STUDIO]
    _sum = sum(v for v in mix_typologique.values() if v > 0) or 1.0
    # LARGEUR CIBLE alignée sur le SEUIL DE RETYPAGE aval (2026-07-03). Le
    # relayout mono-façade fixe la typo finale par la LARGEUR de façade utile :
    # il faut ~N·2,6 + 2,0 m de façade pour N chambres (T3 N=2, T4 N=3, T5 N=4).
    # Slicer une typo à surface/profondeur (T4 = 78/8,7 = 9,0 m) tombait JUSTE
    # SOUS le seuil T4 (9,45 m) → le relayout la rétrogradait en T3 (mix 55/45/0
    # puis plafonné à 17 % de T4/T5). On vise donc directement seuil + petite
    # marge, borné par une largeur max « vendable » à cette profondeur.
    _NCH = {Typologie.T2: 1, Typologie.T3: 2, Typologie.T4: 3, Typologie.T5: 4,
            Typologie.T1: 0, Typologie.STUDIO: 0}
    _MARGIN = 0.5   # au-dessus du seuil de retypage pour survivre au room-fitting
    plan: list[tuple[Typologie, float]] = []  # (typo, width)
    for t in order:
        share = mix_typologique.get(t, 0.0) / _sum
        if share <= 0:
            continue
        n_ch = _NCH.get(t, 0)
        if n_ch >= 2:
            # largeur qui GARANTIT n_ch chambres au relayout (seuil + marge),
            # sans dépasser une largeur donnant une surface > cible + ~25 %.
            thr = n_ch * 2.6 + 2.0 - 0.35 + _MARGIN
            w_area = _TYPO_TARGET_SURFACE_M2.get(t, 58.0) / depth
            width = max(thr, w_area)
        else:
            width = _TYPO_TARGET_SURFACE_M2.get(t, 58.0) / depth
        if width < _MIN_APT_WIDTH_M or width > long_len + 0.01:
            continue
        plan.append((t, width, share))  # type: ignore[arg-type]

    if not plan:
        # aucune typo ne rentre proprement → fallback largeur uniforme T3.
        return slice_quadrant_into_apts(
            quadrant, Typologie.T3, _TYPO_TARGET_SURFACE_M2[Typologie.T3], id_prefix)

    # ── FILL PROPORTIONNEL À LARGEUR CIBLE (réécrit 2026-07-03) ─────────────
    # Root-cause du mix 55/45/0 : l'ancien fill calculait un n_target arrondi
    # puis un `scale` global qui DISTORDAIT toutes les largeurs — les slots
    # larges (T5 ~11,5 m, T4 ~9 m) étaient rabotés à ~8 m → le relayout mono-
    # façade (typo = f(largeur façade) : T4≥~9,5 m, T5≥~12 m) ne voyait plus que
    # des T2/T3. Ici on remplit long_len en POSANT chaque slot à SA largeur cible
    # (surface_typo/profondeur), choisi par déficit vs part du mix, SANS scale
    # global. Le petit reste (<1 largeur T2) est réparti également → largeurs
    # restent au voisinage de la cible → T4/T5 survivent au relayout. Universel.
    width_of = {t: w2 for t, w2, _ in plan}
    share_of = {t: s for t, _, s in plan}
    # normalise les parts sur les seules typos éligibles à cette profondeur
    _elig_sum = sum(share_of.values()) or 1.0
    share_of = {t: s / _elig_sum for t, s in share_of.items()}
    typos = [t for t, _, _ in plan]  # déjà triés grandes→petites (order)
    # ── APPORTIONNEMENT STABLE (largest-remainder / Hamilton) ───────────────
    # L'ancien greedy « plus gros déficit » était BANG-BANG : une seule typo
    # saturait un petit quadrant et faisait basculer tout le mix (55/45/0 <->
    # 38/18/44 selon ±2 % de brief). On calcule ici, DÉTERMINISTE :
    #   1. n_slots ≈ long_len / largeur_moyenne_pondérée (par la part du mix),
    #   2. counts[t] = round Hamilton de share_of[t] * n_slots (somme == n_slots),
    #   3. on pose les slots du plus LARGE au plus étroit pour tuiler proprement.
    # Résultat : le mix de sortie suit LINÉAIREMENT le brief → réglage stable.
    # n_slots dérivé d'une largeur de RÉFÉRENCE FIXE (~largeur d'un T3, indépendante
    # du brief) : sinon avg_w bougeait avec le brief et faisait basculer n_slots
    # d'un quadrant (donc 6 étages d'un coup) → mix bang-bang. Avec une réf fixe,
    # seul le mix des COMPTES change avec le brief → réponse lisse et réglable.
    _REF_W = 8.0
    n_slots = max(1, int(round(long_len / _REF_W)))
    # Hamilton : parts entières + plus grands restes.
    raw = {t: share_of[t] * n_slots for t in typos}
    counts = {t: int(raw[t]) for t in typos}
    rem = n_slots - sum(counts.values())
    for t in sorted(typos, key=lambda t: raw[t] - int(raw[t]), reverse=True)[:max(0, rem)]:
        counts[t] += 1
    # garantit ≥1 grande typo si le brief en demande et que la place existe.
    if sum(counts.values()) == 0:
        counts[typos[0]] = 1
    # ── RÉSERVE 1 T5 sur les LONGUES façades éclairées (2026-07-03) ─────────
    # Le mix quantifie grossièrement (6 étages identiques → 1 slot = 6 apts), donc
    # Hamilton arrondit souvent T5 à 0 même quand le brief en demande ~12 % : on
    # n'obtient alors QUE des T4. Pour matérialiser au moins un vrai T5 (4 ch,
    # séjour plafonné) sans gonfler le mix, on force 1 T5 UNIQUEMENT sur les
    # quadrants « longue façade » (long_len ≥ 24 m ≈ 2 logements larges = les
    # bandes de rue), en le prenant sur un T4 s'il y en a, sinon un T3. Les legs
    # /squares courts restent inchangés → +1 T5, −1 T4 (le mix T4/T5 est préservé,
    # juste rééquilibré vers T5). Universel : dépend de la longueur de façade.
    if (Typologie.T5 in width_of and share_of.get(Typologie.T5, 0.0) >= 0.08
            and long_len >= 32.0 and width_of[Typologie.T5] <= long_len
            and counts.get(Typologie.T5, 0) == 0):
        _donor = (Typologie.T4 if counts.get(Typologie.T4, 0) > 0
                  else (Typologie.T3 if counts.get(Typologie.T3, 0) > 0 else None))
        if _donor is not None:
            counts[_donor] -= 1
            counts[Typologie.T5] = counts.get(Typologie.T5, 0) + 1
    # séquence large→étroit (les grandes typos sur la façade, tuilage propre).
    bag: list[Typologie] = []
    for t in typos:  # typos déjà triés T5..STUDIO
        bag.extend([t] * counts[t])
    # Pose les slots à leur largeur cible tant qu'ils tiennent. Quand le PROCHAIN
    # slot du bag ne rentre plus, on NE gonfle PAS le dernier (cela ferait un coin
    # obèse re-scindé en 2 T3) : on comble le reliquat par des slots de la plus
    # GRANDE typo qui tient encore dans l'espace restant (≥ _MIN_APT_WIDTH_M).
    # Ainsi un leg de 16 m = 1 T4 (9,45 m) + 1 T2 (6,55 m), pas 2×8 m → T3/T3.
    # Pose D'ABORD tous les slots planifiés (comptes Hamilton) qui tiennent, en
    # ordre large→étroit (bag l'est déjà). Ceux qui ne tiennent pas sont sautés.
    seq: list[tuple[Typologie, float]] = []
    used = 0.0
    for t in bag:
        if width_of[t] <= (long_len - used) + 0.5:
            seq.append((t, width_of[t])); used += width_of[t]
    # Puis comble le RELIQUAT avec des slots de la plus grande typo qui tient
    # ENCORE dans l'espace restant. Comme les grandes typos planifiées sont déjà
    # posées, ce reliquat est petit → on n'y injecte pas de T4/T5 surnuméraires.
    while (long_len - used) >= _MIN_APT_WIDTH_M:
        remaining = long_len - used
        fit = next((t for t in typos if width_of[t] <= remaining + 0.5), None)
        if fit is None:
            break
        seq.append((fit, width_of[fit])); used += width_of[fit]
    if not seq:
        seq = [(Typologie.T3, long_len)]
    else:
        # Reliquat de largeur : on ne l'étale PAS uniformément (cela rabotait les
        # slots larges T4/T5 sous leur seuil de retypage et gonflait les étroits).
        # On l'ABSORBE dans les slots ÉTROITS (< seuil T4) d'abord — eux peuvent
        # grandir sans changer de typo — en préservant les slots larges à leur
        # largeur cible. Si tous les slots sont déjà larges, on étale le reste.
        slack = long_len - sum(w2 for _, w2 in seq)
        _T4_THR = 3 * 2.6 + 2.0 - 0.35  # ~9,45 m : seuil T4 aval
        if slack > 0.01:
            narrow_idx = [i for i, (_, w2) in enumerate(seq) if w2 < _T4_THR - 0.1]
            targets = narrow_idx if narrow_idx else list(range(len(seq)))
            add = slack / len(targets)
            seq = [(t, w2 + (add if i in targets else 0.0))
                   for i, (t, w2) in enumerate(seq)]
        elif slack < -0.01:
            # trop plein : rétrécit également (rare, borné par la troncature).
            add = slack / len(seq)
            seq = [(t, w2 + add) for t, w2 in seq]

    # ── ANTI-COIN-OBÈSE (fix 2026-07-03) ───────────────────────────────────
    # Le `scale` ci-dessus peut étirer un slot bien au-delà d'une largeur de
    # logement vendable (ex. 16,7 m à profondeur 8,7 m = 145 m² « T5 » monstre).
    # On SCINDE tout slot dépassant _MAX_APT_WIDTH_M en k parts égales (k =
    # ceil(w/_MAX)), tant que chaque part reste ≥ _MIN_APT_WIDTH_M. Résultat :
    # +d'apparts, aucun séjour géant, aucune cuisine orpheline. La typo de
    # chaque part est re-labellisée plus bas par sa surface réelle.
    # Deux critères de scission : largeur (> _MAX_APT_WIDTH_M) OU aire (> _MAX
    # _APT_AREA_M2). Le 2e attrape le « coin profond » : un slot à façade courte
    # mais grande aire (ex. 10,2 × 8,7 = 89 m²) fabrique 1 seule chambre + une
    # cuisine orpheline géante côté couloir. Le scinder en largeur redonne à
    # chaque part une façade suffisante → apts cohérents, 0 cuisine flottante.
    import math as _math
    # Aire MAX avant scission. Relevée à 120 m² (2026-07-03) pour laisser vivre un
    # T5 (~12 m × 8,7 m ≈ 104 m²) : un plafond à 80 m² scindait tout T4/T5 en T2/T3
    # (mix 55/45/0). Le relayout mono-façade plafonne le séjour et pose N chambres,
    # donc un slot ≤120 m² n'est plus un « coin obèse » ; seuls les slots vraiment
    # monstrueux (double-merge du core) restent scindés.
    _MAX_APT_AREA_M2 = 120.0
    _SPLIT_MIN_W = 5.0   # largeur mini d'une part scindée (un petit T2 tient à 5 m)
    _split_seq: list[tuple[Typologie, float]] = []
    for t, wdt in seq:
        area = wdt * depth
        k = 1
        if wdt > _MAX_APT_WIDTH_M + 0.01:
            k = max(k, _math.ceil(wdt / _MAX_APT_WIDTH_M))
        if area > _MAX_APT_AREA_M2 + 0.01:
            k = max(k, _math.ceil(area / _MAX_APT_AREA_M2))
        # ne pas descendre sous la largeur mini d'une part scindée
        while k > 1 and (wdt / k) < _SPLIT_MIN_W:
            k -= 1
        if k > 1:
            _split_seq.extend([(t, wdt / k)] * k)
        else:
            _split_seq.append((t, wdt))
    seq = _split_seq

    slots: list[ApartmentSlot] = []
    cursor = 0.0
    for i, (typo_hint, wdt) in enumerate(seq):
        if quadrant.long_axis == "horizontal":
            ax0, ax1 = qx0 + cursor, qx0 + cursor + wdt
            ay0, ay1 = qy0, qy1
        else:
            ay0, ay1 = qy0 + cursor, qy0 + cursor + wdt
            ax0, ax1 = qx0, qx1
        cursor += wdt
        poly = shp_box(ax0, ay0, ax1, ay1)
        position = "extremite" if i == 0 or i == len(seq) - 1 else "milieu"
        slots.append(ApartmentSlot(
            id=f"{id_prefix}{quadrant.name}_{i}",
            polygon=poly,
            surface_m2=poly.area,
            target_typologie=_reclassify_by_surface(poly.area, typo_hint),
            orientations=list(quadrant.facade_sides),
            position_in_floor=position,
        ))
    return slots


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
    # Cages d'escalier/ascenseur SECONDAIRES (2e égress). Pour le U il y a 2
    # cages aux 2 angles intérieurs : la principale part dans ``core``, la 2e
    # est listée ici pour rester VISIBLE et distincte au rendu (et compter comme
    # issue de secours #2). Vide par défaut (L n'a qu'une cage).
    secondary_cores: tuple[ShapelyPolygon, ...] = ()


# Realistic stair+lift core footprint. A code-compliant escalier QUART TOURNANT
# (18 marches) tient dans ~2,6 × 2,6 m ; la gaine ASC PMR ~1,6 m ; le palier
# d'étage (landing PMR donnant accès aux deux depuis le couloir) ~1,4 m clair.
# Côte à côte : escalier (~2,6 m) + ASC (~1,6 m) ≈ 4,2 m de large, ~3,1 m de
# profond → un bloc ≈ 13 m² SUFFIT. Au-delà, le core n'est plus de la
# circulation mais un gros rectangle blanc mangeant de la SHAB — le défaut
# « gros palier 160 vide au centre » (23 m²) mesuré 2026-07-03. On CAPE donc le
# core à `_CORE_MAX_AREA_M2` (≈ bande PMR + esc + ASC), ancré contre le couloir,
# et on rend TOUTE la bande restante du slot (côté opposé au couloir) comme un
# rectangle PROPRE fusionné dans le logement voisin (SHAB récupérée).
_CORE_MAX_LEN_M = 5.5      # (héritage) profondeur max avant cap — conservé pour compat
_CORE_MAX_AREA_M2 = 13.0   # emprise max du core central (esc quart-tournant + ASC + palier PMR)
_CORE_BLOCK_W_M = 4.3      # largeur max du bloc esc+ASC (perpendiculaire à la profondeur)
_CORE_MIN_DEPTH_M = 2.7    # profondeur mini pour loger un quart-tournant + palier PMR

# 2e CAGE (égress secondaire) : CAPÉE au même titre que le core central pour ne
# pas laisser un gros palier blanc mangeant l'apt voisin (défaut user #1,
# 2026-07-03). Escalier d'égress + gaine ASC + palier PMR mini ≈ 3,0 × 3,6 m.
_SECONDARY_CAGE_SIDE_M = 3.0
_SECONDARY_CAGE_DEPTH_M = 3.6


def _place_core_in_landlocked_slot(
    slot: ApartmentSlot,
    corridor: ShapelyPolygon,
    core_surface_m2: float,
    apt_slots: list[ApartmentSlot] | None = None,
) -> tuple[ShapelyPolygon, list[ShapelyPolygon]]:
    """Place a COMPACT core (esc quart-tournant + ASC + palier PMR, ≤ ~13 m²)
    against the corridor edge of a landlocked slot, and return the freed rest of
    the slot as CLEAN axis-aligned rectangles to be merged into neighbours.

    Returns ``(core_polygon, freed_rectangles)``.

    Le core est un bloc minimal (`_CORE_MAX_AREA_M2`, largeur `_CORE_BLOCK_W_M`)
    ANCRÉ dans le coin du slot qui touche le couloir ; tout le reste du slot est
    re-tuilé en ≤ 2 rectangles PROPRES (bande opposée pleine largeur + bande
    latérale) qui fusionnent EXACTEMENT dans les logements voisins alignés → la
    SHAB est récupérée sans dentelé et sans poche blanche, les séjours voisins
    restent sous leur cap. Universel : dérivé de la géométrie du slot + du contact
    réel couloir (aucune constante de site).

    NB (2026-07-08) : ce placement laisse la cage AU BORD DU COULOIR (elle peut
    donc « flotter » dans le gris). L'INTÉGRATION de la cage — la coller au bord
    de la COUR + à un mur d'apt — est faite EN AVAL dans le pipeline (glissement
    ``_snap_cage_to_courtyard_corner``) : on ne touche PAS ici au tuilage des apts
    (qui casse leur gabarit si on déplace le core), on ne bouge QUE le polygone de
    la cage vers le coin cour∩apt de l'anneau. ``apt_slots`` reste accepté pour
    compat (non utilisé ici).
    """
    _ = apt_slots
    sx0, sy0, sx1, sy1 = slot.polygon.bounds
    sw, sh = sx1 - sx0, sy1 - sy0

    # ── 1. Quel(s) bord(s) du slot touche(nt) le couloir ? Le core s'y adosse ────
    cb = corridor.buffer(0.05) if (corridor is not None and not corridor.is_empty) else None

    def _edge_contact(x0, y0, x1, y1) -> float:
        if cb is None:
            return 0.0
        return shp_box(x0, y0, x1, y1).intersection(cb).area

    top_c = _edge_contact(sx0, sy1 - 0.4, sx1, sy1 + 0.4)
    bot_c = _edge_contact(sx0, sy0 - 0.4, sx1, sy0 + 0.4)
    right_c = _edge_contact(sx1 - 0.4, sy0, sx1 + 0.4, sy1)
    left_c = _edge_contact(sx0 - 0.4, sy0, sx0 + 0.4, sy1)

    vert_side = "top" if top_c >= bot_c else "bottom"
    vert_c = max(top_c, bot_c)
    horiz_side = "right" if right_c >= left_c else "left"
    horiz_c = max(right_c, left_c)

    block_w = min(_CORE_BLOCK_W_M, sw)
    depth = min(sh, max(_CORE_MIN_DEPTH_M, _CORE_MAX_AREA_M2 / block_w))
    if slot.polygon.area <= _CORE_MAX_AREA_M2 + 0.5:
        return slot.polygon, []

    x_anchor_right = (horiz_c > 0.3 and horiz_side == "right") or horiz_c <= 0.3
    if x_anchor_right:
        cx0, cx1 = sx1 - block_w, sx1
    else:
        cx0, cx1 = sx0, sx0 + block_w
    if (vert_c <= 0.3 and bot_c < top_c) or vert_side == "top":
        cy0, cy1 = sy1 - depth, sy1
    else:
        cy0, cy1 = sy0, sy0 + depth
    core = shp_box(cx0, cy0, cx1, cy1)

    # ── 2. Re-tuiler le RESTE du slot en rectangles PROPRES (SHAB récupérée) ─────
    freed: list[ShapelyPolygon] = []
    if cy1 >= sy1 - 1e-6:            # core ancré en HAUT → bande opposée en bas
        opp = shp_box(sx0, sy0, sx1, cy0)
        if x_anchor_right:
            lat = shp_box(sx0, cy0, cx0, sy1)
        else:
            lat = shp_box(cx1, cy0, sx1, sy1)
    else:                            # core ancré en BAS → bande opposée en haut
        opp = shp_box(sx0, cy1, sx1, sy1)
        if x_anchor_right:
            lat = shp_box(sx0, sy0, cx0, cy1)
        else:
            lat = shp_box(cx1, sy0, sx1, cy1)
    for r in (opp, lat):
        if r is not None and not r.is_empty and r.area >= 1.0:
            freed.append(r)
    return core, freed


def _snap_cage_to_courtyard_corner(
    cage: ShapelyPolygon,
    cour: ShapelyPolygon,
    apts: ShapelyPolygon,
    corridor: ShapelyPolygon,
) -> ShapelyPolygon:
    """Glisse la CAGE (rectangle esc+ASC) vers un COIN de l'anneau de la cour où
    elle partage ≥ 2 m avec la COUR ET ≥ 2 m avec un MUR D'APT, sans recouvrir ni
    la cour ni un apt, en restant desservie par le couloir. Retourne la cage
    déplacée (ou l'originale si aucun coin conforme).

    Motivation (2026-07-08, demande user) : au centre du coude la cage « flotte »
    dans le couloir (contact apt = 0). On la RECOLLE à un coin cour∩apt : escalier
    sur cour assumé (jour), adossé au bâti. On NE touche PAS aux logements (leur
    gabarit casse si on les re-tuile) : seul le polygone cage bouge. On balaie les
    positions candidates = coins de la cour, la cage plaquée contre le mur d'apt
    voisin, et on garde la 1re qui : cage∩cour≈0, cage∩apt≈0, contact cour ≥ 2 m,
    contact apt ≥ 2 m, cage ⊂ (couloir ∪ ancienne empreinte cage) [desservie].
    Universel : dérivé de la géométrie cour/apts/couloir (aucune constante de site).
    """
    if cour is None or cour.is_empty or apts is None or apts.is_empty:
        return cage
    cb = cage.bounds
    cw, ch = cb[2] - cb[0], cb[3] - cb[1]
    ox0, oy0, ox1, oy1 = cour.bounds
    reach = (corridor.buffer(0.30).union(cage.buffer(0.05))
             if corridor is not None and not corridor.is_empty else cage.buffer(0.05))
    apts_b = apts.buffer(0.02)
    # bord de l'anneau côté apts : la cage doit plaquer un MUR d'apt qui borde la
    # cour, PAS l'arête de la cour elle-même (l'anneau 1,40 m les sépare). On
    # cherche donc, à chaque coin, le mur d'apt LE PLUS PROCHE et on y adosse la
    # cage. Bornes des apts qui bordent la cour, dilatées de l'anneau (~1,6 m).
    _ring = 1.6

    # Positions de référence des MURS D'APT bordant la cour : les x/y des arêtes
    # de la boîte-englobante des apts qui touchent la cour (là où la cage peut se
    # plaquer). On récupère les coords des sommets apts proches de la cour.
    _near = apts.intersection(cour.buffer(2.0))
    _xs, _ys = set(), set()
    for _g in (_near.geoms if _near.geom_type in ("MultiPolygon", "GeometryCollection")
               else [_near]):
        if _g.is_empty or not hasattr(_g, "exterior"):
            continue
        for _px, _py in list(_g.exterior.coords):
            _xs.add(round(_px, 2)); _ys.add(round(_py, 2))

    cands: list[ShapelyPolygon] = []
    for (w, h) in ((max(cw, ch), min(cw, ch)), (min(cw, ch), max(cw, ch))):
        # (A) Cage dans la bande de couloir AU-DESSUS / EN-DESSOUS de la cour (bord
        #     bas/haut de la cage sur l'arête cour), glissée en x pour qu'un de ses
        #     bords verticaux tombe sur un mur d'apt (x ∈ _xs). Idem faces E/O.
        for _ax in _xs:
            # cage au-dessus de la cour, bord gauche OU droit sur le mur d'apt
            cands.append(shp_box(_ax, oy1, _ax + w, oy1 + h))          # au-dessus, gauche sur mur
            cands.append(shp_box(_ax - w, oy1, _ax, oy1 + h))          # au-dessus, droite sur mur
            cands.append(shp_box(_ax, oy0 - h, _ax + w, oy0))         # en-dessous, gauche sur mur
            cands.append(shp_box(_ax - w, oy0 - h, _ax, oy0))         # en-dessous, droite sur mur
        for _ay in _ys:
            # cage à gauche/droite de la cour, bord bas OU haut sur le mur d'apt
            cands.append(shp_box(ox0 - w, _ay, ox0, _ay + h))         # à gauche, bas sur mur
            cands.append(shp_box(ox0 - w, _ay - h, ox0, _ay))         # à gauche, haut sur mur
            cands.append(shp_box(ox1, _ay, ox1 + w, _ay + h))         # à droite, bas sur mur
            cands.append(shp_box(ox1, _ay - h, ox1 + w, _ay))         # à droite, haut sur mur
        # (B) coins de la cour, plaqués tangents (fallback si (A) ne donne rien).
        for off in (0.0, 0.2, 0.4):
            cands.append(shp_box(ox0 - off, oy1, ox0 - off + w, oy1 + h))
            cands.append(shp_box(ox1 + off - w, oy1, ox1 + off, oy1 + h))
            cands.append(shp_box(ox0 - off, oy0 - h, ox0 - off + w, oy0))
            cands.append(shp_box(ox1 + off - w, oy0 - h, ox1 + off, oy0))

    def _ok(c: ShapelyPolygon) -> tuple[bool, float, float]:
        if c.intersection(cour).area > 0.5 or c.intersection(apts_b).area > 0.5:
            return (False, 0.0, 0.0)
        clen = c.boundary.intersection(cour.boundary.buffer(0.30)).length
        blen = c.boundary.intersection(apts.boundary.buffer(0.08)).length
        served = reach.contains(c.buffer(-0.10))
        return (clen >= 2.0 and blen >= 2.0 and served, clen, blen)

    best = None
    best_score = -1.0
    for c in cands:
        ok, clen, blen = _ok(c)
        if ok:
            # préférer un contact équilibré cour+apt, cage proche de l'originale.
            _dist = cage.centroid.distance(c.centroid)
            sc = min(clen, 6.0) + min(blen, 6.0) - 0.05 * _dist
            if sc > best_score:
                best, best_score = c, sc
    return best if best is not None else cage


def _place_cage_in_atrium(
    cage: ShapelyPolygon,
    cour: ShapelyPolygon,
    corridor: ShapelyPolygon,
) -> ShapelyPolygon | None:
    """PARTI ATRIUM PLANTÉ (2026-07-09, demande user) : place le NOYAU esc+ASC
    À L'INTÉRIEUR de l'emprise de la COUR (sur l'herbe), plaqué contre UNE face de
    la cour qui donne sur le COULOIR — on accède au noyau directement depuis la
    circulation, et l'ANNEAU PLANTÉ (cour − noyau) l'entoure sur les 3 autres faces.
    La cour devient un ATRIUM : on monte à travers un jardin sous verrière.

    Retourne le rectangle-noyau REPOSITIONNÉ dans la cour (≥ 2 m sur le couloir sur
    UNE face, anneau planté ≥ ~15 m² autour), ou None si la cour est trop petite
    pour loger le noyau + un anneau (dégradé gracieux : on garde le snap tangent).

    Universel : dérivé de la géométrie cour/couloir (aucune constante de site). La
    face d'accès choisie est celle de la cour dont le bord longe le PLUS le couloir
    (contact circulation maximal), le noyau y est plaqué et centré sur les 2 autres
    axes pour un anneau régulier autour."""
    if cour is None or cour.is_empty or cour.geom_type != "Polygon":
        return None
    cb = cage.bounds
    cw, ch = cb[2] - cb[0], cb[3] - cb[1]
    ox0, oy0, ox1, oy1 = cour.bounds
    cour_w, cour_h = ox1 - ox0, oy1 - oy0
    # Le noyau doit tenir DANS la cour en laissant un anneau planté d'au moins ~1 m
    # sur les 3 faces non-couloir. On accepte les 2 orientations du noyau.
    corr = (corridor if corridor is not None and not corridor.is_empty else None)
    best = None
    best_score = -1.0
    for (w, h) in ((cw, ch), (ch, cw)):
        if w > cour_w - 0.2 or h > cour_h - 0.2:
            continue
        # 4 faces d'ancrage : noyau plaqué contre un bord de la cour, centré sur
        # l'axe orthogonal → anneau régulier autour des 3 autres faces.
        cx_mid = (ox0 + ox1) / 2.0
        cy_mid = (oy0 + oy1) / 2.0
        anchors = {
            "S": shp_box(cx_mid - w / 2, oy0, cx_mid + w / 2, oy0 + h),
            "N": shp_box(cx_mid - w / 2, oy1 - h, cx_mid + w / 2, oy1),
            "O": shp_box(ox0, cy_mid - h / 2, ox0 + w, cy_mid + h / 2),
            "E": shp_box(ox1 - w, cy_mid - h / 2, ox1, cy_mid + h / 2),
        }
        for _face, cand in anchors.items():
            if not cour.buffer(0.05).contains(cand):
                continue
            ring = cour.difference(cand).area
            if ring < 15.0:            # anneau planté insuffisant
                continue
            # contact couloir : la face plaquée de la cour longe-t-elle le couloir ?
            # On mesure la longueur du bord du noyau (= bord de la cour sur cette
            # face) qui est à ≤ 0,30 m du couloir.
            if corr is not None:
                corr_len = cand.boundary.intersection(
                    corr.buffer(0.30)).length
            else:
                corr_len = 0.0
            if corr_len < 2.0:
                continue
            # score : max contact couloir, puis anneau le plus régulier (grand).
            sc = min(corr_len, 6.0) + 0.02 * ring
            if sc > best_score:
                best, best_score = cand, sc
    if best is not None:
        return best
    # FALLBACK : aucune face ne longe le couloir ≥ 2 m (cour non bordée de couloir
    # sur un côté droit) — on centre quand même le noyau dans la cour, la face la
    # plus proche du couloir servant d'accès (l'anneau reste ≥ 15 m² si la cour est
    # assez grande). Sinon None (on garde le snap tangent v23).
    for (w, h) in ((cw, ch), (ch, cw)):
        if w > cour_w - 0.2 or h > cour_h - 0.2:
            continue
        cand = shp_box((ox0 + ox1) / 2 - w / 2, (oy0 + oy1) / 2 - h / 2,
                       (ox0 + ox1) / 2 + w / 2, (oy0 + oy1) / 2 + h / 2)
        if cour.buffer(0.05).contains(cand) and cour.difference(cand).area >= 15.0:
            return cand
    return None


def _merge_remainder_with_neighbor(
    remainder: ShapelyPolygon,
    slots: list[ApartmentSlot],
) -> list[ApartmentSlot]:
    """Attempt to merge `remainder` (leftover from core carve) with an
    adjacent apt slot. Returns a new slots list.

    Merge rule: the merged shape must be a clean axis-aligned rectangle
    (same y-range if extending east/west, same x-range if extending
    north/south). Otherwise discard the remainder.
    """
    if remainder is None or remainder.is_empty:
        return slots
    rx0, ry0, rx1, ry1 = remainder.bounds
    TOL = 0.2

    def _bounds(p):
        return p.bounds

    # Find a neighbor whose edge touches the remainder and whose
    # perpendicular range matches exactly — merged shape is a rectangle.
    for i, s in enumerate(slots):
        sx0, sy0, sx1, sy1 = _bounds(s.polygon)
        # Neighbor to WEST: its east edge touches remainder's west edge,
        # same y-range → extend east
        if abs(sx1 - rx0) < TOL and abs(sy0 - ry0) < TOL and abs(sy1 - ry1) < TOL:
            new_poly = shp_box(sx0, sy0, rx1, sy1)
            new_slots = list(slots)
            new_slots[i] = ApartmentSlot(
                id=s.id, polygon=new_poly, surface_m2=new_poly.area,
                target_typologie=s.target_typologie,
                orientations=s.orientations,
                position_in_floor=s.position_in_floor,
            )
            return new_slots
        # Neighbor to EAST
        if abs(sx0 - rx1) < TOL and abs(sy0 - ry0) < TOL and abs(sy1 - ry1) < TOL:
            new_poly = shp_box(rx0, sy0, sx1, sy1)
            new_slots = list(slots)
            new_slots[i] = ApartmentSlot(
                id=s.id, polygon=new_poly, surface_m2=new_poly.area,
                target_typologie=s.target_typologie,
                orientations=s.orientations,
                position_in_floor=s.position_in_floor,
            )
            return new_slots
        # Neighbor to SOUTH
        if abs(sy1 - ry0) < TOL and abs(sx0 - rx0) < TOL and abs(sx1 - rx1) < TOL:
            new_poly = shp_box(sx0, sy0, sx1, ry1)
            new_slots = list(slots)
            new_slots[i] = ApartmentSlot(
                id=s.id, polygon=new_poly, surface_m2=new_poly.area,
                target_typologie=s.target_typologie,
                orientations=s.orientations,
                position_in_floor=s.position_in_floor,
            )
            return new_slots
        # Neighbor to NORTH
        if abs(sy0 - ry1) < TOL and abs(sx0 - rx0) < TOL and abs(sx1 - rx1) < TOL:
            new_poly = shp_box(sx0, ry0, sx1, sy1)
            new_slots = list(slots)
            new_slots[i] = ApartmentSlot(
                id=s.id, polygon=new_poly, surface_m2=new_poly.area,
                target_typologie=s.target_typologie,
                orientations=s.orientations,
                position_in_floor=s.position_in_floor,
            )
            return new_slots
    # No clean rectangle merge — discard remainder (wasted space).
    return slots


def _absorb_strip_into_neighbor(
    strip: ShapelyPolygon,
    slots: list[ApartmentSlot],
    max_apt_area: float = 95.0,
) -> tuple[list[ApartmentSlot], ShapelyPolygon | None]:
    """Grow a neighbouring apt to SWALLOW a freed rectangular strip, TOLERANT to
    a small perpendicular offset (the L-decomposition leaves ~0,3 m seams).

    Complète ``_merge_remainder_with_neighbor`` (qui exige un alignement EXACT)
    pour le cas du core compact : la bande libérée pleine-largeur ne s'aligne pas
    au mm près avec le voisin sud/nord (jointure ~0,3 m du L). Ici on accepte un
    voisin dont la plage PERPENDICULAIRE CONTIENT (à ~0,6 m) celle de la bande :
    on étend le voisin sur SA plage (⇒ rectangle propre couvrant toute la bande),
    sans dépasser ``max_apt_area`` (anti-coin-obèse). Retourne (slots, reste) où
    ``reste`` = None si absorbé, sinon la bande inchangée (pour tenter un autre
    voisin / la laisser au reclaim aval)."""
    if strip is None or strip.is_empty or strip.area < 1.0:
        return slots, None
    rx0, ry0, rx1, ry1 = strip.bounds
    SNAP = 0.6
    best_i = None
    best_poly = None
    for i, s in enumerate(slots):
        sx0, sy0, sx1, sy1 = s.polygon.bounds
        # SOUTH neighbour (its top edge meets strip bottom), x-range ⊇ strip.
        if abs(sy1 - ry0) < SNAP and sx0 <= rx0 + SNAP and sx1 >= rx1 - SNAP:
            cand = shp_box(sx0, sy0, sx1, ry1)
        # NORTH neighbour (its bottom edge meets strip top), x-range ⊇ strip.
        elif abs(sy0 - ry1) < SNAP and sx0 <= rx0 + SNAP and sx1 >= rx1 - SNAP:
            cand = shp_box(sx0, ry0, sx1, sy1)
        # WEST neighbour (its east edge meets strip west), y-range ⊇ strip.
        elif abs(sx1 - rx0) < SNAP and sy0 <= ry0 + SNAP and sy1 >= ry1 - SNAP:
            cand = shp_box(sx0, sy0, rx1, sy1)
        # EAST neighbour (its west edge meets strip east), y-range ⊇ strip.
        elif abs(sx0 - rx1) < SNAP and sy0 <= ry0 + SNAP and sy1 >= ry1 - SNAP:
            cand = shp_box(rx0, sy0, sx1, sy1)
        else:
            continue
        if cand.area > max_apt_area + 0.5:
            continue
        # Prefer the SMALLEST resulting apt (spreads SHAB, avoids obese corner).
        if best_poly is None or cand.area < best_poly.area:
            best_i, best_poly = i, cand
    if best_i is None:
        return slots, strip
    s = slots[best_i]
    new_slots = list(slots)
    new_slots[best_i] = ApartmentSlot(
        id=s.id, polygon=best_poly, surface_m2=best_poly.area,
        target_typologie=s.target_typologie, orientations=s.orientations,
        position_in_floor=s.position_in_floor,
    )
    return new_slots, None


def _split_oversized_slots(
    slots: list[ApartmentSlot],
    footprint: ShapelyPolygon,
    voirie_orientations: tuple[str, ...] | None,
) -> list[ApartmentSlot]:
    """Scinde tout slot devenu OBÈSE après merges/carves du core.

    Le merge du reliquat de core dans un voisin peut fabriquer un slot très large
    (ex. 16,7 m ou 10,2 m de large × 8,7 m = 90-145 m²) : « coin obèse » qui, en
    aval, produit un séjour géant + une cuisine orpheline. On le recoupe le long
    de son AXE LONG en k parts égales (k = ceil(dim_longue / _MAX_APT_WIDTH_M) et
    ceil(aire / _MAX_APT_AREA_M2)), tant que chaque part reste ≥ _SPLIT_MIN_W.
    Chaque part est re-labellisée par sa surface réelle. Universel (toute L).
    """
    import math as _math
    from core.building_model.solver import _reclassify_by_surface

    # Cohérent avec slice_quadrant_by_mix : 120 m² laisse vivre les T5 (~104 m²).
    _MAX_APT_AREA_M2 = 120.0
    _SPLIT_MIN_W = 5.0

    def _lit_subrange(part: ShapelyPolygon, axis_x: bool) -> tuple[float, float] | None:
        """Sous-intervalle ÉCLAIRÉ (contact rue/cour) le long de l'axe long.
        Retourne (lo, hi) en coord monde le long de l'axe long, ou None. Sert à
        (a) mesurer la longueur de façade lumineuse et (b) COUPER le slot pile à
        la limite lit/aveugle (coin aveugle profond : apt06, 12,6 m large / 8 m
        lit → part gauche lumineuse gardée, part droite aveugle abandonnée)."""
        sides = _compute_exterior_facades(part, footprint, voirie_orientations)
        if not sides:
            return None
        px0, py0, px1, py1 = part.bounds
        fp_b = footprint.boundary.buffer(0.15)
        lo, hi = float("inf"), float("-inf")
        for sd in sides:
            if sd in ("sud", "nord") and axis_x:
                yv = py0 if sd == "sud" else py1
                inter = LineString([(px0, yv), (px1, yv)]).intersection(fp_b)
            elif sd in ("ouest", "est") and not axis_x:
                xv = px0 if sd == "ouest" else px1
                inter = LineString([(xv, py0), (xv, py1)]).intersection(fp_b)
            else:
                continue
            if inter.is_empty:
                continue
            b = inter.bounds
            lo = min(lo, b[0] if axis_x else b[1])
            hi = max(hi, b[2] if axis_x else b[3])
        return (lo, hi) if hi > lo else None

    out: list[ApartmentSlot] = []
    for s in slots:
        x0, y0, x1, y1 = s.polygon.bounds
        w, h = x1 - x0, y1 - y0
        long_len, along_x = (w, True) if w >= h else (h, False)
        area = s.polygon.area
        k = 1
        if long_len > _MAX_APT_WIDTH_M + 0.01:
            k = max(k, _math.ceil(long_len / _MAX_APT_WIDTH_M))
        if area > _MAX_APT_AREA_M2 + 0.01:
            k = max(k, _math.ceil(area / _MAX_APT_AREA_M2))
        # ── COIN AVEUGLE PROFOND (défaut user #3, cuisine 37,5 m² : 2026-07-03) ──
        # Un slot dont la LARGEUR (axe long) dépasse sa FAÇADE ÉCLAIRÉE d'un pan
        # aveugle profond (≥ _BLIND_TRIM_M, contre mitoyen / retour de L) devient
        # en aval un séjour géant + une CUISINE orpheline hors gabarit. On COUPE
        # pile à la limite lit/aveugle : la part lumineuse reste un logement sain,
        # la part aveugle est ABANDONNÉE (récupérée par _reclaim_pockets dans le
        # séjour du voisin en aval — jamais un logement/pièce borgne). Universel.
        _BLIND_TRIM_M = 3.5   # ≥ un vrai pan de pièce aveugle (pas un sliver de mur)
        _sub = _lit_subrange(s.polygon, along_x)
        if _sub is not None:
            _slo, _shi = _sub
            _axis_lo = x0 if along_x else y0
            _axis_hi = x1 if along_x else y1
            blind_lo = _slo - _axis_lo      # pan aveugle côté bas
            blind_hi = _axis_hi - _shi      # pan aveugle côté haut
            if max(blind_lo, blind_hi) >= _BLIND_TRIM_M:
                # coupe à la limite du pan aveugle le plus large ; garde le lit.
                if blind_hi >= blind_lo:
                    keep = (shp_box(x0, y0, _shi, y1) if along_x
                            else shp_box(x0, y0, x1, _shi))
                else:
                    keep = (shp_box(_slo, y0, x1, y1) if along_x
                            else shp_box(x0, _slo, x1, y1))
                if keep.area >= _SPLIT_MIN_W * 3.0:  # reste un logement vendable
                    sides2 = _compute_exterior_facades(keep, footprint,
                                                       voirie_orientations)
                    out.append(ApartmentSlot(
                        id=s.id, polygon=keep, surface_m2=keep.area,
                        target_typologie=_reclassify_by_surface(
                            keep.area, s.target_typologie),
                        orientations=list(sides2),
                        position_in_floor=s.position_in_floor))
                    continue   # pan aveugle abandonné → reclaim en aval
        while k > 1 and (long_len / k) < _SPLIT_MIN_W:
            k -= 1
        if k <= 1:
            out.append(s)
            continue
        step = long_len / k
        boxes: list = []
        lit: list[bool] = []
        for i in range(k):
            if along_x:
                part = shp_box(x0 + i * step, y0, x0 + (i + 1) * step, y1)
            else:
                part = shp_box(x0, y0 + i * step, x1, y0 + (i + 1) * step)
            boxes.append(part)
            lit.append(bool(_compute_exterior_facades(part, footprint, voirie_orientations)))

        # Une part SANS façade (coin aveugle contre 2 mitoyens) ne doit PAS
        # devenir un logement : elle fabriquerait une pièce géante borgne
        # (cuisine orpheline, défaut user #2). On la FUSIONNE dans la part
        # éclairée adjacente la plus proche (extension en profondeur, absorbée
        # au séjour borné par le peigne). Si aucune part n'est éclairée → pas de
        # scission (le slot d'origine est conservé, traité en amont).
        lit_idx = [i for i, b in enumerate(lit) if b]
        if not lit_idx:
            out.append(s)
            continue
        # Chaque part ÉCLAIRÉE = un logement. Les parts BORGNES (coin aveugle
        # contre 2 mitoyens) sont ABANDONNÉES ici : elles seraient des pièces
        # géantes borgnes (cuisine orpheline, défaut #2). Le vide résiduel est
        # ensuite récupéré par la circulation / 2e cage / _reclaim_pockets en
        # aval — jamais un logement borgne, jamais une pièce hors logement.
        for n, i in enumerate(lit_idx):
            part = boxes[i]
            sides2 = _compute_exterior_facades(part, footprint, voirie_orientations)
            out.append(ApartmentSlot(
                id=f"{s.id}_s{n}", polygon=part, surface_m2=part.area,
                target_typologie=_reclassify_by_surface(part.area, s.target_typologie),
                orientations=list(sides2),
                position_in_floor=s.position_in_floor,
            ))
    return out


def compute_l_layout(
    footprint: ShapelyPolygon,
    mix_typologique: dict[Typologie, float],
    core_surface_m2: float,
    corridor_width: float = 1.6,
    id_prefix: str = "",
    voirie_orientations: tuple[str, ...] | None = None,
) -> LLayoutResult | None:
    """Generate core + L-corridor + apt slots for an L-shaped footprint.

    Algorithm (per-slot landlocked detection, 2026-04-24):
    1. Slice ALL quadrants (including ne_bar) into slots.
    2. For each slot, compute its exterior façades against the footprint.
    3. Find landlocked slots (zero exterior façades). One is sacrificed
       to host the core.
    4. Place the core inside the sacrificed slot touching the corridor.
    5. Merge the leftover piece of the sacrificed slot with its neighbor
       (if the merged shape is a clean rectangle) or discard it.

    Returns None if the footprint is not a clean L (caller should fall
    back to legacy wing-par-wing layout).
    """
    d = decompose_l(footprint)
    if d is None:
        return None

    corridor = build_l_corridor(d, corridor_width=corridor_width)
    quadrants = compute_l_quadrants(d, footprint, corridor_width=corridor_width)

    # Assign typology from the FULL mix (T1..T5), not just T2/T3.
    # Root-cause fix (2026-07-03) : l'ancien code ne lisait que T2/T3 → T4/T5
    # impossibles + biais T2 massif (mix L 63/36/1). On dérive UNE surface-cible
    # moyenne pondérée par le mix (comme solver.py:730-733) ; on découpe chaque
    # quadrant à cette surface, puis on RE-LABELLISE chaque slot par sa surface
    # RÉELLE (_reclassify_by_surface) → les slots profonds (bar) sortent en
    # T4/T5, les fins (leg) en T2/T3 → le mix émerge de la géométrie.
    _mix_sum = sum(v for v in mix_typologique.values() if v > 0)
    if _mix_sum <= 0:
        return None
    # Slice ALL quadrants into slots — including ne_bar — so we can test
    # landlocked-ness per-slot rather than per-quadrant. Variable width per
    # the FULL mix so T2/T3/T4/T5 all emerge (fix 2026-07-03).
    slots: list[ApartmentSlot] = []
    for q in quadrants:
        slots.extend(slice_quadrant_by_mix(
            quadrant=q, mix_typologique=mix_typologique, id_prefix=id_prefix,
        ))

    # Recompute exterior façades PER SLOT (a slot inside ne_bar can have
    # an east façade even if its sibling in the same quadrant is landlocked).
    # The per-quadrant orientation list was a coarse approximation.
    refined_slots: list[ApartmentSlot] = []
    for s in slots:
        sides = _compute_exterior_facades(s.polygon, footprint, voirie_orientations)
        refined_slots.append(ApartmentSlot(
            id=s.id, polygon=s.polygon, surface_m2=s.surface_m2,
            target_typologie=s.target_typologie,
            orientations=list(sides),
            position_in_floor=s.position_in_floor,
        ))
    slots = refined_slots

    # Identify landlocked slots (zero exterior façades).
    landlocked = [s for s in slots if len(s.orientations) == 0]

    if landlocked:
        # Sacrifice the largest landlocked slot (most space for core).
        sacrificed = max(landlocked, key=lambda s: s.polygon.area)
        core, freed_rects = _place_core_in_landlocked_slot(
            sacrificed, corridor, core_surface_m2, apt_slots=slots,
        )
        # Remove the sacrificed slot from the list.
        slots = [s for s in slots if s.id != sacrificed.id]
        # Merge EACH freed rectangle (compact-core carve leftovers) into an
        # aligned neighbour so the elbow space becomes SHAB, not a blank palier.
        # The full-width band opposite the corridor merges into the south/north
        # leg apt; the lateral band merges into the west/east neighbour. Bigger
        # rectangles first (biggest SHAB win first). We try the EXACT-align merge
        # first, then the TOLERANT strip-absorb (the L-decomposition leaves ~0,3 m
        # seams that defeat the exact match). Whatever an oversized neighbour
        # swallows is re-split downstream by ``_split_oversized_slots``.
        _unabsorbed: list[ShapelyPolygon] = []
        for _fr in sorted(freed_rects, key=lambda g: -g.area):
            if _fr is None or _fr.is_empty or _fr.area < 1.0:
                continue
            _rx0, _ry0, _rx1, _ry1 = _fr.bounds
            _rect = shp_box(_rx0, _ry0, _rx1, _ry1)
            _before = [s.polygon.area for s in slots]
            slots = _merge_remainder_with_neighbor(_rect, slots)
            if [s.polygon.area for s in slots] != _before:
                continue
            # exact merge did nothing → tolerant absorb into a LIT neighbour that
            # keeps the merged apt healthy (a lit façade spans the strip). The
            # blind-trim downstream re-abandons any deep BLIND extension, so we
            # only keep here what a lit neighbour genuinely swallows.
            slots, _rest = _absorb_strip_into_neighbor(
                _rect, slots, max_apt_area=118.0)
            if _rest is not None:
                _unabsorbed.append(_rest)
        # Un rect libéré qui n'a PU être récupéré en SHAB est une POCHE AVEUGLE du
        # centre profond du L (aucune façade — impossible à éclairer). Plutôt que
        # (a) le laisser en BLANC (poche non attribuée = défaut visuel) ou (b) le
        # rendre en gros palier vide (le défaut d'origine), on le rattache au
        # CORRIDOR : le centre profond d'un L double-loaded EST une zone de
        # circulation. Le couloir absorbe la poche de façon CONTINUE (spine reliant
        # les 2 branches), pas un rectangle blanc isolé. La cellule ``palier``
        # reste le core compact ≤13 m² ; ce surplus compte comme couloir (le gate
        # borne la circulation à 18 % — marge suffisante). Universel.
        if _unabsorbed:
            corridor = corridor.union(unary_union(_unabsorbed)).buffer(0)
            if corridor.geom_type == "MultiPolygon":
                corridor = max(corridor.geoms, key=lambda g: g.area)
        # After merging, refresh every apt's exterior orientations.
        refreshed: list[ApartmentSlot] = []
        for s in slots:
            sides = _compute_exterior_facades(s.polygon, footprint, voirie_orientations)
            refreshed.append(ApartmentSlot(
                id=s.id, polygon=s.polygon, surface_m2=s.polygon.area,
                target_typologie=s.target_typologie,
                orientations=list(sides),
                position_in_floor=s.position_in_floor,
            ))
        slots = refreshed
    else:
        # No landlocked slot → fallback to ne_bar-based core placement.
        # This preserves behaviour for footprints where every slot already
        # has a façade (rare for L).
        core = place_core_at_elbow(d, core_surface_m2=core_surface_m2)
        # Drop any apt slots overlapping the core.
        slots = [s for s in slots if s.polygon.intersection(core).area < 1.0]

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

    # ANTI-COIN-OBÈSE post-merge (2026-07-03) : le merge du reliquat de core
    # peut avoir fabriqué un slot très large → on le recoupe ici. +d'apparts,
    # 0 séjour géant, 0 cuisine orpheline (défauts user #2/#3/#4).
    clipped_slots = _split_oversized_slots(
        clipped_slots, footprint, voirie_orientations)

    # ── UNE SEULE CAGE AU COUDE (décision USER 2026-07-06) ─────────────────
    # RAISONNEMENT : un L n'a qu'UN angle rentrant (le coude). UNE cage
    # esc+ASC placée au coude (dans ``core``) dessert les DEUX branches par le
    # couloir en L qui part de là. La règle « 2 cages » venait du U (2 angles
    # intérieurs) → CADUQUE pour le L. On ne produit donc AUCUNE cage
    # secondaire : ``secondary_cores`` reste vide. L'espace autrefois pris par
    # la 2e cage (bout d'aile, côté hall) reste en SLOTS APT → récupéré en SHAB
    # (relayout + _reclaim_pockets en aval). Universel (tout L, toute orientation).
    secondary: tuple[ShapelyPolygon, ...] = ()

    return LLayoutResult(
        core=core, corridor=corridor, slots=clipped_slots, decomposition=d,
        secondary_cores=secondary,
    )


def _second_cage_on_corridor(corridor, core, slots) -> ShapelyPolygon | None:
    """Place une 2e cage (esc+asc) SUR le couloir, à l'extrémité la plus loin
    du core (bout de l'aile la plus longue). On échantillonne le couloir réel
    pour trouver le point du couloir le plus éloigné du core, puis on adosse un
    rectangle ~3,4 x 4,4 m centré sur l'axe local du couloir à cet endroit. Le
    couloir en L peut être un multipolygone : on unifie d'abord. Universel."""
    from shapely.geometry import Point as _P2

    corr = corridor if corridor.geom_type == "Polygon" else unary_union([
        g for g in getattr(corridor, "geoms", [corridor])])
    corr = corr.buffer(0)
    if corr.is_empty:
        return None
    if corr.geom_type == "MultiPolygon":
        corr = max(corr.geoms, key=lambda g: g.area)
    core_c = core.centroid
    cx0, cy0, cx1, cy1 = corr.bounds

    # 1. Point du COULOIR le plus loin du core : on échantillonne une grille
    #    fine dans la bbox du couloir et on garde ceux réellement DANS le
    #    couloir (buffer léger) puis on prend le plus éloigné du core.
    best_pt = None
    best_d = -1.0
    step = 0.6
    y = cy0
    corr_b = corr.buffer(0.05)
    while y <= cy1 + 1e-6:
        x = cx0
        while x <= cx1 + 1e-6:
            p = _P2(x, y)
            if corr_b.contains(p):
                dd = p.distance(core_c)
                if dd > best_d:
                    best_d, best_pt = dd, p
            x += step
        y += step
    if best_pt is None:
        return None

    # 2. Direction locale du couloir en ce point : horizontale si le couloir
    #    est plus étendu en x qu'en y autour du point, sinon verticale.
    px, py = best_pt.x, best_pt.y
    horiz_span = corr.intersection(shp_box(cx0, py - 0.8, cx1, py + 0.8)).area
    vert_span = corr.intersection(shp_box(px - 0.8, cy0, px + 0.8, cy1)).area
    # CAP 2e CAGE (défaut user #1, 2026-07-03) : on applique à la 2e cage le
    # MÊME principe qu'au core central (``_CORE_MAX_LEN_M``) — pas de gros
    # rectangle blanc qui mange l'apt voisin. Un escalier d'égress (2 volées +
    # palier de repos) + gaine ASC + palier PMR mini tient dans ~3,0 × 3,6 m
    # (10,8 m²). L'excédent vs l'ancien 3,4 × 4,4 (15 m²) est rendu au logement
    # voisin en SHAB (la 2e cage est carvée des apts qui la recouvrent en aval :
    # une cage plus petite ⇒ moins de carve ⇒ +SHAB voisin). Universel.
    side = _SECONDARY_CAGE_SIDE_M    # largeur cage (perpendiculaire au couloir)
    depth = _SECONDARY_CAGE_DEPTH_M  # longueur cage le long du couloir
    if horiz_span >= vert_span:
        # couloir horizontal : cage part vers l'INTÉRIEUR (vers le core) depuis
        # le bout, centrée sur la ligne du couloir (y=py).
        toward = -1 if px > core_c.x else 1
        x0 = min(px, px + toward * depth)
        cage = shp_box(x0, py - side / 2, x0 + depth, py + side / 2)
    else:
        toward = -1 if py > core_c.y else 1
        y0 = min(py, py + toward * depth)
        cage = shp_box(px - side / 2, y0, px + side / 2, y0 + depth)

    # 3. Contraintes : vraie 2e issue → loin du core, adossée au couloir.
    if cage.distance(core) < 6.0:
        return None
    if not cage.buffer(0.3).intersects(corr):
        return None
    return cage
