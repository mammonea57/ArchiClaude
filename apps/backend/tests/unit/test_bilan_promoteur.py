"""Reproduce the real Bilan Opt1 for the Nogent-sur-Marne operation.

All tolerances are expressed as relative error vs the Excel value. We
target < 0.5 % on every line and < 0.1 % on the final margin.

Source: ``/tmp/bilan.xlsx`` sheet "Bilan Opt1", operation 78-80 Rue des
Héros Nogentais, Nogent-sur-Marne 94130.
"""
from __future__ import annotations

import pytest

from core.feasibility.bilan_promoteur import (
    BilanInputs,
    BilanProgramme,
    compute_bilan,
)


def _relerr(got: float, expected: float) -> float:
    return abs(got - expected) / abs(expected)


@pytest.fixture
def nogent_programme() -> BilanProgramme:
    return BilanProgramme(
        terrain_m2=1266.0,
        ces=0.8,
        sdp_m2=5165.28,
        rendement_plan_shab_sur_sdp=0.912,
        shab_libre_m2=3362.597,
        shab_social_m2=1441.113,
        shab_commerce_m2=0.0,
        nb_parkings_ss_sol=62,
        nb_parkings_exterieurs=0,
        duree_chantier_mois=18,
    )


@pytest.fixture
def nogent_inputs() -> BilanInputs:
    return BilanInputs(
        prix_vente_ht_libre_eur_m2_shab=6750.0,
        prix_vente_ht_social_eur_m2_shab=3945.4545,
        tva_vente_libre_pct=0.20,
        tva_vente_social_pct=0.10,
        prix_terrain_total_ht=6_500_000.0,
        frais_acquisition_pct=0.03,
        frais_geometre_forfait=4000.0,
        frais_sondages_forfait=20000.0,
        taxe_amenagement_assiette_m2=6425.4108,
        taxe_amenagement_valeur_m2=860.0,
        taxe_amenagement_taux_commune=0.20,
        taxe_amenagement_taux_departement=0.025,
        taxe_amenagement_taux_region=0.01,
        taxe_amenagement_taux_inrap=0.004,
        taxe_assainissement_eur_m2_sdp=20.0,
        constats_huissier_forfait=15000.0,
        demolition_forfait=60000.0,
        honos_avocat_pct_terrain=0.02,
        divers_concession_pct_terrain=0.015,
        cout_travaux_libre_eur_m2_shab=2500.0,
        cout_travaux_social_eur_m2_shab=1380.0,
        cout_parking_ss_sol_eur=18000.0,
        honos_architecte_pct_travx=0.04,
        honos_moe_exe_pct_travx=0.03,
        honos_autres_bet_pct_travx=0.01,
        honos_sps_bc_pct_travx=0.01,
        assurances_pct_travx_honos_ttc=0.013,
        honos_comm_vente_pct_ventes_ttc=0.028,
        mise_en_copro_forfait=5000.0,
        frais_comm_plaquette_pct_ventes_ttc=0.005,
        honos_sav_pct_travx_ttc=0.01,
        frais_dossier_banque_forfait=5000.0,
        gfa_pct_ventes_ttc=0.015,
        cautions_pct_fonds_propres_an=0.02,
        fonds_propres_ht=7_977_269.889,
        frais_financiers_total=349_862.6942,
        imprevus_pct_travx_honos=0.05,
    )


def test_recettes_nogent(nogent_programme, nogent_inputs):
    b = compute_bilan(nogent_programme, nogent_inputs, option_label="opt1")
    assert _relerr(b.recettes.libre_ht, 22_697_529.75) < 1e-4
    assert _relerr(b.recettes.social_ht, 5_685_845.84) < 1e-4
    assert _relerr(b.recettes.total_ht, 28_383_375.59) < 1e-4
    assert _relerr(b.recettes.total_ttc, 33_491_466.12) < 1e-4


def test_foncier_total_nogent(nogent_programme, nogent_inputs):
    b = compute_bilan(nogent_programme, nogent_inputs, option_label="opt1")
    assert _relerr(b.foncier.total_ht, 8_445_484.534) < 5e-3


def test_travaux_total_nogent(nogent_programme, nogent_inputs):
    b = compute_bilan(nogent_programme, nogent_inputs, option_label="opt1")
    assert _relerr(b.travaux.total_ht, 11_511_228.44) < 1e-4


def test_honoraires_total_nogent(nogent_programme, nogent_inputs):
    b = compute_bilan(nogent_programme, nogent_inputs, option_label="opt1")
    assert _relerr(b.honoraires.total_ht, 1_036_010.56) < 1e-4


def test_assurances_total_nogent(nogent_programme, nogent_inputs):
    b = compute_bilan(nogent_programme, nogent_inputs, option_label="opt1")
    assert _relerr(b.assurances.total_ht, 192_835.3284) < 5e-3


def test_commercialisation_total_nogent(nogent_programme, nogent_inputs):
    b = compute_bilan(nogent_programme, nogent_inputs, option_label="opt1")
    assert _relerr(b.commercialisation.total_ht, 1_110_218.382) < 1e-4


def test_gestion_fi_total_nogent(nogent_programme, nogent_inputs):
    b = compute_bilan(nogent_programme, nogent_inputs, option_label="opt1")
    assert _relerr(b.gestion_financiere.total_ht, 1_152_682.825) < 5e-3


def test_imprevus_total_nogent(nogent_programme, nogent_inputs):
    b = compute_bilan(nogent_programme, nogent_inputs, option_label="opt1")
    assert _relerr(b.imprevus.total_ht, 627_361.95) < 1e-4


def test_depenses_total_nogent(nogent_programme, nogent_inputs):
    b = compute_bilan(nogent_programme, nogent_inputs, option_label="opt1")
    assert _relerr(b.depenses_total_ht, 24_075_822.02) < 5e-3


def test_marge_nogent(nogent_programme, nogent_inputs):
    b = compute_bilan(nogent_programme, nogent_inputs, option_label="opt1")
    assert _relerr(b.marge_ht, 4_307_553.567) < 5e-3
    assert _relerr(b.marge_pct_ht, 0.1518) < 5e-3


def test_chapter_percentages_sum_to_one(nogent_programme, nogent_inputs):
    b = compute_bilan(nogent_programme, nogent_inputs, option_label="opt1")
    chapters = [
        b.foncier,
        b.travaux,
        b.honoraires,
        b.assurances,
        b.commercialisation,
        b.gestion_financiere,
        b.imprevus,
    ]
    assert sum(c.pct_depenses_ht for c in chapters) == pytest.approx(1.0, abs=1e-9)


def test_charge_fonciere_coherent(nogent_programme, nogent_inputs):
    b = compute_bilan(nogent_programme, nogent_inputs, option_label="opt1")
    non_foncier = b.depenses_total_ht - b.foncier.total_ht
    assert b.charge_fonciere_max_ht == pytest.approx(
        b.recettes.total_ht - non_foncier
    )
    assert b.charge_fonciere_max_ht > b.foncier.total_ht


def test_warnings_on_non_bankable_margin(nogent_programme, nogent_inputs):
    """Marge < 12 % → opération non finançable, warning explicite avec gap €."""
    inp = nogent_inputs.model_copy(update={"prix_vente_ht_libre_eur_m2_shab": 3000.0})
    b = compute_bilan(nogent_programme, inp)
    assert b.marge_pct_ht < 0.12
    assert any("NON FINAN" in w.upper() for w in b.warnings)


def test_bankable_margin_no_warning(nogent_programme, nogent_inputs):
    """Nogent Opt1 est à 15,18 % > 12 % donc PAS de warning non-finançable."""
    b = compute_bilan(nogent_programme, nogent_inputs, option_label="opt1")
    assert b.marge_pct_ht >= 0.12
    assert not any("NON FINAN" in w.upper() for w in b.warnings)


def test_lls_quota_warning_below_minimum(nogent_programme, nogent_inputs):
    """Nogent → 30 % LLS exigé ; avec seulement 1441/4803 = 30 % exactement
    on est à la limite ; si on descend à 20 % un warning doit apparaître."""
    p = nogent_programme.model_copy(update={
        "lls_quota_minimum": 0.30,
        "shab_libre_m2": 4000.0,
        "shab_social_m2": 800.0,  # 800 / 4800 = 16.7 %
    })
    b = compute_bilan(p, nogent_inputs)
    assert any("quota PLU" in w and "LLS" in w for w in b.warnings)


def test_lls_quota_ok_no_warning(nogent_programme, nogent_inputs):
    """Nogent Opt1 réel : 1441 social / 4803 total = 30,0 % → respecte 30 %."""
    p = nogent_programme.model_copy(update={"lls_quota_minimum": 0.30})
    b = compute_bilan(p, nogent_inputs)
    assert p.pct_social_reel >= 0.30 - 1e-4
    assert not any("quota PLU" in w for w in b.warnings)


def test_lls_quota_zero_disables_check(nogent_programme, nogent_inputs):
    """Sans quota PLU imposé, aucun warning LLS même si social = 0 %."""
    p = nogent_programme.model_copy(update={
        "lls_quota_minimum": 0.0,
        "shab_libre_m2": 4803.71,
        "shab_social_m2": 0.0,
    })
    b = compute_bilan(p, nogent_inputs)
    assert not any("quota PLU" in w for w in b.warnings)
