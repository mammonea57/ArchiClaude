# ArchiClaude — Améliorations SP1 : Maximisation acceptation PC — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter 6 modules d'intelligence au sous-projet 1 pour maximiser la surface construite et les chances d'acceptation du PC : score de risque recours hybride, motifs de refus géolocalisés avec dédoublonnage PC, checklist pré-instruction, analyse vue droite/oblique avec Vision Claude, simulation ombre portée (2 modes), marge de sécurité PLU adaptative (plancher 96%).

**Architecture:** Modules purs `core/analysis/` (risk_score, refusal_patterns, vue_analysis, shadow, pre_instruction) + `core/feasibility/smart_margin.py`. Intégration dans le pipeline existant entre compliance et analyse architecte Opus. Enrichissement du prompt Opus pour score risque + checklist. Composants frontend additionnels.

**Tech Stack:** Python 3.12, shapely (ombre portée géométrique), math (astronomie solaire), anthropic SDK (Vision Claude pour fenêtres), pytest.

**Spec source:** `docs/superpowers/specs/2026-04-18-archiclaude-sp1-ameliorations-maximisation.md`

---

## File Structure

```
apps/backend/
├── core/
│   ├── analysis/
│   │   ├── risk_score.py                    (NEW — score hybride calculé + Opus)
│   │   ├── refusal_patterns.py              (NEW — motifs de refus géolocalisés)
│   │   ├── pre_instruction.py               (NEW — checklist pré-dépôt)
│   │   ├── vue_analysis.py                  (NEW — vue droite/oblique R.111-18/19)
│   │   ├── shadow.py                        (NEW — ombre portée 2 modes)
│   │   └── architect_prompt.py              (MODIFY — enrichir prompt Opus)
│   └── feasibility/
│       ├── smart_margin.py                  (NEW — marge adaptative 96-100%)
│       ├── schemas.py                       (MODIFY — nouveaux champs FeasibilityResult)
│       └── engine.py                        (MODIFY — intégrer nouveaux modules)
├── schemas/
│   └── analysis.py                          (NEW — API schemas pour nouveaux modules)
└── tests/
    └── unit/
        ├── test_risk_score.py               (NEW)
        ├── test_refusal_patterns.py         (NEW)
        ├── test_pre_instruction.py          (NEW)
        ├── test_vue_analysis.py             (NEW)
        ├── test_shadow.py                   (NEW)
        └── test_smart_margin.py             (NEW)

apps/frontend/src/
└── components/
    └── analysis/
        ├── RiskScoreGauge.tsx               (NEW)
        ├── RefusalPatternsAlert.tsx          (NEW)
        ├── PreInstructionChecklist.tsx       (NEW)
        ├── VueConflictsMap.tsx              (NEW)
        ├── ShadowSimulation.tsx             (NEW)
        └── SmartMarginTable.tsx             (NEW)
```

---

## Task 1: Schemas — nouveaux types pour les 6 modules

**Files:**
- Modify: `apps/backend/core/feasibility/schemas.py`
- Create: `apps/backend/core/analysis/risk_score.py` (just dataclasses for now)

- [ ] **Step 1: Add new dataclasses and extend FeasibilityResult**

Add to `core/feasibility/schemas.py`:

```python
# --- Nouveaux types pour améliorations SP1 ---

class RiskScore(BaseModel):
    score_calcule: int  # 0-100
    score_opus: int | None = None  # 0-100
    score_final: int  # 0-100
    justification_opus: str | None = None
    detail_calcul: dict[str, int] = Field(default_factory=dict)  # facteur → points

class RefusalPattern(BaseModel):
    motif: str  # hauteur_excessive, vis_a_vis, ombre, insertion
    occurrences_500m: int
    dernier_cas: str | None = None
    projet_concerne: bool = False
    recommandation: str = ""

class LocalContext(BaseModel):
    gabarit_dominant_niveaux: int | None = None
    gabarit_dominant_m: float | None = None
    projet_depasse_gabarit: bool = False
    depassement_niveaux: int = 0
    pc_acceptes_500m: list[dict] = Field(default_factory=list)
    pc_refuses_500m: list[dict] = Field(default_factory=list)
    patterns: list[RefusalPattern] = Field(default_factory=list)

class PreInstructionItem(BaseModel):
    demarche: str
    timing_jours: int  # J-X avant dépôt
    priorite: Literal["obligatoire", "fortement_recommande", "recommande"] = "recommande"
    raison: str = ""
    contact_type: str | None = None

class Ouverture(BaseModel):
    batiment_id: str
    etage: int
    type: str  # fenetre, porte_fenetre, balcon, loggia
    lat: float
    lng: float

class VueConflict(BaseModel):
    ouverture: Ouverture
    distance_m: float
    type_vue: Literal["droite", "oblique"]
    distance_min_requise_m: float  # 19 or 6
    deficit_m: float

class VueAnalysisResult(BaseModel):
    ouvertures_detectees: list[Ouverture] = Field(default_factory=list)
    conflits: list[VueConflict] = Field(default_factory=list)
    nb_conflits_droite: int = 0
    nb_conflits_oblique: int = 0
    risque_vue: Literal["aucun", "mineur", "majeur"] = "aucun"

class ShadowResult(BaseModel):
    # Mode A — diagramme solaire
    critical_shadows: list[dict] = Field(default_factory=list)  # 3 ombres critiques
    max_shadow_length_m: float = 0.0
    # Mode B — contextuel
    ombre_existante_m2: float | None = None
    ombre_future_m2: float | None = None
    ombre_ajoutee_m2: float | None = None
    pct_aggravation: float | None = None
    batiments_impactes: list[dict] = Field(default_factory=list)

class RecommendedProgramme(BaseModel):
    marge_pct: float  # 96-100
    sdp_recommandee_m2: float
    sdp_max_m2: float
    raison_marge: str
    ajustement_comparables: bool = False
```

Add to `FeasibilityResult`:
```python
    # Nouveaux champs améliorations SP1
    risk_score: RiskScore | None = None
    refusal_patterns: LocalContext | None = None
    pre_instruction_checklist: list[PreInstructionItem] = Field(default_factory=list)
    vue_analysis: VueAnalysisResult | None = None
    shadow_analysis: ShadowResult | None = None
    recommended_programme: RecommendedProgramme | None = None
```

- [ ] **Step 2: Commit**

```bash
git commit -m "feat(schemas): add risk score, vue analysis, shadow, smart margin types to FeasibilityResult"
```

---

## Task 2: Score de risque recours — partie calculée

**Files:**
- Create: `apps/backend/core/analysis/risk_score.py`
- Test: `apps/backend/tests/unit/test_risk_score.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_risk_score.py
"""Tests for hybrid risk score calculation."""
import pytest
from core.analysis.risk_score import compute_risk_score_calcule, compute_risk_score_final


class TestComputeRiskScoreCalcule:
    def test_zero_risk(self):
        score, detail = compute_risk_score_calcule(
            nb_recours_commune=0, nb_recours_500m=0, associations_actives=0,
            projet_depasse_gabarit=False, depassement_niveaux=0,
            abf_obligatoire=False, nb_conflits_vue=0,
        )
        assert score == 0
        assert all(v == 0 for v in detail.values())

    def test_high_risk_commune(self):
        score, detail = compute_risk_score_calcule(
            nb_recours_commune=10, nb_recours_500m=3, associations_actives=2,
            projet_depasse_gabarit=True, depassement_niveaux=3,
            abf_obligatoire=True, nb_conflits_vue=2,
        )
        assert score > 60  # should be high
        assert score <= 100

    def test_abf_adds_10(self):
        s1, _ = compute_risk_score_calcule(
            nb_recours_commune=0, nb_recours_500m=0, associations_actives=0,
            projet_depasse_gabarit=False, depassement_niveaux=0,
            abf_obligatoire=False, nb_conflits_vue=0,
        )
        s2, _ = compute_risk_score_calcule(
            nb_recours_commune=0, nb_recours_500m=0, associations_actives=0,
            projet_depasse_gabarit=False, depassement_niveaux=0,
            abf_obligatoire=True, nb_conflits_vue=0,
        )
        assert s2 - s1 == 10

    def test_vue_conflicts_add_points(self):
        score, detail = compute_risk_score_calcule(
            nb_recours_commune=0, nb_recours_500m=0, associations_actives=0,
            projet_depasse_gabarit=False, depassement_niveaux=0,
            abf_obligatoire=False, nb_conflits_vue=3,
        )
        assert detail["vue_conflicts"] == 45  # 3 * 15


class TestComputeRiskScoreFinal:
    def test_weighted_average(self):
        final = compute_risk_score_final(score_calcule=40, score_opus=60)
        # 0.4 * 40 + 0.6 * 60 = 16 + 36 = 52
        assert final == 52

    def test_opus_none_uses_calcule(self):
        final = compute_risk_score_final(score_calcule=40, score_opus=None)
        assert final == 40

    def test_clamped_100(self):
        final = compute_risk_score_final(score_calcule=100, score_opus=100)
        assert final == 100
```

- [ ] **Step 2: Implement risk score**

```python
# apps/backend/core/analysis/risk_score.py
"""Hybrid risk score — calculated component + Opus AI component."""
from __future__ import annotations


def compute_risk_score_calcule(
    *,
    nb_recours_commune: int,
    nb_recours_500m: int,
    associations_actives: int,
    projet_depasse_gabarit: bool,
    depassement_niveaux: int,
    abf_obligatoire: bool,
    nb_conflits_vue: int,
) -> tuple[int, dict[str, int]]:
    """Compute the data-driven risk score (0-100).

    Returns (score, detail_dict) where detail_dict maps factor → points.
    """
    detail: dict[str, int] = {}

    # Recours commune (max 20)
    detail["recours_commune"] = min(20, nb_recours_commune * 2)

    # Recours 500m (max 15)
    detail["recours_500m"] = min(15, nb_recours_500m * 5)

    # Associations actives (max 10)
    detail["associations"] = min(10, associations_actives * 5)

    # Dépassement gabarit voisinage (max 20)
    if projet_depasse_gabarit:
        detail["gabarit"] = min(20, 5 + depassement_niveaux * 5)
    else:
        detail["gabarit"] = 0

    # ABF (fixe 10)
    detail["abf"] = 10 if abf_obligatoire else 0

    # Conflits de vue (15 par conflit, max 45 → capped in total)
    detail["vue_conflicts"] = min(45, nb_conflits_vue * 15)

    score = min(100, sum(detail.values()))
    return score, detail


def compute_risk_score_final(
    *, score_calcule: int, score_opus: int | None
) -> int:
    """Combine calculated and Opus scores: 0.4 × calc + 0.6 × opus.

    If Opus score is None (not available), uses calculated score alone.
    """
    if score_opus is None:
        return min(100, score_calcule)
    return min(100, round(0.4 * score_calcule + 0.6 * score_opus))
```

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat(analysis): add hybrid risk score calculator"
```

---

## Task 3: Motifs de refus géolocalisés + dédoublonnage PC

**Files:**
- Create: `apps/backend/core/analysis/refusal_patterns.py`
- Test: `apps/backend/tests/unit/test_refusal_patterns.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_refusal_patterns.py
"""Tests for geolocalized refusal pattern analysis."""
import pytest
from core.analysis.refusal_patterns import (
    analyze_local_context, deduplicate_pc, GabaritInfo,
)


class TestDeduplicatePc:
    def test_links_refused_then_accepted(self):
        pcs = [
            {"address": "12 Rue Test", "date": "2024-01-15", "status": "refused", "parcelle_ref": "94052-AB-42"},
            {"address": "12 Rue Test", "date": "2024-08-20", "status": "accepted", "parcelle_ref": "94052-AB-42"},
        ]
        result = deduplicate_pc(pcs)
        refused_pure = [p for p in result if p.get("status") == "refused" and not p.get("subsequently_accepted")]
        assert len(refused_pure) == 0  # the refusal was followed by acceptance

    def test_unrelated_refusal_kept(self):
        pcs = [
            {"address": "12 Rue Test", "date": "2024-01-15", "status": "refused", "parcelle_ref": "94052-AB-42"},
            {"address": "45 Rue Autre", "date": "2024-08-20", "status": "accepted", "parcelle_ref": "94052-CD-10"},
        ]
        result = deduplicate_pc(pcs)
        refused_pure = [p for p in result if p.get("status") == "refused" and not p.get("subsequently_accepted")]
        assert len(refused_pure) == 1

    def test_old_refusal_not_linked(self):
        """Refusal >18 months before acceptance = different project."""
        pcs = [
            {"address": "12 Rue Test", "date": "2022-01-15", "status": "refused", "parcelle_ref": "94052-AB-42"},
            {"address": "12 Rue Test", "date": "2024-08-20", "status": "accepted", "parcelle_ref": "94052-AB-42"},
        ]
        result = deduplicate_pc(pcs)
        refused_pure = [p for p in result if p.get("status") == "refused" and not p.get("subsequently_accepted")]
        assert len(refused_pure) == 1


class TestAnalyzeLocalContext:
    def test_gabarit_dominant(self):
        batiments = [
            {"hauteur": 9, "nb_etages": 3},
            {"hauteur": 12, "nb_etages": 4},
            {"hauteur": 9, "nb_etages": 3},
            {"hauteur": 10, "nb_etages": 3},
        ]
        gabarit = GabaritInfo.from_batiments(batiments)
        assert gabarit.dominant_niveaux == 3  # median
        assert gabarit.dominant_m == 9.5  # median

    def test_projet_depasse(self):
        batiments = [{"hauteur": 9, "nb_etages": 3}] * 5
        gabarit = GabaritInfo.from_batiments(batiments)
        assert gabarit.projet_depasse(projet_niveaux=5) is True
        assert gabarit.depassement_niveaux(projet_niveaux=5) == 2

    def test_projet_coherent(self):
        batiments = [{"hauteur": 15, "nb_etages": 5}] * 5
        gabarit = GabaritInfo.from_batiments(batiments)
        assert gabarit.projet_depasse(projet_niveaux=5) is False
```

- [ ] **Step 2: Implement refusal patterns**

```python
# apps/backend/core/analysis/refusal_patterns.py
"""Geolocalized refusal pattern analysis with PC deduplication."""
from __future__ import annotations
import statistics
from dataclasses import dataclass
from datetime import datetime


class GabaritInfo:
    """Neighborhood dominant building gabarit from BDTopo data."""

    def __init__(self, dominant_niveaux: int, dominant_m: float) -> None:
        self.dominant_niveaux = dominant_niveaux
        self.dominant_m = dominant_m

    @classmethod
    def from_batiments(cls, batiments: list[dict]) -> "GabaritInfo":
        if not batiments:
            return cls(dominant_niveaux=0, dominant_m=0.0)
        niveaux = [b.get("nb_etages", 0) for b in batiments if b.get("nb_etages")]
        hauteurs = [b.get("hauteur", 0) for b in batiments if b.get("hauteur")]
        return cls(
            dominant_niveaux=round(statistics.median(niveaux)) if niveaux else 0,
            dominant_m=round(statistics.median(hauteurs), 1) if hauteurs else 0.0,
        )

    def projet_depasse(self, projet_niveaux: int) -> bool:
        return projet_niveaux > self.dominant_niveaux and self.dominant_niveaux > 0

    def depassement_niveaux(self, projet_niveaux: int) -> int:
        return max(0, projet_niveaux - self.dominant_niveaux)


def deduplicate_pc(pcs: list[dict]) -> list[dict]:
    """Link refused PCs that were subsequently accepted after modification.

    Same address/parcelle + accepted within 18 months of refusal = same project.
    The refusal is marked 'subsequently_accepted=True' and does NOT count as a pure refusal.
    """
    MAX_MONTHS = 18
    result = [dict(p) for p in pcs]  # copy

    refused = [p for p in result if p.get("status") == "refused"]
    accepted = [p for p in result if p.get("status") == "accepted"]

    for ref in refused:
        ref_key = ref.get("parcelle_ref") or ref.get("address", "")
        ref_date = _parse_date(ref.get("date", ""))
        if not ref_date:
            continue

        for acc in accepted:
            acc_key = acc.get("parcelle_ref") or acc.get("address", "")
            acc_date = _parse_date(acc.get("date", ""))
            if not acc_date:
                continue

            if ref_key == acc_key and acc_date > ref_date:
                months_diff = (acc_date.year - ref_date.year) * 12 + (acc_date.month - ref_date.month)
                if months_diff <= MAX_MONTHS:
                    ref["subsequently_accepted"] = True
                    break

    return result


def _parse_date(date_str: str) -> datetime | None:
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None


def analyze_local_context(
    *,
    batiments_200m: list[dict],
    pc_500m: list[dict],
    projet_niveaux: int,
) -> dict:
    """Analyze local context: gabarit dominant + PC history."""
    gabarit = GabaritInfo.from_batiments(batiments_200m)
    deduped = deduplicate_pc(pc_500m)

    refused_pure = [p for p in deduped if p.get("status") == "refused" and not p.get("subsequently_accepted")]
    accepted = [p for p in deduped if p.get("status") == "accepted"]

    return {
        "gabarit_dominant_niveaux": gabarit.dominant_niveaux,
        "gabarit_dominant_m": gabarit.dominant_m,
        "projet_depasse_gabarit": gabarit.projet_depasse(projet_niveaux),
        "depassement_niveaux": gabarit.depassement_niveaux(projet_niveaux),
        "nb_pc_acceptes": len(accepted),
        "nb_pc_refuses_purs": len(refused_pure),
    }
```

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat(analysis): add geolocalized refusal patterns with PC deduplication"
```

---

## Task 4: Checklist pré-instruction

**Files:**
- Create: `apps/backend/core/analysis/pre_instruction.py`
- Test: `apps/backend/tests/unit/test_pre_instruction.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_pre_instruction.py
"""Tests for pre-instruction checklist generation."""
import pytest
from core.analysis.pre_instruction import generate_checklist


class TestGenerateChecklist:
    def test_always_includes_geometre(self):
        items = generate_checklist(alerts=[], risk_score=10)
        geos = [i for i in items if "géomètre" in i.demarche.lower()]
        assert len(geos) == 1
        assert geos[0].timing_jours == 90

    def test_abf_when_monument(self):
        items = generate_checklist(
            alerts=[{"type": "abf"}], risk_score=30,
        )
        abf = [i for i in items if "ABF" in i.demarche or "abf" in i.contact_type]
        assert len(abf) >= 1
        assert abf[0].priorite == "obligatoire"

    def test_g2_when_argiles(self):
        items = generate_checklist(
            alerts=[{"type": "argiles"}], risk_score=20,
        )
        g2 = [i for i in items if "G2" in i.demarche or "géotechnique" in i.demarche.lower()]
        assert len(g2) >= 1

    def test_pre_instruction_rdv_high_risk(self):
        items = generate_checklist(alerts=[], risk_score=50)
        rdv = [i for i in items if "pré-instruction" in i.demarche.lower()]
        assert len(rdv) >= 1
        assert rdv[0].priorite in ("obligatoire", "fortement_recommande")

    def test_acoustique_when_bruit(self):
        items = generate_checklist(
            alerts=[{"type": "bruit_cat_1"}], risk_score=20,
        )
        acous = [i for i in items if "acoustique" in i.demarche.lower()]
        assert len(acous) >= 1

    def test_sorted_by_timing(self):
        items = generate_checklist(
            alerts=[{"type": "abf"}, {"type": "argiles"}], risk_score=60,
        )
        timings = [i.timing_jours for i in items]
        assert timings == sorted(timings, reverse=True)  # J-90 before J-30
```

- [ ] **Step 2: Implement checklist**

Deterministic function based on alerts and risk score. Each applicable démarche is included with timing and priority. Sorted by timing descending (earliest first).

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat(analysis): add pre-instruction checklist generator"
```

---

## Task 5: Simulation ombre portée (2 modes)

**Files:**
- Create: `apps/backend/core/analysis/shadow.py`
- Test: `apps/backend/tests/unit/test_shadow.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_shadow.py
"""Tests for shadow simulation — solar diagram + contextual modes."""
import pytest
from shapely.geometry import Polygon
from core.analysis.shadow import (
    compute_sun_position, compute_shadow_polygon,
    compute_shadow_mode_a, compute_shadow_mode_b,
)


class TestSunPosition:
    def test_paris_winter_solstice_noon(self):
        alt, azi = compute_sun_position(
            lat=48.8566, lng=2.3522, month=12, day=21, hour=12,
        )
        assert 15 < alt < 25  # sun is low in winter (~18.5°)
        assert 170 < azi < 190  # roughly south

    def test_paris_summer_solstice_noon(self):
        alt, azi = compute_sun_position(
            lat=48.8566, lng=2.3522, month=6, day=21, hour=12,
        )
        assert 60 < alt < 70  # sun is high in summer (~65°)


class TestShadowPolygon:
    def test_shadow_projects_north_at_noon(self):
        building = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        shadow = compute_shadow_polygon(building, hauteur_m=10, sun_altitude=30, sun_azimuth=180)
        # Sun from south → shadow projects north (positive y)
        assert shadow.centroid.y > building.centroid.y

    def test_shadow_length(self):
        building = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        shadow = compute_shadow_polygon(building, hauteur_m=10, sun_altitude=45, sun_azimuth=180)
        # tan(45°) = 1, shadow length = 10/1 = 10m
        # Shadow should extend ~10m from building
        assert shadow.bounds[3] - building.bounds[3] == pytest.approx(10, abs=1)


class TestModeA:
    def test_returns_critical_shadows(self):
        building = Polygon([(0, 0), (20, 0), (20, 15), (0, 15)])
        result = compute_shadow_mode_a(building, hauteur_m=15)
        assert len(result.critical_shadows) == 3  # 21 dec 10h, 12h, 14h
        assert result.max_shadow_length_m > 0


class TestModeB:
    def test_aggravation_calculated(self):
        projet = Polygon([(0, 0), (20, 0), (20, 15), (0, 15)])
        voisins = [
            {"geometry": Polygon([(25, 0), (35, 0), (35, 10), (25, 10)]), "hauteur": 9},
        ]
        result = compute_shadow_mode_b(projet, hauteur_m=15, voisins=voisins)
        assert result.ombre_future_m2 is not None
        assert result.ombre_existante_m2 is not None
        assert result.pct_aggravation is not None
```

- [ ] **Step 2: Implement shadow module**

```python
# apps/backend/core/analysis/shadow.py
"""Shadow simulation — solar position + shadow projection.

Mode A: Annual solar diagram (132 positions)
Mode B: Contextual with existing BDTopo neighbors (aggravation %)
"""
from __future__ import annotations
import math
from dataclasses import dataclass

from shapely.affinity import translate
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union


def compute_sun_position(
    *, lat: float, lng: float, month: int, day: int, hour: int
) -> tuple[float, float]:
    """Compute solar altitude and azimuth for a given position and time.

    Simplified astronomical calculation for metropolitan France.
    Returns (altitude_degrees, azimuth_degrees) where azimuth 0=north, 180=south.
    """
    # Day of year
    days_in_months = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    doy = days_in_months[month - 1] + day

    # Solar declination (Spencer formula simplified)
    B = (360 / 365) * (doy - 81)
    B_rad = math.radians(B)
    declination = 23.45 * math.sin(B_rad)

    # Hour angle (15° per hour from solar noon)
    # Approximate solar noon at lng=2.35 → ~12:10 UTC+1
    hour_angle = (hour - 12) * 15

    lat_rad = math.radians(lat)
    dec_rad = math.radians(declination)
    ha_rad = math.radians(hour_angle)

    # Altitude
    sin_alt = (math.sin(lat_rad) * math.sin(dec_rad) +
               math.cos(lat_rad) * math.cos(dec_rad) * math.cos(ha_rad))
    altitude = math.degrees(math.asin(max(-1, min(1, sin_alt))))

    # Azimuth
    cos_azi = (math.sin(dec_rad) - math.sin(lat_rad) * sin_alt) / (
        math.cos(lat_rad) * math.cos(math.radians(altitude)) + 1e-10
    )
    azimuth = math.degrees(math.acos(max(-1, min(1, cos_azi))))
    if hour_angle > 0:
        azimuth = 360 - azimuth

    return altitude, azimuth


def compute_shadow_polygon(
    building: BaseGeometry,
    hauteur_m: float,
    sun_altitude: float,
    sun_azimuth: float,
) -> BaseGeometry:
    """Project building shadow on the ground given sun position."""
    if sun_altitude <= 0:
        return Polygon()  # sun below horizon

    shadow_length = hauteur_m / math.tan(math.radians(sun_altitude))
    shadow_azimuth_rad = math.radians((sun_azimuth + 180) % 360)

    dx = shadow_length * math.sin(shadow_azimuth_rad)
    dy = shadow_length * math.cos(shadow_azimuth_rad)

    shadow = translate(building, xoff=dx, yoff=dy)
    return unary_union([building, shadow]).convex_hull


@dataclass
class ShadowModeAResult:
    critical_shadows: list[dict]
    max_shadow_length_m: float

@dataclass
class ShadowModeBResult:
    ombre_existante_m2: float
    ombre_future_m2: float
    ombre_ajoutee_m2: float
    pct_aggravation: float
    batiments_impactes: list[dict]


def compute_shadow_mode_a(
    building: BaseGeometry, hauteur_m: float, lat: float = 48.8566, lng: float = 2.3522
) -> ShadowModeAResult:
    """Mode A: Critical shadows at winter solstice (Dec 21 at 10h, 12h, 14h)."""
    critical_times = [(12, 21, 10), (12, 21, 12), (12, 21, 14)]
    critical_shadows = []
    max_length = 0.0

    for month, day, hour in critical_times:
        alt, azi = compute_sun_position(lat=lat, lng=lng, month=month, day=day, hour=hour)
        if alt > 0:
            shadow = compute_shadow_polygon(building, hauteur_m, alt, azi)
            length = hauteur_m / math.tan(math.radians(alt)) if alt > 0 else 0
            max_length = max(max_length, length)
            critical_shadows.append({
                "time": f"21 déc {hour}h",
                "sun_altitude": round(alt, 1),
                "sun_azimuth": round(azi, 1),
                "shadow_length_m": round(length, 1),
                "shadow_area_m2": round(shadow.area, 1),
            })

    return ShadowModeAResult(critical_shadows=critical_shadows, max_shadow_length_m=round(max_length, 1))


def compute_shadow_mode_b(
    projet: BaseGeometry,
    hauteur_m: float,
    voisins: list[dict],
    lat: float = 48.8566,
    lng: float = 2.3522,
) -> ShadowModeBResult:
    """Mode B: Contextual with neighbors — compute aggravation %."""
    # Use winter solstice noon as reference
    alt, azi = compute_sun_position(lat=lat, lng=lng, month=12, day=21, hour=12)

    # Existing shadows (neighbors only)
    existing_shadows = []
    for v in voisins:
        geom = v.get("geometry")
        h = v.get("hauteur", 0)
        if geom and h > 0 and alt > 0:
            existing_shadows.append(compute_shadow_polygon(geom, h, alt, azi))

    ombre_existante = unary_union(existing_shadows) if existing_shadows else Polygon()

    # Future shadows (neighbors + project)
    projet_shadow = compute_shadow_polygon(projet, hauteur_m, alt, azi) if alt > 0 else Polygon()
    all_shadows = existing_shadows + [projet_shadow]
    ombre_future = unary_union(all_shadows) if all_shadows else Polygon()

    ombre_ajoutee = ombre_future.difference(ombre_existante)

    area_future = ombre_future.area
    area_ajoutee = ombre_ajoutee.area
    pct = (area_ajoutee / area_future * 100) if area_future > 0 else 0

    return ShadowModeBResult(
        ombre_existante_m2=round(ombre_existante.area, 1),
        ombre_future_m2=round(area_future, 1),
        ombre_ajoutee_m2=round(area_ajoutee, 1),
        pct_aggravation=round(pct, 1),
        batiments_impactes=[],
    )
```

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat(analysis): add shadow simulation — solar diagram + contextual modes"
```

---

## Task 6: Analyse vue droite / vue oblique

**Files:**
- Create: `apps/backend/core/analysis/vue_analysis.py`
- Test: `apps/backend/tests/unit/test_vue_analysis.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_vue_analysis.py
"""Tests for vue droite/oblique conflict detection."""
import pytest
from core.analysis.vue_analysis import (
    detect_vue_conflicts, classify_vue_type, VueConflictResult,
)


class TestClassifyVueType:
    def test_droite(self):
        assert classify_vue_type(angle_deg=10) == "droite"  # < 45°
        assert classify_vue_type(angle_deg=44) == "droite"

    def test_oblique(self):
        assert classify_vue_type(angle_deg=46) == "oblique"
        assert classify_vue_type(angle_deg=89) == "oblique"


class TestDetectVueConflicts:
    def test_no_conflicts(self):
        ouvertures = [
            {"lat": 48.838, "lng": 2.485, "etage": 3, "type": "fenetre", "batiment_id": "b1"},
        ]
        footprint_centroid = (2.480, 48.835)  # far enough
        result = detect_vue_conflicts(
            ouvertures=ouvertures,
            footprint_centroid=footprint_centroid,
            projet_hauteur_m=15,
        )
        assert result.nb_conflits_droite == 0
        assert result.risque_vue == "aucun"

    def test_vue_droite_conflict(self):
        ouvertures = [
            {"lat": 48.83752, "lng": 2.48335, "etage": 3, "type": "fenetre", "batiment_id": "b1"},
        ]
        footprint_centroid = (2.48340, 48.83750)  # ~5m away
        result = detect_vue_conflicts(
            ouvertures=ouvertures,
            footprint_centroid=footprint_centroid,
            projet_hauteur_m=15,
        )
        assert result.nb_conflits_droite >= 1
        assert result.risque_vue == "majeur"

    def test_empty_ouvertures(self):
        result = detect_vue_conflicts(
            ouvertures=[], footprint_centroid=(2.48, 48.83), projet_hauteur_m=15,
        )
        assert result.risque_vue == "aucun"
```

- [ ] **Step 2: Implement vue analysis**

Module computing haversine distances from project footprint to each detected window, classifying as vue droite (≤45° angle, requires 19m) or vue oblique (>45°, requires 6m), flagging conflicts.

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat(analysis): add vue droite/oblique conflict detection (R.111-18/19)"
```

---

## Task 7: Marge de sécurité PLU adaptative

**Files:**
- Create: `apps/backend/core/feasibility/smart_margin.py`
- Test: `apps/backend/tests/unit/test_smart_margin.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_smart_margin.py
"""Tests for smart PLU margin — 96-100% based on risk score."""
import pytest
from core.feasibility.smart_margin import compute_smart_margin


class TestComputeSmartMargin:
    def test_very_safe_100pct(self):
        result = compute_smart_margin(risk_score=10, sdp_max=3000)
        assert result.marge_pct == 100
        assert result.sdp_recommandee == 3000

    def test_safe_98pct(self):
        result = compute_smart_margin(risk_score=30, sdp_max=3000)
        assert result.marge_pct == 98
        assert result.sdp_recommandee == 2940

    def test_medium_97pct(self):
        result = compute_smart_margin(risk_score=50, sdp_max=3000)
        assert result.marge_pct == 97

    def test_high_96pct(self):
        result = compute_smart_margin(risk_score=70, sdp_max=3000)
        assert result.marge_pct == 96

    def test_very_high_still_96pct(self):
        """Never goes below 96% — promoteur needs to maximize."""
        result = compute_smart_margin(risk_score=95, sdp_max=3000)
        assert result.marge_pct == 96
        assert result.sdp_recommandee == 2880

    def test_comparables_boost(self):
        """Comparables showing acceptance near max → raise margin."""
        result = compute_smart_margin(
            risk_score=50, sdp_max=3000,
            comparables_max_pct_accepted=99,
        )
        assert result.marge_pct >= 98  # boosted by comparables
        assert result.ajustement_comparables is True

    def test_zero_sdp(self):
        result = compute_smart_margin(risk_score=50, sdp_max=0)
        assert result.sdp_recommandee == 0
```

- [ ] **Step 2: Implement smart margin**

```python
# apps/backend/core/feasibility/smart_margin.py
"""Smart PLU margin — 96-100% based on risk score, calibrated by comparables.

RULE: Never below 96%. The promoteur maximizes profit.
Niveaux and emprise ALWAYS stay at PLU max — margin only applies to SDP.
"""
from __future__ import annotations
from dataclasses import dataclass

_MARGIN_TABLE = [
    (20, 100),   # risk < 20 → 100%
    (40, 98),    # risk 20-40 → 98%
    (60, 97),    # risk 40-60 → 97%
    (80, 96),    # risk 60-80 → 96%
    (101, 96),   # risk > 80 → 96% (floor)
]

_FLOOR_PCT = 96


@dataclass(frozen=True)
class SmartMarginResult:
    marge_pct: float
    sdp_recommandee: float
    sdp_max: float
    raison: str
    ajustement_comparables: bool


def compute_smart_margin(
    *,
    risk_score: int,
    sdp_max: float,
    comparables_max_pct_accepted: float | None = None,
) -> SmartMarginResult:
    """Compute recommended SDP with adaptive margin.

    Args:
        risk_score: 0-100 hybrid risk score.
        sdp_max: Maximum SDP allowed by PLU.
        comparables_max_pct_accepted: Highest % of max accepted in nearby comparables.
    """
    if sdp_max <= 0:
        return SmartMarginResult(marge_pct=100, sdp_recommandee=0, sdp_max=0,
                                  raison="SDP max nulle", ajustement_comparables=False)

    # Base margin from risk score
    base_pct = _FLOOR_PCT
    for threshold, pct in _MARGIN_TABLE:
        if risk_score < threshold:
            base_pct = pct
            break

    # Boost by comparables
    ajustement = False
    final_pct = base_pct
    if comparables_max_pct_accepted is not None and comparables_max_pct_accepted >= 97:
        # Nearby projects accepted at near-max → raise margin
        final_pct = max(base_pct, min(100, round(comparables_max_pct_accepted)))
        ajustement = final_pct > base_pct

    # Floor
    final_pct = max(_FLOOR_PCT, final_pct)

    sdp_rec = round(sdp_max * final_pct / 100, 2)

    raison = f"Score risque {risk_score}/100 → marge {final_pct}%"
    if ajustement:
        raison += f" (relevée par comparables acceptés à {comparables_max_pct_accepted}%)"

    return SmartMarginResult(
        marge_pct=final_pct,
        sdp_recommandee=sdp_rec,
        sdp_max=sdp_max,
        raison=raison,
        ajustement_comparables=ajustement,
    )
```

- [ ] **Step 3: Run tests, commit**

```bash
git commit -m "feat(feasibility): add smart PLU margin — 96-100% based on risk score"
```

---

## Task 8: Enrichissement prompt Opus + intégration pipeline

**Files:**
- Modify: `apps/backend/core/analysis/architect_prompt.py`
- Modify: `apps/backend/core/analysis/architect_analysis.py`
- Modify: `apps/backend/core/feasibility/engine.py`

- [ ] **Step 1: Enrich Opus prompt**

Add to SYSTEM_PROMPT in `architect_prompt.py`:
```
EN PLUS de la note d'opportunité, tu dois fournir :
1. Un SCORE DE RISQUE RECOURS (0-100) avec justification en 2-3 lignes
2. Des RECOMMANDATIONS PRÉ-INSTRUCTION contextuelles (3-5 démarches prioritaires)
3. Un commentaire sur les CONFLITS DE VUE détectés (si données fournies)
4. Un commentaire sur l'OMBRE PORTÉE du projet (si données fournies)
```

Add to `build_architect_prompt()`: new optional params for vue_analysis and shadow_analysis context injection.

- [ ] **Step 2: Integrate new modules in engine.py**

Add steps 7-11 to `run_feasibility()` pipeline between servitudes and RAG:
```python
# 7. Vue analysis (Vision Claude on Street View — stubbed until Vision wired)
# 8. Shadow simulation
# 9. Refusal patterns analysis
# 10. Risk score calculation
# 11. Smart margin
```

- [ ] **Step 3: Commit**

```bash
git commit -m "feat(engine): integrate risk score, shadow, vue, refusal patterns, smart margin into pipeline"
```

---

## Task 9: Frontend components + final verification

**Files:**
- Create: `apps/frontend/src/components/analysis/RiskScoreGauge.tsx`
- Create: `apps/frontend/src/components/analysis/RefusalPatternsAlert.tsx`
- Create: `apps/frontend/src/components/analysis/PreInstructionChecklist.tsx`
- Create: `apps/frontend/src/components/analysis/ShadowSimulation.tsx`
- Create: `apps/frontend/src/components/analysis/SmartMarginTable.tsx`

- [ ] **Step 1: Create all frontend components**

Simple presentational components:
- RiskScoreGauge: circular gauge 0-100, color-coded (green/yellow/orange/red)
- RefusalPatternsAlert: alert banner with gabarit dominant + local patterns
- PreInstructionChecklist: interactive checklist with timeline
- ShadowSimulation: SVG overlay placeholder (actual animation in SP3)
- SmartMarginTable: two-column table Max PLU vs Recommandé

- [ ] **Step 2: Run backend ruff + tests**
- [ ] **Step 3: Run frontend typecheck + build**
- [ ] **Step 4: Final commit**

```bash
git commit -m "feat(frontend): add risk score, refusal patterns, shadow, margin UI components"
```
