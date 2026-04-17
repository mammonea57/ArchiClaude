"""Neighbourhood building enrichment module.

Enriches BDTopo building results with DPE energy performance data by
matching buildings on approximate storey count.

Window/opening detection (_detect_ouvertures) is a stub — deferred to
Phase 6 where it will use Claude Vision on Mapillary/Street View imagery.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.sources.dpe import DpeResult
from core.sources.ign_bdtopo import BatimentResult


@dataclass(frozen=True)
class VoisinEnrichi:
    """An enriched neighbouring building."""

    hauteur: float | None
    nb_etages: int | None
    usage: str | None
    dpe_classe: str | None          # A–G energy class from DPE ADEME
    ouvertures_visibles: bool | None  # None = not analyzed (deferred to Phase 6)
    geometry: dict[str, Any] | None


def _detect_ouvertures(_batiment: BatimentResult) -> bool | None:  # noqa: ARG001
    """Stub: detect visible openings from imagery.

    Deferred to Phase 6 — will use Claude Vision on Mapillary/Street View.

    Returns:
        Always ``None`` until implemented.
    """
    return None


def _match_dpe(batiment: BatimentResult, dpe_records: list[DpeResult]) -> DpeResult | None:
    """Find the best DPE match for *batiment* by storey count.

    Matches on nb_niveaux == nb_etages (approximate; nb_etages is floors above
    ground level, nb_niveaux includes ground floor as a level).

    Args:
        batiment: The building to match.
        dpe_records: Available DPE records.

    Returns:
        Best matching :class:`DpeResult` or ``None`` if no match.
    """
    if batiment.nb_etages is None:
        return None

    for dpe in dpe_records:
        if dpe.nb_niveaux is not None and dpe.nb_niveaux == batiment.nb_etages:
            return dpe

    return None


async def enrich_voisinage(
    *,
    batiments: list[BatimentResult],
    dpe_nearby: list[DpeResult],
) -> list[VoisinEnrichi]:
    """Enrich neighbouring buildings with DPE and opening data.

    Args:
        batiments: List of :class:`BatimentResult` from IGN BDTopo.
        dpe_nearby: List of :class:`DpeResult` from ADEME DPE dataset.

    Returns:
        List of :class:`VoisinEnrichi`, one per input building, preserving order.
    """
    results: list[VoisinEnrichi] = []

    for bat in batiments:
        matched_dpe = _match_dpe(bat, dpe_nearby)
        dpe_classe = matched_dpe.classe_energie if matched_dpe is not None else None

        results.append(
            VoisinEnrichi(
                hauteur=bat.hauteur,
                nb_etages=bat.nb_etages,
                usage=bat.usage,
                dpe_classe=dpe_classe,
                ouvertures_visibles=_detect_ouvertures(bat),
                geometry=bat.geometry,
            )
        )

    return results
