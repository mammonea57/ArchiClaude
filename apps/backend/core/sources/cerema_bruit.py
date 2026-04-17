"""Cerema noise classification client via IGN WFS (Géoplateforme).

Queries the WFS endpoint at data.geopf.fr for road and railway noise
classification (classement sonore des infrastructures de transports terrestres).
No API key required.

Returns empty list gracefully on any network or parsing error.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from core.http_client import fetch_json

_WFS_URL = "https://data.geopf.fr/wfs/ows"

# IGN/Cerema WFS typename for noise classification
_TYPENAME = "BDCARTO_V5:troncon_de_route"  # fallback typename; real layer may vary
_NOISE_TYPENAME = "CLASSEMENT_SONORE:classement_sonore_route"

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClassementSonore:
    """A road or railway noise classification segment."""

    categorie: int        # 1–5, category 1 is the noisiest
    type_infra: str       # "route" or "voie_ferree"
    nom_voie: str | None
    lden: float | None    # day-evening-night level in dB(A)


async def fetch_classement_sonore(
    *, lat: float, lng: float, radius_m: int = 200
) -> list[ClassementSonore]:
    """Fetch noise-classified infrastructure segments near the given point.

    Uses a WFS bbox query against the Géoplateforme IGN endpoint.

    Args:
        lat: Latitude in WGS84 decimal degrees.
        lng: Longitude in WGS84 decimal degrees.
        radius_m: Search radius in metres (converted to a bbox).

    Returns:
        List of :class:`ClassementSonore`. Returns ``[]`` on any error
        (graceful degradation — noise data is supplemental).
    """
    dlat = radius_m / 111_000
    dlng = radius_m / 73_000

    west = lng - dlng
    south = lat - dlat
    east = lng + dlng
    north = lat + dlat
    bbox = f"{west},{south},{east},{north},EPSG:4326"

    params: dict[str, str | int | float] = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": _NOISE_TYPENAME,
        "BBOX": bbox,
        "OUTPUTFORMAT": "application/json",
        "COUNT": 50,
    }

    try:
        data = await fetch_json(_WFS_URL, params=params)
    except Exception:
        _logger.warning("Cerema noise WFS request failed — returning empty", exc_info=True)
        return []

    results: list[ClassementSonore] = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        try:
            results.append(
                ClassementSonore(
                    categorie=int(props.get("categorie", 5)),
                    type_infra=str(props.get("type_infra", "route")),
                    nom_voie=props.get("nom_voie") or None,
                    lden=float(props["lden"]) if props.get("lden") is not None else None,
                )
            )
        except (KeyError, ValueError, TypeError):
            _logger.debug("Skipping malformed Cerema feature: %s", props)

    return results
