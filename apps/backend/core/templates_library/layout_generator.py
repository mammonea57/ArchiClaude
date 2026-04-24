"""Architectural apartment layout generator.

Produces realistic room polygons for a given slot + typologie + orientation
based on promoteur/archi rules:

  - Porte d'entrée ouvre sur le mur côté PALIER
  - Entrée/hall (~4 m²) côté palier
  - Dégagement (couloir) dessert wet-rooms + chambres
  - SdB + WC en zone INTÉRIEURE (pas de fenêtre)
  - Séjour/cuisine sur la FAÇADE la plus dégagée
  - Chambres sur la/les FAÇADEs (chaque chambre a une fenêtre)
  - Porte-fenêtre sur le séjour, fenêtres sur chambres

The generator works in local (u, v) coordinates where:
  u = along the wall parallel to the palier (slot width)
  v = from palier (0) to façade (depth)
then maps back to world coordinates.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from core.building_model.schemas import (
    Cellule, CelluleType, Opening, OpeningType, Room, RoomType, Typologie, Wall, WallType,
)


PalierSide = Literal["sud", "nord", "est", "ouest"]


@dataclass
class _Rect:
    """Rectangle in local (u, v) coordinates, with a room type."""
    u0: float
    v0: float
    u1: float
    v1: float
    type: RoomType
    id: str

    @property
    def area(self) -> float:
        return (self.u1 - self.u0) * (self.v1 - self.v0)

    @property
    def cu(self) -> float:
        return (self.u0 + self.u1) / 2

    @property
    def cv(self) -> float:
        return (self.v0 + self.v1) / 2


# ───────────────────────────────────────────────────────────────────────────
# Target-sized layout — per-room m² targets drive rectangle dimensions.
# Promoteur spec (validated 2026-04-22) :
#   T2 40-45 · T3 60 · T4 75-85 · T5 95-110
# ───────────────────────────────────────────────────────────────────────────

@dataclass
class _RoomTarget:
    type: RoomType
    min_m2: float
    ideal_m2: float
    max_m2: float
    id_suffix: str
    zone: Literal["service", "sejour", "cuisine", "chambre"]


# Order WITHIN each zone matters:
#   service = left→right along palier: [ENTREE, SDB, SDE?, WC, WC2?]
#   chambre = palier-side → façade-side (stacked toward façade)
_TARGETS: dict[Typologie, list[_RoomTarget]] = {
    Typologie.T2: [
        _RoomTarget(RoomType.ENTREE,          2.0,  3.0,  4.0, "r_entree",     "service"),
        _RoomTarget(RoomType.SDB,             3.5,  4.0,  4.5, "r_sdb",        "service"),
        _RoomTarget(RoomType.WC,              1.0,  1.2,  1.5, "r_wc",         "service"),
        _RoomTarget(RoomType.SEJOUR_CUISINE,22.0, 25.0, 29.0, "r_sejour",     "sejour"),
        _RoomTarget(RoomType.CHAMBRE_PARENTS,10.0,11.0, 12.0, "r_ch_parents", "chambre"),
    ],
    Typologie.T3: [
        _RoomTarget(RoomType.ENTREE,          4.0,  5.0,  6.0, "r_entree",      "service"),
        _RoomTarget(RoomType.SDB,             4.0,  4.5,  5.0, "r_sdb",         "service"),
        _RoomTarget(RoomType.WC,              1.2,  1.5,  1.8, "r_wc",          "service"),
        _RoomTarget(RoomType.SEJOUR_CUISINE,26.0, 28.0, 31.0, "r_sejour",      "sejour"),
        _RoomTarget(RoomType.CHAMBRE_ENFANT,  9.0,  9.5, 10.5, "r_ch_enfant",   "chambre"),
        _RoomTarget(RoomType.CHAMBRE_PARENTS,10.0,11.0, 12.0, "r_ch_parents",  "chambre"),
    ],
    Typologie.T4: [
        _RoomTarget(RoomType.ENTREE,          5.0,  6.0,  8.0, "r_entree",      "service"),
        _RoomTarget(RoomType.SDB,             4.5,  5.0,  6.0, "r_sdb",         "service"),
        _RoomTarget(RoomType.SALLE_DE_DOUCHE, 2.0,  2.5,  3.0, "r_sde",         "service"),
        _RoomTarget(RoomType.WC,              1.5,  1.8,  2.0, "r_wc",          "service"),
        _RoomTarget(RoomType.SEJOUR,        25.0, 28.0, 30.0, "r_sejour",      "sejour"),
        _RoomTarget(RoomType.CUISINE,         5.0,  6.0,  7.0, "r_cuisine",     "cuisine"),
        _RoomTarget(RoomType.CHAMBRE_ENFANT, 10.0,11.0, 12.0, "r_ch_enfant",   "chambre"),
        _RoomTarget(RoomType.CHAMBRE_SUPP,    9.0,10.0, 11.0, "r_ch_supp",     "chambre"),
        _RoomTarget(RoomType.CHAMBRE_PARENTS,11.0,12.0, 13.0, "r_ch_parents",  "chambre"),
    ],
    Typologie.T5: [
        _RoomTarget(RoomType.ENTREE,          6.0,  8.0, 10.0, "r_entree",      "service"),
        _RoomTarget(RoomType.SDB,             5.0,  5.5,  6.0, "r_sdb",         "service"),
        _RoomTarget(RoomType.SALLE_DE_DOUCHE, 3.0,  3.5,  4.0, "r_sde",         "service"),
        _RoomTarget(RoomType.WC,              2.0,  2.5,  3.0, "r_wc",          "service"),
        _RoomTarget(RoomType.WC,              1.5,  2.0,  3.0, "r_wc2",         "service"),
        _RoomTarget(RoomType.SEJOUR,        30.0, 32.0, 35.0, "r_sejour",      "sejour"),
        _RoomTarget(RoomType.CUISINE,         6.0,  8.0, 10.0, "r_cuisine",     "cuisine"),
        _RoomTarget(RoomType.CHAMBRE_ENFANT, 10.0,11.0, 12.0, "r_ch_enfant",   "chambre"),
        _RoomTarget(RoomType.CHAMBRE_SUPP,   10.0,10.5, 11.0, "r_ch_supp1",    "chambre"),
        _RoomTarget(RoomType.CHAMBRE_SUPP,    9.0, 9.5, 10.5, "r_ch_supp2",    "chambre"),
        _RoomTarget(RoomType.CHAMBRE_PARENTS,12.0,13.0, 14.0, "r_ch_parents",  "chambre"),
    ],
}


def _allocate_sizes(targets: list[_RoomTarget], slot_area: float) -> dict[int, float]:
    """Grow from ideal → max in priority order (chambres > cuisine > entrée).
    Séjour absorbs residual (may exceed max for very oversized slots).
    If slot < ideal, shrink from ideal → min proportionally."""
    sizes = {id(t): t.ideal_m2 for t in targets}
    total_ideal = sum(t.ideal_m2 for t in targets)
    delta = slot_area - total_ideal
    if delta >= 0:
        # Grow chambres first
        for t in targets:
            if t.zone == "chambre":
                bonus = min(delta, t.max_m2 - t.ideal_m2)
                sizes[id(t)] += bonus
                delta -= bonus
                if delta <= 0:
                    break
        # Then cuisine
        if delta > 0:
            for t in targets:
                if t.zone == "cuisine":
                    bonus = min(delta, t.max_m2 - t.ideal_m2)
                    sizes[id(t)] += bonus
                    delta -= bonus
        # Then entrée
        if delta > 0:
            for t in targets:
                if t.type == RoomType.ENTREE:
                    bonus = min(delta, t.max_m2 - t.ideal_m2)
                    sizes[id(t)] += bonus
                    delta -= bonus
        # Dump remaining into séjour
        sej = next((t for t in targets if t.zone == "sejour"), None)
        if sej and delta > 0:
            sizes[id(sej)] += delta
    else:
        shortage = -delta
        shrinkables = {id(t): max(0.0, t.ideal_m2 - t.min_m2) for t in targets}
        total_shrink = sum(shrinkables.values())
        if total_shrink > 0:
            k = min(1.0, shortage / total_shrink)
            for t in targets:
                sizes[id(t)] -= shrinkables[id(t)] * k
    return sizes


def _layout_for_typology(typo: Typologie, slot_w: float, slot_d: float) -> list[_Rect]:
    """Target-m²-driven layout. Rooms get realistic sizes matching promoteur spec.

    Layout invariants (preserved from the legacy proportion-based version):

        ╔════════════════╦══════════════════╗  v = slot_d (façade)
        ║                ║    CH. PARENTS   ║
        ║     SÉJOUR     ╠══════════════════╣
        ║                ║    CH. SUPP      ║
        ║                ╠══════════════════╣
        ║                ║    CH. ENFANT    ║
        ╠════════════════╣                  ║
        ║    CUISINE     ║                  ║  (T4/T5: cuisine séparée
        ╠════════════════╩╦═════════════════╣                en strip)
        ║  ENTRÉE │  SdB  │SdE│   WC  │ WC2 ║  v = service_d
        ╚══════════════════════════════════╝  v = 0 (palier)

    Guarantees:
      - Entrée at v=0 → porte d'entrée sur le palier
      - Every chambre adjacent to séjour via u=ch_u0 edge (door via _should_link)
      - Cuisine (if separate) adjacent to séjour + entrée (open-plan topology)
      - Service strip packs entrée + wet rooms along palier wall
    """
    targets = _TARGETS.get(typo) or _TARGETS[Typologie.T2]

    service = [t for t in targets if t.zone == "service"]
    chambres = [t for t in targets if t.zone == "chambre"]
    sejour_t = next(t for t in targets if t.zone == "sejour")
    cuisine_t = next((t for t in targets if t.zone == "cuisine"), None)

    sizes = _allocate_sizes(targets, slot_w * slot_d)

    # ── Service strip depth: constrained by SdB needing ≥ 1.5m width
    #    and the total slot_d, capped at 30% slot depth or 2.6m.
    sdb_t = next((t for t in service if t.type == RoomType.SDB), None)
    sdb_area = sizes[id(sdb_t)] if sdb_t else 4.0
    service_d = max(1.9, min(2.6, slot_d * 0.22, sdb_area / 1.5))
    facade_d = slot_d - service_d
    if facade_d < 3.5:
        service_d = slot_d * 0.30
        facade_d = slot_d - service_d

    # Service room widths: area / service_d, packed left-to-right.
    service_ws = [max(0.8, sizes[id(t)] / service_d) for t in service]
    total_sw = sum(service_ws)
    if total_sw > slot_w:
        k = slot_w / total_sw
        service_ws = [w * k for w in service_ws]
    else:
        # Slack distributed respecting each room's max m² — WC stays small
        # etc. Any remaining slack inflates entrée (corridor space, fine).
        gap = slot_w - total_sw
        for idx, t in enumerate(service):
            max_w = t.max_m2 / service_d
            bonus = min(gap, max(0.0, max_w - service_ws[idx]))
            service_ws[idx] += bonus
            gap -= bonus
            if gap <= 0:
                break
        if gap > 0:
            service_ws[0] += gap  # remainder → entrée (acts as circulation)

    rects: list[_Rect] = []
    u = 0.0
    for t, w in zip(service, service_ws):
        rects.append(_Rect(u, 0.0, u + w, service_d, t.type, t.id_suffix))
        u += w

    # ── Chambres column at u=ch_u0..slot_w, stacked in v.
    # Column width from total chambre areas, clamped. Min 2.5m = comfortable
    # chambre width; max = half of slot_w so séjour keeps >= half.
    ch_areas = [sizes[id(t)] for t in chambres]
    ch_total = sum(ch_areas)
    ideal_col_w = ch_total / max(facade_d, 0.1)
    ch_col_w = max(2.5, min(slot_w * 0.55, ideal_col_w))

    # Heights at this col width
    heights = [a / ch_col_w for a in ch_areas]
    total_h = sum(heights)

    if total_h > facade_d + 0.1:
        # Column too short → shrink chambres proportionally to fit
        k = facade_d / total_h
        heights = [h * k for h in heights]
        chambres_fill_column = True
        empty_strip_h = 0.0
    elif total_h < facade_d - 0.1:
        # Column too long → chambres pushed to the FAÇADE end (best light),
        # unused palier-side portion becomes a séjour extension (L-shape).
        chambres_fill_column = False
        empty_strip_h = facade_d - total_h
    else:
        chambres_fill_column = True
        empty_strip_h = 0.0

    ch_u0 = slot_w - ch_col_w
    # Chambres start at service_d if filling, else at (service_d + empty_strip_h)
    v = service_d + empty_strip_h
    for t, h in zip(chambres, heights):
        v1 = v + h
        rects.append(_Rect(ch_u0, v, slot_w, v1, t.type, t.id_suffix))
        v = v1

    # ── Séjour (+ cuisine) on left portion of façade strip.
    # Cuisine is a HORIZONTAL strip adjacent to service (so entrée→cuisine
    # works) and below séjour. This keeps every chambre adjacent to séjour
    # on its left edge (u=ch_u0) so the _should_link door logic fires.
    sc_w = ch_u0
    if cuisine_t is not None and sc_w > 2.5:
        cui_area = sizes[id(cuisine_t)]
        cui_h = cui_area / sc_w
        cui_h = max(1.8, min(cui_h, 2.8))
        cui_h = min(cui_h, facade_d * 0.35)
        sej_v0 = service_d + cui_h
        rects.append(_Rect(0.0, service_d, sc_w, sej_v0, cuisine_t.type, cuisine_t.id_suffix))
    else:
        sej_v0 = service_d

    # If the main séjour rectangle would exceed max × 1.3 (pathological
    # oversized slot), carve a CELLIER strip at the palier-adjacent corner
    # of the séjour to cap séjour size and give the apt some storage.
    sej_rect_area = sc_w * (slot_d - sej_v0)
    sej_max = sejour_t.max_m2 * 1.3  # allow 30% overshoot
    if sej_rect_area > sej_max + 3.0 and sc_w > 3.5:
        excess = sej_rect_area - sejour_t.max_m2  # cap at clean max, not max×1.3
        rang_w = min(2.5, sc_w * 0.35)
        rang_h = min((slot_d - sej_v0) * 0.4, excess / rang_w)
        # CELLIER at the palier-adjacent corner of séjour (left side, near cuisine)
        rects.append(_Rect(0.0, sej_v0, rang_w, sej_v0 + rang_h,
                          RoomType.CELLIER, "r_cellier"))
        # Séjour L-shape: top strip + right-of-cellier strip
        rects.append(_Rect(rang_w, sej_v0, sc_w, sej_v0 + rang_h,
                          sejour_t.type, sejour_t.id_suffix + "_a"))
        rects.append(_Rect(0.0, sej_v0 + rang_h, sc_w, slot_d,
                          sejour_t.type, sejour_t.id_suffix + "_b"))
    else:
        # Main séjour (left column above cuisine/service)
        rects.append(_Rect(0.0, sej_v0, sc_w, slot_d, sejour_t.type, sejour_t.id_suffix))

    # If chambres don't fill the column, the palier-side strip (u=ch_u0..slot_w,
    # v=service_d..service_d+empty_strip_h) becomes a séjour extension.
    # Same type as main séjour → downstream treats it as one logical room.
    if not chambres_fill_column and empty_strip_h > 0.3:
        rects.append(_Rect(ch_u0, service_d, slot_w,
                          service_d + empty_strip_h,
                          sejour_t.type, sejour_t.id_suffix + "_ext"))

    return rects


def _transform_uv_to_world(
    u: float, v: float,
    slot_bounds: tuple[float, float, float, float],
    palier_side: PalierSide,
) -> tuple[float, float]:
    """Map (u, v) local coord to world coord given the slot bounds + palier side.

    u axis = parallel to the palier wall (left to right as you stand in palier)
    v axis = from palier (0) toward façade
    """
    minx, miny, maxx, maxy = slot_bounds
    if palier_side == "sud":
        # palier at miny; façade at maxy
        return minx + u, miny + v
    if palier_side == "nord":
        # palier at maxy; façade at miny
        return maxx - u, maxy - v
    if palier_side == "ouest":
        # palier at minx; façade at maxx
        return minx + v, miny + u
    # est
    return maxx - v, maxy - u


def _rect_to_world_polygon(
    rect: _Rect,
    slot_bounds: tuple[float, float, float, float],
    palier_side: PalierSide,
) -> list[tuple[float, float]]:
    """Return 4-corner polygon of the rect in world coordinates (clockwise)."""
    corners_uv = [
        (rect.u0, rect.v0), (rect.u1, rect.v0),
        (rect.u1, rect.v1), (rect.u0, rect.v1),
    ]
    return [_transform_uv_to_world(u, v, slot_bounds, palier_side) for (u, v) in corners_uv]


def effective_typology(
    slot_bounds: tuple[float, float, float, float],
    requested: Typologie,
) -> Typologie:
    """Downgrade typology when the slot is objectively too small to host it.

    Hierarchy T5 > T4 > T3 > T2. Threshold = **sum of mins** (strict floor
    below which the typo cannot be built within spec). A slot at or above
    that sum is acceptable — the layout engine absorbs any shortage by
    shrinking rooms proportionally within [min, ideal].
    """
    minx, miny, maxx, maxy = slot_bounds
    slot_area = (maxx - minx) * (maxy - miny)
    # Sum-of-mins per typo (strict floor from _TARGETS)
    TYPO_MIN_SUM = {
        Typologie.T2: 38.5,   # 2 + 3.5 + 1 + 22 + 10
        Typologie.T3: 54.2,   # 4 + 4 + 1.2 + 26 + 9 + 10
        Typologie.T4: 73.0,   # 5 + 4.5 + 2 + 1.5 + 25 + 5 + 10 + 9 + 11
        Typologie.T5: 94.5,   # 6 + 5 + 3 + 2 + 1.5 + 30 + 6 + 10 + 10 + 9 + 12
    }
    HIERARCHY = [Typologie.T5, Typologie.T4, Typologie.T3, Typologie.T2]
    try:
        idx = HIERARCHY.index(requested)
    except ValueError:
        return requested
    while idx < len(HIERARCHY):
        candidate = HIERARCHY[idx]
        if slot_area >= TYPO_MIN_SUM[candidate]:
            return candidate
        idx += 1
    return Typologie.T2


def generate_apartment(
    slot_bounds: tuple[float, float, float, float],
    typologie: Typologie,
    orientations: list[str],
    slot_id: str,
    template_id: str | None = None,
    palier_side_hint: PalierSide | None = None,
) -> tuple[list[Room], list[Wall], list[Opening], PalierSide, Typologie]:
    """Produce rooms + walls + openings for a typology in a slot.

    If ``palier_side_hint`` is given (provided by the pipeline based on
    ACTUAL corridor geometry), use it verbatim — this is the only
    reliable source for apts with just one exterior wall or with
    mismatched orientation/corridor pairings (e.g. bar-east apt with
    east facade but corridor on north).

    Otherwise fall back to the orientations-based heuristic.

    Auto-downgrades the typology if the slot can't realistically host it
    (returns the effective typology alongside rooms/walls/openings).

    Returns (rooms, walls, openings, palier_side, effective_typo).
    """
    # Auto-downgrade typology if slot undersized (maximize usable lot count
    # rather than ship a cramped-unsellable bigger typo).
    typologie = effective_typology(slot_bounds, typologie)

    OPPOSITE = {"sud": "nord", "nord": "sud", "ouest": "est", "est": "ouest"}
    if palier_side_hint is not None:
        palier_side: PalierSide = palier_side_hint
    else:
        primary = None
        for cand in ("sud", "ouest", "est", "nord"):
            if cand in orientations:
                primary = cand
                break
        if primary is None:
            primary = "sud"
        palier_side = OPPOSITE[primary]  # type: ignore

    minx, miny, maxx, maxy = slot_bounds
    # Slot width = parallel to palier; depth = perpendicular (palier → façade)
    if palier_side in ("sud", "nord"):
        slot_w = maxx - minx
        slot_d = maxy - miny
    else:
        slot_w = maxy - miny
        slot_d = maxx - minx

    rects = _layout_for_typology(typologie, slot_w, slot_d)

    # Build rooms
    rooms: list[Room] = []
    for rect in rects:
        poly = _rect_to_world_polygon(rect, slot_bounds, palier_side)
        rooms.append(Room(
            id=f"{slot_id}_{rect.id}",
            type=rect.type,
            surface_m2=rect.area,
            polygon_xy=poly,
            orientation=None,
            label_fr=_label_fr(rect.type),
            furniture=[],
        ))

    # Walls + openings built by the caller (adapter) so they stay in sync
    # with slot envelope. We return empty lists here; the adapter adds
    # perimeter walls + internal partitions based on the rects.
    walls: list[Wall] = []
    openings: list[Opening] = []

    return rooms, walls, openings, palier_side, typologie


def _label_fr(t: RoomType) -> str:
    M = {
        RoomType.ENTREE: "Entrée",
        RoomType.SEJOUR: "Séjour",
        RoomType.SEJOUR_CUISINE: "Séjour / cuisine",
        RoomType.CUISINE: "Cuisine",
        RoomType.SDB: "Salle de bain",
        RoomType.SALLE_DE_DOUCHE: "Salle d'eau",
        RoomType.WC: "WC",
        RoomType.WC_SDB: "SdB / WC",
        RoomType.CHAMBRE_PARENTS: "Chambre parents",
        RoomType.CHAMBRE_ENFANT: "Chambre enfant",
        RoomType.CHAMBRE_SUPP: "Chambre",
        RoomType.CELLIER: "Cellier",
        RoomType.PLACARD_TECHNIQUE: "Placard technique",
        RoomType.LOGGIA: "Loggia",
    }
    return M.get(t, t.value)


def build_walls_and_openings(
    rooms: list[Room],
    slot_bounds: tuple[float, float, float, float],
    palier_side: PalierSide,
    slot_id: str,
    orientations: list[str] | None = None,
) -> tuple[list[Wall], list[Opening]]:
    """Given placed rooms, derive perimeter + partition walls and openings.

    - Perimeter walls: 4 walls on the slot envelope (porteur 20 cm).
    - Palier wall has the porte d'entrée (centered on entrée room).
    - Façade walls have porte-fenêtre for séjour, fenêtres for chambres.
    - Internal walls: partitions between each pair of adjacent rooms
      (cloison 10 cm).
    """
    minx, miny, maxx, maxy = slot_bounds
    walls: list[Wall] = []
    openings: list[Opening] = []

    # Four perimeter walls
    def _wall(wid: str, x0: float, y0: float, x1: float, y1: float, porteur: bool = True) -> Wall:
        return Wall(
            id=wid,
            type=WallType.PORTEUR if porteur else WallType.CLOISON_70,
            thickness_cm=20 if porteur else 10,
            geometry={"type": "LineString", "coords": [[x0, y0], [x1, y1]]},
            hauteur_cm=260,
            materiau="beton_banche" if porteur else "placo",
        )

    w_sud = _wall(f"{slot_id}_w_sud", minx, miny, maxx, miny)
    w_nord = _wall(f"{slot_id}_w_nord", minx, maxy, maxx, maxy)
    w_ouest = _wall(f"{slot_id}_w_ouest", minx, miny, minx, maxy)
    w_est = _wall(f"{slot_id}_w_est", maxx, miny, maxx, maxy)
    walls.extend([w_sud, w_nord, w_ouest, w_est])

    # Internal partition walls: find every shared edge between pairs of rooms
    # and emit a cloison_70 along it. Segments are deduplicated so that a
    # boundary shared by three rooms only produces one wall per linear
    # segment.
    _TOL = 0.15  # 15 cm tolerance for matching endpoints
    emitted: list[tuple[tuple[float, float], tuple[float, float]]] = []

    def _seg_eq(a: tuple[tuple[float, float], tuple[float, float]],
                b: tuple[tuple[float, float], tuple[float, float]]) -> bool:
        return (abs(a[0][0] - b[0][0]) < _TOL and abs(a[0][1] - b[0][1]) < _TOL
                and abs(a[1][0] - b[1][0]) < _TOL and abs(a[1][1] - b[1][1]) < _TOL) or (
                abs(a[0][0] - b[1][0]) < _TOL and abs(a[0][1] - b[1][1]) < _TOL
                and abs(a[1][0] - b[0][0]) < _TOL and abs(a[1][1] - b[0][1]) < _TOL)

    def _is_on_perimeter(p0: tuple[float, float], p1: tuple[float, float]) -> bool:
        """True if the segment runs along the outer envelope."""
        # vertical at minx or maxx
        if abs(p0[0] - p1[0]) < _TOL and (abs(p0[0] - minx) < _TOL or abs(p0[0] - maxx) < _TOL):
            return True
        # horizontal at miny or maxy
        if abs(p0[1] - p1[1]) < _TOL and (abs(p0[1] - miny) < _TOL or abs(p0[1] - maxy) < _TOL):
            return True
        return False

    def _room_edges(room: Room) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        pts = room.polygon_xy
        return [(pts[i], pts[(i + 1) % len(pts)]) for i in range(len(pts))]

    def _shared_overlap(
        e1: tuple[tuple[float, float], tuple[float, float]],
        e2: tuple[tuple[float, float], tuple[float, float]],
    ) -> tuple[tuple[float, float], tuple[float, float]] | None:
        """If the two segments are collinear and overlap, return the overlap."""
        (a0, a1), (b0, b1) = e1, e2
        # Collinear vertical (same x)
        if abs(a0[0] - a1[0]) < _TOL and abs(b0[0] - b1[0]) < _TOL and abs(a0[0] - b0[0]) < _TOL:
            ys_a = sorted([a0[1], a1[1]])
            ys_b = sorted([b0[1], b1[1]])
            lo = max(ys_a[0], ys_b[0])
            hi = min(ys_a[1], ys_b[1])
            if hi - lo > _TOL:
                return ((a0[0], lo), (a0[0], hi))
        # Collinear horizontal (same y)
        if abs(a0[1] - a1[1]) < _TOL and abs(b0[1] - b1[1]) < _TOL and abs(a0[1] - b0[1]) < _TOL:
            xs_a = sorted([a0[0], a1[0]])
            xs_b = sorted([b0[0], b1[0]])
            lo = max(xs_a[0], xs_b[0])
            hi = min(xs_a[1], xs_b[1])
            if hi - lo > _TOL:
                return ((lo, a0[1]), (hi, a0[1]))
        return None

    # Track which pair of rooms is separated by each emitted internal wall,
    # so we can add a PORTE_INTERIEURE on walls connecting the entrée to
    # every other room, plus séjour↔cuisine when they're distinct rooms.
    wi = 0
    wall_room_pairs: list[tuple[str, Room, Room]] = []
    for i in range(len(rooms)):
        for j in range(i + 1, len(rooms)):
            edges_i = _room_edges(rooms[i])
            edges_j = _room_edges(rooms[j])
            # Two rooms of the same room type share a logical space (e.g.
            # L-shaped séjour split into 2 rects). Don't emit a wall between
            # them — they should render as one continuous room.
            same_type = rooms[i].type == rooms[j].type
            for ei in edges_i:
                for ej in edges_j:
                    overlap = _shared_overlap(ei, ej)
                    if overlap is None:
                        continue
                    (p0, p1) = overlap
                    if _is_on_perimeter(p0, p1):
                        continue  # skip — already covered by envelope wall
                    if same_type:
                        continue  # merged-logical-room → no partition
                    if any(_seg_eq((p0, p1), e) for e in emitted):
                        continue
                    emitted.append((p0, p1))
                    wid = f"{slot_id}_p_{wi}"
                    walls.append(_wall(wid, p0[0], p0[1], p1[0], p1[1], porteur=False))
                    wall_room_pairs.append((wid, rooms[i], rooms[j]))
                    wi += 1

    # PORTE_INTERIEURE placement — every room must be reachable from the
    # entrée. Rules (all symmetric):
    #   - ENTREE links to any adjacent room (hub).
    #   - SEJOUR/SEJOUR_CUISINE opens onto CUISINE and any CHAMBRE (common
    #     in French T2/T3 where there's no dedicated night corridor).
    #   - SDB links to WC (en-suite WC) and to CHAMBRE_PARENTS (suite
    #     parentale) so the SdB is accessible even if not adjacent to
    #     the entrée.
    HUB_TYPES = {RoomType.ENTREE}
    LIVING_TYPES = {
        RoomType.SEJOUR, RoomType.SEJOUR_CUISINE,
    }
    CHAMBRES = {
        RoomType.CHAMBRE_PARENTS, RoomType.CHAMBRE_ENFANT, RoomType.CHAMBRE_SUPP,
    }
    WET_ROOMS = {
        RoomType.SDB, RoomType.SALLE_DE_DOUCHE, RoomType.WC, RoomType.WC_SDB,
    }

    def _should_link(a: Room, b: Room) -> bool:
        ta, tb = a.type, b.type
        # Hub pattern
        if ta in HUB_TYPES or tb in HUB_TYPES:
            return True
        # Séjour ↔ cuisine (open-plan) and séjour ↔ chambres (petit appt)
        if ta in LIVING_TYPES and tb in (
            {RoomType.CUISINE} | CHAMBRES
        ):
            return True
        if tb in LIVING_TYPES and ta in (
            {RoomType.CUISINE} | CHAMBRES
        ):
            return True
        # Wet-room chain: SDB ↔ WC (en-suite) or SDB ↔ master
        if ta in WET_ROOMS and tb in WET_ROOMS:
            return True
        if (ta == RoomType.SDB and tb == RoomType.CHAMBRE_PARENTS) or (
            tb == RoomType.SDB and ta == RoomType.CHAMBRE_PARENTS
        ):
            return True
        return False

    door_idx = 0
    for wid, ra, rb in wall_room_pairs:
        if not _should_link(ra, rb):
            continue
        wcoords = next(w for w in walls if w.id == wid).geometry["coords"]
        (x0, y0), (x1, y1) = wcoords[0], wcoords[1]
        wlen = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        if wlen < 0.9:
            continue  # wall too short for a 83 cm door
        door_pos_cm = max(30, int(wlen * 50) - 42)
        openings.append(Opening(
            id=f"{slot_id}_op_int_{door_idx}",
            type=OpeningType.PORTE_INTERIEURE,
            wall_id=wid,
            position_along_wall_cm=door_pos_cm,
            width_cm=83,
            height_cm=210,
            allege_cm=None,
            swing="interior_right",
        ))
        door_idx += 1

    # Palier wall + entry door
    palier_wall_id = {"sud": w_sud.id, "nord": w_nord.id, "ouest": w_ouest.id, "est": w_est.id}[palier_side]
    palier_wall = {"sud": w_sud, "nord": w_nord, "ouest": w_ouest, "est": w_est}[palier_side]

    # Entry door at the entrée room's center on the palier wall
    entree = next((r for r in rooms if r.type == RoomType.ENTREE), None)
    if entree:
        cx = sum(p[0] for p in entree.polygon_xy) / len(entree.polygon_xy)
        cy = sum(p[1] for p in entree.polygon_xy) / len(entree.polygon_xy)
        coords = palier_wall.geometry["coords"]
        wall_len = ((coords[1][0] - coords[0][0]) ** 2 + (coords[1][1] - coords[0][1]) ** 2) ** 0.5
        if palier_side in ("sud", "nord"):
            proj = cx - coords[0][0]
        else:
            proj = cy - coords[0][1]
        door_pos_cm = max(40, min(int(wall_len * 100) - 40, int(abs(proj) * 100)))
        openings.append(Opening(
            id=f"{slot_id}_op_entree",
            type=OpeningType.PORTE_ENTREE,
            wall_id=palier_wall_id,
            position_along_wall_cm=door_pos_cm,
            width_cm=93,
            height_cm=220,
            allege_cm=None,
            swing="interior_right",
        ))

    # Façade walls — windows for each room that touches them
    from shapely.geometry import LineString, Polygon as ShapelyPoly

    def _wall_for_side(side: str) -> Wall:
        return {"sud": w_sud, "nord": w_nord, "ouest": w_ouest, "est": w_est}[side]

    def _side_of_room(room: Room) -> list[str]:
        """Which façade sides does this room touch?"""
        xs = [p[0] for p in room.polygon_xy]
        ys = [p[1] for p in room.polygon_xy]
        sides = []
        if min(ys) - miny < 0.3: sides.append("sud")
        if maxy - max(ys) < 0.3: sides.append("nord")
        if min(xs) - minx < 0.3: sides.append("ouest")
        if maxx - max(xs) < 0.3: sides.append("est")
        return sides

    OPPOSITE = {"sud": "nord", "nord": "sud", "ouest": "est", "est": "ouest"}

    living_types = {
        RoomType.SEJOUR, RoomType.SEJOUR_CUISINE, RoomType.CUISINE,
        RoomType.CHAMBRE_PARENTS, RoomType.CHAMBRE_ENFANT, RoomType.CHAMBRE_SUPP,
    }

    # Exterior sides only — never place a window on a wall that faces a
    # corridor / another apt (those sides are NOT in ``orientations``).
    exterior_set = set(orientations or []) if orientations else None
    for room in rooms:
        if room.type not in living_types:
            continue
        room_sides = _side_of_room(room)
        # Drop the palier side (door, not window)
        candidates = [s for s in room_sides if s != palier_side]
        # Keep only sides that are actually exterior facades. If the
        # caller passed orientations, use them as ground truth; apts
        # that can't reach any exterior wall stay window-less (dark
        # room) rather than emit a fake window on an interior wall.
        if exterior_set is not None:
            candidates = [s for s in candidates if s in exterior_set]
        if not candidates:
            continue
        preferred = OPPOSITE[palier_side]
        side = preferred if preferred in candidates else candidates[0]
        wall = _wall_for_side(side)
        wcoords = wall.geometry["coords"]
        wall_len = ((wcoords[1][0] - wcoords[0][0]) ** 2 + (wcoords[1][1] - wcoords[0][1]) ** 2) ** 0.5

        # Window position = midpoint of room projection on that wall
        if side in ("sud", "nord"):
            room_xs = [p[0] for p in room.polygon_xy]
            pos_m = (min(room_xs) + max(room_xs)) / 2 - wcoords[0][0]
        else:
            room_ys = [p[1] for p in room.polygon_xy]
            pos_m = (min(room_ys) + max(room_ys)) / 2 - wcoords[0][1]
        pos_cm = max(50, min(int(wall_len * 100) - 50, int(abs(pos_m) * 100)))

        if room.type in (RoomType.SEJOUR, RoomType.SEJOUR_CUISINE):
            op_type = OpeningType.PORTE_FENETRE
            width = min(240, int(wall_len * 50))
            height = 220
            allege = None
        elif room.type == RoomType.CUISINE:
            op_type = OpeningType.FENETRE
            width = min(120, int(wall_len * 40))
            height = 200
            allege = 95
        else:
            op_type = OpeningType.FENETRE
            width = min(140, int(wall_len * 45))
            height = 200
            allege = 95

        openings.append(Opening(
            id=f"{slot_id}_op_{room.id}",
            type=op_type,
            wall_id=wall.id,
            position_along_wall_cm=pos_cm,
            width_cm=width,
            height_cm=height,
            allege_cm=allege,
            swing=None,
        ))
        _ = (LineString, ShapelyPoly)  # keep imports

    return walls, openings
