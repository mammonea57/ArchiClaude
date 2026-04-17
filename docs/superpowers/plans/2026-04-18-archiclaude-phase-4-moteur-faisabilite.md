# ArchiClaude — Phase 4 : Moteur de faisabilité PLU + Compliance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire le moteur de faisabilité (footprint max constructible, SDP, niveaux, logements, stationnement, comparaison brief) + les modules de compliance complémentaire (incendie, PMR, RE2020, LLS/SRU, RSDU), le schéma Brief, le FeasibilityResult complet, les DB models projets, le worker ARQ `/projects/{id}/analyze`, et le stream SSE.

**Architecture:** Modules purs `core/feasibility/` (footprint shapely, capacity, servitudes, brief_compare) + `core/compliance/` (incendie, pmr, re2020, lls_sru, rsdu). Orchestrateur `core/feasibility/engine.py` qui enchaîne toutes les étapes. Worker ARQ `workers/feasibility.py` pour l'exécution async. Endpoints API pour projets + analyse + status + SSE.

**Tech Stack:** Python 3.12, shapely (buffers, intersection, area), pyproj (Lambert-93), math (floor, ceil, inf), SQLAlchemy 2.0, Alembic, FastAPI (SSE via StreamingResponse), ARQ, pytest.

**Spec source:** `docs/superpowers/specs/2026-04-16-archiclaude-sous-projet-1-design.md` §5 (Moteur faisabilité), §12.1 (Brief)

---

## File Structure (final état Phase 4)

```
apps/backend/
├── core/
│   ├── feasibility/
│   │   ├── __init__.py                      (NEW)
│   │   ├── schemas.py                       (NEW — Brief, FeasibilityResult, EcartItem, etc.)
│   │   ├── footprint.py                     (NEW — emprise max constructible via shapely)
│   │   ├── capacity.py                      (NEW — SDP, niveaux, logements, stationnement)
│   │   ├── servitudes.py                    (NEW — contraintes dures ABF/PPRI/EBC/alignement)
│   │   ├── brief_compare.py                (NEW — comparaison brief vs max)
│   │   └── engine.py                        (NEW — orchestrateur pipeline complet)
│   └── compliance/
│       ├── __init__.py                      (NEW)
│       ├── incendie.py                      (NEW — classement habitation, coef réduction SDP)
│       ├── pmr.py                           (NEW — ascenseur, logements adaptables, places PMR)
│       ├── re2020.py                        (NEW — ic_construction, ic_energie prévisionnels)
│       ├── lls_sru.py                       (NEW — obligation LLS, bonus constructibilité)
│       └── rsdu.py                          (NEW — RSDU IDF obligations)
├── api/
│   └── routes/
│       └── projects.py                      (NEW — /projects CRUD + /analyze + /status)
├── db/
│   └── models/
│       ├── projects.py                      (NEW — projects, project_parcels, feasibility_results)
│       └── reports.py                       (NEW — reports placeholder for Phase 7)
├── schemas/
│   └── project.py                           (NEW — API schemas)
├── workers/
│   └── feasibility.py                       (NEW — ARQ feasibility worker)
├── alembic/versions/
│   └── 20260418_0001_projects.py            (NEW)
└── tests/
    ├── unit/
    │   ├── test_feasibility_footprint.py    (NEW)
    │   ├── test_feasibility_capacity.py     (NEW)
    │   ├── test_feasibility_servitudes.py   (NEW)
    │   ├── test_feasibility_brief_compare.py (NEW)
    │   ├── test_compliance_incendie.py      (NEW)
    │   ├── test_compliance_pmr.py           (NEW)
    │   ├── test_compliance_re2020.py        (NEW)
    │   ├── test_compliance_lls_sru.py       (NEW)
    │   └── test_compliance_rsdu.py          (NEW)
    └── integration/
        └── test_projects_endpoints.py       (NEW)
```

---

## Task 1: Brief + FeasibilityResult schemas

**Files:**
- Create: `apps/backend/core/feasibility/__init__.py`
- Create: `apps/backend/core/feasibility/schemas.py`
- Test: `apps/backend/tests/unit/test_feasibility_schemas.py` (optional — schemas are data containers)

- [ ] **Step 1: Implement schemas**

```python
# apps/backend/core/feasibility/__init__.py
"""Feasibility engine for ArchiClaude."""

# apps/backend/core/feasibility/schemas.py
"""Feasibility schemas — Brief, FeasibilityResult, and supporting types."""
from __future__ import annotations
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID
from pydantic import BaseModel, Field

from core.plu.schemas import NumericRules, ParsedRules


class Brief(BaseModel):
    """User brief — programme targets and constraints."""
    destination: Literal["logement_collectif", "residence_service", "bureaux", "commerce", "mixte"]
    cible_nb_logements: int | None = None
    mix_typologique: dict[str, float] = Field(default_factory=lambda: {"T2": 0.3, "T3": 0.4, "T4": 0.3})
    cible_sdp_m2: float | None = None
    hauteur_cible_niveaux: int | None = None  # total levels incl. RDC (R+3 → 4)
    emprise_cible_pct: float | None = None
    stationnement_cible_par_logement: float | None = None
    espaces_verts_pleine_terre_cible_pct: float | None = None


class ZoneApplicableInfo(BaseModel):
    zone_id: UUID | None = None
    code: str
    libelle: str
    surface_intersectee_m2: float
    pct_of_terrain: float
    rules_numeric: NumericRules


class EcartItem(BaseModel):
    target: str
    brief_value: float
    max_value: float
    ratio: float
    classification: Literal["tres_sous_exploite", "sous_exploite", "coherent", "limite", "infaisable"]
    commentaire: str


class Servitude(BaseModel):
    type: str
    libelle: str
    geom: dict[str, Any] | None = None
    attributes: dict[str, Any] = Field(default_factory=dict)


class Alert(BaseModel):
    level: Literal["info", "warning", "critical"]
    type: str
    message: str
    source: str


class VigilancePoint(BaseModel):
    category: Literal["insertion", "recours", "patrimoine", "environnement", "technique"]
    message: str


class ComplianceResult(BaseModel):
    incendie_classement: str  # 1ere, 2eme, 3A, 3B, 4eme, IGH
    incendie_coef_reduction_sdp: float = 1.0
    pmr_ascenseur_obligatoire: bool = False
    pmr_surface_circulations_m2: float = 0.0
    pmr_nb_places_pmr: int = 0
    re2020_ic_construction_estime: float | None = None
    re2020_ic_energie_estime: float | None = None
    re2020_seuil_applicable: str = "2025"
    lls_commune_statut: str = "non_soumise"
    lls_obligation_pct: float | None = None
    lls_bonus_constructibilite_pct: float | None = None
    rsdu_applicable: bool = True
    rsdu_obligations: list[str] = Field(default_factory=list)


class FeasibilityResult(BaseModel):
    surface_terrain_m2: float
    zones_applicables: list[ZoneApplicableInfo] = Field(default_factory=list)
    footprint_geojson: dict[str, Any] = Field(default_factory=dict)
    surface_emprise_m2: float = 0.0
    surface_pleine_terre_m2: float = 0.0
    hauteur_retenue_m: float = 0.0
    nb_niveaux: int = 0
    sdp_max_m2: float = 0.0
    sdp_max_m2_avant_compliance: float = 0.0
    nb_logements_max: int = 0
    nb_par_typologie: dict[str, int] = Field(default_factory=dict)
    nb_places_stationnement: int = 0
    nb_places_pmr: int = 0
    compliance: ComplianceResult | None = None
    ecart_brief: dict[str, EcartItem] = Field(default_factory=dict)
    servitudes_actives: list[Servitude] = Field(default_factory=list)
    alertes_dures: list[Alert] = Field(default_factory=list)
    points_vigilance: list[VigilancePoint] = Field(default_factory=list)
    confidence_score: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    computed_at: datetime = Field(default_factory=datetime.utcnow)
```

- [ ] **Step 2: Commit**

```bash
git add apps/backend/core/feasibility/
git commit -m "feat(feasibility): add Brief and FeasibilityResult schemas"
```

---

## Task 2: Footprint maximum constructible

**Files:**
- Create: `apps/backend/core/feasibility/footprint.py`
- Test: `apps/backend/tests/unit/test_feasibility_footprint.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_feasibility_footprint.py
"""Tests for maximum buildable footprint calculation."""
import pytest
from shapely.geometry import Polygon
from core.feasibility.footprint import compute_footprint, FootprintResult


class TestComputeFootprint:
    def test_square_no_setbacks(self):
        """100x100m square with no setbacks → full area."""
        terrain = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        result = compute_footprint(
            terrain=terrain,
            recul_voirie_m=0, recul_lat_m=0, recul_fond_m=0,
            emprise_max_pct=100,
        )
        assert isinstance(result, FootprintResult)
        assert abs(result.surface_emprise_m2 - 10000) < 1

    def test_uniform_setbacks(self):
        """100x100m with 5m setbacks on all sides → 90x90 = 8100 m²."""
        terrain = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        result = compute_footprint(
            terrain=terrain,
            recul_voirie_m=5, recul_lat_m=5, recul_fond_m=5,
            emprise_max_pct=100,
        )
        # Buffer -5 on all sides → 90×90 = 8100
        assert abs(result.surface_emprise_m2 - 8100) < 50  # tolerance for buffer approx

    def test_emprise_cap(self):
        """Emprise cap at 60% → max 6000 m² on 10000 m² terrain."""
        terrain = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        result = compute_footprint(
            terrain=terrain,
            recul_voirie_m=0, recul_lat_m=0, recul_fond_m=0,
            emprise_max_pct=60,
        )
        assert result.surface_emprise_m2 <= 6000 + 10

    def test_ebc_subtraction(self):
        """EBC polygon subtracted from buildable area."""
        terrain = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        ebc = Polygon([(80, 80), (100, 80), (100, 100), (80, 100)])  # 20x20 = 400m²
        result = compute_footprint(
            terrain=terrain,
            recul_voirie_m=0, recul_lat_m=0, recul_fond_m=0,
            emprise_max_pct=100,
            ebc_geom=ebc,
        )
        assert result.surface_emprise_m2 < 9700  # at least 300m² removed

    def test_pleine_terre(self):
        """Pleine terre = terrain - footprint."""
        terrain = Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
        result = compute_footprint(
            terrain=terrain,
            recul_voirie_m=0, recul_lat_m=0, recul_fond_m=0,
            emprise_max_pct=60,
        )
        assert result.surface_pleine_terre_m2 >= 3900  # 10000 - 6000
```

- [ ] **Step 2: Implement footprint module**

```python
# apps/backend/core/feasibility/footprint.py
"""Maximum buildable footprint calculation.

Uses shapely buffer operations to apply setbacks and emprise caps.
All calculations in Lambert-93 (meters).
"""
from __future__ import annotations
from dataclasses import dataclass
from shapely.geometry import Polygon, MultiPolygon
from shapely.geometry.base import BaseGeometry


@dataclass(frozen=True)
class FootprintResult:
    footprint_geom: BaseGeometry
    surface_emprise_m2: float
    surface_pleine_terre_m2: float
    surface_terrain_m2: float


def compute_footprint(
    *,
    terrain: Polygon | MultiPolygon,
    recul_voirie_m: float = 0,
    recul_lat_m: float = 0,
    recul_fond_m: float = 0,
    emprise_max_pct: float = 100,
    ebc_geom: BaseGeometry | None = None,
) -> FootprintResult:
    """Compute maximum buildable footprint from terrain geometry and setback rules.

    Args:
        terrain: Parcel geometry in Lambert-93 (meters).
        recul_voirie_m: Voirie setback (applied as uniform buffer for v1).
        recul_lat_m: Lateral boundary setback.
        recul_fond_m: Rear boundary setback.
        emprise_max_pct: Maximum ground coverage percentage (0-100).
        ebc_geom: Protected woodland geometry to subtract.

    In v1, setbacks are applied as a uniform negative buffer using the maximum
    of all three setback values. Segment-specific setbacks require identifying
    voirie/lateral/fond segments which is deferred to v1.1.
    """
    surface_terrain = terrain.area

    # Apply setbacks as negative buffer (v1 simplified: uniform max setback)
    max_recul = max(recul_voirie_m, recul_lat_m, recul_fond_m)
    if max_recul > 0:
        footprint = terrain.buffer(-max_recul)
    else:
        footprint = terrain

    if footprint.is_empty:
        return FootprintResult(
            footprint_geom=footprint,
            surface_emprise_m2=0,
            surface_pleine_terre_m2=surface_terrain,
            surface_terrain_m2=surface_terrain,
        )

    # Subtract EBC
    if ebc_geom is not None and not ebc_geom.is_empty:
        footprint = footprint.difference(ebc_geom)

    # Cap emprise
    max_emprise = emprise_max_pct / 100.0 * surface_terrain
    if footprint.area > max_emprise:
        # Scale footprint down to match emprise cap
        # Use centroid-based scaling to maintain shape
        ratio = (max_emprise / footprint.area) ** 0.5
        centroid = footprint.centroid
        from shapely.affinity import scale
        footprint = scale(footprint, xfact=ratio, yfact=ratio, origin=centroid)

    surface_emprise = footprint.area
    surface_pleine_terre = surface_terrain - surface_emprise

    return FootprintResult(
        footprint_geom=footprint,
        surface_emprise_m2=round(surface_emprise, 2),
        surface_pleine_terre_m2=round(max(0, surface_pleine_terre), 2),
        surface_terrain_m2=round(surface_terrain, 2),
    )
```

- [ ] **Step 3: Run tests to verify they pass**

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/feasibility/footprint.py apps/backend/tests/unit/test_feasibility_footprint.py
git commit -m "feat(feasibility): add maximum buildable footprint with setbacks and emprise cap"
```

---

## Task 3: Capacity — SDP, niveaux, logements, stationnement

**Files:**
- Create: `apps/backend/core/feasibility/capacity.py`
- Test: `apps/backend/tests/unit/test_feasibility_capacity.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_feasibility_capacity.py
"""Tests for SDP, niveaux, logements, and parking calculations."""
import pytest
from core.feasibility.capacity import (
    compute_capacity, CapacityResult,
    compute_hauteur_retenue, compute_nb_niveaux, compute_sdp,
    compute_logements, compute_stationnement,
)


class TestHauteurRetenue:
    def test_min_of_constraints(self):
        h = compute_hauteur_retenue(hauteur_max_m=15, niveaux_max=4, altitude_sol_m=None, hauteur_max_ngf=None)
        # 4 niveaux → (4*3)+0.5 = 12.5m, vs 15m → min = 12.5
        assert h == 12.5

    def test_ngf_constraint(self):
        h = compute_hauteur_retenue(hauteur_max_m=20, niveaux_max=None, altitude_sol_m=50, hauteur_max_ngf=62)
        # NGF: 62 - 50 = 12m, vs 20m → 12
        assert h == 12.0

    def test_no_constraints_returns_max(self):
        h = compute_hauteur_retenue(hauteur_max_m=15, niveaux_max=None, altitude_sol_m=None, hauteur_max_ngf=None)
        assert h == 15.0


class TestNbNiveaux:
    def test_floor_division(self):
        assert compute_nb_niveaux(hauteur_m=15.0) == 5  # 15/3 = 5
        assert compute_nb_niveaux(hauteur_m=12.5) == 4  # floor(12.5/3) = 4
        assert compute_nb_niveaux(hauteur_m=3.0) == 1


class TestComputeSdp:
    def test_basic(self):
        sdp = compute_sdp(surface_emprise_m2=500, nb_niveaux=4, sdp_max_plu=None, cos=None, surface_terrain_m2=1000)
        assert sdp == 2000.0  # 500 * 4

    def test_capped_by_plu(self):
        sdp = compute_sdp(surface_emprise_m2=500, nb_niveaux=4, sdp_max_plu=1500, cos=None, surface_terrain_m2=1000)
        assert sdp == 1500.0

    def test_capped_by_cos(self):
        sdp = compute_sdp(surface_emprise_m2=500, nb_niveaux=4, sdp_max_plu=None, cos=1.5, surface_terrain_m2=1000)
        assert sdp == 1500.0  # COS 1.5 × 1000 = 1500


class TestComputeLogements:
    def test_basic_mix(self):
        mix = {"T2": 0.3, "T3": 0.4, "T4": 0.3}
        nb_total, nb_par_typo = compute_logements(sdp_m2=2000, mix=mix)
        assert nb_total > 0
        assert sum(nb_par_typo.values()) == nb_total

    def test_zero_sdp(self):
        nb_total, nb_par_typo = compute_logements(sdp_m2=0, mix={"T3": 1.0})
        assert nb_total == 0


class TestComputeStationnement:
    def test_basic(self):
        nb, nb_pmr = compute_stationnement(nb_logements=20, ratio_par_logement=1.0)
        assert nb == 20
        assert nb_pmr == 1  # ceil(20 * 0.02) = 1

    def test_fractional(self):
        nb, nb_pmr = compute_stationnement(nb_logements=25, ratio_par_logement=0.5)
        assert nb == 13  # ceil(25 * 0.5)
        assert nb_pmr == 1  # ceil(13 * 0.02)


class TestComputeCapacity:
    def test_full_pipeline(self):
        result = compute_capacity(
            surface_emprise_m2=600,
            surface_terrain_m2=1000,
            hauteur_max_m=15,
            niveaux_max=5,
            altitude_sol_m=None,
            hauteur_max_ngf=None,
            sdp_max_plu=None,
            cos=None,
            mix={"T2": 0.3, "T3": 0.4, "T4": 0.3},
            stationnement_par_logement=1.0,
        )
        assert isinstance(result, CapacityResult)
        assert result.hauteur_retenue_m == 15.0
        assert result.nb_niveaux == 5
        assert result.sdp_max_m2 == 3000.0  # 600 * 5
        assert result.nb_logements_max > 0
        assert result.nb_places_stationnement > 0
```

- [ ] **Step 2: Implement capacity module**

```python
# apps/backend/core/feasibility/capacity.py
"""SDP, niveaux, logements, and parking capacity calculations.

All values computed from NumericRules constraints + brief parameters.
Coefficients brute→utile are NOT hardcoded — they escalate as "à valider"
until properly sourced from CSTB/AFNOR/USH references (spec §4.2 constraint).
"""
from __future__ import annotations
import math
from dataclasses import dataclass


# Surface average per typology (SDP utile m²).
# These are ORDER-OF-MAGNITUDE reference values pending Phase 3.2 validation.
# The spec requires sourced values from Observatoire logement neuf IDF / AFNOR.
# Until validated, the feasibility report will flag these as "indicatif".
SURFACE_PAR_TYPOLOGIE_M2 = {
    "T1": 30.0,
    "T2": 45.0,
    "T3": 65.0,
    "T4": 82.0,
    "T5": 105.0,
}

_HAUTEUR_PAR_NIVEAU_M = 3.0  # meters per usable level
_EPAISSEUR_PLANCHER_M = 0.5  # floor slab thickness


@dataclass(frozen=True)
class CapacityResult:
    hauteur_retenue_m: float
    nb_niveaux: int
    sdp_max_m2: float
    nb_logements_max: int
    nb_par_typologie: dict[str, int]
    nb_places_stationnement: int
    nb_places_pmr: int
    warnings: list[str]


def compute_hauteur_retenue(
    *,
    hauteur_max_m: float | None,
    niveaux_max: int | None,
    altitude_sol_m: float | None,
    hauteur_max_ngf: float | None,
) -> float:
    """Compute the retained height as the minimum of all applicable constraints."""
    candidates = []
    if hauteur_max_m is not None:
        candidates.append(hauteur_max_m)
    if niveaux_max is not None:
        candidates.append(niveaux_max * _HAUTEUR_PAR_NIVEAU_M + _EPAISSEUR_PLANCHER_M)
    if hauteur_max_ngf is not None and altitude_sol_m is not None:
        candidates.append(hauteur_max_ngf - altitude_sol_m)
    if not candidates:
        return 0.0
    return min(candidates)


def compute_nb_niveaux(hauteur_m: float) -> int:
    """Compute number of usable levels from height."""
    if hauteur_m <= 0:
        return 0
    return math.floor(hauteur_m / _HAUTEUR_PAR_NIVEAU_M)


def compute_sdp(
    *,
    surface_emprise_m2: float,
    nb_niveaux: int,
    sdp_max_plu: float | None,
    cos: float | None,
    surface_terrain_m2: float,
) -> float:
    """Compute maximum SDP under all constraints."""
    sdp_brute = surface_emprise_m2 * nb_niveaux
    candidates = [sdp_brute]
    if sdp_max_plu is not None:
        candidates.append(sdp_max_plu)
    if cos is not None:
        candidates.append(cos * surface_terrain_m2)
    return min(candidates)


def compute_logements(
    *, sdp_m2: float, mix: dict[str, float]
) -> tuple[int, dict[str, int]]:
    """Compute number of dwellings from SDP and typology mix."""
    if sdp_m2 <= 0 or not mix:
        return 0, {}

    surface_moy = sum(
        pct * SURFACE_PAR_TYPOLOGIE_M2.get(t, 65.0)
        for t, pct in mix.items()
    )
    if surface_moy <= 0:
        return 0, {}

    nb_total = math.floor(sdp_m2 / surface_moy)
    nb_par_typo = {}
    for t, pct in mix.items():
        nb_par_typo[t] = round(nb_total * pct)

    # Adjust rounding to match total
    diff = nb_total - sum(nb_par_typo.values())
    if diff != 0 and nb_par_typo:
        # Add/remove from largest typology
        largest = max(nb_par_typo, key=lambda k: nb_par_typo[k])
        nb_par_typo[largest] += diff

    return nb_total, nb_par_typo


def compute_stationnement(
    *, nb_logements: int, ratio_par_logement: float | None
) -> tuple[int, int]:
    """Compute parking spaces and PMR places."""
    if ratio_par_logement is None or nb_logements <= 0:
        return 0, 0
    nb_places = math.ceil(nb_logements * ratio_par_logement)
    nb_pmr = max(1, math.ceil(nb_places * 0.02)) if nb_places > 0 else 0
    return nb_places, nb_pmr


def compute_capacity(
    *,
    surface_emprise_m2: float,
    surface_terrain_m2: float,
    hauteur_max_m: float | None,
    niveaux_max: int | None,
    altitude_sol_m: float | None = None,
    hauteur_max_ngf: float | None = None,
    sdp_max_plu: float | None = None,
    cos: float | None = None,
    mix: dict[str, float],
    stationnement_par_logement: float | None = None,
) -> CapacityResult:
    """Full capacity pipeline: height → levels → SDP → dwellings → parking."""
    warnings = []

    hauteur = compute_hauteur_retenue(
        hauteur_max_m=hauteur_max_m, niveaux_max=niveaux_max,
        altitude_sol_m=altitude_sol_m, hauteur_max_ngf=hauteur_max_ngf,
    )
    nb_niveaux = compute_nb_niveaux(hauteur)
    sdp = compute_sdp(
        surface_emprise_m2=surface_emprise_m2, nb_niveaux=nb_niveaux,
        sdp_max_plu=sdp_max_plu, cos=cos, surface_terrain_m2=surface_terrain_m2,
    )

    warnings.append("Coefficients brute→utile non appliqués — valeurs indicatives à valider")

    nb_logements, nb_par_typo = compute_logements(sdp_m2=sdp, mix=mix)
    nb_places, nb_pmr = compute_stationnement(
        nb_logements=nb_logements, ratio_par_logement=stationnement_par_logement,
    )

    return CapacityResult(
        hauteur_retenue_m=hauteur,
        nb_niveaux=nb_niveaux,
        sdp_max_m2=sdp,
        nb_logements_max=nb_logements,
        nb_par_typologie=nb_par_typo,
        nb_places_stationnement=nb_places,
        nb_places_pmr=nb_pmr,
        warnings=warnings,
    )
```

- [ ] **Step 3: Run tests to verify they pass**

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/feasibility/capacity.py apps/backend/tests/unit/test_feasibility_capacity.py
git commit -m "feat(feasibility): add capacity calculator — SDP, niveaux, logements, stationnement"
```

---

## Task 4: Servitudes — contraintes dures

**Files:**
- Create: `apps/backend/core/feasibility/servitudes.py`
- Test: `apps/backend/tests/unit/test_feasibility_servitudes.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_feasibility_servitudes.py
"""Tests for hard servitude constraint detection."""
import pytest
from core.feasibility.servitudes import detect_servitudes_alerts, ServitudeAlert
from core.sources.gpu import GpuServitude
from core.sources.georisques import RisqueResult
from core.sources.pop import MonumentResult


class TestDetectServitudesAlerts:
    def test_monument_historique(self):
        monuments = [MonumentResult(reference="PA001", nom="Église", date_protection="1906", commune="Nogent", departement="94", lat=48.837, lng=2.483)]
        alerts = detect_servitudes_alerts(monuments=monuments, risques=[], servitudes=[])
        assert any(a.type == "abf" for a in alerts)
        assert any("ABF" in a.message for a in alerts)

    def test_ppri(self):
        risques = [RisqueResult(type="ppri", code="PPRI-94", libelle="Inondation", niveau_alea="moyen")]
        alerts = detect_servitudes_alerts(monuments=[], risques=risques, servitudes=[])
        assert any(a.type == "ppri" for a in alerts)

    def test_argiles_fort(self):
        risques = [RisqueResult(type="argiles", code=None, libelle="Retrait-gonflement", niveau_alea="fort")]
        alerts = detect_servitudes_alerts(monuments=[], risques=risques, servitudes=[])
        assert any(a.type == "argiles" for a in alerts)

    def test_no_alerts(self):
        alerts = detect_servitudes_alerts(monuments=[], risques=[], servitudes=[])
        assert alerts == []

    def test_ebc(self):
        servitudes = [GpuServitude(libelle="EBC", categorie="EBC", txt="Espace boisé classé", geometry=None)]
        alerts = detect_servitudes_alerts(monuments=[], risques=[], servitudes=servitudes)
        assert any(a.type == "ebc" for a in alerts)
```

- [ ] **Step 2: Implement servitudes module**

```python
# apps/backend/core/feasibility/servitudes.py
"""Hard servitude constraint detection — ABF, PPRI, EBC, polluted soil, clay."""
from __future__ import annotations
from dataclasses import dataclass

from core.sources.georisques import RisqueResult
from core.sources.gpu import GpuServitude
from core.sources.pop import MonumentResult


@dataclass(frozen=True)
class ServitudeAlert:
    level: str  # info, warning, critical
    type: str  # abf, ppri, ebc, sol_pollue, argiles, alignement
    message: str
    source: str


def detect_servitudes_alerts(
    *,
    monuments: list[MonumentResult],
    risques: list[RisqueResult],
    servitudes: list[GpuServitude],
) -> list[ServitudeAlert]:
    """Detect hard constraints from servitudes, monuments, and risks."""
    alerts: list[ServitudeAlert] = []

    # Monument historique < 500m → ABF
    if monuments:
        names = ", ".join(m.nom for m in monuments[:3])
        alerts.append(ServitudeAlert(
            level="warning",
            type="abf",
            message=f"Avis ABF obligatoire — monument(s) historique(s) à proximité : {names}. Contraintes de recul, matériaux et teinte possibles.",
            source="pop",
        ))

    # PPRI
    ppri = [r for r in risques if r.type == "ppri"]
    if ppri:
        alerts.append(ServitudeAlert(
            level="critical",
            type="ppri",
            message=f"Zone de risque inondation (PPRI) — {ppri[0].libelle}. Cote NGF minimale possible, réduction SDP RDC.",
            source="georisques",
        ))

    # Argiles fort
    argiles_fort = [r for r in risques if r.type == "argiles" and r.niveau_alea and "fort" in r.niveau_alea.lower()]
    if argiles_fort:
        alerts.append(ServitudeAlert(
            level="warning",
            type="argiles",
            message="Retrait-gonflement des argiles — aléa fort. Étude géotechnique G2 obligatoire.",
            source="georisques",
        ))

    # Sol pollué
    sol_pollue = [r for r in risques if r.type in ("basias", "basol")]
    if sol_pollue:
        alerts.append(ServitudeAlert(
            level="critical",
            type="sol_pollue",
            message="Sol potentiellement pollué (BASIAS/BASOL). Étude des sols obligatoire, dépollution potentiellement requise.",
            source="georisques",
        ))

    # EBC
    ebc = [s for s in servitudes if "ebc" in s.categorie.lower() or "boisé" in s.libelle.lower()]
    if ebc:
        alerts.append(ServitudeAlert(
            level="warning",
            type="ebc",
            message="Espace Boisé Classé sur ou à proximité de la parcelle. Surface retirée du calcul d'emprise.",
            source="gpu",
        ))

    return alerts
```

- [ ] **Step 3: Run tests to verify they pass**

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/feasibility/servitudes.py apps/backend/tests/unit/test_feasibility_servitudes.py
git commit -m "feat(feasibility): add hard servitude constraint detection"
```

---

## Task 5: Brief comparison — écart brief vs max

**Files:**
- Create: `apps/backend/core/feasibility/brief_compare.py`
- Test: `apps/backend/tests/unit/test_feasibility_brief_compare.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_feasibility_brief_compare.py
"""Tests for brief vs max comparison."""
import pytest
from core.feasibility.brief_compare import compare_brief_to_max, classify_ratio
from core.feasibility.schemas import EcartItem


class TestClassifyRatio:
    def test_tres_sous_exploite(self):
        assert classify_ratio(0.5) == "tres_sous_exploite"
    def test_sous_exploite(self):
        assert classify_ratio(0.75) == "sous_exploite"
    def test_coherent(self):
        assert classify_ratio(0.92) == "coherent"
    def test_limite(self):
        assert classify_ratio(1.03) == "limite"
    def test_infaisable(self):
        assert classify_ratio(1.1) == "infaisable"


class TestCompareBriefToMax:
    def test_all_targets(self):
        ecarts = compare_brief_to_max(
            brief_nb_logements=20, max_nb_logements=30,
            brief_sdp_m2=1500, max_sdp_m2=2000,
            brief_hauteur_niveaux=4, max_niveaux=5,
            brief_emprise_pct=50, max_emprise_pct=60,
        )
        assert "nb_logements" in ecarts
        assert "sdp" in ecarts
        assert ecarts["nb_logements"].ratio == pytest.approx(20/30, rel=0.01)
        assert ecarts["nb_logements"].classification == "sous_exploite"

    def test_infaisable(self):
        ecarts = compare_brief_to_max(
            brief_nb_logements=50, max_nb_logements=30,
        )
        assert ecarts["nb_logements"].classification == "infaisable"

    def test_none_targets_skipped(self):
        ecarts = compare_brief_to_max(
            brief_nb_logements=None, max_nb_logements=30,
        )
        assert "nb_logements" not in ecarts
```

- [ ] **Step 2: Implement brief comparison**

```python
# apps/backend/core/feasibility/brief_compare.py
"""Comparison of user brief targets vs maximum buildable capacity."""
from __future__ import annotations
from core.feasibility.schemas import EcartItem

_THRESHOLDS = [
    (0.60, "tres_sous_exploite", "Opportunité significative perdue"),
    (0.85, "sous_exploite", "Possibilité de pousser le programme"),
    (1.00, "coherent", "Projet bien dimensionné"),
    (1.05, "limite", "Attention aux tolérances PLU"),
]
_INFAISABLE = ("infaisable", "Dépasse les contraintes PLU — système cap au maximum")


def classify_ratio(ratio: float) -> str:
    for threshold, classification, _ in _THRESHOLDS:
        if ratio < threshold:
            return classification
    return _INFAISABLE[0]


def _make_ecart(target: str, brief_val: float, max_val: float) -> EcartItem:
    ratio = brief_val / max_val if max_val > 0 else 0
    classification = classify_ratio(ratio)
    for t, c, comment in _THRESHOLDS:
        if classification == c:
            return EcartItem(target=target, brief_value=brief_val, max_value=max_val, ratio=round(ratio, 4), classification=classification, commentaire=comment)
    return EcartItem(target=target, brief_value=brief_val, max_value=max_val, ratio=round(ratio, 4), classification="infaisable", commentaire=_INFAISABLE[1])


def compare_brief_to_max(
    *,
    brief_nb_logements: int | None = None, max_nb_logements: int = 0,
    brief_sdp_m2: float | None = None, max_sdp_m2: float = 0,
    brief_hauteur_niveaux: int | None = None, max_niveaux: int = 0,
    brief_emprise_pct: float | None = None, max_emprise_pct: float = 0,
) -> dict[str, EcartItem]:
    ecarts = {}
    if brief_nb_logements is not None and max_nb_logements > 0:
        ecarts["nb_logements"] = _make_ecart("nb_logements", brief_nb_logements, max_nb_logements)
    if brief_sdp_m2 is not None and max_sdp_m2 > 0:
        ecarts["sdp"] = _make_ecart("sdp", brief_sdp_m2, max_sdp_m2)
    if brief_hauteur_niveaux is not None and max_niveaux > 0:
        ecarts["hauteur"] = _make_ecart("hauteur", brief_hauteur_niveaux, max_niveaux)
    if brief_emprise_pct is not None and max_emprise_pct > 0:
        ecarts["emprise"] = _make_ecart("emprise", brief_emprise_pct, max_emprise_pct)
    return ecarts
```

- [ ] **Step 3: Run tests, commit**

```bash
git add apps/backend/core/feasibility/brief_compare.py apps/backend/tests/unit/test_feasibility_brief_compare.py
git commit -m "feat(feasibility): add brief vs max comparison with PLU threshold classification"
```

---

## Task 6: Compliance modules — incendie, PMR, RE2020, LLS/SRU, RSDU

**Files:**
- Create: `apps/backend/core/compliance/__init__.py`
- Create: `apps/backend/core/compliance/incendie.py`
- Create: `apps/backend/core/compliance/pmr.py`
- Create: `apps/backend/core/compliance/re2020.py`
- Create: `apps/backend/core/compliance/lls_sru.py`
- Create: `apps/backend/core/compliance/rsdu.py`
- Test: `apps/backend/tests/unit/test_compliance_incendie.py`
- Test: `apps/backend/tests/unit/test_compliance_pmr.py`
- Test: `apps/backend/tests/unit/test_compliance_re2020.py`
- Test: `apps/backend/tests/unit/test_compliance_lls_sru.py`
- Test: `apps/backend/tests/unit/test_compliance_rsdu.py`

- [ ] **Step 1: Write all compliance tests**

Tests for each module:

**incendie:** test_1ere_famille (individuel ≤R+1), test_3A (collectif ≤28m), test_4eme_famille (28-50m), test_igh (>50m), test_coef_escalade (unsourced values → "à valider")

**pmr:** test_ascenseur_r3 (obligatory ≥R+3), test_places_pmr (ceil 2%), test_no_ascenseur_r2

**re2020:** test_seuil_2025 (ic ≤650), test_seuil_2028 (ic ≤480), test_indicatif_warning

**lls_sru:** test_commune_carencee (obligation LLS), test_commune_conforme (no obligation), test_bonus_35pct

**rsdu:** test_rsdu_obligations (vélo, poubelles, aération)

- [ ] **Step 2: Implement all 5 compliance modules**

Each module follows the same pattern:
- Pure function taking relevant inputs
- Returns a partial ComplianceResult or specific dataclass
- Escalates as "à valider" when coefficients are unsourced (spec constraint)

```python
# core/compliance/incendie.py
def classify_incendie(*, hauteur_m: float, nb_niveaux: int, destination: str) -> tuple[str, float]:
    """Returns (classement, coef_reduction_sdp). Coef is 1.0 until sourced."""

# core/compliance/pmr.py
def compute_pmr(*, nb_niveaux: int, nb_places: int) -> tuple[bool, float, int]:
    """Returns (ascenseur_obligatoire, surface_circulations_m2, nb_places_pmr)."""

# core/compliance/re2020.py
def estimate_re2020(*, destination: str, annee_cible: int) -> tuple[float | None, float | None, str]:
    """Returns (ic_construction, ic_energie, seuil_applicable). All indicatif."""

# core/compliance/lls_sru.py
def compute_lls_obligation(*, statut: str, sdp_m2: float, nb_logements: int) -> tuple[float | None, float | None]:
    """Returns (obligation_pct, bonus_pct)."""

# core/compliance/rsdu.py
def compute_rsdu_obligations() -> list[str]:
    """Returns list of RSDU IDF obligations (vélo, poubelles, etc.)."""
```

- [ ] **Step 3: Run all compliance tests**

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/compliance/ apps/backend/tests/unit/test_compliance_*.py
git commit -m "feat(compliance): add incendie, PMR, RE2020, LLS/SRU, RSDU modules"
```

---

## Task 7: Feasibility engine orchestrator

**Files:**
- Create: `apps/backend/core/feasibility/engine.py`
- (Tested via integration tests in Task 8)

- [ ] **Step 1: Implement engine**

```python
# apps/backend/core/feasibility/engine.py
"""Feasibility engine — orchestrates footprint, capacity, servitudes, compliance, and brief comparison."""
from __future__ import annotations
from core.feasibility.schemas import Brief, FeasibilityResult, ComplianceResult
from core.feasibility.footprint import compute_footprint
from core.feasibility.capacity import compute_capacity
from core.feasibility.servitudes import detect_servitudes_alerts
from core.feasibility.brief_compare import compare_brief_to_max
from core.compliance.incendie import classify_incendie
from core.compliance.pmr import compute_pmr
from core.compliance.re2020 import estimate_re2020
from core.compliance.lls_sru import compute_lls_obligation
from core.compliance.rsdu import compute_rsdu_obligations
from core.plu.schemas import NumericRules
from shapely.geometry import shape


def run_feasibility(
    *,
    terrain_geojson: dict,
    numeric_rules: NumericRules,
    brief: Brief,
    monuments: list = None,
    risques: list = None,
    servitudes_gpu: list = None,
    altitude_sol_m: float | None = None,
    commune_sru_statut: str = "non_soumise",
    annee_cible_pc: int = 2025,
) -> FeasibilityResult:
    """Run complete feasibility analysis."""
    # ... orchestrate all steps
    # Returns FeasibilityResult
```

- [ ] **Step 2: Commit**

```bash
git add apps/backend/core/feasibility/engine.py
git commit -m "feat(feasibility): add engine orchestrator combining all analysis steps"
```

---

## Task 8: DB models projects + migration + API endpoints + worker

**Files:**
- Create: `apps/backend/db/models/projects.py`
- Create: `apps/backend/alembic/versions/20260418_0001_projects.py`
- Create: `apps/backend/api/routes/projects.py`
- Create: `apps/backend/schemas/project.py`
- Create: `apps/backend/workers/feasibility.py`
- Modify: `apps/backend/api/main.py`
- Test: `apps/backend/tests/integration/test_projects_endpoints.py`

- [ ] **Step 1: Create DB models**

```python
# db/models/projects.py
class ProjectRow(Base):
    __tablename__ = "projects"
    id: UUID PK, user_id: UUID FK users, name: Text, brief: JSONB,
    status: Text (draft/analyzed/archived), created_at, updated_at

class ProjectParcelRow(Base):
    __tablename__ = "project_parcels"
    project_id: UUID FK projects, parcel_id: UUID FK parcels,
    ordering: SmallInteger, PK(project_id, parcel_id)

class FeasibilityResultRow(Base):
    __tablename__ = "feasibility_results"
    id: UUID PK, project_id: UUID FK projects, result: JSONB,
    footprint_geom: Geometry(MultiPolygon, 4326),
    zone_rules_used: ARRAY(UUID), confidence_score: Numeric,
    warnings: JSONB, generated_at: DateTime
```

- [ ] **Step 2: Migration + API routes + worker**

Create migration, API endpoints (POST /projects, GET /projects, POST /projects/{id}/analyze, GET /projects/{id}/analyze/status), ARQ worker, register router.

- [ ] **Step 3: Integration tests**

- [ ] **Step 4: Commit**

```bash
git add apps/backend/db/models/projects.py apps/backend/alembic/ apps/backend/api/routes/projects.py apps/backend/schemas/project.py apps/backend/workers/feasibility.py apps/backend/api/main.py apps/backend/tests/integration/test_projects_endpoints.py
git commit -m "feat(api): add projects CRUD, /analyze endpoint, feasibility worker"
```

---

## Task 9: Vérification finale

- [ ] **Step 1: Run ruff**
- [ ] **Step 2: Run full test suite**
- [ ] **Step 3: Fix issues + commit cleanup**
