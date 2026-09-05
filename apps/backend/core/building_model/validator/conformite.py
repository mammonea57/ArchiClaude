"""Pre-render conformite gate for BuildingModel.

Checks the BuildingModel against:
  - PLU rules  (NumericRules: emprise, hauteur, niveaux, retraits voirie/lat/fond)
  - R.111-18    (chambres vue voisins ≥ 6 m — see feedback_r111_18_vue_voisins)
  - Business    (marge bilan ≥ 12 %, LLS quota ≥ 30 % Nogent, T3+ mix)

This validator is the LAST gate before render. The render pipeline must
refuse to dispatch when ``ConformiteCheck.has_blocking_errors()`` is True
— investors and banks rely on visual output reflecting a legally /
financially viable project (see memory: project_precision_requirement,
bilan_marge_cible).

Returns a :class:`ConformiteCheck` with:
  - ``errors``   blocking violations (HTTP 422 detail content)
  - ``warnings`` non-blocking (cosmetic / advisory)
  - ``alerts``   merged for backwards-compat with the legacy validator

The legacy ``validate_all`` (PMR / incendie / ventilation / lumière) is
RE-RUN inside ``validate_conformite`` so the resulting ConformiteCheck is
a single source of truth the API and frontend can consume.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from shapely.geometry import Polygon as ShapelyPolygon
from shapely.geometry import shape as _shape

from core.building_model.schemas import (
    BuildingModel,
    Cellule,
    CelluleType,
    ConformiteAlert,
    ConformiteCheck,
    RoomType,
    Typologie,
)
from core.plu.schemas import NumericRules


# --- Hard banking + PLU constants (see project memory) -------------------

# Marge bilan minimale exigée par toutes les banques pour financer une
# opération de promotion immobilière (memory: bilan_marge_cible).
BANK_MIN_MARGE_HT_PCT = 12.0

# Quota LLS minimum imposé par les PLU communaux ciblés. Nogent-sur-Marne
# = 30 % (memory: feedback_plu_typology_mix_rules + feedback_plu_nogent_ua1).
_COMMUNE_LLS_QUOTA_PCT: dict[str, float] = {
    "nogent-sur-marne": 30.0,
}

# Quota T3+ par commune (% des logements ≥ T3). Cf.
# feedback_plu_typology_mix_rules. Stocké ici pour le pilote ; à terme
# ce mapping viendra du PLU parsé en base.
_COMMUNE_T3PLUS_QUOTA_PCT: dict[str, float] = {
    "nogent-sur-marne": 40.0,
}

# R.111-18 : distance min 6 m entre chambres « vue directe » et limite
# voisin (memory: feedback_r111_18_vue_voisins).
R111_18_CHAMBRE_RETRAIT_MIN_M = 6.0

_CHAMBRE_TYPES = {
    RoomType.CHAMBRE_PARENTS,
    RoomType.CHAMBRE_ENFANT,
    RoomType.CHAMBRE_SUPP,
}


# --- BusinessRules input schema ------------------------------------------

@dataclass
class BusinessRules:
    """Project-level business / commercial constraints to check.

    Defaults mirror the hardest constraint applicable to every project
    (12 % marge HT is a banking floor). LLS / typologie quotas default to
    ``None`` so non-Nogent projects don't fail by accident; the API
    layer resolves the right values from the project commune / PLU.
    """

    # Marge HT minimum (%). Hard. Below → opération non finançable.
    marge_bilan_min_pct: float = BANK_MIN_MARGE_HT_PCT
    # Achieved marge HT for the current project (%). When None, the gate
    # is skipped (the bilan module hasn't been run yet).
    marge_bilan_actual_pct: float | None = None

    # LLS quota minimum (%). When set, the share of social SHAB must
    # be ≥ this value. Resolved from the project commune by the caller.
    lls_quota_min_pct: float | None = None
    # Achieved LLS share (% of SHAB). None → unchecked (no bilan run yet).
    lls_quota_actual_pct: float | None = None

    # Typologie mix obligation: minimum share (%) of dwellings whose
    # typologie is ≥ T3. Resolved per-commune.
    typologie_t3_plus_min_pct: float | None = None

    @classmethod
    def for_commune(
        cls,
        commune: str | None,
        *,
        marge_actual_pct: float | None = None,
        lls_actual_pct: float | None = None,
    ) -> "BusinessRules":
        """Build a BusinessRules instance pre-populated with the
        commune's local quotas (LLS / typologie). Hard constants
        (12 % marge) always apply.
        """
        key = (commune or "").strip().lower()
        return cls(
            marge_bilan_min_pct=BANK_MIN_MARGE_HT_PCT,
            marge_bilan_actual_pct=marge_actual_pct,
            lls_quota_min_pct=_COMMUNE_LLS_QUOTA_PCT.get(key),
            lls_quota_actual_pct=lls_actual_pct,
            typologie_t3_plus_min_pct=_COMMUNE_T3PLUS_QUOTA_PCT.get(key),
        )


# --- PLU geometry helpers -------------------------------------------------

def _footprint_polygon(bm: BuildingModel) -> ShapelyPolygon | None:
    try:
        return _shape(bm.envelope.footprint_geojson)  # type: ignore[return-value]
    except Exception:
        return None


def _parcelle_polygon(bm: BuildingModel) -> ShapelyPolygon | None:
    try:
        return _shape(bm.site.parcelle_geojson)  # type: ignore[return-value]
    except Exception:
        return None


def _voirie_side_of_parcelle(bm: BuildingModel) -> str | None:
    if not bm.site.voirie_orientations:
        return None
    return bm.site.voirie_orientations[0]


def _check_retrait_voirie(
    footprint: ShapelyPolygon,
    parcelle: ShapelyPolygon,
    voirie_side: str,
    min_recul_m: float,
) -> float | None:
    """Return the measured retrait from the voirie edge of the parcelle.

    The voirie edge is identified by the side of the parcelle's bbox
    matching ``voirie_side``. Returns the perpendicular distance from
    that edge to the closest footprint vertex.
    """
    pminx, pminy, pmaxx, pmaxy = parcelle.bounds
    fminx, fminy, fmaxx, fmaxy = footprint.bounds
    if voirie_side == "sud":
        return fminy - pminy
    if voirie_side == "nord":
        return pmaxy - fmaxy
    if voirie_side == "ouest":
        return fminx - pminx
    if voirie_side == "est":
        return pmaxx - fmaxx
    return None


def _check_retrait_lateral_and_fond(
    footprint: ShapelyPolygon,
    parcelle: ShapelyPolygon,
    voirie_side: str | None,
) -> tuple[float, float]:
    """Return (min_retrait_lateral_m, retrait_fond_m).

    Lateral = the two sides perpendicular to the voirie axis.
    Fond     = the side opposite to voirie.
    """
    pminx, pminy, pmaxx, pmaxy = parcelle.bounds
    fminx, fminy, fmaxx, fmaxy = footprint.bounds
    # Default: assume voirie south
    side = voirie_side or "sud"
    if side in ("sud", "nord"):
        lat = min(fminx - pminx, pmaxx - fmaxx)
        fond = (pmaxy - fmaxy) if side == "sud" else (fminy - pminy)
    else:
        lat = min(fminy - pminy, pmaxy - fmaxy)
        fond = (pmaxx - fmaxx) if side == "ouest" else (fminx - pminx)
    return lat, fond


# --- PLU validation -------------------------------------------------------

def _validate_plu(
    bm: BuildingModel, rules: NumericRules,
) -> list[ConformiteAlert]:
    errors: list[ConformiteAlert] = []

    # 1. Emprise
    if rules.emprise_max_pct is not None and bm.site.parcelle_surface_m2:
        emprise_max_m2 = (
            bm.site.parcelle_surface_m2 * rules.emprise_max_pct / 100.0
        )
        if bm.envelope.emprise_m2 > emprise_max_m2 + 0.5:
            errors.append(ConformiteAlert(
                level="error", category="plu",
                message=(
                    f"PLU emprise {bm.envelope.emprise_m2:.1f} m² "
                    f"> max {emprise_max_m2:.1f} m² "
                    f"({rules.emprise_max_pct:.0f} % de la parcelle)"
                ),
            ))

    # 2. Hauteur (m)
    if rules.hauteur_max_m is not None and bm.envelope.hauteur_totale_m > rules.hauteur_max_m + 0.05:
        errors.append(ConformiteAlert(
            level="error", category="plu",
            message=(
                f"PLU hauteur {bm.envelope.hauteur_totale_m:.2f} m "
                f"> max {rules.hauteur_max_m:.2f} m"
            ),
        ))

    # 3. Niveaux (R+N)
    if rules.hauteur_max_niveaux is not None:
        r_plus = bm.envelope.niveaux - 1
        if r_plus > rules.hauteur_max_niveaux:
            errors.append(ConformiteAlert(
                level="error", category="plu",
                message=(
                    f"PLU niveaux R+{r_plus} > max R+{rules.hauteur_max_niveaux}"
                ),
            ))

    # 4. Retraits — only checkable when both footprint and parcelle are
    # available and rectangular-ish (the bbox approximation suffices for
    # the gate; precise polygon-distance checks live in the geometry
    # solver).
    footprint = _footprint_polygon(bm)
    parcelle = _parcelle_polygon(bm)
    if footprint is not None and parcelle is not None and not footprint.is_empty:
        voirie_side = _voirie_side_of_parcelle(bm)
        if rules.recul_voirie_m is not None and voirie_side is not None:
            actual = _check_retrait_voirie(footprint, parcelle, voirie_side, rules.recul_voirie_m)
            if actual is not None and actual + 0.05 < rules.recul_voirie_m:
                errors.append(ConformiteAlert(
                    level="error", category="plu",
                    message=(
                        f"PLU recul voirie {actual:.2f} m "
                        f"< min {rules.recul_voirie_m:.2f} m"
                    ),
                ))
        if (
            rules.recul_limite_lat_m is not None
            or rules.recul_fond_m is not None
        ):
            lat, fond = _check_retrait_lateral_and_fond(footprint, parcelle, voirie_side)
            if rules.recul_limite_lat_m is not None and lat + 0.05 < rules.recul_limite_lat_m:
                errors.append(ConformiteAlert(
                    level="error", category="plu",
                    message=(
                        f"PLU recul limite latérale {lat:.2f} m "
                        f"< min {rules.recul_limite_lat_m:.2f} m"
                    ),
                ))
            if rules.recul_fond_m is not None and fond + 0.05 < rules.recul_fond_m:
                errors.append(ConformiteAlert(
                    level="error", category="plu",
                    message=(
                        f"PLU recul fond {fond:.2f} m "
                        f"< min {rules.recul_fond_m:.2f} m"
                    ),
                ))

    return errors


# --- R.111-18 (chambres vue voisins ≥ 6 m) -------------------------------

def _validate_r111_18(
    bm: BuildingModel,
) -> list[ConformiteAlert]:
    """Check every chambre with a window facing a side has retrait ≥ 6 m
    from the closest parcelle boundary on that side.

    The per-window orientation check requires full building-model
    semantics (which wall a window is on, then which parcelle limit that
    wall faces). For the gate we approximate: a chambre whose room
    polygon lies within 6 m of any lateral or fond limite is flagged.

    TODO: tighten to per-window check once Cellule walls / openings
    metadata exposes "facing limite voisin" per side. See memory note
    feedback_r111_18_vue_voisins.
    """
    errors: list[ConformiteAlert] = []
    parcelle = _parcelle_polygon(bm)
    if parcelle is None or parcelle.is_empty:
        return errors

    pminx, pminy, pmaxx, pmaxy = parcelle.bounds
    voirie_side = _voirie_side_of_parcelle(bm)

    # "Limites voisins" = the three parcelle sides NOT facing the voirie.
    def _dist_to_limites(room_poly: ShapelyPolygon) -> float:
        rminx, rminy, rmaxx, rmaxy = room_poly.bounds
        d_west = rminx - pminx
        d_east = pmaxx - rmaxx
        d_south = rminy - pminy
        d_north = pmaxy - rmaxy
        sides = {
            "ouest": d_west, "est": d_east,
            "sud": d_south, "nord": d_north,
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
                    errors.append(ConformiteAlert(
                        level="error", category="r111_18",
                        message=(
                            f"R.111-18 : chambre {room.label_fr} "
                            f"({cell.id}) à {d:.2f} m de la limite voisin "
                            f"< {R111_18_CHAMBRE_RETRAIT_MIN_M:.0f} m"
                        ),
                        affected_element_id=room.id,
                    ))
    return errors


# --- Business rules ------------------------------------------------------

def _validate_business(
    bm: BuildingModel, business: BusinessRules,
) -> list[ConformiteAlert]:
    errors: list[ConformiteAlert] = []

    # Marge bilan
    if business.marge_bilan_actual_pct is not None:
        if business.marge_bilan_actual_pct + 1e-6 < business.marge_bilan_min_pct:
            errors.append(ConformiteAlert(
                level="error", category="business",
                message=(
                    f"Marge bilan {business.marge_bilan_actual_pct:.2f} % "
                    f"< minimum bancaire {business.marge_bilan_min_pct:.1f} % "
                    "— opération non finançable"
                ),
            ))

    # LLS quota
    if (
        business.lls_quota_min_pct is not None
        and business.lls_quota_actual_pct is not None
        and business.lls_quota_actual_pct + 1e-6 < business.lls_quota_min_pct
    ):
        errors.append(ConformiteAlert(
            level="error", category="business",
            message=(
                f"Quota LLS {business.lls_quota_actual_pct:.1f} % "
                f"< minimum PLU {business.lls_quota_min_pct:.1f} %"
            ),
        ))

    # Typologie T3+
    if business.typologie_t3_plus_min_pct is not None:
        t3_plus_count = 0
        total_logements = 0
        t3_plus = {Typologie.T3, Typologie.T4, Typologie.T5}
        for niveau in bm.niveaux:
            for cell in niveau.cellules:
                if cell.type != CelluleType.LOGEMENT:
                    continue
                total_logements += 1
                if cell.typologie in t3_plus:
                    t3_plus_count += 1
        if total_logements > 0:
            pct = (t3_plus_count / total_logements) * 100.0
            if pct + 1e-6 < business.typologie_t3_plus_min_pct:
                errors.append(ConformiteAlert(
                    level="error", category="typologie",
                    message=(
                        f"Mix typologie : T3+ {pct:.1f} % "
                        f"({t3_plus_count}/{total_logements} logts) "
                        f"< minimum {business.typologie_t3_plus_min_pct:.1f} %"
                    ),
                ))

    return errors


# --- Top-level entry point ----------------------------------------------

def validate_conformite(
    bm: BuildingModel,
    plu_rules: NumericRules,
    business_rules: BusinessRules | None = None,
) -> ConformiteCheck:
    """Run the full pre-render conformite check.

    Aggregates the legacy validators (PMR/incendie/ventilation/lumière)
    AND the new PLU/R.111-18/business gates into a single
    ``ConformiteCheck`` whose ``has_blocking_errors()`` controls the
    render gate.
    """
    business_rules = business_rules or BusinessRules()

    # Re-run the legacy validators (they emit into ``alerts``) so the
    # resulting check carries every signal the frontend already knows
    # how to render.
    from core.building_model._validator_legacy import validate_all as _legacy_all
    legacy = _legacy_all(bm, plu_rules)

    plu_errors = _validate_plu(bm, plu_rules)
    r111_18_errors = _validate_r111_18(bm)
    business_errors = _validate_business(bm, business_rules)

    # Build categorised booleans (True = no blocking error in that bucket).
    def _no_err(cat: str, alerts: Iterable[ConformiteAlert]) -> bool:
        return not any(a.category == cat and a.level == "error" for a in alerts)

    all_errors = plu_errors + r111_18_errors + business_errors

    # Categorise PLU retraits separately (sub-message marker "recul").
    plu_retraits_ok = not any(
        a.category == "plu" and a.level == "error" and "recul" in a.message.lower()
        for a in plu_errors
    )

    check = ConformiteCheck(
        # Carry over the legacy booleans as-is.
        pmr_ascenseur_ok=legacy.pmr_ascenseur_ok,
        pmr_rotation_cercles_ok=legacy.pmr_rotation_cercles_ok,
        incendie_distance_sorties_ok=legacy.incendie_distance_sorties_ok,
        ventilation_ok=legacy.ventilation_ok,
        lumiere_ok=legacy.lumiere_ok,
        # PLU split: emprise/hauteur from this gate (more precise), retraits new.
        plu_emprise_ok=_no_err("plu", [a for a in plu_errors if "emprise" in a.message.lower()]),
        plu_hauteur_ok=_no_err("plu", [a for a in plu_errors if "hauteur" in a.message.lower() or "niveaux" in a.message.lower()]),
        plu_retraits_ok=plu_retraits_ok,
        # Business gates
        business_marge_ok=not any(a.category == "business" and "marge" in a.message.lower() for a in business_errors),
        business_lls_quota_ok=not any(a.category == "business" and "lls" in a.message.lower() for a in business_errors),
        business_typologie_ok=_no_err("typologie", business_errors),
        r111_18_chambres_ok=not any(a.category == "r111_18" for a in r111_18_errors),
        # Keep the legacy alerts (downstream UI still reads them) AND
        # publish the new ones for the renderer/API.
        alerts=list(legacy.alerts),
        errors=list(all_errors),
        warnings=[],  # reserved for non-blocking future signals
    )
    return check
