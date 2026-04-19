"""Materials catalog — 70 materials for PCMI6 rendering."""
from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache, lru_cache
from pathlib import Path

_DATA_PATH = Path(__file__).parent / "materials_data.json"


@dataclass(frozen=True)
class Material:
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


@lru_cache(maxsize=1)
def load_materials() -> list[Material]:
    """Load the full materials catalog from JSON data file."""
    with open(_DATA_PATH) as f:
        raw = json.load(f)
    return [Material(**item) for item in raw]


@cache
def get_material(material_id: str) -> Material | None:
    """Get a material by its ID, or None if not found."""
    for m in load_materials():
        if m.id == material_id:
            return m
    return None


def materials_by_category(category: str) -> list[Material]:
    """Get all materials in a given category."""
    return [m for m in load_materials() if m.categorie == category]
