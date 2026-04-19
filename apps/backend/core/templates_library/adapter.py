# apps/backend/core/templates_library/adapter.py
"""TemplateAdapter: fit an abstract template to a concrete slot geometry."""
from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import Polygon as ShapelyPolygon

from core.building_model.schemas import (
    Cellule,
    CelluleType,
    Furniture,
    Opening,
    OpeningType,
    Room,
    RoomType,
    Wall,
    WallType,
)
from core.building_model.solver import ApartmentSlot
from core.templates_library.schemas import Template

_STRETCH_MIN = 0.85
_STRETCH_MAX = 1.15


@dataclass
class FitResult:
    success: bool
    apartment: Cellule | None = None
    rejection_reason: str | None = None
    stretch_x: float = 1.0
    stretch_y: float = 1.0


class TemplateAdapter:
    """Adapter that applies scale + rotation + mirror to fit a template in a slot."""

    def fit_to_slot(self, template: Template, slot: ApartmentSlot) -> FitResult:
        # 1. Check slot dimensions compatibility
        minx, miny, maxx, maxy = slot.polygon.bounds
        slot_width = maxx - minx
        slot_depth = maxy - miny

        # Range check vs template's declared dimensions
        dim = template.dimensions_grille
        width_ok = dim.largeur_min_m * 0.85 <= slot_width <= dim.largeur_max_m * 1.15
        depth_ok = dim.profondeur_min_m * 0.85 <= slot_depth <= dim.profondeur_max_m * 1.15
        if not (width_ok and depth_ok):
            return FitResult(
                success=False,
                rejection_reason=(
                    f"slot dimensions {slot_width:.1f}×{slot_depth:.1f}m outside template range "
                    f"[{dim.largeur_min_m:.1f}–{dim.largeur_max_m:.1f}]×"
                    f"[{dim.profondeur_min_m:.1f}–{dim.profondeur_max_m:.1f}]m"
                ),
            )

        # Determine the template grid shape from bounds_cells, then size cells so
        # rooms tile the slot exactly (no gap, no overflow).
        topo = template.topologie
        orig_max_col = max(max(c[0] for c in room["bounds_cells"]) for room in topo["rooms"])
        orig_max_row = max(max(c[1] for c in room["bounds_cells"]) for room in topo["rooms"])

        # Orient the template so that the "entrée" row ends up facing the
        # palier (= non-exterior side) and the "séjour" side faces the voirie /
        # cœur d'îlot. By default templates are built with entrée at row 0
        # (bottom) and séjour/chambres at higher rows (top), i.e. the façade
        # is at the TOP of the grid. If the slot's façade is SOUTH (miny),
        # we flip vertically; if WEST/EAST, we rotate 90°.
        transform = self._choose_grid_transform(slot.orientations or [])
        n_cols_t, n_rows_t = self._transformed_grid_shape(orig_max_col, orig_max_row, transform)

        max_col = n_cols_t - 1
        max_row = n_rows_t - 1
        n_cols = n_cols_t
        n_rows = n_rows_t
        cell_w = slot_width / n_cols
        cell_h = slot_depth / n_rows
        stretch_x = cell_w / 3.0
        stretch_y = cell_h / 3.0

        def _xform_cell(col: int, row: int) -> tuple[int, int]:
            return self._apply_grid_transform(col, row, orig_max_col, orig_max_row, transform)

        # Detect cells shared by multiple rooms (seed templates like T3 use
        # the same bounds_cells for sdb + wc, or entrée + cellier, assuming
        # the cell gets sub-divided between them). Build an occupancy map.
        from collections import defaultdict
        cell_occupants: dict[tuple[int, int], list[int]] = defaultdict(list)
        for idx, abs_room in enumerate(topo["rooms"]):
            for (orig_col, orig_row) in abs_room["bounds_cells"]:
                cell_occupants[(orig_col, orig_row)].append(idx)

        # 2. Build rooms. For a room occupying a shared cell, give it only its
        #    slice (cell divided horizontally into N strips of equal width,
        #    one per co-occupant, ordered by index). This prevents overlap.
        rooms: list[Room] = []
        for idx, abs_room in enumerate(template.topologie["rooms"]):
            cell_polys = []
            for orig_col, orig_row in abs_room["bounds_cells"]:
                occupants = cell_occupants[(orig_col, orig_row)]
                n_occ = len(occupants)
                my_pos = occupants.index(idx)
                col, row = _xform_cell(orig_col, orig_row)
                x0 = minx + col * cell_w
                y0 = miny + row * cell_h
                if n_occ == 1:
                    cell_polys.append(ShapelyPolygon([
                        (x0, y0), (x0 + cell_w, y0),
                        (x0 + cell_w, y0 + cell_h),
                        (x0, y0 + cell_h),
                    ]))
                else:
                    # Divide the cell into N equal vertical strips
                    strip_w = cell_w / n_occ
                    sx0 = x0 + my_pos * strip_w
                    cell_polys.append(ShapelyPolygon([
                        (sx0, y0), (sx0 + strip_w, y0),
                        (sx0 + strip_w, y0 + cell_h),
                        (sx0, y0 + cell_h),
                    ]))
            if not cell_polys:
                continue
            if len(cell_polys) == 1:
                merged = cell_polys[0]
            else:
                merged = cell_polys[0]
                for p in cell_polys[1:]:
                    merged = merged.union(p)
            # Fallback if cells aren't contiguous — use the largest piece
            if merged.geom_type == "MultiPolygon":
                merged = max(merged.geoms, key=lambda g: g.area)
            # Simplify to coords list
            coords = list(merged.exterior.coords)[:-1]
            surface = merged.area
            try:
                room_type = RoomType(abs_room["type"])
            except ValueError:
                return FitResult(success=False, rejection_reason=f"unknown room type {abs_room['type']}")
            rooms.append(Room(
                id=abs_room["id"], type=room_type,
                surface_m2=surface, polygon_xy=list(coords),
                orientation=None, label_fr=self._label_fr(room_type),
                furniture=self._place_furniture(abs_room["id"], room_type, merged, template),
            ))

        # 3. Build walls (scaled + rotated coordinates)
        walls: list[Wall] = []
        for i, aw in enumerate(template.topologie.get("walls_abstract", [])):
            fcol, frow = _xform_cell(aw["from_cell"][0], aw["from_cell"][1])
            tcol, trow = _xform_cell(aw["to_cell"][0], aw["to_cell"][1])
            from_x = minx + fcol * cell_w
            from_y = miny + frow * cell_h
            to_x = minx + tcol * cell_w
            to_y = miny + trow * cell_h
            try:
                w_type = WallType(aw["type"])
            except ValueError:
                return FitResult(success=False, rejection_reason=f"unknown wall type {aw['type']}")
            walls.append(Wall(
                id=f"w_{i}", type=w_type,
                thickness_cm=20 if w_type == WallType.PORTEUR else 7,
                geometry={"type": "LineString", "coords": [[from_x, from_y], [to_x, to_y]]},
                hauteur_cm=260, materiau="beton_banche" if w_type == WallType.PORTEUR else "placo",
            ))

        # 4. Build openings
        openings: list[Opening] = []
        for i, ao in enumerate(template.topologie.get("openings_abstract", [])):
            wall = walls[ao["wall_idx"]]
            coords = wall.geometry["coords"]
            wall_length_cm = int(
                ((coords[1][0] - coords[0][0])**2 + (coords[1][1] - coords[0][1])**2) ** 0.5 * 100
            )
            pos_cm = int(wall_length_cm * ao["position_ratio"])
            try:
                op_type = OpeningType(ao["type"])
            except ValueError:
                return FitResult(success=False, rejection_reason=f"unknown opening type {ao['type']}")
            width_cm = ao.get("largeur_min_cm", 93 if op_type == OpeningType.PORTE_ENTREE else 120)
            openings.append(Opening(
                id=f"op_{i}", type=op_type, wall_id=wall.id,
                position_along_wall_cm=pos_cm, width_cm=width_cm,
                height_cm=210 if "porte" in op_type.value else 200,
                allege_cm=95 if op_type == OpeningType.FENETRE else None,
                swing=ao.get("swing"),
            ))

        # 5. Add exterior-wall windows for living rooms that don't yet have one.
        #    Slot.orientations carries the cardinal sides that face the outside
        #    (voirie or cœur d'îlot). Each séjour + chambre on the apartment's
        #    perimeter receives a standard window on its nearest exterior side.
        self._add_exterior_openings(rooms, walls, openings, slot)

        # 6. Build Cellule
        apartment = Cellule(
            id=slot.id,
            type=CelluleType.LOGEMENT,
            typologie=slot.target_typologie,
            surface_m2=sum(r.surface_m2 for r in rooms),
            polygon_xy=list(slot.polygon.exterior.coords)[:-1],
            orientation=slot.orientations,
            template_id=template.id,
            rooms=rooms, walls=walls, openings=openings,
        )

        return FitResult(success=True, apartment=apartment, stretch_x=stretch_x, stretch_y=stretch_y)

    @staticmethod
    def _add_exterior_openings(
        rooms: list[Room], walls: list[Wall], openings: list[Opening], slot: ApartmentSlot
    ) -> None:
        """Ensure every living room has a window on an exterior wall.

        A room is a living room if its type is sejour*, cuisine, or chambre*.
        An exterior side is one listed in slot.orientations (sud/nord/est/ouest).
        For each such room that doesn't already have a window, we add a
        140-cm-wide fenêtre (200 cm for séjour) on the side of the room
        that coincides with an exterior side of the slot.
        """
        from core.building_model.schemas import OpeningType  # local to avoid top-level churn

        if slot.polygon.is_empty:
            return
        sminx, sminy, smaxx, smaxy = slot.polygon.bounds
        exterior_sides = set(slot.orientations or [])
        if not exterior_sides:
            return

        LIVING_ROOMS = {
            RoomType.SEJOUR, RoomType.SEJOUR_CUISINE, RoomType.CUISINE,
            RoomType.CHAMBRE_PARENTS, RoomType.CHAMBRE_ENFANT, RoomType.CHAMBRE_SUPP,
        }

        def _room_touches_side(room: Room, side: str, tol: float = 0.35) -> bool:
            if not room.polygon_xy:
                return False
            xs = [p[0] for p in room.polygon_xy]
            ys = [p[1] for p in room.polygon_xy]
            if side == "sud":   return min(ys) - sminy < tol
            if side == "nord":  return smaxy - max(ys) < tol
            if side == "ouest": return min(xs) - sminx < tol
            if side == "est":   return smaxx - max(xs) < tol
            return False

        def _side_segment(side: str, room: Room) -> tuple[tuple[float, float], tuple[float, float]] | None:
            """Return the (start, end) world coords of the room edge along that side."""
            if not room.polygon_xy:
                return None
            xs = [p[0] for p in room.polygon_xy]
            ys = [p[1] for p in room.polygon_xy]
            if side == "sud":   return ((min(xs), sminy), (max(xs), sminy))
            if side == "nord":  return ((min(xs), smaxy), (max(xs), smaxy))
            if side == "ouest": return ((sminx, min(ys)), (sminx, max(ys)))
            if side == "est":   return ((smaxx, min(ys)), (smaxx, max(ys)))
            return None

        next_op_idx = len(openings)
        next_wall_idx = len(walls)

        for room in rooms:
            if room.type not in LIVING_ROOMS:
                continue
            # Skip if room already has a window (via wall_id lookup)
            has_window = False
            for op in openings:
                if op.type not in (OpeningType.FENETRE, OpeningType.PORTE_FENETRE, OpeningType.BAIE_COULISSANTE):
                    continue
                w = next((ww for ww in walls if ww.id == op.wall_id), None)
                if w is None:
                    continue
                coords = w.geometry.get("coords", [])
                if len(coords) < 2:
                    continue
                # Is this wall along one of the room's polygon edges?
                # Quick check: at least one wall endpoint is close to the room
                for wp in coords:
                    if any((abs(wp[0] - p[0]) + abs(wp[1] - p[1])) < 0.4 for p in room.polygon_xy):
                        has_window = True
                        break
                if has_window:
                    break
            if has_window:
                continue

            # Pick the best exterior side for this room
            chosen_side = None
            for side in ("sud", "ouest", "est", "nord"):  # prefer south, then voirie-likely sides
                if side in exterior_sides and _room_touches_side(room, side):
                    chosen_side = side
                    break
            if chosen_side is None:
                continue

            seg = _side_segment(chosen_side, room)
            if seg is None:
                continue
            (x0, y0), (x1, y1) = seg
            # Create (or reuse) a wall for that side
            wall = Wall(
                id=f"w_ext_{next_wall_idx}",
                type=WallType.PORTEUR,
                thickness_cm=20,
                geometry={"type": "LineString", "coords": [[x0, y0], [x1, y1]]},
                hauteur_cm=260,
                materiau="beton_banche",
            )
            walls.append(wall)
            next_wall_idx += 1

            wall_len_cm = int(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5 * 100)
            if wall_len_cm < 100:
                continue
            # Window size: large for séjour, medium for chambres, small for cuisine-only
            if room.type in (RoomType.SEJOUR, RoomType.SEJOUR_CUISINE):
                op_type = OpeningType.PORTE_FENETRE
                width_cm = min(240, int(wall_len_cm * 0.55))
            elif room.type == RoomType.CUISINE:
                op_type = OpeningType.FENETRE
                width_cm = min(120, int(wall_len_cm * 0.4))
            else:
                op_type = OpeningType.FENETRE
                width_cm = min(140, int(wall_len_cm * 0.45))

            openings.append(Opening(
                id=f"op_ext_{next_op_idx}",
                type=op_type,
                wall_id=wall.id,
                position_along_wall_cm=wall_len_cm // 2,
                width_cm=width_cm,
                height_cm=220 if op_type == OpeningType.PORTE_FENETRE else 200,
                allege_cm=None if op_type == OpeningType.PORTE_FENETRE else 95,
                swing=None,
            ))
            next_op_idx += 1

    # ──────────────── Grid transforms (template orientation) ────────────────

    @staticmethod
    def _choose_grid_transform(orientations: list[str]) -> str:
        """Pick a grid transform so entrée (row 0) lands on the palier side.

        Templates are authored with the façade at the TOP of the grid
        (max_row) and entrée at the BOTTOM (row 0 = palier). We rotate/mirror
        so that orientation matches the slot's exterior sides.

        Heuristic:
        - If slot faces 'sud' (south) — façade at TOP of grid would render
          at the top of the SVG which is the north side of the world. So we
          flip vertically (row → max_row - row) to put the façade at the
          south (miny) side.
        - If slot faces 'nord' alone (rare) — no flip, default orientation.
        - If slot faces 'ouest' only (west) — rotate 90° CCW so the original
          top of the grid (façade) ends up at the west side.
        - If slot faces 'est' only (east) — rotate 90° CW.
        - If slot faces multiple sides (corner apt), prefer 'sud' > 'ouest'
          > 'est' > 'nord' as the primary façade.
        """
        if not orientations:
            return "identity"
        s = set(orientations)
        if "sud" in s:
            return "flip_y"
        if "ouest" in s:
            return "rotate_ccw"
        if "est" in s:
            return "rotate_cw"
        return "identity"

    @staticmethod
    def _transformed_grid_shape(max_col: int, max_row: int, transform: str) -> tuple[int, int]:
        """Return (n_cols, n_rows) of the grid after transform."""
        n_cols = max_col + 1
        n_rows = max_row + 1
        if transform in ("rotate_ccw", "rotate_cw"):
            return n_rows, n_cols
        return n_cols, n_rows

    @staticmethod
    def _apply_grid_transform(
        col: int, row: int, max_col: int, max_row: int, transform: str,
    ) -> tuple[int, int]:
        """Transform (col, row) in the original grid to (col, row) in the
        rotated/flipped grid."""
        if transform == "identity":
            return col, row
        if transform == "flip_y":
            return col, max_row - row
        if transform == "flip_x":
            return max_col - col, row
        if transform == "rotate_cw":
            # 90° clockwise: (col, row) -> (max_row - row, col)
            return max_row - row, col
        if transform == "rotate_ccw":
            # 90° counter-clockwise: (col, row) -> (row, max_col - col)
            return row, max_col - col
        return col, row

    @staticmethod
    def _label_fr(room_type: RoomType) -> str:
        labels = {
            RoomType.ENTREE: "Entrée", RoomType.SEJOUR: "Séjour",
            RoomType.SEJOUR_CUISINE: "Séjour / cuisine", RoomType.CUISINE: "Cuisine",
            RoomType.SDB: "Salle de bain", RoomType.SALLE_DE_DOUCHE: "Salle d'eau",
            RoomType.WC: "WC", RoomType.WC_SDB: "SDB / WC",
            RoomType.CHAMBRE_PARENTS: "Chambre parents",
            RoomType.CHAMBRE_ENFANT: "Chambre enfant",
            RoomType.CHAMBRE_SUPP: "Chambre", RoomType.CELLIER: "Cellier",
            RoomType.PLACARD_TECHNIQUE: "Placard technique",
            RoomType.LOGGIA: "Loggia",
        }
        return labels.get(room_type, room_type.value)

    @staticmethod
    def _place_furniture(room_id: str, room_type: RoomType, polygon: ShapelyPolygon, template: Template) -> list[Furniture]:
        """Place default furniture at centroid + offset (very rough for v1)."""
        default_types = template.furniture_defaults.get(room_type.value, [])
        furniture: list[Furniture] = []
        cx, cy = polygon.centroid.x, polygon.centroid.y
        for i, f_type in enumerate(default_types):
            furniture.append(Furniture(
                type=f_type,
                position_xy=(cx + (i - len(default_types)/2) * 1.0, cy),
                rotation_deg=0.0,
            ))
        return furniture
