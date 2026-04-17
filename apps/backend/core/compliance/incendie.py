"""Fire safety classification (familles d'habitation, IGH).

Based on the French Arrêté du 31 janvier 1986 relatif à la protection
contre l'incendie des bâtiments d'habitation.

Classification uses *plancher haut* height (height of the highest floor
above finished ground level), NOT the total building height.

IMPORTANT — coef_reduction_sdp:
    The coefficient is always returned as 1.0.  The actual SDP reduction
    coefficients vary by classement and staircase configuration and must be
    verified by a BET incendie / bureau de contrôle.  Returning 1.0 is
    conservative (no auto-reduction) pending sourced values.
"""

from __future__ import annotations


def classify_incendie(
    *,
    hauteur_plancher_haut_m: float,
    nb_niveaux: int,
    destination: str,
) -> tuple[str, float]:
    """Classify a building's fire safety family and return the SDP coefficient.

    Args:
        hauteur_plancher_haut_m: Height of the highest occupied floor above
            finished ground level, in metres.
        nb_niveaux: Total number of storeys including RDC (e.g. R+3 → 4).
        destination: Building use — ``"logement_individuel"`` triggers
            the individuel thresholds; all other values use the collectif path.

    Returns:
        A tuple ``(classement, coef_reduction_sdp)`` where:
          - classement: one of ``"1ere"``, ``"2eme"``, ``"3A"``, ``"4eme"``,
            ``"IGH"``.
          - coef_reduction_sdp: always ``1.0`` — to be confirmed by BET.
    """
    h = hauteur_plancher_haut_m
    is_individuel = destination == "logement_individuel"

    if h > 50.0:
        classement = "IGH"
    elif h > 28.0:
        classement = "4eme"
    elif h > 8.0:
        # collectif plancher haut > 8 m and ≤ 28 m → 3A
        # individuel > R+3 → also 3A (rare but possible)
        classement = "3A"
    else:
        # h ≤ 8 m
        classement = "1ere" if is_individuel and nb_niveaux <= 2 else "2eme"

    return classement, 1.0
