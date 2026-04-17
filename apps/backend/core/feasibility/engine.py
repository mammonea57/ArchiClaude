"""Feasibility engine orchestrator — assembles all sub-modules into a single pipeline call.

Coordinate system flow:
  - Input: terrain_geojson in WGS84 (EPSG:4326)
  - Internal computation: Lambert-93 (EPSG:2154, metric)
  - Output footprint_geojson: back to WGS84

All monetary or sizing decisions downstream must treat results as indicatifs
pending calibration against real programmes. See project precision requirement.
"""

from __future__ import annotations

from datetime import datetime

from shapely.geometry import mapping, shape

from core.compliance.incendie import classify_incendie
from core.compliance.lls_sru import compute_lls_obligation
from core.compliance.pmr import compute_pmr
from core.compliance.re2020 import estimate_re2020
from core.compliance.rsdu import compute_rsdu_obligations
from core.feasibility.brief_compare import compare_brief_to_max
from core.feasibility.capacity import compute_capacity
from core.feasibility.footprint import compute_footprint
from core.feasibility.schemas import Alert, Brief, ComplianceResult, FeasibilityResult
from core.feasibility.servitudes import ServitudeAlert, detect_servitudes_alerts
from core.geo.surface import _reproject
from core.plu.schemas import NumericRules


def run_feasibility(
    *,
    terrain_geojson: dict,
    numeric_rules: NumericRules,
    brief: Brief,
    monuments: list | None = None,
    risques: list | None = None,
    servitudes_gpu: list | None = None,
    altitude_sol_m: float | None = None,
    commune_sru_statut: str = "non_soumise",
    annee_cible_pc: int = 2025,
) -> FeasibilityResult:
    """Run the full feasibility pipeline and return a FeasibilityResult.

    Args:
        terrain_geojson: GeoJSON geometry dict (Polygon or MultiPolygon) in WGS84.
        numeric_rules: Parsed numeric PLU rules for the zone.
        brief: Developer programme targets.
        monuments: Pre-fetched MonumentResult list (POP).
        risques: Pre-fetched RisqueResult list (GeoRisques).
        servitudes_gpu: Pre-fetched GpuServitude list.
        altitude_sol_m: Ground altitude (NGF) in metres.
        commune_sru_statut: SRU status of the commune.
        annee_cible_pc: Target year for building permit submission.

    Returns:
        FeasibilityResult with all computed values.
    """
    all_warnings: list[str] = []

    # ------------------------------------------------------------------
    # Step 1: Convert terrain GeoJSON to Lambert-93 Shapely geometry
    # ------------------------------------------------------------------
    terrain_wgs84 = shape(terrain_geojson)
    terrain_l93 = _reproject(terrain_wgs84, "EPSG:4326", "EPSG:2154")

    # ------------------------------------------------------------------
    # Step 2: Footprint — emprise, pleine terre
    # ------------------------------------------------------------------
    footprint_result = compute_footprint(
        terrain=terrain_l93,
        recul_voirie_m=numeric_rules.recul_voirie_m or 0.0,
        recul_lat_m=numeric_rules.recul_limite_lat_m or 0.0,
        recul_fond_m=numeric_rules.recul_fond_m or 0.0,
        emprise_max_pct=numeric_rules.emprise_max_pct or 100.0,
    )

    # ------------------------------------------------------------------
    # Step 3: Capacity — hauteur, niveaux, SDP, logements, stationnement
    # ------------------------------------------------------------------
    capacity_result = compute_capacity(
        surface_emprise_m2=footprint_result.surface_emprise_m2,
        surface_terrain_m2=footprint_result.surface_terrain_m2,
        hauteur_max_m=numeric_rules.hauteur_max_m,
        niveaux_max=numeric_rules.hauteur_max_niveaux,
        altitude_sol_m=altitude_sol_m,
        hauteur_max_ngf=numeric_rules.hauteur_max_ngf,
        sdp_max_plu=numeric_rules.sdp_max_m2,
        cos=numeric_rules.cos,
        mix=brief.mix_typologique,
        ratio_stationnement=numeric_rules.stationnement_par_logement or 1.0,
    )
    all_warnings.extend(capacity_result.warnings)

    # ------------------------------------------------------------------
    # Step 4: Servitudes / hard constraint alerts
    # ------------------------------------------------------------------
    servitude_alerts: list[ServitudeAlert] = detect_servitudes_alerts(
        monuments=monuments or [],
        risques=risques or [],
        servitudes=servitudes_gpu or [],
    )
    alertes_dures: list[Alert] = [
        Alert(
            level=sa.level,
            type=sa.type,
            message=sa.message,
            source=sa.source,
        )
        for sa in servitude_alerts
    ]
    servitudes_actives = [
        {"level": sa.level, "type": sa.type, "message": sa.message, "source": sa.source}
        for sa in servitude_alerts
    ]

    # ------------------------------------------------------------------
    # Step 5: Compliance
    # ------------------------------------------------------------------
    # Incendie — use hauteur of the top inhabited floor (one floor below total)
    hauteur_plancher_haut = max(
        0.0, capacity_result.hauteur_retenue_m - 3.0
    )  # approximate: top floor height ≈ total - one storey
    incendie_classement, incendie_coef = classify_incendie(
        hauteur_plancher_haut_m=hauteur_plancher_haut,
        nb_niveaux=capacity_result.nb_niveaux,
        destination=brief.destination,
    )

    # PMR
    ascenseur, surf_circ, nb_pmr = compute_pmr(
        nb_niveaux=capacity_result.nb_niveaux,
        nb_places=capacity_result.nb_places_stationnement,
        destination=brief.destination,
    )

    # RE2020
    ic_const, ic_energie, seuil_re, re_warnings = estimate_re2020(
        destination=brief.destination,
        annee_cible=annee_cible_pc,
    )
    all_warnings.extend(re_warnings)

    # LLS/SRU
    obligation_pct, bonus_pct, lls_warnings = compute_lls_obligation(
        commune_statut=commune_sru_statut,
        sdp_m2=capacity_result.sdp_max_m2,
        nb_logements=capacity_result.nb_logements_max,
    )
    all_warnings.extend(lls_warnings)

    # RSDU
    rsdu_obligations = compute_rsdu_obligations()

    compliance = ComplianceResult(
        incendie_classement=incendie_classement,
        incendie_coef_reduction_sdp=incendie_coef,
        pmr_ascenseur_obligatoire=ascenseur,
        pmr_surface_circulations_m2=surf_circ,
        pmr_nb_places_pmr=nb_pmr,
        re2020_ic_construction_estime=ic_const,
        re2020_ic_energie_estime=ic_energie,
        re2020_seuil_applicable=seuil_re,
        lls_commune_statut=commune_sru_statut,
        lls_obligation_pct=obligation_pct,
        lls_bonus_constructibilite_pct=bonus_pct,
        rsdu_applicable=True,
        rsdu_obligations=rsdu_obligations,
    )

    # ------------------------------------------------------------------
    # Step 6: Brief gap analysis
    # ------------------------------------------------------------------
    ecart_brief = compare_brief_to_max(
        brief_nb_logements=brief.cible_nb_logements,
        max_nb_logements=capacity_result.nb_logements_max,
        brief_sdp_m2=brief.cible_sdp_m2,
        max_sdp_m2=capacity_result.sdp_max_m2,
        brief_hauteur_niveaux=brief.hauteur_cible_niveaux,
        max_niveaux=capacity_result.nb_niveaux,
        brief_emprise_pct=brief.emprise_cible_pct,
        max_emprise_pct=numeric_rules.emprise_max_pct or 0.0,
    )

    # ------------------------------------------------------------------
    # Step 7: Convert footprint geometry back to WGS84 GeoJSON
    # ------------------------------------------------------------------
    footprint_geom = footprint_result.footprint_geom
    footprint_geojson: dict = {}
    if footprint_geom is not None and not footprint_geom.is_empty:
        footprint_wgs84 = _reproject(footprint_geom, "EPSG:2154", "EPSG:4326")
        footprint_geojson = dict(mapping(footprint_wgs84))

    # ------------------------------------------------------------------
    # Confidence score: average of extraction_confidence, penalise critical alerts
    # ------------------------------------------------------------------
    base_confidence = numeric_rules.extraction_confidence or 0.0
    critical_count = sum(1 for a in servitude_alerts if a.level == "critical")
    confidence_score = max(0.0, base_confidence - critical_count * 0.15)

    # ------------------------------------------------------------------
    # Assemble result
    # ------------------------------------------------------------------
    return FeasibilityResult(
        surface_terrain_m2=footprint_result.surface_terrain_m2,
        zones_applicables=[],
        footprint_geojson=footprint_geojson,
        surface_emprise_m2=footprint_result.surface_emprise_m2,
        surface_pleine_terre_m2=footprint_result.surface_pleine_terre_m2,
        hauteur_retenue_m=capacity_result.hauteur_retenue_m,
        nb_niveaux=capacity_result.nb_niveaux,
        sdp_max_m2=capacity_result.sdp_max_m2,
        sdp_max_m2_avant_compliance=capacity_result.sdp_max_m2,
        nb_logements_max=capacity_result.nb_logements_max,
        nb_par_typologie=capacity_result.nb_par_typologie,
        nb_places_stationnement=capacity_result.nb_places_stationnement,
        nb_places_pmr=nb_pmr,
        compliance=compliance,
        ecart_brief=ecart_brief,
        servitudes_actives=servitudes_actives,
        alertes_dures=alertes_dures,
        points_vigilance=[],
        confidence_score=confidence_score,
        warnings=all_warnings,
        computed_at=datetime.utcnow(),
    )
