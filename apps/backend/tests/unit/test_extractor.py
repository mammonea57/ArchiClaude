"""Unit tests for core.plu.extractor — select_model and extract_rules pipeline."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from core.plu.extractor import extract_rules, select_model
from core.plu.schemas import ParsedRules

# ---------------------------------------------------------------------------
# select_model
# ---------------------------------------------------------------------------


def test_select_model_plui_uses_sonnet() -> None:
    """PLUi document should always use Sonnet regardless of text length."""
    model = select_model(is_plui=True, text_length=50_000)
    assert "sonnet" in model.lower()


def test_select_model_large_uses_sonnet() -> None:
    """Text > 120K chars should trigger Sonnet even if not PLUi."""
    model = select_model(is_plui=False, text_length=150_000)
    assert "sonnet" in model.lower()


def test_select_model_small_uses_haiku() -> None:
    """Short non-PLUi text should use the cheaper Haiku model."""
    model = select_model(is_plui=False, text_length=50_000)
    assert "haiku" in model.lower()


def test_select_model_exact_boundary_haiku() -> None:
    """Text at exactly 120K chars should still use Haiku (boundary is >120K)."""
    model = select_model(is_plui=False, text_length=120_000)
    assert "haiku" in model.lower()


def test_select_model_over_boundary_sonnet() -> None:
    """Text at 120_001 chars should use Sonnet."""
    model = select_model(is_plui=False, text_length=120_001)
    assert "sonnet" in model.lower()


# ---------------------------------------------------------------------------
# extract_rules — happy path
# ---------------------------------------------------------------------------

_VALID_LLM_RESPONSE = """\
{
  "hauteur": "15 m max — (Article UB.10, p.25)",
  "emprise": "60 % max — (Article UB.9, p.22)",
  "implantation_voie": "Alignement obligatoire — (Article UB.6, p.18)",
  "limites_separatives": "3 m min sans baie | 6 m min avec baie — (UB.7, p.20)",
  "stationnement": "1 place/logement | 1/85 m² bureaux — (UB.12, p.30)",
  "lls": "30 % LLS si programme > 800 m² SDP — (UB.4, p.10)",
  "espaces_verts": "20 % min espaces verts | 10 % pleine terre — (UB.13, p.35)",
  "destinations": "✅ Habitation, commerces, bureaux | ⛔ Industrie lourde — (UB.1-2, p.5)",
  "pages": {
    "hauteur": 25,
    "emprise": 22,
    "implantation_voie": 18,
    "limites_separatives": 20,
    "stationnement": 30,
    "lls": 10,
    "espaces_verts": 35,
    "destinations": 5
  }
}"""

_PLU_TEXT = (
    "ZONE UB\nArticle UB.10 — Hauteur\nLa hauteur maximale des constructions est fixée à 15 mètres.\n"
    "Article UB.9 — Emprise\nL'emprise au sol est limitée à 60 %.\n"
    "Article UB.6 — Implantation\nAlignement obligatoire.\n" * 100
)


@pytest.mark.asyncio
async def test_extract_rules_returns_parsed_rules() -> None:
    """Full pipeline mock: valid LLM response + valid PDF → ParsedRules with correct fields."""
    with (
        patch(
            "core.plu.extractor.pdf_fetcher.fetch_pdf_text",
            new=AsyncMock(return_value=(_PLU_TEXT, "abc123")),
        ),
        patch(
            "core.plu.extractor._call_llm",
            new=AsyncMock(return_value=_VALID_LLM_RESPONSE),
        ),
    ):
        result = await extract_rules(
            pdf_url="https://example.com/plu.pdf",
            zone_code="UB",
            zone_description="UB — Zone urbaine mixte",
        )

    assert result is not None
    assert isinstance(result, ParsedRules)
    assert result.hauteur is not None
    assert "15" in result.hauteur
    assert result.emprise is not None
    assert "60" in result.emprise
    assert result.source == "ai_parsed"
    assert isinstance(result.pages, dict)
    assert result.pages.get("hauteur") == 25


@pytest.mark.asyncio
async def test_extract_rules_with_commune_name() -> None:
    """extract_rules accepts commune_name and passes it through."""
    with (
        patch(
            "core.plu.extractor.pdf_fetcher.fetch_pdf_text",
            new=AsyncMock(return_value=(_PLU_TEXT, "abc123")),
        ),
        patch(
            "core.plu.extractor._call_llm",
            new=AsyncMock(return_value=_VALID_LLM_RESPONSE),
        ),
    ):
        result = await extract_rules(
            pdf_url="https://example.com/plui.pdf",
            zone_code="UB",
            zone_description="UB — Zone mixte",
            commune_name="Vincennes",
        )

    assert result is not None
    assert isinstance(result, ParsedRules)


# ---------------------------------------------------------------------------
# extract_rules — failure cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pdf_unavailable_returns_none() -> None:
    """When pdf_fetcher returns None (download failure), extract_rules returns None."""
    with patch(
        "core.plu.extractor.pdf_fetcher.fetch_pdf_text",
        new=AsyncMock(return_value=None),
    ):
        result = await extract_rules(
            pdf_url="https://example.com/missing.pdf",
            zone_code="UB",
            zone_description="UB",
        )

    assert result is None


@pytest.mark.asyncio
async def test_llm_returns_invalid_json_returns_none() -> None:
    """When LLM returns unparseable text, extract_rules returns None."""
    with (
        patch(
            "core.plu.extractor.pdf_fetcher.fetch_pdf_text",
            new=AsyncMock(return_value=(_PLU_TEXT, "abc123")),
        ),
        patch(
            "core.plu.extractor._call_llm",
            new=AsyncMock(return_value="Ce règlement ne contient pas de zone UB."),
        ),
    ):
        result = await extract_rules(
            pdf_url="https://example.com/plu.pdf",
            zone_code="UB",
            zone_description="UB",
        )

    assert result is None


@pytest.mark.asyncio
async def test_extract_rules_cleans_null_values() -> None:
    """LLM null/error string values are cleaned to None in the final ParsedRules."""
    response_with_nulls = """\
{
  "hauteur": "15 m max — (Article UB.10, p.25)",
  "emprise": "null",
  "implantation_voie": "not found",
  "limites_separatives": "3 m min — (UB.7)",
  "stationnement": "1 place/logement — (UB.12)",
  "lls": "Non précisé dans ce règlement",
  "espaces_verts": "20 % min — (UB.13)",
  "destinations": "✅ Habitation — (UB.1)",
  "pages": {}
}"""

    with (
        patch(
            "core.plu.extractor.pdf_fetcher.fetch_pdf_text",
            new=AsyncMock(return_value=(_PLU_TEXT, "abc123")),
        ),
        patch(
            "core.plu.extractor._call_llm",
            new=AsyncMock(return_value=response_with_nulls),
        ),
    ):
        result = await extract_rules(
            pdf_url="https://example.com/plu.pdf",
            zone_code="UB",
            zone_description="UB",
        )

    assert result is not None
    assert result.emprise is None  # "null" cleaned to None
    assert result.implantation_voie is None  # "not found" cleaned to None
    assert result.lls == "Non précisé dans ce règlement"  # kept as-is
    assert result.hauteur is not None
