"""Conformite V2 — full TOP 20 impact-constraint gate.

This is the **production** pre-render gate that exhaustively checks the
project against the 20 highest-impact regulatory + financial constraints
documented in :file:`refs/plu/taxonomy/FR_urbanism_documents_exhaustive_v1.md`.

Each constraint becomes a ``ConformiteCheckItem`` with an explicit
``pass / fail`` status and a ``blocking | warning`` severity. The
top-level :class:`ConformiteCheckV2` then exposes ``has_blocking_errors``
which the renderer / API / dossier-builder consult to refuse dispatch.

The 20 constraints implemented (ranked by financial impact — see TOP 20
in the taxonomy):

  1. Règlement PLU emprise ≤ max               (blocking)
  2. Règlement PLU hauteur ≤ max               (blocking)
  3. Règlement PLU retraits ≥ min              (blocking)
  4. OAP sectorielle (% LLS, densité, voirie)  (blocking)
  5. AC1 ABF — MH 500m → avis ABF conforme     (blocking flag)
  6. PPRI cote PHEC respectée (RDC ≥ PHEC + Δ) (blocking)
  7. PPRT Seveso — flag si périmètre           (blocking flag)
  8. SRU SMS L.151-15 — % LLS imposé           (blocking)
  9. SUP I1/I3 — bande inconstructible         (blocking flag)
 10. RGA — étude G2 si aléa moyen/fort         (warning)
 11. BASIAS/BASOL — étude L.556-1              (warning / blocking si BASOL)
 12. EBC L.113-1 — interdiction construction   (blocking)
 13. L.151-19 — restrictions modification      (warning / blocking)
 14. Natura 2000 — évaluation incidences       (blocking flag)
 15. CDPENAF — zone A/N                        (blocking flag)
 16. CDAC — commerce > 1000m²                  (warning flag)
 17. RE2020 — attestation présente             (warning)
 18. Stationnement PLU + PDU respecté          (blocking)
 19. R.111-18 — 6m chambres vue voisin         (blocking)
 20. L.151-16 — linéaire commercial RDC        (blocking)

Plus **business gates** (memory: bilan_marge_cible, feedback_plu_typology_mix_rules) :
 21. Marge bilan ≥ 12 %                        (blocking)
 22. Quota LLS ≥ 30 % (Nogent) / commune       (blocking)
 23. Quota T3+ par commune                     (blocking)

Plus **per-project overlay gates** loaded from
``apps/render-service/src/prompt_context/plu_rules_cache.json`` :
 24. Hauteur graphique carte 4-4 PLUi          (blocking)

The legacy validator (PMR / incendie / ventilation / lumière) is **also
re-run** so the ConformiteCheckV2 carries a single source of truth.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

from pydantic import BaseModel, Field
from shapely.geometry import Polygon as ShapelyPolygon
from shapely.geometry import shape as _shape

_log = logging.getLogger(__name__)

from core.building_model.schemas import (
    BuildingModel,
    CelluleType,
    ConformiteAlert,
    ConformiteCheck,
    RoomType,
    Typologie,
)
from core.building_model.validator.conformite import (
    BANK_MIN_MARGE_HT_PCT,
    BusinessRules,
    R111_18_CHAMBRE_RETRAIT_MIN_M,
    _CHAMBRE_TYPES,
    _check_retrait_lateral_and_fond,
    _check_retrait_voirie,
    _footprint_polygon,
    _parcelle_polygon,
    _voirie_side_of_parcelle,
)
from core.plu.schemas import NumericRules

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

# Single source of truth for the project_overlays cache, mirrored by the
# render-service (see apps/render-service/src/prompt_context/plu_context.py).
# Resolved relative to the backend package so the path is stable whether the
# code runs from apps/backend, the monorepo root, or a deployment image.
_REPO_ROOT = Path(__file__).resolve().parents[5]
_DEFAULT_PLU_RULES_CACHE_PATH = (
    _REPO_ROOT
    / "apps"
    / "render-service"
    / "src"
    / "prompt_context"
    / "plu_rules_cache.json"
)


# ---------------------------------------------------------------------------
# Per-check result schema
# ---------------------------------------------------------------------------


CheckSeverity = Literal["blocking", "warning"]
CheckStatus = Literal["pass", "fail", "skipped"]


class ConformiteCheckItem(BaseModel):
    """One regulatory check executed against the project."""

    # Stable canonical id (e.g. "PLU_EMPRISE", "PPRI_PHEC").
    code: str
    # Short FR label for the dashboard.
    label_fr: str
    # Severity if the check fails. Blocking = render refused, PC refused.
    severity: CheckSeverity = "blocking"
    # Outcome.
    status: CheckStatus = "pass"
    # FR human-readable detail (only filled when status == "fail").
    message: str | None = None
    # Stable reference (article CU/CCH/CE/CP/etc.) when applicable.
    article_ref: str | None = None
    # The element (Cellule.id, Room.id, …) the violation pinpoints, if any.
    affected_element_id: str | None = None
    # Numeric context (actual vs allowed) — used by the frontend tooltips.
    actual: float | None = None
    allowed: float | None = None

    @property
    def passed(self) -> bool:  # readability helper for tests / consumers
        return self.status == "pass"


# ---------------------------------------------------------------------------
# Project-context inputs (PLU / overlays / business)
# ---------------------------------------------------------------------------


@dataclass
class OverlayContext:
    """Geo-derived urbanism overlay state for the project.

    Filled by upstream fetchers (Géoportail de l'Urbanisme, GéoRisques,
    INPN, Atlas Patrimoine, DRIHL, …). Every field is optional so that
    the gate stays usable in pilot mode where only a subset of overlays
    has been parsed.

    A ``None`` field means **unknown** — the corresponding check is
    skipped (``status=skipped``) so it cannot silently pass.
    """

    # -- A. PLU / OAP -----------------------------------------------
    # OAP sectorielle (densité min/max, % LLS, programmation imposée).
    in_oap_sectorielle: bool | None = None
    oap_secteur_name: str | None = None
    oap_pct_lls_min: float | None = None
    oap_densite_min_log_ha: float | None = None
    oap_hauteur_max_m: float | None = None
    oap_obligation_voirie: bool | None = None  # voirie principle respecté
    oap_voirie_compliant: bool | None = None

    # -- B. SUP -----------------------------------------------------
    # AC1 — Monument historique 500m / PDA. When True, ABF conforme requise.
    in_perimetre_ac1: bool | None = None
    abf_avis_obtenu: bool | None = None  # True if dossier ABF reçu

    # I1 / I3 — pipelines hydrocarbures / gaz : bande SUP1 = inconstructible.
    in_bande_sup_i1: bool | None = None
    in_bande_sup_i3: bool | None = None

    # -- C. Risque --------------------------------------------------
    # PPRI : cote PHEC NGF + cote du plancher RDC du projet.
    ppri_zone: Literal["rouge", "orange", "bleu", "blanc"] | None = None
    ppri_cote_phec_ngf: float | None = None
    plancher_rdc_ngf: float | None = None
    ppri_delta_securite_m: float = 0.20  # +20 cm canonique (memory PPRI)

    # PPRT Seveso seuil haut.
    in_perimetre_pprt: bool | None = None

    # RGA — Retrait Gonflement Argiles.
    rga_niveau: Literal["faible", "moyen", "fort"] | None = None
    rga_etude_g2_realisee: bool | None = None

    # Pollution sols.
    in_basias: bool | None = None
    in_basol: bool | None = None
    in_sis: bool | None = None
    pollution_etude_l556_1_realisee: bool | None = None

    # -- D. Patrimoine ---------------------------------------------
    in_l151_19: bool | None = None
    l151_19_modification_autorisee: bool | None = None
    in_spr_psmv: bool | None = None  # SPR / PSMV — ABF conforme idem AC1

    # -- E. Mixité --------------------------------------------------
    # SRU / SMS — % LLS imposé par seuil m² SDP.
    sms_pct_lls_min: float | None = None
    sms_seuil_sdp_m2: float | None = None  # appliqué uniquement si SDP > seuil
    # L.151-16 linéaire commercial protégé en RDC.
    in_lineaire_l151_16: bool | None = None
    rdc_commerce_present: bool | None = None

    # -- F. Environnement ------------------------------------------
    in_ebc: bool | None = None  # Espace Boisé Classé sur emprise = blocage
    in_natura2000: bool | None = None
    natura2000_evaluation_realisee: bool | None = None

    # -- H. Supra (déclencheurs) ------------------------------------
    in_zone_a_n: bool | None = None  # CDPENAF déclenchée
    cdpenaf_avis_favorable: bool | None = None
    commerce_surface_vente_m2: float | None = None  # CDAC > 1000m²

    # -- G. RE2020 + stationnement ---------------------------------
    re2020_attestation_presente: bool | None = None
    # Stationnement : nb places exigées (PLU+PDU) vs nb places projetées.
    stationnement_places_requises: float | None = None
    stationnement_places_projet: float | None = None
    # Périmètre bonne desserte (gare RER < 500-800m) → plafond PDU.
    stationnement_perimetre_bonne_desserte: bool | None = None
    # Plafond stationnement par logement appliqué par le PDU (1pl/log Nogent < RER A).
    stationnement_pl_max_per_log: float | None = None

    # -- I. Hauteur graphique (carte 4-4) --------------------------
    # Hauteur graphique HG lue sur la carte prescriptions particulières 4-4 du PLUi.
    # Quand renseignée, override la hauteur PLU UA.10 (toujours MIN(plu, HG)).
    hauteur_graphique_carte_4_4_m: float | None = None

    # -- Z. Métadonnées projet (informationnel, non bloquant) ------
    abf_distance_mh_m: float | None = None
    abf_mh_reference: str | None = None
    voisin_l151_19_references: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Loader from plu_rules_cache.json (project_overlays)
    # ------------------------------------------------------------------
    @classmethod
    def from_project_slug(
        cls, project_slug: str, *, cache_path: Path | None = None,
    ) -> "OverlayContext":
        """Build an :class:`OverlayContext` from the project_overlays cache.

        Reads ``apps/render-service/src/prompt_context/plu_rules_cache.json``
        (key ``project_overlays.<slug>``) populated by agent-recherche
        upstream and maps the fields 1:1 onto the dataclass.

        Returns an empty :class:`OverlayContext` (all fields ``None``) when
        the slug is unknown — the gate keeps working in pilot mode.
        """
        if cache_path is None:
            cache_path = _DEFAULT_PLU_RULES_CACHE_PATH
        try:
            data = json.loads(Path(cache_path).read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            _log.warning("plu_rules_cache unreadable (%s): %s", cache_path, exc)
            return cls()
        overlays = (data.get("project_overlays") or {}).get(project_slug)
        if not isinstance(overlays, dict):
            return cls()
        # Whitelist of accepted keys = OverlayContext field names. Keys
        # prefixed with ``_`` or ``__`` (meta / documentation) are ignored.
        accepted = {f for f in cls.__dataclass_fields__}
        kwargs: dict[str, Any] = {}
        for key, value in overlays.items():
            if key.startswith("_"):
                continue
            if key in accepted:
                kwargs[key] = value
        return cls(**kwargs)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _pass(code: str, label: str, severity: CheckSeverity = "blocking", **extra: Any) -> ConformiteCheckItem:
    return ConformiteCheckItem(code=code, label_fr=label, severity=severity, status="pass", **extra)


def _fail(
    code: str,
    label: str,
    message: str,
    *,
    severity: CheckSeverity = "blocking",
    article_ref: str | None = None,
    actual: float | None = None,
    allowed: float | None = None,
    affected_element_id: str | None = None,
) -> ConformiteCheckItem:
    return ConformiteCheckItem(
        code=code, label_fr=label, severity=severity,
        status="fail", message=message, article_ref=article_ref,
        actual=actual, allowed=allowed,
        affected_element_id=affected_element_id,
    )


def _skip(code: str, label: str, severity: CheckSeverity = "blocking") -> ConformiteCheckItem:
    return ConformiteCheckItem(
        code=code, label_fr=label, severity=severity, status="skipped",
    )


# ---------------------------------------------------------------------------
# Individual check implementations
# ---------------------------------------------------------------------------


def _check_plu_emprise(bm: BuildingModel, rules: NumericRules) -> ConformiteCheckItem:
    label = "Règlement PLU — emprise au sol"
    if rules.emprise_max_pct is None or not bm.site.parcelle_surface_m2:
        return _skip("PLU_EMPRISE", label)
    emprise_max_m2 = bm.site.parcelle_surface_m2 * rules.emprise_max_pct / 100.0
    if bm.envelope.emprise_m2 > emprise_max_m2 + 0.5:
        return _fail(
            "PLU_EMPRISE", label,
            f"Emprise {bm.envelope.emprise_m2:.1f} m² > max {emprise_max_m2:.1f} m² "
            f"({rules.emprise_max_pct:.0f} % de la parcelle)",
            article_ref="Art. 9 PLU",
            actual=bm.envelope.emprise_m2, allowed=emprise_max_m2,
        )
    return _pass("PLU_EMPRISE", label,
                 actual=bm.envelope.emprise_m2, allowed=emprise_max_m2,
                 article_ref="Art. 9 PLU")


def _check_plu_hauteur(bm: BuildingModel, rules: NumericRules) -> ConformiteCheckItem:
    label = "Règlement PLU — hauteur"
    if rules.hauteur_max_m is None:
        return _skip("PLU_HAUTEUR", label)
    if bm.envelope.hauteur_totale_m > rules.hauteur_max_m + 0.05:
        return _fail(
            "PLU_HAUTEUR", label,
            f"Hauteur {bm.envelope.hauteur_totale_m:.2f} m > max {rules.hauteur_max_m:.2f} m",
            article_ref="Art. 10 PLU",
            actual=bm.envelope.hauteur_totale_m, allowed=rules.hauteur_max_m,
        )
    # Also check niveaux R+N if rules specifies.
    if rules.hauteur_max_niveaux is not None:
        r_plus = bm.envelope.niveaux - 1
        if r_plus > rules.hauteur_max_niveaux:
            return _fail(
                "PLU_HAUTEUR", label,
                f"Niveaux R+{r_plus} > max R+{rules.hauteur_max_niveaux}",
                article_ref="Art. 10 PLU",
                actual=float(r_plus), allowed=float(rules.hauteur_max_niveaux),
            )
    return _pass("PLU_HAUTEUR", label,
                 actual=bm.envelope.hauteur_totale_m, allowed=rules.hauteur_max_m,
                 article_ref="Art. 10 PLU")


def _check_plu_retraits(bm: BuildingModel, rules: NumericRules) -> ConformiteCheckItem:
    label = "Règlement PLU — retraits / reculs"
    footprint = _footprint_polygon(bm)
    parcelle = _parcelle_polygon(bm)
    if footprint is None or parcelle is None or footprint.is_empty:
        return _skip("PLU_RETRAITS", label)
    voirie_side = _voirie_side_of_parcelle(bm)

    # 1) Recul voirie
    if rules.recul_voirie_m is not None and voirie_side is not None:
        actual = _check_retrait_voirie(footprint, parcelle, voirie_side, rules.recul_voirie_m)
        if actual is not None and actual + 0.05 < rules.recul_voirie_m:
            return _fail(
                "PLU_RETRAITS", label,
                f"Recul voirie {actual:.2f} m < min {rules.recul_voirie_m:.2f} m",
                article_ref="Art. 6 PLU",
                actual=actual, allowed=rules.recul_voirie_m,
            )

    # 2) Latéral + fond
    if rules.recul_limite_lat_m is not None or rules.recul_fond_m is not None:
        lat, fond = _check_retrait_lateral_and_fond(footprint, parcelle, voirie_side)
        if rules.recul_limite_lat_m is not None and lat + 0.05 < rules.recul_limite_lat_m:
            return _fail(
                "PLU_RETRAITS", label,
                f"Recul limite latérale {lat:.2f} m < min {rules.recul_limite_lat_m:.2f} m",
                article_ref="Art. 7 PLU",
                actual=lat, allowed=rules.recul_limite_lat_m,
            )
        if rules.recul_fond_m is not None and fond + 0.05 < rules.recul_fond_m:
            return _fail(
                "PLU_RETRAITS", label,
                f"Recul fond {fond:.2f} m < min {rules.recul_fond_m:.2f} m",
                article_ref="Art. 7 PLU",
                actual=fond, allowed=rules.recul_fond_m,
            )

    return _pass("PLU_RETRAITS", label, article_ref="Art. 6 + 7 PLU")


def _check_oap_sectorielle(
    bm: BuildingModel, overlays: OverlayContext, business: BusinessRules,
) -> ConformiteCheckItem:
    label = "OAP sectorielle — programmation / densité"
    if overlays.in_oap_sectorielle is None:
        return _skip("OAP_SECTORIELLE", label)
    if not overlays.in_oap_sectorielle:
        return _pass("OAP_SECTORIELLE", label,
                     message="Parcelle hors OAP sectorielle")
    # Hauteur OAP
    if overlays.oap_hauteur_max_m is not None and bm.envelope.hauteur_totale_m > overlays.oap_hauteur_max_m + 0.05:
        return _fail(
            "OAP_SECTORIELLE", label,
            f"OAP {overlays.oap_secteur_name or ''} : hauteur "
            f"{bm.envelope.hauteur_totale_m:.2f} m > max {overlays.oap_hauteur_max_m:.2f} m",
            article_ref="L.151-6/7 CU",
            actual=bm.envelope.hauteur_totale_m, allowed=overlays.oap_hauteur_max_m,
        )
    # % LLS OAP (delegated to business.lls_quota_actual_pct).
    if (
        overlays.oap_pct_lls_min is not None
        and business.lls_quota_actual_pct is not None
        and business.lls_quota_actual_pct + 1e-6 < overlays.oap_pct_lls_min
    ):
        return _fail(
            "OAP_SECTORIELLE", label,
            f"OAP {overlays.oap_secteur_name or ''} : %LLS "
            f"{business.lls_quota_actual_pct:.0f}% < min OAP {overlays.oap_pct_lls_min:.0f}%",
            article_ref="L.151-6/7 CU",
            actual=business.lls_quota_actual_pct, allowed=overlays.oap_pct_lls_min,
        )
    # Densité log/ha
    if (
        overlays.oap_densite_min_log_ha is not None
        and bm.site.parcelle_surface_m2 > 0
    ):
        nb_log = sum(
            1 for niv in bm.niveaux for c in niv.cellules
            if c.type == CelluleType.LOGEMENT
        )
        densite = nb_log / (bm.site.parcelle_surface_m2 / 10_000.0)
        if densite + 1e-6 < overlays.oap_densite_min_log_ha:
            return _fail(
                "OAP_SECTORIELLE", label,
                f"OAP densité {densite:.1f} log/ha < min {overlays.oap_densite_min_log_ha:.1f} log/ha",
                article_ref="L.151-6/7 CU",
                actual=densite, allowed=overlays.oap_densite_min_log_ha,
            )
    # Voirie / schéma de principes
    if overlays.oap_obligation_voirie and overlays.oap_voirie_compliant is False:
        return _fail(
            "OAP_SECTORIELLE", label,
            f"OAP {overlays.oap_secteur_name or ''} : schéma voirie / accès non respecté",
            article_ref="L.151-6/7 CU",
        )
    return _pass("OAP_SECTORIELLE", label,
                 message=f"OAP {overlays.oap_secteur_name or ''} respectée")


def _check_abf_ac1(overlays: OverlayContext) -> ConformiteCheckItem:
    label = "AC1 — ABF avis conforme (MH 500 m)"
    if overlays.in_perimetre_ac1 is None:
        return _skip("ABF_AC1", label)
    if not overlays.in_perimetre_ac1:
        return _pass("ABF_AC1", label, message="Hors périmètre MH")
    if overlays.abf_avis_obtenu is True:
        return _pass("ABF_AC1", label, message="Avis ABF reçu",
                     article_ref="L.621-30 CP")
    return _fail(
        "ABF_AC1", label,
        "Parcelle en périmètre AC1 (Monument Historique 500 m) : "
        "avis ABF conforme REQUIS, dossier non transmis",
        article_ref="L.621-30 CP",
    )


def _check_ppri_phec(overlays: OverlayContext) -> ConformiteCheckItem:
    label = "PPRI — cote PHEC plancher RDC"
    if overlays.ppri_zone is None:
        return _skip("PPRI_PHEC", label)
    if overlays.ppri_zone == "rouge":
        return _fail(
            "PPRI_PHEC", label,
            "PPRI zone rouge : construction nouvelle interdite",
            article_ref="L.562-1 CE",
        )
    if overlays.ppri_zone == "blanc":
        return _pass("PPRI_PHEC", label, message="Hors zone PPRI")
    # Zone bleue / orange — vérifier la cote.
    if overlays.ppri_cote_phec_ngf is None or overlays.plancher_rdc_ngf is None:
        return _skip("PPRI_PHEC", label)
    seuil = overlays.ppri_cote_phec_ngf + overlays.ppri_delta_securite_m
    if overlays.plancher_rdc_ngf + 1e-6 < seuil:
        return _fail(
            "PPRI_PHEC", label,
            f"Plancher RDC {overlays.plancher_rdc_ngf:.2f} NGF "
            f"< PHEC {overlays.ppri_cote_phec_ngf:.2f} + Δ {overlays.ppri_delta_securite_m:.2f} m "
            f"= {seuil:.2f} NGF",
            article_ref="L.562-1 CE",
            actual=overlays.plancher_rdc_ngf, allowed=seuil,
        )
    return _pass("PPRI_PHEC", label,
                 actual=overlays.plancher_rdc_ngf, allowed=seuil,
                 article_ref="L.562-1 CE")


def _check_pprt(overlays: OverlayContext) -> ConformiteCheckItem:
    label = "PPRT Seveso — périmètre"
    if overlays.in_perimetre_pprt is None:
        return _skip("PPRT", label)
    if overlays.in_perimetre_pprt:
        return _fail(
            "PPRT", label,
            "Parcelle en périmètre PPRT Seveso : ERP / logement interdit "
            "ou contraint (zones expropriation / délaissement / prescription)",
            article_ref="L.515-15 CE",
        )
    return _pass("PPRT", label, message="Hors périmètre PPRT")


def _check_sru_sms(
    bm: BuildingModel, overlays: OverlayContext, business: BusinessRules,
) -> ConformiteCheckItem:
    label = "SRU / SMS L.151-15 — % LLS"
    if overlays.sms_pct_lls_min is None:
        return _skip("SRU_SMS_LLS", label)
    # Compute SDP (sum of cellules sdp_m2 if present, else fall back to envelope niveaux × emprise).
    sdp_m2 = sum(
        c.surface_sdp_m2 or c.surface_m2
        for niv in bm.niveaux
        for c in niv.cellules
    )
    if sdp_m2 <= 0:
        sdp_m2 = bm.envelope.emprise_m2 * bm.envelope.niveaux
    if overlays.sms_seuil_sdp_m2 is not None and sdp_m2 < overlays.sms_seuil_sdp_m2:
        return _pass("SRU_SMS_LLS", label,
                     message=f"SDP {sdp_m2:.0f} m² < seuil {overlays.sms_seuil_sdp_m2:.0f} m²")
    actual = business.lls_quota_actual_pct
    if actual is None:
        return _skip("SRU_SMS_LLS", label)
    if actual + 1e-6 < overlays.sms_pct_lls_min:
        return _fail(
            "SRU_SMS_LLS", label,
            f"%LLS {actual:.0f}% < min SMS {overlays.sms_pct_lls_min:.0f}% "
            f"(SDP {sdp_m2:.0f} m² ≥ seuil {overlays.sms_seuil_sdp_m2 or 0:.0f} m²)",
            article_ref="L.151-15 CU",
            actual=actual, allowed=overlays.sms_pct_lls_min,
        )
    return _pass("SRU_SMS_LLS", label,
                 actual=actual, allowed=overlays.sms_pct_lls_min,
                 article_ref="L.151-15 CU")


def _check_sup_canalisations(overlays: OverlayContext) -> ConformiteCheckItem:
    label = "SUP I1/I3 — canalisations hydrocarbures / gaz"
    if overlays.in_bande_sup_i1 is None and overlays.in_bande_sup_i3 is None:
        return _skip("SUP_I1_I3", label)
    if overlays.in_bande_sup_i1:
        return _fail(
            "SUP_I1_I3", label,
            "Parcelle dans bande SUP1 I1 (hydrocarbures) — inconstructible / ERP interdit",
            article_ref="L.555-27 CE",
        )
    if overlays.in_bande_sup_i3:
        return _fail(
            "SUP_I1_I3", label,
            "Parcelle dans bande SUP1 I3 (gaz) — inconstructible / ERP interdit",
            article_ref="L.555-27 CE",
        )
    return _pass("SUP_I1_I3", label, message="Hors bandes SUP I1/I3")


def _check_rga(overlays: OverlayContext) -> ConformiteCheckItem:
    label = "RGA — étude G2 obligatoire si aléa moyen/fort"
    if overlays.rga_niveau is None:
        return _skip("RGA", label, severity="warning")
    if overlays.rga_niveau in {"moyen", "fort"}:
        if overlays.rga_etude_g2_realisee is True:
            return _pass("RGA", label, severity="warning",
                         message=f"RGA {overlays.rga_niveau} — étude G2 réalisée",
                         article_ref="L.112-20 CCH")
        return _fail(
            "RGA", label,
            f"RGA aléa {overlays.rga_niveau} : étude géotechnique G2 "
            "obligatoire avant PC (loi ELAN 2018 + décret 22/5/2019)",
            severity="warning",
            article_ref="L.112-20 CCH",
        )
    return _pass("RGA", label, severity="warning",
                 message=f"RGA aléa {overlays.rga_niveau}")


def _check_pollution_sols(overlays: OverlayContext) -> ConformiteCheckItem:
    label = "BASIAS / BASOL / SIS — pollution sols"
    if overlays.in_basias is None and overlays.in_basol is None and overlays.in_sis is None:
        return _skip("POLLUTION_SOLS", label, severity="warning")
    # BASOL or SIS = blocking until L.556-1 attestation produced.
    if (overlays.in_basol or overlays.in_sis) and overlays.pollution_etude_l556_1_realisee is not True:
        return _fail(
            "POLLUTION_SOLS", label,
            "Site BASOL/SIS : attestation L.556-1 CE (BE certifié LNE) "
            "obligatoire avant PC",
            article_ref="L.556-1 CE",
        )
    # BASIAS = warning (étude historique recommandée).
    if overlays.in_basias and overlays.pollution_etude_l556_1_realisee is not True:
        return _fail(
            "POLLUTION_SOLS", label,
            "Site BASIAS : étude historique + diagnostic pollution recommandés",
            severity="warning",
            article_ref="L.556-1 CE",
        )
    return _pass("POLLUTION_SOLS", label, severity="warning",
                 message="Pas de pollution sols connue ou attestation L.556-1 fournie")


def _check_ebc(overlays: OverlayContext) -> ConformiteCheckItem:
    label = "EBC L.113-1 — Espace Boisé Classé"
    if overlays.in_ebc is None:
        return _skip("EBC", label)
    if overlays.in_ebc:
        return _fail(
            "EBC", label,
            "Parcelle classée EBC (L.113-1 CU) : construction interdite, "
            "défrichement prohibé",
            article_ref="L.113-1 CU",
        )
    return _pass("EBC", label, message="Hors EBC")


def _check_l151_19(overlays: OverlayContext) -> ConformiteCheckItem:
    label = "L.151-19 — Patrimoine / restrictions modification"
    if overlays.in_l151_19 is None:
        return _skip("L151_19", label, severity="warning")
    if overlays.in_l151_19 and overlays.l151_19_modification_autorisee is not True:
        return _fail(
            "L151_19", label,
            "Élément protégé L.151-19 CU : démolition / modification soumise "
            "à DP / PC + accord patrimoine",
            article_ref="L.151-19 CU",
        )
    return _pass("L151_19", label, severity="warning",
                 message="Pas d'élément L.151-19 ou autorisation reçue")


def _check_natura2000(overlays: OverlayContext) -> ConformiteCheckItem:
    label = "Natura 2000 — évaluation des incidences"
    if overlays.in_natura2000 is None:
        return _skip("NATURA2000", label)
    if overlays.in_natura2000 and overlays.natura2000_evaluation_realisee is not True:
        return _fail(
            "NATURA2000", label,
            "Parcelle en site Natura 2000 : évaluation des incidences "
            "obligatoire (art. R.414-19 CE)",
            article_ref="R.414-19 CE",
        )
    return _pass("NATURA2000", label,
                 message="Hors Natura 2000 ou évaluation réalisée")


def _check_cdpenaf(overlays: OverlayContext) -> ConformiteCheckItem:
    label = "CDPENAF — zone agricole / naturelle"
    if overlays.in_zone_a_n is None:
        return _skip("CDPENAF", label)
    if overlays.in_zone_a_n and overlays.cdpenaf_avis_favorable is not True:
        return _fail(
            "CDPENAF", label,
            "Parcelle en zone A/N : avis CDPENAF requis (favorable manquant)",
            article_ref="L.112-1-1 Code rural",
        )
    return _pass("CDPENAF", label,
                 message="Hors zone A/N ou avis CDPENAF favorable")


def _check_cdac(overlays: OverlayContext) -> ConformiteCheckItem:
    label = "CDAC — commerce > 1 000 m²"
    if overlays.commerce_surface_vente_m2 is None:
        return _skip("CDAC", label, severity="warning")
    if overlays.commerce_surface_vente_m2 > 1000.0:
        return _fail(
            "CDAC", label,
            f"Surface de vente commerce {overlays.commerce_surface_vente_m2:.0f} m² > 1 000 m² : "
            "passage CDAC obligatoire",
            severity="warning",
            article_ref="L.752-1 Code commerce",
            actual=overlays.commerce_surface_vente_m2, allowed=1000.0,
        )
    return _pass("CDAC", label, severity="warning",
                 actual=overlays.commerce_surface_vente_m2, allowed=1000.0)


def _check_re2020(overlays: OverlayContext) -> ConformiteCheckItem:
    label = "RE2020 — attestation présente"
    if overlays.re2020_attestation_presente is None:
        return _skip("RE2020", label, severity="warning")
    if not overlays.re2020_attestation_presente:
        return _fail(
            "RE2020", label,
            "Attestation RE2020 (Bbio / Cep / Ic-construction) manquante au dossier PC",
            severity="warning",
            article_ref="L.171-1 CCH",
        )
    return _pass("RE2020", label, severity="warning",
                 message="Attestation RE2020 fournie")


def _check_stationnement(
    bm: BuildingModel, overlays: OverlayContext,
) -> ConformiteCheckItem:
    label = "Stationnement PLU + PDU"
    # Case A — explicit places requested / projected (legacy code path).
    if (
        overlays.stationnement_places_requises is not None
        and overlays.stationnement_places_projet is not None
    ):
        if overlays.stationnement_places_projet + 1e-6 < overlays.stationnement_places_requises:
            return _fail(
                "STATIONNEMENT", label,
                f"Stationnement : {overlays.stationnement_places_projet:.0f} places projet "
                f"< {overlays.stationnement_places_requises:.0f} requises (PLU + PDU)",
                article_ref="L.151-30 CU + L.1214-1 CT",
                actual=overlays.stationnement_places_projet,
                allowed=overlays.stationnement_places_requises,
            )
        return _pass("STATIONNEMENT", label,
                     actual=overlays.stationnement_places_projet,
                     allowed=overlays.stationnement_places_requises,
                     article_ref="L.151-30 CU + L.1214-1 CT")
    # Case B — PDU plafond per logement (memory: feedback_plu_nogent_ua1,
    # périmètre bonne desserte RER A < 800m → max 1 pl/log). Triggered when
    # ``stationnement_pl_max_per_log`` is set and the project lists logements.
    if (
        overlays.stationnement_perimetre_bonne_desserte is True
        and overlays.stationnement_pl_max_per_log is not None
        and overlays.stationnement_places_projet is not None
    ):
        nb_log = sum(
            1 for niv in bm.niveaux for c in niv.cellules
            if c.type == CelluleType.LOGEMENT
        )
        if nb_log > 0:
            max_pl = overlays.stationnement_pl_max_per_log * nb_log
            if overlays.stationnement_places_projet > max_pl + 1e-6:
                return _fail(
                    "STATIONNEMENT", label,
                    f"Stationnement : {overlays.stationnement_places_projet:.0f} places projet "
                    f"> plafond PDU {max_pl:.1f} places "
                    f"({overlays.stationnement_pl_max_per_log:.1f}pl/log × {nb_log} logts, "
                    "périmètre bonne desserte RER)",
                    article_ref="L.151-30 CU + L.1214-1 CT",
                    actual=overlays.stationnement_places_projet, allowed=max_pl,
                )
            return _pass("STATIONNEMENT", label,
                         actual=overlays.stationnement_places_projet, allowed=max_pl,
                         article_ref="L.151-30 CU + L.1214-1 CT")
    return _skip("STATIONNEMENT", label)


def _check_hauteur_graphique(
    bm: BuildingModel, plu_rules: NumericRules, overlays: OverlayContext,
) -> ConformiteCheckItem:
    """Carte 4-4 — Hauteur graphique HG override PLU article UA.10.

    When the prescriptions particulières carte 4-4 of a PLUi sets an
    explicit *hauteur graphique* (12 / 18 / 26m, etc.) for the parcel,
    that value caps the article-10 hauteur. The project must therefore
    respect ``MIN(plu_rules.hauteur_max_m, overlays.hauteur_graphique_carte_4_4_m)``.

    See ``refs/plu/nogent_80_heros_overlays_exhaustifs.md`` (overlay #2b)
    and memory note ``feedback_plu_nogent_ua1``.
    """
    label = "Hauteur graphique carte 4-4 — PLUi"
    if overlays.hauteur_graphique_carte_4_4_m is None:
        return _skip("HAUTEUR_GRAPHIQUE", label)
    hg = overlays.hauteur_graphique_carte_4_4_m
    # Cap = min(PLU article-10, HG carte 4-4).
    plu_cap = plu_rules.hauteur_max_m if plu_rules.hauteur_max_m is not None else float("inf")
    effective_cap = min(plu_cap, hg)
    if bm.envelope.hauteur_totale_m > effective_cap + 0.05:
        return _fail(
            "HAUTEUR_GRAPHIQUE", label,
            f"Hauteur projet {bm.envelope.hauteur_totale_m:.2f} m > "
            f"MIN(PLU {plu_cap:.2f} m, HG carte 4-4 {hg:.2f} m) = {effective_cap:.2f} m",
            article_ref="Carte 4-4 PLUi PEMB / UA.10",
            actual=bm.envelope.hauteur_totale_m, allowed=effective_cap,
        )
    return _pass(
        "HAUTEUR_GRAPHIQUE", label,
        article_ref="Carte 4-4 PLUi PEMB / UA.10",
        actual=bm.envelope.hauteur_totale_m, allowed=effective_cap,
    )


def _check_r111_18(bm: BuildingModel) -> ConformiteCheckItem:
    label = "R.111-18 — chambres vue voisin ≥ 6 m"
    parcelle = _parcelle_polygon(bm)
    if parcelle is None or parcelle.is_empty:
        return _skip("R111_18", label)

    pminx, pminy, pmaxx, pmaxy = parcelle.bounds
    voirie_side = _voirie_side_of_parcelle(bm)

    def _dist_to_limites(room_poly: ShapelyPolygon) -> float:
        rminx, rminy, rmaxx, rmaxy = room_poly.bounds
        sides = {
            "ouest": rminx - pminx,
            "est": pmaxx - rmaxx,
            "sud": rminy - pminy,
            "nord": pmaxy - rmaxy,
        }
        if voirie_side in sides:
            sides.pop(voirie_side)
        return min(sides.values()) if sides else 0.0

    for niveau in bm.niveaux:
        for cell in niveau.cellules:
            if cell.type != CelluleType.LOGEMENT:
                continue
            for room in cell.rooms:
                if room.type not in _CHAMBRE_TYPES:
                    continue
                if not room.polygon_xy or len(room.polygon_xy) < 3:
                    continue
                try:
                    poly = ShapelyPolygon(room.polygon_xy)
                except Exception:
                    continue
                d = _dist_to_limites(poly)
                if d + 0.05 < R111_18_CHAMBRE_RETRAIT_MIN_M:
                    return _fail(
                        "R111_18", label,
                        f"Chambre {room.label_fr} ({cell.id}) à {d:.2f} m "
                        f"de la limite voisin < {R111_18_CHAMBRE_RETRAIT_MIN_M:.0f} m",
                        article_ref="R.111-18 CCH",
                        actual=d, allowed=R111_18_CHAMBRE_RETRAIT_MIN_M,
                        affected_element_id=room.id,
                    )
    return _pass("R111_18", label, article_ref="R.111-18 CCH")


def _check_lineaire_commercial(
    bm: BuildingModel, overlays: OverlayContext,
) -> ConformiteCheckItem:
    label = "L.151-16 — linéaire commercial RDC"
    if overlays.in_lineaire_l151_16 is None:
        return _skip("LINEAIRE_L151_16", label)
    if not overlays.in_lineaire_l151_16:
        return _pass("LINEAIRE_L151_16", label,
                     message="Parcelle hors linéaire commercial protégé")
    # On vérifie soit la valeur fournie par l'overlay, soit le RDC du projet.
    rdc_commerce_present: bool
    if overlays.rdc_commerce_present is not None:
        rdc_commerce_present = overlays.rdc_commerce_present
    else:
        rdc = next((n for n in bm.niveaux if n.index == 0), None)
        rdc_commerce_present = bool(rdc) and any(
            c.type == CelluleType.COMMERCE for c in (rdc.cellules if rdc else [])
        )
    if not rdc_commerce_present:
        return _fail(
            "LINEAIRE_L151_16", label,
            "Linéaire commercial L.151-16 : RDC doit conserver une activité "
            "commerciale (aucune cellule commerce détectée en RDC)",
            article_ref="L.151-16 CU",
        )
    return _pass("LINEAIRE_L151_16", label, article_ref="L.151-16 CU")


# ---------------------------------------------------------------------------
# Business gates
# ---------------------------------------------------------------------------


def _check_business_marge(business: BusinessRules) -> ConformiteCheckItem:
    label = "Business — marge bilan ≥ minimum bancaire"
    if business.marge_bilan_actual_pct is None:
        return _skip("BUSINESS_MARGE", label)
    if business.marge_bilan_actual_pct + 1e-6 < business.marge_bilan_min_pct:
        return _fail(
            "BUSINESS_MARGE", label,
            f"Marge bilan {business.marge_bilan_actual_pct:.2f} % "
            f"< minimum bancaire {business.marge_bilan_min_pct:.1f} % "
            "— opération non finançable",
            actual=business.marge_bilan_actual_pct,
            allowed=business.marge_bilan_min_pct,
        )
    return _pass("BUSINESS_MARGE", label,
                 actual=business.marge_bilan_actual_pct,
                 allowed=business.marge_bilan_min_pct)


def _check_business_lls(business: BusinessRules) -> ConformiteCheckItem:
    label = "Business — quota LLS commune"
    if business.lls_quota_min_pct is None:
        return _skip("BUSINESS_LLS", label)
    if business.lls_quota_actual_pct is None:
        return _skip("BUSINESS_LLS", label)
    if business.lls_quota_actual_pct + 1e-6 < business.lls_quota_min_pct:
        return _fail(
            "BUSINESS_LLS", label,
            f"Quota LLS {business.lls_quota_actual_pct:.1f} % "
            f"< minimum PLU {business.lls_quota_min_pct:.1f} %",
            actual=business.lls_quota_actual_pct,
            allowed=business.lls_quota_min_pct,
        )
    return _pass("BUSINESS_LLS", label,
                 actual=business.lls_quota_actual_pct,
                 allowed=business.lls_quota_min_pct)


def _check_business_t3plus(
    bm: BuildingModel, business: BusinessRules,
) -> ConformiteCheckItem:
    label = "Business — quota typologie T3+"
    if business.typologie_t3_plus_min_pct is None:
        return _skip("BUSINESS_T3_PLUS", label)
    t3_plus = {Typologie.T3, Typologie.T4, Typologie.T5}
    t3_count = 0
    total = 0
    for niv in bm.niveaux:
        for c in niv.cellules:
            if c.type != CelluleType.LOGEMENT:
                continue
            total += 1
            if c.typologie in t3_plus:
                t3_count += 1
    if total == 0:
        return _skip("BUSINESS_T3_PLUS", label)
    pct = 100.0 * t3_count / total
    if pct + 1e-6 < business.typologie_t3_plus_min_pct:
        return _fail(
            "BUSINESS_T3_PLUS", label,
            f"Mix T3+ : {pct:.1f} % ({t3_count}/{total} logts) "
            f"< minimum {business.typologie_t3_plus_min_pct:.1f} %",
            actual=pct,
            allowed=business.typologie_t3_plus_min_pct,
        )
    return _pass("BUSINESS_T3_PLUS", label,
                 actual=pct,
                 allowed=business.typologie_t3_plus_min_pct)


# ---------------------------------------------------------------------------
# Top-level ConformiteCheckV2
# ---------------------------------------------------------------------------


class ConformiteCheckV2(BaseModel):
    """Result of the TOP 20 + business + legacy conformite gate.

    The renderer / API / dossier-builder use ``has_blocking_errors()`` to
    refuse dispatch when any **failed** check has ``severity='blocking'``.

    ``checks`` lists every constraint individually (pass / fail / skipped)
    so the frontend dashboard can render a complete TOP 20 grid even when
    some constraints are unknown (status='skipped').

    The legacy :class:`ConformiteCheck` is preserved as ``legacy_check`` so
    existing callers can continue reading PMR / incendie / ventilation /
    lumière booleans without breaking.
    """

    checks: list[ConformiteCheckItem] = Field(default_factory=list)
    legacy_check: ConformiteCheck | None = None

    # ----- aggregations --------
    def blocking_errors(self) -> list[ConformiteCheckItem]:
        return [c for c in self.checks if c.status == "fail" and c.severity == "blocking"]

    def warnings(self) -> list[ConformiteCheckItem]:
        return [c for c in self.checks if c.status == "fail" and c.severity == "warning"]

    def has_blocking_errors(self) -> bool:
        # 1) any V2 blocking failure
        if any(self.blocking_errors()):
            return True
        # 2) legacy alerts still gate the renderer
        if self.legacy_check is not None and self.legacy_check.has_blocking_errors():
            return True
        return False

    def to_summary(self) -> dict[str, Any]:
        """JSON-friendly summary for API responses / dashboards."""
        return {
            "n_total": len(self.checks),
            "n_pass": sum(1 for c in self.checks if c.status == "pass"),
            "n_fail": sum(1 for c in self.checks if c.status == "fail"),
            "n_skipped": sum(1 for c in self.checks if c.status == "skipped"),
            "blocking": [c.model_dump() for c in self.blocking_errors()],
            "warnings": [c.model_dump() for c in self.warnings()],
        }


def validate_conformite_v2(
    bm: BuildingModel,
    plu_rules: NumericRules,
    *,
    overlays: OverlayContext | None = None,
    business_rules: BusinessRules | None = None,
) -> ConformiteCheckV2:
    """Run every TOP 20 + business + legacy check and return the consolidated
    :class:`ConformiteCheckV2`.

    Parameters
    ----------
    bm
        The :class:`BuildingModel` being designed.
    plu_rules
        Numeric PLU rules (emprise / hauteur / retraits).
    overlays
        Optional :class:`OverlayContext` carrying every urbanism flag
        fetched upstream (AC1, PPRI, EBC, …). When ``None`` (pilot mode),
        the constraint checks return ``status='skipped'``.
    business_rules
        Optional :class:`BusinessRules` carrying marge bilan / LLS /
        typologie quotas. When ``None``, defaults from the constructor
        apply.
    """
    overlays = overlays or OverlayContext()
    business = business_rules or BusinessRules()

    checks: list[ConformiteCheckItem] = []

    # 1 — 3   PLU réglement
    checks.append(_check_plu_emprise(bm, plu_rules))
    checks.append(_check_plu_hauteur(bm, plu_rules))
    checks.append(_check_plu_retraits(bm, plu_rules))

    # 4       OAP sectorielle
    checks.append(_check_oap_sectorielle(bm, overlays, business))

    # 5       AC1 ABF
    checks.append(_check_abf_ac1(overlays))

    # 6       PPRI cote PHEC
    checks.append(_check_ppri_phec(overlays))

    # 7       PPRT Seveso
    checks.append(_check_pprt(overlays))

    # 8       SRU SMS L.151-15
    checks.append(_check_sru_sms(bm, overlays, business))

    # 9       SUP I1/I3
    checks.append(_check_sup_canalisations(overlays))

    # 10      RGA
    checks.append(_check_rga(overlays))

    # 11      BASIAS / BASOL / SIS
    checks.append(_check_pollution_sols(overlays))

    # 12      EBC
    checks.append(_check_ebc(overlays))

    # 13      L.151-19
    checks.append(_check_l151_19(overlays))

    # 14      Natura 2000
    checks.append(_check_natura2000(overlays))

    # 15      CDPENAF
    checks.append(_check_cdpenaf(overlays))

    # 16      CDAC commerce
    checks.append(_check_cdac(overlays))

    # 17      RE2020
    checks.append(_check_re2020(overlays))

    # 18      Stationnement
    checks.append(_check_stationnement(bm, overlays))

    # 19      R.111-18 chambres
    checks.append(_check_r111_18(bm))

    # 20      L.151-16 linéaire commercial
    checks.append(_check_lineaire_commercial(bm, overlays))

    # 24      Hauteur graphique carte 4-4 (PLUi override UA.10)
    checks.append(_check_hauteur_graphique(bm, plu_rules, overlays))

    # 21-23   Business (marge, LLS, T3+)
    checks.append(_check_business_marge(business))
    checks.append(_check_business_lls(business))
    checks.append(_check_business_t3plus(bm, business))

    # Legacy validator (PMR / incendie / ventilation / lumière) — kept
    # alongside so V2 stays a true superset.
    from core.building_model._validator_legacy import validate_all as _legacy_all
    legacy = _legacy_all(bm, plu_rules)

    return ConformiteCheckV2(checks=checks, legacy_check=legacy)


__all__ = [
    "ConformiteCheckItem",
    "ConformiteCheckV2",
    "OverlayContext",
    "validate_conformite_v2",
]
