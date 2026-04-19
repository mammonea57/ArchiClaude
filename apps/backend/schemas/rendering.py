"""API schemas for rendering endpoints."""
from pydantic import BaseModel


class MaterialOut(BaseModel):
    id: str
    nom: str
    categorie: str
    sous_categorie: str
    texture_url: str
    thumbnail_url: str
    prompt_en: str
    prompt_fr: str
    couleur_dominante: str
    conforme_abf: bool
    regional: str | None = None


class MaterialsResponse(BaseModel):
    items: list[MaterialOut]
    total: int


class QuotaResponse(BaseModel):
    credits_remaining: int  # -1 for unlimited
    provider: str
