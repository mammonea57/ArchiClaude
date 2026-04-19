import pytest
from core.building_model.schemas import (
    BuildingModel, Cellule, CelluleType, Typologie, Niveau, Room, RoomType,
    Wall, WallType, Opening, OpeningType, Metadata, Site, Envelope, Core, Escalier,
    Facade, ToitureConfig, ToitureType, Circulation,
)
from core.building_model.validator import (
    validate_incendie_niveau, validate_ventilation, validate_lumiere_naturelle,
)
from uuid import uuid4
from datetime import datetime, UTC


def _appt(orientation_with_fenetre: bool) -> Cellule:
    walls = []
    openings = []
    if orientation_with_fenetre:
        walls.append(Wall(id="w_ext", type=WallType.PORTEUR, thickness_cm=20,
                          geometry={"type":"LineString","coords":[[0,0],[5,0]]},
                          hauteur_cm=260, materiau="beton"))
        openings.append(Opening(id="fen1", type=OpeningType.FENETRE, wall_id="w_ext",
                                position_along_wall_cm=200,
                                width_cm=160, height_cm=200, allege_cm=95))
    return Cellule(
        id="appt1", type=CelluleType.LOGEMENT, typologie=Typologie.T2,
        surface_m2=50.0, polygon_xy=[(0,0),(5,0),(5,10),(0,10)],
        orientation=["sud"] if orientation_with_fenetre else [],
        rooms=[Room(id="sej", type=RoomType.SEJOUR, surface_m2=25.0,
                    polygon_xy=[(0,0),(5,0),(5,5),(0,5)],
                    orientation=["sud"] if orientation_with_fenetre else None,
                    label_fr="Séjour")],
        walls=walls, openings=openings,
    )


def test_ventilation_fails_when_window_too_small():
    appt = _appt(orientation_with_fenetre=False)
    alerts = validate_ventilation(appt)
    assert any(a.category == "ventilation" for a in alerts)


def test_ventilation_ok_with_adequate_window():
    appt = _appt(orientation_with_fenetre=True)
    alerts = validate_ventilation(appt)
    # 160×200 = 3.2m² > 25m²/8 = 3.125m² — just OK
    assert not any(a.category == "ventilation" and a.level == "error" for a in alerts)


def test_lumiere_fails_for_room_with_no_external_wall():
    appt = _appt(orientation_with_fenetre=False)
    alerts = validate_lumiere_naturelle(appt)
    assert any(a.category == "lumiere" for a in alerts)


def test_incendie_niveau_warns_far_door():
    """Sorties de secours distance ≤25m from any apartment door."""
    niv = Niveau(index=1, code="R+1", usage_principal="logements",
                 hauteur_sous_plafond_m=2.7, surface_plancher_m2=500.0,
                 cellules=[
                     Cellule(id="a", type=CelluleType.LOGEMENT, typologie=Typologie.T2,
                             surface_m2=50.0, polygon_xy=[(0,0),(5,0),(5,10),(0,10)],
                             openings=[Opening(id="door_entry", type=OpeningType.PORTE_ENTREE,
                                               wall_id="w1", position_along_wall_cm=0,
                                               width_cm=90, height_cm=210)],
                             walls=[Wall(id="w1", type=WallType.PORTEUR, thickness_cm=20,
                                         geometry={"type":"LineString","coords":[[40,0],[40,5]]},
                                         hauteur_cm=260, materiau="beton")]),
                 ],
                 circulations_communes=[Circulation(id="pal1",
                                        polygon_xy=[(0,0),(2,0),(2,2),(0,2)],
                                        surface_m2=4.0, largeur_min_cm=140)])
    alerts = validate_incendie_niveau(niv)
    # 40m distance > 25m → warning
    assert any(a.category == "incendie" for a in alerts)
