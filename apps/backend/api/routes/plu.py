"""PLU (Plan Local d'Urbanisme) API routes — urbanisme data at a point."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from core.sources import georisques, gpu, pop
from schemas.plu import (
    MonumentOut,
    PluAtPointResponse,
    PluDocumentOut,
    PluZoneOut,
    PrescriptionOut,
    RisqueOut,
    ServitudeOut,
)

router = APIRouter(prefix="/plu", tags=["plu"])


@router.get("/at-point", response_model=PluAtPointResponse)
async def plu_at_point(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
) -> PluAtPointResponse:
    """Fetch all urbanisme data at a WGS84 point.

    Queries all 6 data sources in parallel: GPU zones, GPU document,
    GPU servitudes, GPU prescriptions, GeoRisques risks, and POP monuments.
    """
    (
        zones_raw,
        docs_raw,
        servitudes_raw,
        prescriptions_raw,
        risques_raw,
        monuments_raw,
    ) = await asyncio.gather(
        gpu.fetch_zones_at_point(lat=lat, lng=lng),
        gpu.fetch_document(lat=lat, lng=lng),
        gpu.fetch_servitudes_at_point(lat=lat, lng=lng),
        gpu.fetch_prescriptions_at_point(lat=lat, lng=lng),
        georisques.fetch_risques(lat=lat, lng=lng),
        pop.fetch_monuments_around(lat=lat, lng=lng, radius_m=500),
    )

    zones = [
        PluZoneOut(
            libelle=z.libelle,
            libelong=z.libelong,
            typezone=z.typezone,
            nomfic=z.nomfic,
            urlfic=z.urlfic,
            geometry=z.geometry,
        )
        for z in zones_raw
    ]

    document: PluDocumentOut | None = None
    if docs_raw:
        d = docs_raw[0]
        document = PluDocumentOut(
            idurba=d.idurba,
            typedoc=d.typedoc,
            datappro=d.datappro,
            nom=d.nom,
        )

    servitudes = [
        ServitudeOut(
            libelle=s.libelle,
            categorie=s.categorie,
            txt=s.txt,
            geometry=s.geometry,
        )
        for s in servitudes_raw
    ]

    prescriptions = [
        PrescriptionOut(
            libelle=p.libelle,
            txt=p.txt,
            typepsc=p.typepsc,
            geometry=p.geometry,
        )
        for p in prescriptions_raw
    ]

    risques = [
        RisqueOut(
            type=r.type,
            code=r.code,
            libelle=r.libelle,
            niveau_alea=r.niveau_alea,
        )
        for r in risques_raw
    ]

    monuments = [
        MonumentOut(
            reference=m.reference,
            nom=m.nom,
            date_protection=m.date_protection,
            commune=m.commune,
            lat=m.lat,
            lng=m.lng,
        )
        for m in monuments_raw
    ]

    return PluAtPointResponse(
        zones=zones,
        document=document,
        servitudes=servitudes,
        prescriptions=prescriptions,
        risques=risques,
        monuments=monuments,
    )
