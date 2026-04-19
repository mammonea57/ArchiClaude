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
        max_col = max(max(c[0] for c in room["bounds_cells"]) for room in topo["rooms"])
        max_row = max(max(c[1] for c in room["bounds_cells"]) for room in topo["rooms"])
        n_cols = max_col + 1
        n_rows = max_row + 1
        cell_w = slot_width / n_cols
        cell_h = slot_depth / n_rows
        stretch_x = cell_w / 3.0
        stretch_y = cell_h / 3.0

        # 2. Build rooms with scaled polygons
        rooms: list[Room] = []
        for abs_room in template.topologie["rooms"]:
            cell_polys = []
            for col, row in abs_room["bounds_cells"]:
                x0 = minx + col * cell_w
                y0 = miny + row * cell_h
                cell_polys.append(ShapelyPolygon([
                    (x0, y0), (x0 + cell_w, y0),
                    (x0 + cell_w, y0 + cell_h),
                    (x0, y0 + cell_h),
                ]))
            if len(cell_polys) == 1:
                merged = cell_polys[0]
            else:
                merged = cell_polys[0]
                for p in cell_polys[1:]:
                    merged = merged.union(p)
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

        # 3. Build walls (scaled coordinates)
        walls: list[Wall] = []
        for i, aw in enumerate(template.topologie.get("walls_abstract", [])):
            from_x = minx + aw["from_cell"][0] * cell_w
            from_y = miny + aw["from_cell"][1] * cell_h
            to_x = minx + aw["to_cell"][0] * cell_w
            to_y = miny + aw["to_cell"][1] * cell_h
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

        # 5. Build Cellule
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
