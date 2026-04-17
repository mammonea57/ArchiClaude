# ArchiClaude — Phase 3 : Extraction règles PLU — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire le moteur PLU hybride complet : schémas ParsedRules/NumericRules, extracteur LLM (port fidèle du bot TS), numericizer LLM, parser Paris Bioclimatique, DB zone_rules, endpoints extraction/validation, et worker ARQ async.

**Architecture:** Trois couches — (1) données structurées GPU déjà en place (Phase 1), (2) extraction textuelle LLM `core/plu/extractor.py` portant la logique complète du bot TS (regex multi-pass, scoring sections, filtrage PLUi, JSON repair, prompt caching, retry), (3) conversion numérique `core/plu/numericizer.py` via Claude Sonnet tool_use. Cache triple : mémoire LRU + filesystem + DB `zone_rules_text`. Parser dédié Paris Bioclimatique pour zéro coût LLM sur Paris.

**Tech Stack:** Python 3.12, anthropic SDK (prompt caching, tool_use), httpx (PDF fetch), pdfplumber (PDF→text), hashlib (sha256), functools.lru_cache, re (regex), asteval (formules paramétriques), ARQ (worker async), SQLAlchemy 2.0, Alembic, FastAPI.

**Spec source:** `docs/superpowers/specs/2026-04-16-archiclaude-sous-projet-1-design.md` §4 (Moteur PLU hybride), §7.2 (Endpoints /plu/*)

**Reference context:** Existing bot `~/Desktop/Urbanisme app/urbanisme-france-live/src/app/api/parse-reglement/route.ts` — READ ONLY. Full extraction pipeline logic ported from this file.

---

## File Structure (final état Phase 3)

```
apps/backend/
├── core/
│   └── plu/
│       ├── __init__.py                      (NEW)
│       ├── schemas.py                       (NEW — ParsedRules, NumericRules, RuleFormula, Bande)
│       ├── pdf_fetcher.py                   (NEW — fetch + extract text from PLU PDF)
│       ├── section_finder.py                (NEW — zone section identification + scoring)
│       ├── commune_filter.py                (NEW — PLUi commune paragraph filtering)
│       ├── extractor.py                     (NEW — LLM extraction pipeline, main orchestrator)
│       ├── json_repair.py                   (NEW — truncated JSON repair)
│       ├── value_cleaner.py                 (NEW — clean/validate/hoist extracted values)
│       ├── numericizer.py                   (NEW — ParsedRules → NumericRules via LLM tool_use)
│       ├── prompt.py                        (NEW — LLM prompt templates)
│       ├── cache.py                         (NEW — triple cache: memory + filesystem + DB)
│       └── parsers/
│           ├── __init__.py                  (NEW)
│           └── paris_bioclim.py             (NEW — dedicated parser Paris Bioclimatique)
├── api/
│   └── routes/
│       └── plu.py                           (MODIFY — add /zone/{id}/rules, /extract, /validate)
├── db/
│   └── models/
│       ├── zone_rules.py                    (NEW — zone_rules_text + zone_rules_numeric)
│       └── extraction_feedback.py           (NEW — user corrections telemetry)
├── schemas/
│   └── plu.py                               (MODIFY — add rules/extraction response schemas)
├── workers/
│   └── extraction.py                        (NEW — ARQ extraction worker)
├── alembic/versions/
│   └── 20260417_0003_zone_rules.py          (NEW)
└── tests/
    ├── unit/
    │   ├── test_plu_schemas.py              (NEW)
    │   ├── test_section_finder.py           (NEW)
    │   ├── test_commune_filter.py           (NEW)
    │   ├── test_json_repair.py              (NEW)
    │   ├── test_value_cleaner.py            (NEW)
    │   ├── test_extractor.py                (NEW)
    │   ├── test_numericizer.py              (NEW)
    │   └── test_paris_bioclim.py            (NEW)
    └── integration/
        └── test_plu_rules_endpoints.py      (NEW)
```

**Responsabilités par fichier :**
- `core/plu/schemas.py` : Pydantic models ParsedRules, NumericRules, RuleFormula, Bande — shared contracts
- `core/plu/pdf_fetcher.py` : download PDF from GPU URL, extract text via pdfplumber, compute sha256
- `core/plu/section_finder.py` : multi-pass regex zone section identification, scoring, boundary detection — port of `extractZoneSection()` + `extractFullZoneSection()`
- `core/plu/commune_filter.py` : PLUi filtering — port of `stripOtherCommunesFromSection()`
- `core/plu/extractor.py` : main orchestrator — PDF→text→section→filter→LLM→parse→clean→cache
- `core/plu/json_repair.py` : truncated JSON repair — port of `extractAndParseJson()`
- `core/plu/value_cleaner.py` : clean values, detect errors, hoist numbers — port of `cleanValue()` + `hoistChiffreFront()`
- `core/plu/prompt.py` : LLM prompt templates for extraction + numericization
- `core/plu/numericizer.py` : ParsedRules→NumericRules via Claude Sonnet tool_use
- `core/plu/cache.py` : triple-layer cache manager (LRU + filesystem + DB lookup)
- `core/plu/parsers/paris_bioclim.py` : deterministic parser for PLU Bioclimatique Paris (confidence 1.0)
- `workers/extraction.py` : ARQ worker wrapping extractor for async job queue

---

## Task 1: Pydantic schemas — ParsedRules, NumericRules, RuleFormula, Bande

**Files:**
- Create: `apps/backend/core/plu/__init__.py`
- Create: `apps/backend/core/plu/schemas.py`
- Test: `apps/backend/tests/unit/test_plu_schemas.py`

- [ ] **Step 1: Write failing tests for schemas**

```python
# apps/backend/tests/unit/test_plu_schemas.py
"""Tests for PLU rule schemas."""
import pytest
from core.plu.schemas import ParsedRules, NumericRules, RuleFormula, Bande


class TestParsedRules:
    def test_minimal_valid(self):
        r = ParsedRules(
            hauteur="15 m max (Article UA.10, p.42)",
            emprise=None, implantation_voie=None, limites_separatives=None,
            stationnement=None, lls=None, espaces_verts=None, destinations=None,
            pages={}, source="ai_parsed",
        )
        assert r.hauteur == "15 m max (Article UA.10, p.42)"
        assert r.source == "ai_parsed"
        assert r.cached is False

    def test_all_fields(self):
        r = ParsedRules(
            hauteur="15 m", emprise="60%", implantation_voie="5 m min",
            limites_separatives="3 m ou H/2", stationnement="1 place/logement",
            lls="25% min si >12 logements", espaces_verts="30% pleine terre",
            destinations="Habitation, commerces en RDC",
            pages={"hauteur": 42, "emprise": 43},
            source="ai_parsed",
        )
        assert r.pages["hauteur"] == 42

    def test_cached_flag(self):
        r = ParsedRules(
            hauteur=None, emprise=None, implantation_voie=None,
            limites_separatives=None, stationnement=None, lls=None,
            espaces_verts=None, destinations=None,
            pages={}, source="cache", cached=True,
        )
        assert r.cached is True


class TestRuleFormula:
    def test_simple(self):
        f = RuleFormula(expression="H/2", min_value=4.0, max_value=None, units="m", raw_text="L=H/2 min 4m")
        assert f.expression == "H/2"
        assert f.min_value == 4.0


class TestBande:
    def test_principale(self):
        b = Bande(name="principale", hauteur_max_m=15.0, emprise_max_pct=80.0, depth_from_voie_m=25.0)
        assert b.name == "principale"


class TestNumericRules:
    def test_minimal(self):
        nr = NumericRules(
            hauteur_max_m=15.0, hauteur_max_niveaux=5,
            pleine_terre_min_pct=30.0,
            article_refs={"hauteur": "Art. UA.10"},
            extraction_confidence=0.92, extraction_warnings=[],
        )
        assert nr.hauteur_max_m == 15.0
        assert nr.extraction_confidence == 0.92

    def test_with_formulas_and_bandes(self):
        nr = NumericRules(
            hauteur_max_m=18.0,
            recul_voirie_formula=RuleFormula(expression="5", min_value=5.0, max_value=None, units="m", raw_text="5m minimum"),
            bandes_constructibles=[
                Bande(name="principale", hauteur_max_m=18.0, emprise_max_pct=80.0, depth_from_voie_m=20.0),
                Bande(name="secondaire", hauteur_max_m=9.0, emprise_max_pct=40.0, depth_from_voie_m=None),
            ],
            pleine_terre_min_pct=25.0,
            article_refs={}, extraction_confidence=0.85, extraction_warnings=[],
        )
        assert len(nr.bandes_constructibles) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_plu_schemas.py -v`

- [ ] **Step 3: Implement schemas**

```python
# apps/backend/core/plu/__init__.py
"""PLU extraction engine for ArchiClaude."""

# apps/backend/core/plu/schemas.py
"""PLU rule schemas — ParsedRules (textual) and NumericRules (numeric).

ParsedRules: strings extracted from PLU PDF by LLM, identical structure to the TS bot.
NumericRules: numeric values converted from ParsedRules, exploitable by feasibility engine.
"""
from __future__ import annotations
from typing import Literal
from pydantic import BaseModel, Field


class ParsedRules(BaseModel):
    """Textual rules extracted from PLU regulation PDF."""
    hauteur: str | None = None
    emprise: str | None = None
    implantation_voie: str | None = None
    limites_separatives: str | None = None
    stationnement: str | None = None
    lls: str | None = None
    espaces_verts: str | None = None
    destinations: str | None = None
    pages: dict[str, int | None] = Field(default_factory=dict)
    source: Literal["ai_parsed", "cache", "manual", "paris_bioclim_parser"] = "ai_parsed"
    cached: bool = False


class RuleFormula(BaseModel):
    """Parametric formula: e.g. 'L=H/2 min 4m' → evaluable with H known."""
    expression: str
    min_value: float | None = None
    max_value: float | None = None
    units: str = "m"
    raw_text: str = ""


class Bande(BaseModel):
    """Constructible band (principale vs secondaire in PLUi)."""
    name: Literal["principale", "secondaire", "fond"]
    hauteur_max_m: float | None = None
    emprise_max_pct: float | None = None
    depth_from_voie_m: float | None = None


class NumericRules(BaseModel):
    """Numeric rules exploitable by feasibility engine."""
    # Height
    hauteur_max_m: float | None = None
    hauteur_max_niveaux: int | None = None
    hauteur_max_ngf: float | None = None
    hauteur_facade_m: float | None = None
    # Footprint and setbacks
    emprise_max_pct: float | None = None
    recul_voirie_m: float | None = None
    recul_voirie_formula: RuleFormula | None = None
    recul_limite_lat_m: float | None = None
    recul_limite_lat_formula: RuleFormula | None = None
    recul_fond_m: float | None = None
    recul_fond_formula: RuleFormula | None = None
    # Programme
    cos: float | None = None
    sdp_max_m2: float | None = None
    # Environment
    pleine_terre_min_pct: float = 0.0
    surface_vegetalisee_min_pct: float | None = None
    coef_biotope_min: float | None = None
    # Parking
    stationnement_par_logement: float | None = None
    stationnement_par_m2_bureau: float | None = None
    stationnement_par_m2_commerce: float | None = None
    # Complex cases
    bandes_constructibles: list[Bande] | None = None
    # Meta
    article_refs: dict[str, str] = Field(default_factory=dict)
    extraction_confidence: float = 0.0
    extraction_warnings: list[str] = Field(default_factory=list)
```

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/plu/ apps/backend/tests/unit/test_plu_schemas.py
git commit -m "feat(plu): add ParsedRules/NumericRules/RuleFormula/Bande Pydantic schemas"
```

---

## Task 2: JSON repair module

**Files:**
- Create: `apps/backend/core/plu/json_repair.py`
- Test: `apps/backend/tests/unit/test_json_repair.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_json_repair.py
"""Tests for truncated JSON repair — ported from TS extractAndParseJson."""
import pytest
from core.plu.json_repair import extract_and_parse_json


class TestExtractAndParseJson:
    def test_clean_json(self):
        raw = '{"hauteur": "15 m", "emprise": "60%"}'
        result = extract_and_parse_json(raw)
        assert result == {"hauteur": "15 m", "emprise": "60%"}

    def test_markdown_block(self):
        raw = 'Here is the result:\n```json\n{"hauteur": "15 m"}\n```\nDone.'
        result = extract_and_parse_json(raw)
        assert result == {"hauteur": "15 m"}

    def test_surrounding_text(self):
        raw = 'Based on the document, I found:\n{"hauteur": "15 m", "emprise": null}\nLet me know.'
        result = extract_and_parse_json(raw)
        assert result["hauteur"] == "15 m"

    def test_truncated_odd_quotes(self):
        raw = '{"hauteur": "15 m max (Article UA.10, p.42)", "emprise": "60% max", "stationnement": "1 place par'
        result = extract_and_parse_json(raw)
        assert result is not None
        assert result["hauteur"] == "15 m max (Article UA.10, p.42)"

    def test_truncated_missing_braces(self):
        raw = '{"hauteur": "15 m", "emprise": "60%"'
        result = extract_and_parse_json(raw)
        assert result is not None
        assert result["emprise"] == "60%"

    def test_trailing_comma(self):
        raw = '{"hauteur": "15 m", "emprise": "60%",}'
        result = extract_and_parse_json(raw)
        assert result is not None

    def test_no_json(self):
        raw = "I could not find any rules in this document."
        result = extract_and_parse_json(raw)
        assert result is None

    def test_nested_object(self):
        raw = '{"hauteur": "15 m", "pages": {"hauteur": 42, "emprise": 43}}'
        result = extract_and_parse_json(raw)
        assert result["pages"]["hauteur"] == 42
```

- [ ] **Step 2: Implement JSON repair**

```python
# apps/backend/core/plu/json_repair.py
"""Repair truncated or malformed JSON from LLM responses.

Port of extractAndParseJson() from the TS bot. Handles:
- Markdown code blocks
- Surrounding text (extract brace-delimited content)
- Odd quote count (unclosed strings from max_tokens truncation)
- Missing closing braces
- Trailing commas
"""
from __future__ import annotations
import json
import re
from typing import Any


def extract_and_parse_json(raw: str) -> dict[str, Any] | None:
    """Extract and parse JSON from LLM response text, repairing truncation.

    Returns parsed dict or None if no valid JSON can be recovered.
    """
    if not raw or not raw.strip():
        return None

    # 1. Try markdown code block
    block_match = re.search(r"```json\s*([\s\S]*?)\s*```", raw)
    if block_match:
        try:
            return json.loads(block_match.group(1))
        except json.JSONDecodeError:
            pass

    # 2. Try brace-delimited content
    first_brace = raw.find("{")
    last_brace = raw.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        candidate = raw[first_brace : last_brace + 1]
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    # 3. Truncation repair
    if first_brace < 0:
        return None

    s = raw[first_brace:]

    # Check for odd quote count (unclosed string)
    quote_count = s.count('"')
    if quote_count % 2 == 1:
        # Find last clean boundary
        last_clean = max(s.rfind('",'), s.rfind("}"))
        if last_clean > 0:
            s = s[: last_clean + 1]

    # Remove trailing comma
    s = re.sub(r",\s*$", "", s)

    # Count brace nesting and auto-close
    open_count = 0
    in_string = False
    prev_char = ""
    for c in s:
        if c == '"' and prev_char != "\\":
            in_string = not in_string
        if not in_string:
            if c == "{":
                open_count += 1
            elif c == "}":
                open_count -= 1
        prev_char = c

    while open_count > 0:
        s += "}"
        open_count -= 1

    # Fix trailing comma before closing brace
    s = re.sub(r",\s*}", "}", s)

    try:
        return json.loads(s)
    except json.JSONDecodeError:
        return None
```

- [ ] **Step 3: Run tests to verify they pass**

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/plu/json_repair.py apps/backend/tests/unit/test_json_repair.py
git commit -m "feat(plu): add JSON repair module for truncated LLM responses"
```

---

## Task 3: Value cleaner + hoist numbers

**Files:**
- Create: `apps/backend/core/plu/value_cleaner.py`
- Test: `apps/backend/tests/unit/test_value_cleaner.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_value_cleaner.py
"""Tests for PLU value cleaning and number hoisting."""
import pytest
from core.plu.value_cleaner import clean_value, hoist_chiffre_front, is_error_pattern


class TestIsErrorPattern:
    def test_null_variants(self):
        assert is_error_pattern("null") is True
        assert is_error_pattern("NULL") is True
        assert is_error_pattern("n/a") is True
        assert is_error_pattern("N/A") is True

    def test_not_found(self):
        assert is_error_pattern("not found") is True
        assert is_error_pattern("section incomplete") is True

    def test_valid_value(self):
        assert is_error_pattern("15 m max") is False
        assert is_error_pattern("Non précisé dans ce règlement") is False


class TestCleanValue:
    def test_none_passthrough(self):
        assert clean_value(None) is None

    def test_error_to_none(self):
        assert clean_value("null") is None
        assert clean_value("n/a") is None

    def test_normalize_non_precise(self):
        assert clean_value("Non précisé dans ce règlement — pas d'info") == "Non précisé dans ce règlement"

    def test_normalize_non_reglemente(self):
        assert clean_value("Non réglementé — aucune restriction") == "Non réglementé"

    def test_strip_whitespace(self):
        assert clean_value("  15 m max  ") == "15 m max"

    def test_truncate_180_chars(self):
        long_val = "x" * 200
        assert len(clean_value(long_val)) <= 180


class TestHoistChiffreFront:
    def test_already_starts_with_number(self):
        assert hoist_chiffre_front("15 m max") == "15 m max"

    def test_label_colon_number(self):
        result = hoist_chiffre_front("Habitation : 1 place/85m²")
        assert result.startswith("1 place")

    def test_number_buried_mid_string(self):
        result = hoist_chiffre_front("Maximum autorisé de 15 m en zone UA")
        assert result.startswith("15")

    def test_r_plus_notation(self):
        result = hoist_chiffre_front("Hauteur maximale R+4")
        assert "R+4" in result

    def test_no_number(self):
        assert hoist_chiffre_front("Non précisé dans ce règlement") == "Non précisé dans ce règlement"
```

- [ ] **Step 2: Implement value cleaner**

```python
# apps/backend/core/plu/value_cleaner.py
"""Clean and normalize extracted PLU values.

Port of cleanValue() and hoistChiffreFront() from the TS bot.
- Detects error patterns (null, n/a, not found)
- Normalizes "Non précisé" / "Non réglementé" suffixes
- Hoists buried numbers to front of string
- Truncates to 180 chars max
"""
from __future__ import annotations
import re

_ERROR_PATTERNS = re.compile(
    r"^(null|n/?a|not\s+found|not\s+included|section\s+incomplete|"
    r"non\s+trouv[eé]|pas\s+trouv[eé]|aucune?\s+information|"
    r"information\s+non\s+disponible)$",
    re.IGNORECASE,
)

_NON_PRECISE_PREFIX = re.compile(
    r"^(Non\s+pr[eé]cis[eé]\s+dans\s+ce\s+r[eè]glement)\b.*",
    re.IGNORECASE,
)

_NON_REGLEMENTE_PREFIX = re.compile(
    r"^(Non\s+r[eé]glement[eé])\b.*",
    re.IGNORECASE,
)

_CHIFFRE_RE = re.compile(
    r"(\d+(?:[.,]\d+)?\s*(?:m[²2]?|%|places?|logements?)|R\+\d+)",
    re.IGNORECASE,
)

MAX_VALUE_LENGTH = 180


def is_error_pattern(value: str) -> bool:
    """Check if value is a disguised error/null from LLM."""
    return bool(_ERROR_PATTERNS.match(value.strip()))


def clean_value(value: str | None) -> str | None:
    """Clean an extracted PLU value. Returns None for error patterns."""
    if value is None:
        return None

    v = value.strip()
    if not v:
        return None

    if is_error_pattern(v):
        return None

    # Normalize "Non précisé..." variants
    m = _NON_PRECISE_PREFIX.match(v)
    if m:
        return m.group(1)

    m = _NON_REGLEMENTE_PREFIX.match(v)
    if m:
        return m.group(1)

    # Truncate
    if len(v) > MAX_VALUE_LENGTH:
        v = v[:MAX_VALUE_LENGTH]

    return v


def hoist_chiffre_front(value: str) -> str:
    """Move first number/R+n to the front of the string if buried.

    "Habitation : 1 place/85m²" → "1 place/85m² habitation"
    "Maximum autorisé de 15 m" → "15 m maximum autorisé de"
    """
    v = value.strip()
    if not v:
        return v

    # Already starts with number or R+
    if re.match(r"^(\d|R\+|%)", v):
        return v

    # Pattern a: "Label : number_stuff"
    prefix_colon = re.match(r"^([A-ZÀ-Ÿa-zà-ÿ\s-]{2,40})\s*:\s+(.+)", v)
    if prefix_colon and _CHIFFRE_RE.search(prefix_colon.group(2)):
        label = prefix_colon.group(1).strip().lower()
        rest = prefix_colon.group(2).strip()
        return f"{rest} {label}".strip()

    # Pattern b: find first number and move to head
    m = _CHIFFRE_RE.search(v)
    if m and m.start() > 0:
        num = m.group(0)
        before = v[: m.start()].strip().rstrip(":,")
        after = v[m.end() :].strip().lstrip(":, ")
        parts = [p for p in [before, after] if p]
        return f"{num} {' '.join(parts)}".strip()

    return v
```

- [ ] **Step 3: Run tests to verify they pass**

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/plu/value_cleaner.py apps/backend/tests/unit/test_value_cleaner.py
git commit -m "feat(plu): add value cleaner with error detection and number hoisting"
```

---

## Task 4: Zone section finder (regex scoring)

**Files:**
- Create: `apps/backend/core/plu/section_finder.py`
- Test: `apps/backend/tests/unit/test_section_finder.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_section_finder.py
"""Tests for PLU zone section identification and scoring."""
import pytest
from core.plu.section_finder import (
    find_zone_section,
    score_candidate,
    generate_zone_variants,
    SectionCandidate,
)


class TestGenerateZoneVariants:
    def test_basic(self):
        variants = generate_zone_variants("UA1")
        assert "UA1" in variants
        assert "UA-1" in variants
        assert "UA.1" in variants
        assert "UA 1" in variants

    def test_no_number(self):
        variants = generate_zone_variants("UB")
        assert "UB" in variants
        assert len(variants) == 1  # no numeric variants


class TestScoreCandidate:
    def test_regulatory_words_boost(self):
        text = "Article UA.10 — Hauteur maximale\nLa hauteur maximale est de 15 m.\nL'emprise au sol ne doit pas excéder 60%."
        score = score_candidate(text)
        assert score > 0  # has regulatory words

    def test_toc_penalty(self):
        text = "UA.10 Hauteur .......................... 42\nUA.11 Emprise .......................... 43\nUA.12 Implantation .......................... 44"
        score = score_candidate(text)
        assert score < 0  # TOC penalty

    def test_dispositions_bonus(self):
        text = "Dispositions applicables à la zone UB\nArticle UB.1 — Destinations autorisées"
        score = score_candidate(text)
        assert score >= 80


class TestFindZoneSection:
    def test_finds_section(self):
        text = """
SOMMAIRE
UA Hauteur ........ 42

ZONE UA — Dispositions applicables à la zone UA
Article UA.10 — Hauteur maximale
La hauteur maximale des constructions est fixée à 15 mètres.
Article UA.11 — Emprise au sol
L'emprise au sol maximale est de 60%.

ZONE UB — Dispositions applicables à la zone UB
Article UB.10 — Hauteur maximale
"""
        result = find_zone_section(text, zone_code="UA")
        assert result is not None
        assert "15 mètres" in result
        assert "ZONE UB" not in result  # should stop at next zone

    def test_not_found(self):
        text = "Ce document ne contient aucune zone UC."
        result = find_zone_section(text, zone_code="UC")
        assert result is None or len(result) < 100
```

- [ ] **Step 2: Implement section finder**

Create `apps/backend/core/plu/section_finder.py` with the full ported logic:
- `generate_zone_variants(zone_code)` → list of notation variants
- `score_candidate(context_text)` → int score
- `find_zone_section(full_text, zone_code, *, commune_name=None, window_chars=500_000)` → str | None
- `_find_canonical_header(text, zone_code)` → attempt "Dispositions applicables à la zone X" first
- `_find_by_regex_scoring(text, zone_code, window_chars)` → fallback multi-pass regex with scoring
- `_detect_section_boundary(text, start_idx, zone_code)` → find end of zone section

The implementation should faithfully port all 11 refinements from the TS bot (spec §4.4).

- [ ] **Step 3: Run tests to verify they pass**

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/plu/section_finder.py apps/backend/tests/unit/test_section_finder.py
git commit -m "feat(plu): add zone section finder with multi-pass regex scoring"
```

---

## Task 5: PLUi commune filter

**Files:**
- Create: `apps/backend/core/plu/commune_filter.py`
- Test: `apps/backend/tests/unit/test_commune_filter.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_commune_filter.py
"""Tests for PLUi commune paragraph filtering."""
import pytest
from core.plu.commune_filter import strip_other_communes, normalize_commune_name


class TestNormalizeCommuneName:
    def test_diacritics(self):
        assert normalize_commune_name("Nogent-sur-Marne") == "nogent-sur-marne"
        assert normalize_commune_name("Évreux") == "evreux"
        assert normalize_commune_name("Châtillon") == "chatillon"

    def test_whitespace(self):
        assert normalize_commune_name("  Saint Denis  ") == "saint denis"


class TestStripOtherCommunes:
    def test_keeps_target_commune(self):
        text = """Article UB.10
Pour la commune de Nogent-sur-Marne :
La hauteur maximale est de 15 m.
Pour la commune de Saint-Mandé :
La hauteur maximale est de 12 m.
"""
        result = strip_other_communes(text, target_commune="Nogent-sur-Marne")
        assert "15 m" in result
        assert "Saint-Mandé" not in result

    def test_keeps_neutral_paragraphs(self):
        text = """Article UB.10 — Hauteur
La hauteur maximale est de 15 m.
Dispositions générales applicables à toutes les communes.
Pour la commune de Vincennes :
Exception : 12 m.
"""
        result = strip_other_communes(text, target_commune="Nogent-sur-Marne")
        assert "15 m" in result  # neutral kept
        assert "Vincennes" not in result  # other commune removed

    def test_no_commune_markers(self):
        text = "Article UB.10\nHauteur maximale 15 m."
        result = strip_other_communes(text, target_commune="Nogent-sur-Marne")
        assert result == text  # unchanged

    def test_prefix_matching(self):
        """Handles 'Saint-' hyphenated name matching."""
        text = """Pour la commune de Saint-Mandé : hauteur 12 m.
Pour la commune de Saint-Maur-des-Fossés : hauteur 15 m."""
        result = strip_other_communes(text, target_commune="Saint-Maur-des-Fossés")
        assert "15 m" in result
        assert "Saint-Mandé" not in result
```

- [ ] **Step 2: Implement commune filter**

Create `apps/backend/core/plu/commune_filter.py` porting `stripOtherCommunesFromSection()`:
- `normalize_commune_name(name)` → lowercase, strip diacritics
- `strip_other_communes(text, target_commune)` → filtered text
- Split on commune-specific paragraph markers
- Keep paragraphs matching target commune or neutral (no commune header)
- Remove paragraphs mentioning other communes
- Flexible matching: exact, prefix, 4-char prefix fallback

- [ ] **Step 3: Run tests to verify they pass**

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/plu/commune_filter.py apps/backend/tests/unit/test_commune_filter.py
git commit -m "feat(plu): add PLUi commune paragraph filter"
```

---

## Task 6: PDF fetcher + text extraction

**Files:**
- Create: `apps/backend/core/plu/pdf_fetcher.py`
- (No dedicated test file — tested via integration with extractor)

- [ ] **Step 1: Implement PDF fetcher**

```python
# apps/backend/core/plu/pdf_fetcher.py
"""Fetch PLU regulation PDF and extract text.

Handles multiple URL candidates (GPU geopf.fr + fallback).
Uses pdfplumber for text extraction. Computes sha256 for cache invalidation.
"""
from __future__ import annotations
import hashlib
import logging

import httpx
import pdfplumber

from core.http_client import get_http_client

logger = logging.getLogger(__name__)

PDF_TIMEOUT = httpx.Timeout(connect=5.0, read=40.0, write=5.0, pool=5.0)


async def fetch_pdf_text(url: str) -> tuple[str, str] | None:
    """Download PDF and extract text.

    Returns (text, sha256_hex) or None if download/extraction fails.
    """
    try:
        client = get_http_client()
        resp = await client.get(url, timeout=PDF_TIMEOUT)
        resp.raise_for_status()
        pdf_bytes = resp.content
    except Exception:
        logger.warning("Failed to download PDF from %s", url)
        return None

    sha256 = hashlib.sha256(pdf_bytes).hexdigest()

    try:
        text = _extract_text(pdf_bytes)
    except Exception:
        logger.warning("Failed to extract text from PDF %s", url)
        return None

    if not text or len(text) < 100:
        logger.warning("PDF text too short (%d chars) — possibly scanned", len(text) if text else 0)
        return None

    return text, sha256


def _extract_text(pdf_bytes: bytes) -> str:
    """Extract text from PDF bytes using pdfplumber."""
    import io
    pages_text = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)
    return "\n\n".join(pages_text)
```

- [ ] **Step 2: Commit**

```bash
git add apps/backend/core/plu/pdf_fetcher.py
git commit -m "feat(plu): add PDF fetcher with text extraction and sha256"
```

---

## Task 7: LLM prompt templates

**Files:**
- Create: `apps/backend/core/plu/prompt.py`

- [ ] **Step 1: Implement prompt templates**

```python
# apps/backend/core/plu/prompt.py
"""LLM prompt templates for PLU rule extraction and numericization.

Port of the extraction prompt from the TS bot with all strict formatting rules.
"""
from __future__ import annotations


def build_extraction_prompt(
    *,
    zone_code: str,
    zone_description: str,
    commune_name: str | None = None,
    is_plui: bool = False,
) -> str:
    """Build the question prompt for PLU rule extraction.

    The PLU text itself is sent as cachedPrefix (prompt caching).
    This returns only the question/instruction part.
    """
    commune_desc = ""
    commune_filter = ""
    if commune_name and is_plui:
        commune_desc = f" dans la commune de {commune_name}"
        commune_filter = f"""

INSTRUCTION PRIORITAIRE — FILTRAGE PAR COMMUNE :
Ce document est un PLUi (PLU intercommunal) couvrant plusieurs communes.
Tu dois UNIQUEMENT retourner les règles applicables à la commune de {commune_name}.
- Ignore tout paragraphe commençant par "Pour la commune de [autre commune]"
- Si un tableau donne des valeurs par commune, lis UNIQUEMENT la ligne/colonne de {commune_name}
- Si des dispositions sont "communes à toutes les communes", inclus-les
- En cas de doute entre une disposition générale et une disposition spécifique à {commune_name}, retiens la spécifique
"""

    return f"""Tu es un expert en urbanisme français. Extrais les règles de la zone {zone_code} ({zone_description}){commune_desc} depuis le texte du règlement ci-dessus.
{commune_filter}
CONSIGNES STRICTES :
1. Chaque valeur doit commencer par un chiffre, un pourcentage, "R+n", "Non précisé dans ce règlement", ou "Non réglementé"
2. Maximum 180 caractères par champ
3. Format : <VALEUR> | <secondaire si applicable> — <contexte bref> (Article X, p.Y)
4. Si une règle n'est pas précisée dans le texte, écris exactement "Non précisé dans ce règlement"
5. Si une règle est explicitement absente/libre, écris "Non réglementé"
6. JAMAIS d'explication narrative dans les valeurs — uniquement valeurs chiffrées
7. Table de conversion R+n → mètres : R+0≈3m, R+1≈6m, R+2≈10m, R+3≈12m, R+4≈15m, R+5≈18m, R+6≈21m, R+7≈24m, R+8≈27m, R+9≈30m
8. Pour l'emprise : si "Non réglementé" → écrire "100% max (non réglementé)"

Retourne un JSON avec exactement ces 9 clés (pas de clé supplémentaire) :
{{
  "hauteur": "...",
  "emprise": "...",
  "implantation_voie": "...",
  "limites_separatives": "...",
  "stationnement": "...",
  "lls": "...",
  "espaces_verts": "...",
  "destinations": "...",
  "pages": {{"hauteur": <int|null>, "emprise": <int|null>, "implantation_voie": <int|null>, "limites_separatives": <int|null>, "stationnement": <int|null>, "lls": <int|null>, "espaces_verts": <int|null>, "destinations": <int|null>}}
}}"""


def build_numericizer_prompt() -> str:
    """Build the system prompt for ParsedRules → NumericRules conversion."""
    return """Tu es un expert en urbanisme français. Tu reçois des règles PLU extraites au format textuel (ParsedRules) et tu dois les convertir en valeurs numériques exploitables (NumericRules).

CONSIGNES :
1. Extrais les valeurs numériques précises de chaque champ textuel
2. Pour les formules paramétriques (ex "L=H/2 min 4m"), crée un objet RuleFormula
3. Si une valeur textuelle dit "Non précisé" ou "Non réglementé", laisse le champ numérique à null
4. Pour les bandes constructibles (principale/secondaire), crée des objets Bande
5. Évalue ta confiance (0-1) sur l'ensemble de l'extraction
6. Liste les avertissements pour les valeurs ambiguës ou incertaines
7. Référence l'article PLU source pour chaque valeur extraite dans article_refs"""
```

- [ ] **Step 2: Commit**

```bash
git add apps/backend/core/plu/prompt.py
git commit -m "feat(plu): add LLM prompt templates for extraction and numericization"
```

---

## Task 8: Main extractor orchestrator

**Files:**
- Create: `apps/backend/core/plu/extractor.py`
- Test: `apps/backend/tests/unit/test_extractor.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_extractor.py
"""Tests for PLU rule extractor orchestrator."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from core.plu.schemas import ParsedRules
from core.plu.extractor import extract_rules, select_model


class TestSelectModel:
    def test_plui_uses_sonnet(self):
        model = select_model(is_plui=True, text_length=50_000)
        assert "sonnet" in model

    def test_large_text_uses_sonnet(self):
        model = select_model(is_plui=False, text_length=150_000)
        assert "sonnet" in model

    def test_small_mono_commune_uses_haiku(self):
        model = select_model(is_plui=False, text_length=80_000)
        assert "haiku" in model


class TestExtractRules:
    @pytest.mark.asyncio
    async def test_returns_parsed_rules(self):
        mock_llm_response = '{"hauteur": "15 m max (Art. UA.10, p.42)", "emprise": "60% max", "implantation_voie": "5 m min", "limites_separatives": "3 m", "stationnement": "1 place/logement", "lls": "Non précisé dans ce règlement", "espaces_verts": "30% pleine terre", "destinations": "Habitation", "pages": {"hauteur": 42}}'

        with (
            patch("core.plu.extractor._call_llm", new_callable=AsyncMock, return_value=mock_llm_response),
            patch("core.plu.extractor.pdf_fetcher.fetch_pdf_text", new_callable=AsyncMock, return_value=("Full PLU text here with lots of content about zone UA...", "abc123sha")),
        ):
            result = await extract_rules(
                pdf_url="https://gpu.beta.gouv.fr/test.pdf",
                zone_code="UA",
                zone_description="Zone urbaine",
            )

        assert isinstance(result, ParsedRules)
        assert result.hauteur == "15 m max (Art. UA.10, p.42)"
        assert result.emprise == "60% max"
        assert result.source == "ai_parsed"

    @pytest.mark.asyncio
    async def test_pdf_unavailable_returns_none(self):
        with patch("core.plu.extractor.pdf_fetcher.fetch_pdf_text", new_callable=AsyncMock, return_value=None):
            result = await extract_rules(
                pdf_url="https://gpu.beta.gouv.fr/missing.pdf",
                zone_code="UA",
                zone_description="Zone urbaine",
            )
        assert result is None
```

- [ ] **Step 2: Implement extractor orchestrator**

Create `apps/backend/core/plu/extractor.py` — the main pipeline:

```python
# apps/backend/core/plu/extractor.py
"""PLU rule extraction orchestrator.

Pipeline: PDF URL → fetch text → find zone section → filter PLUi commune →
          LLM extraction → JSON repair → value cleaning → ParsedRules.

Port of parse-reglement/route.ts from the TS bot.
"""
from __future__ import annotations
import logging
import os
from typing import Any

import anthropic

from core.plu import pdf_fetcher
from core.plu.commune_filter import strip_other_communes
from core.plu.json_repair import extract_and_parse_json
from core.plu.prompt import build_extraction_prompt
from core.plu.schemas import ParsedRules
from core.plu.section_finder import find_zone_section
from core.plu.value_cleaner import clean_value, hoist_chiffre_front

logger = logging.getLogger(__name__)

_PARSED_FIELDS = ["hauteur", "emprise", "implantation_voie", "limites_separatives",
                   "stationnement", "lls", "espaces_verts", "destinations"]


def select_model(*, is_plui: bool, text_length: int) -> str:
    """Select LLM model based on PLU complexity."""
    if is_plui or text_length > 120_000:
        return "claude-sonnet-4-6-20250514"
    return "claude-haiku-4-5-20251001"


async def extract_rules(
    *,
    pdf_url: str,
    zone_code: str,
    zone_description: str,
    commune_name: str | None = None,
    commune_insee: str | None = None,
) -> ParsedRules | None:
    """Extract PLU rules from a regulation PDF.

    Returns ParsedRules or None if extraction fails entirely.
    """
    # 1. Fetch PDF text
    fetch_result = await pdf_fetcher.fetch_pdf_text(pdf_url)
    if fetch_result is None:
        return None
    full_text, pdf_sha = fetch_result

    # 2. Detect PLUi
    is_plui = bool(
        commune_name
        and any(
            kw in full_text[:5000].lower()
            for kw in ("plui", "intercommunal", "communauté", "territoire")
        )
    )

    # 3. Find zone section
    section_text = find_zone_section(
        full_text, zone_code=zone_code, commune_name=commune_name
    )
    if not section_text:
        section_text = full_text[:500_000]  # fallback: send first 500K chars

    # 4. Filter PLUi communes
    if is_plui and commune_name:
        section_text = strip_other_communes(section_text, target_commune=commune_name)

    # 5. LLM extraction
    model = select_model(is_plui=is_plui, text_length=len(section_text))
    prompt = build_extraction_prompt(
        zone_code=zone_code,
        zone_description=zone_description,
        commune_name=commune_name,
        is_plui=is_plui,
    )

    raw_response = await _call_llm(
        model=model,
        plu_text=section_text,
        question=prompt,
    )

    # 6. Parse JSON
    parsed = extract_and_parse_json(raw_response)
    if parsed is None:
        logger.warning("Failed to parse LLM response for zone %s", zone_code)
        return None

    # 7. Clean values
    for field in _PARSED_FIELDS:
        raw_val = parsed.get(field)
        cleaned = clean_value(raw_val)
        if cleaned:
            cleaned = hoist_chiffre_front(cleaned)
        parsed[field] = cleaned

    # 8. Build ParsedRules
    return ParsedRules(
        hauteur=parsed.get("hauteur"),
        emprise=parsed.get("emprise"),
        implantation_voie=parsed.get("implantation_voie"),
        limites_separatives=parsed.get("limites_separatives"),
        stationnement=parsed.get("stationnement"),
        lls=parsed.get("lls"),
        espaces_verts=parsed.get("espaces_verts"),
        destinations=parsed.get("destinations"),
        pages=parsed.get("pages", {}),
        source="ai_parsed",
    )


async def _call_llm(*, model: str, plu_text: str, question: str) -> str:
    """Call Anthropic API with prompt caching on PLU text."""
    client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

    response = await client.messages.create(
        model=model,
        max_tokens=3000,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": f"TEXTE DU RÈGLEMENT :\n{plu_text}",
                        "cache_control": {"type": "ephemeral"},
                    },
                    {
                        "type": "text",
                        "text": question,
                    },
                ],
            },
        ],
    )

    return response.content[0].text
```

- [ ] **Step 3: Run tests to verify they pass**

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/plu/extractor.py apps/backend/tests/unit/test_extractor.py
git commit -m "feat(plu): add main extraction orchestrator with LLM pipeline"
```

---

## Task 9: Numericizer — ParsedRules → NumericRules via LLM tool_use

**Files:**
- Create: `apps/backend/core/plu/numericizer.py`
- Test: `apps/backend/tests/unit/test_numericizer.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_numericizer.py
"""Tests for ParsedRules → NumericRules conversion via LLM."""
import pytest
from unittest.mock import AsyncMock, patch

from core.plu.schemas import ParsedRules, NumericRules
from core.plu.numericizer import numericize_rules


class TestNumericizeRules:
    @pytest.mark.asyncio
    async def test_converts_basic_rules(self):
        parsed = ParsedRules(
            hauteur="15 m max (Article UA.10, p.42)",
            emprise="60% max (Article UA.11, p.43)",
            implantation_voie="5 m minimum",
            limites_separatives="3 m ou H/2 min 4m",
            stationnement="1 place par logement",
            lls="Non précisé dans ce règlement",
            espaces_verts="30% pleine terre min",
            destinations="Habitation, commerce en RDC",
            pages={"hauteur": 42, "emprise": 43},
            source="ai_parsed",
        )

        mock_result = {
            "hauteur_max_m": 15.0,
            "hauteur_max_niveaux": 5,
            "emprise_max_pct": 60.0,
            "recul_voirie_m": 5.0,
            "recul_limite_lat_m": 3.0,
            "recul_limite_lat_formula": {"expression": "H/2", "min_value": 4.0, "units": "m", "raw_text": "H/2 min 4m"},
            "pleine_terre_min_pct": 30.0,
            "stationnement_par_logement": 1.0,
            "extraction_confidence": 0.92,
            "extraction_warnings": [],
            "article_refs": {"hauteur": "Art. UA.10", "emprise": "Art. UA.11"},
        }

        with patch("core.plu.numericizer._call_numericizer_llm", new_callable=AsyncMock, return_value=mock_result):
            result = await numericize_rules(parsed)

        assert isinstance(result, NumericRules)
        assert result.hauteur_max_m == 15.0
        assert result.emprise_max_pct == 60.0
        assert result.pleine_terre_min_pct == 30.0
        assert result.extraction_confidence == 0.92
```

- [ ] **Step 2: Implement numericizer**

Create `apps/backend/core/plu/numericizer.py`:
- `numericize_rules(parsed: ParsedRules) -> NumericRules`
- Uses Claude Sonnet tool_use with NumericRules schema as tool definition
- `_call_numericizer_llm(parsed_dict)` → dict (mocked in tests)
- Maps LLM tool_use output to NumericRules Pydantic model
- Handles RuleFormula nested objects

- [ ] **Step 3: Run tests to verify they pass**

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/plu/numericizer.py apps/backend/tests/unit/test_numericizer.py
git commit -m "feat(plu): add numericizer — ParsedRules to NumericRules via LLM tool_use"
```

---

## Task 10: DB models zone_rules + migration + API endpoints + worker

**Files:**
- Create: `apps/backend/db/models/zone_rules.py`
- Create: `apps/backend/db/models/extraction_feedback.py`
- Create: `apps/backend/alembic/versions/20260417_0003_zone_rules.py`
- Create: `apps/backend/workers/extraction.py`
- Modify: `apps/backend/api/routes/plu.py`
- Modify: `apps/backend/schemas/plu.py`
- Test: `apps/backend/tests/integration/test_plu_rules_endpoints.py`

- [ ] **Step 1: Create DB models**

```python
# apps/backend/db/models/zone_rules.py
"""SQLAlchemy models for extracted PLU rules (mutualized across users)."""
import uuid
from sqlalchemy import Column, DateTime, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from db.base import Base


class ZoneRulesTextRow(Base):
    __tablename__ = "zone_rules_text"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    plu_zone_id = Column(UUID(as_uuid=True), ForeignKey("plu_zones.id", ondelete="CASCADE"), nullable=False)
    commune_insee = Column(String(5), nullable=True)
    parsed_rules = Column(JSONB, nullable=False)
    pdf_text_hash = Column(String(64), nullable=True)
    source = Column(Text, nullable=True)  # llm_sonnet, llm_haiku, paris_bioclim_parser, manual
    model_used = Column(Text, nullable=True)
    extraction_cost_cents = Column(Numeric(10, 4), nullable=True)
    extracted_at = Column(DateTime(timezone=True), server_default=func.now())


class ZoneRulesNumericRow(Base):
    __tablename__ = "zone_rules_numeric"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    zone_rules_text_id = Column(UUID(as_uuid=True), ForeignKey("zone_rules_text.id", ondelete="CASCADE"), unique=True, nullable=False)
    numeric_rules = Column(JSONB, nullable=False)
    extraction_confidence = Column(Numeric(3, 2), nullable=True)
    warnings = Column(JSONB, nullable=True)
    validated_by_user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=True)
    validated_at = Column(DateTime(timezone=True), nullable=True)
    validation_edits = Column(JSONB, nullable=True)
```

```python
# apps/backend/db/models/extraction_feedback.py
"""User corrections on extracted rules (telemetry for LLM improvement)."""
import uuid
from sqlalchemy import Column, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from db.base import Base


class ExtractionFeedbackRow(Base):
    __tablename__ = "extraction_feedback"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    zone_rules_numeric_id = Column(UUID(as_uuid=True), ForeignKey("zone_rules_numeric.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    diff = Column(JSONB, nullable=False)
    edit_reason = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 2: Create Alembic migration**

Migration creating zone_rules_text, zone_rules_numeric, extraction_feedback tables with unique constraints and indexes per spec §6.2.

- [ ] **Step 3: Add extraction-related API endpoints to plu.py**

Add to existing `api/routes/plu.py`:
- `GET /plu/zone/{zone_id}/rules?commune_insee=` → cached rules if available
- `POST /plu/zone/{zone_id}/extract` → enqueue ARQ extraction job, return job_id
- `GET /plu/extract/status/{job_id}` → check job status
- `POST /plu/zone/{zone_id}/validate` → user validates/corrects rules
- `POST /rules/{zone_rules_numeric_id}/feedback` → store user correction telemetry

- [ ] **Step 4: Create ARQ extraction worker**

```python
# apps/backend/workers/extraction.py
"""ARQ worker for async PLU rule extraction."""
from core.plu.extractor import extract_rules
from core.plu.numericizer import numericize_rules


async def run_extraction(ctx, *, pdf_url: str, zone_code: str, zone_description: str,
                          commune_name: str | None = None, commune_insee: str | None = None,
                          plu_zone_id: str | None = None):
    """ARQ task: extract + numericize PLU rules, store in DB."""
    # 1. Extract ParsedRules
    parsed = await extract_rules(
        pdf_url=pdf_url, zone_code=zone_code, zone_description=zone_description,
        commune_name=commune_name, commune_insee=commune_insee,
    )
    if parsed is None:
        return {"status": "failed", "error": "extraction_failed"}

    # 2. Numericize
    numeric = await numericize_rules(parsed)

    # 3. Store in DB (zone_rules_text + zone_rules_numeric)
    # ... DB session logic

    return {"status": "done", "parsed_rules": parsed.model_dump(), "numeric_rules": numeric.model_dump()}
```

- [ ] **Step 5: Write integration tests**

```python
# apps/backend/tests/integration/test_plu_rules_endpoints.py
"""Integration tests for PLU rules extraction endpoints."""
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient


class TestPluZoneRules:
    @pytest.mark.asyncio
    async def test_rules_endpoint_returns_cached(self, client: AsyncClient):
        # Mock DB lookup returning cached rules
        # GET /api/v1/plu/zone/{id}/rules
        pass  # Implement with proper mocking

    @pytest.mark.asyncio
    async def test_extract_endpoint_returns_job_id(self, client: AsyncClient):
        # POST /api/v1/plu/zone/{id}/extract → 202 {job_id}
        pass

    @pytest.mark.asyncio
    async def test_validate_endpoint(self, client: AsyncClient):
        # POST /api/v1/plu/zone/{id}/validate
        pass
```

- [ ] **Step 6: Run all tests**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/ -v`

- [ ] **Step 7: Commit**

```bash
git add apps/backend/db/models/zone_rules.py apps/backend/db/models/extraction_feedback.py apps/backend/alembic/ apps/backend/workers/extraction.py apps/backend/api/routes/plu.py apps/backend/schemas/plu.py apps/backend/tests/integration/test_plu_rules_endpoints.py
git commit -m "feat(plu): add zone_rules DB, extraction worker, and PLU rules API endpoints"
```

---

## Task 11: Paris Bioclimatique parser

**Files:**
- Create: `apps/backend/core/plu/parsers/paris_bioclim.py`
- Create: `apps/backend/core/plu/parsers/__init__.py`
- Test: `apps/backend/tests/unit/test_paris_bioclim.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_paris_bioclim.py
"""Tests for Paris Bioclimatique dedicated parser."""
import pytest
from core.plu.parsers.paris_bioclim import parse_paris_bioclim, is_paris_bioclim
from core.plu.schemas import ParsedRules, NumericRules


class TestIsParissBioclim:
    def test_paris_ug(self):
        assert is_paris_bioclim(code_insee="75108", zone_code="UG") is True

    def test_paris_ugsu(self):
        assert is_paris_bioclim(code_insee="75101", zone_code="UGSU") is True

    def test_non_paris(self):
        assert is_paris_bioclim(code_insee="94052", zone_code="UB") is False

    def test_paris_non_bioclim_zone(self):
        # Paris zones not in bioclim table → not handled by parser
        assert is_paris_bioclim(code_insee="75108", zone_code="XYZ") is False


class TestParseParissBioclim:
    def test_ug_zone(self):
        parsed, numeric = parse_paris_bioclim(zone_code="UG", code_insee="75108")
        assert isinstance(parsed, ParsedRules)
        assert isinstance(numeric, NumericRules)
        assert parsed.source == "paris_bioclim_parser"
        assert numeric.extraction_confidence == 1.0
        assert numeric.hauteur_max_m is not None

    def test_uv_zone(self):
        parsed, numeric = parse_paris_bioclim(zone_code="UV", code_insee="75116")
        assert parsed.source == "paris_bioclim_parser"
        assert numeric.extraction_confidence == 1.0
```

- [ ] **Step 2: Implement Paris Bioclimatique parser**

Create `apps/backend/core/plu/parsers/paris_bioclim.py` with hardcoded tables from the PLU Bioclimatique (approved 20/11/2024):
- `is_paris_bioclim(code_insee, zone_code)` → bool
- `parse_paris_bioclim(zone_code, code_insee)` → tuple[ParsedRules, NumericRules]
- Gabarit tables by zone (UG, UGSU, UV, UVE, UN, USC)
- Coefficients biotope by sector
- source = "paris_bioclim_parser", confidence = 1.0

- [ ] **Step 3: Run tests to verify they pass**

- [ ] **Step 4: Commit**

```bash
git add apps/backend/core/plu/parsers/ apps/backend/tests/unit/test_paris_bioclim.py
git commit -m "feat(plu): add Paris Bioclimatique dedicated parser — zero LLM cost"
```

---

## Task 12: Vérification finale

- [ ] **Step 1: Run ruff**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && ruff check . --fix
```

- [ ] **Step 2: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short
```

- [ ] **Step 3: Fix any issues**

- [ ] **Step 4: Commit cleanup**

```bash
git add -A && git commit -m "chore: Phase 3 lint fixes and cleanup"
```
