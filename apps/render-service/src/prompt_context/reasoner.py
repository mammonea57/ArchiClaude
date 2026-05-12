"""Architectural reasoner — combines BM + PLU + voisinage + trends into
justified design choices.

This is the brain of Phase 5b. Each architectural element (facade, roof,
balconies, RDC, context) gets a `Justification` answering : *given the PLU,
the voisinage, the market and current trends, what should the building look
like — and why ?*.

The reasoner doesn't just describe what the BM already says ; it also
checks coherence (e.g. if BM has a flat roof but PLU prescribes mansard, it
flags) and pushes 2025 trend cues that fit the site.
"""
from __future__ import annotations

import logging
from typing import Any

from .plu_context import fetch_plu_constraints
from .reasoning import (
    ArchReasoning,
    Era,
    FacadeAccent,
    FacadeComposition,
    FacadeZone,
    Justification,
    MarketContext,
    MarketSegment,
    PluConstraints,
    VoisinageContext,
)
from .trends_2025 import select_applicable_trends
from .voisinage_context import fetch_voisinage_context_sync

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-element reasoners — each returns one Justification answering "why X here".
# ---------------------------------------------------------------------------

def _compose_facade(
    bm: dict[str, Any],
    plu: PluConstraints,
    voisinage: VoisinageContext,
    market: MarketContext,
) -> FacadeComposition:
    """Build the stratified facade composition (RDC + courant + attique + accents).

    Logic per zone :
      - RDC : noble material (pierre meulière + brique) when sector is dense UA
              and PLU prescribes it. Falls back to BM facade.style otherwise.
      - Courant : BM facade.style if it's in the PLU prescribed list, else the
              first prescribed material.
      - Attique : zinc retrait (faubourg insertion) OR bardage bois (BM
              terrasse modern) OR none (low building).
      - Accents : balcony railings + cornice/bandeau if haussmannien/faubourg.
    """
    bm_model = bm.get("model_json", bm)
    bm_style = (bm_model.get("facades") or {}).get("est", {}).get("style")
    niveaux = bm_model.get("envelope", {}).get("niveaux", 0)
    storeys = max(0, int(niveaux) - 1)
    toit = bm_model.get("envelope", {}).get("toiture") or {}
    rdc_use = next(
        (n.get("usage_principal") for n in (bm_model.get("niveaux") or [])
         if n.get("code") == "R+0"),
        None,
    )

    # CRITICAL : the BM `materiaux_rendu` carries the architect's actual
    # material decisions. They override PLU defaults.
    materiaux_rendu = bm_model.get("materiaux_rendu") or {}
    bm_facade = materiaux_rendu.get("facade_principal")
    bm_toiture_mat = materiaux_rendu.get("toiture")
    bm_menuiseries = materiaux_rendu.get("menuiseries")

    is_dense_ua = (plu.sector or "").upper().startswith("UA") and (plu.emprise_max_pct or 0) >= 0.7
    insertion_haussmannienne = voisinage.dominant_era in (Era.HAUSSMANNIEN, Era.FAUBOURG_1900)

    zones: list[FacadeZone] = []

    # ─── BM materiaux_rendu fast path ───
    # When the BM defines an exact material set, use it everywhere on the
    # facade and ignore PLU material defaults (those are starting points,
    # the architect has already chosen).
    if bm_facade:
        facade_visual = _bm_material_visual(bm_facade)
        zones.append(FacadeZone(
            zone_id="rdc",
            height_label="ground floor",
            material_visual=f"solid residential ground floor in {facade_visual}",
            rationale=[f"BM materiaux_rendu.facade_principal={bm_facade}"],
        ))
        zones.append(FacadeZone(
            zone_id="courant",
            height_label=f"R+1 to R+{storeys - 1}" if storeys >= 2 else "upper floor",
            material_visual=f"{facade_visual} upper floors",
            rationale=[f"BM materiaux_rendu.facade_principal={bm_facade}"],
        ))
        attique_visual = "set-back top floor"
        if toit.get("vegetalisee"):
            attique_visual += " with rooftop garden"
        if bm_toiture_mat:
            attique_visual += f", {_bm_material_visual(bm_toiture_mat)} parapet"
        zones.append(FacadeZone(
            zone_id="attique",
            height_label="attique",
            material_visual=attique_visual,
            rationale=[f"BM toiture", f"BM materiaux_rendu.toiture={bm_toiture_mat}"],
        ))
        from .reasoning import FacadeAccent
        accents: list[FacadeAccent] = []
        if bm_menuiseries:
            accents.append(FacadeAccent(
                name="window_frames",
                visual=f"{_bm_material_visual(bm_menuiseries)} window frames",
                rationale=[f"BM materiaux_rendu.menuiseries={bm_menuiseries}"],
            ))
        accents.append(FacadeAccent(
            name="balcony_railings",
            visual="continuous balconies on every upper floor with slim metal railings",
            rationale=["standard residential IDF"],
        ))
        return FacadeComposition(zones=zones, accents=accents)

    # ─── RDC ───
    if is_dense_ua and ("pierre_meuliere" in (plu.materials_prescribed or [])):
        rdc_visual = "meulière stone and terracotta brick ground floor base"
        rdc_sources = [f"PLU {plu.sector} art-11 pierre+brique", "tendance 2024-26 RDC pierre noble"]
    elif "brique" in (plu.materials_prescribed or []):
        rdc_visual = "terracotta brick ground floor base"
        rdc_sources = [f"PLU {plu.sector} art-11 brique"]
    elif bm_style:
        rdc_visual = f"ground floor in {_material_visual(bm_style)}"
        rdc_sources = ["BM facade.style (no PLU stone prescribed)"]
    else:
        rdc_visual = "stone-base ground floor"
        rdc_sources = ["default IDF UA"]
    if rdc_use == "commerce":
        rdc_visual += " with commercial shop windows"
        rdc_sources.append("BM R+0=commerce")
    zones.append(FacadeZone(
        zone_id="rdc",
        height_label="ground floor",
        material_visual=rdc_visual,
        rationale=rdc_sources,
    ))

    # ─── Courant (R+1 to R+(N-1)) ───
    courant_label = f"R+1 to R+{storeys - 1}" if storeys >= 2 else "upper floor"
    if bm_style and bm_style in (plu.materials_prescribed or [bm_style]):
        courant_material = _material_visual_short(bm_style)
        courant_sources = ["BM facade.style", f"PLU {plu.sector} art-11 confirme"]
    elif plu.materials_prescribed:
        courant_material = _material_visual_short(plu.materials_prescribed[0])
        courant_sources = [f"PLU {plu.sector} art-11"]
    else:
        courant_material = _material_visual_short(bm_style or "enduit_clair")
        courant_sources = ["BM facade.style"]
    courant_visual = f"{courant_material} upper floors"
    # Add window-grid descriptor for richness
    if market.segment in (MarketSegment.HAUT_GAMME, MarketSegment.MOYEN_GAMME):
        courant_visual += " with stone window surrounds"
        courant_sources.append("positionnement moyen/haut-gamme")
    zones.append(FacadeZone(
        zone_id="courant",
        height_label=courant_label,
        material_visual=courant_visual,
        rationale=courant_sources,
    ))

    # ─── Attique (R+N retrait) ───
    if storeys >= 4:
        if toit.get("type") == "terrasse":
            if insertion_haussmannienne and "zinc" in (plu.toiture_prescribed or []):
                attique_visual = "zinc-cladded set-back top floor"
                attique_sources = [f"PLU {plu.sector} art-11 zinc",
                                   "voisinage haussmannien/faubourg insertion"]
            elif toit.get("vegetalisee"):
                attique_visual = "set-back top floor with rooftop garden"
                attique_sources = ["BM toiture.vegetalisee", "tendance 2024-26 RE2020"]
            else:
                attique_visual = "wood-clad set-back top floor"
                attique_sources = ["BM toiture.terrasse", "tendance 2024-26 attique bois"]
        else:
            attique_visual = "zinc mansard top floor with dormers"
            attique_sources = [f"BM toiture.type={toit.get('type')}"]
        zones.append(FacadeZone(
            zone_id="attique",
            height_label=f"R+{storeys} setback",
            material_visual=attique_visual,
            rationale=attique_sources,
        ))

    # ─── Accents ───
    accents: list[FacadeAccent] = []
    # Balcony railings — always (modern collectif)
    if market.segment == MarketSegment.HAUT_GAMME:
        accents.append(FacadeAccent(
            name="balcony_railings",
            visual="cantilevered balconies with glass railings",
            rationale=["positionnement haut-gamme"],
        ))
    else:
        accents.append(FacadeAccent(
            name="balcony_railings",
            visual="cantilevered balconies with metal railings",
            rationale=["tendance 2024-26 IDF résidentiel collectif"],
        ))
    # Cornice/bandeau when faubourg insertion
    if insertion_haussmannienne or is_dense_ua:
        accents.append(FacadeAccent(
            name="cornice",
            visual="stone cornice band",
            rationale=([f"voisinage {voisinage.dominant_era.value}" if insertion_haussmannienne
                        else f"PLU {plu.sector} contexte faubourg"]),
        ))
    # Wrought iron details for haussmannien
    if voisinage.dominant_era == Era.HAUSSMANNIEN:
        accents.append(FacadeAccent(
            name="iron_details",
            visual="ornate wrought-iron juliet railings",
            rationale=["voisinage haussmannien insertion"],
        ))

    return FacadeComposition(zones=zones, accents=accents)


def _reason_toiture(
    bm: dict[str, Any], plu: PluConstraints, voisinage: VoisinageContext
) -> Justification:
    """Decide the roof type. BM is authoritative (already validated), PLU is sanity check."""
    toit = bm.get("model_json", bm).get("envelope", {}).get("toiture") or {}
    bm_type = toit.get("type", "terrasse")
    vegetalisee = bool(toit.get("vegetalisee"))

    visual = _toiture_visual(bm_type, vegetalisee=vegetalisee)
    sources = ["BM envelope.toiture"]

    # Sanity flag : if PLU prescribes only sloped roofs but BM is flat, note it.
    if plu.toiture_prescribed and bm_type == "terrasse" and "terrasse" not in plu.toiture_prescribed:
        sources.append(f"⚠ PLU prescrit {plu.toiture_prescribed}, BM=terrasse")

    return Justification(
        element="toiture",
        chosen=visual,
        sources=sources,
    )


def _reason_height(bm: dict[str, Any], plu: PluConstraints) -> Justification:
    """Storey count — should respect PLU max ; flag if BM under-uses constructible."""
    env = bm.get("model_json", bm).get("envelope") or {}
    niveaux = env.get("niveaux", 0)
    storeys = max(0, int(niveaux) - 1)
    sources = ["BM envelope.niveaux"]

    chosen = f"R+{storeys} apartment building"
    if plu.hauteur_max_storeys is not None:
        if storeys >= plu.hauteur_max_storeys:
            sources.append(f"PLU max R+{plu.hauteur_max_storeys} reached")
        elif storeys < plu.hauteur_max_storeys - 1:
            sources.append(f"⚠ PLU autorise R+{plu.hauteur_max_storeys}, BM={storeys} sous-utilise")
    return Justification(element="height", chosen=chosen, sources=sources)


def _reason_rdc(
    bm: dict[str, Any], plu: PluConstraints, voisinage: VoisinageContext
) -> Justification:
    """Ground floor : commercial vs residential entrance, stone base or not."""
    niveaux = bm.get("model_json", bm).get("niveaux") or []
    rdc = next((n for n in niveaux if n.get("code") == "R+0"), None)
    rdc_use = (rdc or {}).get("usage_principal") if rdc else None
    sources = ["BM niveau R+0"]
    if rdc_use == "commerce":
        chosen = "stone-base ground floor with commercial shop windows"
        if plu.sector and plu.sector.upper().startswith("UA"):
            sources.append(f"PLU {plu.sector} linéaire commercial")
    elif rdc_use == "logements":
        chosen = "stone-base ground floor with glazed residential entrance"
    else:
        chosen = "stone-base ground floor"
    return Justification(element="rdc", chosen=chosen, sources=sources)


def _reason_balcons(
    bm: dict[str, Any], market: MarketContext
) -> Justification:
    """Balcony style — defaults to filants (modern) ; PLU rarely prescribes."""
    chosen = "cantilevered balconies on every floor with thin metal railings"
    sources = ["tendance 2024-2026 IDF résidentiel collectif"]
    if market.segment == MarketSegment.HAUT_GAMME:
        chosen = "deep cantilevered balconies with bronze-tinted glass railings"
        sources.append("positionnement haut-gamme")
    return Justification(element="balcons", chosen=chosen, sources=sources)


def _reason_context(
    plu: PluConstraints, voisinage: VoisinageContext
) -> Justification:
    """Urban context cue — describes ABOVE-the-building (sky) and BELOW (sidewalk).

    Critical : FLUX/SDXL with depth-ControlNet leaves the non-building pixels
    unconstrained (~50 % of frame). Whatever we put here, the model paints in
    that empty space. Wording like "dense Paris cityscape" makes the model
    invent an aerial cityscape and creates a fake horizon line. We instead
    describe the FOREGROUND (sidewalk) and BACKGROUND (clear sky) so the
    empty pixels resolve to a coherent ground-level scene.
    """
    parts = []
    sources = []
    # Foreground = grey concrete sidewalk + tarmac road. NO parked cars and
    # NO commercial storefronts (those make FLUX render arcades/shops at
    # the ground floor and confuse the road as a cityscape).
    if plu.sector and plu.sector.upper().startswith("UA"):
        parts.append("plain grey concrete pedestrian sidewalk in foreground, tarmac asphalt road on the ground")
        sources.append(f"PLU {plu.sector} street-level")
    else:
        parts.append("plain grey concrete sidewalk in foreground, tarmac asphalt road on the ground")
        sources.append("default IDF street-level")
    parts.append("clear smooth blue sky in background")
    parts.append("a few mature plane trees flanking the sidewalk")
    return Justification(
        element="context",
        chosen=", ".join(parts),
        sources=sources,
    )


# ---------------------------------------------------------------------------
# Material / toiture → English natural-language visual cues.
# ---------------------------------------------------------------------------

_MATERIAL_VISUAL: dict[str, str] = {
    "enduit_clair": "smooth pale cream rendered facade",
    "enduit_blanc": "smooth white rendered facade",
    "enduit_ocre": "smooth ochre rendered facade",
    "pierre_meuliere": "Parisian meulière stone facade with rough-cut texture",
    "pierre_de_taille": "ashlar limestone facade",
    "brique": "warm terracotta brick facade",
    "bardage_bois": "vertical natural wood-slat cladding facade",
    "verre": "floor-to-ceiling glass curtain wall facade",
    "metal": "anodised metal panel facade",
    "beton_brut": "exposed board-formed concrete facade",
}


def _material_visual(code: str) -> str:
    return _MATERIAL_VISUAL.get(code, code.replace("_", " "))


# BM `materiaux_rendu` codes — these are the exact architect-defined values
# coming from the project record, not PLU defaults. Each maps to a precise
# visual phrase so the FLUX prompt reproduces the actual specification.
_BM_MATERIAL_VISUAL: dict[str, str] = {
    "enduit_taloche_blanc_casse": "off-white smooth troweled render (enduit taloché blanc cassé)",
    "enduit_taloche_blanc": "white smooth troweled render",
    "enduit_taloche_ocre": "ochre smooth troweled render",
    "enduit_taloche_gris": "warm grey smooth troweled render",
    "zinc_anthracite": "anthracite-grey standing-seam zinc",
    "zinc_naturel": "natural matt zinc",
    "tuile_plate": "small flat-tile",
    "ardoise": "natural slate",
    "aluminium_anthracite_RAL7016": "anthracite RAL 7016 matt aluminium",
    "aluminium_blanc": "white matt aluminium",
    "aluminium_noir": "matt black aluminium",
    "bois_naturel": "natural wood",
}


def _bm_material_visual(code: str) -> str:
    if not code:
        return ""
    return _BM_MATERIAL_VISUAL.get(code, code.replace("_", " "))


# Compact versions for the courant zone (avoids "smooth pale cream rendered facade
# upper floors" being too long).
_MATERIAL_VISUAL_SHORT: dict[str, str] = {
    "enduit_clair": "pale cream rendered",
    "enduit_blanc": "white rendered",
    "enduit_ocre": "ochre rendered",
    "pierre_meuliere": "meulière stone",
    "pierre_de_taille": "limestone",
    "brique": "terracotta brick",
    "bardage_bois": "wood-clad",
    "verre": "glass",
    "metal": "metal-panel",
    "beton_brut": "exposed concrete",
}


def _material_visual_short(code: str) -> str:
    return _MATERIAL_VISUAL_SHORT.get(code, code.replace("_", " "))


_TOITURE_VISUAL: dict[str, str] = {
    "terrasse": "flat roof",
    "terrasse_accessible": "accessible flat roof terrace",
    "mansard": "zinc mansard roof with dormer windows",
    "deux_pans": "twin-sloped tiled roof",
    "monopente": "single-sloped roof",
    "tuile_plate": "small flat-tile roof",
    "ardoise": "slate roof",
    "zinc": "zinc roof à la française",
}


def _toiture_visual(code: str, *, vegetalisee: bool = False) -> str:
    base = _TOITURE_VISUAL.get(code, code.replace("_", " "))
    if vegetalisee:
        base += " with rooftop terrace garden and planted greenery"
    return base


# ---------------------------------------------------------------------------
# Top-level entry — builds the full ArchReasoning.
# ---------------------------------------------------------------------------

def reason_about_project(bm: dict[str, Any], project_id: str | None = None) -> ArchReasoning:
    """Run the full architectural reasoning for a project.

    Args :
        bm : raw BM payload (output of `/api/v1/projects/{id}/building_model`).
        project_id : if provided, also fetches voisinage from the backend.

    Returns :
        Fully populated `ArchReasoning` with PLU + voisinage + market +
        applicable 2025 trends + per-element justifications.
    """
    plu = fetch_plu_constraints(bm, project_id=project_id)
    voisinage = (
        fetch_voisinage_context_sync(project_id)
        if project_id else VoisinageContext()
    )
    market = _infer_market_from_bm(bm)  # placeholder — wire DVF endpoint later

    trends = select_applicable_trends(plu, voisinage, market, bm)

    facade = _compose_facade(bm, plu, voisinage, market)

    # Other per-element choices (toiture, height, context) remain — but
    # the rdc + balcons are now subsumed in the facade composition. We keep
    # toiture (for the explicit roof prompt fragment) + height + context.
    choices = {
        "toiture": _reason_toiture(bm, plu, voisinage),
        "height": _reason_height(bm, plu),
        "context": _reason_context(plu, voisinage),
    }

    reasoning = ArchReasoning(
        bm_payload=bm,
        plu=plu,
        voisinage=voisinage,
        market=market,
        trends_applied=[t.id for t in trends],
        choices=choices,
        facade=facade,
    )
    logger.info("Reasoning complete:\n%s", reasoning.explain())
    return reasoning


def _infer_market_from_bm(bm: dict[str, Any]) -> MarketContext:
    """Stub : default to moyen_gamme until we wire the DVF endpoint.

    TODO Phase 5c : query `/site/dvf?project_id=...` to derive
    median_price_eur_m2, then map to segments :
      < 4000 €/m² → bas_gamme
      4000-6500 → moyen_gamme
      6500-9000 → haut_gamme
      > 9000 → ultra_haut_gamme
    """
    return MarketContext(segment=MarketSegment.MOYEN_GAMME)
