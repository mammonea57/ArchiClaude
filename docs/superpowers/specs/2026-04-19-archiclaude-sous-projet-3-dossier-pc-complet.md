# ArchiClaude — Sous-projet 3 : Génération du dossier PC complet (PCMI)

**Document de spécification — Design validé**
Date : 2026-04-19
Statut : validé par l'utilisateur, prêt pour génération du plan d'implémentation

---

## 1. Contexte et objectif

### 1.1 Objectif

Produire automatiquement le **dossier complet du permis de construire** (PCMI 1 à 8) conforme au code de l'urbanisme français, exportable en PDF unique ou ZIP avec pièces séparées, prêt pour dépôt en mairie ou sur plateforme dématérialisée (Plat'AU, etc.).

### 1.2 Périmètre

Le SP3 s'appuie sur les modules SP1 et SP2 existants :
- SP1 fournit : parcelles, PLU numérique, faisabilité, compliance, notice architecte Opus, photos de site
- SP2 fournit : plans masse, plans de niveaux (cotations complètes PC), coupes, façades en SVG + DXF

Le SP3 ajoute :
1. **PCMI1** — Plan de situation IGN (Scan 25 par défaut + Plan IGN v2 en alternative toggle)
2. **PCMI4** — Notice architecturale formatée selon l'article R.431-8 (générée via adaptation du prompt Opus existant, 2 formats en 1 appel)
3. **PCMI7/PCMI8** — Photographies d'environnement proche et lointain (depuis Mapillary/Street View déjà intégré)
4. **Cartouche PC normé ArchiClaude** appliqué à chaque pièce graphique
5. **Assemblage PDF unique** (dossier navigable) + **ZIP avec pièces séparées** (Plat'AU)
6. **Export reportlab** pour plans (contrôle format ISO) + **WeasyPrint** pour notice

### 1.3 Principe cartouche — signature ArchiClaude

Le cartouche PC est **conforme réglementairement** (pétitionnaire, architecte, références cadastrales, échelle, date, indice révision) + **signé ArchiClaude** (petit watermark "Généré par ArchiClaude — archiclaude.app" en bas du cartouche) pour pub indirecte. Conformité préservée.

### 1.4 Pièces du dossier

| Pièce | Contenu | Source | Format |
|---|---|---|---|
| **PCMI1** | Plan de situation IGN Scan 25 avec cercle rouge + polygone parcelle | IGN WMTS | A4 portrait |
| **PCMI2a** | Plan de masse | SP2 `plan_masse.py` | A3 paysage |
| **PCMI2b** | Plans de niveaux (RDC + étage courant + dernier niveau) cotations complètes | SP2 `plan_niveau.py` enrichi | A1 paysage |
| **PCMI3** | Plan en coupe du terrain et de la construction | SP2 `coupe.py` | A3 paysage |
| **PCMI4** | Notice architecturale R.431-8 (5 sections) | SP1 Opus adapté | A4 portrait texte |
| **PCMI5** | Plans des façades (minimum 4 côtés : nord/sud/est/ouest) | SP2 `facade.py` étendu | A3 paysage |
| **PCMI6** | Document graphique insertion paysagère | **Reporté SP4** (Rendair/ReRender) | — |
| **PCMI7** | Photographie environnement proche | Mapillary/Street View | A4 paysage |
| **PCMI8** | Photographie environnement lointain | Mapillary/Street View | A4 paysage |

---

## 2. Architecture modulaire

### 2.1 Nouveau package `core/pcmi/`

```
apps/backend/core/pcmi/
├── __init__.py
├── schemas.py                 # PcmiPiece, PcmiDossier dataclasses
├── situation.py               # PCMI1 — plan situation IGN (Scan 25 + Plan IGN v2)
├── facades.py                 # PCMI5 — 4 façades automatiques depuis volume 3D
├── photos.py                  # PCMI7/8 — récupération + crop photos d'environnement
├── notice_pcmi4.py            # PCMI4 — adaptation notice Opus format R.431-8
├── cartouche_pc.py            # Cartouche PC normé ArchiClaude avec signature
└── assembler.py               # Assemblage PDF unique + ZIP
```

### 2.2 Renderers PDF

```
apps/backend/core/programming/plans/
├── renderer_svg.py            # existant
├── renderer_dxf.py            # existant
└── renderer_pdf.py            # NOUVEAU — reportlab pour plans
```

### 2.3 Worker ARQ

```
apps/backend/workers/pcmi.py   # Job async generate_pcmi_dossier
```

Durée estimée : 10-30 secondes pour un dossier complet (fetch IGN + génération 8 PDF + assemblage).

### 2.4 Endpoints API

```
POST   /projects/{id}/pcmi/generate           → 202 {job_id}
GET    /projects/{id}/pcmi/status             → {status, piece_en_cours}
GET    /projects/{id}/pcmi/{piece}            → SVG (PCMI1, 2a, 2b, 3, 5, 7, 8)
GET    /projects/{id}/pcmi/{piece}/pdf        → PDF individuel
GET    /projects/{id}/pcmi/dossier.pdf        → PDF unique complet
GET    /projects/{id}/pcmi/dossier.zip        → ZIP pièces séparées
PATCH  /projects/{id}/pcmi/settings           → {map_base: "scan25"|"planv2", revision: "A"|"B"...}
```

---

## 3. PCMI1 — Plan de situation

### 3.1 Fonds cartographiques

Deux fonds IGN disponibles via WMTS :

**Fond 1 — IGN Scan 25 (défaut, conformité PC)** :
- Layer WMTS : `GEOGRAPHICALGRIDSYSTEMS.MAPS.SCAN25TOUR.CV`
- URL : `https://data.geopf.fr/wmts`
- Échelle : 1/25000 (standard PC)
- Style : carte topographique traditionnelle noir/blanc/couleurs IGN

**Fond 2 — IGN Plan v2 (alternative)** :
- Layer WMTS : `GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2`
- Même URL
- Style : plan moderne multi-échelle

**Toggle utilisateur** : `PATCH /projects/{id}/pcmi/settings` avec `{map_base: "scan25" | "planv2"}`. Défaut = `scan25` pour conformité.

### 3.2 Marquage de la parcelle

Méthode combinée cercle + polygone :
- **Cercle rouge** : centré sur le centroïde de la parcelle, rayon adaptatif (50-150m selon taille), épaisseur trait 1.5mm, couleur `#FF0000`
- **Polygone rouge** : contour exact de toutes les parcelles du projet, trait fin 0.5mm, couleur `#CC0000`

Double marquage : le cercle attire l'œil pour localisation, le polygone donne la précision exacte.

### 3.3 Format

- A4 portrait (210×297mm)
- Marges 10mm + 40mm en pied pour cartouche
- Échelle 1/25000 centrée sur la parcelle
- Zone carte ~200×230mm
- Orientation nord en haut du plan
- Légende en bas à gauche (échelle graphique + flèche nord)

---

## 4. PCMI4 — Notice architecturale R.431-8

### 4.1 Structure imposée (article R.431-8 du code de l'urbanisme)

Cinq sections obligatoires :

1. **Terrain et ses abords** — topographie, végétation existante, bâti environnant, accès existants, réseaux disponibles
2. **Projet dans son contexte** — insertion urbaine (gabarit voisinage), insertion architecturale (style, matériaux), insertion paysagère (espaces verts)
3. **Composition du projet** — volumes, façades, toitures, ouvertures, matériaux et couleurs
4. **Accès et stationnement** — desserte véhicules et piétons, nombre de places, accessibilité PMR
5. **Espaces libres et plantations** — % pleine terre, essences prévues, gestion des eaux pluviales

### 4.2 Ton et style

Formel, factuel, administratif. Ton qui rassure l'instructeur :
- Pas d'"opportunités" ni "alertes" (ça c'est dans la note interne)
- Description objective du projet
- Références normatives précises (articles PLU cités)
- Vocabulaire architectural précis (faîtage, acrotère, gabarit-enveloppe, etc.)
- Longueur cible : 500-900 mots

### 4.3 Prompt Opus adaptatif

Un seul appel Opus produit les deux formats :

```python
# Modification de core/analysis/architect_analysis.py
# Le prompt existant est enrichi pour produire un JSON avec 2 clés
{
  "note_opportunite_md": "## Synthèse...",  # existant pour rapport interne
  "notice_pcmi4_md": "## 1. Terrain et ses abords..."  # nouveau pour dossier PC
}
```

Le prompt enrichi demande explicitement les deux formats avec leurs structures. Même contexte injecté (faisabilité, compliance, RAG, etc.) → cohérence garantie entre les deux documents.

Coût LLM : identique (même appel, output plus long mais pas doublé).

### 4.4 Rendu PDF

Template Jinja2 `core/pcmi/templates/notice_pcmi4.html.j2` :
- A4 portrait
- Typo Inter 11pt, titres Playfair Display 14pt
- Sections numérotées 1 à 5 avec titres automatiques
- Pagination
- Cartouche PC en pied de page
- Rendu via **WeasyPrint** (meilleur pour texte mis en page)

---

## 5. PCMI5 — Façades (extension SP2)

### 5.1 Règle réglementaire

Un dossier PC doit présenter **toutes les façades du projet** — minimum nord/sud/est/ouest pour un bâtiment compact, plus pour formes complexes.

### 5.2 Extension du module SP2 facade.py

Actuellement `facade.py` génère une façade à la fois. On ajoute :

```python
def generate_all_facades(*, footprint: Polygon, nb_niveaux: int, 
                          hauteur_par_niveau: float, orientations: list[dict],
                          detail: str = "pc_norme", format: str = "svg") -> dict[str, str]:
    """Generate facades for all 4 cardinal orientations.
    
    Returns dict: {"nord": svg_str, "sud": ..., "est": ..., "ouest": ...}
    """
```

L'algorithme :
1. Pour chaque orientation (N, S, E, O), identifier les segments du footprint qui correspondent
2. Générer la façade pour la projection orthogonale dans cette direction
3. Positionner les ouvertures (fenêtres, portes) selon la distribution intérieure SP2
4. Indiquer les matériaux en légende (béton enduit, bois, vitrage, etc.)

### 5.3 Format PDF

4 façades sur un seul plan A3 paysage, disposées en grille 2×2 :
```
┌─────────────┬─────────────┐
│  FAÇADE NORD │  FAÇADE SUD │
├─────────────┼─────────────┤
│  FAÇADE EST  │ FAÇADE OUEST│
└─────────────┴─────────────┘
```

Chaque façade cotée (hauteurs, largeurs) avec échelle 1/100.

---

## 6. PCMI7 / PCMI8 — Photographies

### 6.1 Sources

Réutilise les modules SP2 existants :
- `core/sources/mapillary.py` — photos contributives haute résolution
- `core/sources/google_streetview.py` — fallback quand Mapillary insuffisant

### 6.2 PCMI7 — environnement proche (rayon 30-50m)

Photo prise depuis la voie publique, **montrant le terrain** et les bâtiments immédiatement voisins. Crop automatique centré sur la parcelle.

### 6.3 PCMI8 — environnement lointain (rayon 200-500m)

Photo plus large, vue d'ensemble du quartier. Street View zoom out ou plusieurs photos Mapillary assemblées.

### 6.4 Traitement

```python
# core/pcmi/photos.py
async def fetch_photo_environnement_proche(lat, lng) -> bytes:  # JPEG
    """Get best photo showing the parcel from nearby street view."""

async def fetch_photo_environnement_lointain(lat, lng) -> bytes:
    """Get wider context photo (neighborhood overview)."""
```

Annotations optionnelles : flèche rouge pointant vers la parcelle (comme pour PCMI1).

### 6.5 Format PDF

A4 paysage, une photo par page, avec :
- Photo occupant 80% de la page
- Légende sous la photo ("Environnement proche — vue depuis la rue X" ou "Environnement lointain — vue aérienne du quartier Y")
- Date de la photo + source
- Cartouche PC en pied

---

## 7. Cartouche PC normé ArchiClaude

### 7.1 Contenu réglementaire

Bloc cartouche de 40mm de haut, pleine largeur de la page, avec :

```
┌─────────────────────────────────────────────────────────────────────────┐
│ [Logo agence]  PROJET : [Nom du projet]           │ PCMI2 — Plan masse │
│                ADRESSE : [Adresse complète]        │ Échelle : 1/500    │
│                PARCELLES : [INSEE section numero]  │ Date : JJ/MM/AAAA   │
│                                                    │ Indice : A         │
├────────────────────────────────────────────────────┴────────────────────┤
│ Pétitionnaire : [nom, adresse, contact]                                │
│ Architecte : [nom, N° ordre, contact]        Généré par ArchiClaude —  │
│                                              archiclaude.app            │
└─────────────────────────────────────────────────────────────────────────┘
```

### 7.2 Signature ArchiClaude (pub indirecte)

- Texte petit (7pt) en bas à droite : "Généré par ArchiClaude — archiclaude.app"
- Optionnel : logo ArchiClaude miniature (15×15mm)
- Discret mais visible — ne gêne pas la lecture des infos légales

### 7.3 Indice de révision

Auto-incrémenté à chaque régénération du dossier :
- Première génération : indice **A**
- Régénération : **B**, **C**, **D**...
- Stocké dans `reports` table (SP1 Phase 7 existant, champ `indice_revision` à ajouter)

### 7.4 Pré-remplissage depuis le profil

Pétitionnaire et architecte sont pré-remplis depuis `agency_settings` (SP1 existant). L'utilisateur peut surcharger par projet via le frontend.

### 7.5 Module `core/pcmi/cartouche_pc.py`

```python
@dataclass
class CartouchePC:
    nom_projet: str
    adresse: str
    parcelles_refs: list[str]  # ["94052-AB-0042", ...]
    petitionnaire: dict  # {nom, adresse, contact}
    architecte: dict | None
    piece_num: str  # "PCMI2"
    piece_titre: str  # "Plan de masse"
    echelle: str  # "1/500"
    date: str
    indice: str  # "A", "B"...
    logo_agence_url: str | None = None

def render_cartouche_svg(cartouche: CartouchePC, width_mm: float = 297) -> str:
    """Generate SVG cartouche block (height 40mm)."""

def apply_cartouche_to_pdf_page(canvas, cartouche: CartouchePC):
    """reportlab canvas: draw cartouche block at bottom of page."""
```

---

## 8. Assemblage — PDF unique + ZIP

### 8.1 PDF unique

```
dossier-pc-{nom-projet}.pdf
├── Couverture (page 1) — titre projet + logo agence + indice
├── Sommaire (page 2) — liste des pièces avec numéros de page
├── PCMI1 — Plan de situation
├── PCMI2 — Plan de masse + plans de niveaux
├── PCMI3 — Coupe
├── PCMI4 — Notice architecturale
├── PCMI5 — Façades
├── PCMI7 — Photo environnement proche
└── PCMI8 — Photo environnement lointain
```

- Signets PDF pour navigation entre pièces
- Pagination continue
- Généré via `pypdf.PdfWriter.append()` qui concatène les PDF individuels

### 8.2 ZIP avec pièces séparées

```
dossier-pc-{nom-projet}.zip
├── 00-couverture.pdf
├── PCMI1-plan-situation.pdf
├── PCMI2a-plan-masse.pdf
├── PCMI2b-plans-niveaux.pdf
├── PCMI3-coupe.pdf
├── PCMI4-notice-architecturale.pdf
├── PCMI5-facades.pdf
├── PCMI7-photo-proche.pdf
├── PCMI8-photo-lointaine.pdf
└── README.txt  — liste des pièces + instructions dépôt
```

Format exigé par certaines plateformes de dépôt dématérialisé (Plat'AU).

### 8.3 Stockage R2

Les deux fichiers sont uploadés sur Cloudflare R2 (SP1 existant). URLs signées 24h fournies au frontend.

### 8.4 Module `core/pcmi/assembler.py`

```python
async def assemble_dossier(
    *,
    pdfs_par_piece: dict[str, bytes],  # {"PCMI1": b"...", "PCMI2a": b"...", ...}
    nom_projet: str,
    cartouche: CartouchePC,
) -> tuple[bytes, bytes]:
    """Assemble both unified PDF and ZIP.
    
    Returns (unified_pdf_bytes, zip_bytes).
    """
```

---

## 9. Rendu PDF — reportlab pour plans, WeasyPrint pour notice

### 9.1 Plans (PCMI1, 2, 3, 5, 7, 8) — reportlab

**Pourquoi reportlab pour les plans** :
- Contrôle exact des formats ISO (A0, A1, A3, A4) avec marges précises
- Contrôle pixel-perfect des unités en mm
- Meilleur rendu des grands formats (A1 pour plans niveaux détaillés)
- Gestion native des calques pour impression

**Pipeline** : SVG généré par SP2 → conversion en drawing reportlab via `svglib` → intégration dans canvas A3/A1 avec cartouche → output PDF bytes.

```python
# core/programming/plans/renderer_pdf.py
def svg_to_pdf(svg_string: str, *, format: str = "A3", orientation: str = "landscape",
                cartouche: CartouchePC) -> bytes:
    """Convert SVG to A-format PDF with cartouche."""
    from reportlab.graphics import renderPDF
    from svglib.svglib import svg2rlg
    from reportlab.pdfgen import canvas
    from io import BytesIO
    # ... implementation
```

Nouvelles dépendances :
- `reportlab>=4.0`
- `svglib>=1.5`

### 9.2 Notice PCMI4 — WeasyPrint (existant)

WeasyPrint reste parfait pour les documents textuels avec HTML/CSS `@page`. Aucune nouvelle dépendance, SP1 Phase 7 déjà en place.

Template Jinja2 sobre :
```html
<!DOCTYPE html>
<html>
<head><style>
  @page { size: A4; margin: 20mm 15mm 50mm 15mm; }
  @page { @bottom-center { content: element(cartouche); } }
  body { font-family: Inter, sans-serif; font-size: 11pt; }
  h1 { font-family: "Playfair Display", serif; font-size: 18pt; }
  h2 { font-size: 14pt; margin-top: 20px; }
</style></head>
<body>
  <h1>{{ nom_projet }} — Notice architecturale</h1>
  {{ notice_pcmi4_md_html | safe }}
  <div class="cartouche">{{ cartouche_html | safe }}</div>
</body>
</html>
```

---

## 10. Pipeline d'exécution

### 10.1 Pipeline détaillé

```
POST /projects/{id}/pcmi/generate
       │
       ▼
┌─────────────────────────────────────────────────────┐
│ 1. Collecte données existantes SP1/SP2             │
│    ├─ Parcelles (ids, géométries WGS84/L93)        │
│    ├─ NumericRules + Brief                         │
│    ├─ FeasibilityResult (SDP, niveaux, etc.)       │
│    ├─ Scenario sélectionné (footprint, niveaux)   │
│    ├─ Plans SVG (masse, niveaux, coupe)            │
│    ├─ Notice Opus (JSON 2 formats)                 │
│    └─ Photos Mapillary/Street View                 │
└─────────────┬───────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────┐
│ 2. Génération pièces parallèle (asyncio.gather)    │
│    ├─ PCMI1 : fetch IGN WMTS + overlay parcelle    │
│    ├─ PCMI2 : SVG existants (SP2)                  │
│    ├─ PCMI3 : SVG existant (SP2)                   │
│    ├─ PCMI4 : notice Opus.notice_pcmi4_md          │
│    ├─ PCMI5 : generate_all_facades (4 côtés)       │
│    ├─ PCMI7 : fetch_photo_environnement_proche     │
│    └─ PCMI8 : fetch_photo_environnement_lointain   │
└─────────────┬───────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────┐
│ 3. Rendu PDF par pièce (parallèle)                 │
│    ├─ reportlab pour plans (PCMI1,2,3,5,7,8)      │
│    └─ WeasyPrint pour notice (PCMI4)              │
│    + cartouche PC appliqué sur chaque page        │
└─────────────┬───────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────┐
│ 4. Assemblage (core/pcmi/assembler.py)             │
│    ├─ pypdf merge → dossier-pc.pdf                 │
│    └─ zipfile → dossier-pc.zip                     │
└─────────────┬───────────────────────────────────────┘
              ▼
┌─────────────────────────────────────────────────────┐
│ 5. Upload R2 + DB                                   │
│    ├─ Upload dossier-pc.pdf → R2                   │
│    ├─ Upload dossier-pc.zip → R2                   │
│    ├─ Insert reports row (format="pcmi_complet")   │
│    └─ Notify job done                              │
└─────────────────────────────────────────────────────┘
```

### 10.2 État et reprises

Table `pcmi_dossiers` (nouveau) :
```sql
CREATE TABLE pcmi_dossiers (
    id UUID PRIMARY KEY,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    status TEXT NOT NULL,  -- queued, generating, done, failed
    indice_revision TEXT NOT NULL,  -- A, B, C...
    map_base TEXT DEFAULT 'scan25',
    pdf_unique_r2_key TEXT,
    zip_r2_key TEXT,
    pieces_status JSONB,  -- {PCMI1: "done", PCMI2: "generating", ...}
    error_msg TEXT,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (project_id, indice_revision)
);
```

---

## 11. Frontend

### 11.1 Nouvelle page `/projects/[id]/pcmi`

**Layout** :
- Header : statut de génération (pas généré / en cours X% / disponible)
- Toggle fond carte PCMI1 (Scan 25 / Plan IGN v2)
- Bouton "Générer le dossier PC"
- Preview des 8 pièces en carrousel (SVG affiché)
- Deux boutons télécharger : "PDF unique" + "ZIP séparé"
- Historique des révisions (A, B, C) avec date et possibilité de re-télécharger

### 11.2 Nouveaux composants frontend

```
apps/frontend/src/components/pcmi/
├── PcmiGenerator.tsx         # Bouton + état progression
├── PcmiPreview.tsx           # Carrousel SVG des pièces
├── PcmiDownloadButtons.tsx   # Download PDF + ZIP
├── SituationMapSelector.tsx  # Toggle Scan 25 / Plan IGN v2
└── RevisionHistory.tsx       # Liste indices A, B, C...
```

### 11.3 Intégration rapport existant

Dans `/projects/[id]/report`, ajouter une section "Dossier PC" avec :
- Statut (non généré / disponible)
- Bouton "Générer / Régénérer" → redirige vers `/projects/[id]/pcmi`
- Lien téléchargement rapide si déjà généré

---

## 12. Critères de succès

| Critère | Seuil |
|---|---|
| Pièces générées | 100% des 7 pièces (PCMI1, 2a, 2b, 3, 4, 5, 7, 8) pour un projet standard |
| Conformité PCMI1 | Fond IGN Scan 25 correctement téléchargé, cercle + polygone visibles, échelle 1/25000 respectée |
| Conformité PCMI4 | Notice contient les 5 sections R.431-8 dans l'ordre, longueur 500-900 mots, lexique formel |
| Conformité cartouche | Tous les champs obligatoires présents (pétitionnaire, architecte, refs cadastrales, échelle, date, indice) + signature ArchiClaude |
| PDF unique | Tous PCMI concaténés, signets navigables, pagination continue |
| ZIP | Un PDF par pièce + README.txt présent |
| Durée génération | P95 ≤ 30 secondes pour dossier complet |
| Format PDF | A1/A3/A4 respectés, marges 10-20mm, rendu vectoriel net |
| Indice de révision | Auto-incrémente à chaque régénération (A → B → C…) |
| Signature ArchiClaude | Présente sur 100% des pièces graphiques |

---

## 13. Contraintes techniques

### 13.1 Nouvelles dépendances

```
reportlab>=4.0           # PDF génération plans avec contrôle format
svglib>=1.5              # Conversion SVG → reportlab drawing
Pillow>=10.0             # Traitement images photos PCMI7/8 (crop, annotations)
```

### 13.2 Limites techniques

- PCMI6 (insertion paysagère photomontage) **hors scope** — reporté SP4 (Rendair/ReRender AI)
- Formulaires Cerfa 13406/13409 **hors scope** — v1.1 éventuelle
- Signature manuscrite architecte — nécessite intégration DocuSign ou équivalent — v1.1

### 13.3 Sécurité

- URLs R2 signées 24h pour les PDF (pas d'accès public permanent)
- Cartouche contient des données personnelles (pétitionnaire) — chiffrement transit HTTPS obligatoire

---

## Fin du document
