"""GeoRisques API client — natural and technological risks at a point.

APIs:
  GASPAR: https://georisques.gouv.fr/api/v1/gaspar
  Argiles: https://georisques.gouv.fr/api/v1/mvt (rephrased below)
No API key required.

Each sub-endpoint is queried independently; failures are silently swallowed
(mode dégradé) so that partial results are still returned.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.http_client import fetch_json

_GASPAR_URL = "https://georisques.gouv.fr/api/v1/gaspar/risque"
_ARGILES_URL = "https://georisques.gouv.fr/api/v1/argiles"

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RisqueResult:
    """A risk entry returned by the GeoRisques API."""

    type: str           # ppri, argiles, basias, basol, …
    code: str | None
    libelle: str
    niveau_alea: str | None


async def fetch_risques(*, lat: float, lng: float) -> list[RisqueResult]:
    """Fetch risk data at a WGS84 point from GeoRisques.

    Queries GASPAR (multi-risk database) and the Argiles (shrink-swell clay)
    endpoint in sequence, each in an independent try/except block so that a
    failure of one source does not prevent the other from being returned.

    Args:
        lat: Latitude in WGS84 decimal degrees.
        lng: Longitude in WGS84 decimal degrees.

    Returns:
        Aggregated list of :class:`RisqueResult`. May be empty if both sources
        are unavailable or return no data for this location.
    """
    results: list[RisqueResult] = []

    # --- GASPAR ---------------------------------------------------------------
    try:
        gaspar_params: dict[str, str | int | float] = {
            "latlon": f"{lat},{lng}",
            "rayon": 100,
        }
        gaspar_data = await fetch_json(_GASPAR_URL, params=gaspar_params)
        for item in gaspar_data.get("data", []):
            results.append(
                RisqueResult(
                    type=item.get("type_risque", ""),
                    code=item.get("code_risque"),
                    libelle=item.get("libelle_risque", ""),
                    niveau_alea=item.get("niveau_alea"),
                )
            )
    except Exception:
        _logger.warning("GeoRisques GASPAR endpoint unavailable — skipping", exc_info=True)

    # --- Argiles --------------------------------------------------------------
    try:
        argiles_params: dict[str, str | int | float] = {
            "latlon": f"{lat},{lng}",
        }
        argiles_data = await fetch_json(_ARGILES_URL, params=argiles_params)
        for item in argiles_data.get("data", []):
            results.append(
                RisqueResult(
                    type="argiles",
                    code=item.get("code_alea"),
                    libelle=item.get("libelle_alea", "Retrait-gonflement des argiles"),
                    niveau_alea=item.get("niveau_alea"),
                )
            )
    except Exception:
        _logger.warning("GeoRisques Argiles endpoint unavailable — skipping", exc_info=True)

    return results
