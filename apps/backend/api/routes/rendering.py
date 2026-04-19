"""Rendering endpoints — materials catalog, provider quota."""
import os

from fastapi import APIRouter

from core.rendering.materials_catalog import load_materials
from core.rendering.rerender_provider import ReRenderProvider
from schemas.rendering import MaterialOut, MaterialsResponse, QuotaResponse

router = APIRouter(prefix="/rendering", tags=["rendering"])


@router.get("/materials", response_model=MaterialsResponse)
async def list_materials():
    """Return the full materials catalog."""
    items = [
        MaterialOut(
            id=m.id,
            nom=m.nom,
            categorie=m.categorie,
            sous_categorie=m.sous_categorie,
            texture_url=m.texture_url,
            thumbnail_url=m.thumbnail_url,
            prompt_en=m.prompt_en,
            prompt_fr=m.prompt_fr,
            couleur_dominante=m.couleur_dominante,
            conforme_abf=m.conforme_abf,
            regional=m.regional,
        )
        for m in load_materials()
    ]
    return MaterialsResponse(items=items, total=len(items))


@router.get("/quota", response_model=QuotaResponse)
async def get_quota():
    """Return remaining credits for the rendering provider."""
    api_key = os.environ.get("RERENDER_API_KEY", "")
    provider = ReRenderProvider(api_key=api_key)
    remaining = await provider.get_account_credits()
    return QuotaResponse(credits_remaining=remaining, provider="rerender")
