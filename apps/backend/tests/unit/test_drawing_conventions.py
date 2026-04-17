"""Unit tests for core.drawing.conventions — normothèque SVG."""

from __future__ import annotations

import pytest

from core.drawing.conventions import (
    HACHURES,
    POLICES,
    SYMBOLES,
    CARTOUCHE_DEFAULTS,
    TRAIT_EPAISSEURS,
)


# ---------------------------------------------------------------------------
# TRAIT_EPAISSEURS
# ---------------------------------------------------------------------------


def test_trait_epaisseurs_required_keys() -> None:
    required = {"mur_porteur", "cloison", "contour_parcelle", "axe", "cote"}
    assert required.issubset(TRAIT_EPAISSEURS.keys())


def test_trait_epaisseurs_values_positive() -> None:
    for key, value in TRAIT_EPAISSEURS.items():
        assert value > 0, f"TRAIT_EPAISSEURS[{key!r}] must be positive, got {value}"


def test_trait_epaisseurs_known_values() -> None:
    assert TRAIT_EPAISSEURS["mur_porteur"] == pytest.approx(0.50)
    assert TRAIT_EPAISSEURS["cloison"] == pytest.approx(0.18)
    assert TRAIT_EPAISSEURS["contour_parcelle"] == pytest.approx(0.70)


# ---------------------------------------------------------------------------
# HACHURES
# ---------------------------------------------------------------------------


def test_hachures_required_keys() -> None:
    required = {"beton", "bois", "terrain_naturel"}
    assert required.issubset(HACHURES.keys())


def test_hachures_each_has_pattern_and_color() -> None:
    for name, hachure in HACHURES.items():
        assert "pattern" in hachure, f"HACHURES[{name!r}] missing 'pattern'"
        assert "color" in hachure, f"HACHURES[{name!r}] missing 'color'"


def test_hachures_color_is_string() -> None:
    for name, hachure in HACHURES.items():
        assert isinstance(hachure["color"], str), f"HACHURES[{name!r}]['color'] must be str"


# ---------------------------------------------------------------------------
# POLICES
# ---------------------------------------------------------------------------


def test_polices_required_keys() -> None:
    required = {"titre", "corps", "cote"}
    assert required.issubset(POLICES.keys())


def test_polices_each_has_family_and_size() -> None:
    for name, police in POLICES.items():
        assert "family" in police, f"POLICES[{name!r}] missing 'family'"
        assert "size_pt" in police, f"POLICES[{name!r}] missing 'size_pt'"


def test_polices_titre() -> None:
    assert POLICES["titre"]["family"] == "Playfair Display"
    assert POLICES["titre"]["size_pt"] == 14


def test_polices_corps() -> None:
    assert POLICES["corps"]["family"] == "Inter"
    assert POLICES["corps"]["size_pt"] == 9


def test_polices_cote() -> None:
    assert POLICES["cote"]["family"] == "Inter"
    assert POLICES["cote"]["size_pt"] == 7


def test_polices_sizes_positive() -> None:
    for name, police in POLICES.items():
        assert police["size_pt"] > 0, f"POLICES[{name!r}]['size_pt'] must be positive"


# ---------------------------------------------------------------------------
# SYMBOLES
# ---------------------------------------------------------------------------


def test_symboles_required_keys() -> None:
    required = {"nord", "arbre", "porte", "escalier", "ascenseur"}
    assert required.issubset(SYMBOLES.keys())


def test_symboles_each_has_svg_id() -> None:
    for name, symbole in SYMBOLES.items():
        assert "svg_id" in symbole, f"SYMBOLES[{name!r}] missing 'svg_id'"


def test_symboles_svg_id_is_string() -> None:
    for name, symbole in SYMBOLES.items():
        assert isinstance(symbole["svg_id"], str), f"SYMBOLES[{name!r}]['svg_id'] must be str"
        assert len(symbole["svg_id"]) > 0, f"SYMBOLES[{name!r}]['svg_id'] must be non-empty"


# ---------------------------------------------------------------------------
# CARTOUCHE_DEFAULTS
# ---------------------------------------------------------------------------


def test_cartouche_defaults_required_keys() -> None:
    required = {"width_mm", "height_mm"}
    assert required.issubset(CARTOUCHE_DEFAULTS.keys())


def test_cartouche_defaults_width() -> None:
    assert CARTOUCHE_DEFAULTS["width_mm"] == pytest.approx(180.0)


def test_cartouche_defaults_height() -> None:
    assert CARTOUCHE_DEFAULTS["height_mm"] == pytest.approx(40.0)


def test_cartouche_defaults_positive() -> None:
    assert CARTOUCHE_DEFAULTS["width_mm"] > 0
    assert CARTOUCHE_DEFAULTS["height_mm"] > 0
