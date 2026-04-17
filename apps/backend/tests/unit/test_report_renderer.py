"""Unit tests for core.reports.renderer — Jinja2 HTML feasibility report."""

from __future__ import annotations

import pytest

from core.reports.renderer import render_feasibility_html

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_BASE_KWARGS = {
    "project_name": "Résidence les Acacias",
    "commune": "Vincennes",
    "zone": "UA",
    "date": "2026-04-17",
    "surface_parcelle_m2": 800.0,
    "sdp_brute_m2": 2400.0,
    "niveaux": 4,
    "nb_logements": 32,
    "emprise_sol_m2": 480.0,
    "compliance_incendie": {"statut": "conforme", "details": "Accès pompiers OK"},
    "compliance_pmr": {"statut": "conforme", "details": "Rampe d'accès prévue"},
    "alertes": [],
    "analyse_architecte_md": "## Synthèse\nProjet faisable sous réserve de validation PLU.",
    "cartouche": {
        "agency_name": "ArchiClaude",
        "brand_primary_color": "#0d9488",
    },
    "typologies": [
        {"type": "T2", "nb": 12, "surface_m2": 45.0},
        {"type": "T3", "nb": 14, "surface_m2": 65.0},
        {"type": "T4", "nb": 6, "surface_m2": 82.0},
    ],
}


def test_renders_html() -> None:
    html = render_feasibility_html(**_BASE_KWARGS)
    assert "<!DOCTYPE html>" in html
    assert "Résidence les Acacias" in html
    assert "2 400" in html or "2400" in html  # SDP — formatted or raw
    assert "32" in html  # logements
    assert "Synthèse" in html  # from analyse_architecte_md markdown


def test_renders_with_alerts() -> None:
    kwargs = {
        **_BASE_KWARGS,
        "alertes": [
            {"niveau": "critical", "code": "ABF", "message": "Périmètre ABF — avis obligatoire"},
            {"niveau": "warning", "code": "PLU_HAUTEUR", "message": "Hauteur max 12m atteinte"},
        ],
    }
    html = render_feasibility_html(**kwargs)
    assert "ABF" in html
    assert "PLU_HAUTEUR" in html


def test_renders_with_cartouche() -> None:
    kwargs = {
        **_BASE_KWARGS,
        "cartouche": {
            "agency_name": "Cabinet Dupont Architectes",
            "brand_primary_color": "#1a2b3c",
            "logo_url": "https://example.com/logo.png",
        },
    }
    html = render_feasibility_html(**kwargs)
    assert "Cabinet Dupont Architectes" in html


def test_renders_html_structure() -> None:
    html = render_feasibility_html(**_BASE_KWARGS)
    assert "<html" in html
    assert "</html>" in html
    assert "<body" in html or "<body>" in html


def test_renders_markdown_to_html() -> None:
    kwargs = {
        **_BASE_KWARGS,
        "analyse_architecte_md": "## Synthèse\n\nProjet **faisable**.",
    }
    html = render_feasibility_html(**kwargs)
    # markdown should be converted: ## → <h2>, **bold** → <strong>
    assert "<h2>" in html or "<h2 " in html
    assert "<strong>" in html


def test_renders_commune_and_zone() -> None:
    html = render_feasibility_html(**_BASE_KWARGS)
    assert "Vincennes" in html
    assert "UA" in html


def test_renders_typologies_table() -> None:
    html = render_feasibility_html(**_BASE_KWARGS)
    assert "T2" in html
    assert "T3" in html
    assert "T4" in html
