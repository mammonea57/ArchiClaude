"""LLS/SRU — Logements Locatifs Sociaux obligations under loi SRU.

Loi n° 2000-1208 du 13 décembre 2000 (SRU), modified by loi ALUR 2014
and loi 3DS 2022.

Commune statuts:
  - conforme      : commune meets its SRU quota — no additional obligation
                    on individual operations.
  - rattrapage    : commune is below quota and subject to a catch-up plan.
                    Obligation applies to operations above a size threshold
                    (sdp > 800 m² or nb_logements > 12).
  - carencee      : commune has been formally declared in deficiency.
                    Reinforced obligation applies regardless of size.
  - non_soumise   : commune is not subject to SRU (< 3 500 inhabitants,
                    or not in an agglomeration ≥ 50 000).

Obligations (indicative — precise % depends on PLH / convention):
  - rattrapage : 25 % LLS minimum (simplified; actual rate set by prefecture)
  - carencee   : 30 % LLS minimum (reinforced — simplified)

Bonus constructibilité:
  Up to 10 % additional constructibility when the programme includes
  > 35 % LLS (article L.151-28 du Code de l'urbanisme).
"""

from __future__ import annotations

# Thresholds for rattrapage communes
_RATTRAPAGE_SDP_SEUIL = 800.0   # m²
_RATTRAPAGE_LOGEMENTS_SEUIL = 12

_OBLIGATION_RATTRAPAGE = 0.25  # 25 %
_OBLIGATION_CARENCEE = 0.30    # 30 % (reinforced)
_BONUS_CONSTRUCTIBILITE = 10.0  # percent


def compute_lls_obligation(
    *,
    commune_statut: str,
    sdp_m2: float,
    nb_logements: int,
) -> tuple[float | None, float | None, list[str]]:
    """Compute LLS obligation and potential constructibility bonus.

    Args:
        commune_statut: One of ``"conforme"``, ``"rattrapage"``,
            ``"carencee"``, ``"non_soumise"``.
        sdp_m2: Total SDP of the programme in m².
        nb_logements: Total number of dwellings in the programme.

    Returns:
        A tuple ``(obligation_pct, bonus_constructibilite_pct, warnings)``
        where:
          - obligation_pct: Minimum LLS fraction (0–1) or None if no obligation.
          - bonus_constructibilite_pct: Up to 10.0 if eligible, else None.
          - warnings: Advisory messages (always a list, may be empty).
    """
    warnings: list[str] = []
    obligation_pct: float | None = None
    bonus_constructibilite_pct: float | None = None

    if commune_statut in ("conforme", "non_soumise"):
        # No obligation — programme is free.
        if commune_statut == "rattrapage":  # unreachable branch, safety guard
            pass
        return None, None, warnings

    if commune_statut == "rattrapage":
        above_threshold = sdp_m2 > _RATTRAPAGE_SDP_SEUIL or nb_logements > _RATTRAPAGE_LOGEMENTS_SEUIL
        if above_threshold:
            obligation_pct = _OBLIGATION_RATTRAPAGE
            warnings.append(
                f"Commune en rattrapage SRU : {obligation_pct * 100:.0f} % de LLS "
                "minimum requis (taux indicatif — à confirmer avec la préfecture)."
            )
            bonus_constructibilite_pct = _BONUS_CONSTRUCTIBILITE
        else:
            warnings.append(
                "Commune en rattrapage SRU mais opération sous seuil "
                f"(SDP ≤ {_RATTRAPAGE_SDP_SEUIL} m² et logements ≤ {_RATTRAPAGE_LOGEMENTS_SEUIL})."
            )

    elif commune_statut == "carencee":
        obligation_pct = _OBLIGATION_CARENCEE
        warnings.append(
            f"Commune carencée SRU : {obligation_pct * 100:.0f} % de LLS minimum requis "
            "(obligation renforcée — arrêté préfectoral applicable)."
        )
        bonus_constructibilite_pct = _BONUS_CONSTRUCTIBILITE

    else:
        warnings.append(f"Statut SRU inconnu '{commune_statut}' — vérifier avec la commune.")

    return obligation_pct, bonus_constructibilite_pct, warnings
