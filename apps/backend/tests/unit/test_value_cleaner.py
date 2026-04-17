"""Unit tests for core.plu.value_cleaner — is_error_pattern, clean_value, hoist_chiffre_front."""

from __future__ import annotations

from core.plu.value_cleaner import clean_value, hoist_chiffre_front, is_error_pattern

# ---------------------------------------------------------------------------
# is_error_pattern
# ---------------------------------------------------------------------------


def test_error_pattern_null() -> None:
    assert is_error_pattern("null") is True
    assert is_error_pattern("NULL") is True
    assert is_error_pattern("Null") is True


def test_error_pattern_na() -> None:
    assert is_error_pattern("N/A") is True
    assert is_error_pattern("n/a") is True
    assert is_error_pattern("NA") is True


def test_error_pattern_not_found() -> None:
    assert is_error_pattern("not found") is True
    assert is_error_pattern("Not Found") is True
    assert is_error_pattern("non trouvé") is True
    assert is_error_pattern("Non Trouvé") is True
    assert is_error_pattern("non trouvée") is True


def test_error_pattern_section_incomplete() -> None:
    assert is_error_pattern("section incomplete") is True
    assert is_error_pattern("Section Incomplete") is True
    assert is_error_pattern("section incomplète") is True


def test_error_pattern_none_string() -> None:
    assert is_error_pattern("none") is True
    assert is_error_pattern("None") is True


def test_error_pattern_false_for_real_value() -> None:
    assert is_error_pattern("15 m") is False
    assert is_error_pattern("1 place par logement") is False
    assert is_error_pattern("60% de l'emprise") is False
    assert is_error_pattern("Non précisé dans ce règlement") is False
    assert is_error_pattern("Non réglementé") is False


# ---------------------------------------------------------------------------
# clean_value
# ---------------------------------------------------------------------------


def test_clean_value_none_passthrough() -> None:
    assert clean_value(None) is None


def test_clean_value_error_to_none() -> None:
    assert clean_value("null") is None
    assert clean_value("N/A") is None
    assert clean_value("not found") is None
    assert clean_value("section incomplete") is None


def test_clean_value_normalize_non_precise() -> None:
    result = clean_value("Non précisé dans ce règlement — voir article 3")
    assert result == "Non précisé dans ce règlement"


def test_clean_value_normalize_non_reglemente() -> None:
    result = clean_value("Non réglementé — se référer aux dispositions générales")
    assert result == "Non réglementé"


def test_clean_value_strip_whitespace() -> None:
    result = clean_value("  15 m maximum  ")
    assert result == "15 m maximum"


def test_clean_value_truncate_180() -> None:
    long_value = "A" * 200
    result = clean_value(long_value)
    assert result is not None
    assert len(result) == 180


def test_clean_value_regular_value_unchanged() -> None:
    result = clean_value("1 place par logement de moins de 100 m²")
    assert result == "1 place par logement de moins de 100 m²"


def test_clean_value_empty_string() -> None:
    # Empty string is not an error pattern but should still be stripped
    result = clean_value("")
    assert result == ""


def test_clean_value_non_precise_no_suffix() -> None:
    result = clean_value("Non précisé dans ce règlement")
    assert result == "Non précisé dans ce règlement"


def test_clean_value_non_reglemente_dash_variant() -> None:
    result = clean_value("Non réglementé - autre suffixe")
    assert result == "Non réglementé"


# ---------------------------------------------------------------------------
# hoist_chiffre_front
# ---------------------------------------------------------------------------


def test_hoist_already_starts_with_digit() -> None:
    value = "15 m maximum autorisé"
    assert hoist_chiffre_front(value) == "15 m maximum autorisé"


def test_hoist_already_starts_with_r_plus() -> None:
    value = "R+4 maximum"
    assert hoist_chiffre_front(value) == "R+4 maximum"


def test_hoist_already_starts_with_percent() -> None:
    value = "60% de l'unité foncière"
    assert hoist_chiffre_front(value) == "60% de l'unité foncière"


def test_hoist_label_colon() -> None:
    value = "Stationnement : 1 place/85m²"
    result = hoist_chiffre_front(value)
    # Number should come first
    assert result.startswith("1")


def test_hoist_buried_number() -> None:
    value = "Maximum autorisé de 15 m"
    result = hoist_chiffre_front(value)
    assert result.startswith("15")


def test_hoist_r_plus_buried() -> None:
    value = "Hauteur limitée à R+3"
    result = hoist_chiffre_front(value)
    assert result.startswith("R+3")


def test_hoist_no_number_unchanged() -> None:
    value = "Non réglementé"
    assert hoist_chiffre_front(value) == "Non réglementé"


def test_hoist_percent_buried() -> None:
    value = "Emprise maximale de 60%"
    result = hoist_chiffre_front(value)
    assert result.startswith("60%")


def test_hoist_logements() -> None:
    value = "Minimum de 2 logements par opération"
    result = hoist_chiffre_front(value)
    assert result.startswith("2")
