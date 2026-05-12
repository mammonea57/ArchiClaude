"""Voisinage → architectural typology + era inference.

Reads the project's neighbouring buildings via the backend
`/site/voisinage` endpoint, then aggregates them into a `VoisinageContext`
that the reasoner can use to determine which insertion-urbaine cues to
inject in the prompt.

Limitations of the first pass :
  - The voisinage endpoint returns only height + storeys + usage + DPE
    class — no construction year. We *infer* era from height + DPE class
    + commune typology, which is approximate. When BDTopo annee_construction
    is exposed (Phase 6), we plug it in here.
  - Style ↔ era mapping is hardcoded for IDF Paris suburbs ; works for
    Nogent / Vincennes / Saint-Mandé / Paris. Other regions need their own
    mapping table (out of scope for now).
"""
from __future__ import annotations

import logging
from collections import Counter
from typing import Any

import httpx

from .reasoning import Era, VoisinageContext

logger = logging.getLogger(__name__)

BACKEND_URL = "http://localhost:8000"

# DPE energy class → likely construction era window.
# Class A/B = post-2012 RT2012/RE2020 ; C/D = 2000-2012 RT2005 ; E = 1980-2000 ;
# F/G = pre-1980 (poorly insulated, often haussmannien or post-war).
_DPE_TO_ERA: dict[str, Era] = {
    "A": Era.CONTEMPORAIN_NEUF,
    "B": Era.CONTEMPORAIN_NEUF,
    "C": Era.CONTEMPORAIN_RECENT,
    "D": Era.CONTEMPORAIN_RECENT,
    "E": Era.CONTEMPORAIN_80_2000,
    "F": Era.HAUSSMANNIEN,    # very-poor insulation often = old stone
    "G": Era.HAUSSMANNIEN,
}

# Era → typical materials seen in IDF Paris suburbs.
_ERA_MATERIALS: dict[Era, list[str]] = {
    Era.HAUSSMANNIEN: ["pierre_meuliere", "pierre_de_taille", "zinc", "ardoise", "balcon_fer_forge"],
    Era.FAUBOURG_1900: ["enduit_ocre", "brique", "zinc", "lucarnes", "balcon_fer_forge"],
    Era.ART_DECO: ["enduit_clair", "brique", "tuile_plate", "balcon_geometrique"],
    Era.MODERNE_APRES_GUERRE: ["beton_brut", "enduit_blanc", "terrasse", "balcon_filant"],
    Era.CONTEMPORAIN_80_2000: ["enduit_clair", "brique", "tuile_plate", "balcon_metal"],
    Era.CONTEMPORAIN_RECENT: ["enduit_clair", "bardage_bois", "metal", "terrasse"],
    Era.CONTEMPORAIN_NEUF: ["enduit_clair", "bardage_bois", "metal", "verre", "terrasse_vegetalisee"],
    Era.INCONNU: [],
}


def _infer_era(building: dict[str, Any]) -> Era:
    """Infer era from DPE class + height heuristics."""
    dpe = (building.get("dpe_classe") or "").upper()
    if dpe in _DPE_TO_ERA:
        return _DPE_TO_ERA[dpe]
    # Without DPE, use height as a weak signal — IDF post-war buildings are
    # often tall (R+8+) while haussmannien is R+4 to R+6.
    h = building.get("hauteur") or 0
    if h > 25:
        return Era.MODERNE_APRES_GUERRE
    if h > 18:
        return Era.CONTEMPORAIN_RECENT
    return Era.INCONNU


def _median(xs: list[float]) -> float | None:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    n = len(xs)
    return xs[n // 2] if n % 2 else (xs[n // 2 - 1] + xs[n // 2]) / 2


async def fetch_voisinage_context(project_id: str) -> VoisinageContext:
    """Query the backend voisinage endpoint and aggregate the results.

    Gracefully degrades : if the endpoint returns 0 buildings (data not yet
    enriched for this project), we return an empty context — the reasoner
    should fall back on PLU + trends without voisinage cues.
    """
    url = f"{BACKEND_URL}/api/v1/site/voisinage?project_id={project_id}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            r = await client.get(url)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning("voisinage fetch failed: %s — falling back to empty", e)
        return VoisinageContext()

    batiments = data.get("batiments", [])
    if not batiments:
        return VoisinageContext()

    heights = [b.get("hauteur") for b in batiments if b.get("hauteur")]
    storeys = [b.get("nb_etages") for b in batiments if b.get("nb_etages")]
    usages = [b.get("usage") for b in batiments if b.get("usage")]
    eras = [_infer_era(b) for b in batiments]

    era_dist = Counter(eras)
    dominant_era, _ = era_dist.most_common(1)[0]
    dominant_usage, _ = (Counter(usages).most_common(1) or [(None, 0)])[0]

    return VoisinageContext(
        n_buildings=len(batiments),
        median_height_m=_median(heights),
        median_storeys=int(_median(storeys)) if storeys else None,
        dominant_era=dominant_era,
        era_distribution={era: count for era, count in era_dist.items()},
        dominant_usage=dominant_usage,
        likely_materials=list(_ERA_MATERIALS.get(dominant_era, [])),
    )


def fetch_voisinage_context_sync(project_id: str) -> VoisinageContext:
    """Sync wrapper for the synthesizer (which is called from sync render code)."""
    import asyncio
    try:
        return asyncio.run(fetch_voisinage_context(project_id))
    except Exception as e:
        logger.warning("sync voisinage fetch failed: %s — empty context", e)
        return VoisinageContext()
