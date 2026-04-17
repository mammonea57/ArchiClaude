# ArchiClaude — Phase 7 : Génération rapport HTML/PDF + versionnage — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire le template Jinja2 de rapport de faisabilité (style note d'opportunité architecte), la génération PDF via WeasyPrint, le stockage R2 (stubbed), le module cartouche personnalisable, le versionnage des analyses, les graines architecture/dessin pour les sous-projets 2-3, les DB models (reports, agency_settings), et les endpoints API correspondants.

**Architecture:** Template Jinja2 unique `feasibility.html.j2` avec CSS `@page` pour impression A4. WeasyPrint en worker ARQ génère le PDF. Module `core/reports/cartouche.py` injecte les paramètres agence. Module `core/reports/versioning.py` gère les versions immuables. Tables DB `reports` et `agency_settings`. Graines `core/drawing/conventions.py` et `core/architecture/library.py` pour les sous-projets futurs.

**Tech Stack:** Python 3.12, Jinja2, WeasyPrint, FastAPI (StreamingResponse pour HTML), ARQ, SQLAlchemy 2.0, Alembic, pytest.

**Spec source:** `docs/superpowers/specs/2026-04-16-archiclaude-sous-projet-1-design.md` §8.5 (Rapport), §5.16 (Versionnage), Phase 7 roadmap

---

## File Structure (final état Phase 7)

```
apps/backend/
├── core/
│   ├── reports/
│   │   ├── __init__.py                      (NEW)
│   │   ├── renderer.py                      (NEW — Jinja2 HTML rendering)
│   │   ├── pdf.py                           (NEW — WeasyPrint PDF generation)
│   │   ├── cartouche.py                     (NEW — agency branding injection)
│   │   ├── versioning.py                    (NEW — version management logic)
│   │   └── templates/
│   │       ├── feasibility.html.j2          (NEW — main report template)
│   │       └── styles.css                   (NEW — print + web CSS)
│   ├── drawing/
│   │   ├── __init__.py                      (NEW)
│   │   └── conventions.py                   (NEW — normothèque SVG graine SP3)
│   └── architecture/
│       ├── __init__.py                      (NEW)
│       └── library.py                       (NEW — bibliothèque archi graine SP2)
├── api/
│   └── routes/
│       ├── reports.py                       (NEW — /feasibility/{id}/report.html, .pdf, /reports/{id}/download)
│       ├── versions.py                      (NEW — /projects/{id}/versions)
│       └── agency.py                        (NEW — /agency/settings, /agency/logo)
├── db/
│   └── models/
│       ├── reports.py                       (NEW)
│       └── agency_settings.py               (NEW)
├── schemas/
│   ├── report.py                            (NEW)
│   ├── version.py                           (NEW)
│   └── agency.py                            (NEW)
├── workers/
│   └── pdf.py                               (NEW — ARQ PDF generation worker)
├── alembic/versions/
│   └── 20260418_0003_reports_agency.py      (NEW)
└── tests/
    ├── unit/
    │   ├── test_report_renderer.py          (NEW)
    │   ├── test_report_cartouche.py         (NEW)
    │   ├── test_report_versioning.py        (NEW)
    │   ├── test_drawing_conventions.py      (NEW)
    │   └── test_architecture_library.py     (NEW)
    └── integration/
        ├── test_report_endpoints.py         (NEW)
        ├── test_version_endpoints.py        (NEW)
        └── test_agency_endpoints.py         (NEW)
```

---

## Task 1: Drawing conventions + architecture library (graines SP2/SP3)

**Files:**
- Create: `apps/backend/core/drawing/__init__.py`
- Create: `apps/backend/core/drawing/conventions.py`
- Create: `apps/backend/core/architecture/__init__.py`
- Create: `apps/backend/core/architecture/library.py`
- Test: `apps/backend/tests/unit/test_drawing_conventions.py`
- Test: `apps/backend/tests/unit/test_architecture_library.py`

- [ ] **Step 1: Write tests for drawing conventions**

```python
# apps/backend/tests/unit/test_drawing_conventions.py
"""Tests for SVG drawing conventions — normothèque graine sous-projet 3."""
from core.drawing.conventions import (
    TRAIT_EPAISSEURS, HACHURES, POLICES, SYMBOLES, CARTOUCHE_DEFAULTS,
)


class TestConventions:
    def test_trait_epaisseurs_has_required_types(self):
        assert "mur_porteur" in TRAIT_EPAISSEURS
        assert "cloison" in TRAIT_EPAISSEURS
        assert "contour_parcelle" in TRAIT_EPAISSEURS
        for key, val in TRAIT_EPAISSEURS.items():
            assert isinstance(val, (int, float))
            assert val > 0

    def test_hachures_defined(self):
        assert "beton" in HACHURES
        assert "terrain_naturel" in HACHURES

    def test_polices_defined(self):
        assert "titre" in POLICES
        assert "corps" in POLICES
        assert "cote" in POLICES

    def test_symboles_defined(self):
        assert "nord" in SYMBOLES
        assert "arbre" in SYMBOLES

    def test_cartouche_defaults(self):
        assert "width_mm" in CARTOUCHE_DEFAULTS
        assert "height_mm" in CARTOUCHE_DEFAULTS
```

- [ ] **Step 2: Implement drawing conventions**

```python
# apps/backend/core/drawing/__init__.py
"""Drawing conventions — graine sous-projet 3."""

# apps/backend/core/drawing/conventions.py
"""Normothèque SVG — épaisseurs de trait, hachures, polices, symboles, cartouches.

Conventions normatives pour les plans architecturaux.
Graine pour le sous-projet 3 (génération graphique 2D).
Utilisée en v1 pour le cartouche rapport et les symboles carte.
"""

# Épaisseurs de trait en mm (convention architecturale française)
TRAIT_EPAISSEURS: dict[str, float] = {
    "mur_porteur": 0.50,
    "mur_facade": 0.35,
    "cloison": 0.18,
    "contour_parcelle": 0.70,
    "contour_batiment": 0.50,
    "limite_separative": 0.25,
    "cote": 0.13,
    "axe": 0.13,
    "hachure": 0.09,
    "texte_cadre": 0.25,
}

# Hachures par matériau (pattern SVG IDs)
HACHURES: dict[str, dict[str, str]] = {
    "beton": {"pattern": "diagonal_45", "spacing_mm": 2.0, "color": "#333"},
    "bois": {"pattern": "parallel_30", "spacing_mm": 3.0, "color": "#8B6914"},
    "terrain_naturel": {"pattern": "dots", "spacing_mm": 4.0, "color": "#6B8E23"},
    "isolation": {"pattern": "zigzag", "spacing_mm": 1.5, "color": "#666"},
    "verre": {"pattern": "none", "spacing_mm": 0, "color": "#ADD8E6"},
}

# Polices par usage
POLICES: dict[str, dict[str, str | float]] = {
    "titre": {"family": "Playfair Display", "size_pt": 14, "weight": "bold"},
    "sous_titre": {"family": "Inter", "size_pt": 11, "weight": "semibold"},
    "corps": {"family": "Inter", "size_pt": 9, "weight": "normal"},
    "cote": {"family": "Inter", "size_pt": 7, "weight": "normal"},
    "legende": {"family": "Inter", "size_pt": 8, "weight": "normal"},
}

# Symboles normalisés (SVG path data placeholders)
SYMBOLES: dict[str, str] = {
    "nord": "M 0,-10 L 5,10 L 0,5 L -5,10 Z",  # flèche nord
    "arbre": "M 0,-8 Q 4,-8 4,-4 Q 4,0 0,0 Q -4,0 -4,-4 Q -4,-8 0,-8 Z",
    "porte": "M 0,0 A 5,5 0 0,1 5,5",  # arc de porte
    "escalier": "M 0,0 L 10,0 L 10,2 L 0,2 Z",  # marche
    "ascenseur": "M 0,0 L 8,0 L 8,8 L 0,8 Z M 1,1 L 7,1 L 7,7 L 1,7 Z",
    "parking": "P",
}

# Cartouche par défaut (dimensions en mm)
CARTOUCHE_DEFAULTS: dict[str, float | str] = {
    "width_mm": 180.0,
    "height_mm": 40.0,
    "margin_mm": 5.0,
    "border_width_mm": 0.5,
    "font_title": "Playfair Display",
    "font_body": "Inter",
}
```

- [ ] **Step 3: Write tests + implement architecture library**

```python
# apps/backend/tests/unit/test_architecture_library.py
"""Tests for architecture library — graine sous-projet 2."""
from core.architecture.library import (
    TRAMES_BA, EPAISSEURS_MUR, CIRCULATIONS, ASCENSEURS,
)


class TestLibrary:
    def test_trames_ba(self):
        assert "5.40" in TRAMES_BA or 5.40 in [t["portee_m"] for t in TRAMES_BA]

    def test_epaisseurs_mur(self):
        assert "porteur_beton" in EPAISSEURS_MUR
        assert EPAISSEURS_MUR["porteur_beton"] >= 0.15

    def test_circulations(self):
        assert "couloir_min_m" in CIRCULATIONS
        assert CIRCULATIONS["couloir_min_m"] >= 1.20

    def test_ascenseurs(self):
        assert "gaine_min_m2" in ASCENSEURS
```

```python
# apps/backend/core/architecture/__init__.py
"""Architecture library — graine sous-projet 2."""

# apps/backend/core/architecture/library.py
"""Bibliothèque architecture — trames BA, épaisseurs, circulations, ascenseurs.

Valeurs de référence pour la programmation architecturale.
Graine pour le sous-projet 2 (programmation + volumes conformes).
Utilisée en v1 pour le raffinement des coefficients SDP utile.
"""

# Trames béton armé courantes (portées en mètres)
TRAMES_BA: list[dict[str, float | str]] = [
    {"portee_m": 5.40, "usage": "logement_collectif", "description": "Trame standard logement"},
    {"portee_m": 6.00, "usage": "logement_collectif", "description": "Trame confort logement"},
    {"portee_m": 7.50, "usage": "bureaux", "description": "Trame bureaux standard"},
    {"portee_m": 8.10, "usage": "bureaux", "description": "Trame bureaux large"},
    {"portee_m": 5.00, "usage": "parking", "description": "Trame parking souterrain"},
]

# Épaisseurs murs en mètres
EPAISSEURS_MUR: dict[str, float] = {
    "porteur_beton": 0.20,
    "porteur_beton_isole": 0.35,  # avec isolation par l'intérieur
    "facade_ite": 0.38,  # isolation thermique extérieure
    "cloison_simple": 0.07,
    "cloison_double": 0.10,
    "separation_logements": 0.18,  # acoustique
    "refend": 0.18,
}

# Dimensions circulations réglementaires (mètres)
CIRCULATIONS: dict[str, float] = {
    "couloir_min_m": 1.20,  # PMR
    "couloir_confort_m": 1.40,
    "escalier_largeur_min_m": 1.00,  # habitation 3ème famille
    "escalier_largeur_2cages_m": 0.80,  # par cage si 2 cages
    "palier_profondeur_min_m": 1.40,  # PMR
    "porte_entree_min_m": 0.90,  # PMR
    "porte_interieure_min_m": 0.80,
}

# Ascenseurs
ASCENSEURS: dict[str, float] = {
    "gaine_min_m2": 4.0,  # gaine + machinerie
    "cabine_pmr_largeur_m": 1.10,
    "cabine_pmr_profondeur_m": 1.40,
    "palier_appel_profondeur_m": 1.50,  # PMR
}
```

- [ ] **Step 4: Run tests, commit**

```bash
git add apps/backend/core/drawing/ apps/backend/core/architecture/ apps/backend/tests/unit/test_drawing_conventions.py apps/backend/tests/unit/test_architecture_library.py
git commit -m "feat: add drawing conventions and architecture library (seeds for SP2/SP3)"
```

---

## Task 2: Report renderer — Jinja2 HTML template + CSS

**Files:**
- Create: `apps/backend/core/reports/__init__.py`
- Create: `apps/backend/core/reports/renderer.py`
- Create: `apps/backend/core/reports/templates/feasibility.html.j2`
- Create: `apps/backend/core/reports/templates/styles.css`
- Test: `apps/backend/tests/unit/test_report_renderer.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_report_renderer.py
"""Tests for Jinja2 report renderer."""
import pytest
from core.reports.renderer import render_feasibility_html


class TestRenderFeasibilityHtml:
    def test_renders_html(self):
        html = render_feasibility_html(
            project_name="Test Vincennes R+5",
            commune="Vincennes",
            zone_code="UB",
            surface_terrain_m2=1250.0,
            sdp_max_m2=3200.0,
            nb_niveaux=5,
            nb_logements=28,
            nb_par_typologie={"T2": 8, "T3": 12, "T4": 8},
            hauteur_retenue_m=15.0,
            surface_emprise_m2=640.0,
            analyse_architecte_md="## Synthèse\nProjet faisable.",
            alertes=[],
            compliance={"incendie_classement": "3A", "pmr_ascenseur_obligatoire": True},
        )
        assert "<!DOCTYPE html>" in html
        assert "Test Vincennes R+5" in html
        assert "3200" in html  # SDP
        assert "28" in html  # logements
        assert "Synthèse" in html  # analyse architecte

    def test_renders_with_alerts(self):
        html = render_feasibility_html(
            project_name="Test ABF",
            commune="Nogent",
            zone_code="UA",
            surface_terrain_m2=800.0,
            sdp_max_m2=1500.0,
            nb_niveaux=4,
            nb_logements=15,
            nb_par_typologie={"T3": 15},
            hauteur_retenue_m=12.0,
            surface_emprise_m2=375.0,
            analyse_architecte_md="## Synthèse\nAttention ABF.",
            alertes=[{"level": "warning", "type": "abf", "message": "ABF obligatoire"}],
        )
        assert "ABF" in html

    def test_renders_with_cartouche(self):
        html = render_feasibility_html(
            project_name="Test",
            commune="Paris",
            zone_code="UG",
            surface_terrain_m2=500.0,
            sdp_max_m2=1000.0,
            nb_niveaux=3,
            nb_logements=10,
            nb_par_typologie={"T2": 10},
            hauteur_retenue_m=10.0,
            surface_emprise_m2=333.0,
            analyse_architecte_md="",
            cartouche={"agency_name": "Cabinet Archi Test", "contact_email": "archi@test.fr"},
        )
        assert "Cabinet Archi Test" in html
```

- [ ] **Step 2: Create HTML template**

```jinja2
{# apps/backend/core/reports/templates/feasibility.html.j2 #}
<!DOCTYPE html>
<html lang="fr">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ project_name }} — Rapport de faisabilité</title>
    <link rel="stylesheet" href="styles.css">
    <style>
        {# Inline critical CSS for PDF generation #}
        @page { size: A4; margin: 20mm 15mm 25mm 15mm; }
        @page :first { margin-top: 0; }
        body { font-family: 'Inter', sans-serif; color: #1a1a1a; line-height: 1.5; }
        h1, h2, h3 { font-family: 'Playfair Display', serif; }
        .page-break { page-break-before: always; }
        .cartouche { position: running(cartouche); font-size: 8pt; border-top: 1px solid #ccc; padding-top: 4mm; }
        @page { @bottom-center { content: element(cartouche); } }
        @page { @bottom-right { content: counter(page) " / " counter(pages); font-size: 8pt; } }
        .cover { height: 100vh; display: flex; flex-direction: column; justify-content: center; }
        .kpi-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
        .kpi-card { border: 1px solid #e0e0e0; border-radius: 8px; padding: 16px; text-align: center; }
        .kpi-value { font-size: 2em; font-weight: bold; color: #0d9488; }
        .kpi-label { font-size: 0.85em; color: #666; }
        .alert-critical { background: #fef2f2; border-left: 4px solid #dc2626; padding: 12px; margin: 8px 0; }
        .alert-warning { background: #fffbeb; border-left: 4px solid #f59e0b; padding: 12px; margin: 8px 0; }
        .alert-info { background: #eff6ff; border-left: 4px solid #3b82f6; padding: 12px; margin: 8px 0; }
        table { width: 100%; border-collapse: collapse; margin: 16px 0; }
        th, td { border: 1px solid #e0e0e0; padding: 8px; text-align: left; }
        th { background: #f8f9fa; font-weight: 600; }
        .analyse-architecte h2 { color: #0d9488; border-bottom: 2px solid #0d9488; padding-bottom: 4px; }
    </style>
</head>
<body>

{# === PAGE DE COUVERTURE === #}
<div class="cover">
    <h1>{{ project_name }}</h1>
    <p class="subtitle">Rapport de faisabilité — {{ commune }} — Zone {{ zone_code }}</p>
    <p class="date">{{ generated_date | default("", true) }}</p>
    {% if cartouche %}
    <div class="cover-cartouche">
        <p><strong>{{ cartouche.agency_name | default("") }}</strong></p>
        <p>{{ cartouche.contact_email | default("") }}</p>
    </div>
    {% endif %}
</div>

{# === SOMMAIRE === #}
<div class="page-break">
    <h2>Sommaire</h2>
    <ol>
        <li>Données du terrain</li>
        <li>Règles PLU applicables</li>
        <li>Capacité constructible</li>
        <li>Compliance réglementaire</li>
        <li>Alertes et servitudes</li>
        <li>Analyse architecte</li>
        <li>Annexes</li>
    </ol>
</div>

{# === 1. DONNÉES DU TERRAIN === #}
<div class="page-break">
    <h2>1. Données du terrain</h2>
    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-value">{{ "%.0f" | format(surface_terrain_m2) }} m²</div>
            <div class="kpi-label">Surface terrain</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-value">{{ zone_code }}</div>
            <div class="kpi-label">Zone PLU</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-value">{{ commune }}</div>
            <div class="kpi-label">Commune</div>
        </div>
    </div>
</div>

{# === 3. CAPACITÉ CONSTRUCTIBLE === #}
<div class="page-break">
    <h2>3. Capacité constructible</h2>
    <div class="kpi-grid">
        <div class="kpi-card">
            <div class="kpi-value">{{ "%.0f" | format(sdp_max_m2) }} m²</div>
            <div class="kpi-label">SDP maximale</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-value">R+{{ nb_niveaux - 1 }}</div>
            <div class="kpi-label">Hauteur retenue ({{ "%.1f" | format(hauteur_retenue_m) }}m)</div>
        </div>
        <div class="kpi-card">
            <div class="kpi-value">{{ nb_logements }}</div>
            <div class="kpi-label">Logements max</div>
        </div>
    </div>

    <h3>Répartition typologique</h3>
    <table>
        <thead><tr><th>Typologie</th><th>Nombre</th></tr></thead>
        <tbody>
        {% for typo, nb in nb_par_typologie.items() %}
            <tr><td>{{ typo }}</td><td>{{ nb }}</td></tr>
        {% endfor %}
        </tbody>
    </table>

    <h3>Emprise au sol</h3>
    <p>{{ "%.0f" | format(surface_emprise_m2) }} m² ({{ "%.0f" | format(surface_emprise_m2 / surface_terrain_m2 * 100) }}% du terrain)</p>
</div>

{# === 4. COMPLIANCE === #}
{% if compliance %}
<div class="page-break">
    <h2>4. Compliance réglementaire</h2>
    <table>
        <tr><td>Classement incendie</td><td>{{ compliance.incendie_classement | default("N/A") }}</td></tr>
        <tr><td>Ascenseur PMR</td><td>{{ "Obligatoire" if compliance.pmr_ascenseur_obligatoire else "Non requis" }}</td></tr>
    </table>
</div>
{% endif %}

{# === 5. ALERTES === #}
{% if alertes %}
<div class="page-break">
    <h2>5. Alertes et servitudes</h2>
    {% for alerte in alertes %}
    <div class="alert-{{ alerte.level | default('info') }}">
        <strong>{{ alerte.type | default('') | upper }}</strong> — {{ alerte.message | default('') }}
    </div>
    {% endfor %}
</div>
{% endif %}

{# === 6. ANALYSE ARCHITECTE === #}
{% if analyse_architecte_md %}
<div class="page-break analyse-architecte">
    <h2>6. Analyse architecte</h2>
    {{ analyse_architecte_md | safe }}
</div>
{% endif %}

{# === CARTOUCHE PIED DE PAGE === #}
{% if cartouche %}
<div class="cartouche">
    {{ cartouche.agency_name | default("ArchiClaude") }} — {{ cartouche.contact_email | default("") }}
</div>
{% endif %}

</body>
</html>
```

- [ ] **Step 3: Implement renderer**

```python
# apps/backend/core/reports/__init__.py
"""Report generation modules for ArchiClaude."""

# apps/backend/core/reports/renderer.py
"""Jinja2 HTML report renderer for feasibility reports."""
from __future__ import annotations
import markdown
from datetime import datetime
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)


def render_feasibility_html(
    *,
    project_name: str,
    commune: str,
    zone_code: str,
    surface_terrain_m2: float,
    sdp_max_m2: float,
    nb_niveaux: int,
    nb_logements: int,
    nb_par_typologie: dict[str, int],
    hauteur_retenue_m: float,
    surface_emprise_m2: float,
    analyse_architecte_md: str = "",
    alertes: list[dict] | None = None,
    compliance: dict | None = None,
    cartouche: dict | None = None,
    generated_date: str | None = None,
) -> str:
    """Render the feasibility report as HTML string."""
    if generated_date is None:
        generated_date = datetime.now().strftime("%d/%m/%Y")

    # Convert markdown analysis to HTML
    analyse_html = ""
    if analyse_architecte_md:
        analyse_html = markdown.markdown(analyse_architecte_md, extensions=["extra"])

    template = _env.get_template("feasibility.html.j2")
    return template.render(
        project_name=project_name,
        commune=commune,
        zone_code=zone_code,
        surface_terrain_m2=surface_terrain_m2,
        sdp_max_m2=sdp_max_m2,
        nb_niveaux=nb_niveaux,
        nb_logements=nb_logements,
        nb_par_typologie=nb_par_typologie,
        hauteur_retenue_m=hauteur_retenue_m,
        surface_emprise_m2=surface_emprise_m2,
        analyse_architecte_md=analyse_html,
        alertes=alertes or [],
        compliance=compliance,
        cartouche=cartouche,
        generated_date=generated_date,
    )
```

- [ ] **Step 4: Run tests, commit**

NOTE: Add `"markdown>=3.5"` to pyproject.toml dependencies.

```bash
git add apps/backend/core/reports/ apps/backend/tests/unit/test_report_renderer.py apps/backend/pyproject.toml
git commit -m "feat(reports): add Jinja2 HTML report renderer with A4 print CSS"
```

---

## Task 3: Cartouche personnalisable + PDF generation

**Files:**
- Create: `apps/backend/core/reports/cartouche.py`
- Create: `apps/backend/core/reports/pdf.py`
- Test: `apps/backend/tests/unit/test_report_cartouche.py`

- [ ] **Step 1: Write tests + implement cartouche**

```python
# apps/backend/tests/unit/test_report_cartouche.py
"""Tests for agency cartouche injection."""
from core.reports.cartouche import build_cartouche


class TestBuildCartouche:
    def test_with_full_settings(self):
        c = build_cartouche(
            agency_name="Cabinet Dupont",
            contact_email="contact@dupont-archi.fr",
            contact_phone="01 42 00 00 00",
            archi_ordre_number="S12345",
            brand_primary_color="#0d9488",
        )
        assert c["agency_name"] == "Cabinet Dupont"
        assert c["contact_email"] == "contact@dupont-archi.fr"

    def test_with_minimal_settings(self):
        c = build_cartouche()
        assert c["agency_name"] == "ArchiClaude"

    def test_with_logo_url(self):
        c = build_cartouche(agency_name="Test", logo_url="https://r2.example.com/logo.png")
        assert c["logo_url"] == "https://r2.example.com/logo.png"
```

```python
# apps/backend/core/reports/cartouche.py
"""Agency branding cartouche for reports."""


def build_cartouche(
    *,
    agency_name: str = "ArchiClaude",
    logo_url: str | None = None,
    address: str | None = None,
    contact_email: str | None = None,
    contact_phone: str | None = None,
    archi_ordre_number: str | None = None,
    default_footer: str | None = None,
    brand_primary_color: str = "#0d9488",
) -> dict:
    """Build cartouche dict for template injection."""
    return {
        "agency_name": agency_name,
        "logo_url": logo_url,
        "address": address,
        "contact_email": contact_email,
        "contact_phone": contact_phone,
        "archi_ordre_number": archi_ordre_number,
        "default_footer": default_footer or f"Rapport généré par {agency_name}",
        "brand_primary_color": brand_primary_color,
    }
```

- [ ] **Step 2: Implement PDF generation module**

```python
# apps/backend/core/reports/pdf.py
"""PDF generation via WeasyPrint."""
from __future__ import annotations
import logging

logger = logging.getLogger(__name__)


def generate_pdf_from_html(html: str) -> bytes:
    """Convert HTML string to PDF bytes via WeasyPrint."""
    from weasyprint import HTML
    doc = HTML(string=html)
    return doc.write_pdf()
```

- [ ] **Step 3: Commit**

```bash
git add apps/backend/core/reports/cartouche.py apps/backend/core/reports/pdf.py apps/backend/tests/unit/test_report_cartouche.py
git commit -m "feat(reports): add cartouche branding + WeasyPrint PDF generation"
```

---

## Task 4: Versioning module

**Files:**
- Create: `apps/backend/core/reports/versioning.py`
- Test: `apps/backend/tests/unit/test_report_versioning.py`

- [ ] **Step 1: Write tests + implement versioning**

```python
# apps/backend/tests/unit/test_report_versioning.py
"""Tests for report versioning logic."""
from core.reports.versioning import compute_next_version, build_version_diff


class TestComputeNextVersion:
    def test_first_version(self):
        assert compute_next_version(existing_versions=[]) == 1

    def test_increment(self):
        assert compute_next_version(existing_versions=[1, 2, 3]) == 4

    def test_gap_fills_next(self):
        assert compute_next_version(existing_versions=[1, 3]) == 4


class TestBuildVersionDiff:
    def test_sdp_change(self):
        diff = build_version_diff(
            v_old={"sdp_max_m2": 2000, "nb_logements_max": 25},
            v_new={"sdp_max_m2": 2200, "nb_logements_max": 28},
        )
        assert "sdp_max_m2" in diff
        assert diff["sdp_max_m2"]["old"] == 2000
        assert diff["sdp_max_m2"]["new"] == 2200

    def test_no_changes(self):
        diff = build_version_diff(
            v_old={"sdp_max_m2": 2000},
            v_new={"sdp_max_m2": 2000},
        )
        assert diff == {}

    def test_new_field(self):
        diff = build_version_diff(
            v_old={},
            v_new={"sdp_max_m2": 2000},
        )
        assert "sdp_max_m2" in diff
```

```python
# apps/backend/core/reports/versioning.py
"""Project version management — immutable snapshots with diff."""


def compute_next_version(existing_versions: list[int]) -> int:
    """Compute the next version number."""
    if not existing_versions:
        return 1
    return max(existing_versions) + 1


def build_version_diff(*, v_old: dict, v_new: dict) -> dict:
    """Build a diff between two version snapshots. Only includes changed fields."""
    diff = {}
    all_keys = set(v_old.keys()) | set(v_new.keys())
    for key in sorted(all_keys):
        old_val = v_old.get(key)
        new_val = v_new.get(key)
        if old_val != new_val:
            diff[key] = {"old": old_val, "new": new_val}
    return diff
```

- [ ] **Step 2: Commit**

```bash
git add apps/backend/core/reports/versioning.py apps/backend/tests/unit/test_report_versioning.py
git commit -m "feat(reports): add version management with immutable snapshots and diff"
```

---

## Task 5: DB models (reports, agency_settings) + migration

**Files:**
- Create: `apps/backend/db/models/reports.py`
- Create: `apps/backend/db/models/agency_settings.py`
- Create: `apps/backend/alembic/versions/20260418_0003_reports_agency.py`

- [ ] **Step 1: Create DB models**

```python
# apps/backend/db/models/reports.py
import uuid
from sqlalchemy import Column, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from db.base import Base

class ReportRow(Base):
    __tablename__ = "reports"
    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    feasibility_result_id = Column(PgUUID(as_uuid=True), ForeignKey("feasibility_results.id", ondelete="CASCADE"), nullable=False)
    format = Column(Text, nullable=False)  # html, pdf
    r2_key = Column(Text, nullable=True)
    sha256 = Column(String(64), nullable=True)
    size_bytes = Column(Integer, nullable=True)
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
```

```python
# apps/backend/db/models/agency_settings.py
import uuid
from sqlalchemy import Column, DateTime, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from db.base import Base

class AgencySettingsRow(Base):
    __tablename__ = "agency_settings"
    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    agency_name = Column(Text, nullable=True)
    logo_r2_key = Column(Text, nullable=True)
    address = Column(Text, nullable=True)
    contact_email = Column(Text, nullable=True)
    contact_phone = Column(Text, nullable=True)
    archi_ordre_number = Column(Text, nullable=True)
    default_cartouche_footer = Column(Text, nullable=True)
    brand_primary_color = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 2: Migration + update alembic/env.py**

- [ ] **Step 3: Commit**

```bash
git add apps/backend/db/models/reports.py apps/backend/db/models/agency_settings.py apps/backend/alembic/
git commit -m "feat(db): add reports and agency_settings tables"
```

---

## Task 6: API endpoints — reports, versions, agency

**Files:**
- Create: `apps/backend/api/routes/reports.py`
- Create: `apps/backend/api/routes/versions.py`
- Create: `apps/backend/api/routes/agency.py`
- Create: `apps/backend/schemas/report.py`
- Create: `apps/backend/schemas/version.py`
- Create: `apps/backend/schemas/agency.py`
- Create: `apps/backend/workers/pdf.py`
- Modify: `apps/backend/api/main.py`
- Test: `apps/backend/tests/integration/test_report_endpoints.py`
- Test: `apps/backend/tests/integration/test_version_endpoints.py`
- Test: `apps/backend/tests/integration/test_agency_endpoints.py`

- [ ] **Step 1: Create Pydantic schemas**

```python
# schemas/report.py
class ReportGenerateResponse(BaseModel):
    job_id: str; status: str

class ReportDownloadResponse(BaseModel):
    url: str

# schemas/version.py
class VersionCreate(BaseModel):
    label: str | None = None; notes: str | None = None

class VersionOut(BaseModel):
    id: str; version_number: int; version_label: str | None
    created_at: str

class VersionCompareResponse(BaseModel):
    diff: dict

# schemas/agency.py
class AgencySettingsUpdate(BaseModel):
    agency_name: str | None = None; address: str | None = None
    contact_email: str | None = None; contact_phone: str | None = None
    archi_ordre_number: str | None = None; brand_primary_color: str | None = None

class AgencySettingsOut(BaseModel):
    agency_name: str | None; logo_url: str | None; contact_email: str | None
    brand_primary_color: str | None
```

- [ ] **Step 2: Create API routes**

```python
# api/routes/reports.py
GET /feasibility/{result_id}/report.html  → StreamingResponse HTML
POST /feasibility/{result_id}/report.pdf  → 202 {job_id}
GET /reports/{report_id}/download         → {url} (placeholder)

# api/routes/versions.py
POST /projects/{id}/versions             → 201 VersionOut
GET  /projects/{id}/versions             → [VersionOut]
GET  /projects/{id}/versions/compare?a=&b= → VersionCompareResponse

# api/routes/agency.py
GET  /agency/settings                    → AgencySettingsOut
PUT  /agency/settings                    → AgencySettingsOut
POST /agency/logo                        → {logo_url} (placeholder)
```

- [ ] **Step 3: Create PDF worker**

```python
# workers/pdf.py
async def generate_pdf_job(ctx, *, result_id: str, html: str):
    from core.reports.pdf import generate_pdf_from_html
    pdf_bytes = generate_pdf_from_html(html)
    # TODO: upload to R2, store in reports table
    return {"status": "done", "size_bytes": len(pdf_bytes)}
```

- [ ] **Step 4: Register all routers in main.py**

- [ ] **Step 5: Write integration tests**

- [ ] **Step 6: Commit**

```bash
git add apps/backend/api/routes/reports.py apps/backend/api/routes/versions.py apps/backend/api/routes/agency.py apps/backend/schemas/ apps/backend/workers/pdf.py apps/backend/api/main.py apps/backend/tests/integration/
git commit -m "feat(api): add report/version/agency endpoints + PDF worker"
```

---

## Task 7: Vérification finale

- [ ] **Step 1: Run ruff**
- [ ] **Step 2: Run full test suite**
- [ ] **Step 3: Fix issues + commit cleanup**
