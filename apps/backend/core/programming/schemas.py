"""Schemas and constants for programming/envelope modules.

All geometries must be in Lambert-93 (EPSG:2154, metric CRS).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from shapely.geometry import Point, Polygon

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TRAME_BA_M = 5.40  # standard BA grid module (metres)
SURFACE_NOYAU_M2 = 35.0  # typical vertical circulation core footprint

SURFACE_CENTRE: dict[str, float] = {
    "T1": 27.0,
    "T2": 42.0,
    "T3": 58.0,
    "T4": 77.0,
    "T5": 95.0,
}

TRAMES_PAR_TYPO: dict[str, float] = {
    "T1": 1.0,
    "T2": 1.5,
    "T3": 2.0,
    "T4": 2.5,
    "T5": 3.0,
}

# ---------------------------------------------------------------------------
# Segment classification
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClassifiedSegment:
    """A single boundary segment of a parcelle with its classification."""

    start: tuple[float, float]
    end: tuple[float, float]
    segment_type: Literal["voirie", "separative", "fond"]
    recul_m: float
    recul_formula: str | None = None
    longueur_m: float = 0.0


# ---------------------------------------------------------------------------
# Envelope / niveau footprints
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NiveauFootprint:
    """Constructible footprint for one storey level."""

    niveau: int
    hauteur_plancher_m: float
    footprint: Polygon
    surface_m2: float


# ---------------------------------------------------------------------------
# Programming scenarios
# ---------------------------------------------------------------------------


@dataclass
class Scenario:
    """A single programming scenario output from the solver."""

    nom: str
    mix_utilise: dict[str, float]
    mix_ajustements: list[str]
    sdp_m2: float
    nb_logements: int
    nb_par_typologie: dict[str, int]
    nb_niveaux: int
    footprints_par_niveau: list[NiveauFootprint]
    nb_places_stationnement: int
    nb_places_pmr: int
    variante_acces_separes: bool = False
    perte_sdp_acces_separes_m2: float | None = None
    marge_pct: float = 100.0


@dataclass
class SolverResult:
    """Collection of scenarios with a recommended scenario."""

    scenarios: list[Scenario]
    scenario_recommande: str
    raison_recommandation: str


# ---------------------------------------------------------------------------
# Distribution / layout
# ---------------------------------------------------------------------------


@dataclass
class Piece:
    """A room inside a logement."""

    nom: str
    surface_m2: float
    largeur_m: float
    longueur_m: float


@dataclass
class Logement:
    """A single dwelling unit."""

    id: str
    typologie: str
    surface_m2: float
    niveau: int
    position: str
    exposition: str
    est_lls: bool
    pieces: list[Piece]
    geometry: Polygon


@dataclass
class Noyau:
    """A vertical circulation core (staircase + lift)."""

    id: str
    type: str
    position: Point
    surface_m2: float
    dessert: list[str]


@dataclass
class NiveauDistribution:
    """Full floor-plate distribution for one level."""

    niveau: int
    footprint: Polygon
    logements: list[Logement]
    noyaux: list[Noyau]
    couloirs: list[Polygon]
    surface_utile_m2: float
    surface_circulations_m2: float


@dataclass
class DistributionResult:
    """Result of a full distribution computation across all levels."""

    template: str
    niveaux: list[NiveauDistribution]
    total_logements: int
    total_surface_utile_m2: float
    total_circulations_m2: float
    coefficient_utile: float
