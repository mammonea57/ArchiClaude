from typing import Any

from pydantic import BaseModel


class GeocodingResultOut(BaseModel):
    label: str
    score: float
    lat: float
    lng: float
    citycode: str
    city: str


class ParcelFromApi(BaseModel):
    """Parcel data returned from external API (before DB storage)."""

    code_insee: str
    section: str
    numero: str
    contenance_m2: int | None
    commune: str
    geometry: dict[str, Any]
