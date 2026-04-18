"""Multi-scenario programmer solver.

Computes three programming scenarios from a set of level footprints:
  - max_sdp: maximises developer revenue (brief mix, risk-adjusted SDP)
  - max_logements: shifts mix toward smaller units for more dwellings
  - max_confort: shifts mix toward larger units for better comfort

All surfaces in m². All inputs must be in Lambert-93 (EPSG:2154, metric CRS).
"""

from __future__ import annotations

import math

from core.feasibility.capacity import compute_logements, compute_stationnement
from core.feasibility.smart_margin import compute_smart_margin
from core.programming.schemas import (
    NiveauFootprint,
    Scenario,
    SolverResult,
    SURFACE_NOYAU_M2,
)

# ---------------------------------------------------------------------------
# Mix shifting helpers
# ---------------------------------------------------------------------------

# Ordered typology list (small → large)
_TYPO_ORDER = ["T1", "T2", "T3", "T4", "T5"]


def _normalise(mix: dict[str, float]) -> dict[str, float]:
    """Ensure mix values sum to exactly 1.0."""
    total = sum(mix.values())
    if total <= 0.0:
        return mix
    return {k: v / total for k, v in mix.items()}


def _shift_mix_small(mix: dict[str, float]) -> dict[str, float]:
    """Shift mix toward small units (T1/T2) for maximum logement count.

    Strategy:
    - Add 15% to T2 (or T1 if T2 not present)
    - Reduce proportionally from the largest present typologies
    Always re-normalises so sum = 1.0.
    """
    result = dict(mix)
    shift = 0.15

    # Identify target small type (T2 preferred, fall back to T1)
    small_key = None
    for t in ("T2", "T1"):
        if t in result:
            small_key = t
            break
    if small_key is None:
        # Nothing to shift toward
        return _normalise(result)

    # Identify source large types (T4/T5 preferred, then T3)
    large_keys = [t for t in ("T5", "T4", "T3") if t in result and t != small_key]
    if not large_keys:
        return _normalise(result)

    # Distribute the shift reduction across large types proportionally
    large_total = sum(result[k] for k in large_keys)
    if large_total <= 0.0:
        return _normalise(result)

    actual_shift = min(shift, large_total * 0.5)  # cap to avoid going negative
    result[small_key] = result[small_key] + actual_shift
    for k in large_keys:
        result[k] = max(0.0, result[k] - actual_shift * result[k] / large_total)

    return _normalise(result)


def _shift_mix_large(mix: dict[str, float]) -> dict[str, float]:
    """Shift mix toward large units (T3/T4) for maximum comfort.

    Strategy:
    - Add 10% to T3, 10% to T4 (if present)
    - Reduce proportionally from T1/T2
    Always re-normalises so sum = 1.0.
    """
    result = dict(mix)

    # Targets to boost
    boost_keys = [t for t in ("T3", "T4") if t in result]
    # Sources to reduce
    reduce_keys = [t for t in ("T1", "T2") if t in result]

    if not boost_keys or not reduce_keys:
        return _normalise(result)

    shift_per_target = 0.10
    total_shift = shift_per_target * len(boost_keys)

    reduce_total = sum(result[k] for k in reduce_keys)
    actual_shift = min(total_shift, reduce_total * 0.5)
    per_boost = actual_shift / len(boost_keys)

    for k in boost_keys:
        result[k] = result[k] + per_boost

    for k in reduce_keys:
        result[k] = max(0.0, result[k] - actual_shift * result[k] / reduce_total)

    return _normalise(result)


# ---------------------------------------------------------------------------
# Adjustment suggestion texts
# ---------------------------------------------------------------------------


def _build_adjustments_small(
    mix_original: dict[str, float],
    mix_shifted: dict[str, float],
    nb_logements_orig: int,
    nb_logements_new: int,
) -> list[str]:
    """Generate human-readable adjustment suggestions for max_logements."""
    suggestions: list[str] = []
    gain = nb_logements_new - nb_logements_orig

    for t in _TYPO_ORDER:
        orig = mix_original.get(t, 0.0)
        shifted = mix_shifted.get(t, 0.0)
        delta = shifted - orig
        if abs(delta) > 0.005:
            direction = "hausse" if delta > 0 else "baisse"
            suggestions.append(
                f"{t} à {shifted * 100:.0f}% ({direction} de {abs(delta) * 100:.0f} pts)"
            )

    if gain > 0:
        # Find the T with the biggest increase
        biggest = max(
            ((t, mix_shifted.get(t, 0.0) - mix_original.get(t, 0.0)) for t in _TYPO_ORDER),
            key=lambda x: x[1],
        )
        t_name, _ = biggest
        pct = mix_shifted.get(t_name, 0.0) * 100
        suggestions.insert(
            0,
            f"En passant à {pct:.0f}% de {t_name}, vous gagnez {gain} logements",
        )

    if not suggestions:
        suggestions.append("Mix déjà optimisé pour le nombre de logements")

    return suggestions


def _build_adjustments_large(
    mix_original: dict[str, float],
    mix_shifted: dict[str, float],
) -> list[str]:
    """Generate human-readable adjustment suggestions for max_confort."""
    suggestions: list[str] = []

    for t in _TYPO_ORDER:
        orig = mix_original.get(t, 0.0)
        shifted = mix_shifted.get(t, 0.0)
        delta = shifted - orig
        if abs(delta) > 0.005:
            direction = "hausse" if delta > 0 else "baisse"
            suggestions.append(
                f"{t} à {shifted * 100:.0f}% ({direction} de {abs(delta) * 100:.0f} pts)"
            )

    if not suggestions:
        suggestions.append("Mix déjà optimisé pour le confort")

    return suggestions


# ---------------------------------------------------------------------------
# LLS separate access calculation
# ---------------------------------------------------------------------------


def _compute_lls_variant(
    *,
    sdp: float,
    nb_niveaux: int,
) -> tuple[float, bool]:
    """Compute perte_sdp for separate LLS access and whether to auto-recommend.

    Returns:
        (perte_sdp_m2, variante_recommandee)
    """
    perte = SURFACE_NOYAU_M2 * nb_niveaux
    auto_recommend = sdp > 0.0 and (perte / sdp) < 0.03
    return perte, auto_recommend


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def solve_scenarios(
    *,
    footprints: list[NiveauFootprint],
    surface_terrain_m2: float,
    mix_brief: dict[str, float],
    stationnement_par_logement: float,
    risk_score: int,
    lls_obligatoire: bool = False,
    comparables_max_pct: float | None = None,
) -> SolverResult:
    """Compute three programming scenarios for the given footprints.

    Args:
        footprints: List of NiveauFootprint (one per storey level).
        surface_terrain_m2: Total terrain surface in m² (used for context).
        mix_brief: Typological mix from the brief {"T2": 0.3, ...}; must sum
            to ~1.0.
        stationnement_par_logement: Parking places per logement.
        risk_score: Integer risk score 0–100 (from risk_score module).
        lls_obligatoire: True if social housing (LLS) is mandatory.
        comparables_max_pct: Optional comparable project acceptance ratio
            (forwarded to compute_smart_margin).

    Returns:
        SolverResult with three scenarios and a recommendation.
    """
    if not footprints:
        raise ValueError("footprints must not be empty")

    nb_niveaux = len(footprints)

    # --- Brute SDP = sum of footprint areas ---
    sdp_brute = sum(f.surface_m2 for f in footprints)

    # --- Risk-adjusted margin ---
    margin = compute_smart_margin(
        risk_score=risk_score,
        sdp_max=sdp_brute,
        comparables_max_pct_accepted=comparables_max_pct,
    )
    sdp = margin.sdp_recommandee
    marge_pct = margin.marge_pct

    # --- Three mixes ---
    mix_sdp = _normalise(mix_brief)
    mix_log = _shift_mix_small(mix_brief)
    mix_conf = _shift_mix_large(mix_brief)

    # --- Compute logements for each mix ---
    nb_log_sdp, par_typo_sdp = compute_logements(sdp_m2=sdp, mix=mix_sdp)
    nb_log_log, par_typo_log = compute_logements(sdp_m2=sdp, mix=mix_log)
    nb_log_conf, par_typo_conf = compute_logements(sdp_m2=sdp, mix=mix_conf)

    # --- Stationnement ---
    stat_sdp, pmr_sdp = compute_stationnement(
        nb_logements=nb_log_sdp, ratio_par_logement=stationnement_par_logement
    )
    stat_log, pmr_log = compute_stationnement(
        nb_logements=nb_log_log, ratio_par_logement=stationnement_par_logement
    )
    stat_conf, pmr_conf = compute_stationnement(
        nb_logements=nb_log_conf, ratio_par_logement=stationnement_par_logement
    )

    # --- Adjustment suggestions ---
    adj_sdp: list[str] = []
    adj_log = _build_adjustments_small(mix_sdp, mix_log, nb_log_sdp, nb_log_log)
    adj_conf = _build_adjustments_large(mix_sdp, mix_conf)

    # --- LLS separate access ---
    perte_sdp_sdp: float | None = None
    perte_sdp_log: float | None = None
    perte_sdp_conf: float | None = None
    var_sdp = False
    var_log = False
    var_conf = False

    if lls_obligatoire:
        perte_sdp_sdp, var_sdp = _compute_lls_variant(sdp=sdp, nb_niveaux=nb_niveaux)
        perte_sdp_log, var_log = _compute_lls_variant(sdp=sdp, nb_niveaux=nb_niveaux)
        perte_sdp_conf, var_conf = _compute_lls_variant(sdp=sdp, nb_niveaux=nb_niveaux)

    # --- Build scenarios ---
    scenario_max_sdp = Scenario(
        nom="max_sdp",
        mix_utilise=mix_sdp,
        mix_ajustements=adj_sdp,
        sdp_m2=sdp,
        nb_logements=nb_log_sdp,
        nb_par_typologie=par_typo_sdp,
        nb_niveaux=nb_niveaux,
        footprints_par_niveau=list(footprints),
        nb_places_stationnement=stat_sdp,
        nb_places_pmr=pmr_sdp,
        variante_acces_separes=var_sdp,
        perte_sdp_acces_separes_m2=perte_sdp_sdp,
        marge_pct=marge_pct,
    )

    scenario_max_log = Scenario(
        nom="max_logements",
        mix_utilise=mix_log,
        mix_ajustements=adj_log,
        sdp_m2=sdp,
        nb_logements=nb_log_log,
        nb_par_typologie=par_typo_log,
        nb_niveaux=nb_niveaux,
        footprints_par_niveau=list(footprints),
        nb_places_stationnement=stat_log,
        nb_places_pmr=pmr_log,
        variante_acces_separes=var_log,
        perte_sdp_acces_separes_m2=perte_sdp_log,
        marge_pct=marge_pct,
    )

    scenario_max_conf = Scenario(
        nom="max_confort",
        mix_utilise=mix_conf,
        mix_ajustements=adj_conf,
        sdp_m2=sdp,
        nb_logements=nb_log_conf,
        nb_par_typologie=par_typo_conf,
        nb_niveaux=nb_niveaux,
        footprints_par_niveau=list(footprints),
        nb_places_stationnement=stat_conf,
        nb_places_pmr=pmr_conf,
        variante_acces_separes=var_conf,
        perte_sdp_acces_separes_m2=perte_sdp_conf,
        marge_pct=marge_pct,
    )

    # --- Recommendation ---
    scenario_recommande = "max_sdp"
    if risk_score > 60:
        raison = (
            f"Scénario max_sdp recommandé malgré un risque élevé (score {risk_score}). "
            "Maximise la rentabilité développeur. "
            "La marge de sécurité intégrée atténue le risque réglementaire."
        )
    else:
        raison = (
            "Scénario max_sdp recommandé : maximise la rentabilité développeur "
            "avec la marge réglementaire adaptée au niveau de risque."
        )

    return SolverResult(
        scenarios=[scenario_max_sdp, scenario_max_log, scenario_max_conf],
        scenario_recommande=scenario_recommande,
        raison_recommandation=raison,
    )
