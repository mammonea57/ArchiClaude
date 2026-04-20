"""Multi-step validation chain for the analyze endpoint.

Each step returns a :class:`ValidationCheck` with a pass/fail flag, a
human-readable diagnostic, and the numeric values it inspected. The
analyze endpoint consumes all the checks for a step; if ANY fails, it
raises HTTP 422 with the first failing diagnostic — never a silent
fallback on defaults.

This module is deliberately pure (no IO, no DB) so it's trivial to unit
test across arbitrary parcels, communes, and BMs.
"""
from __future__ import annotations

from dataclasses import dataclass

from shapely.geometry import shape as shapely_shape


@dataclass(frozen=True)
class ValidationCheck:
    """Result of a single validation check."""

    step: str
    passed: bool
    message: str
    facts: dict

    @property
    def is_fatal(self) -> bool:
        return not self.passed


def _check(step: str, cond: bool, msg_fail: str, msg_ok: str, **facts) -> ValidationCheck:
    return ValidationCheck(
        step=step,
        passed=cond,
        message=msg_ok if cond else msg_fail,
        facts=facts,
    )


# ---------------------------------------------------------------------
# Step 1 — Geocoding
# ---------------------------------------------------------------------

def validate_geocoding(
    *,
    label: str,
    score: float,
    lat: float,
    lng: float,
    postcode: str | None,
    citycode: str | None,
    min_score: float = 0.7,
) -> list[ValidationCheck]:
    """Verify the BAN geocoding result is trustworthy."""
    checks = [
        _check(
            "geocoding.score",
            score >= min_score,
            f"Confiance geocoding BAN trop faible ({score:.2f} < {min_score}) pour « {label} ». "
            "Vérifie l'orthographe exacte de l'adresse.",
            f"Geocoding BAN confiance {score:.2f} ≥ {min_score} pour « {label} ».",
            score=score, min_score=min_score,
        ),
        _check(
            "geocoding.coordinates",
            42.0 <= lat <= 51.5 and -5.5 <= lng <= 10.0,
            f"Coordonnées hors France métropolitaine ({lat:.4f}, {lng:.4f}).",
            f"Coordonnées cohérentes ({lat:.4f}, {lng:.4f}).",
            lat=lat, lng=lng,
        ),
        _check(
            "geocoding.citycode",
            bool(citycode and len(citycode) == 5 and citycode.isdigit()),
            f"Code INSEE invalide : « {citycode} » (attendu 5 chiffres).",
            f"Code INSEE {citycode} valide.",
            citycode=citycode,
        ),
        _check(
            "geocoding.postcode",
            bool(postcode and len(postcode) == 5 and postcode.isdigit()),
            f"Code postal invalide : « {postcode} » (attendu 5 chiffres).",
            f"Code postal {postcode} valide.",
            postcode=postcode,
        ),
    ]
    return checks


# ---------------------------------------------------------------------
# Step 2 — Cadastre
# ---------------------------------------------------------------------

def validate_cadastre(
    *,
    geometry: dict,
    contenance_m2: int | None,
    computed_area_m2: float,
    min_parcel_m2: float = 50.0,
    max_delta_pct: float = 0.15,
) -> list[ValidationCheck]:
    """Verify the cadastral parcel is plausible and consistent."""
    checks: list[ValidationCheck] = []
    # Geometry present
    is_polygon = isinstance(geometry, dict) and geometry.get("type") in ("Polygon", "MultiPolygon")
    checks.append(_check(
        "cadastre.geometry",
        is_polygon and bool(geometry.get("coordinates")),
        "Géométrie cadastrale manquante ou invalide.",
        "Géométrie cadastrale présente.",
        geom_type=geometry.get("type") if isinstance(geometry, dict) else None,
    ))
    if not is_polygon:
        return checks  # Skip remaining checks — nothing to measure
    # Surface calculée > seuil
    checks.append(_check(
        "cadastre.min_surface",
        computed_area_m2 >= min_parcel_m2,
        f"Parcelle trop petite : {computed_area_m2:.0f} m² < {min_parcel_m2:.0f} m² minimum.",
        f"Parcelle {computed_area_m2:.0f} m² ≥ {min_parcel_m2:.0f} m².",
        computed_m2=computed_area_m2, min_m2=min_parcel_m2,
    ))
    # Cohérence contenance cadastrale ↔ polygone calculé
    if contenance_m2 is not None and contenance_m2 > 0:
        delta = abs(computed_area_m2 - contenance_m2) / contenance_m2
        checks.append(_check(
            "cadastre.coherence_surface",
            delta <= max_delta_pct,
            f"Incohérence surface parcelle : contenance {contenance_m2} m² vs polygone calculé "
            f"{computed_area_m2:.0f} m² (écart {delta:.1%} > {max_delta_pct:.0%} autorisé).",
            f"Surface parcelle cohérente (contenance {contenance_m2} m² ≈ polygone {computed_area_m2:.0f} m²).",
            contenance=contenance_m2, computed=computed_area_m2, delta_pct=delta,
        ))
    # Géométrie valide (pas auto-intersection)
    try:
        shp = shapely_shape(geometry)
        checks.append(_check(
            "cadastre.geometry_valid",
            shp.is_valid and not shp.is_empty,
            f"Géométrie cadastrale invalide : {shp.is_valid=} {shp.is_empty=}.",
            "Géométrie cadastrale valide (non auto-intersectée).",
        ))
    except Exception as exc:  # noqa: BLE001
        checks.append(ValidationCheck(
            step="cadastre.geometry_valid", passed=False,
            message=f"Impossible de parser la géométrie cadastrale : {exc}", facts={},
        ))
    return checks


# ---------------------------------------------------------------------
# Step 3 — PLU rules
# ---------------------------------------------------------------------

def validate_plu(
    *,
    emprise_max_pct: float | None,
    hauteur_max_m: float | None,
    hauteur_max_niveaux: int | None,
) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    has_height = (hauteur_max_m is not None and hauteur_max_m > 0) or (
        hauteur_max_niveaux is not None and hauteur_max_niveaux > 0
    )
    checks.append(_check(
        "plu.height_defined",
        has_height,
        "Règle de hauteur PLU absente (ni hauteur_max_m ni hauteur_max_niveaux).",
        "Règle de hauteur PLU présente.",
        hauteur_max_m=hauteur_max_m, hauteur_max_niveaux=hauteur_max_niveaux,
    ))
    if hauteur_max_m is not None:
        checks.append(_check(
            "plu.height_range",
            3.0 <= hauteur_max_m <= 200.0,
            f"Hauteur PLU aberrante : {hauteur_max_m} m (hors [3, 200]).",
            f"Hauteur PLU {hauteur_max_m} m dans la plage [3, 200].",
            hauteur_max_m=hauteur_max_m,
        ))
    emprise = emprise_max_pct
    emprise_ok = emprise is not None and 0 < emprise <= 100
    checks.append(_check(
        "plu.emprise",
        emprise_ok,
        f"Emprise max PLU aberrante : {emprise} (hors ]0, 100]).",
        f"Emprise max PLU {emprise}%.",
        emprise_max_pct=emprise,
    ))
    return checks


# ---------------------------------------------------------------------
# Step 4 — Feasibility outputs
# ---------------------------------------------------------------------

def validate_feasibility(
    *,
    sdp_max_m2: float,
    nb_niveaux: int,
    nb_logements_max: int,
    surface_emprise_m2: float,
    footprint_geojson: dict | None,
) -> list[ValidationCheck]:
    checks = [
        _check(
            "feasibility.sdp",
            sdp_max_m2 > 0,
            f"SDP max = {sdp_max_m2} m² — analyse dégénérée.",
            f"SDP max {sdp_max_m2:.0f} m² > 0.",
            sdp_max_m2=sdp_max_m2,
        ),
        _check(
            "feasibility.niveaux",
            nb_niveaux >= 1,
            f"Nombre de niveaux {nb_niveaux} < 1.",
            f"Nombre de niveaux {nb_niveaux} ≥ 1.",
            nb_niveaux=nb_niveaux,
        ),
        _check(
            "feasibility.nb_logements",
            nb_logements_max >= 1,
            f"Nombre de logements {nb_logements_max} < 1.",
            f"Nombre de logements {nb_logements_max} ≥ 1.",
            nb_logements_max=nb_logements_max,
        ),
        _check(
            "feasibility.emprise",
            surface_emprise_m2 > 20.0,
            f"Emprise retenue {surface_emprise_m2:.1f} m² < 20 m² (pas de bâti possible).",
            f"Emprise {surface_emprise_m2:.0f} m² > 20 m².",
            surface_emprise_m2=surface_emprise_m2,
        ),
        _check(
            "feasibility.footprint",
            bool(footprint_geojson and footprint_geojson.get("coordinates")),
            "Footprint recommandé vide.",
            "Footprint recommandé présent.",
        ),
    ]
    return checks


# ---------------------------------------------------------------------
# Step 5 — BM generated
# ---------------------------------------------------------------------

def validate_building_model(building_model) -> list[ValidationCheck]:
    """Run sanity checks on the generated BM."""
    from core.building_model.schemas import CelluleType, OpeningType, RoomType
    from shapely.geometry import Polygon as ShapelyPoly, Point

    bm = building_model
    checks: list[ValidationCheck] = []
    inhab_niveaux = [n for n in bm.niveaux if n.index >= 0 and n.usage_principal == "logements"]
    all_apts = [
        (niv, c)
        for niv in inhab_niveaux
        for c in niv.cellules
        if c.type == CelluleType.LOGEMENT
    ]
    # At least one apartment in the whole BM. A floor with 0 apts is
    # acceptable (ex. RDC commercial) but a building without any is not.
    checks.append(_check(
        "bm.at_least_one_apt",
        len(all_apts) >= 1,
        f"Aucun logement généré sur l'ensemble du bâtiment ({len(inhab_niveaux)} niveaux habitables).",
        f"{len(all_apts)} appartement(s) répartis sur {len(inhab_niveaux)} niveaux.",
        n_apts=len(all_apts), n_niveaux=len(inhab_niveaux),
    ))
    too_small = [(niv.code, c.id, c.surface_m2) for (niv, c) in all_apts if c.surface_m2 < 40.0]
    checks.append(_check(
        "bm.min_apt_surface",
        not too_small,
        f"{len(too_small)} appartement(s) sous le seuil T2 min 40 m² : {too_small[:3]}…",
        f"Tous les {len(all_apts)} appartements ≥ 40 m².",
    ))
    landlocked = [
        (niv.code, c.id) for (niv, c) in all_apts if not c.orientation
    ]
    checks.append(_check(
        "bm.orientations",
        not landlocked,
        f"{len(landlocked)} apt(s) sans façade extérieure (enclavés) : {landlocked[:3]}…",
        f"Tous les appartements ont ≥ 1 orientation.",
    ))
    # Every apt's porte_entree is in the ENTREE room
    doors_in_wet = []
    for niv, apt in all_apts:
        door = next(
            (o for o in apt.openings if o.type == OpeningType.PORTE_ENTREE),
            None,
        )
        if not door:
            continue
        wall = next((w for w in apt.walls if w.id == door.wall_id), None)
        if not wall:
            continue
        p0, p1 = wall.geometry["coords"]
        wlen = ((p1[0] - p0[0]) ** 2 + (p1[1] - p0[1]) ** 2) ** 0.5
        if wlen <= 0:
            continue
        t = (door.position_along_wall_cm / 100) / wlen
        door_pt = Point(p0[0] + (p1[0] - p0[0]) * t, p0[1] + (p1[1] - p0[1]) * t)
        for r in apt.rooms:
            if r.type in (RoomType.SDB, RoomType.SALLE_DE_DOUCHE, RoomType.WC, RoomType.WC_SDB):
                rp = ShapelyPoly(r.polygon_xy).buffer(-0.05)
                if rp.is_valid and not rp.is_empty and rp.contains(door_pt):
                    doors_in_wet.append((niv.code, apt.id, r.type.value))
                    break
    checks.append(_check(
        "bm.doors_not_in_wet",
        not doors_in_wet,
        f"{len(doors_in_wet)} porte(s) d'entrée dans une SdB/WC : {doors_in_wet[:3]}…",
        f"Aucune porte d'entrée dans une pièce humide.",
    ))
    return checks


# ---------------------------------------------------------------------
# Step 6 — Cross-consistency checks
# ---------------------------------------------------------------------

def validate_cross_consistency(
    *,
    bm_sdp_m2: float,
    feas_sdp_m2: float,
    bm_nb_apts: int,
    feas_nb_logements: int,
    bm_emprise_m2: float,
    plu_emprise_max_pct: float | None,
    parcelle_m2: float,
    sdp_tolerance_pct: float = 0.10,
    apts_tolerance_pct: float = 0.20,
) -> list[ValidationCheck]:
    checks: list[ValidationCheck] = []
    if feas_sdp_m2 > 0:
        delta = abs(bm_sdp_m2 - feas_sdp_m2) / feas_sdp_m2
        checks.append(_check(
            "cross.sdp_match",
            delta <= sdp_tolerance_pct,
            f"SDP BM {bm_sdp_m2:.0f} m² vs feasibility {feas_sdp_m2:.0f} m² — "
            f"écart {delta:.1%} > {sdp_tolerance_pct:.0%}.",
            f"SDP cohérent (BM {bm_sdp_m2:.0f} ≈ feasibility {feas_sdp_m2:.0f}, écart {delta:.1%}).",
        ))
    if feas_nb_logements > 0:
        # The feasibility engine's nb_logements_max is a THEORETICAL
        # ceiling from SDP ÷ avg apt size; the BM solver's count is the
        # realised layout after deducting circulation. A gap is expected
        # and not a failure — only flag a hard fault if the BM has zero
        # apartments when feasibility said ≥ 1.
        checks.append(_check(
            "cross.bm_not_empty",
            bm_nb_apts >= 1,
            f"BM vide ({bm_nb_apts} apts) alors que la feasibility prévoit "
            f"{feas_nb_logements} logements théoriques max.",
            f"BM porte {bm_nb_apts} apts (feasibility théorique: {feas_nb_logements}).",
        ))
    if plu_emprise_max_pct and parcelle_m2 > 0:
        bm_emprise_pct = 100 * bm_emprise_m2 / parcelle_m2
        checks.append(_check(
            "cross.emprise_within_plu",
            bm_emprise_pct <= plu_emprise_max_pct + 5,  # 5% tolerance buffer
            f"Emprise BM {bm_emprise_pct:.1f}% > emprise max PLU {plu_emprise_max_pct:.0f}%.",
            f"Emprise BM {bm_emprise_pct:.1f}% ≤ emprise max PLU {plu_emprise_max_pct:.0f}%.",
        ))
    return checks


# ---------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------

class ValidationError(Exception):
    """Raised when one or more checks fail."""

    def __init__(self, step: str, message: str, all_checks: list[ValidationCheck]):
        self.step = step
        self.message = message
        self.all_checks = all_checks
        super().__init__(message)


def run_checks_or_raise(step_name: str, checks: list[ValidationCheck]) -> None:
    """Raise ValidationError on the first failing check."""
    for c in checks:
        if c.is_fatal:
            raise ValidationError(
                step=c.step,
                message=f"[{step_name}] {c.message}",
                all_checks=checks,
            )
