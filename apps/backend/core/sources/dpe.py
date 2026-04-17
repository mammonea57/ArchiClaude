"""DPE ADEME client — energy performance diagnostics near a point.

API: https://data.ademe.fr/data-fair/api/v1/datasets/meg-83tjwtg8dyz4vv7h1dqe/lines
No API key required.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.http_client import fetch_json

_DPE_URL = "https://data.ademe.fr/data-fair/api/v1/datasets/meg-83tjwtg8dyz4vv7h1dqe/lines"

_SELECT_FIELDS = (
    "nombre_niveau_immeuble,"
    "hauteur_sous_plafond,"
    "classe_consommation_energie,"
    "type_batiment,"
    "geo_adresse"
)


@dataclass(frozen=True)
class DpeResult:
    """Structured result from a DPE ADEME query."""

    nb_niveaux: int | None
    hauteur_sous_plafond: float | None
    classe_energie: str | None
    type_batiment: str | None
    adresse: str | None


def _row_to_result(row: dict) -> DpeResult:  # type: ignore[type-arg]
    """Convert a raw API row to a DpeResult."""
    raw_nb = row.get("nombre_niveau_immeuble")
    nb_niveaux: int | None = int(raw_nb) if raw_nb is not None else None

    raw_hsp = row.get("hauteur_sous_plafond")
    hauteur: float | None = float(raw_hsp) if raw_hsp is not None else None

    return DpeResult(
        nb_niveaux=nb_niveaux,
        hauteur_sous_plafond=hauteur,
        classe_energie=row.get("classe_consommation_energie"),
        type_batiment=row.get("type_batiment"),
        adresse=row.get("geo_adresse"),
    )


async def fetch_dpe_around(
    *,
    lat: float,
    lng: float,
    radius_m: int = 30,
) -> list[DpeResult]:
    """Fetch DPE records within *radius_m* metres of a WGS84 point.

    Results are sorted so that records with ``type_batiment == "immeuble"``
    appear first (ascending sort by type, "immeuble" < "maison" lexically).

    Args:
        lat: Latitude in WGS84 decimal degrees.
        lng: Longitude in WGS84 decimal degrees.
        radius_m: Search radius in metres (default 30).

    Returns:
        List of :class:`DpeResult`. Empty list when no records are found.

    Raises:
        httpx.HTTPStatusError: on non-2xx API responses.
    """
    params: dict[str, str | int | float] = {
        "geo_distance": f"{lat},{lng},{radius_m}m",
        "size": 20,
        "select": _SELECT_FIELDS,
    }
    data = await fetch_json(_DPE_URL, params=params)
    results = [_row_to_result(row) for row in data.get("results", [])]

    # Sort: "immeuble" type first (lexicographic order puts "immeuble" before "maison")
    results.sort(key=lambda r: (r.type_batiment or "zzz"))
    return results
