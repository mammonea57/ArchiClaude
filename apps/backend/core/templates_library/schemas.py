"""Pydantic schemas for apartment distribution templates."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TemplateSource(str, Enum):
    MANUAL = "manual"
    SCRAPED = "scraped"
    LLM_GEN = "llm_gen"
    LLM_AUGMENTED = "llm_augmented"


class DimensionsGrille(BaseModel):
    largeur_min_m: float = Field(gt=0)
    largeur_max_m: float = Field(gt=0)
    profondeur_min_m: float = Field(gt=0)
    profondeur_max_m: float = Field(gt=0)
    adaptable_3x3: bool = True


class AbstractRoom(BaseModel):
    id: str
    type: str  # RoomType string
    area_ratio: float = Field(gt=0, le=1.0)
    bounds_cells: list[list[int]]


class AbstractWall(BaseModel):
    type: str  # WallType string
    from_cell: list[int]  # [col, row]
    to_cell: list[int]
    side: str  # "north" | "south" | "east" | "west"


class AbstractOpening(BaseModel):
    type: str  # OpeningType string
    wall_idx: int
    position_ratio: float = Field(ge=0, le=1.0)
    swing: str | None = None
    sur_piece: str | None = None
    largeur_min_cm: int | None = None


class ReglementaireOk(BaseModel):
    pmr_rotation_150: bool = False
    pmr_passages_80: bool = False
    ventilation_traversante: bool = False
    lumiere_naturelle_toutes_pieces_vie: bool = False


class Rating(BaseModel):
    manual_votes: float = 0.0
    usage_count: int = 0
    success_rate: float = 0.0


class SourceMeta(BaseModel):
    author: str | None = None
    scraped_from_pc: str | None = None
    llm_prompt_hash: str | None = None


class Template(BaseModel):
    id: str
    source: TemplateSource
    source_meta: SourceMeta = Field(default_factory=SourceMeta)
    typologie: str  # Typologie string — use string (not Enum) to allow both T2/T3/... and Studio
    surface_shab_range: list[float] = Field(min_length=2, max_length=2)
    orientation_compatible: list[str]
    position_dans_etage: list[str]
    dimensions_grille: DimensionsGrille
    topologie: dict[str, Any]  # {rooms: [...], walls_abstract: [...], openings_abstract: [...]}
    furniture_defaults: dict[str, list[str]] = Field(default_factory=dict)
    reglementaire_ok: ReglementaireOk
    tags: list[str] = Field(default_factory=list)
    rating: Rating = Field(default_factory=Rating)
    embedding: list[float] | None = None
    preview_svg: str | None = None
