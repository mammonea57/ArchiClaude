"""Unit tests for the Paris Bioclimatique deterministic parser (Task 11)."""

from __future__ import annotations

import pytest

from core.plu.parsers.paris_bioclim import (
    PARIS_BIOCLIM_ZONES,
    is_paris_bioclim,
    parse_paris_bioclim,
)
from core.plu.schemas import NumericRules, ParsedRules


class TestIsParisbioclim:
    def test_is_paris_ug(self) -> None:
        """75108 + UG → True (UG is a Paris Bioclimatique zone)."""
        assert is_paris_bioclim("75108", "UG") is True

    def test_is_paris_ugsu(self) -> None:
        """75101 + UGSU → True."""
        assert is_paris_bioclim("75101", "UGSU") is True

    def test_is_paris_uv(self) -> None:
        """75056 + UV → True."""
        assert is_paris_bioclim("75056", "UV") is True

    def test_is_paris_uve(self) -> None:
        """75056 + UVE → True."""
        assert is_paris_bioclim("75056", "UVE") is True

    def test_is_paris_un(self) -> None:
        """75056 + UN → True."""
        assert is_paris_bioclim("75056", "UN") is True

    def test_is_paris_usc(self) -> None:
        """75056 + USC → True."""
        assert is_paris_bioclim("75056", "USC") is True

    def test_not_paris(self) -> None:
        """94052 + UB → False (not Paris INSEE)."""
        assert is_paris_bioclim("94052", "UB") is False

    def test_unknown_zone(self) -> None:
        """75108 + XYZ → False (zone not in PARIS_BIOCLIM_ZONES)."""
        assert is_paris_bioclim("75108", "XYZ") is False

    def test_case_insensitive_zone(self) -> None:
        """75108 + 'ug' (lowercase) → True."""
        assert is_paris_bioclim("75108", "ug") is True

    def test_case_insensitive_ugsu(self) -> None:
        """75101 + 'ugsu' → True."""
        assert is_paris_bioclim("75101", "ugsu") is True

    def test_non_paris_with_known_zone(self) -> None:
        """77001 + UG → False (not Paris)."""
        assert is_paris_bioclim("77001", "UG") is False


class TestParseParisbioclim:
    def test_parse_ug_returns_tuple(self) -> None:
        """parse_paris_bioclim returns (ParsedRules, NumericRules) for UG."""
        result = parse_paris_bioclim("UG", "75108")
        assert isinstance(result, tuple)
        assert len(result) == 2
        parsed, numeric = result
        assert isinstance(parsed, ParsedRules)
        assert isinstance(numeric, NumericRules)

    def test_parse_ug_source(self) -> None:
        """ParsedRules.source must be 'paris_bioclim_parser'."""
        parsed, _ = parse_paris_bioclim("UG", "75108")
        assert parsed.source == "paris_bioclim_parser"

    def test_parse_ug_confidence(self) -> None:
        """NumericRules.extraction_confidence must be 1.0 for deterministic parser."""
        _, numeric = parse_paris_bioclim("UG", "75108")
        assert numeric.extraction_confidence == 1.0

    def test_parse_ug_hauteur_max_m(self) -> None:
        """UG zone: hauteur_max_m must be 37.0."""
        _, numeric = parse_paris_bioclim("UG", "75108")
        assert numeric.hauteur_max_m == 37.0

    def test_parse_ug_emprise(self) -> None:
        """UG zone: emprise_max_pct must be 65.0."""
        _, numeric = parse_paris_bioclim("UG", "75108")
        assert numeric.emprise_max_pct == 65.0

    def test_parse_ug_pleine_terre(self) -> None:
        """UG zone: pleine_terre_min_pct must be 30.0."""
        _, numeric = parse_paris_bioclim("UG", "75108")
        assert numeric.pleine_terre_min_pct == 30.0

    def test_parse_ug_niveaux(self) -> None:
        """UG zone: hauteur_max_niveaux must be 10."""
        _, numeric = parse_paris_bioclim("UG", "75108")
        assert numeric.hauteur_max_niveaux == 10

    def test_parse_uv_valid(self) -> None:
        """parse_paris_bioclim returns valid rules for UV zone."""
        parsed, numeric = parse_paris_bioclim("UV", "75056")
        assert parsed.source == "paris_bioclim_parser"
        assert numeric.extraction_confidence == 1.0
        assert numeric.hauteur_max_m == 25.0
        assert numeric.emprise_max_pct == 50.0
        assert numeric.pleine_terre_min_pct == 40.0
        assert numeric.hauteur_max_niveaux == 7

    def test_parse_ugsu(self) -> None:
        """UGSU zone values are correct."""
        _, numeric = parse_paris_bioclim("UGSU", "75101")
        assert numeric.hauteur_max_m == 31.0
        assert numeric.emprise_max_pct == 60.0
        assert numeric.pleine_terre_min_pct == 35.0
        assert numeric.coef_biotope_min == pytest.approx(0.35)

    def test_parse_uve(self) -> None:
        """UVE zone values are correct."""
        _, numeric = parse_paris_bioclim("UVE", "75056")
        assert numeric.hauteur_max_m == 16.0
        assert numeric.emprise_max_pct == 40.0
        assert numeric.pleine_terre_min_pct == 50.0

    def test_parse_un(self) -> None:
        """UN zone values are correct."""
        _, numeric = parse_paris_bioclim("UN", "75056")
        assert numeric.hauteur_max_m == 12.0
        assert numeric.emprise_max_pct == 20.0
        assert numeric.pleine_terre_min_pct == 70.0

    def test_parse_usc(self) -> None:
        """USC zone values are correct."""
        _, numeric = parse_paris_bioclim("USC", "75056")
        assert numeric.hauteur_max_m == 25.0
        assert numeric.emprise_max_pct == 75.0
        assert numeric.pleine_terre_min_pct == 15.0

    def test_parse_no_warnings(self) -> None:
        """Deterministic parser produces no extraction warnings."""
        _, numeric = parse_paris_bioclim("UG", "75108")
        assert numeric.extraction_warnings == []

    def test_parse_stationnement_zero(self) -> None:
        """Paris exempts parking: stationnement_par_logement must be 0.0."""
        _, numeric = parse_paris_bioclim("UV", "75056")
        assert numeric.stationnement_par_logement == 0.0

    def test_parse_coef_biotope_ug(self) -> None:
        """UG coef_biotope_min must be 0.30."""
        _, numeric = parse_paris_bioclim("UG", "75108")
        assert numeric.coef_biotope_min == pytest.approx(0.30)

    def test_parse_lowercase_zone_code(self) -> None:
        """Parser accepts lowercase zone codes."""
        parsed, numeric = parse_paris_bioclim("ug", "75108")
        assert numeric.hauteur_max_m == 37.0
        assert parsed.source == "paris_bioclim_parser"

    def test_parse_invalid_zone_raises_key_error(self) -> None:
        """Unknown zone code raises KeyError."""
        with pytest.raises(KeyError):
            parse_paris_bioclim("XYZ", "75108")

    def test_parse_non_paris_raises_value_error(self) -> None:
        """Non-Paris INSEE raises ValueError."""
        with pytest.raises(ValueError):
            parse_paris_bioclim("UG", "94052")

    def test_parsed_rules_hauteur_text_not_none(self) -> None:
        """ParsedRules.hauteur contains the height string."""
        parsed, _ = parse_paris_bioclim("UG", "75108")
        assert parsed.hauteur is not None
        assert "37" in parsed.hauteur

    def test_parsed_rules_espaces_verts(self) -> None:
        """ParsedRules.espaces_verts contains pleine terre info."""
        parsed, _ = parse_paris_bioclim("UG", "75108")
        assert parsed.espaces_verts is not None
        assert "30" in parsed.espaces_verts

    def test_parsed_rules_cached_false(self) -> None:
        """ParsedRules.cached must be False for fresh deterministic output."""
        parsed, _ = parse_paris_bioclim("UG", "75108")
        assert parsed.cached is False


class TestParisbioclimTable:
    def test_all_zones_present(self) -> None:
        """All 6 zones must be present in PARIS_BIOCLIM_ZONES."""
        expected = {"UG", "UGSU", "UV", "UVE", "UN", "USC"}
        assert set(PARIS_BIOCLIM_ZONES.keys()) == expected

    def test_all_zones_have_required_keys(self) -> None:
        """Every zone entry must have all required numeric fields."""
        required_keys = {
            "hauteur_max_m",
            "hauteur_max_niveaux",
            "emprise_max_pct",
            "pleine_terre_min_pct",
            "coef_biotope_min",
            "stationnement_par_logement",
            "description",
        }
        for zone, data in PARIS_BIOCLIM_ZONES.items():
            missing = required_keys - set(data.keys())
            assert not missing, f"Zone {zone} missing keys: {missing}"

    def test_pleine_terre_increases_green_intensity(self) -> None:
        """UN (natural) must have higher pleine_terre than UG (urban)."""
        assert (
            PARIS_BIOCLIM_ZONES["UN"]["pleine_terre_min_pct"]
            > PARIS_BIOCLIM_ZONES["UG"]["pleine_terre_min_pct"]
        )

    def test_hauteur_decreases_green_intensity(self) -> None:
        """UG (urban general) must be taller than UN (natural)."""
        assert (
            PARIS_BIOCLIM_ZONES["UG"]["hauteur_max_m"]
            > PARIS_BIOCLIM_ZONES["UN"]["hauteur_max_m"]
        )
