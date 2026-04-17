"""Capacity calculation — SDP, niveaux, logements, stationnement.

All surface values are indicative and pending calibration against real projects.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SURFACE_PAR_TYPOLOGIE_M2: dict[str, float] = {
    "T1": 30.0,
    "T2": 45.0,
    "T3": 65.0,
    "T4": 82.0,
    "T5": 105.0,
}

_HAUTEUR_PAR_NIVEAU_M: float = 3.0
_EPAISSEUR_PLANCHER_M: float = 0.5

_WARNING_INDICATIF = (
    "Coefficients brute→utile non appliqués — valeurs indicatives à valider"
)


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CapacityResult:
    """Immutable result of the capacity pipeline."""

    hauteur_retenue_m: float
    nb_niveaux: int
    sdp_max_m2: float
    nb_logements_max: int
    nb_par_typologie: dict[str, int]
    nb_places_stationnement: int
    nb_places_pmr: int
    warnings: list[str]


# ---------------------------------------------------------------------------
# Step functions
# ---------------------------------------------------------------------------


def compute_hauteur_retenue(
    *,
    hauteur_max_m: float | None,
    niveaux_max: int | None,
    altitude_sol_m: float | None,
    hauteur_max_ngf: float | None,
) -> float:
    """Return the binding height constraint in metres.

    Takes the minimum of:
    - hauteur_max_m (absolute height limit from PLU)
    - niveaux_max * _HAUTEUR_PAR_NIVEAU_M + _EPAISSEUR_PLANCHER_M (niveau-based limit)
    - hauteur_max_ngf - altitude_sol_m (NGF altitude limit, when both provided)

    Returns math.inf when no constraint is provided.
    """
    candidates: list[float] = []

    if hauteur_max_m is not None:
        candidates.append(hauteur_max_m)

    if niveaux_max is not None:
        candidates.append(niveaux_max * _HAUTEUR_PAR_NIVEAU_M + _EPAISSEUR_PLANCHER_M)

    if hauteur_max_ngf is not None and altitude_sol_m is not None:
        candidates.append(hauteur_max_ngf - altitude_sol_m)

    return min(candidates) if candidates else math.inf


def compute_nb_niveaux(hauteur_m: float) -> int:
    """Return the number of storeys that fit within hauteur_m.

    Uses floor(hauteur_m / _HAUTEUR_PAR_NIVEAU_M).
    A height of 0 or less → 0 niveaux.
    """
    if hauteur_m <= 0.0:
        return 0
    return math.floor(hauteur_m / _HAUTEUR_PAR_NIVEAU_M)


def compute_sdp(
    *,
    surface_emprise_m2: float,
    nb_niveaux: int,
    sdp_max_plu: float | None,
    cos: float | None,
    surface_terrain_m2: float,
) -> float:
    """Return the maximum constructible SDP in m².

    Takes the minimum of:
    - surface_emprise_m2 × nb_niveaux (geometric limit)
    - sdp_max_plu (explicit PLU cap, if provided)
    - cos × surface_terrain_m2 (COS-based cap, if provided)
    """
    sdp_geometrique = surface_emprise_m2 * nb_niveaux

    candidates: list[float] = [sdp_geometrique]

    if sdp_max_plu is not None:
        candidates.append(sdp_max_plu)

    if cos is not None:
        candidates.append(cos * surface_terrain_m2)

    return min(candidates)


def compute_logements(
    *,
    sdp_m2: float,
    mix: dict[str, float],
) -> tuple[int, dict[str, int]]:
    """Distribute SDP into dwelling units according to a typological mix.

    Args:
        sdp_m2: Available SDP in m².
        mix: Dict of type → proportion (e.g. {"T2": 0.3, "T3": 0.4, "T4": 0.3}).
             Proportions must sum to ~1.0; missing types default to 0.

    Returns:
        (total_logements, {type: count}) where sum of counts equals total.
    """
    if sdp_m2 <= 0.0 or not mix:
        return 0, {t: 0 for t in mix}

    # Weighted average surface per logement
    total_weight = sum(mix.values())
    avg_surface = sum(
        mix.get(t, 0.0) / total_weight * SURFACE_PAR_TYPOLOGIE_M2.get(t, 65.0)
        for t in mix
    )

    if avg_surface <= 0.0:
        return 0, {t: 0 for t in mix}

    total = math.floor(sdp_m2 / avg_surface)

    if total <= 0:
        return 0, {t: 0 for t in mix}

    # Distribute by mix proportions
    norm = sum(mix.values())
    par_typo: dict[str, int] = {}
    allocated = 0
    types = list(mix.keys())

    for i, t in enumerate(types):
        if i == len(types) - 1:
            # Last type absorbs any rounding remainder
            par_typo[t] = total - allocated
        else:
            count = math.floor(total * mix[t] / norm)
            par_typo[t] = count
            allocated += count

    return total, par_typo


def compute_stationnement(
    *,
    nb_logements: int,
    ratio_par_logement: float,
) -> tuple[int, int]:
    """Compute parking places (total and PMR).

    Args:
        nb_logements: Total number of dwelling units.
        ratio_par_logement: Parking places per logement (may be fractional).

    Returns:
        (total_places, pmr_places) — PMR is max(1, ceil(total * 0.02)).
    """
    total = math.ceil(nb_logements * ratio_par_logement)
    pmr = max(1, math.ceil(total * 0.02))
    return total, pmr


# ---------------------------------------------------------------------------
# Full pipeline
# ---------------------------------------------------------------------------


def compute_capacity(
    *,
    surface_emprise_m2: float,
    surface_terrain_m2: float,
    hauteur_max_m: float | None,
    niveaux_max: int | None,
    altitude_sol_m: float | None,
    hauteur_max_ngf: float | None,
    sdp_max_plu: float | None,
    cos: float | None,
    mix: dict[str, float],
    ratio_stationnement: float,
) -> CapacityResult:
    """Run the full capacity pipeline and return an immutable CapacityResult.

    Steps:
        1. Compute binding height constraint.
        2. Derive number of storeys.
        3. Compute maximum SDP.
        4. Distribute SDP into dwelling units.
        5. Compute parking requirements.
    """
    warnings: list[str] = [_WARNING_INDICATIF]

    # 1. Height
    hauteur_retenue = compute_hauteur_retenue(
        hauteur_max_m=hauteur_max_m,
        niveaux_max=niveaux_max,
        altitude_sol_m=altitude_sol_m,
        hauteur_max_ngf=hauteur_max_ngf,
    )
    # Cap infinite height to avoid nonsensical results downstream
    if math.isinf(hauteur_retenue):
        warnings.append("Aucune contrainte de hauteur fournie — résultat non borné")

    # 2. Niveaux
    nb_niveaux = compute_nb_niveaux(hauteur_retenue if not math.isinf(hauteur_retenue) else 0.0)

    # 3. SDP
    sdp_max = compute_sdp(
        surface_emprise_m2=surface_emprise_m2,
        nb_niveaux=nb_niveaux,
        sdp_max_plu=sdp_max_plu,
        cos=cos,
        surface_terrain_m2=surface_terrain_m2,
    )

    # 4. Logements
    nb_logements, par_typo = compute_logements(sdp_m2=sdp_max, mix=mix)

    # 5. Stationnement
    nb_places, nb_pmr = compute_stationnement(
        nb_logements=nb_logements,
        ratio_par_logement=ratio_stationnement,
    )

    return CapacityResult(
        hauteur_retenue_m=hauteur_retenue if not math.isinf(hauteur_retenue) else 0.0,
        nb_niveaux=nb_niveaux,
        sdp_max_m2=sdp_max,
        nb_logements_max=nb_logements,
        nb_par_typologie=par_typo,
        nb_places_stationnement=nb_places,
        nb_places_pmr=nb_pmr,
        warnings=warnings,
    )
