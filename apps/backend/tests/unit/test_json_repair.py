"""Unit tests for core.plu.json_repair — extract_and_parse_json."""

from __future__ import annotations

import pytest

from core.plu.json_repair import extract_and_parse_json


# ---------------------------------------------------------------------------
# Happy-path
# ---------------------------------------------------------------------------


def test_clean_json() -> None:
    raw = '{"hauteur": "15 m", "emprise": "60%"}'
    result = extract_and_parse_json(raw)
    assert result is not None
    assert result["hauteur"] == "15 m"
    assert result["emprise"] == "60%"


def test_markdown_block() -> None:
    raw = '```json\n{"hauteur": "15 m", "emprise": "60%"}\n```'
    result = extract_and_parse_json(raw)
    assert result is not None
    assert result["hauteur"] == "15 m"


def test_surrounding_text() -> None:
    raw = 'Voici le résultat:\n{"hauteur": "15 m"}\nFin du résultat.'
    result = extract_and_parse_json(raw)
    assert result is not None
    assert result["hauteur"] == "15 m"


def test_nested_object() -> None:
    raw = '{"rules": {"hauteur": "15 m", "emprise": "60%"}, "source": "ai"}'
    result = extract_and_parse_json(raw)
    assert result is not None
    assert result["rules"]["hauteur"] == "15 m"
    assert result["source"] == "ai"


# ---------------------------------------------------------------------------
# Truncation / repair
# ---------------------------------------------------------------------------


def test_truncated_odd_quotes() -> None:
    # Truncated mid-string — odd number of quotes
    raw = '{"hauteur": "15 m", "stat": "1 place par'
    result = extract_and_parse_json(raw)
    assert result is not None
    # Should have at least the complete field
    assert result.get("hauteur") == "15 m"


def test_truncated_missing_braces() -> None:
    # Missing closing brace
    raw = '{"h": "15 m"'
    result = extract_and_parse_json(raw)
    assert result is not None
    assert result.get("h") == "15 m"


def test_trailing_comma() -> None:
    raw = '{"h": "15 m",}'
    result = extract_and_parse_json(raw)
    assert result is not None
    assert result["h"] == "15 m"


def test_trailing_comma_nested() -> None:
    raw = '{"rules": {"h": "15 m",}}'
    result = extract_and_parse_json(raw)
    assert result is not None
    assert result["rules"]["h"] == "15 m"


# ---------------------------------------------------------------------------
# No JSON
# ---------------------------------------------------------------------------


def test_no_json() -> None:
    result = extract_and_parse_json("Aucun résultat trouvé pour cette parcelle.")
    assert result is None


def test_empty_string() -> None:
    result = extract_and_parse_json("")
    assert result is None


def test_only_whitespace() -> None:
    result = extract_and_parse_json("   \n\t  ")
    assert result is None
