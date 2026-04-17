"""Sitadel / opendata.paris.fr building permits client.

Paris open data: https://opendata.paris.fr
No API key required.

Returns comparable building permits (PCs) for feasibility comparisons.
Progressive coverage: Paris (75*) in v1, other communes return empty list.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.http_client import fetch_json

_PARIS_PC_URL = (
    "https://opendata.paris.fr/api/explore/v2.1/catalog/datasets/"
    "permis-de-construire-autorises-a-paris/records"
)

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComparablePC:
    """A comparable building permit from open data."""

    date_arrete: str | None
    adresse: str | None
    nb_logements: int | None
    sdp_m2: float | None
    destination: str | None
    hauteur_niveaux: int | None
    lat: float | None
    lng: float | None
    source: str  # "opendata_paris", "sitadel"


def _row_to_pc(record: dict) -> ComparablePC:  # type: ignore[type-arg]
    """Convert an opendata.paris.fr record to a ComparablePC."""
    fields = record.get("fields", record)  # handle both wrapper formats

    raw_nb = fields.get("nb_logements") or fields.get("nombre_logements")
    nb_logements: int | None = int(raw_nb) if raw_nb is not None else None

    raw_sdp = fields.get("sdp_totale") or fields.get("surface_sdp_totale")
    sdp_m2: float | None = float(raw_sdp) if raw_sdp is not None else None

    raw_niv = fields.get("nb_niveaux") or fields.get("nombre_niveaux")
    hauteur_niveaux: int | None = int(raw_niv) if raw_niv is not None else None

    geo = fields.get("geo_point_2d") or {}
    if isinstance(geo, dict):
        lat = geo.get("lat") or geo.get("latitude")
        lng = geo.get("lon") or geo.get("longitude")
    else:
        lat = None
        lng = None
    lat = float(lat) if lat is not None else None
    lng = float(lng) if lng is not None else None

    return ComparablePC(
        date_arrete=fields.get("date_arrete") or fields.get("date_autorisation"),
        adresse=fields.get("adresse") or fields.get("libelle_adresse"),
        nb_logements=nb_logements,
        sdp_m2=sdp_m2,
        destination=fields.get("destination") or fields.get("nature_travaux"),
        hauteur_niveaux=hauteur_niveaux,
        lat=lat,
        lng=lng,
        source="opendata_paris",
    )


async def fetch_pc_commune(*, code_insee: str) -> list[ComparablePC]:
    """Fetch comparable building permits for *code_insee*.

    Args:
        code_insee: 5-digit INSEE municipality code.

    Returns:
        List of up to 50 recent :class:`ComparablePC`. Returns ``[]``
        for non-Paris communes (v1 — progressive coverage) and on any error.
    """
    if not code_insee.startswith("75"):
        # v1: only Paris is covered
        return []

    params: dict[str, str | int] = {
        "limit": 50,
        "order_by": "date_arrete DESC",
    }

    try:
        data = await fetch_json(_PARIS_PC_URL, params=params)
    except Exception:
        _logger.warning("Sitadel/Paris opendata request failed — returning empty", exc_info=True)
        return []

    results: list[ComparablePC] = []
    for record in data.get("results", []):
        try:
            results.append(_row_to_pc(record))
        except (KeyError, ValueError, TypeError):
            _logger.debug("Skipping malformed PC record: %s", record)

    return results
