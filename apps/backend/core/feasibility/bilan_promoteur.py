"""Bilan promoteur — French developer feasibility P&L.

Reproduces the standard French promoteur bilan structure used by our user
and industry tools (TestFit / Archistar / Forma analogues):

Recettes HT − Dépenses HT (7 chapitres) = Marge HT

Seven expense chapters:
    1. Foncier                 (terrain + frais + taxes)
    2. Travaux                 (construction logement libre/social + parkings)
    3. Honoraires techniques   (archi, MOE, BET, SPS)
    4. Assurances              (TRC, DO, CNR)
    5. Commercialisation       (honos comm, copro, plaquette)
    6. Gestion & frais fi      (SAV, GFA, cautions, frais bancaires)
    7. Imprévus                (aléas sur travaux + honos)

All default rates are calibrated on a real Nogent-sur-Marne operation
(Bilan Opt1) and validated by unit test `test_bilan_promoteur.py` which
reproduces its totals within < 0.1 % relative error.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------- Inputs ----------


class BilanProgramme(BaseModel):
    """Programme quantitatif : surfaces + parkings + durée."""

    terrain_m2: float = Field(gt=0)
    ces: float = Field(gt=0, le=1.0, description="Coefficient d'emprise au sol")
    sdp_m2: float = Field(gt=0, description="Surface de Plancher réglementaire")
    rendement_plan_shab_sur_sdp: float = Field(
        default=0.912, gt=0, le=1.0, description="SHAB / SDP"
    )
    shab_libre_m2: float = Field(ge=0)
    shab_social_m2: float = Field(ge=0, default=0.0)
    shab_commerce_m2: float = Field(ge=0, default=0.0)
    nb_parkings_ss_sol: int = Field(ge=0, default=0)
    nb_parkings_exterieurs: int = Field(ge=0, default=0)
    duree_chantier_mois: int = Field(ge=1, le=60, default=18)

    @property
    def shab_total_m2(self) -> float:
        return self.shab_libre_m2 + self.shab_social_m2 + self.shab_commerce_m2


class BilanInputs(BaseModel):
    """Taux, prix unitaires et forfaits — calibrés par défaut sur IDF 2025."""

    # --- Prix de vente ---
    prix_vente_ht_libre_eur_m2_shab: float = 6750.0
    prix_vente_ht_social_eur_m2_shab: float = 3945.4545
    prix_vente_ht_commerce_eur_m2_shab: float = 5000.0
    tva_vente_libre_pct: float = 0.20
    tva_vente_social_pct: float = 0.10
    tva_vente_commerce_pct: float = 0.20

    # --- Foncier ---
    prix_terrain_total_ht: float = Field(gt=0, description="Prix d'achat terrain HT")
    frais_acquisition_pct: float = 0.03
    frais_geometre_forfait: float = 4000.0
    frais_sondages_forfait: float = 20000.0
    taxe_amenagement_assiette_m2: float | None = Field(
        default=None,
        description="Assiette de la taxe d'aménagement (m² taxables). "
        "Si None, on prend sdp_m2 × 1.244.",
    )
    taxe_amenagement_valeur_m2: float = 860.0
    taxe_amenagement_taux_commune: float = 0.20
    taxe_amenagement_taux_departement: float = 0.025
    taxe_amenagement_taux_region: float = 0.01
    taxe_amenagement_taux_inrap: float = 0.004
    redevance_insuff_parking_forfait: float = 0.0
    taxe_assainissement_eur_m2_sdp: float = 20.0
    constats_huissier_forfait: float = 15000.0
    demolition_forfait: float = 60000.0
    honos_avocat_pct_terrain: float = 0.02
    taxe_dation_forfait: float = 0.0
    divers_concession_pct_terrain: float = 0.015

    # --- Travaux ---
    cout_travaux_libre_eur_m2_shab: float = 2500.0
    cout_travaux_social_eur_m2_shab: float = 1380.0
    cout_travaux_commerce_eur_m2_shab: float = 1100.0
    cout_parking_ss_sol_eur: float = 18000.0
    cout_parking_exterieur_eur: float = 2500.0
    tva_travaux_pct: float = 0.20

    # --- Honoraires techniques ---
    honos_architecte_pct_travx: float = 0.04
    honos_moe_exe_pct_travx: float = 0.03
    honos_autres_bet_pct_travx: float = 0.01
    honos_sps_bc_pct_travx: float = 0.01
    expert_comptable_forfait: float = 0.0
    honos_amo_pct_travx: float = 0.0

    # --- Assurances ---
    assurances_pct_travx_honos_ttc: float = 0.013

    # --- Commercialisation ---
    honos_comm_vente_pct_ventes_ttc: float = 0.028
    mise_en_copro_forfait: float = 5000.0
    honos_comm_locatif_pct: float = 0.0
    frais_comm_plaquette_pct_ventes_ttc: float = 0.005

    # --- Gestion et frais financiers ---
    honos_gestion_pct_ventes_ttc: float = 0.0
    honos_sav_pct_travx_ttc: float = 0.01
    frais_stock_forfait: float = 0.0
    frais_dossier_banque_forfait: float = 5000.0
    gfa_pct_ventes_ttc: float = 0.015
    cautions_pct_fonds_propres_an: float = 0.02
    fonds_propres_ht: float = Field(
        default=0.0,
        description="Montant de fonds propres engagés, utilisé pour cautions + FF",
    )
    frais_financiers_total: float = 0.0

    # --- Imprévus ---
    imprevus_pct_travx_honos: float = 0.05


# ---------- Outputs ----------


class BilanPoste(BaseModel):
    """Ligne de dépense élémentaire du bilan."""

    libelle: str
    base: float = 0.0
    taux_ou_unitaire: float | str = ""
    montant_ht: float = 0.0
    tva_pct: float = 0.20
    montant_tva: float = 0.0
    montant_ttc: float = 0.0


class BilanChapitre(BaseModel):
    """Groupe de postes d'un chapitre budgétaire."""

    nom: str
    postes: list[BilanPoste] = Field(default_factory=list)
    total_ht: float = 0.0
    total_tva: float = 0.0
    total_ttc: float = 0.0
    pct_depenses_ht: float = 0.0


class BilanRecettes(BaseModel):
    """Recettes de vente par destination."""

    libre_surface_m2: float = 0.0
    libre_prix_ht_m2: float = 0.0
    libre_ht: float = 0.0
    libre_ttc: float = 0.0
    social_surface_m2: float = 0.0
    social_prix_ht_m2: float = 0.0
    social_ht: float = 0.0
    social_ttc: float = 0.0
    commerce_surface_m2: float = 0.0
    commerce_prix_ht_m2: float = 0.0
    commerce_ht: float = 0.0
    commerce_ttc: float = 0.0
    total_ht: float = 0.0
    total_ttc: float = 0.0
    prix_m2_shab_moyen_ht: float = 0.0


class BilanResult(BaseModel):
    """Résultat complet d'un bilan promoteur."""

    programme: BilanProgramme
    recettes: BilanRecettes
    foncier: BilanChapitre
    travaux: BilanChapitre
    honoraires: BilanChapitre
    assurances: BilanChapitre
    commercialisation: BilanChapitre
    gestion_financiere: BilanChapitre
    imprevus: BilanChapitre
    depenses_total_ht: float
    depenses_total_ttc: float
    tva_sur_ventes: float
    tva_deductible: float
    tva_residuelle: float
    marge_ht: float
    marge_ttc: float
    marge_pct_ht: float
    marge_pct_ttc: float
    charge_fonciere_max_ht: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    option_label: Literal["opt1", "opt2", "opt3", "custom"] = "custom"


# ---------- Helpers ----------


def _poste(
    libelle: str,
    montant_ht: float,
    *,
    base: float = 0.0,
    taux: float | str = "",
    tva_pct: float = 0.20,
) -> BilanPoste:
    montant_tva = montant_ht * tva_pct
    return BilanPoste(
        libelle=libelle,
        base=base,
        taux_ou_unitaire=taux,
        montant_ht=montant_ht,
        tva_pct=tva_pct,
        montant_tva=montant_tva,
        montant_ttc=montant_ht + montant_tva,
    )


def _close_chapter(nom: str, postes: list[BilanPoste]) -> BilanChapitre:
    total_ht = sum(p.montant_ht for p in postes)
    total_tva = sum(p.montant_tva for p in postes)
    return BilanChapitre(
        nom=nom,
        postes=postes,
        total_ht=total_ht,
        total_tva=total_tva,
        total_ttc=total_ht + total_tva,
    )


# ---------- Recettes ----------


def _compute_recettes(p: BilanProgramme, inp: BilanInputs) -> BilanRecettes:
    libre_ht = p.shab_libre_m2 * inp.prix_vente_ht_libre_eur_m2_shab
    libre_ttc = libre_ht * (1 + inp.tva_vente_libre_pct)
    social_ht = p.shab_social_m2 * inp.prix_vente_ht_social_eur_m2_shab
    social_ttc = social_ht * (1 + inp.tva_vente_social_pct)
    commerce_ht = p.shab_commerce_m2 * inp.prix_vente_ht_commerce_eur_m2_shab
    commerce_ttc = commerce_ht * (1 + inp.tva_vente_commerce_pct)
    total_ht = libre_ht + social_ht + commerce_ht
    total_ttc = libre_ttc + social_ttc + commerce_ttc
    shab_total = p.shab_total_m2 or 1.0
    return BilanRecettes(
        libre_surface_m2=p.shab_libre_m2,
        libre_prix_ht_m2=inp.prix_vente_ht_libre_eur_m2_shab,
        libre_ht=libre_ht,
        libre_ttc=libre_ttc,
        social_surface_m2=p.shab_social_m2,
        social_prix_ht_m2=inp.prix_vente_ht_social_eur_m2_shab,
        social_ht=social_ht,
        social_ttc=social_ttc,
        commerce_surface_m2=p.shab_commerce_m2,
        commerce_prix_ht_m2=inp.prix_vente_ht_commerce_eur_m2_shab,
        commerce_ht=commerce_ht,
        commerce_ttc=commerce_ttc,
        total_ht=total_ht,
        total_ttc=total_ttc,
        prix_m2_shab_moyen_ht=total_ht / shab_total,
    )


# ---------- Chapitres ----------


def _compute_foncier(p: BilanProgramme, inp: BilanInputs) -> BilanChapitre:
    postes: list[BilanPoste] = []
    postes.append(
        _poste(
            "Achat terrain",
            inp.prix_terrain_total_ht,
            base=p.terrain_m2,
            taux=inp.prix_terrain_total_ht / p.terrain_m2 if p.terrain_m2 else 0.0,
            tva_pct=0.0,
        )
    )
    postes.append(
        _poste(
            "Frais acquisition",
            inp.prix_terrain_total_ht * inp.frais_acquisition_pct,
            base=inp.prix_terrain_total_ht,
            taux=inp.frais_acquisition_pct,
            tva_pct=0.0,
        )
    )
    postes.append(_poste("Géomètre / bornage", inp.frais_geometre_forfait))
    postes.append(_poste("Sondages / étude de sol", inp.frais_sondages_forfait))

    assiette_ta = inp.taxe_amenagement_assiette_m2 or p.sdp_m2 * 1.244
    taux_ta = (
        inp.taxe_amenagement_taux_commune
        + inp.taxe_amenagement_taux_departement
        + inp.taxe_amenagement_taux_region
        + inp.taxe_amenagement_taux_inrap
    )
    montant_ta = assiette_ta * taux_ta * inp.taxe_amenagement_valeur_m2
    postes.append(
        _poste(
            "Taxe d'aménagement",
            montant_ta,
            base=assiette_ta,
            taux=taux_ta * inp.taxe_amenagement_valeur_m2,
            tva_pct=0.0,
        )
    )
    postes.append(
        _poste(
            "Redevance insuffisance parking",
            inp.redevance_insuff_parking_forfait,
            tva_pct=0.0,
        )
    )
    postes.append(
        _poste(
            "Autres taxes (assainissement)",
            p.sdp_m2 * inp.taxe_assainissement_eur_m2_sdp,
            base=p.sdp_m2,
            taux=inp.taxe_assainissement_eur_m2_sdp,
            tva_pct=0.0,
        )
    )
    postes.append(_poste("Constats huissier et voisins", inp.constats_huissier_forfait))
    postes.append(_poste("Démolition", inp.demolition_forfait))
    postes.append(
        _poste(
            "Honos conseil (avocat)",
            inp.prix_terrain_total_ht * inp.honos_avocat_pct_terrain,
            base=inp.prix_terrain_total_ht,
            taux=inp.honos_avocat_pct_terrain,
        )
    )
    postes.append(_poste("Taxe sur dation", inp.taxe_dation_forfait, tva_pct=0.0))
    postes.append(
        _poste(
            "Divers (concession, taxe foncière)",
            inp.prix_terrain_total_ht * inp.divers_concession_pct_terrain,
            base=inp.prix_terrain_total_ht,
            taux=inp.divers_concession_pct_terrain,
            tva_pct=0.0,
        )
    )
    return _close_chapter("Foncier", postes)


def _compute_travaux(p: BilanProgramme, inp: BilanInputs) -> BilanChapitre:
    postes: list[BilanPoste] = []
    postes.append(
        _poste(
            "Bâtiment logement libre",
            p.shab_libre_m2 * inp.cout_travaux_libre_eur_m2_shab,
            base=p.shab_libre_m2,
            taux=inp.cout_travaux_libre_eur_m2_shab,
            tva_pct=inp.tva_travaux_pct,
        )
    )
    postes.append(
        _poste(
            "Bâtiment social",
            p.shab_social_m2 * inp.cout_travaux_social_eur_m2_shab,
            base=p.shab_social_m2,
            taux=inp.cout_travaux_social_eur_m2_shab,
            tva_pct=inp.tva_travaux_pct,
        )
    )
    postes.append(
        _poste(
            "Commerce",
            p.shab_commerce_m2 * inp.cout_travaux_commerce_eur_m2_shab,
            base=p.shab_commerce_m2,
            taux=inp.cout_travaux_commerce_eur_m2_shab,
            tva_pct=inp.tva_travaux_pct,
        )
    )
    postes.append(
        _poste(
            "Parkings sous-sol",
            p.nb_parkings_ss_sol * inp.cout_parking_ss_sol_eur,
            base=p.nb_parkings_ss_sol,
            taux=inp.cout_parking_ss_sol_eur,
            tva_pct=0.0,
        )
    )
    postes.append(
        _poste(
            "Parkings extérieurs",
            p.nb_parkings_exterieurs * inp.cout_parking_exterieur_eur,
            base=p.nb_parkings_exterieurs,
            taux=inp.cout_parking_exterieur_eur,
            tva_pct=0.0,
        )
    )
    return _close_chapter("Travaux", postes)


def _compute_honoraires(travaux_ht: float, inp: BilanInputs) -> BilanChapitre:
    postes: list[BilanPoste] = []
    for libelle, taux in [
        ("Architecte conception", inp.honos_architecte_pct_travx),
        ("Maîtrise d'œuvre exécution + BET", inp.honos_moe_exe_pct_travx),
        ("Autres BET", inp.honos_autres_bet_pct_travx),
        ("Mission SPS et bureau de contrôle", inp.honos_sps_bc_pct_travx),
        ("AMO (option)", inp.honos_amo_pct_travx),
    ]:
        if taux > 0:
            postes.append(
                _poste(libelle, travaux_ht * taux, base=travaux_ht, taux=taux)
            )
    if inp.expert_comptable_forfait > 0:
        postes.append(_poste("Expert comptable", inp.expert_comptable_forfait))
    return _close_chapter("Honoraires techniques", postes)


def _compute_assurances(
    travaux_ttc: float, honos_ttc: float, inp: BilanInputs
) -> BilanChapitre:
    base = travaux_ttc + honos_ttc
    postes = [
        _poste(
            "Assurances TRC, DO, CNR + RC",
            base * inp.assurances_pct_travx_honos_ttc,
            base=base,
            taux=inp.assurances_pct_travx_honos_ttc,
            tva_pct=0.0,
        )
    ]
    return _close_chapter("Assurances", postes)


def _compute_commercialisation(
    ventes_ttc: float, inp: BilanInputs
) -> BilanChapitre:
    postes: list[BilanPoste] = []
    postes.append(
        _poste(
            "Honoraires commercialisation ventes détail",
            ventes_ttc * inp.honos_comm_vente_pct_ventes_ttc,
            base=ventes_ttc,
            taux=inp.honos_comm_vente_pct_ventes_ttc,
        )
    )
    postes.append(_poste("Mise en copropriété", inp.mise_en_copro_forfait))
    if inp.honos_comm_locatif_pct > 0:
        postes.append(
            _poste(
                "Honoraires commercialisation locatif",
                ventes_ttc * inp.honos_comm_locatif_pct,
                base=ventes_ttc,
                taux=inp.honos_comm_locatif_pct,
            )
        )
    postes.append(
        _poste(
            "Frais commercialisation + plaquette",
            ventes_ttc * inp.frais_comm_plaquette_pct_ventes_ttc,
            base=ventes_ttc,
            taux=inp.frais_comm_plaquette_pct_ventes_ttc,
        )
    )
    return _close_chapter("Commercialisation", postes)


def _compute_gestion_fi(
    *,
    ventes_ttc: float,
    travaux_ttc: float,
    inp: BilanInputs,
) -> BilanChapitre:
    postes: list[BilanPoste] = []
    if inp.honos_gestion_pct_ventes_ttc > 0:
        postes.append(
            _poste(
                "Honoraires de gestion",
                ventes_ttc * inp.honos_gestion_pct_ventes_ttc,
                base=ventes_ttc,
                taux=inp.honos_gestion_pct_ventes_ttc,
            )
        )
    postes.append(
        _poste(
            "Honoraires SAV",
            travaux_ttc * inp.honos_sav_pct_travx_ttc,
            base=travaux_ttc,
            taux=inp.honos_sav_pct_travx_ttc,
        )
    )
    if inp.frais_stock_forfait > 0:
        postes.append(_poste("Frais sur stock (copro)", inp.frais_stock_forfait))
    postes.append(_poste("Frais de dossier banque", inp.frais_dossier_banque_forfait))
    postes.append(
        _poste(
            "GFA (garantie financière d'achèvement)",
            ventes_ttc * inp.gfa_pct_ventes_ttc,
            base=ventes_ttc,
            taux=inp.gfa_pct_ventes_ttc,
            tva_pct=0.0,
        )
    )
    postes.append(
        _poste(
            "Cautions et engagements / an",
            inp.fonds_propres_ht * inp.cautions_pct_fonds_propres_an,
            base=inp.fonds_propres_ht,
            taux=inp.cautions_pct_fonds_propres_an,
            tva_pct=0.0,
        )
    )
    postes.append(
        _poste(
            "Frais financiers",
            inp.frais_financiers_total,
            base=inp.fonds_propres_ht,
            taux="forfait",
            tva_pct=0.0,
        )
    )
    return _close_chapter("Gestion et frais financiers", postes)


def _compute_imprevus(
    travaux_ht: float, honos_ht: float, inp: BilanInputs
) -> BilanChapitre:
    base = travaux_ht + honos_ht
    postes = [
        _poste(
            "Imprévus sur travaux + honoraires",
            base * inp.imprevus_pct_travx_honos,
            base=base,
            taux=inp.imprevus_pct_travx_honos,
            tva_pct=inp.tva_travaux_pct,
        )
    ]
    return _close_chapter("Imprévus", postes)


# ---------- Orchestrator ----------


def compute_bilan(
    programme: BilanProgramme,
    inputs: BilanInputs,
    *,
    option_label: Literal["opt1", "opt2", "opt3", "custom"] = "custom",
) -> BilanResult:
    """Compute the full French-promoteur bilan (P&L) from programme + rates.

    The seven dépenses chapters are accumulated in the same order as the
    canonical French bilan (foncier → travaux → honos → assurances →
    commercialisation → gestion/fi → imprévus). TVA résiduelle = TVA sur
    ventes − TVA déductible (cumulée sur dépenses TTC).
    """
    recettes = _compute_recettes(programme, inputs)
    foncier = _compute_foncier(programme, inputs)
    travaux = _compute_travaux(programme, inputs)
    honoraires = _compute_honoraires(travaux.total_ht, inputs)
    assurances = _compute_assurances(travaux.total_ttc, honoraires.total_ttc, inputs)
    commercialisation = _compute_commercialisation(recettes.total_ttc, inputs)
    gestion_fi = _compute_gestion_fi(
        ventes_ttc=recettes.total_ttc,
        travaux_ttc=travaux.total_ttc,
        inp=inputs,
    )
    imprevus = _compute_imprevus(travaux.total_ht, honoraires.total_ht, inputs)

    chapters = [
        foncier,
        travaux,
        honoraires,
        assurances,
        commercialisation,
        gestion_fi,
        imprevus,
    ]
    depenses_total_ht = sum(c.total_ht for c in chapters)
    depenses_total_ttc = sum(c.total_ttc for c in chapters)
    for c in chapters:
        c.pct_depenses_ht = (
            c.total_ht / depenses_total_ht if depenses_total_ht else 0.0
        )

    tva_sur_ventes = (
        recettes.libre_ht * inputs.tva_vente_libre_pct
        + recettes.social_ht * inputs.tva_vente_social_pct
        + recettes.commerce_ht * inputs.tva_vente_commerce_pct
    )
    tva_deductible = sum(c.total_tva for c in chapters)
    tva_residuelle = tva_sur_ventes - tva_deductible

    marge_ht = recettes.total_ht - depenses_total_ht
    marge_ttc = recettes.total_ttc - depenses_total_ttc
    marge_pct_ht = marge_ht / recettes.total_ht if recettes.total_ht else 0.0
    marge_pct_ttc = marge_ttc / recettes.total_ttc if recettes.total_ttc else 0.0

    non_foncier_ht = depenses_total_ht - foncier.total_ht
    charge_fonciere_max_ht = recettes.total_ht - non_foncier_ht

    warnings: list[str] = []
    if marge_pct_ht < 0.08:
        warnings.append(
            f"Marge HT {marge_pct_ht:.1%} < 8% — opération à risque pour un promoteur"
        )
    if marge_pct_ht > 0.30:
        warnings.append(
            f"Marge HT {marge_pct_ht:.1%} > 30% — vérifier les prix de vente"
        )
    if programme.shab_total_m2 / programme.sdp_m2 < 0.80:
        warnings.append(
            "Rendement plan SHAB/SDP < 80% — inefficace, revoir le plan"
        )

    return BilanResult(
        programme=programme,
        recettes=recettes,
        foncier=foncier,
        travaux=travaux,
        honoraires=honoraires,
        assurances=assurances,
        commercialisation=commercialisation,
        gestion_financiere=gestion_fi,
        imprevus=imprevus,
        depenses_total_ht=depenses_total_ht,
        depenses_total_ttc=depenses_total_ttc,
        tva_sur_ventes=tva_sur_ventes,
        tva_deductible=tva_deductible,
        tva_residuelle=tva_residuelle,
        marge_ht=marge_ht,
        marge_ttc=marge_ttc,
        marge_pct_ht=marge_pct_ht,
        marge_pct_ttc=marge_pct_ttc,
        charge_fonciere_max_ht=charge_fonciere_max_ht,
        warnings=warnings,
        option_label=option_label,
    )


# ---------- Building-model bridge ----------


def programme_from_building_model(
    building_model: "object",
    *,
    mix_social_pct: float = 0.0,
    shab_commerce_m2: float = 0.0,
    nb_parkings_ss_sol: int | None = None,
    duree_chantier_mois: int = 18,
) -> BilanProgramme:
    """Derive a BilanProgramme from a BuildingModel.

    The BuildingModel has the structural output; the bilan needs surface
    aggregates. This helper pulls them out and splits SHAB between free /
    social according to ``mix_social_pct``. Commerce is kept as an explicit
    override since the 2D plan generator does not yet place RDC commerces.
    """
    from core.building_model.schemas import BuildingModel, CelluleType

    bm = building_model
    if not isinstance(bm, BuildingModel):
        raise TypeError(f"Expected BuildingModel, got {type(bm).__name__}")

    terrain_m2 = bm.site.parcelle_surface_m2
    sdp_m2 = sum(n.surface_plancher_m2 for n in bm.niveaux if n.index >= 0)
    shab_total = sum(
        c.surface_shab_m2 or c.surface_m2
        for n in bm.niveaux
        if n.index >= 0
        for c in n.cellules
        if c.type == CelluleType.LOGEMENT
    )
    shab_social = shab_total * mix_social_pct
    shab_libre = shab_total - shab_social
    rendement = shab_total / sdp_m2 if sdp_m2 else 0.912

    nb_pk_calc = (
        nb_parkings_ss_sol
        if nb_parkings_ss_sol is not None
        else sum(
            1
            for n in bm.niveaux
            if n.index < 0
            for c in n.cellules
            if c.type == CelluleType.PARKING
        )
    )

    return BilanProgramme(
        terrain_m2=terrain_m2,
        ces=bm.envelope.emprise_m2 / terrain_m2 if terrain_m2 else 0.0,
        sdp_m2=sdp_m2,
        rendement_plan_shab_sur_sdp=rendement,
        shab_libre_m2=shab_libre,
        shab_social_m2=shab_social,
        shab_commerce_m2=shab_commerce_m2,
        nb_parkings_ss_sol=nb_pk_calc,
        nb_parkings_exterieurs=0,
        duree_chantier_mois=duree_chantier_mois,
    )
