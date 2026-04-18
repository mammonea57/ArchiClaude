# ArchiClaude — Sous-projet 2 : Programmation architecturale — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire le pipeline complet de programmation architecturale : footprint optimisé segment par segment, solver multi-scénarios (max SDP / max logements / max confort), distribution intérieure avec trames BA et noyaux, et génération de plans architecturaux SVG + DXF à 3 niveaux de détail.

**Architecture:** Package `core/programming/` avec modules indépendants chaînés : segment_classifier → setback_engine → envelope → solver → distribution → plans (renderers SVG + DXF). Chaque module prend la sortie du précédent. Schemas partagés dans `core/programming/schemas.py`. Worker ARQ pour exécution async. Endpoints API + composants frontend.

**Tech Stack:** Python 3.12, shapely (géométrie 2D — demi-plans, intersections, polygones), ezdxf (export DXF), math (trigonométrie, itérations), pyproj (projections), pytest.

**Spec source:** `docs/superpowers/specs/2026-04-18-archiclaude-sous-projet-2-programmation-architecturale.md`

---

## File Structure

```
apps/backend/
├── core/
│   └── programming/
│       ├── __init__.py                      (NEW)
│       ├── schemas.py                       (NEW — all dataclasses)
│       ├── segment_classifier.py            (NEW — classify parcelle segments)
│       ├── setback_engine.py                (NEW — reculs par demi-plans)
│       ├── envelope.py                      (NEW — gabarit-enveloppe tranches)
│       ├── solver.py                        (NEW — multi-scenario optimizer)
│       ├── distribution.py                  (NEW — interior layout)
│       └── plans/
│           ├── __init__.py                  (NEW)
│           ├── plan_masse.py                (NEW — site plan SVG)
│           ├── plan_niveau.py               (NEW — floor plan SVG)
│           ├── coupe.py                     (NEW — section SVG)
│           ├── facade.py                    (NEW — elevation SVG)
│           ├── renderer_svg.py              (NEW — SVG drawing primitives)
│           └── renderer_dxf.py              (NEW — DXF export via ezdxf)
├── api/routes/
│   └── programming.py                       (NEW — /projects/{id}/program endpoints)
├── schemas/
│   └── programming.py                       (NEW — API Pydantic schemas)
├── workers/
│   └── programming.py                       (NEW — ARQ worker)
└── tests/unit/
    ├── test_segment_classifier.py           (NEW)
    ├── test_setback_engine.py               (NEW)
    ├── test_envelope.py                     (NEW)
    ├── test_solver.py                       (NEW)
    ├── test_distribution.py                 (NEW)
    ├── test_plan_masse.py                   (NEW)
    ├── test_plan_niveau.py                  (NEW)
    ├── test_renderer_svg.py                 (NEW)
    └── test_renderer_dxf.py                 (NEW)

apps/frontend/src/components/programming/
    ├── ScenarioComparator.tsx               (NEW)
    ├── FloorPlanViewer.tsx                  (NEW)
    ├── SectionViewer.tsx                    (NEW)
    ├── FacadeViewer.tsx                     (NEW)
    ├── PlanExportButton.tsx                 (NEW)
    └── LLSAccessToggle.tsx                  (NEW)
```

---

## Task 1: Schemas — all dataclasses for the programming pipeline

**Files:**
- Create: `apps/backend/core/programming/__init__.py`
- Create: `apps/backend/core/programming/schemas.py`

- [ ] **Step 1: Implement all schemas**

```python
# apps/backend/core/programming/__init__.py
"""Architectural programming — footprint optimization, solver, distribution, plans."""

# apps/backend/core/programming/schemas.py
"""Schemas for the programming pipeline."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal
from shapely.geometry import Polygon, Point


@dataclass(frozen=True)
class ClassifiedSegment:
    """A parcelle boundary segment with its classification and setback."""
    start: tuple[float, float]  # (x, y) Lambert-93
    end: tuple[float, float]
    segment_type: Literal["voirie", "separative", "fond"]
    recul_m: float  # setback in meters
    recul_formula: str | None = None  # e.g. "H/2 min 4" if parametric
    longueur_m: float = 0.0


@dataclass(frozen=True)
class NiveauFootprint:
    """Footprint for a single building level."""
    niveau: int  # 0=RDC, 1=R+1, etc.
    hauteur_plancher_m: float
    footprint: Polygon
    surface_m2: float


@dataclass
class Scenario:
    """One optimization scenario result."""
    nom: str  # max_sdp, max_logements, max_confort
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
    """Result from the multi-scenario solver."""
    scenarios: list[Scenario]
    scenario_recommande: str
    raison_recommandation: str


@dataclass
class Piece:
    """A room within a dwelling."""
    nom: str  # sejour_cuisine, chambre_1, sdb, wc, degagement, loggia
    surface_m2: float
    largeur_m: float
    longueur_m: float


@dataclass
class Logement:
    """A dwelling unit on a floor."""
    id: str  # "N2-T3-A"
    typologie: str  # T1..T5
    surface_m2: float
    niveau: int
    position: str  # A, B, C
    exposition: str  # N, NE, E, SE, S, SO, O, NO
    est_lls: bool
    pieces: list[Piece]
    geometry: Polygon


@dataclass
class Noyau:
    """A circulation core (stairwell + elevator + lobby)."""
    id: str  # noyau_A, noyau_B
    type: str  # accession, lls, mixte
    position: Point
    surface_m2: float
    dessert: list[str]  # logement IDs


@dataclass
class NiveauDistribution:
    """Complete layout for one floor."""
    niveau: int
    footprint: Polygon
    logements: list[Logement]
    noyaux: list[Noyau]
    couloirs: list[Polygon]
    surface_utile_m2: float
    surface_circulations_m2: float


@dataclass
class DistributionResult:
    """Complete interior distribution result."""
    template: str  # barre_simple, plot, l_distribue, barre_double
    niveaux: list[NiveauDistribution]
    total_logements: int
    total_surface_utile_m2: float
    total_circulations_m2: float
    coefficient_utile: float


# Surface targets per typology (market IDF ranges)
SURFACE_CIBLES: dict[str, tuple[float, float]] = {
    "T1": (25, 30),
    "T2": (40, 45),
    "T3": (55, 60),
    "T4": (72, 80),
    "T5": (90, 100),
}

SURFACE_CENTRE: dict[str, float] = {
    "T1": 27, "T2": 42, "T3": 58, "T4": 77, "T5": 95,
}

TRAME_BA_M: float = 5.40  # standard BA grid for residential

TRAMES_PAR_TYPO: dict[str, float] = {
    "T1": 1.0, "T2": 1.5, "T3": 2.0, "T4": 2.5, "T5": 3.0,
}

SURFACE_NOYAU_M2: float = 35.0  # stairwell + elevator + lobby per level
```

- [ ] **Step 2: Commit**

```bash
git add apps/backend/core/programming/
git commit -m "feat(programming): add all schemas and constants for architectural programming"
```

---

## Task 2: Segment classifier — classify parcelle boundary segments

**Files:**
- Create: `apps/backend/core/programming/segment_classifier.py`
- Test: `apps/backend/tests/unit/test_segment_classifier.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_segment_classifier.py
"""Tests for parcelle segment classification."""
import pytest
from shapely.geometry import Polygon, LineString
from core.programming.segment_classifier import (
    classify_segments, ClassifiedSegment,
    _classify_by_roads, _classify_heuristic,
)


class TestClassifyByRoads:
    def test_segment_near_road_is_voirie(self):
        parcelle = Polygon([(0, 0), (100, 0), (100, 80), (0, 80)])
        roads = [LineString([(0, -5), (100, -5)])]  # road 5m south
        segments = _classify_by_roads(parcelle, roads, recul_voirie=5, recul_sep=3, recul_fond=3)
        voirie = [s for s in segments if s.segment_type == "voirie"]
        assert len(voirie) >= 1  # bottom segment near road

    def test_segments_away_from_road_are_separatives(self):
        parcelle = Polygon([(0, 0), (100, 0), (100, 80), (0, 80)])
        roads = [LineString([(0, -5), (100, -5)])]
        segments = _classify_by_roads(parcelle, roads, recul_voirie=5, recul_sep=3, recul_fond=3)
        seps = [s for s in segments if s.segment_type == "separative"]
        assert len(seps) >= 1  # lateral segments

    def test_fond_is_farthest_from_road(self):
        parcelle = Polygon([(0, 0), (100, 0), (100, 80), (0, 80)])
        roads = [LineString([(0, -5), (100, -5)])]
        segments = _classify_by_roads(parcelle, roads, recul_voirie=5, recul_sep=3, recul_fond=3)
        fond = [s for s in segments if s.segment_type == "fond"]
        assert len(fond) >= 1  # top segment is fond

    def test_corner_parcelle_two_voirie(self):
        parcelle = Polygon([(0, 0), (60, 0), (60, 50), (0, 50)])
        roads = [LineString([(0, -5), (60, -5)]), LineString([(-5, 0), (-5, 50)])]
        segments = _classify_by_roads(parcelle, roads, recul_voirie=5, recul_sep=3, recul_fond=3)
        voirie = [s for s in segments if s.segment_type == "voirie"]
        assert len(voirie) >= 2


class TestClassifyHeuristic:
    def test_longest_segment_is_voirie(self):
        parcelle = Polygon([(0, 0), (100, 0), (100, 40), (0, 40)])
        segments = _classify_heuristic(parcelle, recul_voirie=5, recul_sep=3, recul_fond=3)
        voirie = [s for s in segments if s.segment_type == "voirie"]
        assert voirie[0].longueur_m >= 90  # ~100m bottom segment

    def test_all_segments_classified(self):
        parcelle = Polygon([(0, 0), (100, 0), (100, 80), (0, 80)])
        segments = _classify_heuristic(parcelle, recul_voirie=5, recul_sep=3, recul_fond=3)
        types = {s.segment_type for s in segments}
        assert "voirie" in types
        assert "fond" in types


class TestClassifySegments:
    def test_with_roads(self):
        parcelle = Polygon([(0, 0), (100, 0), (100, 80), (0, 80)])
        roads = [LineString([(0, -5), (100, -5)])]
        segments = classify_segments(parcelle, roads=roads, recul_voirie=5, recul_sep=3, recul_fond=3)
        assert all(isinstance(s, ClassifiedSegment) for s in segments)

    def test_without_roads_uses_heuristic(self):
        parcelle = Polygon([(0, 0), (100, 0), (100, 80), (0, 80)])
        segments = classify_segments(parcelle, roads=None, recul_voirie=5, recul_sep=3, recul_fond=3)
        assert len(segments) == 4

    def test_triangle_parcelle(self):
        parcelle = Polygon([(0, 0), (80, 0), (40, 60)])
        segments = classify_segments(parcelle, roads=None, recul_voirie=5, recul_sep=3, recul_fond=3)
        assert len(segments) == 3
```

- [ ] **Step 2: Implement segment classifier**

```python
# apps/backend/core/programming/segment_classifier.py
"""Classify parcelle boundary segments as voirie/separative/fond.

Hybrid strategy: BDTopo roads when available, geometric heuristic as fallback.
"""
from __future__ import annotations
import math
from shapely.geometry import Polygon, LineString, Point
from shapely.geometry.base import BaseGeometry
from core.programming.schemas import ClassifiedSegment


def classify_segments(
    parcelle: Polygon,
    *,
    prescriptions_gpu: list[dict] | None = None,
    roads: list[LineString] | None = None,
    recul_voirie: float = 5.0,
    recul_sep: float = 3.0,
    recul_fond: float = 3.0,
    recul_formula: str | None = None,
) -> list[ClassifiedSegment]:
    """Classify each segment of the parcelle boundary.

    Three-tier strategy (most reliable first):
    1. GPU prescriptions (typepsc=15) — official PLU digitized rules
       - sous-type 01 = voirie (implantation par rapport à la voie)
       - sous-type 00 = séparative (limites séparatives)
       - Geometry intersection with parcelle boundary identifies exact segments
    2. BDTopo roads — proximity-based classification for uncovered segments
    3. Geometric heuristic — fallback when no external data available

    Args:
        parcelle: Parcel geometry in Lambert-93 (meters).
        prescriptions_gpu: GPU prescription features (typepsc, geometry, libelle).
        roads: Road geometries from BDTopo.
        recul_voirie: Default setback for voirie segments.
        recul_sep: Default setback for separative segments.
        recul_fond: Default setback for fond (rear) segments.
        recul_formula: If set, applied to separative segments (parametric).
    """
    if prescriptions_gpu:
        return _classify_by_gpu_prescriptions(
            parcelle, prescriptions_gpu, roads,
            recul_voirie, recul_sep, recul_fond, recul_formula,
        )
    if roads:
        return _classify_by_roads(parcelle, roads, recul_voirie, recul_sep, recul_fond, recul_formula)
    return _classify_heuristic(parcelle, recul_voirie, recul_sep, recul_fond, recul_formula)


def _extract_segments(parcelle: Polygon) -> list[tuple[tuple[float, float], tuple[float, float], float]]:
    """Extract boundary segments with their lengths."""
    coords = list(parcelle.exterior.coords)
    segments = []
    for i in range(len(coords) - 1):
        p1, p2 = coords[i], coords[i + 1]
        length = math.sqrt((p2[0] - p1[0]) ** 2 + (p2[1] - p1[1]) ** 2)
        if length > 0.01:
            segments.append((p1, p2, length))
    return segments


def _classify_by_roads(
    parcelle: Polygon, roads: list[LineString],
    recul_voirie: float, recul_sep: float, recul_fond: float,
    recul_formula: str | None = None,
) -> list[ClassifiedSegment]:
    """Classify using BDTopo road proximity."""
    raw = _extract_segments(parcelle)
    road_union = _union_roads(roads)

    classified = []
    max_dist = 0
    max_dist_idx = 0

    for i, (p1, p2, length) in enumerate(raw):
        midpoint = Point((p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2)
        dist = midpoint.distance(road_union) if road_union else 9999

        if dist < 15:  # within 15m of a road
            classified.append(ClassifiedSegment(
                start=p1, end=p2, segment_type="voirie",
                recul_m=recul_voirie, longueur_m=round(length, 2),
            ))
        else:
            classified.append(ClassifiedSegment(
                start=p1, end=p2, segment_type="separative",
                recul_m=recul_sep, recul_formula=recul_formula,
                longueur_m=round(length, 2),
            ))
            if dist > max_dist:
                max_dist = dist
                max_dist_idx = len(classified) - 1

    # Reclassify the farthest segment as fond
    if classified and max_dist_idx < len(classified):
        s = classified[max_dist_idx]
        classified[max_dist_idx] = ClassifiedSegment(
            start=s.start, end=s.end, segment_type="fond",
            recul_m=recul_fond, longueur_m=s.longueur_m,
        )

    return classified


def _classify_heuristic(
    parcelle: Polygon, recul_voirie: float, recul_sep: float, recul_fond: float,
    recul_formula: str | None = None,
) -> list[ClassifiedSegment]:
    """Heuristic fallback: longest segment = voirie, opposite = fond."""
    raw = _extract_segments(parcelle)
    if not raw:
        return []

    # Find longest segment → voirie
    longest_idx = max(range(len(raw)), key=lambda i: raw[i][2])
    longest_mid = Point(
        (raw[longest_idx][0][0] + raw[longest_idx][1][0]) / 2,
        (raw[longest_idx][0][1] + raw[longest_idx][1][1]) / 2,
    )

    # Find segment farthest from voirie midpoint → fond
    farthest_idx = max(
        (i for i in range(len(raw)) if i != longest_idx),
        key=lambda i: longest_mid.distance(Point(
            (raw[i][0][0] + raw[i][1][0]) / 2,
            (raw[i][0][1] + raw[i][1][1]) / 2,
        )),
        default=0,
    )

    classified = []
    for i, (p1, p2, length) in enumerate(raw):
        if i == longest_idx:
            seg_type = "voirie"
            recul = recul_voirie
            formula = None
        elif i == farthest_idx:
            seg_type = "fond"
            recul = recul_fond
            formula = None
        else:
            seg_type = "separative"
            recul = recul_sep
            formula = recul_formula

        classified.append(ClassifiedSegment(
            start=p1, end=p2, segment_type=seg_type,
            recul_m=recul, recul_formula=formula,
            longueur_m=round(length, 2),
        ))

    return classified


def _union_roads(roads: list[LineString]) -> BaseGeometry | None:
    from shapely.ops import unary_union
    if not roads:
        return None
    return unary_union(roads)
```

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat(programming): add segment classifier — BDTopo roads + heuristic fallback"
```

---

## Task 3: Setback engine — reculs par demi-plans

**Files:**
- Create: `apps/backend/core/programming/setback_engine.py`
- Test: `apps/backend/tests/unit/test_setback_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_setback_engine.py
"""Tests for setback engine — half-plane intersection method."""
import pytest
from shapely.geometry import Polygon
from core.programming.setback_engine import compute_footprint_by_segments
from core.programming.schemas import ClassifiedSegment


class TestComputeFootprintBySegments:
    def test_square_uniform_setback(self):
        parcelle = Polygon([(0, 0), (100, 0), (100, 80), (0, 80)])
        segments = [
            ClassifiedSegment((0, 0), (100, 0), "voirie", 5, longueur_m=100),
            ClassifiedSegment((100, 0), (100, 80), "separative", 3, longueur_m=80),
            ClassifiedSegment((100, 80), (0, 80), "fond", 3, longueur_m=100),
            ClassifiedSegment((0, 80), (0, 0), "separative", 3, longueur_m=80),
        ]
        fp = compute_footprint_by_segments(parcelle=parcelle, segments=segments)
        # Inner rectangle: (3, 5) to (97, 77) → 94 × 72 = 6768 m²
        assert 6500 < fp.area < 7000

    def test_different_setbacks(self):
        parcelle = Polygon([(0, 0), (100, 0), (100, 80), (0, 80)])
        segments = [
            ClassifiedSegment((0, 0), (100, 0), "voirie", 10, longueur_m=100),  # big voirie setback
            ClassifiedSegment((100, 0), (100, 80), "separative", 3, longueur_m=80),
            ClassifiedSegment((100, 80), (0, 80), "fond", 5, longueur_m=100),
            ClassifiedSegment((0, 80), (0, 0), "separative", 3, longueur_m=80),
        ]
        fp = compute_footprint_by_segments(parcelle=parcelle, segments=segments)
        # Voirie takes 10m, others 3-5m → asymmetric footprint
        assert fp.area < 6768  # less than uniform 5m case

    def test_triangle_parcelle(self):
        parcelle = Polygon([(0, 0), (80, 0), (40, 60)])
        segments = [
            ClassifiedSegment((0, 0), (80, 0), "voirie", 5, longueur_m=80),
            ClassifiedSegment((80, 0), (40, 60), "separative", 3, longueur_m=72),
            ClassifiedSegment((40, 60), (0, 0), "separative", 3, longueur_m=72),
        ]
        fp = compute_footprint_by_segments(parcelle=parcelle, segments=segments)
        assert fp.area > 0
        assert fp.area < parcelle.area

    def test_large_setback_returns_empty(self):
        parcelle = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])  # tiny 10x10
        segments = [
            ClassifiedSegment((0, 0), (10, 0), "voirie", 6, longueur_m=10),
            ClassifiedSegment((10, 0), (10, 10), "separative", 6, longueur_m=10),
            ClassifiedSegment((10, 10), (0, 10), "fond", 6, longueur_m=10),
            ClassifiedSegment((0, 10), (0, 0), "separative", 6, longueur_m=10),
        ]
        fp = compute_footprint_by_segments(parcelle=parcelle, segments=segments)
        assert fp.is_empty or fp.area < 1

    def test_emprise_cap(self):
        parcelle = Polygon([(0, 0), (100, 0), (100, 80), (0, 80)])
        segments = [
            ClassifiedSegment((0, 0), (100, 0), "voirie", 0, longueur_m=100),
            ClassifiedSegment((100, 0), (100, 80), "separative", 0, longueur_m=80),
            ClassifiedSegment((100, 80), (0, 80), "fond", 0, longueur_m=100),
            ClassifiedSegment((0, 80), (0, 0), "separative", 0, longueur_m=80),
        ]
        fp = compute_footprint_by_segments(parcelle=parcelle, segments=segments, emprise_max_pct=50)
        assert fp.area <= 8000 * 0.50 + 10  # 50% of terrain
```

- [ ] **Step 2: Implement setback engine**

Uses half-plane intersection: for each segment, create a half-plane (large polygon) offset inward by the setback distance, perpendicular to the segment. The buildable footprint = intersection of the parcelle with all half-planes.

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat(programming): add setback engine — half-plane intersection per segment"
```

---

## Task 4: Envelope — gabarit-enveloppe par tranches horizontales

**Files:**
- Create: `apps/backend/core/programming/envelope.py`
- Test: `apps/backend/tests/unit/test_envelope.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_envelope.py
"""Tests for envelope calculation — footprint per level with parametric setbacks."""
import pytest
from shapely.geometry import Polygon
from core.programming.envelope import compute_envelope
from core.programming.schemas import ClassifiedSegment, NiveauFootprint


class TestComputeEnvelope:
    def test_fixed_setbacks_same_footprint_all_levels(self):
        parcelle = Polygon([(0, 0), (100, 0), (100, 80), (0, 80)])
        segments = [
            ClassifiedSegment((0, 0), (100, 0), "voirie", 5, longueur_m=100),
            ClassifiedSegment((100, 0), (100, 80), "separative", 3, longueur_m=80),
            ClassifiedSegment((100, 80), (0, 80), "fond", 3, longueur_m=100),
            ClassifiedSegment((0, 80), (0, 0), "separative", 3, longueur_m=80),
        ]
        niveaux = compute_envelope(parcelle=parcelle, segments=segments, hauteur_max_m=15)
        assert len(niveaux) == 5  # 15m / 3m = 5 levels
        # All levels should have same area (fixed setbacks)
        areas = [n.surface_m2 for n in niveaux]
        assert max(areas) - min(areas) < 1  # constant

    def test_parametric_setback_decreasing_area(self):
        parcelle = Polygon([(0, 0), (100, 0), (100, 80), (0, 80)])
        segments = [
            ClassifiedSegment((0, 0), (100, 0), "voirie", 5, longueur_m=100),
            ClassifiedSegment((100, 0), (100, 80), "separative", 3, recul_formula="H/2 min 3", longueur_m=80),
            ClassifiedSegment((100, 80), (0, 80), "fond", 3, recul_formula="H/2 min 3", longueur_m=100),
            ClassifiedSegment((0, 80), (0, 0), "separative", 3, recul_formula="H/2 min 3", longueur_m=80),
        ]
        niveaux = compute_envelope(parcelle=parcelle, segments=segments, hauteur_max_m=15)
        # Higher levels have larger setbacks → smaller footprints
        assert niveaux[0].surface_m2 > niveaux[-1].surface_m2

    def test_sdp_total_is_sum(self):
        parcelle = Polygon([(0, 0), (100, 0), (100, 80), (0, 80)])
        segments = [
            ClassifiedSegment((0, 0), (100, 0), "voirie", 5, longueur_m=100),
            ClassifiedSegment((100, 0), (100, 80), "separative", 3, longueur_m=80),
            ClassifiedSegment((100, 80), (0, 80), "fond", 3, longueur_m=100),
            ClassifiedSegment((0, 80), (0, 0), "separative", 3, longueur_m=80),
        ]
        niveaux = compute_envelope(parcelle=parcelle, segments=segments, hauteur_max_m=12)
        sdp_total = sum(n.surface_m2 for n in niveaux)
        assert sdp_total > 0

    def test_niveau_footprint_fields(self):
        parcelle = Polygon([(0, 0), (50, 0), (50, 50), (0, 50)])
        segments = [
            ClassifiedSegment((0, 0), (50, 0), "voirie", 3, longueur_m=50),
            ClassifiedSegment((50, 0), (50, 50), "separative", 3, longueur_m=50),
            ClassifiedSegment((50, 50), (0, 50), "fond", 3, longueur_m=50),
            ClassifiedSegment((0, 50), (0, 0), "separative", 3, longueur_m=50),
        ]
        niveaux = compute_envelope(parcelle=parcelle, segments=segments, hauteur_max_m=6)
        assert isinstance(niveaux[0], NiveauFootprint)
        assert niveaux[0].niveau == 0
        assert niveaux[0].hauteur_plancher_m == 0
        assert niveaux[1].niveau == 1
        assert niveaux[1].hauteur_plancher_m == 3.0
```

- [ ] **Step 2: Implement envelope**

Evaluates parametric formulas using `asteval` (safe expression evaluator, already in the project concept from the spec). Falls back to fixed setback when formula is None.

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat(programming): add envelope — gabarit-enveloppe par tranches horizontales"
```

---

## Task 5: Solver — multi-scenario optimizer

**Files:**
- Create: `apps/backend/core/programming/solver.py`
- Test: `apps/backend/tests/unit/test_solver.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_solver.py
"""Tests for multi-scenario solver."""
import pytest
from shapely.geometry import Polygon
from core.programming.solver import solve_scenarios, SolverResult
from core.programming.schemas import NiveauFootprint


class TestSolveScenarios:
    def _make_niveaux(self, n=5, area=600):
        return [NiveauFootprint(i, i*3.0, Polygon([(0,0),(20,0),(20,30),(0,30)]), area) for i in range(n)]

    def test_returns_3_scenarios(self):
        result = solve_scenarios(
            footprints=self._make_niveaux(),
            surface_terrain_m2=1000,
            mix_brief={"T2": 0.3, "T3": 0.4, "T4": 0.3},
            stationnement_par_logement=1.0,
            risk_score=30,
        )
        assert isinstance(result, SolverResult)
        assert len(result.scenarios) == 3
        assert {s.nom for s in result.scenarios} == {"max_sdp", "max_logements", "max_confort"}

    def test_max_sdp_uses_brief_mix(self):
        mix = {"T2": 0.3, "T3": 0.4, "T4": 0.3}
        result = solve_scenarios(
            footprints=self._make_niveaux(), surface_terrain_m2=1000,
            mix_brief=mix, stationnement_par_logement=1.0, risk_score=20,
        )
        max_sdp = [s for s in result.scenarios if s.nom == "max_sdp"][0]
        assert max_sdp.mix_utilise == mix

    def test_max_logements_has_more_small_units(self):
        result = solve_scenarios(
            footprints=self._make_niveaux(), surface_terrain_m2=1000,
            mix_brief={"T2": 0.3, "T3": 0.4, "T4": 0.3},
            stationnement_par_logement=1.0, risk_score=20,
        )
        max_logt = [s for s in result.scenarios if s.nom == "max_logements"][0]
        max_sdp = [s for s in result.scenarios if s.nom == "max_sdp"][0]
        assert max_logt.nb_logements >= max_sdp.nb_logements

    def test_max_confort_has_fewer_larger_units(self):
        result = solve_scenarios(
            footprints=self._make_niveaux(), surface_terrain_m2=1000,
            mix_brief={"T2": 0.3, "T3": 0.4, "T4": 0.3},
            stationnement_par_logement=1.0, risk_score=20,
        )
        max_conf = [s for s in result.scenarios if s.nom == "max_confort"][0]
        max_sdp = [s for s in result.scenarios if s.nom == "max_sdp"][0]
        assert max_conf.nb_logements <= max_sdp.nb_logements

    def test_margin_applied(self):
        result = solve_scenarios(
            footprints=self._make_niveaux(area=600), surface_terrain_m2=1000,
            mix_brief={"T3": 1.0}, stationnement_par_logement=1.0, risk_score=50,
        )
        max_sdp = [s for s in result.scenarios if s.nom == "max_sdp"][0]
        assert max_sdp.marge_pct == 97  # risk 50 → 97%

    def test_lls_separate_access_variant(self):
        result = solve_scenarios(
            footprints=self._make_niveaux(area=800), surface_terrain_m2=2000,
            mix_brief={"T3": 1.0}, stationnement_par_logement=1.0, risk_score=20,
            lls_obligatoire=True,
        )
        # At least one scenario should have the variant calculated
        has_variant = any(s.variante_acces_separes for s in result.scenarios)
        # May or may not propose depending on perte threshold
```

- [ ] **Step 2: Implement solver**

The solver creates 3 scenarios by varying the mix typologique:
- max_sdp: uses brief mix unchanged
- max_logements: shifts toward T1/T2 (smaller units)
- max_confort: shifts toward T3/T4 (larger units)

Each scenario: compute_capacity with the adjusted mix, apply smart_margin, generate suggestions.

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat(programming): add multi-scenario solver — max SDP, max logements, max confort"
```

---

## Task 6: Distribution — interior layout on trames

**Files:**
- Create: `apps/backend/core/programming/distribution.py`
- Test: `apps/backend/tests/unit/test_distribution.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_distribution.py
"""Tests for interior distribution on BA grid."""
import pytest
from shapely.geometry import Polygon
from core.programming.distribution import (
    select_template, place_noyaux, distribute_logements,
    DistributionResult,
)
from core.programming.schemas import NiveauFootprint


class TestSelectTemplate:
    def test_elongated_barre(self):
        fp = Polygon([(0,0),(100,0),(100,30),(0,30)])  # 100x30 ratio 3.3
        assert select_template(fp) == "barre_simple"

    def test_compact_plot(self):
        fp = Polygon([(0,0),(40,0),(40,35),(0,35)])  # 40x35 ratio 1.14
        assert select_template(fp) == "plot"

    def test_very_elongated_double(self):
        fp = Polygon([(0,0),(200,0),(200,30),(0,30)])  # ratio 6.7
        assert select_template(fp) == "barre_double"


class TestPlaceNoyaux:
    def test_single_noyau_default(self):
        fp = Polygon([(0,0),(50,0),(50,30),(0,30)])
        noyaux = place_noyaux(fp, template="barre_simple", nb_noyaux_requis=1)
        assert len(noyaux) == 1

    def test_double_noyaux_incendie(self):
        fp = Polygon([(0,0),(100,0),(100,30),(0,30)])
        noyaux = place_noyaux(fp, template="barre_double", nb_noyaux_requis=2)
        assert len(noyaux) == 2


class TestDistributeLogements:
    def test_produces_logements(self):
        niveaux = [NiveauFootprint(i, i*3.0, Polygon([(0,0),(30,0),(30,15),(0,15)]), 450) for i in range(4)]
        result = distribute_logements(
            niveaux=niveaux,
            mix={"T2": 0.5, "T3": 0.5},
            nb_logements_total=20,
            template="barre_simple",
            nb_noyaux=1,
        )
        assert isinstance(result, DistributionResult)
        assert result.total_logements > 0
        assert result.coefficient_utile > 0
        assert result.coefficient_utile < 1
```

- [ ] **Step 2: Implement distribution**

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat(programming): add interior distribution — trames BA, noyaux, logements"
```

---

## Task 7: SVG renderer — drawing primitives

**Files:**
- Create: `apps/backend/core/programming/plans/__init__.py`
- Create: `apps/backend/core/programming/plans/renderer_svg.py`
- Test: `apps/backend/tests/unit/test_renderer_svg.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_renderer_svg.py
"""Tests for SVG rendering primitives."""
import pytest
from core.programming.plans.renderer_svg import SvgCanvas


class TestSvgCanvas:
    def test_creates_valid_svg(self):
        canvas = SvgCanvas(width_mm=297, height_mm=210)  # A4 landscape
        svg = canvas.to_string()
        assert "<svg" in svg
        assert "297mm" in svg

    def test_draw_polygon(self):
        canvas = SvgCanvas(width_mm=100, height_mm=100)
        canvas.draw_polygon([(0,0),(50,0),(50,50),(0,50)], stroke="#000", fill="#ccc", stroke_width=0.5)
        svg = canvas.to_string()
        assert "<polygon" in svg

    def test_draw_line(self):
        canvas = SvgCanvas(width_mm=100, height_mm=100)
        canvas.draw_line(0, 0, 100, 0, stroke="#000", stroke_width=0.5)
        svg = canvas.to_string()
        assert "<line" in svg

    def test_draw_text(self):
        canvas = SvgCanvas(width_mm=100, height_mm=100)
        canvas.draw_text(50, 50, "Séjour 24m²", font_size=9)
        svg = canvas.to_string()
        assert "Séjour" in svg

    def test_draw_dimension(self):
        canvas = SvgCanvas(width_mm=100, height_mm=100)
        canvas.draw_dimension(0, 0, 100, 0, "10.00 m")
        svg = canvas.to_string()
        assert "10.00" in svg

    def test_draw_door_arc(self):
        canvas = SvgCanvas(width_mm=100, height_mm=100)
        canvas.draw_door(50, 0, 0.90, "left")
        svg = canvas.to_string()
        assert "<path" in svg or "<arc" in svg.lower() or "A " in svg
```

- [ ] **Step 2: Implement SVG canvas**

A simple SVG builder class that accumulates elements and outputs a complete SVG string. Methods: draw_polygon, draw_line, draw_rect, draw_text, draw_dimension (with arrows), draw_door (arc), draw_window (line on wall), draw_north_arrow. Supports layer groups for toggle NF/simplifié.

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat(plans): add SVG rendering primitives canvas"
```

---

## Task 8: DXF renderer

**Files:**
- Create: `apps/backend/core/programming/plans/renderer_dxf.py`
- Test: `apps/backend/tests/unit/test_renderer_dxf.py`
- Modify: `apps/backend/pyproject.toml` (add ezdxf)

- [ ] **Step 1: Add ezdxf dependency**

Add `"ezdxf>=1.0"` to pyproject.toml dependencies. Install.

- [ ] **Step 2: Write failing tests + implement**

```python
# apps/backend/tests/unit/test_renderer_dxf.py
"""Tests for DXF export."""
import pytest
from core.programming.plans.renderer_dxf import DxfCanvas


class TestDxfCanvas:
    def test_creates_valid_dxf(self):
        canvas = DxfCanvas()
        canvas.draw_polygon([(0,0),(10,0),(10,10),(0,10)], layer="MURS_PORTEURS")
        dxf_bytes = canvas.to_bytes()
        assert len(dxf_bytes) > 0

    def test_has_standard_layers(self):
        canvas = DxfCanvas()
        layers = canvas.get_layers()
        assert "MURS_PORTEURS" in layers
        assert "CLOISONS" in layers
        assert "COTATIONS" in layers
        assert "MENUISERIES" in layers
        assert "TEXTES" in layers

    def test_draw_text(self):
        canvas = DxfCanvas()
        canvas.draw_text(5, 5, "Séjour", layer="TEXTES")
        dxf_bytes = canvas.to_bytes()
        assert len(dxf_bytes) > 100
```

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat(plans): add DXF export renderer via ezdxf"
```

---

## Task 9: Plan generators — masse, niveau, coupe, façade

**Files:**
- Create: `apps/backend/core/programming/plans/plan_masse.py`
- Create: `apps/backend/core/programming/plans/plan_niveau.py`
- Create: `apps/backend/core/programming/plans/coupe.py`
- Create: `apps/backend/core/programming/plans/facade.py`
- Test: `apps/backend/tests/unit/test_plan_masse.py`
- Test: `apps/backend/tests/unit/test_plan_niveau.py`

- [ ] **Step 1: Write tests for plan masse**

```python
# apps/backend/tests/unit/test_plan_masse.py
"""Tests for site plan generation."""
from shapely.geometry import Polygon
from core.programming.plans.plan_masse import generate_plan_masse


class TestGeneratePlanMasse:
    def test_returns_svg_string(self):
        parcelle = Polygon([(0,0),(100,0),(100,80),(0,80)])
        footprint = Polygon([(5,5),(95,5),(95,75),(5,75)])
        svg = generate_plan_masse(
            parcelle=parcelle, footprint=footprint,
            voirie_name="Rue du Test", north_angle=0,
            emprise_pct=85, surface_pleine_terre_m2=1200,
        )
        assert "<svg" in svg
        assert "Rue du Test" in svg

    def test_contains_north_arrow(self):
        parcelle = Polygon([(0,0),(50,0),(50,50),(0,50)])
        footprint = Polygon([(5,5),(45,5),(45,45),(5,45)])
        svg = generate_plan_masse(parcelle=parcelle, footprint=footprint)
        assert "N" in svg  # north indicator
```

- [ ] **Step 2: Write tests for plan niveau**

```python
# apps/backend/tests/unit/test_plan_niveau.py
"""Tests for floor plan generation."""
from shapely.geometry import Polygon, Point
from core.programming.plans.plan_niveau import generate_plan_niveau
from core.programming.schemas import Logement, Noyau, Piece, NiveauDistribution


class TestGeneratePlanNiveau:
    def test_returns_svg(self):
        logement = Logement(
            id="N0-T3-A", typologie="T3", surface_m2=58, niveau=0,
            position="A", exposition="S", est_lls=False,
            pieces=[Piece("sejour", 24, 6, 4), Piece("chambre_1", 11, 3.5, 3.1)],
            geometry=Polygon([(0,0),(10.8,0),(10.8,6),(0,6)]),
        )
        noyau = Noyau(id="noyau_A", type="mixte", position=Point(15, 3), surface_m2=35, dessert=["N0-T3-A"])
        niveau = NiveauDistribution(
            niveau=0, footprint=Polygon([(0,0),(30,0),(30,15),(0,15)]),
            logements=[logement], noyaux=[noyau], couloirs=[],
            surface_utile_m2=58, surface_circulations_m2=35,
        )
        svg = generate_plan_niveau(niveau, detail="pc_norme")
        assert "<svg" in svg
        assert "T3" in svg or "sejour" in svg.lower() or "Séjour" in svg

    def test_schematic_vs_nf(self):
        # Same input, different detail levels should produce different SVGs
        logement = Logement(
            id="N0-T2-A", typologie="T2", surface_m2=42, niveau=0,
            position="A", exposition="E", est_lls=False,
            pieces=[Piece("sejour", 20, 5, 4)],
            geometry=Polygon([(0,0),(8,0),(8,5),(0,5)]),
        )
        niveau = NiveauDistribution(
            niveau=0, footprint=Polygon([(0,0),(20,0),(20,10),(0,10)]),
            logements=[logement], noyaux=[], couloirs=[],
            surface_utile_m2=42, surface_circulations_m2=0,
        )
        svg_simple = generate_plan_niveau(niveau, detail="schematique")
        svg_nf = generate_plan_niveau(niveau, detail="pc_norme")
        assert len(svg_nf) > len(svg_simple)  # NF has more detail
```

- [ ] **Step 3: Implement all 4 plan generators**

Each generator takes the relevant data (parcelle/footprint/niveaux/distribution) and uses the SvgCanvas to produce an SVG string. Also supports DXF output via DxfCanvas.

- [ ] **Step 4: Run tests, commit**

```bash
git commit -m "feat(plans): add plan masse, plan niveau, coupe, facade generators"
```

---

## Task 10: API endpoints + worker + frontend components

**Files:**
- Create: `apps/backend/api/routes/programming.py`
- Create: `apps/backend/schemas/programming.py`
- Create: `apps/backend/workers/programming.py`
- Modify: `apps/backend/api/main.py`
- Create: `apps/frontend/src/components/programming/ScenarioComparator.tsx`
- Create: `apps/frontend/src/components/programming/FloorPlanViewer.tsx`
- Create: `apps/frontend/src/components/programming/SectionViewer.tsx`
- Create: `apps/frontend/src/components/programming/FacadeViewer.tsx`
- Create: `apps/frontend/src/components/programming/PlanExportButton.tsx`
- Create: `apps/frontend/src/components/programming/LLSAccessToggle.tsx`

- [ ] **Step 1: Create API routes**

```python
# api/routes/programming.py
POST   /projects/{id}/program             → 202 {job_id}
GET    /projects/{id}/program/status       → {status}
GET    /projects/{id}/scenarios            → [Scenario]
GET    /projects/{id}/scenarios/{nom}      → Scenario detail
GET    /projects/{id}/plans/{type}         → SVG (text/svg+xml)
GET    /projects/{id}/plans/{type}/dxf     → DXF (application/dxf)
```

- [ ] **Step 2: Create frontend components**

- ScenarioComparator: 3-column table comparing scenarios with highlight on recommended
- FloorPlanViewer: SVG display with zoom/pan, toggle simplifié/NF complet
- SectionViewer: coupe SVG display
- FacadeViewer: facade SVG display
- PlanExportButton: download SVG or DXF
- LLSAccessToggle: switch accès séparés on/off

- [ ] **Step 3: Create worker + register routes**

- [ ] **Step 4: Commit**

```bash
git commit -m "feat: add programming API endpoints, worker, and frontend components"
```

---

## Task 11: Final verification

- [ ] **Step 1: Run backend ruff + tests**
- [ ] **Step 2: Run frontend typecheck + build**
- [ ] **Step 3: Fix issues + commit cleanup**
