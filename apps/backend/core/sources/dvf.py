"""DVF (Demandes de Valeurs Foncières) client — property transactions by parcel.

API: https://api.cquest.org/dvf
No API key required.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.http_client import fetch_json

_DVF_URL = "https://api.cquest.org/dvf"


@dataclass(frozen=True)
class DvfTransaction:
    """A DVF property transaction record."""

    date_mutation: str
    nature_mutation: str
    valeur_fonciere: float | None
    type_local: str | None
    surface_m2: float | None
    nb_pieces: int | None
    code_commune: str
    adresse: str | None


def _row_to_transaction(row: dict) -> DvfTransaction:  # type: ignore[type-arg]
    """Convert a raw API result row to a DvfTransaction."""
    raw_valeur = row.get("valeur_fonciere")
    valeur: float | None = float(raw_valeur) if raw_valeur is not None else None

    raw_surface = row.get("surface_reelle_bati")
    surface: float | None = float(raw_surface) if raw_surface is not None else None

    raw_pieces = row.get("nombre_pieces_principales")
    nb_pieces: int | None = int(raw_pieces) if raw_pieces is not None else None

    # Build a readable address from available components
    parts = [
        row.get("no_voie"),
        row.get("type_voie"),
        row.get("voie"),
        row.get("code_postal"),
        row.get("commune"),
    ]
    adresse_parts = [str(p) for p in parts if p is not None]
    adresse: str | None = " ".join(adresse_parts) if adresse_parts else row.get("adresse_norm")

    return DvfTransaction(
        date_mutation=row.get("date_mutation", ""),
        nature_mutation=row.get("nature_mutation", ""),
        valeur_fonciere=valeur,
        type_local=row.get("type_local"),
        surface_m2=surface,
        nb_pieces=nb_pieces,
        code_commune=row.get("code_commune", ""),
        adresse=adresse if adresse else None,
    )


async def fetch_dvf_parcelle(
    *,
    code_insee: str,
    section: str,
    numero: str,
) -> list[DvfTransaction]:
    """Fetch DVF property transactions for a specific parcel.

    Args:
        code_insee: 5-character INSEE commune code (e.g. "94052").
        section: Cadastral section (e.g. "AB").
        numero: Parcel number (e.g. "0042").

    Returns:
        List of :class:`DvfTransaction`. Empty list when no transactions exist.

    Raises:
        httpx.HTTPStatusError: on non-2xx API responses.
    """
    params: dict[str, str | int | float] = {
        "code_commune": code_insee,
        "section": section,
        "numero": numero,
    }
    data = await fetch_json(_DVF_URL, params=params)
    return [_row_to_transaction(row) for row in data.get("resultats", [])]
