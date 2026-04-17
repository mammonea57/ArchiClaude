"""Unit tests for core.plu.numericizer — numericize_rules pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core.plu.numericizer import numericize_rules
from core.plu.schemas import NumericRules, ParsedRules, RuleFormula

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_PARSED = ParsedRules(
    hauteur="15 m max — (Article UB.10, p.25)",
    emprise="60 % max — (Article UB.9, p.22)",
    implantation_voie="Alignement obligatoire — (Article UB.6, p.18)",
    limites_separatives="3 m min sans baie | 6 m min avec baie — (UB.7, p.20)",
    stationnement="1 place/logement | 1/85 m² bureaux — (UB.12, p.30)",
    lls="30 % LLS si programme > 800 m² SDP — (UB.4, p.10)",
    espaces_verts="20 % min espaces verts | 10 % pleine terre — (UB.13, p.35)",
    destinations="✅ Habitation, commerces, bureaux | ⛔ Industrie lourde — (UB.1-2, p.5)",
    pages={"hauteur": 25, "emprise": 22},
)

_VALID_NUMERIC_DICT = {
    "hauteur_max_m": 15.0,
    "hauteur_max_niveaux": None,
    "hauteur_max_ngf": None,
    "hauteur_facade_m": None,
    "emprise_max_pct": 60.0,
    "recul_voirie_m": None,
    "recul_voirie_formula": None,
    "recul_limite_lat_m": 3.0,
    "recul_limite_lat_formula": None,
    "recul_fond_m": None,
    "recul_fond_formula": None,
    "cos": None,
    "sdp_max_m2": None,
    "pleine_terre_min_pct": 10.0,
    "surface_vegetalisee_min_pct": 20.0,
    "coef_biotope_min": None,
    "stationnement_par_logement": 1.0,
    "stationnement_par_m2_bureau": None,
    "stationnement_par_m2_commerce": None,
    "bandes_constructibles": None,
    "article_refs": {"hauteur": "Art. UB.10", "emprise": "Art. UB.9"},
    "extraction_confidence": 0.85,
    "extraction_warnings": [],
}


# ---------------------------------------------------------------------------
# test_converts_basic_rules
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_converts_basic_rules() -> None:
    """Mock _call_numericizer_llm returning a valid dict → verify NumericRules fields."""
    with patch(
        "core.plu.numericizer._call_numericizer_llm",
        new=AsyncMock(return_value=_VALID_NUMERIC_DICT),
    ):
        result = await numericize_rules(_PARSED)

    assert isinstance(result, NumericRules)
    assert result.hauteur_max_m == 15.0
    assert result.emprise_max_pct == 60.0
    assert result.recul_limite_lat_m == 3.0
    assert result.stationnement_par_logement == 1.0
    assert result.pleine_terre_min_pct == 10.0
    assert result.surface_vegetalisee_min_pct == 20.0
    assert result.extraction_confidence == 0.85
    assert result.article_refs == {"hauteur": "Art. UB.10", "emprise": "Art. UB.9"}
    assert result.extraction_warnings == []


@pytest.mark.asyncio
async def test_extraction_confidence_preserved() -> None:
    """extraction_confidence from LLM is passed through unchanged."""
    numeric_dict = {**_VALID_NUMERIC_DICT, "extraction_confidence": 0.42}
    with patch(
        "core.plu.numericizer._call_numericizer_llm",
        new=AsyncMock(return_value=numeric_dict),
    ):
        result = await numericize_rules(_PARSED)

    assert result.extraction_confidence == 0.42


@pytest.mark.asyncio
async def test_article_refs_preserved() -> None:
    """article_refs dict is preserved in the NumericRules output."""
    refs = {"hauteur": "Art. UA.10, p.26", "emprise": "Art. UA.9, p.24"}
    numeric_dict = {**_VALID_NUMERIC_DICT, "article_refs": refs}
    with patch(
        "core.plu.numericizer._call_numericizer_llm",
        new=AsyncMock(return_value=numeric_dict),
    ):
        result = await numericize_rules(_PARSED)

    assert result.article_refs == refs


@pytest.mark.asyncio
async def test_rule_formula_nested_object() -> None:
    """RuleFormula nested objects are deserialized correctly."""
    formula_dict = {
        "expression": "H/2",
        "min_value": 3.0,
        "max_value": None,
        "units": "m",
        "raw_text": "retrait = H/2 min 3 m",
    }
    numeric_dict = {**_VALID_NUMERIC_DICT, "recul_limite_lat_formula": formula_dict}
    with patch(
        "core.plu.numericizer._call_numericizer_llm",
        new=AsyncMock(return_value=numeric_dict),
    ):
        result = await numericize_rules(_PARSED)

    assert result.recul_limite_lat_formula is not None
    assert isinstance(result.recul_limite_lat_formula, RuleFormula)
    assert result.recul_limite_lat_formula.expression == "H/2"
    assert result.recul_limite_lat_formula.min_value == 3.0


@pytest.mark.asyncio
async def test_missing_optional_fields_default_to_none() -> None:
    """Fields absent from the LLM dict default to None / empty."""
    minimal_dict: dict = {
        "extraction_confidence": 0.5,
        "extraction_warnings": [],
        "article_refs": {},
        "pleine_terre_min_pct": 0.0,
    }
    with patch(
        "core.plu.numericizer._call_numericizer_llm",
        new=AsyncMock(return_value=minimal_dict),
    ):
        result = await numericize_rules(_PARSED)

    assert result.hauteur_max_m is None
    assert result.emprise_max_pct is None
    assert result.stationnement_par_logement is None
    assert result.extraction_confidence == 0.5


@pytest.mark.asyncio
async def test_extraction_warnings_list() -> None:
    """extraction_warnings list is preserved."""
    warnings = ["hauteur non chiffrée", "emprise manquante"]
    numeric_dict = {**_VALID_NUMERIC_DICT, "extraction_warnings": warnings}
    with patch(
        "core.plu.numericizer._call_numericizer_llm",
        new=AsyncMock(return_value=numeric_dict),
    ):
        result = await numericize_rules(_PARSED)

    assert result.extraction_warnings == warnings
