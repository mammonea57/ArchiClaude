# ArchiClaude — Sous-projet 2 v2 : Rendu architectural de niveau professionnel

**Date :** 2026-04-19
**Statut :** Design validé, prêt pour plan d'implémentation
**Sous-projet :** SP2-v2 (remplace SP2-v1 entièrement, intègre et unifie SP4 PCMI6)

## 1. Motivation

La version 1 (SP2 Programmation architecturale) produit des plans ressemblant à "des rectangles juxtaposés" (constat utilisateur). Les sorties actuelles :
- Plans 2D : polygones simples avec hachures basiques, pas de symboles normalisés, pas de cotations, pas de cartouche NF
- PCMI1-8 : stubs textuels minimaux (`<svg><text>PCMI3 — Plan en coupe</text></svg>`)
- Insertion paysagère (PCMI6) : simple volume cubique Three.js sur fond uni, aucun photoréalisme
- Pas de modèle 3D BIM ni d'export IFC pour interop Archicad/Revit

Ce niveau de qualité est incompatible avec les attentes d'un promoteur immobilier confronté à des décisions de 5 à 50 M€. L'ambition affichée : **outil de rendu architectural le plus avancé d'Europe pour le marché promoteur français**, capable de produire à la fois des plans techniques prêts pour dépôt PC en mairie et des rendus marketing photoréalistes pour investisseurs / commercialisation.

## 2. Décisions de design retenues (synthèse du brainstorming)

| Décision | Choix | Implication |
|----------|-------|-------------|
| Format de sortie | **A+B** — plans techniques PC + rendus marketing 3D depuis le même modèle | Modèle sémantique unique, deux pipelines de rendu |
| Génération modèle sémantique | **C+D** — solveur algorithmique + LLM + bibliothèque de templates | Robustesse + flexibilité + qualité |
| Scope | **Full stack** — plans 2D + 3D + insertion paysagère SDXL internalisée | SDXL self-hosted Modal dès v1 (pas post-v1) |
| Sources des templates | **A+B+C+D** — manuel + scraping + LLM pur + LLM-augmenté | ~185 templates, enrichissement continu |
| Moteur 3D + rendu photo | **Pipeline hybride** — CADQuery + IFC + Blender EEVEE + SDXL Lightning + ControlNet + Real-ESRGAN + Three.js | Qualité archviz, interop BIM, <1.5 min par projet |
| Éditabilité utilisateur | **Hybride** — paramétrique (sliders) + WYSIWYG simplifié (drag cloisons) | Contrôle promoteur sans expertise CAD |

## 3. Objectifs mesurables

### Qualité

- Review aveugle par 3 architectes IDF indépendants : **≥70 %** des plans 2D jugés "professionnels au premier regard"
- 100 % des plans respectent les normes NF pour épaisseurs de trait, symboles, cotations
- **0 erreur** réglementaire PMR / incendie / PLU détectable sur un jeu de 20 projets test
- CLIP score des renders 3D ≥ 0.28 (alignement prompt-image)
- A/B test insertion paysagère : **≥50 %** des utilisateurs non-avertis ne détectent pas le caractère synthétique

### Performance

- Pipeline complet (BuildingModel + plans + IFC + GLTF + 8 renders) : **<1.5 min** end-to-end
- Drag cloison dans l'éditeur : **<100 ms** de latence UI
- Régénération après édition : plans 2D **<10 s**, renders 3D **<30 s**

### Adoption

- 3 mois après ship : 80 % des projets utilisent SP2-v2
- NPS utilisateur ≥ 50
- ≥3 dossiers PC réels déposés en mairie et acceptés sans retouche archi externe

## 4. Architecture globale

### 4.1 Vue d'ensemble

```
┌────────────────────────────────────────────────────────────────────┐
│                         FRONTEND Next.js                            │
│  ┌──────────────────┐  ┌──────────────────┐  ┌─────────────────┐  │
│  │ Plans viewer 2D  │  │ 3D preview       │  │ Editor WYSIWYG  │  │
│  │ (SVG interactif) │  │ (Three.js GLTF)  │  │ (walls drag)    │  │
│  └──────────────────┘  └──────────────────┘  └─────────────────┘  │
└────────────────────────────────────┬───────────────────────────────┘
                                     │ REST + WebSocket live updates
┌────────────────────────────────────┴───────────────────────────────┐
│                      BACKEND FastAPI                                │
│  ORCHESTRATEUR (core/building_model/) — solveur + LLM + templates  │
│         ↓                     ↓                      ↓              │
│  LIBRAIRIE TEMPLATES    GÉNÉRATEURS 2D         EXPORT MULTI-FORMAT │
│  (~185 templates)       (SVG, PDF, DXF)        (SVG/PDF/DXF/IFC)   │
│                                                                     │
│  MOTEUR 3D CADQuery → IFC + GLTF → worker Modal GPU                │
└─────────────────────────────────────┬───────────────────────────────┘
                                      ↓
                     ┌────────────────────────────────┐
                     │  WORKER MODAL (GPU A10G ×8)     │
                     │  Blender EEVEE + SDXL Lightning │
                     │  + ControlNet + Real-ESRGAN     │
                     │  Warm container, ~25s/render    │
                     └────────────────────────────────┘
```

### 4.2 Nouveaux modules

**Backend** (remplacent `core/programming/` et unifient avec `core/rendering/`)
- `core/building_model/` — solveur placement + modèle sémantique + validation
- `core/templates_library/` — banque de templates + index vectoriel + recherche
- `core/rendering_v2/plans_2d/` — générateurs SVG/PDF/DXF professionnels
- `core/rendering_v2/model_3d/` — CADQuery → IFC + GLTF
- `workers/render_gpu.py` — worker Modal pour Blender + SDXL

**Frontend**
- `apps/frontend/src/app/projects/[id]/editor/` — page éditeur unifiée
- `apps/frontend/src/components/plans_viewer/` — viewer SVG 2D interactif
- `apps/frontend/src/components/wysiwyg_editor/` — éditeur drag & drop

### 4.3 Dépendances techniques

**Nouvelles dépendances Python**
- `cadquery >= 2.4` — CAD paramétrique
- `ifcopenshell >= 0.7` — export IFC 4
- `bpy == 4.2` — Blender en tant que module Python
- `diffusers >= 0.28`, `transformers`, `accelerate`, `xformers` — SDXL
- `modal >= 0.63` — orchestration GPU serverless
- `or-tools >= 9.10` — solveur CSP
- `ezdxf >= 1.2`, `weasyprint >= 60`, `svgwrite` — export 2D
- `flatbush`, `rtree` — spatial indexes
- Extension Postgres `pgvector` pour embeddings

**Nouvelles dépendances frontend**
- `react-konva` — canvas 2D interactif éditeur
- `@use-gesture/react` — drag/pinch gestures
- `immer` — state immutable pour undo/redo
- `jotai` ou `zustand` — state management éditeur

**Nouveaux services externes**
- Modal.com — GPU serverless ($0.000596/s sur A10G), auto-scale
- Supabase Storage — renders + IFC + PDF persistés
- Anthropic API Claude Opus — sélection templates + génération exotique

## 5. Modèle bâtiment sémantique (BuildingModel JSON)

Structure unique source de vérité, alimente tous les renderers.

### 5.1 Hiérarchie complète

```
BuildingModel
├── metadata (id, project_id, address, version, locked)
├── site (parcelle_geojson, surface, voirie_orientations, north_angle_deg)
├── envelope (footprint, emprise_m2, niveaux, hauteurs, toiture)
├── core (escalier, ascenseur, gaines — position centrale du bâtiment)
├── niveaux[] (ordonnés RDC → dernier étage)
│   └── cellules[] (logements / commerces / parking / local_commun)
│       └── rooms[] (pour logements : entrée, séjour, cuisine, chambres, SDB, WC...)
│       └── walls[] (porteur ou cloison, avec thickness, matériau)
│       └── openings[] (portes + fenêtres avec swing, allège, dim, vitrage)
│       └── furniture[] (mobilier, pour rendus marketing)
│   └── circulations_communes[] (paliers, couloirs, largeur ≥140 cm PMR)
├── facades (composition N/S/E/O, styles, matériaux, RGB)
├── materiaux_rendu (catalogue PBR pour Blender/SDXL)
└── conformite_check (alerts PMR/incendie/PLU, calculé)
```

### 5.2 Typologies autorisées

**12 types de pièces** : `entree`, `sejour`, `sejour_cuisine`, `cuisine`, `sdb`, `salle_de_douche`, `wc`, `wc_sdb`, `chambre_parents`, `chambre_enfant`, `chambre_supp`, `cellier`, `placard_technique`, `loggia`

**5 types de murs** : `porteur`, `cloison_70`, `cloison_100`, `doublage_isolant`, `fenetre_baie`

**Types de cellules** : `logement`, `commerce`, `tertiaire`, `parking`, `local_commun`

### 5.3 Contraintes réglementaires validées automatiquement

- **PMR** : passage min 80 cm portes, rotation cercle 150 cm dans chaque pièce de vie, ascenseur obligatoire ≥R+2, 100 % logements accessibles
- **Incendie** : distance max porte logement → sortie de secours ≤25 m, couloirs communs ≥140 cm
- **PLU** : emprise ≤ max, hauteur ≤ max, retraits respectés, % pleine terre respecté
- **Surfaces** : cohérence SHAB (loi Boutin) / SDP (code urba), ratio loi Carrez
- **Ventilation** : fenêtre ≥ 1/8 surface pour pièces de vie
- **Lumière** : toutes pièces de vie ont fenêtre extérieure (pas sur palier)

### 5.4 Stockage Postgres

```sql
CREATE TABLE building_models (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version INT NOT NULL DEFAULT 1,
    model_json JSONB NOT NULL,
    conformite_check JSONB,
    generated_at TIMESTAMP NOT NULL DEFAULT now(),
    generated_by UUID REFERENCES users(id),
    source VARCHAR(20) NOT NULL, -- 'auto' | 'user_edit' | 'regen'
    parent_version_id UUID REFERENCES building_models(id),
    dirty BOOLEAN DEFAULT FALSE,
    UNIQUE(project_id, version)
);
CREATE INDEX idx_building_models_project ON building_models(project_id);
CREATE INDEX idx_building_models_model_json ON building_models USING GIN (model_json);
```

## 6. Librairie de templates (A+B+C+D)

Fondation de la qualité : chaque appartement est construit à partir d'un template de distribution validé.

### 6.1 Schéma d'un template

```
Template
├── id (ex: "T3_traversant_ns_v3")
├── source (manual | scraped | llm_gen | llm_augmented)
├── typologie (T1..T5)
├── surface_shab_range [min, max]
├── orientation_compatible (nord-sud, est-ouest...)
├── position_dans_etage (angle | milieu | extremite)
├── dimensions_grille (largeur/profondeur min/max en m, adaptable_3x3)
├── topologie
│   ├── rooms[] (type, area_ratio, bounds_cells relatives à grille abstraite)
│   ├── walls_abstract[] (type, from_cell, to_cell, side)
│   └── openings_abstract[] (type, wall_idx, position_ratio, paramètres)
├── furniture_defaults (par type de pièce)
├── reglementaire_ok (PMR/ventilation/lumière pré-validés)
├── tags (recherche sémantique)
├── rating (manual_votes, usage_count, success_rate)
├── embedding (vecteur 1536-dim pour pgvector)
└── preview_svg (thumbnail auto-généré)
```

### 6.2 Stratégie multi-sources (cible ~185 templates)

| Source | Cible | Effort | Description |
|--------|-------|--------|-------------|
| **A manuel** | 20 | 2 semaines | Dessinés à la main, couvrent 80 % des cas IDF (T2 mono/bi/angle, T3 traversant/angle/compact, T4 traversant/angle/duplex, T5 traversant/duplex, studios, T1, spéciaux PMR) |
| **B scraping** | 100 | 2 semaines + review | Extraction depuis dossiers PC publics des mairies IDF (Paris, Boulogne, Issy, Levallois, Neuilly, Nanterre, Montrouge, Vincennes, Nogent). Pipeline : crawler → OCR + CV (YOLOv8 + Tesseract) → reconstruction JSON → validation. **N'extraire que la topologie anonyme** (pas le style, cartouche, noms). |
| **C LLM pur** | 15 | 3 jours | Claude Opus génère des templates exotiques depuis description textuelle + exemples A. Cible : T4 duplex, T5 mezzanine, T3 tour, lofts, T4 PMR. |
| **D LLM-augmenté** | 50 | 1 semaine | Variations de templates manuels via Claude (ex : inverser séjour/chambres, ajouter bureau, redécouper bain+WC). |
| **Total** | ~185 | ~5 semaines parallèles | |

### 6.3 Stockage + recherche

```sql
CREATE TABLE templates (
    id TEXT PRIMARY KEY,
    typologie VARCHAR(10) NOT NULL,
    source VARCHAR(20) NOT NULL,
    json_data JSONB NOT NULL,
    preview_svg TEXT,
    embedding vector(1536),
    rating_avg NUMERIC(3,2),
    usage_count INT DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT now(),
    created_by UUID REFERENCES users(id)
);
CREATE INDEX idx_templates_embedding ON templates USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX idx_templates_typologie ON templates(typologie);
```

**Recherche au runtime** : description slot → embedding → pgvector top-10 → filtre contraintes dures → Claude sélectionne + justifie.

### 6.4 Indexeur continu

Worker Modal hebdomadaire : scrape les nouvelles PC déposées sur sites mairies cibles, enrichit la librairie passivement.

### 6.5 Considérations juridiques

Le scraping PC ne doit **jamais** importer :
- Le rendu visuel (protégé droit auteur archi)
- Le cartouche avec identité du cabinet
- Les noms / références commerciales

Il doit importer **uniquement** :
- Topologie anonyme (graphe de pièces et murs)
- Dimensions et surfaces (données factuelles non protégeables)

Consultation avocat spécialisé propriété intellectuelle **avant mise en prod** du scraping (sprint 3).

## 7. Pipeline de génération (brief → BuildingModel)

6 étapes séquentielles, chacune validée avant la suivante.

### 7.1 Étape 1 — Récupération du contexte

Input unifié depuis SP1 :

```python
@dataclass
class SP2V2GenerationInputs:
    project_id: UUID
    parcelle_geojson: dict
    parcelle_surface_m2: float
    voirie_orientations: list[str]
    north_angle_deg: float
    plu_rules: NumericRules
    zone_plu: str
    plu_confidence: float
    brief: Brief
    footprint_recommande_geojson: dict
    niveaux_recommandes: int
    hauteur_recommandee_m: float
    emprise_pct_recommandee: float
    abf_perimetre: bool
    monuments_proximite: list[Monument]
    risques: list[RisqueResult]
    lls_requis_pct: float
    batiments_voisins: list[Batiment]
    altitude_sol_m: float
    mapillary_photos_proximite: list[Photo]
    style_architectural_preference: str | None
    facade_style_preference: str | None
    toiture_type_preference: str | None
    loggias_souhaitees: bool
    commerces_rdc: bool
    parking_type: str
```

### 7.2 Étape 2 — Solveur placement structurel (~2 s)

Sortie : `StructuralGrid` (trame modulaire 3×3 m + noyau + murs porteurs + slots vides pour appartements).

Algorithmes appliqués en cascade :
1. Footprint → grille modulaire 3×3 m, classification cellules voirie / cour
2. Placement noyau optimal (CSP minimise surface commune perdue) — contraintes : distance max porte appt → escalier ≤25 m, noyau central si rectangulaire, excentré si L/T
3. Positionnement murs porteurs (refends tous les 6-8 m max, alignement étage par étage)
4. Découpage en slots appartement (soustraction noyau + circulations, division selon mix brief)

Librairie : `shapely` + OR-Tools CP-SAT. Python pur, déterministe, reproductible.

### 7.3 Étape 3 — Sélection templates par slot (~15-25 s)

Pour chaque slot :
1. Query pgvector : top-10 templates compatibles par similarité sémantique
2. Filtre contraintes dures (surface_range, orientation_compatible, dimensions)
3. Claude Opus sélectionne parmi 10 candidats + justifie en FR + propose 2 alternatives
4. Temp 0.3, seed fixe pour reproductibilité

Coût : ~36 slots × 300 tokens = 11k tokens ≈ 0.06 € par projet.

### 7.4 Étape 4 — Adaptation paramétrique (~5-10 s)

Transformation template abstrait → géométrie réelle via CADQuery :
- Stretch grille template à dimensions slot (tolérance ±15 %, sinon rejet)
- Rotation si orientation ≠ base
- Symétrie miroir si position angle ou opposée
- Dimensionnement des pièces par ratio
- Placement mobilier

Si aucun template ne passe → fallback Étape 5.

### 7.5 Étape 5 — Fallback solveur algorithmique (~10-30 s, cas atypiques)

Binary Space Partitioning avec contraintes :
- `area_target` et `aspect_ratio_max` par pièce
- Pièces humides collées (gaines partagées)
- Chambre parents loin entrée (intimité)
- Séjour face meilleure orientation
- Murs orthogonaux sauf dérogation

Implémentation : Python + Shapely + simulated annealing (50-200 itérations). Flag `fallback_used: true` → review humaine recommandée + suggestion "ajouter template couvrant ce cas" dans feedback loop.

### 7.6 Étape 6 — Validation réglementaire + cohérence inter-étages (~2 s)

Validation individuelle par appartement + inter-étages (cascade structurelle, gaines verticales alignées, cascade façade) + PLU global (emprise, hauteur, retraits, % pleine terre, SDP).

Sortie finale : `BuildingModel` JSON complet avec `conformite_check` rempli.

### 7.7 Durée totale

| Configuration | Temps |
|---------------|-------|
| Pas de fallback | ~30-40 s |
| Avec fallbacks | ~60-90 s |

Pipeline exposé en async avec WebSocket progress updates pour UX fluide.

## 8. Stack de rendering

### 8.1 Plans 2D professionnels

Nouveau module `core/rendering_v2/plans_2d/`. Génération directe BuildingModel JSON → SVG (pas de CADQuery, trop lourd pour le 2D).

**Six types de plans produits** :

| Type | Contenu |
|------|---------|
| PCMI2a Plan de masse | Parcelle + voirie + footprint + cotations PLU + nord + cartouche + servitudes + courbes niveau + arbres |
| Plan niveau (par appartement ou étage combiné) | Murs porteurs/cloisons différenciés + portes avec arcs de débattement + fenêtres avec allèges + meubles + labels pièces + surfaces + cotations intérieures |
| Plan masse RDC avec entourage | Plan + bâtiments voisins + voirie stationnement + espaces verts |
| PCMI3 Coupe | Coupe verticale à travers noyau + niveaux + caves + combles + cotations hauteurs + structure dalles + escalier + terrain naturel + hauteurs PLU référence |
| PCMI5 Façades (×4) | Élévation N/S/E/O : contour + ouvertures + matériaux (hachures) + menuiseries + corniches + acrotères + toiture + TN/TF cotations |
| Plan toiture | Vue dessus : acrotères, évacuations, panneaux, edicules, végétalisation |

**Spécifications NF** :
- Épaisseurs de trait normées (contour 0.70 mm, porteur 0.50 mm, cloison 0.25 mm, mobilier 0.18 mm, cotation 0.13 mm)
- Hachures matériaux (béton fines diagonales, isolant parallèles, maçonnerie brique)
- Symboles normalisés (porte arc ¼ de rayon, fenêtre double ligne, escalier flèche + chiffre marches, cuisine plan de travail L)
- Cotations automatiques (3 lignes extérieures, intérieure par pièce, dimensions ouvertures)
- Cartouche NF (adresse, parcelle, zone PLU, échelle graphique + numérique, nord vrai, phase PC, date, indice, logo, mention validation archi)
- Échelles cibles : masse 1:200 ou 1:500, niveaux 1:100 (ou 1:50 zoom), coupe 1:100, façade 1:100
- SVG propre avec groupes par couche, viewBox en mm, font embarqué IBM Plex Sans

**Librairies** : `svgwrite`, `shapely`, `reportlab` + `svglib` pour PDF, `ezdxf` pour DXF.

### 8.2 Modèle 3D paramétrique

Nouveau module `core/rendering_v2/model_3d/builder.py`. CADQuery construit le mesh 3D complet depuis le BuildingModel.

Construction itérative par niveau :
- Socle / fondation béton (profondeur 80 cm)
- Dalles béton 25 cm entre niveaux
- Murs porteurs extrudés hauteur sous plafond
- Cloisons extrudées
- Soustraction ouvertures (portes + fenêtres)
- Toiture (terrasse / 2 pans / 4 pans / mansarde selon envelope)
- Escalier + ascenseur depuis `bm.core`
- Menuiseries visibles (cadres 3D)

Exports depuis CAD :
- **IFC 4** via IfcOpenShell (Site → Building → Stories → Spaces → Walls → Openings → Furnishings) — téléchargeable par utilisateur, importable Archicad/Revit/BlenderBIM
- **GLTF 2.0** (<5 MB pour R+5) — frontend Three.js preview
- **OBJ + MTL** — base pour Blender headless

### 8.3 Rendu photoréaliste optimisé (<1.5 min par projet)

Worker Modal GPU avec **pipeline 5 leviers cumulés** :

**Niveau 1 — Blender EEVEE (pas Cycles)**
- EEVEE temps réel : 5 s par vue (vs 50 s Cycles)
- Qualité suffisante car SDXL raffine derrière via ControlNet
- **Gain : −45 s par render**

**Niveau 2 — SDXL Lightning (4 steps au lieu de 30)**
- Lightning ou LCM LoRA, qualité équivalente à 30 steps standard
- 6 s par render vs 45 s
- **Gain : −40 s par render**

**Niveau 3 — Résolution 1024² + Real-ESRGAN 4×**
- SDXL natif 1024² : 15 s
- Upscale ESRGAN 4× vers 4096² : 3 s
- Préserve détails archi (lignes droites, matériaux) quasi-parfait
- Sortie 4K net vs 2K précédent
- **Gain : −30 s par render**

**Niveau 4 — Parallélisation 8 workers Modal**
- 8 workers GPU A10G simultanés (auto-scale)
- Chaque worker 1 render → tous démarrent en parallèle
- **Gain : ×8 sur le total (pas per-render)**

**Niveau 5 — Warm container + modèles pré-chargés**
- Modal "keep warm" : Blender + SDXL + ControlNet + ESRGAN pré-chargés en VRAM
- Cold start économisé : −10 s par worker
- Coût fixe : ~0.50 €/jour (négligeable)

**Bilan par render** :

| Étape | Avant | Après |
|-------|-------|-------|
| Blender base | 50 s | **5 s** |
| Depth/canny | 8 s | 2 s |
| SDXL ControlNet | 50 s | **6 s** |
| Upscale 4K | — | 3 s |
| Insertion paysagère (si applicable) | 20 s | 5 s |
| Pipeline load | 10 s (cold) | 0 s (warm) |
| **Per render** | **~120 s** | **~20-25 s** |

**Total 8 renders parallèles** : ~25 s + 20 s orchestration = **~45-60 s**.

### 8.4 Vues générées par bâtiment (8 par défaut)

| Vue | Usage | Paramètres caméra |
|-----|-------|-------------------|
| Perspective nord-est (eye-level) | Marketing, PCMI7 | 1.7 m, 25 m |
| Perspective sud-ouest (eye-level) | Marketing, PCMI8 | 1.7 m, 25 m |
| Axonométrie éclatée | Marketing premium | isométrique 30°, coupe transparence |
| Perspective aérienne | Présentation investisseurs | 40 m, 50 m, drone |
| Intérieur séjour T3 type | Brochure commerciale | 1.5 m, fisheye léger |
| Intérieur cuisine T3 type | Brochure commerciale | 1.4 m |
| Insertion paysagère rue | PCMI6 obligatoire | vue piéton photo source |
| Insertion paysagère cour | PCMI6 complément | |

**Coût par projet** : 8 renders × ~25 s × $0.000596/s = **~$0.12** par projet.

**Coût mensuel estimé** (100 projets/mois) : ~$12 GPU + $15 warm container = **~$27/mois**.

### 8.5 Catalogue matériaux PBR (80 textures)

Stockés `core/rendering_v2/materials_pbr/` — JPG 2048² diffuse + normal + roughness + AO :
- **Enduits** : blanc cassé, beige, sable, gris clair (taloché, gratté, bouchardé)
- **Bardages** : bois mélèze/douglas, composite, zinc patiné, corten, cassette alu
- **Menuiseries** : alu anthracite/blanc/bronze, PVC blanc, bois exotique, mixte alu-bois
- **Toitures** : zinc, tuile plate/mécanique, bac acier, EPDM, sedum végétalisé
- **Sols ext** : béton lissé/désactivé, pavés pierre, dallage bois, gazon + chemin sable

### 8.6 Benchmarks qualité

Tests automatisés sur 20 prompts :
- CLIP score (alignement prompt/image) — target ≥ 0.28
- LPIPS (similarité perceptuelle) — target perte <2 % vs config Cycles référence
- FID (qualité statistique) — target perte <2 %
- Si benchmark fail pour une vue → rollback vers Cycles pour cette vue (dégradation gracieuse, +5 s)

### 8.7 Modes de qualité utilisateur

- **Draft** : Lightning 2 steps, 10 s/render — pour itérations rapides pendant édition
- **Final** : Lightning 4 steps + ESRGAN, 25 s/render — pour export définitif

## 9. Éditeur WYSIWYG + mode paramétrique

Page `/projects/[id]/editor`, layout trois colonnes :

- **Sidebar gauche** : sélecteur mode (Plan 2D, 3D, Coupe, Façades) + sélecteur étage
- **Zone centrale** : viewer interactif (2D SVG avec couches, 3D Three.js GLTF, coupe verticale, vues façades)
- **Panel droit** : paramétrique (sliders / dropdowns) + indicateur conformité temps réel

### 9.1 Mode paramétrique (régénération pipeline complet)

Contrôles :
- **Mix typologique** slider (T1-T5 pourcentages)
- **Niveaux** (3 à max PLU)
- **Orientation globale** (picker 8 directions)
- **Style façade** (galerie : enduit_clair_zinc, bardage_bois, pierre_agrafee, brique_pleine, beton_brut_corten, vetue_verre)
- **Switcher templates** par appartement (depuis les 2 alternatives retenues en étape 3)
- **Options booléennes** : loggias sud, toiture terrasse végétalisée, commerces RDC, parking souterrain

Modification → bouton "Régénérer" → re-run pipeline Section 7 (Étapes 2-6) avec nouveaux params → async job avec progress WebSocket.

### 9.2 Mode WYSIWYG Plan 2D (édition la plus puissante)

Canvas SVG React + **layer system** (react-konva) :
- **Structure** (locked, grisé) : murs porteurs non-modifiables
- **Cloisons** (editable) : drag, delete, split
- **Rooms** (editable) : resize, rename, changeType
- **Openings** (editable) : move, resize, flip swing, delete
- **Furniture** (editable) : drag, rotate, delete
- **Cotations** (locked, auto-recalculées)
- **Annotations** (editable) : notes utilisateur libres

**Interactions clés** :
- Drag cloison → pièces adjacentes auto-redimensionnées, cotations recalculées temps réel
- Resize pièce → murs adjacents bougent, voisines s'adaptent, validation surface mini PMR
- Magnétisme snap 10 cm + alignement automatique
- Contrainte intelligente : mur passant à travers gaine ou pièce <min PMR → blocage + warning
- Catalogue mobilier : drag depuis sidebar, auto-align mur + snap rotation 90°

**Toolbar flottante** : dessiner cloison, ajouter porte, fenêtre, mobilier, note, mesure.

### 9.3 Mode 3D (édition volumétrique)

Three.js + gizmos transform. Permet :
- Rotation / déplacement bâtiment sur parcelle
- Hauteur par étage (drag vertical)
- Type toiture (dropdown)
- Volumes saillants (balcons, loggias, retraits d'attique)
- **Pas d'édition cloisons en 3D** (trop fragile ergonomiquement) → force mode 2D

### 9.4 Mode Coupe

Vue coupe verticale noyau + appartement typique. Permet : hauteurs sous plafond, épaisseur dalles, position escaliers, caves/combles.

### 9.5 Mode Façades

4 onglets N/S/E/O. Permet : style + matériaux, déplacement fenêtres, ajout brise-soleil / persiennes / marquises, composition enduit + pierre + bandeaux.

### 9.6 Validateur temps réel

À chaque modif, validation incrémentale <100 ms dans panel conformité :
- ✅ / ⚠ / ❌ par règle (PMR passage, rotation, incendie distance sortie, SDP, PLU emprise/hauteur)
- Click sur une erreur → highlight sur plan
- Suggestions IA de correction + bouton "appliquer" automatique

Erreurs **bloquent export PC final** mais pas l'édition (état intermédiaire invalide toléré).

### 9.7 Undo/redo + historique

- Stack immuable (Jotai + immer)
- Groupement intelligent (drag = 1 étape, pas 60 pixels)
- Historique persistant : chaque save → nouvelle version dans `building_model_versions` Postgres
- UI sidebar "Historique" avec thumbnail + nom auto
- Branches : partir d'une ancienne version sans perdre actuelle

### 9.8 Régénération après édition

Modif → `dirty: true` sur BuildingModel. Au save :
1. Nouvelle version persistée
2. Job async relance uniquement renders impactés (cloison R+1 → plan R+1 + renders 3D montrant cet étage)
3. Plans 2D SVG régénèrent en <5 s
4. Renders Blender+SDXL régénèrent en 25-60 s en parallèle
5. Notification in-app + email utilisateur quand prêt

### 9.9 Collaboration multi-user

v2 : un seul utilisateur actif à la fois via verrou `locked: true`. CRDT Y.js différé v2.1 si besoin prouvé.

## 10. Workflow utilisateur end-to-end + livrables

### 10.1 Parcours (de l'adresse au dossier PC)

1. **Auth + workspace** (existe SP5)
2. **Création projet** — adresse + parcelles + brief (existe SP1)
3. **Analyse faisabilité** — PLU, footprint, conformité, servitudes (existe SP1)
4. **[NOUVEAU] Génération modèle bâtiment SP2-v2** — pipeline Section 7 (~1.5 min)
5. **Review + édition** optionnelle — paramétrique + WYSIWYG (SP2-v2)
6. **Assemblage dossier PC** — PCMI1-8 (existe SP3, consomme renders SP2-v2)
7. **Export & transmission** — PDF dépôt mairie, IFC archi externe, renders brochure

### 10.2 Livrables (ZIP complet)

```
projet_XXX_dossier_complet.zip
├── 00_Notice_ArchiClaude.pdf
├── 01_Dossier_PC_Complet.pdf (A3 prêt mairie)
├── 02_Pieces_PCMI/
│   ├── PCMI1_Plan_situation.pdf
│   ├── PCMI2a_Plan_masse.pdf
│   ├── PCMI2b_Plans_niveaux.pdf
│   ├── PCMI3_Coupe.pdf
│   ├── PCMI4_Notice_architecturale.pdf
│   ├── PCMI5_Facades.pdf
│   ├── PCMI6_Insertion_paysagere.pdf
│   ├── PCMI7_Photo_proche.pdf
│   └── PCMI8_Photo_lointain.pdf
├── 03_Plans_Vectoriels/
│   ├── Plan_masse.svg + .dxf
│   ├── Niveau_RN.svg + .dxf (tous niveaux)
│   ├── Coupe_AA.svg + .dxf
│   └── Facade_XXX.svg + .dxf (N, S, E, O)
├── 04_Modele_BIM/
│   └── batiment.ifc (IFC 4)
├── 05_Renders_Marketing/
│   ├── perspective_nord_est_4k.png
│   ├── perspective_sud_ouest_4k.png
│   ├── axonometrie_eclatee_4k.png
│   ├── aerien_4k.png
│   ├── interieur_sejour_type.png
│   ├── interieur_cuisine_type.png
│   ├── insertion_rue_4k.png
│   └── insertion_cour_4k.png
├── 06_Data_Technique/
│   ├── building_model.json
│   ├── calculs_conformite.json
│   ├── ratios_programme.json
│   └── cartouche_references.txt
└── 07_Revision_history/
    └── versions.json
```

### 10.3 Scénarios d'usage concrets

- **"Validation faisabilité + premier visuel"** — 3 min (brief + pipeline)
- **"Dossier PC prêt dépôt mairie"** — 15-30 min (édition + review + export)
- **"Explorer 3 options programme"** — ~2 min par option, compare side-by-side
- **"Transmission archi externe"** — <1 min (download IFC)

### 10.4 API endpoints

| Endpoint | Méthode | Usage |
|----------|---------|-------|
| `/projects/{id}/building_model` | GET | Charger modèle actuel |
| `/projects/{id}/building_model` | PATCH | Modif partielle (JSON Patch RFC 6902) |
| `/projects/{id}/building_model/validate` | POST | Valider sans sauver |
| `/projects/{id}/building_model/regenerate` | POST | Re-run pipeline nouveaux params |
| `/projects/{id}/building_model/versions` | GET | Liste versions |
| `/projects/{id}/building_model/restore/{v}` | POST | Restaurer version |
| `/projects/{id}/rendering/plans/{type}.svg` | GET | Plan SVG |
| `/projects/{id}/rendering/plans/{type}.pdf` | GET | Plan PDF A3 |
| `/projects/{id}/rendering/plans/{type}.dxf` | GET | Plan DXF |
| `/projects/{id}/rendering/model.ifc` | GET | Modèle IFC 4 |
| `/projects/{id}/rendering/model.gltf` | GET | Modèle GLTF |
| `/projects/{id}/rendering/renders/{view}.png` | GET | Render 4K |
| `/projects/{id}/rendering/archive.zip` | GET | ZIP complet |
| `/projects/{id}/rendering/refresh` | POST | Régénérer renders impactés |

### 10.5 Stockage

Volumes par projet : ~60-110 MB total (JSON 50-200 KB, SVG 2-5 MB, PDF 10-20 MB, IFC 0.5-2 MB, GLTF 2-5 MB, renders PNG 4K 40-80 MB).

100 projets/mois : ~10 GB/mois = ~$0.25/mois Supabase Storage.

### 10.6 Intégration modules existants

| Module existant | Action SP2-v2 |
|-----------------|---------------|
| `core/feasibility/` | **Inchangé** — SP2-v2 consomme son output |
| `core/programming/` | **Remplacé intégralement** par `core/building_model/` + `core/rendering_v2/` |
| `core/pcmi/` | **Réutilise** nouveaux renders SP2-v2 pour assembler PCMI |
| `core/rendering/` (PCMI6 actuel) | **Remplacé** par `core/rendering_v2/` unifié |
| `api/routes/programming.py` | **Réécrit** en `api/routes/building_model.py` + `api/routes/rendering.py` |
| Frontend `/projects/[id]/pcmi6` | **Supprimé** — remplacé par `/projects/[id]/editor` mode 3D |
| Frontend `/projects/[id]/pcmi` | **Simplifié** — consomme nouveaux renders |

## 11. Phasage d'implémentation

6 sprints de ~2 semaines = **~12 semaines total**. Chaque sprint livre du code utilisable.

### Sprint 1 — Fondations (S1-S2)
**Livrable** : BuildingModel + DB + API CRUD
- Schema JSON + validation Pydantic v2
- Migrations Postgres (`building_models`, `renders`, `templates`, `template_ratings`)
- pgvector activé
- API CRUD complet + versions
- Tests unitaires validation modèle + contraintes réglementaires

### Sprint 2 — Solveur structurel + validateur (S3-S4)
**Livrable** : Pipeline Étapes 1→2 + 6 (pas de templates/rendu encore)
- `core/building_model/solver.py` : grille, noyau, slots
- `core/building_model/validator.py` : PMR, incendie, PLU, SDP
- Fallback solveur atypique (BSP + simulated annealing)
- API `POST /building_model/generate` (partiel)
- Tests intégration feed FeasibilityResult → StructuralGrid + slots

### Sprint 3 — Templates A + génération (S5-S6)
**Livrable** : 20 templates manuels + sélection LLM + adaptation CADQuery
- 20 templates JSON manuels avec preview SVG
- Table `templates` peuplée + embeddings OpenAI
- Recherche vectorielle pgvector
- Sélecteur Claude Opus
- `TemplateAdapter` CADQuery (scale + rotation + miroir)
- Pipeline Section 7 end-to-end fonctionnel

### Sprint 4 — Rendering 2D (S7-S8)
**Livrable** : Plans SVG professionnels prêts PC
- `core/rendering_v2/plans_2d/` : tous renderers NF
- Symboles (portes, fenêtres, escaliers, mobilier)
- Cotations automatiques
- Cartouche NF + échelle + nord
- Export PDF A3 + DXF
- Tests visuels régression (snapshots)

### Sprint 5 — Rendering 3D + SDXL optimisé (S9-S10)
**Livrable** : Renders photoréalistes <1.5 min
- `core/rendering_v2/model_3d/` : CADQuery → IFC + GLTF
- Worker Modal `render_gpu.py` : EEVEE + SDXL Lightning + ESRGAN
- 8 vues standardisées
- Catalogue matériaux PBR
- Warm container + parallélisation 8 workers
- Benchmarks CLIP/LPIPS/FID

### Sprint 6 — Éditeur WYSIWYG + paramétrique (S11-S12)
**Livrable** : Frontend éditeur complet
- Page `/projects/[id]/editor`
- PlanEditor2D react-konva : drag cloisons, resize pièces, portes, fenêtres
- Panel paramétrique
- Validateur temps réel
- Undo/redo + historique versions persisté
- Régénération partielle

### Sprints B/C/D parallèles (dès Sprint 3)
- **B** scraping PC mairies (crawler + CV + review)
- **C** LLM templates exotiques
- **D** LLM-augmenté depuis bases manuelles

### Indexeur continu (post-Sprint 6)
Worker Modal hebdomadaire enrichissant la librairie passivement.

## 12. Risques & mitigations

| Risque | Probabilité | Impact | Mitigation |
|--------|-------------|--------|------------|
| Qualité SDXL Lightning insuffisante vs Cycles | Moyenne | Élevé | Benchmark CLIP/LPIPS dès Sprint 5. Fallback Cycles par vue si fail (+5 s/render). |
| Scraping PC mairies juridiquement complexe | Élevée | Moyen | N'extraire que topologie anonyme. Consultation avocat avant mise prod. Fallback A+C+D pur si bloqué. |
| CADQuery instable sur géométries complexes | Moyenne | Moyen | Tests extensifs 20 géométries réelles IDF. Fallback : génération 3D "plate" sans toiture complexe, warning user. |
| Blender headless Modal : conflits dep Python | Élevée | Moyen | Image Modal custom pré-testée. Alternative : `bpy` packagé Python. |
| Template library pauvre → cas non couverts | Moyenne | Élevé | Feedback loop dès Sprint 3. Prioriser ajout templates. Fallback solveur atypique. |
| Latence pipeline >1.5 min en pratique | Moyenne | Moyen | Monitoring real-time Modal. Auto-scale. Cache modèles warm. |
| Coûts GPU explosent en prod | Faible | Moyen | Dashboard + alerte >$X/jour. Cold start heures creuses. |
| Modèle sémantique trop rigide | Moyenne | Élevé | Champs `custom` JSONB. Versioning schéma. |
| WYSIWYG crée état invalide indépassable | Faible | Moyen | Validation permissive (warning non bloquant). "Retour dernière version valide". |
| Édition multi-user simultanée | Faible v2 | Faible | Verrou simple. CRDT Y.js v2.1 si besoin. |

## 13. Infrastructure

### 13.1 Services externes

- **Modal.com** — GPU serverless, $50/mois crédit initial
- **Supabase Storage** ou S3 — ~$10/mois pour 100 projets
- **Anthropic API Claude Opus** — ~$30/mois

### 13.2 Coûts mensuels estimés (100 projets/mois)

| Poste | Coût |
|-------|------|
| GPU Modal (renders) | ~$12 |
| Warm container 24/7 | ~$15 |
| Storage | ~$0.25 |
| Anthropic API | ~$30 |
| **Total** | **~$57/mois** |

Pour des projets promoteur à 5-50 M€, coût opérationnel ridicule. Augmente linéairement avec nombre de projets.

## 14. Ouvertures v2.1+

Non couvertes par SP2-v2 mais pistes identifiées :
- **CRDT multi-user** Y.js pour édition collaborative archi + promoteur
- **Remplacement SDXL par modèle fine-tuné** sur dataset archi FR (v3)
- **Génération variations commerciales** : 3D décorés par style (scandi / bohème / classique) pour staging virtuel
- **Optimisation multi-objectif** : SDP max / coût construction min / ensoleillement max via Pareto front
- **Module coût** : estimation prix construction depuis BuildingModel + prix matériaux actualisés
- **Export Revit native** (Revit plugin en plus de IFC)
- **Mode immersif VR** : WebXR depuis GLTF pour visite virtuelle
- **Génération automatique brochure commerciale** (PDF marketing mise en page IA)

---

**Fin du spec.** Prêt pour plan d'implémentation détaillé via skill `writing-plans`.
