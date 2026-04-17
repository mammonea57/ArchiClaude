"""PMR (Personnes à Mobilité Réduite) accessibility obligations.

References:
  - Loi du 11 février 2005 (accessibilité des ERP et logements)
  - Décret n° 2015-1170 du 17 septembre 2015 (logements neufs)
  - Arrêté du 24 décembre 2015 (logements collectifs neufs)

Rules applied (collectif neuf):
  - Ascenseur obligatoire dès R+3 (4 niveaux total incl. RDC).
  - Surface de circulation liée à l'ascenseur : gaine + palier ≈ 15 m²/niveau.
  - Places PMR : ceil(nb_places × 0.02), minimum 1 si nb_places > 0.
"""

from __future__ import annotations

import math


def compute_pmr(
    *,
    nb_niveaux: int,
    nb_places: int,
    destination: str,
) -> tuple[bool, float, int]:
    """Compute PMR accessibility obligations.

    Args:
        nb_niveaux: Total storey count including RDC (R+3 → 4).
        nb_places:  Total number of parking spaces in the programme.
        destination: Building use (informational, rules are the same for
            all residential uses in v1).

    Returns:
        A tuple ``(ascenseur_obligatoire, surface_circulations_m2, nb_places_pmr)``
        where:
          - ascenseur_obligatoire: True when nb_niveaux ≥ 4 (R+3 and above).
          - surface_circulations_m2: Estimated lift shaft + landing area
            (15 m² × nb_niveaux when lift required, 0 otherwise).
          - nb_places_pmr: ceil(nb_places × 0.02), min 1 if nb_places > 0.
    """
    ascenseur_obligatoire = nb_niveaux >= 4

    if ascenseur_obligatoire:
        surface_circulations_m2 = 15.0 * nb_niveaux
    else:
        surface_circulations_m2 = 0.0

    if nb_places > 0:
        nb_places_pmr = max(1, math.ceil(nb_places * 0.02))
    else:
        nb_places_pmr = 0

    return ascenseur_obligatoire, surface_circulations_m2, nb_places_pmr
