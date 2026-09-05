"""Tests Nogent 80 rue des Héros — conformité v2 + overlays cache.

Vérifie que les 7 overlays prioritaires documentés dans
``refs/plu/nogent_80_heros_overlays_exhaustifs.md`` et persistés dans
``apps/render-service/src/prompt_context/plu_rules_cache.json``
(``project_overlays.nogent_80_heros``) sont chargés par
``OverlayContext.from_project_slug()`` puis évalués par
``validate_conformite_v2()`` pour produire les bonnes décisions.

Lives under ``tests/unit/`` (memory feedback_dont_truncate_prod_db — never
run the full ``pytest tests/`` against a dev DB).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from core.building_model.schemas import (
    BuildingModel,
    Cellule,
    CelluleType,
    Core,
    Envelope,
    Escalier,
    Facade,
    Metadata,
    Niveau,
    Site,
    ToitureConfig,
    ToitureType,
    Typologie,
)
from core.building_model.validator import (
    BusinessRules,
    ConformiteCheckItem,
    OverlayContext,
    validate_conformite_v2,
)
from core.plu.schemas import NumericRules

PROJECT_SLUG = "nogent_80_heros"


# ---------------------------------------------------------------------------
# Building fixtures — Nogent 80 rue des Héros
# ---------------------------------------------------------------------------


def _nogent_building(
    *,
    niveaux_count: int = 6,  # R+5
    hauteur_totale_m: float = 18.0,
    rdc_logement: bool = False,
    rdc_commerce: bool = False,
    typologies: list[Typologie] | None = None,
) -> BuildingModel:
    """Construct a minimal BM resembling 80 rue des Héros, default R+5 18m.

    The parcelle is a 30×30 stand-in for the 3-parcel agglomerated lot
    (940520000G0123/0124/0125), and the footprint is centered with 5 m
    setbacks. Voirie south (rue des Héros).
    """
    parcelle = [[0.0, 0.0], [30.0, 0.0], [30.0, 30.0], [0.0, 30.0], [0.0, 0.0]]
    footprint = [[5.0, 5.0], [25.0, 5.0], [25.0, 25.0], [5.0, 25.0], [5.0, 5.0]]
    typologies = typologies or [
        Typologie.T3, Typologie.T3, Typologie.T2,
        Typologie.T3, Typologie.T4, Typologie.T3,
    ]

    cellules_rdc: list[Cellule] = []
    if rdc_logement:
        cellules_rdc.append(Cellule(
            id="log-rdc-0", type=CelluleType.LOGEMENT, typologie=Typologie.T3,
            surface_m2=70.0, surface_sdp_m2=70.0,
            polygon_xy=[(5.0, 5.0), (25.0, 5.0), (25.0, 15.0), (5.0, 15.0)],
        ))
    if rdc_commerce:
        cellules_rdc.append(Cellule(
            id="cmrc-rdc-0", type=CelluleType.COMMERCE,
            surface_m2=200.0, surface_sdp_m2=200.0,
            polygon_xy=[(5.0, 5.0), (25.0, 5.0), (25.0, 15.0), (5.0, 15.0)],
        ))

    niveaux: list[Niveau] = [
        Niveau(
            index=0, code="R+0", usage_principal="mixte",
            hauteur_sous_plafond_m=3.0, surface_plancher_m2=200.0,
            cellules=cellules_rdc,
        ),
    ]
    # R+1 → R+N logement, 1 cellule logement par niveau
    for lvl, t in enumerate(typologies[: niveaux_count - 1], start=1):
        niveaux.append(Niveau(
            index=lvl, code=f"R+{lvl}", usage_principal="logement",
            hauteur_sous_plafond_m=2.7, surface_plancher_m2=200.0,
            cellules=[Cellule(
                id=f"log-{lvl}", type=CelluleType.LOGEMENT, typologie=t,
                surface_m2=200.0, surface_sdp_m2=200.0,
                polygon_xy=[(5.0, 5.0), (25.0, 5.0), (25.0, 25.0), (5.0, 25.0)],
            )],
        ))

    return BuildingModel(
        metadata=Metadata(
            id=uuid4(), project_id=uuid4(),
            address="80 Rue des Héros Nogentais 94130 Nogent-sur-Marne",
            zone_plu="UA1", created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC), version=1, locked=False,
        ),
        site=Site(
            parcelle_geojson={"type": "Polygon", "coordinates": [parcelle]},
            parcelle_surface_m2=900.0,  # 30×30 stand-in
            voirie_orientations=["sud"], north_angle_deg=0.0,
        ),
        envelope=Envelope(
            footprint_geojson={"type": "Polygon", "coordinates": [footprint]},
            emprise_m2=400.0,  # 20×20 footprint ≈ 44% emprise < 80% UA1
            niveaux=niveaux_count, hauteur_totale_m=hauteur_totale_m,
            hauteur_rdc_m=3.0, hauteur_etage_courant_m=2.7,
            toiture=ToitureConfig(
                type=ToitureType.TERRASSE, accessible=False, vegetalisee=False,
            ),
        ),
        core=Core(
            position_xy=(15.0, 15.0), surface_m2=18.0,
            escalier=Escalier(
                type="droit", giron_cm=28, hauteur_marche_cm=17,
                nb_marches_par_niveau=18,
            ),
            ascenseur=None, gaines_techniques=[],
        ),
        niveaux=niveaux,
        facades={k: Facade(style="e", composition=[], rgb_main="#fff")
                 for k in ("nord", "sud", "est", "ouest")},
    )


def _nogent_rules() -> NumericRules:
    """UA1 numeric rules (from plu_rules_cache.json entries[nogent-sur-marne|UA1])."""
    return NumericRules(
        emprise_max_pct=80.0,
        hauteur_max_m=18.0,
        hauteur_max_niveaux=5,  # R+5
        recul_voirie_m=0.0,
        recul_limite_lat_m=4.0,
        recul_fond_m=6.0,
        pleine_terre_min_pct=15.0,
        stationnement_par_logement=1.0,
    )


def _find(checks: list[ConformiteCheckItem], code: str) -> ConformiteCheckItem:
    matches = [c for c in checks if c.code == code]
    assert matches, f"check {code} not found in {[c.code for c in checks]}"
    return matches[0]


# ---------------------------------------------------------------------------
# 1. plu_rules_cache.json — project_overlays loader
# ---------------------------------------------------------------------------


def test_project_overlays_cache_has_nogent_80_heros():
    """Le cache doit exposer la clé project_overlays.nogent_80_heros."""
    cache = (
        Path(__file__).resolve().parents[3]
        / "render-service"
        / "src"
        / "prompt_context"
        / "plu_rules_cache.json"
    )
    data = json.loads(cache.read_text(encoding="utf-8"))
    assert "project_overlays" in data
    overlays = data["project_overlays"][PROJECT_SLUG]
    assert overlays["in_perimetre_ac1"] is True
    assert overlays["in_lineaire_l151_16"] is True
    assert overlays["in_l151_19"] is True
    assert overlays["ppri_zone"] == "bleu"
    assert overlays["rga_niveau"] == "moyen"
    assert overlays["stationnement_perimetre_bonne_desserte"] is True
    assert overlays["stationnement_pl_max_per_log"] == 1.0


def test_overlay_context_from_project_slug_loads_fields():
    """OverlayContext.from_project_slug doit câbler tous les champs prioritaires."""
    ctx = OverlayContext.from_project_slug(PROJECT_SLUG)
    assert ctx.in_perimetre_ac1 is True
    assert ctx.abf_distance_mh_m == 390
    assert "Saint-Saturnin" in (ctx.abf_mh_reference or "")
    assert ctx.in_lineaire_l151_16 is True
    assert ctx.in_l151_19 is True
    assert "n°88 Mairie de Nogent" in ctx.voisin_l151_19_references
    assert ctx.ppri_zone == "bleu"
    assert ctx.ppri_cote_phec_ngf == 33.5
    assert ctx.rga_niveau == "moyen"
    assert ctx.stationnement_perimetre_bonne_desserte is True
    assert ctx.stationnement_pl_max_per_log == 1.0
    # HG carte 4-4 non encore confirmé → None, check skipped
    assert ctx.hauteur_graphique_carte_4_4_m is None


def test_overlay_context_unknown_slug_returns_empty():
    ctx = OverlayContext.from_project_slug("does_not_exist_42")
    # Toutes les valeurs doivent rester None / défaut
    assert ctx.in_perimetre_ac1 is None
    assert ctx.ppri_zone is None
    assert ctx.rga_niveau is None


# ---------------------------------------------------------------------------
# 2. Nogent 80 R+5 18m — projet RDC commerce → checks attendus
# ---------------------------------------------------------------------------


def test_nogent_r5_18m_with_commerce_rdc_overlay_outcomes():
    """R+5 18m + RDC commerce → ABF fail (avis manquant), linéaire OK,
    PPRI skip (cote plancher inconnue), RGA fail (G2 manquante),
    stationnement skip (places projet non renseignées),
    hauteur graphique skip (HG carte 4-4 inconnu)."""
    bm = _nogent_building(
        niveaux_count=6, hauteur_totale_m=18.0,
        rdc_logement=False, rdc_commerce=True,
        typologies=[Typologie.T3, Typologie.T3, Typologie.T2,
                    Typologie.T3, Typologie.T4],
    )
    overlays = OverlayContext.from_project_slug(PROJECT_SLUG)
    business = BusinessRules.for_commune(
        "nogent-sur-marne",
        marge_actual_pct=15.0,
        lls_actual_pct=30.0,
    )
    out = validate_conformite_v2(
        bm, _nogent_rules(),
        overlays=overlays, business_rules=business,
    )
    # ABF — périmètre 500m Saint-Saturnin actif, avis non obtenu → fail (blocking)
    abf = _find(out.checks, "ABF_AC1")
    assert abf.status == "fail" and abf.severity == "blocking"

    # Linéaire commercial L.151-16 — RDC commerce présent → pass
    lin = _find(out.checks, "LINEAIRE_L151_16")
    assert lin.status == "pass"

    # PPRI — zone bleu mais cote plancher RDC inconnue → skipped
    ppri = _find(out.checks, "PPRI_PHEC")
    assert ppri.status == "skipped"

    # RGA aléa moyen + étude G2 non réalisée → fail warning
    rga = _find(out.checks, "RGA")
    assert rga.status == "fail" and rga.severity == "warning"

    # L.151-19 — Mairie n°88 voisin protégé, autorisation modif non renseignée → fail blocking
    l15119 = _find(out.checks, "L151_19")
    assert l15119.status == "fail"

    # Stationnement — places_projet None → skipped
    stat = _find(out.checks, "STATIONNEMENT")
    assert stat.status == "skipped"

    # HG carte 4-4 inconnu → skipped (la valeur null dans le cache)
    hg = _find(out.checks, "HAUTEUR_GRAPHIQUE")
    assert hg.status == "skipped"


def test_nogent_r5_18m_with_rdc_logement_lineaire_fail():
    """R+5 18m RDC logement (au lieu de commerce) → linéaire L.151-16 fail (blocking)."""
    bm = _nogent_building(rdc_logement=True, rdc_commerce=False)
    overlays = OverlayContext.from_project_slug(PROJECT_SLUG)
    out = validate_conformite_v2(bm, _nogent_rules(), overlays=overlays)
    lin = _find(out.checks, "LINEAIRE_L151_16")
    assert lin.status == "fail"
    assert lin.severity == "blocking"


# ---------------------------------------------------------------------------
# 3. Hauteur graphique carte 4-4 — override UA.10
# ---------------------------------------------------------------------------


def test_hauteur_graphique_skipped_when_unknown():
    bm = _nogent_building()
    overlays = OverlayContext.from_project_slug(PROJECT_SLUG)
    assert overlays.hauteur_graphique_carte_4_4_m is None
    out = validate_conformite_v2(bm, _nogent_rules(), overlays=overlays)
    assert _find(out.checks, "HAUTEUR_GRAPHIQUE").status == "skipped"


def test_hauteur_graphique_12m_fails_r5_18m():
    """Si carte 4-4 confirme HG=12m (probable côté Mairie covisibilité Saint-Saturnin),
    le projet R+5 18m doit échouer le check hauteur graphique."""
    bm = _nogent_building(niveaux_count=6, hauteur_totale_m=18.0)
    overlays = OverlayContext.from_project_slug(PROJECT_SLUG)
    overlays.hauteur_graphique_carte_4_4_m = 12.0
    out = validate_conformite_v2(bm, _nogent_rules(), overlays=overlays)
    hg = _find(out.checks, "HAUTEUR_GRAPHIQUE")
    assert hg.status == "fail" and hg.severity == "blocking"
    assert hg.allowed == 12.0
    assert (hg.actual or 0) >= 17.95


def test_hauteur_graphique_12m_pass_r3_12m():
    """R+3 à 12m doit passer le check HG=12m."""
    bm = _nogent_building(niveaux_count=4, hauteur_totale_m=12.0)
    overlays = OverlayContext.from_project_slug(PROJECT_SLUG)
    overlays.hauteur_graphique_carte_4_4_m = 12.0
    out = validate_conformite_v2(bm, _nogent_rules(), overlays=overlays)
    assert _find(out.checks, "HAUTEUR_GRAPHIQUE").status == "pass"


# ---------------------------------------------------------------------------
# 4. Stationnement plafond PDU — 1pl/log max périmètre bonne desserte RER A
# ---------------------------------------------------------------------------


def test_stationnement_pdu_plafond_respected():
    """5 logements × 1pl/log = 5 places projet → pass."""
    bm = _nogent_building(niveaux_count=6, hauteur_totale_m=18.0,
                          rdc_commerce=True)
    overlays = OverlayContext.from_project_slug(PROJECT_SLUG)
    overlays.stationnement_places_projet = 5.0  # = nb logements (5 = 6 niv - RDC commerce)
    out = validate_conformite_v2(bm, _nogent_rules(), overlays=overlays)
    stat = _find(out.checks, "STATIONNEMENT")
    assert stat.status == "pass", stat.message


def test_stationnement_pdu_plafond_exceeded():
    """5 logements + 10 places projet > 5 plafond PDU → fail (blocking)."""
    bm = _nogent_building(niveaux_count=6, hauteur_totale_m=18.0,
                          rdc_commerce=True)
    overlays = OverlayContext.from_project_slug(PROJECT_SLUG)
    overlays.stationnement_places_projet = 10.0
    out = validate_conformite_v2(bm, _nogent_rules(), overlays=overlays)
    stat = _find(out.checks, "STATIONNEMENT")
    assert stat.status == "fail" and stat.severity == "blocking"
    assert stat.allowed == 5.0


# ---------------------------------------------------------------------------
# 5. Non-compliant project — blocking_errors contains violations
# ---------------------------------------------------------------------------


def test_nogent_non_compliant_blocks_render():
    """R+5 18m, RDC logement, marge 10% → blocking_errors couvre :
    LINEAIRE_L151_16, ABF_AC1, BUSINESS_MARGE, L151_19."""
    bm = _nogent_building(
        niveaux_count=6, hauteur_totale_m=18.0,
        rdc_logement=True, rdc_commerce=False,
    )
    overlays = OverlayContext.from_project_slug(PROJECT_SLUG)
    business = BusinessRules.for_commune(
        "nogent-sur-marne",
        marge_actual_pct=10.0,  # < 12 % bancaire minimum
        lls_actual_pct=30.0,
    )
    out = validate_conformite_v2(
        bm, _nogent_rules(), overlays=overlays, business_rules=business,
    )
    assert out.has_blocking_errors()
    codes = {b.code for b in out.blocking_errors()}
    # Au minimum : RDC logement viole linéaire commercial, ABF non obtenu,
    # marge bilan en dessous bancaire, et voisin L.151-19 sans autorisation.
    assert "LINEAIRE_L151_16" in codes
    assert "ABF_AC1" in codes
    assert "BUSINESS_MARGE" in codes
    assert "L151_19" in codes
