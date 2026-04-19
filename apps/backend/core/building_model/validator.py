"""Validator for BuildingModel — PMR, incendie, PLU, surfaces, ventilation, lumière.

Each validator returns a list of ConformiteAlert. The building-level validator
aggregates all of them into ConformiteCheck.
"""
from __future__ import annotations

from core.building_model.schemas import (
    BuildingModel, Cellule, CelluleType, ConformiteAlert, Niveau, OpeningType,
    Room, RoomType,
)

_PMR_PASSAGE_MIN_CM = 80
_PMR_ROTATION_DIAMETER_CM = 150  # cercle de rotation fauteuil
_PMR_ASCENSEUR_REQUIRED_FROM_NIVEAU = 2  # R+2 et plus


def validate_pmr(cellule: Cellule) -> list[ConformiteAlert]:
    """Validate PMR rules at the apartment/cellule level."""
    alerts: list[ConformiteAlert] = []

    # 1. Passage min 80cm for all doors
    for op in cellule.openings:
        if op.type in (OpeningType.PORTE_ENTREE, OpeningType.PORTE_INTERIEURE):
            if op.width_cm < _PMR_PASSAGE_MIN_CM:
                alerts.append(ConformiteAlert(
                    level="error", category="pmr",
                    message=f"Passage {op.width_cm}cm < 80cm (norme PMR)",
                    affected_element_id=op.id,
                ))

    # 2. Rotation cercle 150cm dans chaque pièce de vie
    for room in cellule.rooms:
        if room.type in {RoomType.SEJOUR, RoomType.SEJOUR_CUISINE,
                         RoomType.CHAMBRE_PARENTS, RoomType.CHAMBRE_ENFANT,
                         RoomType.SDB, RoomType.CUISINE}:
            if not _can_inscribe_circle(room.polygon_xy, _PMR_ROTATION_DIAMETER_CM / 100.0):
                alerts.append(ConformiteAlert(
                    level="warning", category="pmr",
                    message=f"Rotation cercle 150cm non inscriptible dans {room.label_fr}",
                    affected_element_id=room.id,
                ))

    return alerts


def _can_inscribe_circle(polygon: list[tuple[float, float]], diameter_m: float) -> bool:
    """Return True if a circle of given diameter fits inside the polygon."""
    from shapely.geometry import Polygon as ShapelyPolygon
    if len(polygon) < 3:
        return False
    poly = ShapelyPolygon(polygon)
    # Approximation: the largest inscribed circle has radius ≈ distance from centroid to boundary
    # for convex quasi-rectangular rooms. For non-convex rooms this is an under-estimate (safe).
    centroid = poly.centroid
    radius = poly.exterior.distance(centroid)
    return radius >= diameter_m / 2.0


def validate_pmr_building(bm: BuildingModel) -> list[ConformiteAlert]:
    """Validate PMR rules that require the whole building (e.g. ascenseur)."""
    alerts: list[ConformiteAlert] = []
    if bm.envelope.niveaux - 1 >= _PMR_ASCENSEUR_REQUIRED_FROM_NIVEAU:
        if bm.core.ascenseur is None:
            alerts.append(ConformiteAlert(
                level="error", category="pmr",
                message=f"Ascenseur requis pour R+{bm.envelope.niveaux - 1} (obligation PMR ≥R+2)",
            ))
    return alerts
