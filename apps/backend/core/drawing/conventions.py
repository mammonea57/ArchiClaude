"""Normothèque SVG — traits, hachures, polices, symboles, cartouche defaults.

All values follow NF EN ISO 128 / DTU conventions adapted for French PC dossiers.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Trait épaisseurs (mm, stroke-width SVG)
# ---------------------------------------------------------------------------

TRAIT_EPAISSEURS: dict[str, float] = {
    "mur_porteur": 0.50,
    "cloison": 0.18,
    "contour_parcelle": 0.70,
    "axe": 0.18,
    "cote": 0.13,
    "contour_dalle": 0.35,
    "seuil": 0.25,
    "voirie": 0.35,
    "limite_zone": 0.50,
}

# ---------------------------------------------------------------------------
# Hachures (SVG pattern id + couleur de fond)
# ---------------------------------------------------------------------------

HACHURES: dict[str, dict[str, str]] = {
    "beton": {
        "pattern": "hachure_beton",
        "color": "#d4d4d4",
    },
    "bois": {
        "pattern": "hachure_bois",
        "color": "#c8a46e",
    },
    "terrain_naturel": {
        "pattern": "hachure_terrain",
        "color": "#a8c880",
    },
    "isolation": {
        "pattern": "hachure_isolation",
        "color": "#f5e6a0",
    },
    "maconnerie": {
        "pattern": "hachure_maconnerie",
        "color": "#e0c8b0",
    },
    "vide_sanitaire": {
        "pattern": "hachure_vide",
        "color": "#f0f0f0",
    },
}

# ---------------------------------------------------------------------------
# Polices
# ---------------------------------------------------------------------------

POLICES: dict[str, dict[str, object]] = {
    "titre": {
        "family": "Playfair Display",
        "size_pt": 14,
        "weight": "bold",
    },
    "sous_titre": {
        "family": "Playfair Display",
        "size_pt": 11,
        "weight": "normal",
    },
    "corps": {
        "family": "Inter",
        "size_pt": 9,
        "weight": "normal",
    },
    "cote": {
        "family": "Inter",
        "size_pt": 7,
        "weight": "normal",
    },
    "legende": {
        "family": "Inter",
        "size_pt": 8,
        "weight": "normal",
    },
}

# ---------------------------------------------------------------------------
# Symboles (SVG <use> id)
# ---------------------------------------------------------------------------

SYMBOLES: dict[str, dict[str, str]] = {
    "nord": {
        "svg_id": "sym_nord",
        "description": "Rose des vents — indication du nord géographique",
    },
    "arbre": {
        "svg_id": "sym_arbre",
        "description": "Arbre — vue en plan",
    },
    "porte": {
        "svg_id": "sym_porte",
        "description": "Porte — quart de cercle ouverture 90°",
    },
    "escalier": {
        "svg_id": "sym_escalier",
        "description": "Escalier — marches et flèche de montée",
    },
    "ascenseur": {
        "svg_id": "sym_ascenseur",
        "description": "Ascenseur — gaine avec cabine PMR",
    },
    "place_stationnement": {
        "svg_id": "sym_parking",
        "description": "Place de stationnement — 2.50×5.00m",
    },
}

# ---------------------------------------------------------------------------
# Cartouche defaults
# ---------------------------------------------------------------------------

CARTOUCHE_DEFAULTS: dict[str, float] = {
    "width_mm": 180.0,
    "height_mm": 40.0,
}
