"""INSEE SRU (Solidarité et Renouvellement Urbain) commune status client.

Data source: data.gouv.fr — social housing obligation status per commune.
No API key required.

The SRU law (loi SRU, art. L302-5 CCH) requires communes above a threshold
to maintain 20% or 25% social housing (logements locatifs sociaux — LLS).
Non-compliant communes face financial penalties (carence, rattrapage).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.http_client import fetch_json

# Static dataset — pre-compiled CSV/JSON from DHUP / data.gouv.fr
_SRU_DATASET_URL = "https://www.data.gouv.fr/api/1/datasets/5e6e951806e3e779d36e40b8/"

_logger = logging.getLogger(__name__)

# Fallback resource URL if dataset metadata lookup is unavailable
_SRU_RESOURCE_URL = (
    "https://static.data.gouv.fr/resources/communes-soumises-a-la-loi-sru/"
    "bilan-sru.json"
)


def _parse_statut(row: dict) -> str:  # type: ignore[type-arg]
    """Derive SRU status string from row fields."""
    raw = (row.get("statut") or row.get("statut_commune") or "").lower()
    if "carencé" in raw or "carencee" in raw or "carence" in raw:
        return "carencee"
    if "rattrapage" in raw:
        return "rattrapage"
    if "conforme" in raw or "exempt" in raw:
        return "conforme"
    if "non soumise" in raw or "non_soumise" in raw:
        return "non_soumise"
    # Derive from taux fields when statut is absent
    return "non_soumise"


def _row_to_sru(row: dict, code_insee: str) -> CommuneSRU:  # type: ignore[type-arg]
    """Convert a raw API row to a :class:`CommuneSRU`."""
    raw_taux = row.get("taux_lls") or row.get("taux_lls_realise")
    taux_lls: float | None = float(raw_taux) if raw_taux is not None else None

    raw_cible = row.get("taux_cible") or row.get("taux_objectif")
    taux_cible: float | None = float(raw_cible) if raw_cible is not None else None

    raw_penalite = row.get("penalite") or row.get("penalite_eur") or row.get("amendes")
    penalite_eur: float | None = float(raw_penalite) if raw_penalite is not None else None

    return CommuneSRU(
        code_insee=code_insee,
        taux_lls=taux_lls,
        taux_cible=taux_cible,
        statut=_parse_statut(row),
        penalite_eur=penalite_eur,
    )


@dataclass(frozen=True)
class CommuneSRU:
    """SRU obligation status for a French commune."""

    code_insee: str
    taux_lls: float | None        # current social housing rate
    taux_cible: float | None      # target rate: 25 or 30 (% of main residences)
    statut: str                   # conforme, rattrapage, carencee, non_soumise
    penalite_eur: float | None    # annual penalty in EUR (if applicable)


async def fetch_sru_commune(*, code_insee: str) -> CommuneSRU | None:
    """Fetch SRU status for *code_insee*.

    Queries the data.gouv.fr dataset API to locate the latest SRU resource,
    then looks up the commune's status.

    Args:
        code_insee: 5-digit INSEE municipality code.

    Returns:
        :class:`CommuneSRU` when data is found, ``None`` otherwise.
        Returns ``None`` gracefully on any network or parsing error.
    """
    try:
        dataset_meta = await fetch_json(_SRU_DATASET_URL)
    except Exception:
        _logger.warning("SRU dataset metadata lookup failed — returning None", exc_info=True)
        return None

    # Find the first JSON or CSV resource URL
    resource_url: str | None = None
    for resource in dataset_meta.get("resources", []):
        fmt = (resource.get("format") or "").lower()
        mime = (resource.get("mime") or "").lower()
        if "json" in fmt or "json" in mime:
            resource_url = resource.get("url")
            break
    if not resource_url:
        for resource in dataset_meta.get("resources", []):
            resource_url = resource.get("url")
            if resource_url:
                break

    if not resource_url:
        _logger.warning("No SRU resource URL found — returning None")
        return None

    try:
        data = await fetch_json(resource_url)
    except Exception:
        _logger.warning("SRU resource fetch failed — returning None", exc_info=True)
        return None

    # The payload may be a list or wrapped dict
    rows: list[dict] = []  # type: ignore[type-arg]
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        for key in ("data", "records", "results", "communes"):
            if key in data and isinstance(data[key], list):
                rows = data[key]
                break

    for row in rows:
        # Normalise code_insee field names
        row_code = (
            row.get("code_insee")
            or row.get("codecommune")
            or row.get("code_commune")
            or row.get("insee")
            or ""
        )
        if str(row_code).zfill(5) == code_insee.zfill(5):
            try:
                return _row_to_sru(row, code_insee)
            except (KeyError, ValueError, TypeError):
                _logger.debug("Malformed SRU row for %s: %s", code_insee, row)
                return None

    return None
