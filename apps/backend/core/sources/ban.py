"""BAN (Base Adresse Nationale) geocoding client.

API documentation: https://adresse.data.gouv.fr/api-doc/adresse
Rate limit: ~50 req/s — no authentication required.
"""

from __future__ import annotations

from dataclasses import dataclass

from core.http_client import fetch_json

_BAN_URL = "https://api-adresse.data.gouv.fr/search/"


@dataclass(frozen=True)
class GeocodingResult:
    """Structured result from a BAN geocoding query."""

    label: str
    score: float
    lat: float
    lng: float
    citycode: str
    city: str
    postcode: str | None = None
    housenumber: str | None = None
    street: str | None = None


async def geocode(query: str, *, limit: int = 5) -> list[GeocodingResult]:
    """Geocode *query* using the BAN API.

    Args:
        query: Free-form address string (e.g. "12 rue de la Paix 75002 Paris").
        limit: Maximum number of results to return (passed to BAN ``limit`` param).

    Returns:
        A list of :class:`GeocodingResult` ordered by BAN relevance score.
        Returns an empty list when *query* is blank.

    Raises:
        httpx.HTTPStatusError: when the BAN API returns a non-2xx response.
    """
    if not query.strip():
        return []

    data = await fetch_json(_BAN_URL, params={"q": query, "limit": limit})

    results: list[GeocodingResult] = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        coords = feature.get("geometry", {}).get("coordinates", [None, None])
        lng, lat = coords[0], coords[1]

        if lat is None or lng is None:
            continue

        results.append(
            GeocodingResult(
                label=props["label"],
                score=float(props["score"]),
                lat=float(lat),
                lng=float(lng),
                citycode=props["citycode"],
                city=props["city"],
                postcode=props.get("postcode"),
                housenumber=props.get("housenumber"),
                street=props.get("street"),
            )
        )

    return results
