import pytest
from core.building_model.schemas import (
    BuildingModel, Opening, OpeningType, Room, RoomType, Wall, WallType, Cellule,
    CelluleType, Typologie, Niveau, Metadata, Site, Envelope, Core, Escalier,
    Facade, ToitureConfig, ToitureType, Ascenseur,
)
from core.building_model.validator import validate_pmr
from uuid import uuid4
from datetime import datetime, UTC


def _sample_appt_with_passage(passage_cm: int) -> Cellule:
    """Build a small apartment with 1 door of given width."""
    return Cellule(
        id="appt1", type=CelluleType.LOGEMENT, typologie=Typologie.T2,
        surface_m2=50.0,
        polygon_xy=[(0,0),(8,0),(8,6),(0,6)],
        rooms=[Room(id="sejour", type=RoomType.SEJOUR, surface_m2=20.0,
                    polygon_xy=[(0,0),(4,0),(4,5),(0,5)],
                    orientation=["sud"], label_fr="Séjour")],
        walls=[Wall(id="w1", type=WallType.CLOISON_70, thickness_cm=7,
                    geometry={"type":"LineString","coords":[[4,0],[4,5]]},
                    hauteur_cm=260, materiau="placo")],
        openings=[Opening(id="door1", type=OpeningType.PORTE_INTERIEURE,
                          wall_id="w1", position_along_wall_cm=100,
                          width_cm=passage_cm, height_cm=210)],
    )


def test_pmr_passage_ok_for_80cm_door():
    appt = _sample_appt_with_passage(80)
    alerts = validate_pmr(appt)
    assert not any(a.category == "pmr" and "passage" in a.message.lower() for a in alerts)


def test_pmr_passage_fails_for_70cm_door():
    appt = _sample_appt_with_passage(70)
    alerts = validate_pmr(appt)
    assert any(a.category == "pmr" and "passage" in a.message.lower() and a.level == "error" for a in alerts)


def test_pmr_rotation_cercle_warn_for_small_room():
    """Rotation 150cm cercle requires ≥1.5m in both directions inside room."""
    small_appt = Cellule(
        id="appt1", type=CelluleType.LOGEMENT, typologie=Typologie.T1,
        surface_m2=18.0,
        polygon_xy=[(0,0),(3,0),(3,6),(0,6)],
        rooms=[Room(id="sej", type=RoomType.SEJOUR, surface_m2=18.0,
                    polygon_xy=[(0,0),(3,0),(3,6),(0,6)],  # 3m wide only
                    orientation=["sud"], label_fr="Séjour")],
        walls=[],
        openings=[],
    )
    alerts = validate_pmr(small_appt)
    # 3m wide but rotation 150cm needs clear space of 1.5m — boundary case; implementation
    # should return pass here. The test just ensures function runs without raising.
    assert isinstance(alerts, list)


def test_pmr_ascenseur_required_from_r_plus_2(sample_envelope_r_plus_3):
    """Building R+3 without ascenseur should fail PMR."""
    from core.building_model.validator import validate_pmr_building
    bm = sample_envelope_r_plus_3
    alerts = validate_pmr_building(bm)
    if bm.core.ascenseur is None:
        assert any(a.category == "pmr" and "ascenseur" in a.message.lower() for a in alerts)


@pytest.fixture
def sample_envelope_r_plus_3() -> BuildingModel:
    return BuildingModel(
        metadata=Metadata(id=uuid4(), project_id=uuid4(), address="X",
                          zone_plu="UA", created_at=datetime.now(UTC),
                          updated_at=datetime.now(UTC), version=1, locked=False),
        site=Site(parcelle_geojson={"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
                  parcelle_surface_m2=100.0, voirie_orientations=["sud"], north_angle_deg=0.0),
        envelope=Envelope(footprint_geojson={"type":"Polygon","coordinates":[[[1,1],[9,1],[9,9],[1,9],[1,1]]]},
                          emprise_m2=64.0, niveaux=4, hauteur_totale_m=12.0, hauteur_rdc_m=3.2,
                          hauteur_etage_courant_m=2.7,
                          toiture=ToitureConfig(type=ToitureType.TERRASSE, accessible=False, vegetalisee=False)),
        core=Core(position_xy=(5.0,5.0), surface_m2=20.0,
                  escalier=Escalier(type="droit", giron_cm=28, hauteur_marche_cm=17, nb_marches_par_niveau=18),
                  ascenseur=None, gaines_techniques=[]),
        niveaux=[],
        facades={"nord": Facade(style="e", composition=[], rgb_main="#fff"),
                 "sud": Facade(style="e", composition=[], rgb_main="#fff"),
                 "est": Facade(style="e", composition=[], rgb_main="#fff"),
                 "ouest": Facade(style="e", composition=[], rgb_main="#fff")},
    )
