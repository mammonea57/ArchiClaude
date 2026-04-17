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


# ---------------------------------------------------------------------------
# Zone rules extraction schemas
# ---------------------------------------------------------------------------


class ParsedRulesOut(BaseModel):
    hauteur: str | None = None
    emprise: str | None = None
    implantation_voie: str | None = None
    limites_separatives: str | None = None
    stationnement: str | None = None
    lls: str | None = None
    espaces_verts: str | None = None
    destinations: str | None = None
    pages: dict[str, int | None] = {}
    source: str
    cached: bool


class NumericRulesOut(BaseModel):
    hauteur_max_m: float | None = None
    emprise_max_pct: float | None = None
    recul_voirie_m: float | None = None
    pleine_terre_min_pct: float = 0.0
    extraction_confidence: float
    extraction_warnings: list[str] = []


class ZoneRulesResponse(BaseModel):
    text: ParsedRulesOut
    numeric: NumericRulesOut | None = None
    confidence: float | None = None
    validated: bool = False


class ExtractionJobResponse(BaseModel):
    job_id: str
    status: str


class ExtractionStatusResponse(BaseModel):
    job_id: str
    status: str
    progress: str | None = None
    result: dict | None = None
