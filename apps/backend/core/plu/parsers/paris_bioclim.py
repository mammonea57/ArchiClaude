"""Deterministic parser for PLU Bioclimatique Paris (approved 20/11/2024).

No LLM call is made. All values are hardcoded from the approved PLU tables.
This module is the authoritative source for Paris zone parameters — do NOT
approximate or interpolate values; the PLU Bioclimatique is the sole source
of truth.

Public API
----------
is_paris_bioclim(code_insee, zone_code) -> bool
parse_paris_bioclim(zone_code, code_insee) -> tuple[ParsedRules, NumericRules]
"""

from __future__ import annotations

from core.plu.schemas import NumericRules, ParsedRules

# ---------------------------------------------------------------------------
# Hardcoded gabarit data
# Source: PLU Bioclimatique Paris, approved 20/11/2024
# ---------------------------------------------------------------------------

PARIS_BIOCLIM_ZONES: dict[str, dict] = {
    "UG": {
        "hauteur_max_m": 37.0,
        "hauteur_max_niveaux": 10,  # R+9
        "emprise_max_pct": 65.0,
        "pleine_terre_min_pct": 30.0,
        "coef_biotope_min": 0.30,
        "stationnement_par_logement": 0.0,  # Paris exempts parking
        "description": "Zone urbaine générale",
    },
    "UGSU": {
        "hauteur_max_m": 31.0,
        "hauteur_max_niveaux": 8,  # R+7
        "emprise_max_pct": 60.0,
        "pleine_terre_min_pct": 35.0,
        "coef_biotope_min": 0.35,
        "stationnement_par_logement": 0.0,
        "description": "Zone urbaine générale secteur urbain sensible",
    },
    "UV": {
        "hauteur_max_m": 25.0,
        "hauteur_max_niveaux": 7,  # R+6
        "emprise_max_pct": 50.0,
        "pleine_terre_min_pct": 40.0,
        "coef_biotope_min": 0.40,
        "stationnement_par_logement": 0.0,
        "description": "Zone urbaine verte",
    },
    "UVE": {
        "hauteur_max_m": 16.0,
        "hauteur_max_niveaux": 4,  # R+3
        "emprise_max_pct": 40.0,
        "pleine_terre_min_pct": 50.0,
        "coef_biotope_min": 0.50,
        "stationnement_par_logement": 0.0,
        "description": "Zone urbaine verte étendue",
    },
    "UN": {
        "hauteur_max_m": 12.0,
        "hauteur_max_niveaux": 3,  # R+2
        "emprise_max_pct": 20.0,
        "pleine_terre_min_pct": 70.0,
        "coef_biotope_min": 0.70,
        "stationnement_par_logement": 0.0,
        "description": "Zone naturelle",
    },
    "USC": {
        "hauteur_max_m": 25.0,
        "hauteur_max_niveaux": 7,
        "emprise_max_pct": 75.0,
        "pleine_terre_min_pct": 15.0,
        "coef_biotope_min": 0.15,
        "stationnement_par_logement": 0.0,
        "description": "Zone urbaine de secteur de centralité",
    },
}

_PARIS_INSEE_PREFIX = "75"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def is_paris_bioclim(code_insee: str, zone_code: str) -> bool:
    """Return True if this zone is handled by the Paris Bioclimatique parser.

    A zone qualifies when:
    - code_insee starts with "75" (Paris arrondissements or Paris commune)
    - zone_code (normalised to uppercase) is in PARIS_BIOCLIM_ZONES

    Args:
        code_insee: INSEE commune code, e.g. "75108".
        zone_code: PLU zone code, e.g. "UG" or "ug".

    Returns:
        True if the deterministic parser covers this zone.
    """
    return (
        code_insee.startswith(_PARIS_INSEE_PREFIX)
        and zone_code.upper() in PARIS_BIOCLIM_ZONES
    )


def parse_paris_bioclim(
    zone_code: str,
    code_insee: str,
) -> tuple[ParsedRules, NumericRules]:
    """Build ParsedRules and NumericRules deterministically from PLU Bioclimatique Paris tables.

    No LLM call is made. Confidence is always 1.0.

    Args:
        zone_code: PLU zone code, e.g. "UG". Case-insensitive.
        code_insee: INSEE commune code. Must start with "75".

    Returns:
        A 2-tuple ``(ParsedRules, NumericRules)`` populated from the hardcoded table.

    Raises:
        KeyError: If zone_code is not in PARIS_BIOCLIM_ZONES.
        ValueError: If code_insee does not start with "75".
    """
    if not code_insee.startswith(_PARIS_INSEE_PREFIX):
        raise ValueError(
            f"parse_paris_bioclim: code_insee must start with '75', got {code_insee!r}"
        )

    normalised = zone_code.upper()
    if normalised not in PARIS_BIOCLIM_ZONES:
        raise KeyError(
            f"parse_paris_bioclim: zone_code {zone_code!r} not in PARIS_BIOCLIM_ZONES"
        )

    data = PARIS_BIOCLIM_ZONES[normalised]
    description = data["description"]
    hauteur_m = data["hauteur_max_m"]
    niveaux = data["hauteur_max_niveaux"]
    emprise = data["emprise_max_pct"]
    pleine_terre = data["pleine_terre_min_pct"]
    coef_biotope = data["coef_biotope_min"]
    stationnement = data["stationnement_par_logement"]

    # Build human-readable rule strings matching the standard ParsedRules fields
    parsed = ParsedRules(
        hauteur=(
            f"Hauteur maximale : {hauteur_m} m ({niveaux} niveaux — "
            f"{description}). Source : PLU Bioclimatique Paris approuvé le 20/11/2024."
        ),
        emprise=(
            f"Emprise au sol maximale : {emprise} %. "
            f"Source : PLU Bioclimatique Paris approuvé le 20/11/2024."
        ),
        implantation_voie=None,
        limites_separatives=None,
        stationnement=(
            f"Stationnement : {stationnement} place(s) par logement "
            f"(Paris dispense les projets de l'obligation de stationnement). "
            f"Source : PLU Bioclimatique Paris approuvé le 20/11/2024."
        ),
        lls=None,
        espaces_verts=(
            f"Pleine terre minimale : {pleine_terre} %. "
            f"Coefficient de biotope minimum : {coef_biotope}. "
            f"Source : PLU Bioclimatique Paris approuvé le 20/11/2024."
        ),
        destinations=None,
        pages={},
        source="paris_bioclim_parser",
        cached=False,
    )

    numeric = NumericRules(
        hauteur_max_m=hauteur_m,
        hauteur_max_niveaux=niveaux,
        emprise_max_pct=emprise,
        pleine_terre_min_pct=pleine_terre,
        coef_biotope_min=coef_biotope,
        stationnement_par_logement=stationnement,
        extraction_confidence=1.0,
        extraction_warnings=[],
    )

    return parsed, numeric
