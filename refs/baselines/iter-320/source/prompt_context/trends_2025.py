"""Current French residential architecture trends (vintage 2025-2026).

What promoters in IDF actually build *today* — Cogedim, Vinci Immobilier,
Bouygues Immobilier, Pichet, Eiffage Immobilier, Kaufman & Broad. The list
should be reviewed every ~12 months as fashions evolve and the RE2020
constraint reshapes what's economically + regulatory viable.

Each trend has :
  - id : stable code
  - prompt_cue : the concrete visual phrase added to the SD/SDXL prompt
  - applies_when : a predicate over the (PluConstraints, VoisinageContext,
    MarketContext, BM) tuple — only injected if relevant to this site.

Trend versioning : the constant `TRENDS_VINTAGE` records the date of the
last review. When promoteur galleries change significantly, bump it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .reasoning import Era, MarketSegment, PluConstraints, VoisinageContext, MarketContext

TRENDS_VINTAGE = "2026-04"


@dataclass
class Trend:
    id: str
    prompt_cue: str
    description: str
    applies_when: Callable[[PluConstraints, VoisinageContext, MarketContext, dict[str, Any]], bool]


def _has_terrasse_vegetalisee(_p, _v, _m, bm) -> bool:
    """Trend "rooftop garden + planted greenery" — RE2020 + PLU bonus driver."""
    toit = bm.get("model_json", bm).get("envelope", {}).get("toiture", {})
    return toit.get("type") == "terrasse" and bool(toit.get("vegetalisee"))


def _is_haussmannien_context(_p, v: VoisinageContext, _m, _bm) -> bool:
    """Inserts in haussmannien/faubourg context → adopt limestone+mansard cues."""
    return v.dominant_era in (Era.HAUSSMANNIEN, Era.FAUBOURG_1900)


def _is_dense_urban_centre(p: PluConstraints, _v, _m, _bm) -> bool:
    """UA1 / UA / UC sectors with high emprise + RDC commercial linéaire."""
    return (p.sector or "").upper().startswith("UA") and (p.emprise_max_pct or 0) >= 0.7


def _is_haut_gamme(_p, _v, m: MarketContext, _bm) -> bool:
    return m.segment == MarketSegment.HAUT_GAMME


def _is_moyen_gamme_or_more(_p, _v, m: MarketContext, _bm) -> bool:
    return m.segment in (MarketSegment.HAUT_GAMME, MarketSegment.MOYEN_GAMME)


# ---------------------------------------------------------------------------
# The trends list. Each entry is consulted by the reasoner ; only those whose
# applies_when returns True end up in the final prompt.
# ---------------------------------------------------------------------------

CURRENT_TRENDS: list[Trend] = [
    Trend(
        id="rooftop_planted_terrasse",
        prompt_cue="flat roof terrace with planted vegetation, mature shrubs and small trees, biophilic design",
        description="RE2020 + label E+C- → toit végétalisé est devenu standard sur le neuf 2024+",
        applies_when=_has_terrasse_vegetalisee,
    ),
    Trend(
        id="balcons_filants",
        prompt_cue="continuous cantilevered balconies on every floor, thin metal railings",
        description="Tendance majeure 2020+ — balcons filants généreux comme valorisation T3-T5",
        applies_when=lambda p, v, m, bm: True,  # quasi-universel sur logements collectifs neufs
    ),
    Trend(
        id="rdc_commercial_pierre",
        prompt_cue="ground floor with stone-base commercial frontage, shop windows with bronze frames, awnings",
        description="UA dense → linéaire commercial ton noble pour valoriser la rue",
        # Only apply when the BM explicitly declares the RDC as commerce.
        # Pure residential projects must not get shop-window cues — FLUX
        # otherwise renders the building as a strip mall.
        applies_when=lambda p, v, m, bm: (
            _is_dense_urban_centre(p, v, m, bm)
            and any(
                (n.get("usage_principal") == "commerce")
                for n in (bm.get("model_json", bm).get("niveaux") or [])
                if n.get("code") == "R+0"
            )
        ),
    ),
    Trend(
        id="brique_terracotta_accent",
        prompt_cue="terracotta brick accents on the entrance volume and ground floor base",
        description="Tendance 2024-2026 — briquettes pour rappeler le faubourg + casser l'enduit massif",
        applies_when=_is_haussmannien_context,
    ),
    Trend(
        id="mansard_zinc_attique",
        prompt_cue="zinc-cladded set-back top floor with dormer windows, attic-style",
        description="Quand le PLU autorise le gabarit-enveloppe combles, on plafonne en mansard zinc",
        applies_when=lambda p, v, m, bm: (
            "zinc" in (p.toiture_prescribed or [])
            and v.dominant_era in (Era.HAUSSMANNIEN, Era.FAUBOURG_1900)
        ),
    ),
    Trend(
        id="bardage_bois_attique",
        prompt_cue="natural wood-slat cladding on the set-back top floor",
        description="Bardage bois en R+N quand toiture terrasse + contexte contemporain",
        applies_when=lambda p, v, m, bm: (
            "bardage_bois" in v.likely_materials
            and bm.get("model_json", bm).get("envelope", {}).get("toiture", {}).get("type") == "terrasse"
        ),
    ),
    Trend(
        id="grandes_baies_juliet",
        prompt_cue="floor-to-ceiling windows with juliet balconies and slim aluminium frames",
        description="Standard sur résidentiel haut/moyen-gamme 2020+ — luminosité + valorisation pièces",
        applies_when=_is_moyen_gamme_or_more,
    ),
    Trend(
        id="entree_pierre_noble",
        prompt_cue="stone-clad entrance volume with double-height glazed door, bronze details",
        description="Entrée noble = signature perçue haut-gamme",
        applies_when=_is_haut_gamme,
    ),
    Trend(
        id="contexte_arbre_mature",
        prompt_cue="mature plane trees and street furniture in foreground",
        description="Tendance plan paysager renforcé par PLU bonus pleine terre + lutte îlot de chaleur",
        applies_when=lambda p, v, m, bm: (p.pleine_terre_pct or 0) >= 0.10,
    ),
]


def select_applicable_trends(
    plu: PluConstraints,
    voisinage: VoisinageContext,
    market: MarketContext,
    bm: dict[str, Any],
) -> list[Trend]:
    """Filter the trends down to those that apply to the current site."""
    return [t for t in CURRENT_TRENDS if t.applies_when(plu, voisinage, market, bm)]
