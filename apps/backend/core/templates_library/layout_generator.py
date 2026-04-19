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


def _layout_t3(slot_w: float, slot_d: float) -> list[_Rect]:
    """T3 = 55-65 m² = entrée + séjour/cuisine + 2 chambres + SdB + WC.

    Layout: palier en bas (v=0), façade en haut (v=slot_d).
    Service strip at v=0 to v=service_d (entrée + SdB + WC on a hall).
    Chambres strip at v=service_d to v=chambres_d (chambres facing façade
    via séjour on the other u-half).
    Séjour/cuisine takes the whole façade half of the slot width.

    Layout diagram (u=width, v=depth from palier):

        ╔════════════════╦══════════════════╗  v = slot_d (façade)
        ║                ║                  ║
        ║  SÉJOUR/CUIS   ║   CHAMBRE PAR.   ║
        ║                ║                  ║
        ║                ╠══════════════════╣
        ║                ║   CHAMBRE ENF.   ║
        ║                ║                  ║
        ╠════════════════╩╦═════════════════╣  v = service_d
        ║  COULOIR        ║    SdB    │ WC  ║
        ║                 ║           │     ║
        ║  ENTRÉE         ║           │     ║
        ╚══════════════════════════════════╝   v = 0 (palier / entry door)
    """
    rects: list[_Rect] = []

    # Service strip depth: ~2.2m (hall + SdB room depth)
    service_d = min(2.4, slot_d * 0.27)
    # Séjour occupies ~55% of the width
    sejour_w = slot_w * 0.55
    # Entrée on palier side, left half up to sejour_w
    entree_u = 0.0
    entree_w = sejour_w * 0.6  # entrée ~60% of séjour width
    rects.append(_Rect(entree_u, 0.0, entree_u + entree_w, service_d, RoomType.ENTREE, "r_entree"))
    # SdB + WC on the right side of the service strip
    sdb_u0 = entree_u + entree_w
    sdb_u1 = slot_w - (slot_w * 0.12)  # WC takes ~12% of width
    wc_u0 = sdb_u1
    wc_u1 = slot_w
    rects.append(_Rect(sdb_u0, 0.0, sdb_u1, service_d, RoomType.SDB, "r_sdb"))
    rects.append(_Rect(wc_u0, 0.0, wc_u1, service_d, RoomType.WC, "r_wc"))

    # Top strip: séjour (left) + 2 chambres (right stacked)
    sejour_u0 = 0.0
    sejour_u1 = sejour_w
    rects.append(_Rect(sejour_u0, service_d, sejour_u1, slot_d, RoomType.SEJOUR_CUISINE, "r_sejour"))
    # Right half split into chambres_parents (bigger, top) + chambre_enfant
    ch_u0 = sejour_w
    ch_u1 = slot_w
    # chambre_parents: 60% of top strip
    ch_enfant_d = service_d + (slot_d - service_d) * 0.42
    rects.append(_Rect(ch_u0, service_d, ch_u1, ch_enfant_d, RoomType.CHAMBRE_ENFANT, "r_ch_enfant"))
    rects.append(_Rect(ch_u0, ch_enfant_d, ch_u1, slot_d, RoomType.CHAMBRE_PARENTS, "r_ch_parents"))

    return rects


def _layout_t2(slot_w: float, slot_d: float) -> list[_Rect]:
    """T2 = 42-55 m² = entrée + séjour/cuisine + 1 chambre + SdB + WC."""
    rects: list[_Rect] = []
    service_d = min(2.4, slot_d * 0.28)
    sejour_w = slot_w * 0.60

    rects.append(_Rect(0.0, 0.0, sejour_w * 0.65, service_d, RoomType.ENTREE, "r_entree"))
    sdb_u0 = sejour_w * 0.65
    sdb_u1 = slot_w - slot_w * 0.12
    rects.append(_Rect(sdb_u0, 0.0, sdb_u1, service_d, RoomType.SDB, "r_sdb"))
    rects.append(_Rect(sdb_u1, 0.0, slot_w, service_d, RoomType.WC, "r_wc"))

    # Façade strip: séjour (left) + chambre parents (right)
    rects.append(_Rect(0.0, service_d, sejour_w, slot_d, RoomType.SEJOUR_CUISINE, "r_sejour"))
    rects.append(_Rect(sejour_w, service_d, slot_w, slot_d, RoomType.CHAMBRE_PARENTS, "r_ch_parents"))

    return rects


def _layout_t4(slot_w: float, slot_d: float) -> list[_Rect]:
    """T4 = 65-90 m² = entrée + séjour/cuisine + 3 chambres + SdB + SdE + WC."""
    rects: list[_Rect] = []
    service_d = min(2.6, slot_d * 0.28)
    sejour_w = slot_w * 0.48  # séjour smaller to make room for more chambres

    # Service strip: entrée + SdB + WC
    rects.append(_Rect(0.0, 0.0, sejour_w * 0.7, service_d, RoomType.ENTREE, "r_entree"))
    sdb_u0 = sejour_w * 0.7
    sdb_u1 = sejour_w * 0.7 + (slot_w - sejour_w * 0.7) * 0.55
    rects.append(_Rect(sdb_u0, 0.0, sdb_u1, service_d, RoomType.SDB, "r_sdb"))
    rects.append(_Rect(sdb_u1, 0.0, slot_w, service_d, RoomType.WC, "r_wc"))

    # Façade strip: séjour (left) + 3 chambres stacked (right)
    rects.append(_Rect(0.0, service_d, sejour_w, slot_d, RoomType.SEJOUR_CUISINE, "r_sejour"))
    ch_u0 = sejour_w
    ch_u1 = slot_w
    top_h = slot_d - service_d
    # Split top_h into 3 roughly equal chambres
    ch1_top = service_d + top_h * 0.33
    ch2_top = service_d + top_h * 0.66
    rects.append(_Rect(ch_u0, service_d, ch_u1, ch1_top, RoomType.CHAMBRE_ENFANT, "r_ch_enfant"))
    rects.append(_Rect(ch_u0, ch1_top, ch_u1, ch2_top, RoomType.CHAMBRE_SUPP, "r_ch_supp"))
    rects.append(_Rect(ch_u0, ch2_top, ch_u1, slot_d, RoomType.CHAMBRE_PARENTS, "r_ch_parents"))

    return rects


def _layout_for_typology(typo: Typologie, slot_w: float, slot_d: float) -> list[_Rect]:
    if typo == Typologie.T2:
        return _layout_t2(slot_w, slot_d)
    if typo == Typologie.T3:
        return _layout_t3(slot_w, slot_d)
    if typo == Typologie.T4 or typo == Typologie.T5:
        return _layout_t4(slot_w, slot_d)
    return _layout_t2(slot_w, slot_d)


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


def generate_apartment(
    slot_bounds: tuple[float, float, float, float],
    typologie: Typologie,
    orientations: list[str],
    slot_id: str,
    template_id: str | None = None,
) -> tuple[list[Room], list[Wall], list[Opening], PalierSide]:
    """Produce rooms + walls + openings for a typology in a slot.

    Returns (rooms, walls, openings, palier_side).
    """
    OPPOSITE = {"sud": "nord", "nord": "sud", "ouest": "est", "est": "ouest"}
    # Palier = opposite of the primary façade
    primary = None
    for cand in ("sud", "ouest", "est", "nord"):
        if cand in orientations:
            primary = cand
            break
    if primary is None:
        primary = "sud"
    palier_side: PalierSide = OPPOSITE[primary]  # type: ignore

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

    return rooms, walls, openings, palier_side


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
) -> tuple[list[Wall], list[Opening]]:
    """Given placed rooms, derive perimeter + partition walls and openings.

    - Perimeter walls: 4 walls on the slot envelope (porteur 20 cm).
    - Palier wall has the porte d'entrée (centered on entrée room).
    - Façade walls have porte-fenêtre for séjour, fenêtres for chambres.
    - Internal walls: partitions between rooms (cloison 10 cm).
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

    for room in rooms:
        if room.type not in living_types:
            continue
        # Only add windows on sides OTHER than the palier (don't put window on palier wall)
        sides = [s for s in _side_of_room(room) if s != palier_side]
        if not sides:
            continue
        # Prefer the façade direction (opposite palier) first
        preferred = OPPOSITE[palier_side]
        side = preferred if preferred in sides else sides[0]
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
