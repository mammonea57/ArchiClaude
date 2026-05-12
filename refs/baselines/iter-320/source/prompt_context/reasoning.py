"""Architectural reasoning data model.

The render is the visual conclusion of an architectural reasoning, NOT a
texturing of a passive geometric shape. This module captures that reasoning
as a structured `ArchReasoning` object so :

  1. Each design choice (facade material, roof type, balcony style…) carries
     its **why** — citing PLU article, neighbourhood typology, or 2025 trend.
  2. The synthesizer can render the reasoning into a precise prompt.
  3. The frontend can later display the reasoning side-by-side with the render
     ("here's why the AI suggests this design").
  4. Any audit / regression test can introspect what drove a render.

This is what makes ArchiClaude an "augmented architectural advice" tool
instead of a passive viz of a BM.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Era(str, Enum):
    """Architectural era buckets used for neighbourhood typology inference.

    Mapped from construction year. Each era has signature materials + roofs
    that the synthesizer uses as cues when the project should *insert* in this
    context.
    """
    HAUSSMANNIEN = "haussmannien"           # 1850-1914
    FAUBOURG_1900 = "faubourg_1900"          # 1900-1939 — petit faubourg moderne
    ART_DECO = "art_deco"                    # 1920-1939
    MODERNE_APRES_GUERRE = "moderne_apres_guerre"   # 1945-1980 — barres / tours
    CONTEMPORAIN_80_2000 = "contemporain_80_2000"   # 1980-2000 — postmoderne
    CONTEMPORAIN_RECENT = "contemporain_recent"     # 2000-2015 — RT2005 era
    CONTEMPORAIN_NEUF = "contemporain_neuf"         # 2015+ — RE2020 era
    INCONNU = "inconnu"


class MarketSegment(str, Enum):
    """Market positioning derived from DVF + commune."""
    HAUT_GAMME = "haut_gamme"
    MOYEN_GAMME = "moyen_gamme"
    BAS_GAMME = "bas_gamme"
    SOCIAL = "social"
    INCONNU = "inconnu"


@dataclass
class PluConstraints:
    """Hard regulatory constraints from the parcel's PLU article."""
    sector: str | None = None              # e.g. "UA1"
    emprise_max_pct: float | None = None    # e.g. 0.80 (80%)
    hauteur_max_m: float | None = None      # e.g. 18.0
    hauteur_max_storeys: int | None = None  # e.g. 5 (R+5)
    materials_prescribed: list[str] = field(default_factory=list)  # e.g. ["pierre_meuliere", "enduit_clair"]
    toiture_prescribed: list[str] = field(default_factory=list)    # e.g. ["zinc", "tuile_plate"]
    retrait_limites_m: float | None = None   # 3 m standard
    pleine_terre_pct: float | None = None    # min 10%
    article_refs: list[str] = field(default_factory=list)  # e.g. ["UA1.9", "UA1.10", "UA1.11"]


@dataclass
class VoisinageContext:
    """Aggregated typology of the nearby buildings (BDTopo + DPE)."""
    n_buildings: int = 0
    median_height_m: float | None = None
    median_storeys: int | None = None
    dominant_era: Era = Era.INCONNU
    era_distribution: dict[Era, int] = field(default_factory=dict)
    dominant_usage: str | None = None      # "Résidentiel", "Commercial", etc.
    likely_materials: list[str] = field(default_factory=list)  # inferred from era


@dataclass
class MarketContext:
    """Market positioning derived from DVF (recent transaction prices)."""
    segment: MarketSegment = MarketSegment.INCONNU
    median_price_eur_m2: float | None = None
    typology_demand: dict[str, float] = field(default_factory=dict)  # T2/T3/T4 share


@dataclass
class Justification:
    """The 'why' for a single design choice, citing its grounding sources."""
    element: str          # "facade_main", "toiture", "rdc", "balcons", "context"
    chosen: str           # the design choice in plain natural language
    sources: list[str]    # e.g. ["PLU UA-11", "voisinage 1900-1925", "tendance 2025 IDF"]
    confidence: float = 1.0  # 0..1, lowered when conflicting signals


# ---------------------------------------------------------------------------
# Layered facade composition — Phase 5d
#
# A single "enduit_clair" everywhere produces the "couleur sable uni" effect
# that ABF + PLU UA1 would refuse. Real IDF residential facades are stratified
# vertically (RDC noble, courant ton clair, attique retrait) with horizontal
# accents (corniches, bandeaux, garde-corps) tying it together.
# ---------------------------------------------------------------------------

@dataclass
class FacadeZone:
    """One vertical zone of the facade (RDC, courant, attique, …)."""
    zone_id: str          # "rdc" | "courant" | "attique" | "entrance_volume"
    height_label: str     # human label: "ground floor" / "R+1 to R+4" / "R+5 setback"
    material_visual: str  # natural-language visual cue, e.g. "rough-cut meulière stone with terracotta brick accents"
    rationale: list[str]  # justification sources

    def short(self) -> str:
        """Concise prompt fragment — material_visual already encodes the zone."""
        return self.material_visual


@dataclass
class FacadeAccent:
    """Horizontal or punctual detail running across the facade."""
    name: str             # "balcony_railings", "cornice", "window_surrounds"
    visual: str           # natural-language cue
    rationale: list[str]


@dataclass
class FacadeComposition:
    """Stratified facade composition — the real per-zone material spec.

    Replaces the legacy single-material `Justification(element="facade_main")`.
    The synthesizer renders zones top-to-bottom or critical-first to fit
    inside CLIP's 77-token budget.
    """
    zones: list[FacadeZone]
    accents: list[FacadeAccent]

    def to_prompt_phrase(self, max_zones: int = 3, max_accents: int = 2) -> str:
        """Render compactly. Limit zones/accents to keep the prompt within budget."""
        parts: list[str] = []
        for z in self.zones[:max_zones]:
            parts.append(z.short())
        for a in self.accents[:max_accents]:
            parts.append(a.visual)
        return ", ".join(parts)

    def all_justifications(self) -> list[Justification]:
        """Flatten to per-element Justification list for the reasoning explain trace."""
        out: list[Justification] = []
        for z in self.zones:
            out.append(Justification(
                element=f"facade_{z.zone_id}",
                chosen=z.material_visual,
                sources=z.rationale,
            ))
        for a in self.accents:
            out.append(Justification(
                element=f"accent_{a.name}",
                chosen=a.visual,
                sources=a.rationale,
            ))
        return out


@dataclass
class ArchReasoning:
    """Complete architectural reasoning for a single render.

    Built by the reasoner (`reasoner.py`) from the BM + PLU + voisinage + market
    + 2025 trends, then consumed by the synthesizer to produce the prompt.
    """
    bm_payload: dict[str, Any]            # raw BM (kept for downstream display)
    plu: PluConstraints
    voisinage: VoisinageContext
    market: MarketContext
    trends_applied: list[str] = field(default_factory=list)
    choices: dict[str, Justification] = field(default_factory=dict)
    facade: FacadeComposition | None = None  # Phase 5d : stratified facade

    def explain(self) -> str:
        """Human-readable trace — used in logs + the future frontend reasoning panel."""
        lines = [f"PLU sector: {self.plu.sector} (max emprise {self.plu.emprise_max_pct}, "
                 f"max H {self.plu.hauteur_max_m}m, R+{self.plu.hauteur_max_storeys})"]
        lines.append(f"Voisinage: {self.voisinage.n_buildings} buildings, "
                     f"dominant era {self.voisinage.dominant_era.value}, "
                     f"median {self.voisinage.median_storeys} storeys")
        lines.append(f"Market: {self.market.segment.value}, "
                     f"~{self.market.median_price_eur_m2 or '?'}€/m²")
        lines.append(f"2025 trends applied: {', '.join(self.trends_applied) or '(none)'}")
        if self.facade:
            lines.append("Facade composition:")
            for z in self.facade.zones:
                lines.append(f"  ▸ {z.zone_id} ({z.height_label}): {z.material_visual}")
                lines.append(f"      ←  {', '.join(z.rationale)}")
            for a in self.facade.accents:
                lines.append(f"  ✦ {a.name}: {a.visual}  ←  {', '.join(a.rationale)}")
        lines.append("Other choices:")
        for k, j in self.choices.items():
            lines.append(f"  • {k}: {j.chosen}  ←  {', '.join(j.sources)}")
        return "\n".join(lines)
