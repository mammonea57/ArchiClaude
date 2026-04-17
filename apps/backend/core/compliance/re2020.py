"""RE2020 — Réglementation Environnementale 2020.

Decret n° 2021-1004 du 29 juillet 2021 + Arrêté du 4 août 2021.

IC construction (kgCO2eq/m² SDP) thresholds for logements collectifs neufs:
  - Applicable from 1 January 2022 : ≤ 760
  - Applicable from 1 January 2025 : ≤ 650
  - Applicable from 1 January 2028 : ≤ 480

IC énergie thresholds are not yet returned (require BET input) — None.

IMPORTANT: All estimated values are *indicatifs* (order-of-magnitude only).
They must be validated by a BET thermique/environnemental.
"""

from __future__ import annotations

# (annee_debut_inclusif, annee_fin_exclusif, seuil_label, ic_const_seuil)
_SEUILS: list[tuple[int, int, str, float]] = [
    (2022, 2025, "2022", 760.0),
    (2025, 2028, "2025", 650.0),
    (2028, 9999, "2028", 480.0),
]

_WARNING_BET = "Valeurs indicatives — à affiner par un BET thermique/environnemental agréé."


def estimate_re2020(
    *,
    destination: str,
    annee_cible: int,
) -> tuple[float | None, float | None, str, list[str]]:
    """Estimate RE2020 thresholds and return indicative values.

    Args:
        destination: Building use (informational in v1 — thresholds are for
            logements collectifs; other destinations require specific study).
        annee_cible: Target year of building permit submission.

    Returns:
        A tuple ``(ic_construction_estime, ic_energie_estime, seuil_applicable, warnings)``
        where:
          - ic_construction_estime: Always None — indicative, needs BET input.
          - ic_energie_estime: Always None — indicative, needs BET input.
          - seuil_applicable: Label of the applicable threshold period
            (``"2022"``, ``"2025"``, or ``"2028"``).
          - warnings: List of advisory messages (always at least one).
    """
    seuil_label = "2022"
    for debut, fin, label, _ in _SEUILS:
        if annee_cible >= debut:
            seuil_label = label

    warnings: list[str] = [_WARNING_BET]
    if destination not in ("logement_collectif",):
        warnings.append(
            f"Seuils RE2020 affichés pour logement collectif. "
            f"Destination '{destination}' requiert une étude spécifique."
        )

    return None, None, seuil_label, warnings
