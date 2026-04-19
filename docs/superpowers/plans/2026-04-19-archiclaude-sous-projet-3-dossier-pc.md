# ArchiClaude — Sous-projet 3 : Dossier PC complet (PCMI) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire le générateur de dossier PC complet (PCMI1-8 sauf 6) : plan de situation IGN, notice architecturale R.431-8, façades 4 côtés, photos d'environnement, cartouche PC normé ArchiClaude, export PDF unique + ZIP séparé via reportlab/WeasyPrint.

**Architecture:** Nouveau package `core/pcmi/` orchestrant les pièces graphiques/textuelles, réutilisant les modules SP1 (Opus, photos, compliance) et SP2 (plans SVG). Nouveau renderer reportlab pour PDF pro format ISO. Assembleur pypdf pour PDF unique + zipfile pour ZIP Plat'AU. Worker ARQ async. Table DB `pcmi_dossiers` avec auto-incrément indice révision.

**Tech Stack:** Python 3.12, reportlab (PDF plans), svglib (SVG→reportlab), WeasyPrint (notice), pypdf (merge), Pillow (photos), httpx (IGN WMTS), anthropic SDK (Opus adaptatif), SQLAlchemy 2.0, Alembic, FastAPI, ARQ.

**Spec source:** `docs/superpowers/specs/2026-04-19-archiclaude-sous-projet-3-dossier-pc-complet.md`

---

## File Structure

```
apps/backend/
├── core/pcmi/
│   ├── __init__.py                           (NEW)
│   ├── schemas.py                            (NEW)
│   ├── situation.py                          (NEW — PCMI1 IGN)
│   ├── facades.py                            (NEW — PCMI5 4 façades)
│   ├── photos.py                             (NEW — PCMI7/8)
│   ├── notice_pcmi4.py                       (NEW — R.431-8 adapter)
│   ├── cartouche_pc.py                       (NEW — cartouche + signature)
│   └── assembler.py                          (NEW — PDF unique + ZIP)
├── core/programming/plans/
│   └── renderer_pdf.py                       (NEW — reportlab)
├── core/pcmi/templates/
│   └── notice_pcmi4.html.j2                  (NEW — WeasyPrint template)
├── core/analysis/
│   └── architect_analysis.py                 (MODIFY — 2 formats)
├── core/analysis/architect_prompt.py         (MODIFY — prompt enrichi)
├── api/routes/
│   └── pcmi.py                               (NEW)
├── schemas/
│   └── pcmi.py                               (NEW API schemas)
├── workers/
│   └── pcmi.py                               (NEW ARQ worker)
├── db/models/
│   └── pcmi_dossiers.py                      (NEW)
├── alembic/versions/
│   └── 20260419_0001_pcmi_dossiers.py        (NEW)
└── tests/unit/
    ├── test_pcmi_schemas.py
    ├── test_pcmi_situation.py
    ├── test_pcmi_facades.py
    ├── test_pcmi_photos.py
    ├── test_pcmi_notice.py
    ├── test_pcmi_cartouche.py
    ├── test_pcmi_assembler.py
    └── test_renderer_pdf.py

apps/frontend/src/
├── app/projects/[id]/pcmi/page.tsx           (NEW)
└── components/pcmi/
    ├── PcmiGenerator.tsx                     (NEW)
    ├── PcmiPreview.tsx                       (NEW)
    ├── PcmiDownloadButtons.tsx               (NEW)
    ├── SituationMapSelector.tsx              (NEW)
    └── RevisionHistory.tsx                   (NEW)
```

---

## Task 1: Schemas PCMI + dépendances

**Files:**
- Create: `apps/backend/core/pcmi/__init__.py`
- Create: `apps/backend/core/pcmi/schemas.py`
- Modify: `apps/backend/pyproject.toml` (add reportlab, svglib, Pillow)

- [ ] **Step 1: Add new dependencies to pyproject.toml**

Add to `[project.dependencies]`:
```
"reportlab>=4.0",
"svglib>=1.5",
"Pillow>=10.0",
```

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && pip install -e ".[dev]"`

- [ ] **Step 2: Implement schemas.py**

```python
# apps/backend/core/pcmi/__init__.py
"""Dossier PC complet — PCMI generation."""

# apps/backend/core/pcmi/schemas.py
"""Schemas for PCMI dossier generation."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal


@dataclass
class CartouchePC:
    """PC cartouche with ArchiClaude signature."""
    nom_projet: str
    adresse: str
    parcelles_refs: list[str]  # ["94052-AB-0042", ...]
    petitionnaire_nom: str
    petitionnaire_contact: str
    architecte_nom: str | None = None
    architecte_ordre: str | None = None
    architecte_contact: str | None = None
    piece_num: str = ""  # "PCMI2"
    piece_titre: str = ""  # "Plan de masse"
    echelle: str = ""  # "1/500"
    date: str = ""  # JJ/MM/AAAA
    indice: str = "A"  # A, B, C...
    logo_agence_url: str | None = None


@dataclass
class PcmiPiece:
    """One piece of the PCMI dossier."""
    code: str  # PCMI1, PCMI2a, PCMI2b, PCMI3, PCMI4, PCMI5, PCMI7, PCMI8
    titre: str
    svg_content: str | None = None  # for graphic pieces
    pdf_bytes: bytes | None = None
    html_content: str | None = None  # for notice PCMI4
    error: str | None = None


@dataclass
class PcmiDossier:
    """Complete PCMI dossier."""
    project_id: str
    indice_revision: str  # A, B, C...
    pieces: list[PcmiPiece]
    pdf_unique_bytes: bytes | None = None
    zip_bytes: bytes | None = None
    cartouche: CartouchePC | None = None
    map_base: Literal["scan25", "planv2"] = "scan25"
    generated_at: datetime = field(default_factory=datetime.utcnow)
    status: Literal["queued", "generating", "done", "failed"] = "queued"
    error_msg: str | None = None


# Constants
PCMI_ORDER = ["PCMI1", "PCMI2a", "PCMI2b", "PCMI3", "PCMI4", "PCMI5", "PCMI7", "PCMI8"]

PCMI_TITRES = {
    "PCMI1": "Plan de situation",
    "PCMI2a": "Plan de masse",
    "PCMI2b": "Plans de niveaux",
    "PCMI3": "Plan en coupe",
    "PCMI4": "Notice architecturale",
    "PCMI5": "Plans des façades",
    "PCMI7": "Photographie environnement proche",
    "PCMI8": "Photographie environnement lointain",
}

PCMI_FORMATS = {
    "PCMI1": ("A4", "portrait"),
    "PCMI2a": ("A3", "landscape"),
    "PCMI2b": ("A1", "landscape"),
    "PCMI3": ("A3", "landscape"),
    "PCMI4": ("A4", "portrait"),
    "PCMI5": ("A3", "landscape"),
    "PCMI7": ("A4", "landscape"),
    "PCMI8": ("A4", "landscape"),
}
```

- [ ] **Step 3: Write and run tests**

```python
# apps/backend/tests/unit/test_pcmi_schemas.py
from core.pcmi.schemas import CartouchePC, PcmiPiece, PcmiDossier, PCMI_ORDER, PCMI_TITRES, PCMI_FORMATS


def test_cartouche_minimal():
    c = CartouchePC(
        nom_projet="Test", adresse="12 rue Test",
        parcelles_refs=["94052-AB-0042"],
        petitionnaire_nom="Jean Dupont",
        petitionnaire_contact="jean@test.fr",
    )
    assert c.indice == "A"
    assert c.architecte_nom is None


def test_pcmi_order_has_8_pieces():
    assert len(PCMI_ORDER) == 8  # 1, 2a, 2b, 3, 4, 5, 7, 8 (6 skipped)
    assert "PCMI6" not in PCMI_ORDER


def test_pcmi_formats_complete():
    for code in PCMI_ORDER:
        assert code in PCMI_FORMATS
        fmt, orient = PCMI_FORMATS[code]
        assert fmt in ("A1", "A3", "A4")
        assert orient in ("portrait", "landscape")


def test_pcmi_titres_complete():
    for code in PCMI_ORDER:
        assert code in PCMI_TITRES
        assert PCMI_TITRES[code]
```

- [ ] **Step 4: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/core/pcmi/ apps/backend/tests/unit/test_pcmi_schemas.py apps/backend/pyproject.toml
git commit -m "feat(pcmi): add schemas and constants for PCMI dossier"
```

---

## Task 2: Cartouche PC normé ArchiClaude

**Files:**
- Create: `apps/backend/core/pcmi/cartouche_pc.py`
- Test: `apps/backend/tests/unit/test_pcmi_cartouche.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_pcmi_cartouche.py
from core.pcmi.cartouche_pc import render_cartouche_svg
from core.pcmi.schemas import CartouchePC


def _sample_cartouche(**kwargs) -> CartouchePC:
    defaults = {
        "nom_projet": "Résidence Les Tilleuls",
        "adresse": "12 rue de la Paix, 94130 Nogent-sur-Marne",
        "parcelles_refs": ["94052-AB-0042", "94052-AB-0043"],
        "petitionnaire_nom": "SAS Promoteur",
        "petitionnaire_contact": "contact@promoteur.fr",
        "architecte_nom": "Jean Dupont",
        "architecte_ordre": "S12345",
        "architecte_contact": "archi@cabinet.fr",
        "piece_num": "PCMI2",
        "piece_titre": "Plan de masse",
        "echelle": "1/500",
        "date": "19/04/2026",
        "indice": "A",
    }
    defaults.update(kwargs)
    return CartouchePC(**defaults)


def test_renders_svg():
    c = _sample_cartouche()
    svg = render_cartouche_svg(c, width_mm=297)
    assert svg.startswith("<g")
    assert "Résidence Les Tilleuls" in svg
    assert "PCMI2" in svg


def test_contains_archiclaude_signature():
    c = _sample_cartouche()
    svg = render_cartouche_svg(c, width_mm=297)
    assert "ArchiClaude" in svg
    assert "archiclaude.app" in svg


def test_contains_petitionnaire():
    c = _sample_cartouche()
    svg = render_cartouche_svg(c, width_mm=297)
    assert "SAS Promoteur" in svg


def test_contains_architecte():
    c = _sample_cartouche()
    svg = render_cartouche_svg(c, width_mm=297)
    assert "Jean Dupont" in svg
    assert "S12345" in svg


def test_without_architecte():
    c = _sample_cartouche(architecte_nom=None, architecte_ordre=None, architecte_contact=None)
    svg = render_cartouche_svg(c, width_mm=297)
    # No crash when architect is absent
    assert "SAS Promoteur" in svg


def test_contains_indice():
    c = _sample_cartouche(indice="C")
    svg = render_cartouche_svg(c, width_mm=297)
    assert "Indice" in svg
    assert "C" in svg


def test_contains_parcelles_refs():
    c = _sample_cartouche()
    svg = render_cartouche_svg(c, width_mm=297)
    assert "94052-AB-0042" in svg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_pcmi_cartouche.py -v`
Expected: FAIL — `ModuleNotFoundError: core.pcmi.cartouche_pc`

- [ ] **Step 3: Implement cartouche**

```python
# apps/backend/core/pcmi/cartouche_pc.py
"""PC cartouche with ArchiClaude signature.

Renders a normed cartouche block (40mm high) containing all mandatory
PC information + discrete ArchiClaude signature for indirect branding.
"""
from __future__ import annotations
from core.pcmi.schemas import CartouchePC

CARTOUCHE_HEIGHT_MM = 40.0
SIGNATURE = "Généré par ArchiClaude — archiclaude.app"


def render_cartouche_svg(cartouche: CartouchePC, width_mm: float) -> str:
    """Generate SVG cartouche block (40mm high, full page width).

    Returns an SVG group element (not a full SVG document) to embed
    into a larger PDF page.
    """
    h = CARTOUCHE_HEIGHT_MM
    col1_w = width_mm * 0.55  # left: project info
    col2_w = width_mm * 0.45  # right: piece info

    refs = " | ".join(cartouche.parcelles_refs)

    lines = [
        f'<g id="cartouche" transform="translate(0,0)">',
        # Border
        f'<rect x="0" y="0" width="{width_mm}" height="{h}" fill="white" stroke="black" stroke-width="0.5"/>',
        # Vertical divider
        f'<line x1="{col1_w}" y1="0" x2="{col1_w}" y2="{h}" stroke="black" stroke-width="0.3"/>',
        # Horizontal divider (middle)
        f'<line x1="0" y1="{h / 2}" x2="{width_mm}" y2="{h / 2}" stroke="black" stroke-width="0.3"/>',
        # Left-top: project + adress
        f'<text x="2" y="4" font-family="Inter" font-size="2.2" font-weight="bold">PROJET :</text>',
        f'<text x="12" y="4" font-family="Inter" font-size="2.2">{_esc(cartouche.nom_projet)}</text>',
        f'<text x="2" y="8" font-family="Inter" font-size="2" fill="#333">ADRESSE :</text>',
        f'<text x="12" y="8" font-family="Inter" font-size="2">{_esc(cartouche.adresse)}</text>',
        f'<text x="2" y="12" font-family="Inter" font-size="2" fill="#333">PARCELLES :</text>',
        f'<text x="14" y="12" font-family="Inter" font-size="2">{_esc(refs)}</text>',
        # Right-top: piece + echelle + date + indice
        f'<text x="{col1_w + 2}" y="4" font-family="Inter" font-size="2.5" font-weight="bold">{_esc(cartouche.piece_num)} — {_esc(cartouche.piece_titre)}</text>',
        f'<text x="{col1_w + 2}" y="9" font-family="Inter" font-size="2">Échelle : {_esc(cartouche.echelle)}</text>',
        f'<text x="{col1_w + 2}" y="13" font-family="Inter" font-size="2">Date : {_esc(cartouche.date)}</text>',
        f'<text x="{col1_w + 2}" y="17" font-family="Inter" font-size="2">Indice : {_esc(cartouche.indice)}</text>',
        # Bottom: petitionnaire + architecte
        f'<text x="2" y="{h / 2 + 4}" font-family="Inter" font-size="2" font-weight="bold">Pétitionnaire :</text>',
        f'<text x="20" y="{h / 2 + 4}" font-family="Inter" font-size="2">{_esc(cartouche.petitionnaire_nom)} — {_esc(cartouche.petitionnaire_contact)}</text>',
    ]

    if cartouche.architecte_nom:
        archi_line = f"{cartouche.architecte_nom}"
        if cartouche.architecte_ordre:
            archi_line += f" (ordre {cartouche.architecte_ordre})"
        if cartouche.architecte_contact:
            archi_line += f" — {cartouche.architecte_contact}"
        lines.append(
            f'<text x="2" y="{h / 2 + 8}" font-family="Inter" font-size="2" font-weight="bold">Architecte :</text>'
        )
        lines.append(
            f'<text x="20" y="{h / 2 + 8}" font-family="Inter" font-size="2">{_esc(archi_line)}</text>'
        )

    # ArchiClaude signature (bottom-right, small)
    lines.append(
        f'<text x="{width_mm - 2}" y="{h - 1}" font-family="Inter" font-size="1.5" '
        f'fill="#888" text-anchor="end">{_esc(SIGNATURE)}</text>'
    )

    lines.append("</g>")
    return "\n".join(lines)


def _esc(s: str) -> str:
    """Escape XML special characters."""
    return (
        s.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_pcmi_cartouche.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/core/pcmi/cartouche_pc.py apps/backend/tests/unit/test_pcmi_cartouche.py
git commit -m "feat(pcmi): add PC cartouche with ArchiClaude signature"
```

---

## Task 3: PCMI1 — Plan de situation IGN

**Files:**
- Create: `apps/backend/core/pcmi/situation.py`
- Test: `apps/backend/tests/unit/test_pcmi_situation.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_pcmi_situation.py
import pytest
from unittest.mock import AsyncMock, patch
from shapely.geometry import Polygon
from core.pcmi.situation import (
    generate_pcmi1,
    _choose_wmts_layer,
    _compute_map_bounds,
)


class TestChooseWmtsLayer:
    def test_scan25_default(self):
        assert _choose_wmts_layer("scan25") == "GEOGRAPHICALGRIDSYSTEMS.MAPS.SCAN25TOUR.CV"

    def test_planv2(self):
        assert _choose_wmts_layer("planv2") == "GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2"

    def test_unknown_falls_back_scan25(self):
        assert _choose_wmts_layer("unknown") == "GEOGRAPHICALGRIDSYSTEMS.MAPS.SCAN25TOUR.CV"


class TestComputeMapBounds:
    def test_bounds_around_parcel(self):
        parcel = Polygon([(2.4830, 48.8370), (2.4840, 48.8370), (2.4840, 48.8380), (2.4830, 48.8380)])
        bounds = _compute_map_bounds([parcel], scale=25000)
        # Map should be larger than parcel bounds
        assert bounds["min_lng"] < 2.4830
        assert bounds["max_lng"] > 2.4840
        assert bounds["min_lat"] < 48.8370
        assert bounds["max_lat"] > 48.8380

    def test_bounds_centered_on_parcels(self):
        parcel = Polygon([(2.4830, 48.8370), (2.4840, 48.8380)])
        bounds = _compute_map_bounds([parcel], scale=25000)
        expected_lng = (2.4830 + 2.4840) / 2
        expected_lat = (48.8370 + 48.8380) / 2
        actual_lng = (bounds["min_lng"] + bounds["max_lng"]) / 2
        actual_lat = (bounds["min_lat"] + bounds["max_lat"]) / 2
        assert abs(actual_lng - expected_lng) < 0.001
        assert abs(actual_lat - expected_lat) < 0.001


class TestGeneratePcmi1:
    @pytest.mark.asyncio
    async def test_returns_svg(self):
        parcel = Polygon([(2.4830, 48.8370), (2.4840, 48.8370), (2.4840, 48.8380), (2.4830, 48.8380)])
        fake_tile_bytes = b"\x89PNG\r\n" + b"\x00" * 100  # minimal PNG header

        with patch("core.pcmi.situation._fetch_wmts_tile", new_callable=AsyncMock, return_value=fake_tile_bytes):
            svg = await generate_pcmi1(parcelles=[parcel], map_base="scan25")

        assert svg.startswith("<svg") or svg.startswith("<?xml")
        # Red circle and polygon markers present
        assert "#FF0000" in svg or "#CC0000" in svg or "red" in svg.lower()

    @pytest.mark.asyncio
    async def test_contains_parcel_polygon(self):
        parcel = Polygon([(2.4830, 48.8370), (2.4840, 48.8370), (2.4840, 48.8380), (2.4830, 48.8380)])
        fake_tile_bytes = b"\x89PNG\r\n" + b"\x00" * 100

        with patch("core.pcmi.situation._fetch_wmts_tile", new_callable=AsyncMock, return_value=fake_tile_bytes):
            svg = await generate_pcmi1(parcelles=[parcel], map_base="scan25")

        # Parcel overlay should be in SVG
        assert "<polygon" in svg or "<path" in svg
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && python -m pytest tests/unit/test_pcmi_situation.py -v`

- [ ] **Step 3: Implement situation.py**

```python
# apps/backend/core/pcmi/situation.py
"""PCMI1 — Plan de situation IGN with Scan 25 or Plan IGN v2 base map."""
from __future__ import annotations
import base64
import math
from typing import Literal

import httpx
from shapely.geometry import Polygon
from shapely.ops import unary_union

from core.http_client import get_http_client

WMTS_URL = "https://data.geopf.fr/wmts"

LAYERS = {
    "scan25": "GEOGRAPHICALGRIDSYSTEMS.MAPS.SCAN25TOUR.CV",
    "planv2": "GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2",
}


def _choose_wmts_layer(map_base: str) -> str:
    return LAYERS.get(map_base, LAYERS["scan25"])


def _compute_map_bounds(parcelles: list[Polygon], scale: int = 25000) -> dict[str, float]:
    """Compute bounds for the map image, centered on parcels, accommodating the scale.

    At scale 1/25000, 1mm on paper = 25m on ground. A4 portrait has ~200mm usable
    height, so the map covers ~5km × ~3.5km on ground (1250m/1300m ± margin).
    """
    combined = unary_union(parcelles)
    centroid = combined.centroid
    # Bounds ~2km around centroid (in degrees: ~0.02° at this latitude)
    delta = 0.015  # ~1.5km ground at 48.8°N
    return {
        "min_lng": centroid.x - delta,
        "max_lng": centroid.x + delta,
        "min_lat": centroid.y - delta,
        "max_lat": centroid.y + delta,
    }


async def _fetch_wmts_tile(*, layer: str, z: int, x: int, y: int) -> bytes:
    """Fetch a WMTS tile from IGN Géoplateforme."""
    params = {
        "SERVICE": "WMTS",
        "VERSION": "1.0.0",
        "REQUEST": "GetTile",
        "LAYER": layer,
        "STYLE": "normal",
        "TILEMATRIXSET": "PM",
        "TILEMATRIX": str(z),
        "TILEROW": str(y),
        "TILECOL": str(x),
        "FORMAT": "image/jpeg",
    }
    client = get_http_client()
    resp = await client.get(WMTS_URL, params=params, timeout=15.0)
    resp.raise_for_status()
    return resp.content


async def generate_pcmi1(
    *,
    parcelles: list[Polygon],
    map_base: Literal["scan25", "planv2"] = "scan25",
) -> str:
    """Generate PCMI1 plan de situation SVG.

    Args:
        parcelles: List of parcel polygons in WGS84 (lng, lat).
        map_base: "scan25" (default, conformity) or "planv2".

    Returns:
        SVG string with IGN base map + red circle + red polygon overlays.
    """
    layer = _choose_wmts_layer(map_base)
    bounds = _compute_map_bounds(parcelles)

    # Compute tile coordinates at zoom 15 (~1/25000 scale)
    z = 15
    lng_to_tile_x = lambda lng: int((lng + 180) / 360 * (2**z))
    lat_to_tile_y = lambda lat: int(
        (1 - math.log(math.tan(math.radians(lat)) + 1 / math.cos(math.radians(lat))) / math.pi)
        / 2
        * (2**z)
    )

    x_min = lng_to_tile_x(bounds["min_lng"])
    x_max = lng_to_tile_x(bounds["max_lng"])
    y_min = lat_to_tile_y(bounds["max_lat"])
    y_max = lat_to_tile_y(bounds["min_lat"])

    # For now, fetch a single representative tile centered on parcels
    # (Full implementation would stitch multiple tiles)
    combined = unary_union(parcelles)
    c = combined.centroid
    center_x = lng_to_tile_x(c.x)
    center_y = lat_to_tile_y(c.y)

    try:
        tile_bytes = await _fetch_wmts_tile(layer=layer, z=z, x=center_x, y=center_y)
        tile_b64 = base64.b64encode(tile_bytes).decode("ascii")
        tile_data_uri = f"data:image/jpeg;base64,{tile_b64}"
    except Exception:
        # Graceful degradation: white background
        tile_data_uri = ""

    # Build SVG with map + overlays
    svg_width = 200  # mm
    svg_height = 230  # mm

    # Compute combined centroid in SVG coordinates (center of SVG)
    cx_svg = svg_width / 2
    cy_svg = svg_height / 2
    radius_svg = 30  # mm (visible circle)

    # Parcel polygons scaled to fit (simplified: points relative to combined bounds)
    min_lng, max_lng = bounds["min_lng"], bounds["max_lng"]
    min_lat, max_lat = bounds["min_lat"], bounds["max_lat"]

    def project(lng: float, lat: float) -> tuple[float, float]:
        px = (lng - min_lng) / (max_lng - min_lng) * svg_width
        py = svg_height - (lat - min_lat) / (max_lat - min_lat) * svg_height
        return px, py

    polygon_paths = []
    for parcel in parcelles:
        coords = list(parcel.exterior.coords)
        svg_points = " ".join(f"{px:.2f},{py:.2f}" for px, py in (project(lng, lat) for lng, lat in coords))
        polygon_paths.append(
            f'<polygon points="{svg_points}" fill="none" stroke="#CC0000" stroke-width="0.5"/>'
        )

    # Build full SVG
    tile_img = (
        f'<image x="0" y="0" width="{svg_width}" height="{svg_height}" '
        f'href="{tile_data_uri}" preserveAspectRatio="none"/>'
        if tile_data_uri
        else ""
    )

    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{svg_width}mm" height="{svg_height}mm" viewBox="0 0 {svg_width} {svg_height}">
  {tile_img}
  <circle cx="{cx_svg}" cy="{cy_svg}" r="{radius_svg}" fill="none" stroke="#FF0000" stroke-width="1.5"/>
  {"".join(polygon_paths)}
  <g id="north-arrow" transform="translate(10, 20)">
    <polygon points="0,-6 3,6 0,3 -3,6" fill="black"/>
    <text y="12" text-anchor="middle" font-family="Inter" font-size="3">N</text>
  </g>
  <text x="{svg_width - 2}" y="{svg_height - 2}" text-anchor="end" font-family="Inter" font-size="2" fill="#666">Échelle 1/25000 — IGN</text>
</svg>"""

    return svg
```

- [ ] **Step 4: Run tests to verify they pass**

- [ ] **Step 5: Commit**

```bash
git add apps/backend/core/pcmi/situation.py apps/backend/tests/unit/test_pcmi_situation.py
git commit -m "feat(pcmi): add PCMI1 plan de situation IGN (Scan 25 + Plan IGN v2)"
```

---

## Task 4: Notice PCMI4 — adapter prompt Opus + renderer

**Files:**
- Modify: `apps/backend/core/analysis/architect_prompt.py`
- Modify: `apps/backend/core/analysis/architect_analysis.py`
- Create: `apps/backend/core/pcmi/notice_pcmi4.py`
- Create: `apps/backend/core/pcmi/templates/notice_pcmi4.html.j2`
- Test: `apps/backend/tests/unit/test_pcmi_notice.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_pcmi_notice.py
import pytest
from unittest.mock import AsyncMock, patch
from core.pcmi.notice_pcmi4 import generate_notice_pcmi4_pdf, extract_notice_from_opus
from core.pcmi.schemas import CartouchePC


class TestExtractNoticeFromOpus:
    def test_extracts_notice_section(self):
        opus_raw = """## Note d'opportunité

Some opportunity analysis content.

---NOTICE_PCMI4_SEPARATOR---

## 1. Terrain et ses abords

Le terrain se situe...

## 2. Projet dans son contexte

Le projet s'insère...

## 3. Composition du projet
...
"""
        notice = extract_notice_from_opus(opus_raw)
        assert "Terrain et ses abords" in notice
        assert "opportunity analysis" not in notice

    def test_no_separator_returns_full(self):
        opus_raw = "Some content without separator"
        notice = extract_notice_from_opus(opus_raw)
        assert notice == opus_raw


class TestGenerateNoticePdf:
    def test_returns_pdf_bytes(self):
        notice_md = """## 1. Terrain et ses abords
Le terrain se situe dans un secteur résidentiel...

## 2. Projet dans son contexte
Le projet s'insère harmonieusement...

## 3. Composition du projet
Les volumes sont composés...

## 4. Accès et stationnement
L'accès véhicule se fait...

## 5. Espaces libres et plantations
50% de pleine terre avec plantations indigènes.
"""
        cartouche = CartouchePC(
            nom_projet="Résidence Test",
            adresse="12 rue Test",
            parcelles_refs=["94052-AB-0042"],
            petitionnaire_nom="SAS Test",
            petitionnaire_contact="contact@test.fr",
            piece_num="PCMI4",
            piece_titre="Notice architecturale",
            echelle="—",
            date="19/04/2026",
            indice="A",
        )
        pdf_bytes = generate_notice_pcmi4_pdf(notice_md=notice_md, cartouche=cartouche)
        assert isinstance(pdf_bytes, bytes)
        assert len(pdf_bytes) > 1000  # non-trivial PDF
        assert pdf_bytes[:4] == b"%PDF"
```

- [ ] **Step 2: Implement notice_pcmi4.py**

```python
# apps/backend/core/pcmi/notice_pcmi4.py
"""PCMI4 — Notice architecturale R.431-8.

Extracts notice content from Opus output (produces 2 formats in 1 call)
and renders to PDF via WeasyPrint.
"""
from __future__ import annotations
import markdown
from pathlib import Path
from jinja2 import Environment, FileSystemLoader

from core.pcmi.schemas import CartouchePC

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)

SEPARATOR = "---NOTICE_PCMI4_SEPARATOR---"


def extract_notice_from_opus(opus_raw: str) -> str:
    """Extract the PCMI4 notice section from Opus output.

    Opus is instructed to produce 2 formats separated by a marker:
    - Note d'opportunité (internal promoter report)
    - ---NOTICE_PCMI4_SEPARATOR---
    - Notice PCMI4 (formal administrative)

    Returns just the notice section. If no separator found, returns input unchanged.
    """
    if SEPARATOR in opus_raw:
        return opus_raw.split(SEPARATOR, 1)[1].strip()
    return opus_raw


def generate_notice_pcmi4_pdf(*, notice_md: str, cartouche: CartouchePC) -> bytes:
    """Render notice markdown to PDF via WeasyPrint."""
    from weasyprint import HTML

    # Convert markdown to HTML
    notice_html = markdown.markdown(notice_md, extensions=["extra"])

    # Render template
    template = _env.get_template("notice_pcmi4.html.j2")
    html_str = template.render(
        notice_html=notice_html,
        cartouche=cartouche,
    )

    # Render to PDF
    return HTML(string=html_str).write_pdf()
```

- [ ] **Step 3: Create notice template**

```html
<!-- apps/backend/core/pcmi/templates/notice_pcmi4.html.j2 -->
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>{{ cartouche.nom_projet }} — PCMI4 Notice architecturale</title>
<style>
@page {
  size: A4;
  margin: 20mm 15mm 50mm 15mm;
  @bottom-center {
    content: element(cartouche);
  }
}
body {
  font-family: Inter, sans-serif;
  font-size: 11pt;
  line-height: 1.5;
  color: #1a1a1a;
}
h1 {
  font-family: "Playfair Display", serif;
  font-size: 18pt;
  border-bottom: 2px solid #0d9488;
  padding-bottom: 4pt;
}
h2 {
  font-family: "Playfair Display", serif;
  font-size: 14pt;
  color: #0d9488;
  margin-top: 20pt;
}
p {
  text-align: justify;
  margin: 8pt 0;
}
.cartouche {
  position: running(cartouche);
  font-size: 7pt;
  border-top: 1px solid #ccc;
  padding-top: 4mm;
  margin-top: 0;
}
.cartouche-main { display: flex; justify-content: space-between; }
.cartouche-left { width: 60%; }
.cartouche-right { width: 40%; text-align: right; }
.signature { color: #888; font-size: 6pt; text-align: right; margin-top: 2mm; }
</style>
</head>
<body>
<h1>{{ cartouche.nom_projet }}</h1>
<p style="color: #666; font-size: 10pt;">
  {{ cartouche.adresse }} · Parcelles {{ cartouche.parcelles_refs | join(", ") }}
</p>

{{ notice_html | safe }}

<div class="cartouche">
  <div class="cartouche-main">
    <div class="cartouche-left">
      <strong>{{ cartouche.piece_num }} — {{ cartouche.piece_titre }}</strong><br>
      Pétitionnaire : {{ cartouche.petitionnaire_nom }} — {{ cartouche.petitionnaire_contact }}<br>
      {% if cartouche.architecte_nom %}
        Architecte : {{ cartouche.architecte_nom }}
        {% if cartouche.architecte_ordre %} (ordre {{ cartouche.architecte_ordre }}){% endif %}
      {% endif %}
    </div>
    <div class="cartouche-right">
      Date : {{ cartouche.date }}<br>
      Indice : {{ cartouche.indice }}
    </div>
  </div>
  <div class="signature">Généré par ArchiClaude — archiclaude.app</div>
</div>
</body>
</html>
```

- [ ] **Step 4: Modify architect_prompt.py to request both formats**

Edit `apps/backend/core/analysis/architect_prompt.py` to enrich `SYSTEM_PROMPT` with:

```python
# Add to end of SYSTEM_PROMPT:
"""
IMPORTANT — FORMAT DE SORTIE EN DEUX PARTIES :

Tu dois produire DEUX sections séparées par le marqueur exact `---NOTICE_PCMI4_SEPARATOR---`.

PARTIE 1 : Note d'opportunité (promoteur interne)
Structure imposée : Synthèse / Opportunités / Contraintes / Alertes / Recommandations
Ton : décisionnaire, lexique promoteur

---NOTICE_PCMI4_SEPARATOR---

PARTIE 2 : Notice architecturale PCMI4 (dossier PC officiel, article R.431-8)
Structure imposée EXACTEMENT :
## 1. Terrain et ses abords
## 2. Projet dans son contexte
## 3. Composition du projet
## 4. Accès et stationnement
## 5. Espaces libres et plantations

Ton : formel, administratif, factuel. 500-900 mots au total.
"""
```

- [ ] **Step 5: Run tests, commit**

```bash
git add apps/backend/core/pcmi/notice_pcmi4.py apps/backend/core/pcmi/templates/ apps/backend/core/analysis/architect_prompt.py apps/backend/tests/unit/test_pcmi_notice.py
git commit -m "feat(pcmi): add PCMI4 notice architecturale with Opus dual-format prompt"
```

---

## Task 5: PCMI5 — Façades 4 côtés

**Files:**
- Create: `apps/backend/core/pcmi/facades.py`
- Test: `apps/backend/tests/unit/test_pcmi_facades.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_pcmi_facades.py
from shapely.geometry import Polygon
from core.pcmi.facades import generate_all_facades, assemble_facades_grid_svg


def test_generate_all_facades_returns_4_svgs():
    footprint = Polygon([(0, 0), (20, 0), (20, 15), (0, 15)])
    facades = generate_all_facades(
        footprint=footprint, nb_niveaux=4, hauteur_par_niveau=3.0,
    )
    assert set(facades.keys()) == {"nord", "sud", "est", "ouest"}
    for svg in facades.values():
        assert svg.startswith("<svg") or svg.startswith("<?xml")


def test_assemble_facades_grid_returns_single_svg():
    facades = {
        "nord": "<svg><rect/></svg>",
        "sud": "<svg><rect/></svg>",
        "est": "<svg><rect/></svg>",
        "ouest": "<svg><rect/></svg>",
    }
    grid_svg = assemble_facades_grid_svg(facades)
    assert grid_svg.startswith("<svg")
    # Should contain 4 labels
    assert "Nord" in grid_svg or "NORD" in grid_svg
    assert "Sud" in grid_svg or "SUD" in grid_svg
    assert "Est" in grid_svg or "EST" in grid_svg
    assert "Ouest" in grid_svg or "OUEST" in grid_svg
```

- [ ] **Step 2: Implement facades.py**

```python
# apps/backend/core/pcmi/facades.py
"""PCMI5 — Plans des 4 façades (nord, sud, est, ouest)."""
from __future__ import annotations
from shapely.geometry import Polygon
from core.programming.plans.facade import generate_facade


def generate_all_facades(
    *,
    footprint: Polygon,
    nb_niveaux: int,
    hauteur_par_niveau: float = 3.0,
    detail: str = "pc_norme",
) -> dict[str, str]:
    """Generate facades for all 4 cardinal orientations.

    Returns dict: {"nord": svg, "sud": svg, "est": svg, "ouest": svg}
    """
    bounds = footprint.bounds  # (minx, miny, maxx, maxy)
    width_ns = bounds[2] - bounds[0]  # east-west width (for N/S facades)
    width_eo = bounds[3] - bounds[1]  # north-south depth (for E/O facades)

    return {
        "nord": generate_facade(
            footprint_width_m=width_ns, nb_niveaux=nb_niveaux,
            hauteur_par_niveau=hauteur_par_niveau, detail=detail,
        ),
        "sud": generate_facade(
            footprint_width_m=width_ns, nb_niveaux=nb_niveaux,
            hauteur_par_niveau=hauteur_par_niveau, detail=detail,
        ),
        "est": generate_facade(
            footprint_width_m=width_eo, nb_niveaux=nb_niveaux,
            hauteur_par_niveau=hauteur_par_niveau, detail=detail,
        ),
        "ouest": generate_facade(
            footprint_width_m=width_eo, nb_niveaux=nb_niveaux,
            hauteur_par_niveau=hauteur_par_niveau, detail=detail,
        ),
    }


def assemble_facades_grid_svg(facades: dict[str, str]) -> str:
    """Assemble 4 facade SVGs into a 2x2 grid single SVG (for PCMI5 page).

    Layout:
    ┌─────────────┬─────────────┐
    │  FAÇADE NORD │  FAÇADE SUD │
    ├─────────────┼─────────────┤
    │  FAÇADE EST  │ FAÇADE OUEST│
    └─────────────┴─────────────┘
    """
    cell_w = 200  # mm
    cell_h = 130  # mm
    total_w = cell_w * 2 + 30  # margins
    total_h = cell_h * 2 + 40

    def _wrap_cell(label: str, svg_content: str, x: float, y: float) -> str:
        # Extract the body from inner SVG (strip outer <svg> tags if present)
        inner = svg_content
        if "<svg" in inner:
            start = inner.find(">", inner.find("<svg")) + 1
            end = inner.rfind("</svg>")
            inner = inner[start:end] if end > start else inner

        return f"""<g transform="translate({x}, {y})">
  <rect x="0" y="0" width="{cell_w}" height="{cell_h}" fill="none" stroke="#ccc" stroke-width="0.3"/>
  <text x="5" y="8" font-family="Inter" font-size="4" font-weight="bold">FAÇADE {label.upper()}</text>
  <g transform="translate(5, 15) scale(0.8)">
    {inner}
  </g>
</g>"""

    cells = [
        _wrap_cell("Nord", facades.get("nord", ""), 10, 10),
        _wrap_cell("Sud", facades.get("sud", ""), cell_w + 20, 10),
        _wrap_cell("Est", facades.get("est", ""), 10, cell_h + 20),
        _wrap_cell("Ouest", facades.get("ouest", ""), cell_w + 20, cell_h + 20),
    ]

    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{total_w}mm" height="{total_h}mm" viewBox="0 0 {total_w} {total_h}">
{"".join(cells)}
</svg>"""
```

- [ ] **Step 3: Run tests, commit**

```bash
git add apps/backend/core/pcmi/facades.py apps/backend/tests/unit/test_pcmi_facades.py
git commit -m "feat(pcmi): add PCMI5 4-facade generator with 2x2 grid layout"
```

---

## Task 6: PCMI7/8 — Photos d'environnement

**Files:**
- Create: `apps/backend/core/pcmi/photos.py`
- Test: `apps/backend/tests/unit/test_pcmi_photos.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_pcmi_photos.py
import pytest
from unittest.mock import AsyncMock, patch
from core.pcmi.photos import fetch_photo_environnement_proche, fetch_photo_environnement_lointain
from core.sources.mapillary import MapillaryPhoto
from core.sources.google_streetview import StreetViewImage


class TestFetchPhotoProche:
    @pytest.mark.asyncio
    async def test_uses_mapillary_when_available(self):
        mock_photos = [
            MapillaryPhoto(image_id="123", thumb_url="https://mapillary.com/photo.jpg",
                           captured_at=1700000000000, compass_angle=180.0, lat=48.83, lng=2.48),
        ]
        fake_bytes = b"\xff\xd8\xff" + b"\x00" * 100  # JPEG header

        with (
            patch("core.pcmi.photos.mapillary.fetch_photos_around", new_callable=AsyncMock, return_value=mock_photos),
            patch("core.pcmi.photos._download_image", new_callable=AsyncMock, return_value=fake_bytes),
        ):
            result = await fetch_photo_environnement_proche(lat=48.83, lng=2.48)

        assert result is not None
        assert result[:3] == b"\xff\xd8\xff" or len(result) > 0

    @pytest.mark.asyncio
    async def test_fallback_to_streetview(self):
        mock_sv = StreetViewImage(
            pano_id="abc", image_url="https://sv.google.com/img.jpg",
            lat=48.83, lng=2.48, date="2024-06",
        )
        fake_bytes = b"\xff\xd8\xff" + b"\x00" * 100

        with (
            patch("core.pcmi.photos.mapillary.fetch_photos_around", new_callable=AsyncMock, return_value=[]),
            patch("core.pcmi.photos.google_streetview.fetch_streetview_image", new_callable=AsyncMock, return_value=mock_sv),
            patch("core.pcmi.photos._download_image", new_callable=AsyncMock, return_value=fake_bytes),
        ):
            result = await fetch_photo_environnement_proche(lat=48.83, lng=2.48)

        assert result is not None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_source(self):
        with (
            patch("core.pcmi.photos.mapillary.fetch_photos_around", new_callable=AsyncMock, return_value=[]),
            patch("core.pcmi.photos.google_streetview.fetch_streetview_image", new_callable=AsyncMock, return_value=None),
        ):
            result = await fetch_photo_environnement_proche(lat=0.0, lng=0.0)

        assert result is None


class TestFetchPhotoLointaine:
    @pytest.mark.asyncio
    async def test_uses_mapillary_wide_radius(self):
        mock_photos = [
            MapillaryPhoto(image_id="456", thumb_url="https://m.com/wide.jpg",
                           captured_at=1700000000000, compass_angle=0.0, lat=48.83, lng=2.48),
        ]
        fake_bytes = b"\xff\xd8\xff" + b"\x00" * 100

        with (
            patch("core.pcmi.photos.mapillary.fetch_photos_around", new_callable=AsyncMock, return_value=mock_photos),
            patch("core.pcmi.photos._download_image", new_callable=AsyncMock, return_value=fake_bytes),
        ):
            result = await fetch_photo_environnement_lointain(lat=48.83, lng=2.48)

        assert result is not None
```

- [ ] **Step 2: Implement photos.py**

```python
# apps/backend/core/pcmi/photos.py
"""PCMI7/8 — Photos d'environnement proche et lointain."""
from __future__ import annotations
from core.http_client import get_http_client
from core.sources import mapillary, google_streetview


async def _download_image(url: str) -> bytes:
    """Download image bytes from URL."""
    client = get_http_client()
    resp = await client.get(url, timeout=30.0)
    resp.raise_for_status()
    return resp.content


async def fetch_photo_environnement_proche(*, lat: float, lng: float) -> bytes | None:
    """Fetch close-environment photo (PCMI7).

    Tries Mapillary first (30m radius), falls back to Street View.
    Returns JPEG bytes or None if no source available.
    """
    try:
        photos = await mapillary.fetch_photos_around(lat=lat, lng=lng, radius_m=30)
        if photos:
            return await _download_image(photos[0].thumb_url)
    except Exception:
        pass

    try:
        sv = await google_streetview.fetch_streetview_image(lat=lat, lng=lng)
        if sv is not None:
            return await _download_image(sv.image_url)
    except Exception:
        pass

    return None


async def fetch_photo_environnement_lointain(*, lat: float, lng: float) -> bytes | None:
    """Fetch wide-environment photo (PCMI8).

    Uses wider Mapillary radius (200m) for neighborhood overview.
    Returns JPEG bytes or None.
    """
    try:
        photos = await mapillary.fetch_photos_around(lat=lat, lng=lng, radius_m=200)
        if photos:
            return await _download_image(photos[0].thumb_url)
    except Exception:
        pass

    try:
        sv = await google_streetview.fetch_streetview_image(lat=lat, lng=lng, fov=120)
        if sv is not None:
            return await _download_image(sv.image_url)
    except Exception:
        pass

    return None
```

- [ ] **Step 3: Run tests, commit**

```bash
git add apps/backend/core/pcmi/photos.py apps/backend/tests/unit/test_pcmi_photos.py
git commit -m "feat(pcmi): add PCMI7/8 environment photos (Mapillary + Street View fallback)"
```

---

## Task 7: Renderer PDF reportlab pour plans

**Files:**
- Create: `apps/backend/core/programming/plans/renderer_pdf.py`
- Test: `apps/backend/tests/unit/test_renderer_pdf.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_renderer_pdf.py
from core.programming.plans.renderer_pdf import svg_to_pdf, jpeg_to_pdf
from core.pcmi.schemas import CartouchePC


def _sample_cartouche():
    return CartouchePC(
        nom_projet="Test", adresse="12 rue Test",
        parcelles_refs=["94052-AB-0042"],
        petitionnaire_nom="SAS Test",
        petitionnaire_contact="contact@test.fr",
        piece_num="PCMI1",
        piece_titre="Plan situation",
        echelle="1/25000",
        date="19/04/2026",
        indice="A",
    )


def test_svg_to_pdf_returns_bytes():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="100mm" height="100mm"><rect width="50" height="50" fill="red"/></svg>'
    pdf = svg_to_pdf(svg_string=svg, format="A4", orientation="portrait", cartouche=_sample_cartouche())
    assert isinstance(pdf, bytes)
    assert pdf[:4] == b"%PDF"
    assert len(pdf) > 500


def test_svg_to_pdf_a3_landscape():
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="200mm" height="100mm"><rect width="100" height="50" fill="blue"/></svg>'
    pdf = svg_to_pdf(svg_string=svg, format="A3", orientation="landscape", cartouche=_sample_cartouche())
    assert pdf[:4] == b"%PDF"


def test_jpeg_to_pdf_embeds_image():
    # Minimal valid JPEG (2x2 red pixel)
    import base64
    jpeg_b64 = "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFAABAAAAAAAAAAAAAAAAAAAACf/EABQBAQAAAAAAAAAAAAAAAAAAAAD/2gAIAQEAAD8Qf//Z"
    jpeg_bytes = base64.b64decode(jpeg_b64)
    pdf = jpeg_to_pdf(jpeg_bytes=jpeg_bytes, format="A4", orientation="landscape", cartouche=_sample_cartouche())
    assert pdf[:4] == b"%PDF"
```

- [ ] **Step 2: Implement renderer_pdf.py**

```python
# apps/backend/core/programming/plans/renderer_pdf.py
"""PDF rendering for plans via reportlab (ISO format control + cartouche)."""
from __future__ import annotations
from io import BytesIO
from typing import Literal

from reportlab.lib.pagesizes import A1, A3, A4, landscape, portrait
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas as rl_canvas

from core.pcmi.cartouche_pc import render_cartouche_svg, CARTOUCHE_HEIGHT_MM
from core.pcmi.schemas import CartouchePC


FORMATS = {"A1": A1, "A3": A3, "A4": A4}


def _get_page_size(format: str, orientation: str) -> tuple[float, float]:
    size = FORMATS.get(format, A4)
    return landscape(size) if orientation == "landscape" else portrait(size)


def _draw_cartouche_on_canvas(c: rl_canvas.Canvas, cartouche: CartouchePC, page_width_pt: float) -> None:
    """Draw cartouche at bottom of the current page."""
    # Cartouche spans full width, 40mm high
    from reportlab.lib.units import mm
    cartouche_height_pt = CARTOUCHE_HEIGHT_MM * mm
    page_width_mm = page_width_pt / mm

    # Border
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.5 * mm / 2.83)  # 0.5mm in points
    c.rect(0, 0, page_width_pt, cartouche_height_pt, stroke=1, fill=0)

    # Text content (simplified — matches svg cartouche)
    c.setFont("Helvetica-Bold", 8)
    c.drawString(3 * mm, cartouche_height_pt - 5 * mm, f"PROJET : {cartouche.nom_projet}")
    c.setFont("Helvetica", 7)
    c.drawString(3 * mm, cartouche_height_pt - 10 * mm, f"ADRESSE : {cartouche.adresse}")
    c.drawString(
        3 * mm, cartouche_height_pt - 14 * mm,
        f"PARCELLES : {' | '.join(cartouche.parcelles_refs)}",
    )

    col2_x = page_width_mm * 0.55 * mm
    c.setFont("Helvetica-Bold", 9)
    c.drawString(col2_x, cartouche_height_pt - 5 * mm, f"{cartouche.piece_num} — {cartouche.piece_titre}")
    c.setFont("Helvetica", 7)
    c.drawString(col2_x, cartouche_height_pt - 10 * mm, f"Échelle : {cartouche.echelle}")
    c.drawString(col2_x, cartouche_height_pt - 14 * mm, f"Date : {cartouche.date}")
    c.drawString(col2_x, cartouche_height_pt - 18 * mm, f"Indice : {cartouche.indice}")

    # Middle divider
    c.setLineWidth(0.3 * mm / 2.83)
    c.line(0, cartouche_height_pt / 2, page_width_pt, cartouche_height_pt / 2)
    c.line(col2_x, 0, col2_x, cartouche_height_pt)

    # Pétitionnaire / Architecte
    c.setFont("Helvetica-Bold", 7)
    c.drawString(3 * mm, cartouche_height_pt / 2 - 4 * mm, "Pétitionnaire :")
    c.setFont("Helvetica", 7)
    c.drawString(
        20 * mm, cartouche_height_pt / 2 - 4 * mm,
        f"{cartouche.petitionnaire_nom} — {cartouche.petitionnaire_contact}",
    )

    if cartouche.architecte_nom:
        c.setFont("Helvetica-Bold", 7)
        c.drawString(3 * mm, cartouche_height_pt / 2 - 9 * mm, "Architecte :")
        c.setFont("Helvetica", 7)
        archi = cartouche.architecte_nom
        if cartouche.architecte_ordre:
            archi += f" (ordre {cartouche.architecte_ordre})"
        c.drawString(20 * mm, cartouche_height_pt / 2 - 9 * mm, archi)

    # ArchiClaude signature
    c.setFont("Helvetica", 5)
    c.setFillColorRGB(0.53, 0.53, 0.53)  # #888
    c.drawRightString(
        page_width_pt - 2 * mm, 2 * mm,
        "Généré par ArchiClaude — archiclaude.app",
    )
    c.setFillColorRGB(0, 0, 0)  # reset


def svg_to_pdf(
    *,
    svg_string: str,
    format: Literal["A1", "A3", "A4"] = "A4",
    orientation: Literal["portrait", "landscape"] = "portrait",
    cartouche: CartouchePC,
) -> bytes:
    """Convert an SVG string to a PDF page of the given ISO format with cartouche."""
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPDF
    from io import StringIO
    from reportlab.lib.units import mm

    page_w, page_h = _get_page_size(format, orientation)
    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(page_w, page_h))

    # Parse SVG
    svg_buf = StringIO(svg_string)
    drawing = svg2rlg(svg_buf)

    if drawing is not None:
        # Scale drawing to fit page above cartouche
        cartouche_h_pt = CARTOUCHE_HEIGHT_MM * mm
        available_h = page_h - cartouche_h_pt - 10 * mm
        scale_x = (page_w - 20 * mm) / max(drawing.width, 1)
        scale_y = available_h / max(drawing.height, 1)
        scale = min(scale_x, scale_y)

        drawing.width *= scale
        drawing.height *= scale
        drawing.scale(scale, scale)

        x_offset = (page_w - drawing.width) / 2
        y_offset = cartouche_h_pt + (available_h - drawing.height) / 2

        renderPDF.draw(drawing, c, x_offset, y_offset)

    # Draw cartouche
    _draw_cartouche_on_canvas(c, cartouche, page_w)

    c.showPage()
    c.save()
    return buf.getvalue()


def jpeg_to_pdf(
    *,
    jpeg_bytes: bytes,
    format: Literal["A1", "A3", "A4"] = "A4",
    orientation: Literal["portrait", "landscape"] = "landscape",
    cartouche: CartouchePC,
) -> bytes:
    """Embed a JPEG image into a PDF page of the given format with cartouche."""
    from reportlab.lib.units import mm

    page_w, page_h = _get_page_size(format, orientation)
    buf = BytesIO()
    c = rl_canvas.Canvas(buf, pagesize=(page_w, page_h))

    img = ImageReader(BytesIO(jpeg_bytes))

    cartouche_h_pt = CARTOUCHE_HEIGHT_MM * mm
    avail_w = page_w - 20 * mm
    avail_h = page_h - cartouche_h_pt - 20 * mm

    # Get image size for aspect preservation
    img_w, img_h = img.getSize()
    aspect = img_w / img_h
    if avail_w / avail_h > aspect:
        h = avail_h
        w = h * aspect
    else:
        w = avail_w
        h = w / aspect

    x = (page_w - w) / 2
    y = cartouche_h_pt + (avail_h - h) / 2
    c.drawImage(img, x, y, width=w, height=h, preserveAspectRatio=True)

    _draw_cartouche_on_canvas(c, cartouche, page_w)

    c.showPage()
    c.save()
    return buf.getvalue()
```

- [ ] **Step 3: Run tests, commit**

```bash
git add apps/backend/core/programming/plans/renderer_pdf.py apps/backend/tests/unit/test_renderer_pdf.py
git commit -m "feat(plans): add reportlab PDF renderer with ISO format control"
```

---

## Task 8: Assembler PDF unique + ZIP

**Files:**
- Create: `apps/backend/core/pcmi/assembler.py`
- Test: `apps/backend/tests/unit/test_pcmi_assembler.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_pcmi_assembler.py
import zipfile
from io import BytesIO
from core.pcmi.assembler import assemble_dossier
from core.pcmi.schemas import CartouchePC


def _minimal_pdf_bytes() -> bytes:
    """Generate a minimal valid PDF."""
    from reportlab.pdfgen import canvas as rl_canvas
    buf = BytesIO()
    c = rl_canvas.Canvas(buf)
    c.drawString(100, 100, "Test")
    c.showPage()
    c.save()
    return buf.getvalue()


def _sample_cartouche():
    return CartouchePC(
        nom_projet="Test", adresse="12 rue Test",
        parcelles_refs=["94052-AB-0042"],
        petitionnaire_nom="SAS Test",
        petitionnaire_contact="contact@test.fr",
        piece_num="—",
        piece_titre="Dossier PC",
        echelle="—",
        date="19/04/2026",
        indice="A",
    )


def test_assemble_dossier_returns_pdf_and_zip():
    pdfs = {
        "PCMI1": _minimal_pdf_bytes(),
        "PCMI2a": _minimal_pdf_bytes(),
        "PCMI3": _minimal_pdf_bytes(),
    }
    pdf_unique, zip_bytes = assemble_dossier(
        pdfs_par_piece=pdfs, nom_projet="Test Projet",
        cartouche=_sample_cartouche(),
    )
    # PDF unique is a valid PDF
    assert pdf_unique[:4] == b"%PDF"
    # ZIP contains individual PDFs
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        names = zf.namelist()
        assert any("PCMI1" in n for n in names)
        assert any("PCMI2a" in n for n in names)
        assert "README.txt" in names


def test_zip_contains_readme_with_pieces_list():
    pdfs = {"PCMI1": _minimal_pdf_bytes(), "PCMI2a": _minimal_pdf_bytes()}
    _, zip_bytes = assemble_dossier(
        pdfs_par_piece=pdfs, nom_projet="Test",
        cartouche=_sample_cartouche(),
    )
    with zipfile.ZipFile(BytesIO(zip_bytes)) as zf:
        readme = zf.read("README.txt").decode("utf-8")
        assert "PCMI1" in readme
        assert "PCMI2a" in readme
```

- [ ] **Step 2: Implement assembler.py**

```python
# apps/backend/core/pcmi/assembler.py
"""Assemble PCMI pieces into a unified PDF + ZIP with separated pieces."""
from __future__ import annotations
import zipfile
from datetime import datetime
from io import BytesIO

from pypdf import PdfReader, PdfWriter

from core.pcmi.schemas import CartouchePC, PCMI_ORDER, PCMI_TITRES


def _safe_filename(text: str) -> str:
    """Convert text to safe filename."""
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in text).strip("-")


def assemble_dossier(
    *,
    pdfs_par_piece: dict[str, bytes],
    nom_projet: str,
    cartouche: CartouchePC,
) -> tuple[bytes, bytes]:
    """Assemble unified PDF + separated ZIP.

    Args:
        pdfs_par_piece: {"PCMI1": pdf_bytes, "PCMI2a": pdf_bytes, ...}
        nom_projet: Project name for README/filename
        cartouche: Cartouche for cover page

    Returns:
        (unified_pdf_bytes, zip_bytes)
    """
    # Build unified PDF: concatenate pieces in PCMI order
    writer = PdfWriter()
    for code in PCMI_ORDER:
        if code not in pdfs_par_piece:
            continue
        reader = PdfReader(BytesIO(pdfs_par_piece[code]))
        for page in reader.pages:
            writer.add_page(page)
        # Add bookmark (outline) at start of each piece
        titre = PCMI_TITRES.get(code, code)
        writer.add_outline_item(
            f"{code} — {titre}",
            len(writer.pages) - len(reader.pages),
        )

    unified_buf = BytesIO()
    writer.write(unified_buf)
    unified_pdf_bytes = unified_buf.getvalue()

    # Build ZIP
    zip_buf = BytesIO()
    with zipfile.ZipFile(zip_buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for code, pdf_bytes in pdfs_par_piece.items():
            titre = PCMI_TITRES.get(code, code)
            filename = f"{code}-{_safe_filename(titre.lower())}.pdf"
            zf.writestr(filename, pdf_bytes)

        readme = _build_readme(nom_projet=nom_projet, cartouche=cartouche, pieces=list(pdfs_par_piece.keys()))
        zf.writestr("README.txt", readme)

    return unified_pdf_bytes, zip_buf.getvalue()


def _build_readme(*, nom_projet: str, cartouche: CartouchePC, pieces: list[str]) -> str:
    """Generate README.txt for ZIP."""
    lines = [
        f"DOSSIER PERMIS DE CONSTRUIRE — {nom_projet}",
        "=" * 60,
        "",
        f"Pétitionnaire : {cartouche.petitionnaire_nom}",
    ]
    if cartouche.architecte_nom:
        lines.append(f"Architecte : {cartouche.architecte_nom}")
    lines.extend([
        f"Adresse : {cartouche.adresse}",
        f"Parcelles : {' | '.join(cartouche.parcelles_refs)}",
        f"Date de génération : {datetime.utcnow().strftime('%d/%m/%Y')}",
        f"Indice de révision : {cartouche.indice}",
        "",
        "PIÈCES INCLUSES :",
        "",
    ])
    for code in PCMI_ORDER:
        if code in pieces:
            lines.append(f"  ✓ {code} — {PCMI_TITRES.get(code, code)}")

    lines.extend([
        "",
        "INSTRUCTIONS DE DÉPÔT :",
        "",
        "Ce ZIP contient les pièces séparées compatibles avec les plateformes",
        "de dépôt dématérialisé (Plat'AU et autres). Chaque pièce est un PDF",
        "indépendant conforme au code de l'urbanisme.",
        "",
        "Généré par ArchiClaude — archiclaude.app",
    ])

    return "\n".join(lines)
```

- [ ] **Step 3: Run tests, commit**

```bash
git add apps/backend/core/pcmi/assembler.py apps/backend/tests/unit/test_pcmi_assembler.py
git commit -m "feat(pcmi): add dossier assembler — unified PDF + ZIP with README"
```

---

## Task 9: DB model + migration + API routes + worker

**Files:**
- Create: `apps/backend/db/models/pcmi_dossiers.py`
- Create: `apps/backend/alembic/versions/20260419_0001_pcmi_dossiers.py`
- Create: `apps/backend/api/routes/pcmi.py`
- Create: `apps/backend/schemas/pcmi.py`
- Create: `apps/backend/workers/pcmi.py`
- Modify: `apps/backend/api/main.py`
- Modify: `apps/backend/workers/main.py`
- Modify: `apps/backend/alembic/env.py`
- Test: `apps/backend/tests/integration/test_pcmi_endpoints.py`

- [ ] **Step 1: DB model**

```python
# apps/backend/db/models/pcmi_dossiers.py
"""SQLAlchemy model for PCMI dossiers."""
import uuid
from sqlalchemy import Column, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from db.base import Base


class PcmiDossierRow(Base):
    __tablename__ = "pcmi_dossiers"
    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(PgUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    status = Column(Text, nullable=False, server_default="queued")
    indice_revision = Column(String(2), nullable=False)
    map_base = Column(Text, server_default="scan25")
    pdf_unique_r2_key = Column(Text, nullable=True)
    zip_r2_key = Column(Text, nullable=True)
    pieces_status = Column(JSONB, nullable=True)
    error_msg = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("project_id", "indice_revision", name="uq_pcmi_project_revision"),
    )
```

- [ ] **Step 2: Alembic migration**

```python
# apps/backend/alembic/versions/20260419_0001_pcmi_dossiers.py
"""pcmi_dossiers

Revision ID: 20260419_0001
Revises: 20260418_0003
Create Date: 2026-04-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260419_0001"
down_revision = "20260418_0003"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pcmi_dossiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("indice_revision", sa.String(2), nullable=False),
        sa.Column("map_base", sa.Text, server_default="scan25"),
        sa.Column("pdf_unique_r2_key", sa.Text, nullable=True),
        sa.Column("zip_r2_key", sa.Text, nullable=True),
        sa.Column("pieces_status", postgresql.JSONB, nullable=True),
        sa.Column("error_msg", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("project_id", "indice_revision", name="uq_pcmi_project_revision"),
    )


def downgrade():
    op.drop_table("pcmi_dossiers")
```

- [ ] **Step 3: Update alembic/env.py**

Add `from db.models import pcmi_dossiers` to the existing imports list.

- [ ] **Step 4: Schemas Pydantic**

```python
# apps/backend/schemas/pcmi.py
"""API schemas for PCMI endpoints."""
from pydantic import BaseModel
from typing import Literal


class GenerateResponse(BaseModel):
    job_id: str
    status: str


class StatusResponse(BaseModel):
    status: str
    indice_revision: str | None = None
    pieces_status: dict | None = None
    pdf_url: str | None = None
    zip_url: str | None = None
    error_msg: str | None = None


class SettingsUpdate(BaseModel):
    map_base: Literal["scan25", "planv2"] | None = None


class SettingsOut(BaseModel):
    map_base: str
```

- [ ] **Step 5: API routes**

```python
# apps/backend/api/routes/pcmi.py
"""PCMI dossier endpoints."""
import uuid
from fastapi import APIRouter, Response
from fastapi.responses import PlainTextResponse

from core.pcmi.schemas import PCMI_ORDER, PCMI_TITRES
from schemas.pcmi import GenerateResponse, StatusResponse, SettingsOut, SettingsUpdate

router = APIRouter(prefix="/projects/{project_id}/pcmi", tags=["pcmi"])


@router.post("/generate", status_code=202, response_model=GenerateResponse)
async def generate_pcmi(project_id: str):
    """Enqueue PCMI generation job."""
    return GenerateResponse(job_id=str(uuid.uuid4()), status="queued")


@router.get("/status", response_model=StatusResponse)
async def pcmi_status(project_id: str):
    """Check generation status."""
    return StatusResponse(status="not_generated")


@router.get("/{piece}")
async def get_piece_svg(project_id: str, piece: str):
    """Return SVG for a specific piece."""
    if piece not in PCMI_ORDER:
        return Response(status_code=404, content=f"Unknown piece {piece}")
    # Placeholder SVG
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="210mm" height="297mm"><text x="50" y="50">{piece} — {PCMI_TITRES[piece]}</text></svg>'
    return Response(content=svg, media_type="image/svg+xml")


@router.get("/{piece}/pdf")
async def get_piece_pdf(project_id: str, piece: str):
    """Return PDF for a specific piece (placeholder)."""
    return PlainTextResponse(f"PDF for {piece} — placeholder", status_code=200)


@router.get("/dossier.pdf")
async def get_dossier_pdf(project_id: str):
    """Download unified PDF dossier (placeholder)."""
    return PlainTextResponse("Unified PDF — placeholder", status_code=200)


@router.get("/dossier.zip")
async def get_dossier_zip(project_id: str):
    """Download ZIP with separated pieces (placeholder)."""
    return PlainTextResponse("ZIP — placeholder", status_code=200)


@router.patch("/settings", response_model=SettingsOut)
async def update_settings(project_id: str, settings: SettingsUpdate):
    """Update map_base or other settings."""
    return SettingsOut(map_base=settings.map_base or "scan25")
```

- [ ] **Step 6: Worker**

```python
# apps/backend/workers/pcmi.py
"""ARQ worker for PCMI dossier generation."""


async def generate_pcmi_dossier(ctx, *, project_id: str, map_base: str = "scan25"):
    """Generate full PCMI dossier.

    Pipeline:
      1. Fetch project data (parcels, feasibility, plans)
      2. Generate PCMI1-8 in parallel
      3. Render PDFs (reportlab for plans, WeasyPrint for notice)
      4. Assemble unified PDF + ZIP
      5. Upload to R2
      6. Update DB

    v1: stub — full DB integration pending.
    """
    return {"status": "done", "project_id": project_id}
```

- [ ] **Step 7: Register router + worker**

Modify `apps/backend/api/main.py` to add:
```python
from api.routes.pcmi import router as pcmi_router
app.include_router(pcmi_router, prefix="/api/v1")
```

Modify `apps/backend/workers/main.py` to register `generate_pcmi_dossier`.

- [ ] **Step 8: Integration tests**

```python
# apps/backend/tests/integration/test_pcmi_endpoints.py
import pytest
from httpx import AsyncClient


class TestPcmiEndpoints:
    @pytest.mark.asyncio
    async def test_generate_returns_202(self, client: AsyncClient):
        resp = await client.post("/api/v1/projects/test-id/pcmi/generate")
        assert resp.status_code == 202
        assert "job_id" in resp.json()

    @pytest.mark.asyncio
    async def test_status(self, client: AsyncClient):
        resp = await client.get("/api/v1/projects/test-id/pcmi/status")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_piece_svg(self, client: AsyncClient):
        resp = await client.get("/api/v1/projects/test-id/pcmi/PCMI1")
        assert resp.status_code == 200
        assert "svg" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_unknown_piece_404(self, client: AsyncClient):
        resp = await client.get("/api/v1/projects/test-id/pcmi/PCMI99")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_settings_update(self, client: AsyncClient):
        resp = await client.patch(
            "/api/v1/projects/test-id/pcmi/settings",
            json={"map_base": "planv2"},
        )
        assert resp.status_code == 200
        assert resp.json()["map_base"] == "planv2"
```

- [ ] **Step 9: Commit**

```bash
git add apps/backend/db/models/pcmi_dossiers.py apps/backend/alembic/ apps/backend/api/routes/pcmi.py apps/backend/schemas/pcmi.py apps/backend/workers/pcmi.py apps/backend/api/main.py apps/backend/workers/main.py apps/backend/tests/integration/test_pcmi_endpoints.py
git commit -m "feat(api): add PCMI endpoints, DB model, worker"
```

---

## Task 10: Frontend PCMI page + components

**Files:**
- Create: `apps/frontend/src/app/projects/[id]/pcmi/page.tsx`
- Create: `apps/frontend/src/components/pcmi/PcmiGenerator.tsx`
- Create: `apps/frontend/src/components/pcmi/PcmiPreview.tsx`
- Create: `apps/frontend/src/components/pcmi/PcmiDownloadButtons.tsx`
- Create: `apps/frontend/src/components/pcmi/SituationMapSelector.tsx`
- Create: `apps/frontend/src/components/pcmi/RevisionHistory.tsx`

- [ ] **Step 1: Create PcmiGenerator**

```tsx
// apps/frontend/src/components/pcmi/PcmiGenerator.tsx
"use client";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { apiFetch } from "@/lib/api";

interface Props {
  projectId: string;
  onGenerated?: () => void;
}

export default function PcmiGenerator({ projectId, onGenerated }: Props) {
  const [loading, setLoading] = useState(false);
  const [status, setStatus] = useState<string | null>(null);

  async function handleGenerate() {
    setLoading(true);
    setStatus("Génération en cours…");
    try {
      await apiFetch(`/projects/${projectId}/pcmi/generate`, { method: "POST" });
      setStatus("Dossier généré avec succès");
      onGenerated?.();
    } catch {
      setStatus("Erreur lors de la génération");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex items-center gap-3">
      <Button onClick={handleGenerate} disabled={loading} style={{ backgroundColor: "var(--ac-primary)", color: "white" }}>
        {loading ? "Génération…" : "Générer le dossier PC"}
      </Button>
      {status && <span className="text-sm text-slate-600">{status}</span>}
    </div>
  );
}
```

- [ ] **Step 2: Create SituationMapSelector**

```tsx
// apps/frontend/src/components/pcmi/SituationMapSelector.tsx
"use client";
import { useState } from "react";
import { apiFetch } from "@/lib/api";

interface Props {
  projectId: string;
  defaultValue?: "scan25" | "planv2";
}

export default function SituationMapSelector({ projectId, defaultValue = "scan25" }: Props) {
  const [value, setValue] = useState<"scan25" | "planv2">(defaultValue);

  async function handleChange(newVal: "scan25" | "planv2") {
    setValue(newVal);
    await apiFetch(`/projects/${projectId}/pcmi/settings`, {
      method: "PATCH",
      body: JSON.stringify({ map_base: newVal }),
    });
  }

  return (
    <div className="flex items-center gap-2">
      <label className="text-sm font-medium text-slate-700">Fond PCMI1 :</label>
      <div className="inline-flex rounded-md border border-slate-200 overflow-hidden">
        <button
          className={`px-3 py-1 text-sm ${value === "scan25" ? "bg-teal-600 text-white" : "bg-white text-slate-700"}`}
          onClick={() => handleChange("scan25")}
        >
          Scan 25
        </button>
        <button
          className={`px-3 py-1 text-sm ${value === "planv2" ? "bg-teal-600 text-white" : "bg-white text-slate-700"}`}
          onClick={() => handleChange("planv2")}
        >
          Plan IGN v2
        </button>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Create PcmiPreview**

```tsx
// apps/frontend/src/components/pcmi/PcmiPreview.tsx
"use client";
import { useState } from "react";

const PIECES = [
  { code: "PCMI1", titre: "Plan de situation" },
  { code: "PCMI2a", titre: "Plan de masse" },
  { code: "PCMI2b", titre: "Plans de niveaux" },
  { code: "PCMI3", titre: "Coupe" },
  { code: "PCMI4", titre: "Notice architecturale" },
  { code: "PCMI5", titre: "Façades" },
  { code: "PCMI7", titre: "Photo env. proche" },
  { code: "PCMI8", titre: "Photo env. lointain" },
];

interface Props { projectId: string; }

export default function PcmiPreview({ projectId }: Props) {
  const [current, setCurrent] = useState(0);
  const piece = PIECES[current];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 flex-wrap">
        {PIECES.map((p, i) => (
          <button
            key={p.code}
            onClick={() => setCurrent(i)}
            className={`px-2 py-1 text-xs rounded border ${i === current ? "bg-teal-600 text-white border-teal-600" : "bg-white text-slate-700 border-slate-200"}`}
          >
            {p.code}
          </button>
        ))}
      </div>
      <div className="border border-slate-200 rounded-lg p-4 bg-white">
        <h3 className="text-sm font-semibold text-slate-700 mb-2">{piece.titre}</h3>
        <iframe
          src={`/api/v1/projects/${projectId}/pcmi/${piece.code}`}
          className="w-full h-[600px] border border-slate-100"
          title={piece.titre}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Create PcmiDownloadButtons**

```tsx
// apps/frontend/src/components/pcmi/PcmiDownloadButtons.tsx
"use client";
import { Button } from "@/components/ui/button";

interface Props { projectId: string; }

export default function PcmiDownloadButtons({ projectId }: Props) {
  const basePdf = `/api/v1/projects/${projectId}/pcmi/dossier.pdf`;
  const baseZip = `/api/v1/projects/${projectId}/pcmi/dossier.zip`;
  return (
    <div className="flex items-center gap-3">
      <a href={basePdf} download className="inline-flex">
        <Button variant="outline">Télécharger PDF unique</Button>
      </a>
      <a href={baseZip} download className="inline-flex">
        <Button variant="outline">Télécharger ZIP (pièces séparées)</Button>
      </a>
    </div>
  );
}
```

- [ ] **Step 5: Create RevisionHistory (minimal)**

```tsx
// apps/frontend/src/components/pcmi/RevisionHistory.tsx
"use client";

interface Revision {
  indice: string;
  generated_at: string;
  pdf_url: string;
}

interface Props { revisions: Revision[]; }

export default function RevisionHistory({ revisions }: Props) {
  if (revisions.length === 0) {
    return <p className="text-sm text-slate-500">Aucune révision générée.</p>;
  }
  return (
    <div className="space-y-2">
      {revisions.map((r) => (
        <div key={r.indice} className="flex items-center justify-between border border-slate-100 rounded px-3 py-2">
          <div>
            <span className="font-semibold text-teal-700">Indice {r.indice}</span>
            <span className="text-xs text-slate-500 ml-3">{r.generated_at}</span>
          </div>
          <a href={r.pdf_url} download className="text-xs text-teal-600 underline">Télécharger</a>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 6: Create PCMI page**

```tsx
// apps/frontend/src/app/projects/[id]/pcmi/page.tsx
"use client";
import { use } from "react";
import Link from "next/link";
import PcmiGenerator from "@/components/pcmi/PcmiGenerator";
import PcmiPreview from "@/components/pcmi/PcmiPreview";
import PcmiDownloadButtons from "@/components/pcmi/PcmiDownloadButtons";
import SituationMapSelector from "@/components/pcmi/SituationMapSelector";
import RevisionHistory from "@/components/pcmi/RevisionHistory";

export default function PcmiPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);

  return (
    <main className="min-h-screen bg-slate-50">
      <nav className="border-b border-slate-100 bg-white px-6 py-4">
        <div className="max-w-6xl mx-auto flex items-center justify-between">
          <Link href="/" className="font-display text-xl font-semibold text-slate-900">ArchiClaude</Link>
          <div className="flex gap-4 text-sm text-slate-500">
            <Link href="/projects" className="hover:text-slate-700">Mes projets</Link>
            <Link href={`/projects/${id}`} className="hover:text-slate-700">Projet</Link>
          </div>
        </div>
      </nav>

      <div className="max-w-6xl mx-auto px-6 py-8 space-y-6">
        <div className="flex items-center gap-2 text-sm text-slate-400">
          <Link href={`/projects/${id}`} className="hover:text-slate-600">Projet</Link>
          <span>/</span>
          <span className="text-slate-600">Dossier PC</span>
        </div>

        <h1 className="font-display text-3xl font-bold text-slate-900">Dossier PC complet</h1>
        <p className="text-sm text-slate-500">
          Génération automatique des pièces PCMI1-8 conformes au code de l&apos;urbanisme
        </p>

        <div className="bg-white border border-slate-200 rounded-xl p-6 space-y-4">
          <div className="flex items-center justify-between">
            <SituationMapSelector projectId={id} />
            <PcmiGenerator projectId={id} />
          </div>

          <PcmiDownloadButtons projectId={id} />
        </div>

        <div className="bg-white border border-slate-200 rounded-xl p-6">
          <h2 className="font-display text-lg font-semibold text-slate-900 mb-4">Aperçu des pièces</h2>
          <PcmiPreview projectId={id} />
        </div>

        <div className="bg-white border border-slate-200 rounded-xl p-6">
          <h2 className="font-display text-lg font-semibold text-slate-900 mb-4">Historique des révisions</h2>
          <RevisionHistory revisions={[]} />
        </div>
      </div>
    </main>
  );
}
```

- [ ] **Step 7: Run typecheck + commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/frontend && node_modules/.bin/tsc --noEmit

cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/frontend/src/app/projects/\[id\]/pcmi/ apps/frontend/src/components/pcmi/
git commit -m "feat(frontend): add PCMI dossier page with generator, preview, download, revisions"
```

---

## Task 11: Vérification finale

- [ ] **Step 1: Run backend ruff**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend && ruff check . --fix
```

- [ ] **Step 2: Run backend tests**

```bash
python -m pytest tests/ -v --tb=short
```

- [ ] **Step 3: Run frontend typecheck + build**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/frontend && node_modules/.bin/tsc --noEmit
node node_modules/next/dist/bin/next build
```

- [ ] **Step 4: Fix any issues + final commit**

```bash
git add -A && git commit -m "chore: SP3 final cleanup"
```
