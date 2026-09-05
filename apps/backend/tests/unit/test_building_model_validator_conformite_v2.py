"""Tests for the TOP 20 + business conformite V2 gate.

Each constraint gets at least one ``compliant`` case (status='pass' or
'skipped') and one ``non-compliant`` case (status='fail' with the right
severity). The grand-finale compliant test makes sure the full pipeline
returns zero blocking errors when every overlay is satisfied.

Lives under ``tests/unit/`` (memory feedback_dont_truncate_prod_db).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from core.building_model.schemas import (
    Ascenseur,
    BuildingModel,
    Cellule,
    CelluleType,
    Core,
    Envelope,
    Escalier,
    Facade,
    Metadata,
    Niveau,
    Room,
    RoomType,
    Site,
    ToitureConfig,
    ToitureType,
    Typologie,
)
from core.building_model.validator import (
    BusinessRules,
    ConformiteCheckItem,
    ConformiteCheckV2,
    OverlayContext,
    validate_conformite_v2,
)
from core.plu.schemas import NumericRules


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _building(
    *,
    emprise_m2: float = 80.0,
    niveaux_count: int = 3,
    hauteur_totale_m: float = 9.0,
    # 20×20 parcelle, 10×10 footprint centered (offset (5,5) → (15,15))
    parcelle: list[list[float]] | None = None,
    footprint: list[list[float]] | None = None,
    voirie: str = "sud",
    typologies: list[Typologie] | None = None,
    with_chambres: bool = False,
    with_commerce_rdc: bool = False,
    with_ascenseur: bool = False,
) -> BuildingModel:
    if parcelle is None:
        parcelle = [[0, 0], [20, 0], [20, 20], [0, 20], [0, 0]]
    if footprint is None:
        # 10×10 centered in 20×20 parcelle
        footprint = [[5, 5], [15, 5], [15, 15], [5, 15], [5, 5]]

    # Build niveaux populated with cellules for typologie / commerce / chambre
    # tests. Each entry in ``typologies`` becomes a LOGEMENT cellule at R+0.
    niveaux: list[Niveau] = []
    if typologies:
        cellules: list[Cellule] = []
        for i, t in enumerate(typologies):
            rooms: list[Room] = []
            if with_chambres:
                # Place a chambre near each lateral / fond limit to exercise
                # R.111-18. In the default 20×20 parcelle / 10×10 footprint,
                # the chambre polygon is positioned at the WEST edge of the
                # footprint (x=5..6) which is 5 m from the parcelle's WEST
                # limit (x=0). 5 < 6 m → R.111-18 fail.
                rooms.append(Room(
                    id=f"room-chambre-{i}", type=RoomType.CHAMBRE_PARENTS,
                    surface_m2=12.0, label_fr="Chambre parents",
                    polygon_xy=[(5.0, 5.0), (6.0, 5.0), (6.0, 7.0), (5.0, 7.0)],
                ))
            cellules.append(Cellule(
                id=f"log-{i}", type=CelluleType.LOGEMENT, typologie=t,
                surface_m2=60.0, surface_sdp_m2=60.0,
                polygon_xy=[(5.0, 5.0), (15.0, 5.0), (15.0, 15.0), (5.0, 15.0)],
                rooms=rooms,
            ))
        if with_commerce_rdc:
            cellules.append(Cellule(
                id="cmrc-0", type=CelluleType.COMMERCE,
                surface_m2=120.0, surface_sdp_m2=120.0,
                polygon_xy=[(5.0, 5.0), (15.0, 5.0), (15.0, 7.0), (5.0, 7.0)],
            ))
        niveaux.append(Niveau(
            index=0, code="R+0", usage_principal="mixte",
            hauteur_sous_plafond_m=2.7, surface_plancher_m2=120.0,
            cellules=cellules,
        ))

    return BuildingModel(
        metadata=Metadata(
            id=uuid4(), project_id=uuid4(), address="1 rue test",
            zone_plu="UA", created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC), version=1, locked=False,
        ),
        site=Site(
            parcelle_geojson={"type": "Polygon", "coordinates": [parcelle]},
            parcelle_surface_m2=400.0,
            voirie_orientations=[voirie], north_angle_deg=0.0,
        ),
        envelope=Envelope(
            footprint_geojson={"type": "Polygon", "coordinates": [footprint]},
            emprise_m2=emprise_m2, niveaux=niveaux_count,
            hauteur_totale_m=hauteur_totale_m,
            hauteur_rdc_m=3.0, hauteur_etage_courant_m=2.7,
            toiture=ToitureConfig(
                type=ToitureType.TERRASSE, accessible=False, vegetalisee=False,
            ),
        ),
        core=Core(
            position_xy=(10.0, 10.0), surface_m2=12.0,
            escalier=Escalier(
                type="droit", giron_cm=28, hauteur_marche_cm=17,
                nb_marches_par_niveau=18,
            ),
            ascenseur=(
                Ascenseur(type="standard", cabine_l_cm=110, cabine_p_cm=140, norme_pmr=True)
                if with_ascenseur else None
            ),
            gaines_techniques=[],
        ),
        niveaux=niveaux,
        facades={k: Facade(style="e", composition=[], rgb_main="#fff")
                 for k in ("nord", "sud", "est", "ouest")},
    )


def _rules(**over) -> NumericRules:
    base = {
        "emprise_max_pct": 40.0,
        "hauteur_max_m": 20.0,
        "pleine_terre_min_pct": 30.0,
        "recul_voirie_m": None,
        "recul_limite_lat_m": None,
        "recul_fond_m": None,
        "hauteur_max_niveaux": 6,
        "stationnement_par_logement": 1.0,
    }
    base.update(over)
    return NumericRules(**base)


def _find(checks: list[ConformiteCheckItem], code: str) -> ConformiteCheckItem:
    matches = [c for c in checks if c.code == code]
    assert matches, f"check {code} not found in {[c.code for c in checks]}"
    return matches[0]


# ---------------------------------------------------------------------------
# 1-3. PLU emprise / hauteur / retraits
# ---------------------------------------------------------------------------


def test_plu_emprise_compliant():
    bm = _building(emprise_m2=80.0)  # 80 / 400 = 20% ≤ 40%
    out = validate_conformite_v2(bm, _rules(emprise_max_pct=40.0))
    assert _find(out.checks, "PLU_EMPRISE").passed


def test_plu_emprise_fail():
    bm = _building(emprise_m2=200.0)  # 50% > 40%
    out = validate_conformite_v2(bm, _rules(emprise_max_pct=40.0))
    item = _find(out.checks, "PLU_EMPRISE")
    assert item.status == "fail"
    assert item.severity == "blocking"


def test_plu_hauteur_compliant():
    bm = _building(hauteur_totale_m=9.0, niveaux_count=3)
    out = validate_conformite_v2(bm, _rules(hauteur_max_m=20.0))
    assert _find(out.checks, "PLU_HAUTEUR").passed


def test_plu_hauteur_fail():
    bm = _building(hauteur_totale_m=25.0, niveaux_count=8)
    out = validate_conformite_v2(bm, _rules(hauteur_max_m=20.0))
    assert _find(out.checks, "PLU_HAUTEUR").status == "fail"


def test_plu_niveaux_fail():
    bm = _building(hauteur_totale_m=18.0, niveaux_count=9)  # R+8 > R+6
    out = validate_conformite_v2(bm, _rules(hauteur_max_m=20.0, hauteur_max_niveaux=6))
    assert _find(out.checks, "PLU_HAUTEUR").status == "fail"


def test_plu_retraits_compliant():
    # 5 m setbacks from each side of the 20×20 parcelle.
    bm = _building()
    out = validate_conformite_v2(
        bm, _rules(recul_voirie_m=4.0, recul_limite_lat_m=4.0, recul_fond_m=4.0),
    )
    assert _find(out.checks, "PLU_RETRAITS").passed


def test_plu_retrait_voirie_fail():
    # Footprint touches voirie (sud) at y=0 → recul = 0 m < 4 m.
    bm = _building(footprint=[[5, 0], [15, 0], [15, 10], [5, 10], [5, 0]])
    out = validate_conformite_v2(bm, _rules(recul_voirie_m=4.0))
    item = _find(out.checks, "PLU_RETRAITS")
    assert item.status == "fail"
    assert "voirie" in (item.message or "").lower()


# ---------------------------------------------------------------------------
# 4. OAP sectorielle
# ---------------------------------------------------------------------------


def test_oap_skipped_when_unknown():
    bm = _building()
    out = validate_conformite_v2(bm, _rules())
    assert _find(out.checks, "OAP_SECTORIELLE").status == "skipped"


def test_oap_lls_fail():
    bm = _building()
    overlays = OverlayContext(
        in_oap_sectorielle=True, oap_secteur_name="ZAC Test",
        oap_pct_lls_min=30.0,
    )
    business = BusinessRules(lls_quota_actual_pct=20.0)
    out = validate_conformite_v2(bm, _rules(), overlays=overlays, business_rules=business)
    assert _find(out.checks, "OAP_SECTORIELLE").status == "fail"


def test_oap_density_fail():
    # 1 logement / 400 m² = 25 log/ha < 60 log/ha imposé
    bm = _building(typologies=[Typologie.T3])
    overlays = OverlayContext(
        in_oap_sectorielle=True, oap_densite_min_log_ha=60.0,
    )
    out = validate_conformite_v2(bm, _rules(), overlays=overlays)
    assert _find(out.checks, "OAP_SECTORIELLE").status == "fail"


def test_oap_voirie_fail():
    bm = _building()
    overlays = OverlayContext(
        in_oap_sectorielle=True, oap_secteur_name="X",
        oap_obligation_voirie=True, oap_voirie_compliant=False,
    )
    out = validate_conformite_v2(bm, _rules(), overlays=overlays)
    assert _find(out.checks, "OAP_SECTORIELLE").status == "fail"


# ---------------------------------------------------------------------------
# 5. AC1 ABF
# ---------------------------------------------------------------------------


def test_abf_outside_perimeter():
    out = validate_conformite_v2(_building(), _rules(), overlays=OverlayContext(in_perimetre_ac1=False))
    assert _find(out.checks, "ABF_AC1").passed


def test_abf_required_but_missing():
    out = validate_conformite_v2(
        _building(), _rules(),
        overlays=OverlayContext(in_perimetre_ac1=True, abf_avis_obtenu=False),
    )
    item = _find(out.checks, "ABF_AC1")
    assert item.status == "fail" and item.severity == "blocking"


def test_abf_obtained():
    out = validate_conformite_v2(
        _building(), _rules(),
        overlays=OverlayContext(in_perimetre_ac1=True, abf_avis_obtenu=True),
    )
    assert _find(out.checks, "ABF_AC1").passed


# ---------------------------------------------------------------------------
# 6. PPRI cote PHEC
# ---------------------------------------------------------------------------


def test_ppri_zone_blanche_pass():
    out = validate_conformite_v2(_building(), _rules(), overlays=OverlayContext(ppri_zone="blanc"))
    assert _find(out.checks, "PPRI_PHEC").passed


def test_ppri_zone_rouge_fail():
    out = validate_conformite_v2(_building(), _rules(), overlays=OverlayContext(ppri_zone="rouge"))
    assert _find(out.checks, "PPRI_PHEC").status == "fail"


def test_ppri_phec_too_low_fail():
    overlays = OverlayContext(
        ppri_zone="bleu", ppri_cote_phec_ngf=35.0,
        plancher_rdc_ngf=34.8,  # < 35 + 0.20 → fail
        ppri_delta_securite_m=0.20,
    )
    out = validate_conformite_v2(_building(), _rules(), overlays=overlays)
    assert _find(out.checks, "PPRI_PHEC").status == "fail"


def test_ppri_phec_compliant():
    overlays = OverlayContext(
        ppri_zone="bleu", ppri_cote_phec_ngf=35.0,
        plancher_rdc_ngf=35.30,  # 35 + 0.20 ≤ 35.30 → ok
        ppri_delta_securite_m=0.20,
    )
    out = validate_conformite_v2(_building(), _rules(), overlays=overlays)
    assert _find(out.checks, "PPRI_PHEC").passed


# ---------------------------------------------------------------------------
# 7. PPRT Seveso
# ---------------------------------------------------------------------------


def test_pprt_outside_pass():
    out = validate_conformite_v2(_building(), _rules(), overlays=OverlayContext(in_perimetre_pprt=False))
    assert _find(out.checks, "PPRT").passed


def test_pprt_inside_fail():
    out = validate_conformite_v2(_building(), _rules(), overlays=OverlayContext(in_perimetre_pprt=True))
    assert _find(out.checks, "PPRT").status == "fail"


# ---------------------------------------------------------------------------
# 8. SRU SMS L.151-15
# ---------------------------------------------------------------------------


def test_sru_sms_below_seuil_passes():
    # 400 m² parcelle × 3 niveaux × emprise 80 = 240 m² SDP < 800 m² seuil
    bm = _building(emprise_m2=80.0, niveaux_count=3)
    overlays = OverlayContext(sms_pct_lls_min=30.0, sms_seuil_sdp_m2=800.0)
    business = BusinessRules(lls_quota_actual_pct=0.0)
    out = validate_conformite_v2(bm, _rules(), overlays=overlays, business_rules=business)
    assert _find(out.checks, "SRU_SMS_LLS").passed


def test_sru_sms_lls_below_required_fail():
    # Force SDP above seuil (4 niveaux × 200 = 800 m²)
    bm = _building(emprise_m2=300.0, niveaux_count=3)
    overlays = OverlayContext(sms_pct_lls_min=30.0, sms_seuil_sdp_m2=800.0)
    business = BusinessRules(lls_quota_actual_pct=20.0)
    out = validate_conformite_v2(bm, _rules(emprise_max_pct=100.0), overlays=overlays, business_rules=business)
    item = _find(out.checks, "SRU_SMS_LLS")
    assert item.status == "fail"


def test_sru_sms_lls_ok():
    bm = _building(emprise_m2=300.0, niveaux_count=3)
    overlays = OverlayContext(sms_pct_lls_min=30.0, sms_seuil_sdp_m2=800.0)
    business = BusinessRules(lls_quota_actual_pct=30.0)
    out = validate_conformite_v2(bm, _rules(emprise_max_pct=100.0), overlays=overlays, business_rules=business)
    assert _find(out.checks, "SRU_SMS_LLS").passed


# ---------------------------------------------------------------------------
# 9. SUP I1/I3
# ---------------------------------------------------------------------------


def test_sup_canalisations_outside_pass():
    overlays = OverlayContext(in_bande_sup_i1=False, in_bande_sup_i3=False)
    out = validate_conformite_v2(_building(), _rules(), overlays=overlays)
    assert _find(out.checks, "SUP_I1_I3").passed


def test_sup_canalisations_i1_fail():
    overlays = OverlayContext(in_bande_sup_i1=True)
    out = validate_conformite_v2(_building(), _rules(), overlays=overlays)
    assert _find(out.checks, "SUP_I1_I3").status == "fail"


def test_sup_canalisations_i3_fail():
    overlays = OverlayContext(in_bande_sup_i3=True)
    out = validate_conformite_v2(_building(), _rules(), overlays=overlays)
    assert _find(out.checks, "SUP_I1_I3").status == "fail"


# ---------------------------------------------------------------------------
# 10. RGA
# ---------------------------------------------------------------------------


def test_rga_low_pass():
    out = validate_conformite_v2(_building(), _rules(), overlays=OverlayContext(rga_niveau="faible"))
    item = _find(out.checks, "RGA")
    assert item.passed and item.severity == "warning"


def test_rga_moyen_without_g2_fail():
    overlays = OverlayContext(rga_niveau="moyen", rga_etude_g2_realisee=False)
    out = validate_conformite_v2(_building(), _rules(), overlays=overlays)
    item = _find(out.checks, "RGA")
    assert item.status == "fail" and item.severity == "warning"


def test_rga_moyen_with_g2_pass():
    overlays = OverlayContext(rga_niveau="moyen", rga_etude_g2_realisee=True)
    out = validate_conformite_v2(_building(), _rules(), overlays=overlays)
    assert _find(out.checks, "RGA").passed


# ---------------------------------------------------------------------------
# 11. BASIAS / BASOL / SIS
# ---------------------------------------------------------------------------


def test_pollution_clean_pass():
    overlays = OverlayContext(in_basias=False, in_basol=False, in_sis=False)
    out = validate_conformite_v2(_building(), _rules(), overlays=overlays)
    assert _find(out.checks, "POLLUTION_SOLS").passed


def test_basol_without_attestation_fail():
    # BASOL = blocking (taxonomy: "Refus PC + responsabilité environnementale")
    overlays = OverlayContext(in_basol=True, pollution_etude_l556_1_realisee=False)
    out = validate_conformite_v2(_building(), _rules(), overlays=overlays)
    item = _find(out.checks, "POLLUTION_SOLS")
    assert item.status == "fail" and item.severity == "blocking"


def test_basol_with_attestation_pass():
    overlays = OverlayContext(in_basol=True, pollution_etude_l556_1_realisee=True)
    out = validate_conformite_v2(_building(), _rules(), overlays=overlays)
    assert _find(out.checks, "POLLUTION_SOLS").passed


def test_basias_without_etude_warning():
    overlays = OverlayContext(in_basias=True, in_basol=False, in_sis=False,
                              pollution_etude_l556_1_realisee=False)
    out = validate_conformite_v2(_building(), _rules(), overlays=overlays)
    item = _find(out.checks, "POLLUTION_SOLS")
    assert item.status == "fail" and item.severity == "warning"


# ---------------------------------------------------------------------------
# 12. EBC L.113-1
# ---------------------------------------------------------------------------


def test_ebc_outside_pass():
    out = validate_conformite_v2(_building(), _rules(), overlays=OverlayContext(in_ebc=False))
    assert _find(out.checks, "EBC").passed


def test_ebc_inside_fail():
    out = validate_conformite_v2(_building(), _rules(), overlays=OverlayContext(in_ebc=True))
    item = _find(out.checks, "EBC")
    assert item.status == "fail" and item.severity == "blocking"


# ---------------------------------------------------------------------------
# 13. L.151-19
# ---------------------------------------------------------------------------


def test_l151_19_outside_pass():
    out = validate_conformite_v2(_building(), _rules(), overlays=OverlayContext(in_l151_19=False))
    assert _find(out.checks, "L151_19").passed


def test_l151_19_inside_without_auth_warning():
    overlays = OverlayContext(in_l151_19=True, l151_19_modification_autorisee=False)
    out = validate_conformite_v2(_building(), _rules(), overlays=overlays)
    assert _find(out.checks, "L151_19").status == "fail"


def test_l151_19_with_auth_pass():
    overlays = OverlayContext(in_l151_19=True, l151_19_modification_autorisee=True)
    out = validate_conformite_v2(_building(), _rules(), overlays=overlays)
    assert _find(out.checks, "L151_19").passed


# ---------------------------------------------------------------------------
# 14. Natura 2000
# ---------------------------------------------------------------------------


def test_natura2000_outside_pass():
    out = validate_conformite_v2(_building(), _rules(), overlays=OverlayContext(in_natura2000=False))
    assert _find(out.checks, "NATURA2000").passed


def test_natura2000_inside_without_evaluation_fail():
    overlays = OverlayContext(in_natura2000=True, natura2000_evaluation_realisee=False)
    out = validate_conformite_v2(_building(), _rules(), overlays=overlays)
    assert _find(out.checks, "NATURA2000").status == "fail"


def test_natura2000_inside_with_evaluation_pass():
    overlays = OverlayContext(in_natura2000=True, natura2000_evaluation_realisee=True)
    out = validate_conformite_v2(_building(), _rules(), overlays=overlays)
    assert _find(out.checks, "NATURA2000").passed


# ---------------------------------------------------------------------------
# 15. CDPENAF
# ---------------------------------------------------------------------------


def test_cdpenaf_outside_zone_a_n_pass():
    out = validate_conformite_v2(_building(), _rules(), overlays=OverlayContext(in_zone_a_n=False))
    assert _find(out.checks, "CDPENAF").passed


def test_cdpenaf_a_n_without_avis_fail():
    out = validate_conformite_v2(
        _building(), _rules(),
        overlays=OverlayContext(in_zone_a_n=True, cdpenaf_avis_favorable=False),
    )
    assert _find(out.checks, "CDPENAF").status == "fail"


def test_cdpenaf_a_n_with_avis_pass():
    out = validate_conformite_v2(
        _building(), _rules(),
        overlays=OverlayContext(in_zone_a_n=True, cdpenaf_avis_favorable=True),
    )
    assert _find(out.checks, "CDPENAF").passed


# ---------------------------------------------------------------------------
# 16. CDAC commerce
# ---------------------------------------------------------------------------


def test_cdac_below_seuil_pass():
    out = validate_conformite_v2(
        _building(), _rules(),
        overlays=OverlayContext(commerce_surface_vente_m2=500.0),
    )
    assert _find(out.checks, "CDAC").passed


def test_cdac_above_seuil_warn():
    out = validate_conformite_v2(
        _building(), _rules(),
        overlays=OverlayContext(commerce_surface_vente_m2=1500.0),
    )
    item = _find(out.checks, "CDAC")
    assert item.status == "fail" and item.severity == "warning"


# ---------------------------------------------------------------------------
# 17. RE2020
# ---------------------------------------------------------------------------


def test_re2020_attestation_present_pass():
    out = validate_conformite_v2(
        _building(), _rules(),
        overlays=OverlayContext(re2020_attestation_presente=True),
    )
    assert _find(out.checks, "RE2020").passed


def test_re2020_attestation_missing_fail():
    out = validate_conformite_v2(
        _building(), _rules(),
        overlays=OverlayContext(re2020_attestation_presente=False),
    )
    item = _find(out.checks, "RE2020")
    assert item.status == "fail" and item.severity == "warning"


# ---------------------------------------------------------------------------
# 18. Stationnement
# ---------------------------------------------------------------------------


def test_stationnement_ok():
    overlays = OverlayContext(
        stationnement_places_requises=10.0, stationnement_places_projet=10.0,
    )
    out = validate_conformite_v2(_building(), _rules(), overlays=overlays)
    assert _find(out.checks, "STATIONNEMENT").passed


def test_stationnement_short_fail():
    overlays = OverlayContext(
        stationnement_places_requises=10.0, stationnement_places_projet=6.0,
    )
    out = validate_conformite_v2(_building(), _rules(), overlays=overlays)
    item = _find(out.checks, "STATIONNEMENT")
    assert item.status == "fail" and item.severity == "blocking"


# ---------------------------------------------------------------------------
# 19. R.111-18 chambres
# ---------------------------------------------------------------------------


def test_r111_18_no_logement_pass():
    # No chambre present at all → no violation.
    out = validate_conformite_v2(_building(), _rules())
    assert _find(out.checks, "R111_18").passed


def test_r111_18_chambre_too_close_fail():
    bm = _building(typologies=[Typologie.T3], with_chambres=True)
    out = validate_conformite_v2(bm, _rules())
    item = _find(out.checks, "R111_18")
    assert item.status == "fail" and item.severity == "blocking"


# ---------------------------------------------------------------------------
# 20. L.151-16 linéaire commercial
# ---------------------------------------------------------------------------


def test_lineaire_outside_pass():
    overlays = OverlayContext(in_lineaire_l151_16=False)
    out = validate_conformite_v2(_building(), _rules(), overlays=overlays)
    assert _find(out.checks, "LINEAIRE_L151_16").passed


def test_lineaire_without_commerce_fail():
    bm = _building(typologies=[Typologie.T3], with_commerce_rdc=False)
    overlays = OverlayContext(in_lineaire_l151_16=True)
    out = validate_conformite_v2(bm, _rules(), overlays=overlays)
    item = _find(out.checks, "LINEAIRE_L151_16")
    assert item.status == "fail" and item.severity == "blocking"


def test_lineaire_with_commerce_pass():
    bm = _building(typologies=[Typologie.T3], with_commerce_rdc=True)
    overlays = OverlayContext(in_lineaire_l151_16=True)
    out = validate_conformite_v2(bm, _rules(), overlays=overlays)
    assert _find(out.checks, "LINEAIRE_L151_16").passed


# ---------------------------------------------------------------------------
# 21-23. Business — marge / LLS / T3+
# ---------------------------------------------------------------------------


def test_business_marge_ok():
    business = BusinessRules(marge_bilan_actual_pct=15.0)
    out = validate_conformite_v2(_building(), _rules(), business_rules=business)
    assert _find(out.checks, "BUSINESS_MARGE").passed


def test_business_marge_fail():
    business = BusinessRules(marge_bilan_actual_pct=10.0)
    out = validate_conformite_v2(_building(), _rules(), business_rules=business)
    item = _find(out.checks, "BUSINESS_MARGE")
    assert item.status == "fail" and item.severity == "blocking"


def test_business_lls_ok():
    business = BusinessRules(lls_quota_min_pct=30.0, lls_quota_actual_pct=30.0)
    out = validate_conformite_v2(_building(), _rules(), business_rules=business)
    assert _find(out.checks, "BUSINESS_LLS").passed


def test_business_lls_fail():
    business = BusinessRules(lls_quota_min_pct=30.0, lls_quota_actual_pct=20.0)
    out = validate_conformite_v2(_building(), _rules(), business_rules=business)
    assert _find(out.checks, "BUSINESS_LLS").status == "fail"


def test_business_t3plus_ok():
    # 2 logts T3 over 2 = 100% T3+ ≥ 40%
    bm = _building(typologies=[Typologie.T3, Typologie.T3])
    business = BusinessRules(typologie_t3_plus_min_pct=40.0)
    out = validate_conformite_v2(bm, _rules(), business_rules=business)
    assert _find(out.checks, "BUSINESS_T3_PLUS").passed


def test_business_t3plus_fail():
    # 0 / 3 T3+ → 0% < 40%
    bm = _building(typologies=[Typologie.T1, Typologie.T2, Typologie.T2])
    business = BusinessRules(typologie_t3_plus_min_pct=40.0)
    out = validate_conformite_v2(bm, _rules(), business_rules=business)
    item = _find(out.checks, "BUSINESS_T3_PLUS")
    assert item.status == "fail"


# ---------------------------------------------------------------------------
# Grand-finale: fully-compliant project — zero blocking errors
# ---------------------------------------------------------------------------


def test_fully_compliant_returns_no_blocking_errors():
    bm = _building(
        emprise_m2=80.0, niveaux_count=3, hauteur_totale_m=9.0,
        typologies=[Typologie.T3, Typologie.T3, Typologie.T3],
        with_ascenseur=True,  # required from R+2 (PMR)
    )
    overlays = OverlayContext(
        in_oap_sectorielle=False,
        in_perimetre_ac1=False,
        ppri_zone="blanc",
        in_perimetre_pprt=False,
        in_bande_sup_i1=False, in_bande_sup_i3=False,
        rga_niveau="faible",
        in_basias=False, in_basol=False, in_sis=False,
        in_ebc=False,
        in_l151_19=False,
        in_natura2000=False,
        in_zone_a_n=False,
        commerce_surface_vente_m2=0.0,
        re2020_attestation_presente=True,
        stationnement_places_requises=3.0, stationnement_places_projet=3.0,
        in_lineaire_l151_16=False,
    )
    business = BusinessRules(
        marge_bilan_actual_pct=15.0,
        lls_quota_min_pct=30.0, lls_quota_actual_pct=30.0,
        typologie_t3_plus_min_pct=40.0,
    )
    out = validate_conformite_v2(bm, _rules(emprise_max_pct=40.0, hauteur_max_m=20.0),
                                  overlays=overlays, business_rules=business)
    assert isinstance(out, ConformiteCheckV2)
    blockers = out.blocking_errors()
    assert blockers == [], f"unexpected blockers: {[(b.code, b.message) for b in blockers]}"
    assert not out.has_blocking_errors()


def test_top20_categories_all_present():
    """Sanity check: the V2 check returns exactly the 24 expected codes."""
    out = validate_conformite_v2(_building(), _rules())
    codes = {c.code for c in out.checks}
    expected = {
        "PLU_EMPRISE", "PLU_HAUTEUR", "PLU_RETRAITS", "OAP_SECTORIELLE",
        "ABF_AC1", "PPRI_PHEC", "PPRT", "SRU_SMS_LLS", "SUP_I1_I3", "RGA",
        "POLLUTION_SOLS", "EBC", "L151_19", "NATURA2000", "CDPENAF", "CDAC",
        "RE2020", "STATIONNEMENT", "R111_18", "LINEAIRE_L151_16",
        "BUSINESS_MARGE", "BUSINESS_LLS", "BUSINESS_T3_PLUS",
        "HAUTEUR_GRAPHIQUE",
    }
    assert codes == expected, f"missing={expected - codes} extra={codes - expected}"


def test_to_summary_shape():
    out = validate_conformite_v2(_building(), _rules())
    s = out.to_summary()
    assert s["n_total"] == len(out.checks)
    assert "blocking" in s and "warnings" in s


def test_legacy_check_attached():
    out = validate_conformite_v2(_building(), _rules())
    assert out.legacy_check is not None
