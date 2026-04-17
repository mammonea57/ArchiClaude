"""Brief comparison — gap analysis between developer targets and regulatory maxima.

Computes the ratio (brief / max) for each target and classifies it:
  - très sous-exploité : the programme leaves significant capacity unused
  - cohérent           : brief and regulatory max are well matched
  - infaisable         : brief exceeds the regulatory maximum

Uses :class:`~core.feasibility.schemas.EcartItem` as the result container.
"""

from __future__ import annotations

from core.feasibility.schemas import EcartItem

# ---------------------------------------------------------------------------
# Ratio classification
# ---------------------------------------------------------------------------

_COMMENTAIRES: dict[str, str] = {
    "tres_sous_exploite": "Le programme utilise moins de 60 % du potentiel réglementaire.",
    "sous_exploite": "Le programme utilise 60–85 % du potentiel — marge de densification possible.",
    "coherent": "Le programme est cohérent avec le potentiel réglementaire.",
    "limite": "Le programme atteint la limite réglementaire — peu de marge.",
    "infaisable": "Le programme dépasse le potentiel réglementaire — révision nécessaire.",
}


def classify_ratio(ratio: float) -> str:
    """Classify a brief/max ratio into one of five categories.

    Boundaries:
        < 0.60  → tres_sous_exploite
        0.60–0.85 → sous_exploite
        0.85–1.00 → coherent
        1.00–1.05 → limite  (inclusive at 1.00, exclusive at 1.05)
        > 1.05  → infaisable  (≥ 1.05 inclusive)

    Args:
        ratio: brief_value / max_value.

    Returns:
        One of the five classification strings.
    """
    if ratio < 0.60:
        return "tres_sous_exploite"
    if ratio < 0.85:
        return "sous_exploite"
    if ratio < 1.00:
        return "coherent"
    if ratio < 1.05:
        return "limite"
    return "infaisable"


# ---------------------------------------------------------------------------
# Main comparison function
# ---------------------------------------------------------------------------


def compare_brief_to_max(
    *,
    brief_nb_logements: int | None = None,
    max_nb_logements: int = 0,
    brief_sdp_m2: float | None = None,
    max_sdp_m2: float = 0,
    brief_hauteur_niveaux: int | None = None,
    max_niveaux: int = 0,
    brief_emprise_pct: float | None = None,
    max_emprise_pct: float = 0,
) -> dict[str, EcartItem]:
    """Compare brief targets to regulatory maxima and return gap analysis items.

    Only creates an entry when both conditions are met:
      1. The brief target is not None.
      2. The corresponding max is > 0 (avoids division by zero).

    Args:
        brief_nb_logements: Target number of dwellings (optional).
        max_nb_logements:   Regulatory maximum dwellings.
        brief_sdp_m2:       Target SDP in m² (optional).
        max_sdp_m2:         Regulatory maximum SDP in m².
        brief_hauteur_niveaux: Target number of storeys (optional).
        max_niveaux:        Regulatory maximum storeys.
        brief_emprise_pct:  Target footprint percentage (optional).
        max_emprise_pct:    Regulatory maximum footprint percentage.

    Returns:
        Dict mapping target name → :class:`EcartItem`.
    """
    candidates: list[tuple[str, float | None, float]] = [
        ("nb_logements", float(brief_nb_logements) if brief_nb_logements is not None else None, float(max_nb_logements)),
        ("sdp_m2", float(brief_sdp_m2) if brief_sdp_m2 is not None else None, float(max_sdp_m2)),
        ("hauteur_niveaux", float(brief_hauteur_niveaux) if brief_hauteur_niveaux is not None else None, float(max_niveaux)),
        ("emprise_pct", float(brief_emprise_pct) if brief_emprise_pct is not None else None, float(max_emprise_pct)),
    ]

    result: dict[str, EcartItem] = {}
    for target, brief_val, max_val in candidates:
        if brief_val is None:
            continue
        if max_val <= 0:
            continue
        ratio = brief_val / max_val
        classification = classify_ratio(ratio)
        result[target] = EcartItem(
            target=target,
            brief_value=brief_val,
            max_value=max_val,
            ratio=round(ratio, 4),
            classification=classification,
            commentaire=_COMMENTAIRES[classification],
        )

    return result
