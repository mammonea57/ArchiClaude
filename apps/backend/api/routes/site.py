"""Site context API routes — photos, noise, transport, neighbourhood, comparables, DVF."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query

from core.site import bruit as bruit_module
from core.site import transports as transports_module
from core.site import voisinage as voisinage_module
from core.sources import (
    bruitparif,
    cerema_bruit,
    dpe,
    dvf,
    google_streetview,
    ign_bdtopo,
    ign_transports,
    mapillary,
    sitadel,
)
from schemas.site import (
    ArretTCOut,
    ComparableProjectOut,
    DvfAggregates,
    DvfTransactionOut,
    MapillaryPhotoOut,
    SiteBruitResponse,
    SiteComparablesResponse,
    SiteDvfResponse,
    SitePhotosResponse,
    SiteTransportsResponse,
    SiteVoisinageResponse,
    StreetViewImageOut,
    VoisinOut,
)

router = APIRouter(prefix="/site", tags=["site"])


@router.get("/photos", response_model=SitePhotosResponse)
async def site_photos(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_m: int = Query(50, ge=1, le=500),
) -> SitePhotosResponse:
    """Fetch street-level photos from Mapillary and Google Street View in parallel."""
    mapillary_photos, sv_image = await asyncio.gather(
        mapillary.fetch_photos_around(lat=lat, lng=lng, radius_m=radius_m),
        google_streetview.fetch_streetview_image(lat=lat, lng=lng),
    )

    mapillary_out = [
        MapillaryPhotoOut(
            image_id=p.image_id,
            thumb_url=p.thumb_url,
            captured_at=p.captured_at,
            compass_angle=p.compass_angle,
            lat=p.lat,
            lng=p.lng,
        )
        for p in mapillary_photos
    ]

    streetview_out: list[StreetViewImageOut] = []
    if sv_image is not None:
        streetview_out.append(
            StreetViewImageOut(
                pano_id=sv_image.pano_id,
                image_url=sv_image.image_url,
                lat=sv_image.lat,
                lng=sv_image.lng,
                date=sv_image.date,
            )
        )

    return SitePhotosResponse(mapillary=mapillary_out, streetview=streetview_out)


@router.get("/bruit", response_model=SiteBruitResponse)
async def site_bruit(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
) -> SiteBruitResponse:
    """Fetch and aggregate noise data from Cerema and Bruitparif in parallel."""
    cerema_result, bp_result = await asyncio.gather(
        cerema_bruit.fetch_classement_sonore(lat=lat, lng=lng),
        bruitparif.fetch_bruit_idf(lat=lat, lng=lng),
    )

    aggregated = bruit_module.aggregate_bruit(cerema=cerema_result, bruitparif=bp_result)

    return SiteBruitResponse(
        classement_sonore=aggregated.classement_sonore,
        source=aggregated.source,
        lden_dominant=aggregated.lden_dominant,
        isolation_acoustique_obligatoire=aggregated.isolation_acoustique_obligatoire,
    )


@router.get("/transports", response_model=SiteTransportsResponse)
async def site_transports(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_m: int = Query(500, ge=1, le=2000),
) -> SiteTransportsResponse:
    """Fetch transport stops and qualify accessibility."""
    arrets_raw = await ign_transports.fetch_arrets_around(lat=lat, lng=lng, radius_m=radius_m)

    desserte = transports_module.qualify_desserte(arrets_raw)

    arrets_out = [
        ArretTCOut(
            nom=a.nom,
            mode=a.mode,
            ligne=a.ligne,
            distance_m=a.distance_m,
        )
        for a in arrets_raw
    ]

    return SiteTransportsResponse(
        arrets=arrets_out,
        bien_desservie=desserte.bien_desservie,
        stationnement_exoneration_possible=desserte.stationnement_exoneration_possible,
        motif=desserte.motif,
    )


@router.get("/voisinage", response_model=SiteVoisinageResponse)
async def site_voisinage(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    radius_m: int = Query(100, ge=1, le=500),
) -> SiteVoisinageResponse:
    """Fetch and enrich neighbouring buildings with BDTopo + DPE data in parallel."""
    batiments_raw, dpe_raw = await asyncio.gather(
        ign_bdtopo.fetch_batiments_around(lat=lat, lng=lng, radius_m=radius_m),
        dpe.fetch_dpe_around(lat=lat, lng=lng),
    )

    voisins = await voisinage_module.enrich_voisinage(
        batiments=batiments_raw, dpe_nearby=dpe_raw
    )

    batiments_out = [
        VoisinOut(
            hauteur=v.hauteur,
            nb_etages=v.nb_etages,
            usage=v.usage,
            dpe_classe=v.dpe_classe,
            ouvertures_visibles=v.ouvertures_visibles,
            geometry=v.geometry,
        )
        for v in voisins
    ]

    return SiteVoisinageResponse(batiments=batiments_out)


@router.get("/comparables", response_model=SiteComparablesResponse)
async def site_comparables(
    code_insee: str = Query(..., pattern=r"^\d{5}$"),
) -> SiteComparablesResponse:
    """Fetch comparable building permits for a commune."""
    pcs = await sitadel.fetch_pc_commune(code_insee=code_insee)

    projects = [
        ComparableProjectOut(
            date_arrete=pc.date_arrete,
            adresse=pc.adresse,
            nb_logements=pc.nb_logements,
            sdp_m2=pc.sdp_m2,
            destination=pc.destination,
            hauteur_niveaux=pc.hauteur_niveaux,
            source=pc.source,
        )
        for pc in pcs
    ]

    return SiteComparablesResponse(projects=projects)


@router.get("/dvf", response_model=SiteDvfResponse)
async def site_dvf(
    code_insee: str = Query(..., pattern=r"^\d{5}$"),
    section: str = Query(..., pattern=r"^[0-9A-Z]{1,3}$"),
    numero: str = Query(..., pattern=r"^\d{1,5}$"),
) -> SiteDvfResponse:
    """Fetch DVF property transactions for a parcel and compute price aggregates."""
    transactions_raw = await dvf.fetch_dvf_parcelle(
        code_insee=code_insee, section=section, numero=numero
    )

    transactions_out = [
        DvfTransactionOut(
            date_mutation=t.date_mutation,
            nature_mutation=t.nature_mutation,
            valeur_fonciere=t.valeur_fonciere,
            type_local=t.type_local,
            surface_m2=t.surface_m2,
            nb_pieces=t.nb_pieces,
            adresse=t.adresse,
        )
        for t in transactions_raw
    ]

    # Compute price per m² averages by type_local
    def _avg_prix_m2(type_local: str) -> float | None:
        prices = [
            t.valeur_fonciere / t.surface_m2
            for t in transactions_raw
            if t.type_local == type_local
            and t.valeur_fonciere is not None
            and t.surface_m2 is not None
            and t.surface_m2 > 0
        ]
        if not prices:
            return None
        return round(sum(prices) / len(prices), 2)

    aggregates = DvfAggregates(
        prix_moyen_m2_appartement=_avg_prix_m2("Appartement"),
        prix_moyen_m2_maison=_avg_prix_m2("Maison"),
        nb_transactions=len(transactions_raw),
    )

    return SiteDvfResponse(transactions=transactions_out, aggregates=aggregates)
