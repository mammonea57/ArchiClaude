"""Public transport accessibility qualification module.

Determines whether a site is "bien desservie" (well-served) by public
transport according to the criteria used for car-parking exemptions in
dense urban zones (PLU article 12 / motorisation alternative).

Criteria for bien_desservie + stationnement_exoneration_possible:
  - Metro stop within 400m
  - RER stop within 400m
  - Tram stop within 300m
  - At least 2 frequent bus lines within 300m (lines must be in frequent_bus_lines set)
"""

from __future__ import annotations

from dataclasses import dataclass

from core.sources.ign_transports import ArretTC

_METRO_RER_RADIUS_M = 400.0
_TRAM_RADIUS_M = 300.0
_BUS_RADIUS_M = 300.0
_MIN_FREQUENT_BUS_LINES = 2


@dataclass(frozen=True)
class DesserteResult:
    """Public transport accessibility qualification for a site."""

    bien_desservie: bool
    stationnement_exoneration_possible: bool
    motif: str | None  # human-readable justification


def qualify_desserte(
    arrets: list[ArretTC],
    *,
    frequent_bus_lines: set[str] | None = None,
) -> DesserteResult:
    """Qualify the public transport accessibility of a site.

    Args:
        arrets: List of :class:`ArretTC` near the site, with distance_m populated.
        frequent_bus_lines: Set of bus line identifiers considered frequent
            (e.g. {"183", "bus rapide X"}). When None, no bus lines are
            treated as frequent.

    Returns:
        :class:`DesserteResult` with qualification and justification.
    """
    if not arrets:
        return DesserteResult(
            bien_desservie=False,
            stationnement_exoneration_possible=False,
            motif=None,
        )

    fb = frequent_bus_lines or set()

    for arret in arrets:
        dist = arret.distance_m if arret.distance_m is not None else float("inf")
        mode = arret.mode.lower()

        # Metro within 400m
        if mode == "metro" and dist <= _METRO_RER_RADIUS_M:
            return DesserteResult(
                bien_desservie=True,
                stationnement_exoneration_possible=True,
                motif=f"Métro '{arret.nom}' à {dist:.0f}m",
            )

        # RER within 400m
        if mode == "rer" and dist <= _METRO_RER_RADIUS_M:
            return DesserteResult(
                bien_desservie=True,
                stationnement_exoneration_possible=True,
                motif=f"RER '{arret.nom}' à {dist:.0f}m",
            )

        # Tram within 300m
        if mode == "tram" and dist <= _TRAM_RADIUS_M:
            return DesserteResult(
                bien_desservie=True,
                stationnement_exoneration_possible=True,
                motif=f"Tramway '{arret.nom}' à {dist:.0f}m",
            )

    # Check frequent bus lines within 300m
    if fb:
        nearby_frequent_lines: set[str] = set()
        for arret in arrets:
            dist = arret.distance_m if arret.distance_m is not None else float("inf")
            mode = arret.mode.lower()
            if mode == "bus" and dist <= _BUS_RADIUS_M and arret.ligne in fb:
                nearby_frequent_lines.add(arret.ligne)  # type: ignore[arg-type]

        if len(nearby_frequent_lines) >= _MIN_FREQUENT_BUS_LINES:
            lines_str = ", ".join(sorted(nearby_frequent_lines))
            return DesserteResult(
                bien_desservie=True,
                stationnement_exoneration_possible=True,
                motif=f"≥2 lignes bus fréquentes ≤300m ({lines_str})",
            )

    return DesserteResult(
        bien_desservie=False,
        stationnement_exoneration_possible=False,
        motif=None,
    )
