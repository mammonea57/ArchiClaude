"""Pydantic response models for /site/* endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


# --- Photos ---

class MapillaryPhotoOut(BaseModel):
    image_id: str
    thumb_url: str
    captured_at: int
    compass_angle: float
    lat: float
    lng: float


class StreetViewImageOut(BaseModel):
    pano_id: str
    image_url: str
    lat: float
    lng: float
    date: str | None


class SitePhotosResponse(BaseModel):
    mapillary: list[MapillaryPhotoOut]
    streetview: list[StreetViewImageOut]


# --- Transports ---

class ArretTCOut(BaseModel):
    nom: str
    mode: str
    ligne: str | None
    distance_m: float | None


class SiteTransportsResponse(BaseModel):
    arrets: list[ArretTCOut]
    bien_desservie: bool
    stationnement_exoneration_possible: bool
    motif: str | None


# --- Bruit ---

class SiteBruitResponse(BaseModel):
    classement_sonore: int | None
    source: str | None
    lden_dominant: float | None
    isolation_acoustique_obligatoire: bool


# --- Voisinage ---

class VoisinOut(BaseModel):
    hauteur: float | None
    nb_etages: int | None
    usage: str | None
    dpe_classe: str | None
    ouvertures_visibles: bool | None
    geometry: dict[str, Any] | None


class SiteVoisinageResponse(BaseModel):
    batiments: list[VoisinOut]


# --- Comparables ---

class ComparableProjectOut(BaseModel):
    date_arrete: str | None
    adresse: str | None
    nb_logements: int | None
    sdp_m2: float | None
    destination: str | None
    hauteur_niveaux: int | None
    source: str


class SiteComparablesResponse(BaseModel):
    projects: list[ComparableProjectOut]


# --- DVF ---

class DvfTransactionOut(BaseModel):
    date_mutation: str
    nature_mutation: str
    valeur_fonciere: float | None
    type_local: str | None
    surface_m2: float | None
    nb_pieces: int | None
    adresse: str | None


class DvfAggregates(BaseModel):
    prix_moyen_m2_appartement: float | None
    prix_moyen_m2_maison: float | None
    nb_transactions: int


class SiteDvfResponse(BaseModel):
    transactions: list[DvfTransactionOut]
    aggregates: DvfAggregates
