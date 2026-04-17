"""Bibliothèque architecturale — trames BA, épaisseurs mur, circulations, ascenseurs.

Values are calibrated for IDF residential/office construction per DTU and PMR regulations.
All linear dimensions in metres, areas in m².
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Trames béton armé (axe à axe, m)
# ---------------------------------------------------------------------------

TRAMES_BA: dict[str, float] = {
    "logement": 5.40,   # trame courante logement collectif IDF
    "bureaux": 7.50,    # trame bureaux open-space
    "parking": 5.00,    # trame place de stationnement (2× 2.50m)
    "commerce": 6.00,   # trame rez-de-chaussée commercial
}

# ---------------------------------------------------------------------------
# Épaisseurs mur (m)
# ---------------------------------------------------------------------------

EPAISSEURS_MUR: dict[str, float] = {
    "porteur": 0.20,       # voile BA ou maçonnerie porteur
    "facade_ite": 0.38,    # façade avec ITE (voile 0.20 + isolant 0.14 + enduit 0.04)
    "cloison": 0.07,       # cloison légère plaque de plâtre BA13
    "refend": 0.18,        # mur de refend non porteur
    "pignon": 0.25,        # mur pignon mitoyen
    "sous_sol": 0.25,      # voile de sous-sol (poussée terre)
}

# ---------------------------------------------------------------------------
# Circulations (largeurs minimales, m)
# ---------------------------------------------------------------------------

CIRCULATIONS: dict[str, float] = {
    "couloir_pmr": 1.20,   # couloir PMR (art. 14 arrêté 2015)
    "escalier": 1.00,      # escalier encloisonné ERP/habitat collectif
    "porte_pmr": 0.90,     # passage libre PMR (porte 0.93m PF 0.90m)
    "couloir_standard": 0.90,  # couloir privatif logement
    "rampe_pmr": 1.40,     # rampe PMR — largeur libre
    "sas_pmr": 1.50,       # sas d'entrée PMR (carré 1.50×1.50m)
}

# ---------------------------------------------------------------------------
# Ascenseurs
# ---------------------------------------------------------------------------

ASCENSEURS: dict[str, float] = {
    "gaine_m2": 4.0,              # surface gaine ascenseur standard
    "cabine_pmr_largeur_m": 1.10,  # cabine PMR largeur intérieure
    "cabine_pmr_profondeur_m": 1.40,  # cabine PMR profondeur intérieure
    "gaine_pmr_largeur_m": 1.60,   # largeur gaine pour cabine PMR
    "gaine_pmr_profondeur_m": 1.80, # profondeur gaine pour cabine PMR
    "palier_m": 1.50,             # dégagement pallier devant portes
}
