"""ArchiClaude material library — maps internal names to Polyhaven assets.

Each entry is a `MaterialDef`. To add a new material, append to
MATERIAL_LIBRARY and re-run `download_polyhaven.py` then
`import_to_ue5.py`. Materials with no `polyhaven_slug` fall back to a
flat sRGB color (still useful when no good Polyhaven match exists, e.g.
zinc anthracite which Polyhaven doesn't cover well).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class MaterialDef:
    name: str
    polyhaven_slug: Optional[str] = None
    tile_meters: float = 2.0
    fallback_color: tuple = (0.7, 0.7, 0.7)
    tint: Optional[tuple] = None
    roughness_scale: float = 1.0
    notes: str = ""


MATERIAL_LIBRARY: dict[str, MaterialDef] = {
    "enduit_blanc": MaterialDef(
        name="enduit_blanc",
        polyhaven_slug="painted_plaster_wall",
        tile_meters=2.0,
        fallback_color=(0.92, 0.86, 0.74),
        tint=(0.98, 0.95, 0.88),
        notes="Parisian facade plaster, warm white",
    ),
    "brique_rouge": MaterialDef(
        name="brique_rouge",
        polyhaven_slug="red_brick",
        tile_meters=1.5,
        fallback_color=(0.55, 0.22, 0.12),
        notes="Standard red brick wall",
    ),
    "asphalte": MaterialDef(
        name="asphalte",
        polyhaven_slug="asphalt_02",
        tile_meters=4.0,
        fallback_color=(0.16, 0.16, 0.16),
        notes="Weathered street asphalt",
    ),
    "pavers_concrete": MaterialDef(
        name="pavers_concrete",
        polyhaven_slug="concrete_floor_painted",
        tile_meters=2.0,
        fallback_color=(0.58, 0.58, 0.55),
        notes="Sidewalk concrete pavers",
    ),
    "pierre_taille": MaterialDef(
        name="pierre_taille",
        polyhaven_slug="beige_wall_001",
        tile_meters=2.0,
        fallback_color=(0.82, 0.74, 0.58),
        tint=(0.95, 0.90, 0.78),
        notes="Cream limestone wall (pierre de taille parisienne)",
    ),
    "zinc_anthracite": MaterialDef(
        name="zinc_anthracite",
        polyhaven_slug=None,
        tile_meters=1.0,
        fallback_color=(0.16, 0.16, 0.18),
        roughness_scale=0.4,
        notes="Dark zinc panel — no good Polyhaven match, fallback only",
    ),
    "balcon_concrete": MaterialDef(
        name="balcon_concrete",
        polyhaven_slug="concrete_wall_003",
        tile_meters=2.0,
        fallback_color=(0.94, 0.92, 0.88),
        notes="Smooth balcony concrete",
    ),
    "vegetation": MaterialDef(
        name="vegetation",
        polyhaven_slug="aerial_grass_rock",
        tile_meters=1.5,
        fallback_color=(0.28, 0.52, 0.18),
        notes="Lawn / garden ground (top-down)",
    ),
    "voisin": MaterialDef(
        name="voisin",
        polyhaven_slug="cracked_concrete_wall",
        tile_meters=2.5,
        fallback_color=(0.50, 0.45, 0.38),
        notes="Worn plaster — neighbouring buildings",
    ),
    "terre_neutre": MaterialDef(
        name="terre_neutre",
        polyhaven_slug="forest_ground_04",
        tile_meters=3.0,
        fallback_color=(0.42, 0.40, 0.36),
        notes="Bare ground / earth",
    ),
    "pierre_kerb": MaterialDef(
        name="pierre_kerb",
        polyhaven_slug="concrete_floor_painted",
        tile_meters=1.5,
        fallback_color=(0.78, 0.74, 0.68),
        tint=(0.85, 0.82, 0.76),
        notes="Kerb / curb stone (reuse paving texture)",
    ),
    "bois_porte": MaterialDef(
        name="bois_porte",
        polyhaven_slug="weathered_brown_planks",
        tile_meters=1.0,
        fallback_color=(0.28, 0.15, 0.08),
        notes="Traditional wooden door planks",
    ),
    "fer_forge": MaterialDef(
        name="fer_forge",
        polyhaven_slug=None,
        tile_meters=0.5,
        fallback_color=(0.04, 0.04, 0.05),
        roughness_scale=0.7,
        notes="Black wrought iron — too specific, fallback only",
    ),
}
