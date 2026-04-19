from datetime import UTC, datetime
from uuid import uuid4

from core.building_model.schemas import (
    BuildingModel,
    ConformiteCheck,
    Core,
    Envelope,
    Escalier,
    Facade,
    Metadata,
    Site,
    ToitureConfig,
    ToitureType,
)
from core.building_model.validator import validate_all, validate_plu
from core.plu.schemas import NumericRules


def _building(emprise_m2: float, niveaux: int, hauteur_totale_m: float) -> BuildingModel:
    return BuildingModel(
        metadata=Metadata(id=uuid4(), project_id=uuid4(), address="A",
                          zone_plu="UA", created_at=datetime.now(UTC),
                          updated_at=datetime.now(UTC), version=1, locked=False),
        site=Site(parcelle_geojson={"type":"Polygon","coordinates":[[[0,0],[20,0],[20,20],[0,20],[0,0]]]},
                  parcelle_surface_m2=400.0, voirie_orientations=["sud"], north_angle_deg=0.0),
        envelope=Envelope(footprint_geojson={"type":"Polygon","coordinates":[[[0,0],[10,0],[10,10],[0,10],[0,0]]]},
                          emprise_m2=emprise_m2, niveaux=niveaux, hauteur_totale_m=hauteur_totale_m,
                          hauteur_rdc_m=3.0, hauteur_etage_courant_m=2.7,
                          toiture=ToitureConfig(type=ToitureType.TERRASSE, accessible=False, vegetalisee=False)),
        core=Core(position_xy=(5.0,5.0), surface_m2=10.0,
                  escalier=Escalier(type="droit", giron_cm=28, hauteur_marche_cm=17, nb_marches_par_niveau=18),
                  ascenseur=None, gaines_techniques=[]),
        niveaux=[],
        facades={k: Facade(style="e", composition=[], rgb_main="#fff") for k in ("nord","sud","est","ouest")},
    )


def _rules(emprise_max_pct: float = 40.0, hauteur_max_m: float = 20.0,
           pleine_terre_min_pct: float = 30.0) -> NumericRules:
    return NumericRules(
        emprise_max_pct=emprise_max_pct, hauteur_max_m=hauteur_max_m,
        pleine_terre_min_pct=pleine_terre_min_pct,
        retrait_voirie_m=None, retrait_limite_m=4.0,
        stationnement_pct=100.0, hauteur_max_niveaux=6,
    )


def test_plu_emprise_ok():
    bm = _building(emprise_m2=80.0, niveaux=3, hauteur_totale_m=9.0)
    # parcelle 400m² × 40% = 160m². 80 ok
    alerts = validate_plu(bm, _rules(emprise_max_pct=40.0))
    assert not any(a.category == "plu" and "emprise" in a.message.lower() for a in alerts)


def test_plu_emprise_fails():
    bm = _building(emprise_m2=200.0, niveaux=3, hauteur_totale_m=9.0)
    alerts = validate_plu(bm, _rules(emprise_max_pct=40.0))
    assert any(a.category == "plu" and "emprise" in a.message.lower() and a.level == "error" for a in alerts)


def test_plu_hauteur_fails():
    bm = _building(emprise_m2=80.0, niveaux=6, hauteur_totale_m=25.0)
    alerts = validate_plu(bm, _rules(hauteur_max_m=20.0))
    assert any(a.category == "plu" and "hauteur" in a.message.lower() and a.level == "error" for a in alerts)


def test_validate_all_returns_conformite_check():
    bm = _building(emprise_m2=80.0, niveaux=3, hauteur_totale_m=9.0)
    check = validate_all(bm, _rules())
    assert isinstance(check, ConformiteCheck)
    assert check.plu_emprise_ok is True
