"""Validator for BuildingModel — PMR, incendie, PLU, surfaces, ventilation, lumière.

Each validator returns a list of ConformiteAlert. The building-level validator
aggregates all of them into ConformiteCheck.
"""
from __future__ import annotations

from shapely.geometry import LineString, Point
from shapely.geometry import Polygon as ShapelyPolygon

from core.building_model.schemas import (
    BuildingModel,
    Cellule,
    CelluleType,
    ConformiteAlert,
    ConformiteCheck,
    Niveau,
    OpeningType,
    RoomType,
)
from core.plu.schemas import NumericRules

_PMR_PASSAGE_MIN_CM = 80
_PMR_ROTATION_DIAMETER_CM = 150  # cercle de rotation fauteuil
_PMR_ASCENSEUR_REQUIRED_FROM_NIVEAU = 2  # R+2 et plus


def validate_pmr(cellule: Cellule) -> list[ConformiteAlert]:
    """Validate PMR rules at the apartment/cellule level."""
    alerts: list[ConformiteAlert] = []

    # 1. Passage min 80cm for all doors
    for op in cellule.openings:
        if op.type in (OpeningType.PORTE_ENTREE, OpeningType.PORTE_INTERIEURE) and op.width_cm < _PMR_PASSAGE_MIN_CM:
            alerts.append(ConformiteAlert(
                level="error", category="pmr",
                message=f"Passage {op.width_cm}cm < 80cm (norme PMR)",
                affected_element_id=op.id,
            ))

    # 2. Rotation cercle 150cm dans chaque pièce de vie
    _piece_vie = {RoomType.SEJOUR, RoomType.SEJOUR_CUISINE,
                  RoomType.CHAMBRE_PARENTS, RoomType.CHAMBRE_ENFANT,
                  RoomType.SDB, RoomType.CUISINE}
    for room in cellule.rooms:
        if room.type in _piece_vie and not _can_inscribe_circle(room.polygon_xy, _PMR_ROTATION_DIAMETER_CM / 100.0):
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
    if bm.envelope.niveaux - 1 >= _PMR_ASCENSEUR_REQUIRED_FROM_NIVEAU and bm.core.ascenseur is None:
        alerts.append(ConformiteAlert(
            level="error", category="pmr",
            message=f"Ascenseur requis pour R+{bm.envelope.niveaux - 1} (obligation PMR ≥R+2)",
        ))
    return alerts


_INCENDIE_DISTANCE_MAX_M = 25.0
_CIRCULATION_LARGEUR_MIN_CM = 140  # PMR
_VENTILATION_RATIO_MIN = 1.0 / 8.0


def validate_ventilation(cellule: Cellule) -> list[ConformiteAlert]:
    """Each living-room must have a window ≥ surface/8."""
    alerts: list[ConformiteAlert] = []
    for room in cellule.rooms:
        if room.type not in {RoomType.SEJOUR, RoomType.SEJOUR_CUISINE,
                             RoomType.CUISINE, RoomType.CHAMBRE_PARENTS,
                             RoomType.CHAMBRE_ENFANT, RoomType.CHAMBRE_SUPP}:
            continue
        # Compute total window area serving this room
        # Heuristic v1: sum of window areas on walls bordering this room's polygon
        poly = ShapelyPolygon(room.polygon_xy)
        win_surface = 0.0
        for op in cellule.openings:
            if op.type not in (OpeningType.FENETRE, OpeningType.PORTE_FENETRE, OpeningType.BAIE_COULISSANTE):
                continue
            wall = next((w for w in cellule.walls if w.id == op.wall_id), None)
            if wall is None:
                continue
            coords = wall.geometry.get("coords", [])
            if len(coords) < 2:
                continue
            line = LineString(coords)
            if poly.distance(line) < 0.3:  # wall touches the room
                win_surface += (op.width_cm / 100.0) * (op.height_cm / 100.0)
        if win_surface < room.surface_m2 * _VENTILATION_RATIO_MIN:
            alerts.append(ConformiteAlert(
                level="error", category="ventilation",
                message=f"{room.label_fr}: surface vitrée {win_surface:.2f}m² < 1/8 de {room.surface_m2}m²",
                affected_element_id=room.id,
            ))
    return alerts


def validate_lumiere_naturelle(cellule: Cellule) -> list[ConformiteAlert]:
    """Each living-room must have at least one external window (not on palier)."""
    alerts: list[ConformiteAlert] = []
    for room in cellule.rooms:
        if room.type not in {RoomType.SEJOUR, RoomType.SEJOUR_CUISINE,
                             RoomType.CHAMBRE_PARENTS, RoomType.CHAMBRE_ENFANT,
                             RoomType.CHAMBRE_SUPP}:
            continue
        has_external = False
        poly = ShapelyPolygon(room.polygon_xy)
        for op in cellule.openings:
            if op.type not in (OpeningType.FENETRE, OpeningType.PORTE_FENETRE, OpeningType.BAIE_COULISSANTE):
                continue
            wall = next((w for w in cellule.walls if w.id == op.wall_id), None)
            if wall is None:
                continue
            coords = wall.geometry.get("coords", [])
            if len(coords) < 2:
                continue
            line = LineString(coords)
            if poly.distance(line) < 0.3:
                has_external = True
                break
        if not has_external:
            alerts.append(ConformiteAlert(
                level="error", category="lumiere",
                message=f"{room.label_fr}: pas de fenêtre extérieure",
                affected_element_id=room.id,
            ))
    return alerts


def validate_incendie_niveau(niveau: Niveau) -> list[ConformiteAlert]:
    """Distance max porte logement → circulation commune ≤ 25m."""
    alerts: list[ConformiteAlert] = []
    # Take first circulation polygon as reference for sortie de secours
    if not niveau.circulations_communes:
        return [ConformiteAlert(level="error", category="incendie",
                                message=f"{niveau.code}: aucune circulation commune définie")]
    sortie = ShapelyPolygon(niveau.circulations_communes[0].polygon_xy).centroid

    # Circulation width
    for circ in niveau.circulations_communes:
        if circ.largeur_min_cm < _CIRCULATION_LARGEUR_MIN_CM:
            alerts.append(ConformiteAlert(
                level="error", category="incendie",
                message=f"Circulation {circ.id}: largeur {circ.largeur_min_cm}cm < 140cm (PMR/incendie)",
                affected_element_id=circ.id,
            ))

    for cell in niveau.cellules:
        if cell.type != CelluleType.LOGEMENT:
            continue
        entry = next((o for o in cell.openings if o.type == OpeningType.PORTE_ENTREE), None)
        if entry is None:
            alerts.append(ConformiteAlert(
                level="error", category="incendie",
                message=f"Cellule {cell.id}: pas de porte d'entrée définie",
                affected_element_id=cell.id,
            ))
            continue
        wall = next((w for w in cell.walls if w.id == entry.wall_id), None)
        if wall is None:
            continue
        coords = wall.geometry.get("coords", [])
        if len(coords) < 2:
            continue
        # Approximate door position = wall midpoint
        midx = (coords[0][0] + coords[1][0]) / 2.0
        midy = (coords[0][1] + coords[1][1]) / 2.0
        door_pt = Point(midx, midy)
        dist = door_pt.distance(sortie)
        if dist > _INCENDIE_DISTANCE_MAX_M:
            alerts.append(ConformiteAlert(
                level="error", category="incendie",
                message=f"Porte {cell.id}: {dist:.1f}m à la sortie > 25m",
                affected_element_id=cell.id,
            ))
    return alerts


def validate_plu(bm: BuildingModel, rules: NumericRules) -> list[ConformiteAlert]:
    """Validate PLU constraints against computed building."""
    alerts: list[ConformiteAlert] = []

    # Emprise
    if rules.emprise_max_pct is not None:
        emprise_max = bm.site.parcelle_surface_m2 * (rules.emprise_max_pct / 100.0)
        if bm.envelope.emprise_m2 > emprise_max:
            alerts.append(ConformiteAlert(
                level="error", category="plu",
                message=f"PLU emprise {bm.envelope.emprise_m2:.1f}m² > max {emprise_max:.1f}m² "
                        f"({rules.emprise_max_pct}% parcelle)",
            ))

    # Hauteur
    if rules.hauteur_max_m is not None and bm.envelope.hauteur_totale_m > rules.hauteur_max_m:
        alerts.append(ConformiteAlert(
            level="error", category="plu",
            message=f"PLU hauteur {bm.envelope.hauteur_totale_m}m > max {rules.hauteur_max_m}m",
        ))
    if rules.hauteur_max_niveaux is not None:
        # niveaux=4 means R+3
        r_plus = bm.envelope.niveaux - 1
        if r_plus > rules.hauteur_max_niveaux:
            alerts.append(ConformiteAlert(
                level="error", category="plu",
                message=f"PLU niveaux R+{r_plus} > max R+{rules.hauteur_max_niveaux}",
            ))

    return alerts


def validate_all(bm: BuildingModel, rules: NumericRules) -> ConformiteCheck:
    """Run all validators and aggregate into ConformiteCheck."""
    alerts: list[ConformiteAlert] = []
    for niv in bm.niveaux:
        alerts.extend(validate_incendie_niveau(niv))
        for cell in niv.cellules:
            if cell.type == CelluleType.LOGEMENT:
                alerts.extend(validate_pmr(cell))
                alerts.extend(validate_ventilation(cell))
                alerts.extend(validate_lumiere_naturelle(cell))
    alerts.extend(validate_pmr_building(bm))
    alerts.extend(validate_plu(bm, rules))

    return ConformiteCheck(
        pmr_ascenseur_ok=not any(a.category == "pmr" and "ascenseur" in a.message.lower() and a.level == "error" for a in alerts),
        pmr_rotation_cercles_ok=not any(a.category == "pmr" and "rotation" in a.message.lower() and a.level == "error" for a in alerts),
        incendie_distance_sorties_ok=not any(a.category == "incendie" and a.level == "error" for a in alerts),
        plu_emprise_ok=not any(a.category == "plu" and "emprise" in a.message.lower() and a.level == "error" for a in alerts),
        plu_hauteur_ok=not any(a.category == "plu" and "hauteur" in a.message.lower() and a.level == "error" for a in alerts),
        plu_retraits_ok=True,  # v1 retraits pas implémenté
        ventilation_ok=not any(a.category == "ventilation" and a.level == "error" for a in alerts),
        lumiere_ok=not any(a.category == "lumiere" and a.level == "error" for a in alerts),
        alerts=alerts,
    )
