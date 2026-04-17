"""Pydantic schemas for PLU rule extraction — ParsedRules, RuleFormula, Bande, NumericRules."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ParsedRules(BaseModel):
    """Textual rules extracted verbatim from a PLU PDF by the AI parser."""

    hauteur: str | None = None
    emprise: str | None = None
    implantation_voie: str | None = None
    limites_separatives: str | None = None
    stationnement: str | None = None
    lls: str | None = None
    espaces_verts: str | None = None
    destinations: str | None = None
    pages: dict[str, int | None] = Field(default_factory=dict)
    source: Literal["ai_parsed", "cache", "manual", "paris_bioclim_parser"] = "ai_parsed"
    cached: bool = False


class RuleFormula(BaseModel):
    """A parametric formula describing a PLU rule (e.g. recul = H/2)."""

    expression: str  # e.g. "H/2", "0.7*S"
    min_value: float | None = None
    max_value: float | None = None
    units: str = "m"
    raw_text: str = ""


class Bande(BaseModel):
    """A constructible band defined by depth from road alignment."""

    name: Literal["principale", "secondaire", "fond"]
    hauteur_max_m: float | None = None
    emprise_max_pct: float | None = None
    depth_from_voie_m: float | None = None


class NumericRules(BaseModel):
    """Numeric values extracted from ParsedRules for the feasibility engine."""

    # Heights
    hauteur_max_m: float | None = None
    hauteur_max_niveaux: int | None = None
    hauteur_max_ngf: float | None = None
    hauteur_facade_m: float | None = None

    # Footprint
    emprise_max_pct: float | None = None

    # Setbacks
    recul_voirie_m: float | None = None
    recul_voirie_formula: RuleFormula | None = None
    recul_limite_lat_m: float | None = None
    recul_limite_lat_formula: RuleFormula | None = None
    recul_fond_m: float | None = None
    recul_fond_formula: RuleFormula | None = None

    # Floor area
    cos: float | None = None
    sdp_max_m2: float | None = None

    # Green / biotope
    pleine_terre_min_pct: float = 0.0
    surface_vegetalisee_min_pct: float | None = None
    coef_biotope_min: float | None = None

    # Parking
    stationnement_par_logement: float | None = None
    stationnement_par_m2_bureau: float | None = None
    stationnement_par_m2_commerce: float | None = None

    # Constructible bands
    bandes_constructibles: list[Bande] | None = None

    # Metadata
    article_refs: dict[str, str] = Field(default_factory=dict)
    extraction_confidence: float = 0.0
    extraction_warnings: list[str] = Field(default_factory=list)
