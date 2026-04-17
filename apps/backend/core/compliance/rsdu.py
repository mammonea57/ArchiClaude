"""RSDU — Règlement Sanitaire Départemental Unifié (IDF standard obligations).

In Île-de-France, the following obligations apply to all new residential
constructions regardless of the specific PLU zone:

1. Local vélos     — 1 place/logement minimum (loi LOM 2019, décret 2021-837)
2. Local poubelles — tri sélectif obligatoire (Règlement Sanitaire Dép.)
3. VMC             — ventilation mécanique contrôlée (arrêté 24/03/1982)
4. Garde-corps     — balcons et terrasses conformes NF P01-012 / EN 13200

These are always applicable in IDF new builds; no parameters needed.
"""

from __future__ import annotations

_RSDU_IDF_OBLIGATIONS: list[str] = [
    "Local vélos : 1 place par logement minimum (loi LOM 2019, décret 2021-837).",
    "Local poubelles : tri sélectif obligatoire (Règlement Sanitaire Départemental IDF).",
    "Ventilation mécanique contrôlée (VMC) : obligatoire dans tous les logements neufs (arrêté 24/03/1982).",
    "Garde-corps balcons et terrasses : conformes NF P01-012 / EN 13200 (hauteur min. 1,0 m).",
]


def compute_rsdu_obligations() -> list[str]:
    """Return the standard RSDU IDF obligations applicable to all new builds.

    Returns:
        List of exactly 4 obligation strings (always non-empty).
    """
    return list(_RSDU_IDF_OBLIGATIONS)
