"""Risk score calculator for PC feasibility analysis."""

from __future__ import annotations


def compute_risk_score_calcule(
    *,
    nb_recours_commune: int,
    nb_recours_500m: int,
    associations_actives: int,
    projet_depasse_gabarit: bool,
    depassement_niveaux: int,
    abf_obligatoire: bool,
    nb_conflits_vue: int,
) -> tuple[int, dict[str, int]]:
    """Compute the algorithmic risk score and breakdown detail.

    Returns
    -------
    tuple[int, dict[str, int]]
        (score_calcule capped at 100, detail dict with component scores)
    """
    recours_commune = min(20, nb_recours_commune * 2)
    recours_500m = min(15, nb_recours_500m * 5)
    associations = min(10, associations_actives * 5)
    gabarit = min(20, 5 + depassement_niveaux * 5) if projet_depasse_gabarit else 0
    abf = 10 if abf_obligatoire else 0
    vue_conflicts = min(45, nb_conflits_vue * 15)

    detail: dict[str, int] = {
        "recours_commune": recours_commune,
        "recours_500m": recours_500m,
        "associations": associations,
        "gabarit": gabarit,
        "abf": abf,
        "vue_conflicts": vue_conflicts,
    }

    score = min(100, sum(detail.values()))
    return score, detail


def compute_risk_score_final(
    *,
    score_calcule: int,
    score_opus: int | None,
) -> int:
    """Compute the final blended risk score.

    If score_opus is available: 0.4 * score_calcule + 0.6 * score_opus, capped at 100.
    Otherwise: score_calcule as-is (still capped at 100).
    """
    blended = 0.4 * score_calcule + 0.6 * score_opus if score_opus is not None else float(score_calcule)
    return min(100, round(blended))
