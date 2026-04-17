"""Servitudes hard constraint detection — ABF, PPRI, EBC, sol pollué, argiles.

Raises :class:`ServitudeAlert` items for each hard constraint found across
monuments historiques (POP), georisques risks, and GPU servitudes.
No network calls — purely analytical over pre-fetched data.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.sources.georisques import RisqueResult
from core.sources.gpu import GpuServitude
from core.sources.pop import MonumentResult


@dataclass(frozen=True)
class ServitudeAlert:
    """A hard-constraint alert raised from servitude / risk data."""

    level: str   # info | warning | critical
    type: str    # abf | ppri | ebc | sol_pollue | argiles | alignement
    message: str
    source: str  # pop | georisques | gpu


def detect_servitudes_alerts(
    *,
    monuments: list[MonumentResult],
    risques: list[RisqueResult],
    servitudes: list[GpuServitude],
) -> list[ServitudeAlert]:
    """Analyse pre-fetched data and return hard-constraint alerts.

    Args:
        monuments: Monuments historiques within the search radius (POP).
        risques:   Risk entries from GeoRisques (GASPAR + argiles).
        servitudes: GPU servitudes at the point.

    Returns:
        Ordered list of :class:`ServitudeAlert`. Empty when no issues found.
    """
    alerts: list[ServitudeAlert] = []

    # -----------------------------------------------------------------------
    # ABF — Architecte des Bâtiments de France (monuments historiques)
    # -----------------------------------------------------------------------
    if monuments:
        noms = ", ".join(m.nom for m in monuments[:3])
        alerts.append(
            ServitudeAlert(
                level="warning",
                type="abf",
                message=(
                    f"Périmètre ABF : avis obligatoire de l'ABF. "
                    f"Monument(s) à proximité : {noms}."
                ),
                source="pop",
            )
        )

    # -----------------------------------------------------------------------
    # Risques GeoRisques
    # -----------------------------------------------------------------------
    for risque in risques:
        rtype = (risque.type or "").lower()

        if rtype == "ppri":
            alerts.append(
                ServitudeAlert(
                    level="critical",
                    type="ppri",
                    message=(
                        f"PPRI : {risque.libelle}. "
                        "Inondation — vérifier cote NGF et conditions de constructibilité."
                    ),
                    source="georisques",
                )
            )

        elif rtype == "argiles":
            niveau = (risque.niveau_alea or "").lower()
            if "fort" in niveau:
                alerts.append(
                    ServitudeAlert(
                        level="warning",
                        type="argiles",
                        message=(
                            f"Retrait-gonflement des argiles — aléa fort. "
                            "Étude géotechnique G2 obligatoire (art. L.112-22 CC)."
                        ),
                        source="georisques",
                    )
                )

        elif rtype in ("basias", "basol"):
            alerts.append(
                ServitudeAlert(
                    level="critical",
                    type="sol_pollue",
                    message=(
                        f"Sol potentiellement pollué ({rtype.upper()}) : {risque.libelle}. "
                        "Diagnostic LSP obligatoire avant permis."
                    ),
                    source="georisques",
                )
            )

    # -----------------------------------------------------------------------
    # EBC — Espaces Boisés Classés (GPU servitudes / prescriptions)
    # -----------------------------------------------------------------------
    for serv in servitudes:
        libelle_lower = (serv.libelle or "").lower()
        categorie_lower = (serv.categorie or "").lower()
        if "ebc" in libelle_lower or "boisé" in libelle_lower or "boise" in libelle_lower:
            alerts.append(
                ServitudeAlert(
                    level="warning",
                    type="ebc",
                    message=(
                        f"Espace Boisé Classé (EBC) : {serv.libelle}. "
                        "Toute construction ou défrichement est interdit."
                    ),
                    source="gpu",
                )
            )
        elif "ebc" in categorie_lower or "boisé" in categorie_lower or "boise" in categorie_lower:
            alerts.append(
                ServitudeAlert(
                    level="warning",
                    type="ebc",
                    message=(
                        f"Espace Boisé Classé (EBC) — catégorie {serv.categorie} : {serv.libelle}. "
                        "Toute construction ou défrichement est interdit."
                    ),
                    source="gpu",
                )
            )

    return alerts
