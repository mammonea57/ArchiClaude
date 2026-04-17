from typing import Any

from pydantic import BaseModel


class PluZoneOut(BaseModel):
    libelle: str
    libelong: str | None
    typezone: str
    nomfic: str | None
    urlfic: str | None
    geometry: dict[str, Any] | None


class PluDocumentOut(BaseModel):
    idurba: str
    typedoc: str
    datappro: str | None
    nom: str | None


class ServitudeOut(BaseModel):
    libelle: str
    categorie: str
    txt: str | None
    geometry: dict[str, Any] | None


class PrescriptionOut(BaseModel):
    libelle: str
    txt: str | None
    typepsc: str | None
    geometry: dict[str, Any] | None


class RisqueOut(BaseModel):
    type: str
    code: str | None
    libelle: str
    niveau_alea: str | None


class MonumentOut(BaseModel):
    reference: str
    nom: str
    date_protection: str | None
    commune: str | None
    lat: float | None
    lng: float | None


class PluAtPointResponse(BaseModel):
    zones: list[PluZoneOut]
    document: PluDocumentOut | None
    servitudes: list[ServitudeOut]
    prescriptions: list[PrescriptionOut]
    risques: list[RisqueOut]
    monuments: list[MonumentOut]
