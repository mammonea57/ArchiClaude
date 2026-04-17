"""Unit tests for core.plu.schemas — ParsedRules, NumericRules, RuleFormula, Bande."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from core.plu.schemas import Bande, NumericRules, ParsedRules, RuleFormula

# ---------------------------------------------------------------------------
# ParsedRules
# ---------------------------------------------------------------------------


def test_minimal_parsed_rules() -> None:
    rules = ParsedRules()
    assert rules.hauteur is None
    assert rules.emprise is None
    assert rules.implantation_voie is None
    assert rules.limites_separatives is None
    assert rules.stationnement is None
    assert rules.lls is None
    assert rules.espaces_verts is None
    assert rules.destinations is None
    assert rules.pages == {}
    assert rules.source == "ai_parsed"
    assert rules.cached is False


def test_all_fields() -> None:
    rules = ParsedRules(
        hauteur="15 m maximum",
        emprise="60 % de l'unité foncière",
        implantation_voie="Retrait de 5 m",
        limites_separatives="Mitoyen ou retrait H/2",
        stationnement="1 place par logement",
        lls="30 % minimum",
        espaces_verts="30 % pleine terre",
        destinations="Logements, bureaux",
        pages={"hauteur": 12, "emprise": 14},
        source="cache",
        cached=True,
    )
    assert rules.hauteur == "15 m maximum"
    assert rules.source == "cache"
    assert rules.cached is True
    assert rules.pages["hauteur"] == 12


def test_cached_flag() -> None:
    rules = ParsedRules(cached=True, source="manual")
    assert rules.cached is True
    assert rules.source == "manual"


def test_parsed_rules_sources() -> None:
    for src in ("ai_parsed", "cache", "manual", "paris_bioclim_parser"):
        r = ParsedRules(source=src)  # type: ignore[arg-type]
        assert r.source == src


def test_parsed_rules_invalid_source() -> None:
    with pytest.raises(ValidationError):
        ParsedRules(source="unknown_source")  # type: ignore[arg-type]


def test_pages_none_values() -> None:
    rules = ParsedRules(pages={"hauteur": None, "emprise": 10})
    assert rules.pages["hauteur"] is None
    assert rules.pages["emprise"] == 10


# ---------------------------------------------------------------------------
# RuleFormula
# ---------------------------------------------------------------------------


def test_rule_formula() -> None:
    f = RuleFormula(expression="H/2", raw_text="retrait égal à la moitié de la hauteur")
    assert f.expression == "H/2"
    assert f.min_value is None
    assert f.max_value is None
    assert f.units == "m"
    assert f.raw_text == "retrait égal à la moitié de la hauteur"


def test_rule_formula_with_bounds() -> None:
    f = RuleFormula(expression="H/2", min_value=3.0, max_value=8.0, units="m")
    assert f.min_value == 3.0
    assert f.max_value == 8.0


def test_rule_formula_defaults() -> None:
    f = RuleFormula(expression="0.7*S")
    assert f.units == "m"
    assert f.raw_text == ""
    assert f.min_value is None
    assert f.max_value is None


# ---------------------------------------------------------------------------
# Bande
# ---------------------------------------------------------------------------


def test_bande() -> None:
    b = Bande(name="principale", hauteur_max_m=15.0, emprise_max_pct=60.0, depth_from_voie_m=20.0)
    assert b.name == "principale"
    assert b.hauteur_max_m == 15.0
    assert b.emprise_max_pct == 60.0
    assert b.depth_from_voie_m == 20.0


def test_bande_secondaire() -> None:
    b = Bande(name="secondaire", hauteur_max_m=10.0)
    assert b.name == "secondaire"
    assert b.emprise_max_pct is None
    assert b.depth_from_voie_m is None


def test_bande_fond() -> None:
    b = Bande(name="fond")
    assert b.name == "fond"
    assert b.hauteur_max_m is None


def test_bande_invalid_name() -> None:
    with pytest.raises(ValidationError):
        Bande(name="invalid_zone")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# NumericRules
# ---------------------------------------------------------------------------


def test_numeric_rules_minimal() -> None:
    nr = NumericRules()
    assert nr.hauteur_max_m is None
    assert nr.hauteur_max_niveaux is None
    assert nr.hauteur_max_ngf is None
    assert nr.hauteur_facade_m is None
    assert nr.emprise_max_pct is None
    assert nr.recul_voirie_m is None
    assert nr.recul_voirie_formula is None
    assert nr.recul_limite_lat_m is None
    assert nr.recul_limite_lat_formula is None
    assert nr.recul_fond_m is None
    assert nr.recul_fond_formula is None
    assert nr.cos is None
    assert nr.sdp_max_m2 is None
    assert nr.pleine_terre_min_pct == 0.0
    assert nr.surface_vegetalisee_min_pct is None
    assert nr.coef_biotope_min is None
    assert nr.stationnement_par_logement is None
    assert nr.stationnement_par_m2_bureau is None
    assert nr.stationnement_par_m2_commerce is None
    assert nr.bandes_constructibles is None
    assert nr.article_refs == {}
    assert nr.extraction_confidence == 0.0
    assert nr.extraction_warnings == []


def test_with_formulas_and_bandes() -> None:
    formula = RuleFormula(expression="H/2", min_value=3.0, raw_text="retrait H/2 min 3m")
    bande = Bande(name="principale", hauteur_max_m=18.0, depth_from_voie_m=25.0)

    nr = NumericRules(
        hauteur_max_m=18.0,
        hauteur_max_niveaux=5,
        emprise_max_pct=65.0,
        recul_voirie_m=None,
        recul_voirie_formula=formula,
        recul_limite_lat_m=3.0,
        recul_fond_formula=RuleFormula(expression="H/3"),
        pleine_terre_min_pct=30.0,
        coef_biotope_min=0.3,
        stationnement_par_logement=1.0,
        bandes_constructibles=[bande],
        article_refs={"hauteur": "Article UG.10", "emprise": "Article UG.9"},
        extraction_confidence=0.85,
        extraction_warnings=["hauteur_max_ngf not found"],
    )

    assert nr.hauteur_max_m == 18.0
    assert nr.hauteur_max_niveaux == 5
    assert nr.recul_voirie_formula is not None
    assert nr.recul_voirie_formula.expression == "H/2"
    assert nr.bandes_constructibles is not None
    assert len(nr.bandes_constructibles) == 1
    assert nr.bandes_constructibles[0].name == "principale"
    assert nr.extraction_confidence == 0.85
    assert "hauteur_max_ngf not found" in nr.extraction_warnings
    assert nr.article_refs["hauteur"] == "Article UG.10"


def test_numeric_rules_pleine_terre_default() -> None:
    nr = NumericRules()
    assert nr.pleine_terre_min_pct == 0.0


def test_numeric_rules_extraction_warnings_list() -> None:
    nr = NumericRules(extraction_warnings=["w1", "w2"])
    assert len(nr.extraction_warnings) == 2
