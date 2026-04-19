import pytest
from uuid import uuid4
from datetime import UTC, datetime

from core.building_model.schemas import (
    BuildingModel, Metadata, Site, Envelope, Core, Niveau, Cellule, Room, Wall,
    Opening, Facade, ToitureConfig, Escalier, Ascenseur, RoomType, WallType,
    CelluleType, Typologie, OpeningType,
)


def _minimal_building_model() -> BuildingModel:
    """A tiny valid building model for tests."""
    return BuildingModel(
        metadata=Metadata(
            id=uuid4(), project_id=uuid4(),
            address="80 Rue Test, 94130 Nogent-sur-Marne",
            zone_plu="UA",
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
            version=1, locked=False,
        ),
        site=Site(
            parcelle_geojson={"type": "Polygon", "coordinates": [[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
            parcelle_surface_m2=100.0,
            voirie_orientations=["sud"],
            north_angle_deg=0.0,
        ),
        envelope=Envelope(
            footprint_geojson={"type": "Polygon", "coordinates": [[[1,1],[9,1],[9,9],[1,9],[1,1]]]},
            emprise_m2=64.0,
            niveaux=2,
            hauteur_totale_m=6.5,
            hauteur_rdc_m=3.2,
            hauteur_etage_courant_m=2.7,
            toiture=ToitureConfig(type="terrasse", accessible=False, vegetalisee=False),
        ),
        core=Core(
            position_xy=(5.0, 5.0),
            surface_m2=20.0,
            escalier=Escalier(
                type="droit", giron_cm=28, hauteur_marche_cm=17,
                nb_marches_par_niveau=18,
            ),
            ascenseur=None,
            gaines_techniques=[],
        ),
        niveaux=[],
        facades={
            "nord": Facade(style="enduit_clair", composition=[], rgb_main="#EEEEEE"),
            "sud":  Facade(style="enduit_clair", composition=[], rgb_main="#EEEEEE"),
            "est":  Facade(style="enduit_clair", composition=[], rgb_main="#EEEEEE"),
            "ouest":Facade(style="enduit_clair", composition=[], rgb_main="#EEEEEE"),
        },
        materiaux_rendu={},
    )


def test_minimal_model_validates():
    bm = _minimal_building_model()
    assert bm.metadata.version == 1
    assert bm.envelope.emprise_m2 == 64.0


def test_room_type_enum_accepts_known_values():
    r = Room(id="r1", type=RoomType.SEJOUR, surface_m2=20.0,
             polygon_xy=[(0,0),(4,0),(4,5),(0,5)],
             orientation=["sud"], label_fr="Séjour")
    assert r.type == RoomType.SEJOUR


def test_wall_type_enum_rejects_unknown():
    with pytest.raises(Exception):
        Wall(
            id="w1",
            type="wall_de_bouilli",  # not a valid WallType
            thickness_cm=20,
            geometry={"type":"LineString","coords":[[0,0],[4,0]]},
            hauteur_cm=260,
            materiau="beton",
        )


def test_building_model_round_trip_json():
    bm = _minimal_building_model()
    raw = bm.model_dump_json()
    reloaded = BuildingModel.model_validate_json(raw)
    assert reloaded.envelope.niveaux == bm.envelope.niveaux


def test_opening_type_enum_includes_expected():
    op = Opening(
        id="o1", type=OpeningType.PORTE_ENTREE,
        wall_id="w1", position_along_wall_cm=100,
        width_cm=93, height_cm=210,
    )
    assert op.type == OpeningType.PORTE_ENTREE
