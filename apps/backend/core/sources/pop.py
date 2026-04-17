"""POP — Plateforme Ouverte du Patrimoine client (monuments historiques).

API: https://api.pop.culture.gouv.fr/search/
Uses Elasticsearch DSL via HTTP POST with a geo_distance filter.
No API key required.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.http_client import post_json

_POP_URL = "https://api.pop.culture.gouv.fr/search/merimee/_search"


@dataclass(frozen=True)
class MonumentResult:
    """Structured result from a POP monuments historiques query."""

    reference: str
    nom: str
    date_protection: str | None
    commune: str | None
    departement: str | None
    lat: float | None
    lng: float | None


async def fetch_monuments_around(
    *,
    lat: float,
    lng: float,
    radius_m: int = 500,
) -> list[MonumentResult]:
    """Fetch monuments historiques within *radius_m* metres of a WGS84 point.

    Uses an Elasticsearch geo_distance query posted to the POP search API.

    Args:
        lat: Latitude in WGS84 decimal degrees.
        lng: Longitude in WGS84 decimal degrees.
        radius_m: Search radius in metres (default 500).

    Returns:
        List of :class:`MonumentResult`. Empty list when no monuments are found.

    Raises:
        httpx.HTTPStatusError: on non-2xx API responses.
    """
    body = {
        "size": 50,
        "query": {
            "bool": {
                "filter": [
                    {
                        "geo_distance": {
                            "distance": f"{radius_m}m",
                            "POP_COORDONNEES": {"lat": lat, "lon": lng},
                        }
                    }
                ]
            }
        },
    }

    data = await post_json(_POP_URL, json_body=body)

    results: list[MonumentResult] = []
    hits = data.get("hits", {}).get("hits", [])
    for hit in hits:
        src = hit.get("_source", {})
        coords = src.get("POP_COORDONNEES") or {}
        hit_lat: float | None = float(coords["lat"]) if coords.get("lat") is not None else None
        hit_lng: float | None = float(coords["lon"]) if coords.get("lon") is not None else None

        results.append(
            MonumentResult(
                reference=src.get("REF", ""),
                nom=src.get("TICO", ""),
                date_protection=src.get("DPRO"),
                commune=src.get("COM"),
                departement=src.get("DPT"),
                lat=hit_lat,
                lng=hit_lng,
            )
        )

    return results
