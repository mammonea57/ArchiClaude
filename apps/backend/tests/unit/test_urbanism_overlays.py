"""Tests for ``core.urbanism_overlays`` schemas.

Compliant / non-compliant examples per category. Lives under
``tests/unit/`` to avoid the truncating fixture in ``tests/`` root
(memory feedback_dont_truncate_prod_db).
"""

from __future__ import annotations

from datetime import date

import pytest

from core.urbanism_overlays.schemas import (
    # Base
    BaseUrbanismOverlay,
    OverlayCategory,
    OverlayViolation,
    ProjectContext,
    UrbanismOverlayBundle,
    # A
    PLUReglement,
    PLUZonage,
    OAPSectorielle,
    OAPBioclim,
    ER45,
    Patrimoine43,
    # B
    SUP_AC1, SUP_AS1, SUP_T7, SUP_INT1,
    # C
    PPRI, RGA, BASOL, SIS, ERP,
    # D
    L_151_19, PSMV, SPR,
    # E
    L_151_15_SMS, L_151_16_Lineaire, SRU_Art55, T3PlusQuota,
    # F
    Natura2000, EBC, ZonesHumides, IOTA, EvaluationEnvironnementale, EspecesProtegees,
    # G
    R_111_18_Vues, RNU_R_111, RE2020, PMR,
    # H
    ZAN, CDAC_CDPENAF, Loi_Littoral, DUP,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ctx(**over) -> ProjectContext:
    base = {
        "parcelle_geojson": {
            "type": "Polygon",
            "coordinates": [[[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]],
        },
        "footprint_geojson": {
            "type": "Polygon",
            "coordinates": [[[2, 2], [18, 2], [18, 18], [2, 18], [2, 2]]],
        },
        "parcelle_surface_m2": 400.0,
        "emprise_m2": 256.0,
        "hauteur_totale_m": 10.0,
        "niveaux": 3,
        "sdp_m2": 750.0,
        "nb_logements": 10,
        "typologies": {"T1": 1, "T2": 2, "T3": 4, "T4": 3},
        "pct_lls": 30.0,
        "commune_insee": "94052",
        "zone_plu": "UA1",
    }
    base.update(over)
    return ProjectContext(**base)


# ---------------------------------------------------------------------------
# Generic base behaviour
# ---------------------------------------------------------------------------


def test_overlay_not_applicable_yields_no_violations():
    ov = PLUReglement(applies=False, hauteur_max_m=5.0)
    assert ov.validate(_ctx(hauteur_totale_m=30.0)) == []
    assert ov.to_buildable_impact().endswith("non applicable.")


def test_overlay_violation_shape():
    ov = PPRI(applies=True, zone_alea="rouge")
    vs = ov.validate(_ctx())
    assert all(isinstance(v, OverlayViolation) for v in vs)
    assert vs[0].overlay_code == "PPRI"
    assert vs[0].severity == "blocking"


# ---------------------------------------------------------------------------
# A. PLU
# ---------------------------------------------------------------------------


def test_plu_zonage_interdit_habitation_blocking():
    ov = PLUZonage(applies=True, zone_code="N", destinations_interdites=["habitation"])
    vs = ov.validate(_ctx())
    assert any(v.severity == "blocking" for v in vs)


def test_plu_reglement_compliant_height_emprise():
    ov = PLUReglement(applies=True, hauteur_max_m=12.0, emprise_max_pct=80.0)
    # parcelle 400 m², emprise 256 m² → 64% < 80%, hauteur 10 < 12
    assert ov.validate(_ctx()) == []


def test_plu_reglement_non_compliant_height():
    ov = PLUReglement(applies=True, hauteur_max_m=8.0)
    vs = ov.validate(_ctx(hauteur_totale_m=10.0))
    assert vs and vs[0].severity == "blocking" and "Hauteur" in vs[0].message


def test_plu_reglement_non_compliant_emprise():
    ov = PLUReglement(applies=True, emprise_max_pct=50.0)
    vs = ov.validate(_ctx())  # 64% > 50%
    assert vs and vs[0].severity == "blocking" and "Emprise" in vs[0].message


def test_oap_sectorielle_height_violation():
    ov = OAPSectorielle(applies=True, secteur_name="Gare", hauteur_max_m=7.0)
    assert ov.validate(_ctx(hauteur_totale_m=10.0))[0].severity == "blocking"


def test_oap_bioclim_summary():
    ov = OAPBioclim(applies=True, coef_biotope_min=0.35, pct_pleine_terre_min=30)
    s = ov.to_buildable_impact()
    assert "CBS" in s and "PT" in s


def test_er_4_5_blocks_construction():
    ov = ER45(applies=True, bénéficiaire="Commune", destination="école")
    vs = ov.validate(_ctx())
    assert vs and vs[0].severity == "blocking"


def test_patrimoine_4_3_warns_when_elements_present():
    ov = Patrimoine43(applies=True, elements_proteges=["maison ouvrière 1900"])
    assert ov.validate(_ctx())[0].severity == "warning"


# ---------------------------------------------------------------------------
# B. SUP
# ---------------------------------------------------------------------------


def test_sup_ac1_blocks_with_abf():
    ov = SUP_AC1(applies=True)
    vs = ov.validate(_ctx())
    assert vs and vs[0].severity == "blocking" and "ABF" in vs[0].message


def test_sup_as1_captage():
    ov = SUP_AS1(applies=True)
    assert ov.validate(_ctx())[0].severity == "blocking"


def test_sup_t7_height_violation():
    ov = SUP_T7(applies=True, hauteur_max_m=8.0)
    vs = ov.validate(_ctx(hauteur_totale_m=10.0))
    assert vs and vs[0].severity == "blocking" and "T7" in vs[0].message


def test_sup_t7_height_compliant():
    ov = SUP_T7(applies=True, hauteur_max_m=15.0)
    # T7 base also emits a warning by default — t7 overrides _validate_impl
    # and only emits violations when height exceeds. So compliant → [].
    assert ov.validate(_ctx(hauteur_totale_m=10.0)) == []


def test_sup_int1_has_radius_100m():
    ov = SUP_INT1(applies=True)
    assert ov.rayon_protection_m == 100.0


def test_sup_category_is_b():
    assert SUP_AC1().category == OverlayCategory.B_SUP


# ---------------------------------------------------------------------------
# C. Risque
# ---------------------------------------------------------------------------


def test_ppri_zone_rouge_blocks():
    vs = PPRI(applies=True, zone_alea="rouge").validate(_ctx())
    assert vs[0].severity == "blocking"


def test_ppri_zone_blanc_ok():
    assert PPRI(applies=True, zone_alea="blanc").validate(_ctx()) == []


def test_ppri_basement_blocked_in_orange_zone():
    vs = PPRI(applies=True, zone_alea="orange").validate(_ctx(has_basement=True))
    # 1 error (sous-sol interdit) + 1 blocking (basement)
    msgs = [v.message for v in vs]
    assert any("Sous-sol" in m for m in msgs)


def test_rga_moyen_emits_warning():
    vs = RGA(applies=True, niveau="moyen").validate(_ctx())
    assert vs and vs[0].severity == "warning"


def test_rga_faible_no_warning():
    assert RGA(applies=True, niveau="faible").validate(_ctx()) == []


def test_basol_blocks_with_attestation():
    vs = BASOL(applies=True).validate(_ctx())
    assert vs[0].severity == "blocking" and "L.556-1" in vs[0].message


def test_sis_blocks_with_attestation_l125_6():
    vs = SIS(applies=True).validate(_ctx())
    assert vs[0].severity == "blocking" and "L.125-6" in vs[0].message


def test_erp_metadata_only():
    ov = ERP(applies=True, type_erp="N", categorie="3")
    # ERP has no _validate_impl override → returns []
    assert ov.validate(_ctx()) == []


# ---------------------------------------------------------------------------
# D. Patrimoine
# ---------------------------------------------------------------------------


def test_l_151_19_blocks_demolition():
    ov = L_151_19(applies=True, designation="Hôtel particulier")
    vs = ov.validate(_ctx())
    assert vs and vs[0].article_ref == "L.151-19 CU"


def test_psmv_blocks_with_abf():
    assert PSMV(applies=True).validate(_ctx())[0].severity == "blocking"


def test_spr_emits_error():
    vs = SPR(applies=True).validate(_ctx())
    assert vs and vs[0].severity == "error"


# ---------------------------------------------------------------------------
# E. Mixité
# ---------------------------------------------------------------------------


def test_l_151_15_sms_compliant():
    ov = L_151_15_SMS(applies=True, pct_lls_min=30.0)
    assert ov.validate(_ctx(pct_lls=30.0)) == []


def test_l_151_15_sms_non_compliant():
    ov = L_151_15_SMS(applies=True, pct_lls_min=30.0)
    vs = ov.validate(_ctx(pct_lls=20.0))
    assert vs and vs[0].severity == "blocking" and "LLS" in vs[0].message


def test_l_151_16_lineaire_blocks_rdc_habitation():
    ov = L_151_16_Lineaire(applies=True, destination_imposee="commerce")
    assert ov.validate(_ctx())[0].severity == "blocking"


def test_sru_art55_blocks_carence():
    ov = SRU_Art55(
        applies=True,
        pct_lls_commune=15.0,           # commune en carence (< 25%)
        seuil_legal_pct=25.0,
        operation_seuil_logements=12,
        pct_lls_min_operation=30.0,
    )
    vs = ov.validate(_ctx(nb_logements=15, pct_lls=20.0))
    assert vs and vs[0].severity == "blocking"


def test_sru_art55_does_not_block_compliant_commune():
    ov = SRU_Art55(applies=True, pct_lls_commune=40.0, pct_lls_min_operation=30.0)
    assert ov.validate(_ctx(nb_logements=20, pct_lls=10.0)) == []


def test_t3_plus_quota_compliant():
    ov = T3PlusQuota(applies=True, pct_t3_plus_min=50.0)
    # _ctx default = 1 T1 + 2 T2 + 4 T3 + 3 T4 → 7/10 = 70%
    assert ov.validate(_ctx()) == []


def test_t3_plus_quota_non_compliant():
    ov = T3PlusQuota(applies=True, pct_t3_plus_min=80.0)
    vs = ov.validate(_ctx())  # 70% < 80%
    assert vs and vs[0].severity == "blocking"


# ---------------------------------------------------------------------------
# F. Environnement
# ---------------------------------------------------------------------------


def test_natura2000_requires_evaluation():
    vs = Natura2000(applies=True).validate(_ctx())
    assert vs and vs[0].severity == "blocking" and "incidences" in vs[0].message


def test_ebc_blocks_defrichement():
    assert EBC(applies=True).validate(_ctx())[0].severity == "blocking"


def test_zones_humides_blocks():
    assert ZonesHumides(applies=True).validate(_ctx())[0].severity == "blocking"


def test_iota_under_threshold():
    assert IOTA(applies=True).validate(_ctx(parcelle_surface_m2=5_000)) == []


def test_iota_declaration_threshold():
    vs = IOTA(applies=True).validate(_ctx(parcelle_surface_m2=15_000))
    assert vs and vs[0].severity == "warning"


def test_iota_autorisation_threshold():
    vs = IOTA(applies=True).validate(_ctx(parcelle_surface_m2=25_000))
    assert vs and vs[0].severity == "blocking"


def test_evaluation_environnementale_threshold():
    vs = EvaluationEnvironnementale(applies=True).validate(_ctx(sdp_m2=50_000))
    assert vs and vs[0].article_ref == "R.122-2 CE"


def test_especes_protegees_blocking_when_present():
    vs = EspecesProtegees(applies=True, especes=["Pipistrelle commune"]).validate(_ctx())
    assert vs and vs[0].severity == "blocking"


def test_especes_protegees_none():
    assert EspecesProtegees(applies=True, especes=[]).validate(_ctx()) == []


# ---------------------------------------------------------------------------
# G. Règles bâtiment
# ---------------------------------------------------------------------------


def test_r_111_18_compliant():
    ov = R_111_18_Vues(applies=True, distance_min_m=6.0)
    assert ov.validate(_ctx(distance_to_axis_m={"voisin_chambre": 6.5})) == []


def test_r_111_18_non_compliant():
    ov = R_111_18_Vues(applies=True, distance_min_m=6.0)
    vs = ov.validate(_ctx(distance_to_axis_m={"voisin_chambre": 4.2}))
    assert vs and vs[0].severity == "blocking" and vs[0].article_ref == "R.111-18 CU"


def test_rnu_default_applies():
    assert RNU_R_111().applies is True


def test_re2020_summary():
    s = RE2020(applies=True).to_buildable_impact()
    assert "RE2020" in s


def test_pmr_summary():
    s = PMR(applies=True).to_buildable_impact()
    assert "PMR" in s


# ---------------------------------------------------------------------------
# H. Supra
# ---------------------------------------------------------------------------


def test_zan_default_objectif():
    assert ZAN(applies=True).objectif_pct_reduction_2031 == 50.0


def test_cdac_emits_warning():
    vs = CDAC_CDPENAF(applies=True).validate(_ctx())
    assert vs and vs[0].severity == "warning"


def test_loi_littoral_blocks():
    assert Loi_Littoral(applies=True).validate(_ctx())[0].severity == "blocking"


def test_dup_blocks():
    assert DUP(applies=True).validate(_ctx())[0].severity == "blocking"


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


def test_bundle_validate_all_aggregates_violations():
    bundle = UrbanismOverlayBundle(
        plu_reglement=PLUReglement(applies=True, hauteur_max_m=8.0),  # violation
        mixite=[L_151_15_SMS(applies=True, pct_lls_min=30.0)],         # ok
        risques=[PPRI(applies=True, zone_alea="rouge")],               # blocking
        sups=[SUP_AC1(applies=True)],                                  # blocking
    )
    violations = bundle.validate_all(_ctx(hauteur_totale_m=12.0, pct_lls=30.0))
    codes = {v.overlay_code for v in violations}
    assert {"PLU_REGLEMENT", "PPRI", "SUP_AC1"}.issubset(codes)


def test_bundle_blocking_violations_filters_severity():
    bundle = UrbanismOverlayBundle(
        risques=[RGA(applies=True, niveau="moyen")],  # warning only
        environnement=[Natura2000(applies=True)],     # blocking
    )
    blocking = bundle.blocking_violations(_ctx())
    assert all(v.severity in {"blocking", "error"} for v in blocking)
    assert {v.overlay_code for v in blocking} == {"NATURA2000"}


def test_bundle_impact_summary_only_applicable():
    bundle = UrbanismOverlayBundle(
        plu_zonage=PLUZonage(applies=True, zone_code="UA1"),
        plu_reglement=PLUReglement(applies=False, hauteur_max_m=12.0),
        sups=[SUP_AC1(applies=True)],
    )
    out = bundle.buildable_impact_summary()
    # Reglement not applicable → not in summary
    assert any("UA1" in s for s in out)
    assert any("AC1" in s for s in out)
    assert not any("Règlement PLU" in s for s in out)


def test_bundle_all_overlays_count_matches_inputs():
    bundle = UrbanismOverlayBundle(
        plu_zonage=PLUZonage(applies=True, zone_code="UA"),
        plu_reglement=PLUReglement(applies=True, hauteur_max_m=12.0),
        oap_bioclim=OAPBioclim(applies=True),
        oap_sectorielle=[OAPSectorielle(applies=True, secteur_name="A"),
                         OAPSectorielle(applies=True, secteur_name="B")],
        sups=[SUP_AC1(applies=True), SUP_AS1(applies=True), SUP_T7(applies=True)],
        risques=[PPRI(applies=True, zone_alea="blanc"), RGA(applies=True, niveau="faible")],
        patrimoine=[L_151_19(applies=True), PSMV(applies=True), SPR(applies=True)],
        mixite=[L_151_15_SMS(applies=True), T3PlusQuota(applies=True)],
        environnement=[Natura2000(applies=True), EBC(applies=True), IOTA(applies=True)],
        regles_batiment=[RNU_R_111(), R_111_18_Vues(applies=True), RE2020(applies=True),
                         PMR(applies=True)],
        supra=[ZAN(applies=True), CDAC_CDPENAF(applies=True), Loi_Littoral(applies=True)],
    )
    overlays = bundle.all_overlays()
    # 3 + 2 (oap_sect) + 3 (sup) + 2 + 3 + 2 + 3 + 4 + 3 = 25
    assert len(overlays) == 25
    # Every overlay must have the required base API
    for ov in overlays:
        assert isinstance(ov, BaseUrbanismOverlay)
        assert hasattr(ov, "validate") and hasattr(ov, "to_buildable_impact")


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_overlay_round_trip_json():
    ov = PLUReglement(
        applies=True, hauteur_max_m=15.0, emprise_max_pct=60.0,
        source_url="https://geoportail-urbanisme.gouv.fr/...",
        last_updated=date(2026, 1, 1),
    )
    raw = ov.model_dump_json()
    back = PLUReglement.model_validate_json(raw)
    assert back.hauteur_max_m == 15.0
    assert back.last_updated == date(2026, 1, 1)


def test_bundle_round_trip_json():
    bundle = UrbanismOverlayBundle(
        plu_zonage=PLUZonage(applies=True, zone_code="UA"),
        risques=[PPRI(applies=True, zone_alea="blanc")],
    )
    raw = bundle.model_dump_json()
    back = UrbanismOverlayBundle.model_validate_json(raw)
    assert back.plu_zonage is not None
    assert back.plu_zonage.zone_code == "UA"
    assert len(back.risques) == 1


# ---------------------------------------------------------------------------
# Non-regression on BuildingModel
# ---------------------------------------------------------------------------


def test_building_model_still_loads_without_overlays():
    """Adding ``urbanism_overlays`` field must not break existing models."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from core.building_model.schemas import (
        BuildingModel, Core, Envelope, Escalier, Facade, Metadata,
        Site, ToitureConfig,
    )

    bm = BuildingModel(
        metadata=Metadata(
            id=uuid4(), project_id=uuid4(),
            address="80 Rue Test, 94130 Nogent-sur-Marne",
            zone_plu="UA",
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
            version=1, locked=False,
        ),
        site=Site(
            parcelle_geojson={"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]]},
            parcelle_surface_m2=100.0,
            voirie_orientations=["sud"],
            north_angle_deg=0.0,
        ),
        envelope=Envelope(
            footprint_geojson={"type": "Polygon", "coordinates": [[[1, 1], [9, 1], [9, 9], [1, 9], [1, 1]]]},
            emprise_m2=64.0,
            niveaux=2,
            hauteur_totale_m=6.5,
            hauteur_rdc_m=3.2,
            hauteur_etage_courant_m=2.7,
            toiture=ToitureConfig(type="terrasse"),
        ),
        core=Core(
            position_xy=(5.0, 5.0), surface_m2=20.0,
            escalier=Escalier(type="droit", giron_cm=28, hauteur_marche_cm=17, nb_marches_par_niveau=18),
        ),
        niveaux=[],
        facades={
            "nord": Facade(style="enduit_clair", composition=[], rgb_main="#EEEEEE"),
            "sud":  Facade(style="enduit_clair", composition=[], rgb_main="#EEEEEE"),
            "est":  Facade(style="enduit_clair", composition=[], rgb_main="#EEEEEE"),
            "ouest":Facade(style="enduit_clair", composition=[], rgb_main="#EEEEEE"),
        },
    )
    assert bm.urbanism_overlays is None


def test_building_model_accepts_overlay_bundle():
    """Bundle can be attached to BuildingModel without an import cycle."""
    from datetime import UTC, datetime
    from uuid import uuid4

    from core.building_model.schemas import (
        BuildingModel, Core, Envelope, Escalier, Facade, Metadata,
        Site, ToitureConfig,
    )

    bundle = UrbanismOverlayBundle(plu_zonage=PLUZonage(applies=True, zone_code="UA1"))
    bm = BuildingModel(
        metadata=Metadata(
            id=uuid4(), project_id=uuid4(), address="X", zone_plu="UA",
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        ),
        site=Site(
            parcelle_geojson={"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 0]]]},
            parcelle_surface_m2=100.0, voirie_orientations=["sud"],
        ),
        envelope=Envelope(
            footprint_geojson={"type": "Polygon", "coordinates": [[[1, 1], [9, 9]]]},
            emprise_m2=64.0, niveaux=2, hauteur_totale_m=6.5,
            hauteur_rdc_m=3.2, hauteur_etage_courant_m=2.7,
            toiture=ToitureConfig(type="terrasse"),
        ),
        core=Core(
            position_xy=(5.0, 5.0), surface_m2=20.0,
            escalier=Escalier(type="droit", giron_cm=28, hauteur_marche_cm=17, nb_marches_par_niveau=18),
        ),
        niveaux=[],
        facades={k: Facade(style="x", composition=[], rgb_main="#000")
                 for k in ("nord", "sud", "est", "ouest")},
        urbanism_overlays=bundle,
    )
    assert bm.urbanism_overlays is bundle
