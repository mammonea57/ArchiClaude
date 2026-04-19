"""Unit tests for core.pcmi.cartouche_pc."""

from __future__ import annotations

import pytest

from core.pcmi.cartouche_pc import SIGNATURE, render_cartouche_svg
from core.pcmi.schemas import CartouchePC


def _make_cartouche(**overrides: object) -> CartouchePC:
    defaults: dict[str, object] = {
        "nom_projet": "Résidence Les Lilas",
        "adresse": "12 rue de la Paix, 75001 Paris",
        "parcelles_refs": ["75056AB0012", "75056AB0013"],
        "petitionnaire_nom": "SCI Dupont",
        "petitionnaire_contact": "dupont@example.com",
        "architecte_nom": "Cabinet Moreau",
        "architecte_ordre": "CROA Île-de-France",
        "architecte_contact": "moreau@example.com",
        "piece_num": "PCMI1",
        "piece_titre": "Plan de situation",
        "echelle": "1/25000",
        "date": "2026-04-18",
        "indice": "B",
    }
    defaults.update(overrides)
    return CartouchePC(**defaults)  # type: ignore[arg-type]


def test_renders_svg() -> None:
    c = _make_cartouche()
    result = render_cartouche_svg(c, width_mm=210.0)
    assert result.startswith("<g")
    assert "Résidence Les Lilas" in result
    assert "PCMI1" in result


def test_contains_archiclaude_signature() -> None:
    c = _make_cartouche()
    result = render_cartouche_svg(c, width_mm=210.0)
    assert SIGNATURE in result
    assert "archiclaude.app" in result


def test_contains_petitionnaire() -> None:
    c = _make_cartouche()
    result = render_cartouche_svg(c, width_mm=210.0)
    assert "SCI Dupont" in result
    assert "dupont@example.com" in result


def test_contains_architecte() -> None:
    c = _make_cartouche()
    result = render_cartouche_svg(c, width_mm=210.0)
    assert "Cabinet Moreau" in result
    assert "CROA Île-de-France" in result
    assert "moreau@example.com" in result


def test_without_architecte() -> None:
    """Rendering without an architecte must not raise."""
    c = _make_cartouche(
        architecte_nom=None,
        architecte_ordre=None,
        architecte_contact=None,
    )
    result = render_cartouche_svg(c, width_mm=210.0)
    assert result.startswith("<g")
    # Architecte block should not appear
    assert "Cabinet Moreau" not in result


def test_contains_indice() -> None:
    c = _make_cartouche(indice="C")
    result = render_cartouche_svg(c, width_mm=210.0)
    assert "Indice" in result
    assert "C" in result


def test_contains_parcelles_refs() -> None:
    c = _make_cartouche(parcelles_refs=["75056AB0099", "75056AB0100"])
    result = render_cartouche_svg(c, width_mm=210.0)
    assert "75056AB0099" in result
    assert "75056AB0100" in result


def test_xml_escaping_in_project_name() -> None:
    """Special XML characters in project name must be escaped."""
    c = _make_cartouche(nom_projet="Résidence <Les Lilas> & Cie")
    result = render_cartouche_svg(c, width_mm=210.0)
    assert "&lt;Les Lilas&gt;" in result
    assert "&amp; Cie" in result


@pytest.mark.parametrize("width_mm", [148.0, 210.0, 297.0, 420.0])
def test_different_widths(width_mm: float) -> None:
    """Cartouche must render without error for common page widths."""
    c = _make_cartouche()
    result = render_cartouche_svg(c, width_mm=width_mm)
    assert result.startswith("<g")
    assert "</g>" in result
