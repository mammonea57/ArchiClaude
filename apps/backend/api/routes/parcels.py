"""Parcels API routes — geocoding and cadastral parcel lookup."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from core.sources import ban, cadastre
from schemas.parcel import GeocodingResultOut, ParcelFromApi

router = APIRouter(prefix="/parcels", tags=["parcels"])


@router.get("/search", response_model=list[GeocodingResultOut])
async def search_parcels(
    q: str = Query(..., min_length=3),
    limit: int = Query(5, ge=1, le=20),
) -> list[GeocodingResultOut]:
    """Geocode address via BAN (Base Adresse Nationale)."""
    results = await ban.geocode(q, limit=limit)
    return [
        GeocodingResultOut(
            label=r.label,
            score=r.score,
            lat=r.lat,
            lng=r.lng,
            citycode=r.citycode,
            city=r.city,
        )
        for r in results
    ]


@router.get("/at-point", response_model=ParcelFromApi)
async def parcel_at_point(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
) -> ParcelFromApi:
    """Fetch parcel at a WGS84 point."""
    result = await cadastre.fetch_parcelle_at_point(lat=lat, lng=lng)
    if result is None:
        raise HTTPException(status_code=404, detail="No parcel found at this location")
    return ParcelFromApi(
        code_insee=result.code_insee,
        section=result.section,
        numero=result.numero,
        contenance_m2=result.contenance_m2,
        commune=result.commune,
        geometry=result.geometry,
    )


@router.get("/by-ref", response_model=ParcelFromApi)
async def parcel_by_ref(
    insee: str = Query(..., pattern=r"^\d{5}$"),
    section: str = Query(..., pattern=r"^[0-9A-Z]{1,3}$"),
    numero: str = Query(..., pattern=r"^\d{1,5}$"),
) -> ParcelFromApi:
    """Fetch parcel by cadastral reference (INSEE code + section + numero)."""
    result = await cadastre.fetch_parcelle_by_ref(
        code_insee=insee,
        section=section,
        numero=numero,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="No parcel found for this reference")
    return ParcelFromApi(
        code_insee=result.code_insee,
        section=result.section,
        numero=result.numero,
        contenance_m2=result.contenance_m2,
        commune=result.commune,
        geometry=result.geometry,
    )
