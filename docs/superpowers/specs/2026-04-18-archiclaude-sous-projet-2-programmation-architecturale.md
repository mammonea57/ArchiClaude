# ArchiClaude — Sous-projet 2 : Programmation architecturale

**Document de spécification — Design validé**
Date : 2026-04-18
Statut : validé par l'utilisateur, prêt pour génération du plan d'implémentation

---

## 1. Contexte et objectif

### 1.1 Objectif

Transformer les résultats de faisabilité du sous-projet 1 (NumericRules + Brief + parcelle) en **volumes constructibles optimisés** et **plans architecturaux complets** prêts pour un dossier de permis de construire.

### 1.2 Pipeline global

```
Parcelle GeoJSON + NumericRules + Brief
         │
         ▼
  A. FOOTPRINT OPTIMISÉ
     ├─ Classification segments (BDTopo routes + heuristique fallback)
     ├─ Reculs segment par segment (voirie/séparative/fond)
     ├─ Gabarit-enveloppe oblique (footprint par tranche/niveau)
     └─ Support formes complexes (triangles, L, parcelles en biais)
         │
         ▼
  B. SOLVER MAXIMISATION
     ├─ 3 scénarios : Max SDP / Max logements / Max confort
     ├─ Suggestions optimisation mix typologique par scénario
     ├─ Variante accès séparés LLS/accession (si applicable, perte <3%)
     └─ Marge intelligente appliquée (96-100%)
         │
         ▼
  C. DISTRIBUTION INTÉRIEURE
     ├─ Sélection template (barre/plot/double/L) selon forme footprint
     ├─ Placement noyaux (escalier+ascenseur) — auto-multiple si incendie/PMR
     ├─ Distribution logements sur trames BA par niveau
     ├─ Circulations PMR conformes (1.20m couloir, paliers)
     └─ Noyaux séparés LLS/accession si espace suffisant
         │
         ▼
  D. PLANS ARCHITECTURAUX
     ├─ 3 niveaux de détail (schématique / PC normé / exécution)
     ├─ 2 modes de rendu (simplifié / NF complet en 1 clic)
     ├─ 2 formats export (SVG web/rapport + DXF pro)
     └─ Plans : masse, niveaux (RDC→dernier), coupe, façades
```

### 1.3 Philosophie

**Maximiser toujours.** Le solver cherche le maximum constructible sous contraintes PLU. La marge de sécurité (96-100%) est la seule réduction appliquée, et le max théorique est toujours affiché à côté du recommandé pour que le promoteur décide.

---

## 2. Module A : Footprint optimisé segment par segment

### 2.1 Classification des segments de parcelle

Fichier : `core/programming/segment_classifier.py`

**Stratégie hybride :**

1. **Détection par BDTopo routes** (prioritaire) :
   - Requête WFS BDTopo routes dans un buffer de 15m autour de la parcelle
   - Pour chaque segment du contour de la parcelle : calcul distance minimale au réseau routier le plus proche
   - Distance < 5m → segment classé **voirie**
   - Sinon, test adjacence à d'autres parcelles cadastrales (parcelles contiguës via buffer 1m) → **séparative latérale**
   - Le segment (ou groupe de segments) le plus éloigné de toute voirie → **fond de parcelle**

2. **Fallback heuristique** (si BDTopo indisponible) :
   - Segment le plus long face à un espace vide (pas de parcelle contiguë) = voirie présumée
   - Segment opposé au segment voirie = fond de parcelle
   - Autres segments = séparatives latérales
   - Warning automatique : "Classification des segments approximative — vérifier manuellement"

**Gestion des cas complexes :**
- **Parcelles d'angle** (2+ segments voirie) : chaque segment voirie reçoit le recul voirie
- **Parcelles en drapeau** : le passage d'accès est classé séparative, le fond large est classé par BDTopo
- **Voiries en diagonale** : le recul est appliqué perpendiculairement au segment, pas aux axes cardinaux
- **Parcelles triangulaires, trapézoïdales, irrégulières** : traités nativement par l'algorithme demi-plans

### 2.2 Application des reculs par demi-plans

Fichier : `core/programming/setback_engine.py`

Pour chaque segment classifié :
1. Calculer la **normale intérieure** du segment (perpendiculaire vers l'intérieur de la parcelle)
2. Créer un **demi-plan** à distance `recul_m` du segment, dans la direction de la normale
3. Le footprint constructible = **intersection de la parcelle avec tous les demi-plans**

```python
def compute_footprint_segments(
    *,
    parcelle: Polygon,
    segments: list[ClassifiedSegment],  # type + recul_m pour chaque segment
    emprise_max_pct: float,
    ebc_geom: BaseGeometry | None = None,
) -> Polygon:
```

Avantages par rapport au buffer uniforme :
- Chaque segment a son propre recul (voirie 5m, séparative 3m, fond 3m par ex.)
- Fonctionne nativement sur toutes les formes de parcelle
- Le footprint résultant suit la géométrie de la parcelle, pas un rectangle approximatif

### 2.3 Gabarit-enveloppe oblique par tranches

Fichier : `core/programming/envelope.py`

Quand un ou plusieurs reculs sont paramétriques (ex: `L = H/2 min 4m`) :

```python
def compute_envelope_tranches(
    *,
    parcelle: Polygon,
    segments: list[ClassifiedSegment],
    hauteur_max_m: float,
    hauteur_par_niveau: float = 3.0,
) -> list[NiveauFootprint]:
    """Compute footprint for each level with height-dependent setbacks.
    
    Returns list of (niveau, footprint_geom, surface_m2) from RDC to top.
    """
```

Pour chaque niveau n (0 = RDC, 1 = R+1, ...) :
1. Hauteur cumulée h = (n + 1) × 3.0m
2. Pour chaque segment avec recul paramétrique : évaluer recul(h) via la RuleFormula
3. Pour les segments à recul fixe : garder le recul constant
4. Calculer le footprint de ce niveau par intersection de demi-plans
5. SDP totale = Σ surface(footprint_niveau_n)

**Output :**
```python
@dataclass
class NiveauFootprint:
    niveau: int           # 0=RDC, 1=R+1, etc.
    hauteur_plancher_m: float  # hauteur du plancher de ce niveau
    footprint: Polygon
    surface_m2: float
```

### 2.4 Soustraction EBC + emprise cap

- EBC : soustrait de chaque footprint de niveau
- Emprise cap : appliqué uniquement au footprint RDC (emprise au sol = surface du RDC). Si emprise RDC > emprise_max_pct × surface_terrain, le footprint RDC est réduit par scaling centroïde. Les niveaux supérieurs sont recalculés à partir du RDC réduit.

---

## 3. Module B : Solver de maximisation multi-scénarios

### 3.1 Architecture

Fichier : `core/programming/solver.py`

### 3.2 Trois scénarios

**Scénario "Max SDP"** :
- Objectif : maximiser la surface de plancher totale
- Mix typologique : celui du brief utilisateur (inchangé)
- Hauteur et emprise poussées au maximum PLU
- Marge intelligente appliquée (96-100% selon score risque)

**Scénario "Max logements"** :
- Objectif : maximiser le nombre d'unités de logement
- Mix ajusté automatiquement : augmente T1/T2 (petites surfaces), réduit T4/T5
- Même footprint et hauteur max
- Suggestion affichée : "en passant à X% T2 (+Y%), vous gagnez Z logements"

**Scénario "Max confort"** :
- Objectif : maximiser la qualité (surfaces généreuses, mieux valorisables)
- Mix ajusté : augmente T3/T4, réduit T1/T2
- Moins de logements mais prix/m² plus élevé en accession
- Surfaces par logement supérieures aux minimums de marché

### 3.3 Itération footprint ↔ hauteur

Si les reculs sont paramétriques (L=H/2), le footprint dépend de la hauteur et vice versa :

```
Itération 1: H = H_max PLU → reculs → footprint → SDP
Itération 2: H ajusté si SDP cap → reculs → footprint → SDP
...
Convergence quand |SDP_n - SDP_n-1| < 1 m²  (3-5 itérations)
```

### 3.4 Suggestions d'optimisation du mix

Pour chaque scénario, le solver calcule l'impact marginal de chaque changement de mix :
- "Passer de 30% T2 à 45% T2 gagnerait X logements (+Y%)"
- "Ajouter 10% de T1 gagnerait X logements mais réduit le prix moyen de Y€/m²"

### 3.5 Variante accès séparés LLS / accession

Si le programme inclut des LLS (commune carencée/rattrapage) ET que le footprint le permet :

1. Calculer la perte SDP d'un 2ème noyau (~30-40 m² par niveau)
2. Si perte < 3% de la SDP totale → proposer automatiquement la variante "accès séparés"
3. Si perte ≥ 3% → proposer les deux options (mutualisé vs séparé) avec le chiffrage de la perte
4. Le promoteur choisit

### 3.6 Output

```python
@dataclass
class Scenario:
    nom: str                          # max_sdp, max_logements, max_confort
    mix_utilise: dict[str, float]     # mix final utilisé
    mix_ajustements: list[str]        # suggestions textuelles
    sdp_m2: float
    nb_logements: int
    nb_par_typologie: dict[str, int]
    nb_niveaux: int
    footprints_par_niveau: list[NiveauFootprint]
    nb_places_stationnement: int
    nb_places_pmr: int
    variante_acces_separes: bool      # True si proposé
    perte_sdp_acces_separes_m2: float | None
    marge_pct: float                  # marge appliquée (96-100%)

@dataclass
class SolverResult:
    scenarios: list[Scenario]         # toujours 3
    scenario_recommande: str          # nom du scénario recommandé
    raison_recommandation: str
```

---

## 4. Module C : Distribution intérieure

### 4.1 Architecture

Fichier : `core/programming/distribution.py`

### 4.2 Sélection du template de distribution

Basé sur le ratio longueur/largeur du footprint RDC :

| Forme footprint | Ratio L/l | Template | Description |
|---|---|---|---|
| Rectangle allongé | > 2.0 | **barre_simple** | Couloir central, logements des deux côtés |
| Rectangle compact | ≤ 2.0 | **plot** | Noyau central, logements en couronne |
| Forme en L | détection angle | **l_distribue** | Noyau à l'angle, ailes des deux côtés |
| Très allongé ou 3B/4ème famille | > 3.5 ou incendie | **barre_double** | 2 noyaux répartis |

### 4.3 Noyau de distribution

Composition d'un noyau :
- Cage d'escalier : 1.00m × 2.40m minimum (habitation 3ème famille)
- Ascenseur : gaine 4.0m² (cabine PMR 1.10 × 1.40m)
- Palier d'arrivée PMR : 1.50m de profondeur minimum
- Couloir de distribution : 1.20m de large minimum (PMR)
- Surface totale noyau : ~30-40 m² par niveau

**Auto-multiplication des noyaux :**
- Classement incendie 3B ou 4ème famille → 2 cages d'escalier obligatoires
- Longueur de couloir PMR > 30m → 2 noyaux
- Footprint très allongé (ratio > 3.5) → 2 noyaux pour efficacité de distribution

### 4.4 Distribution des logements sur trames BA

Trame de base : **5.40m** (standard logement collectif IDF)

Chaque logement occupe un nombre de trames selon sa typologie :
- T1 : 1 trame (5.40m de façade) → 25-30 m²
- T2 : 1.5 trames (~8.10m) → 40-45 m²
- T3 : 2 trames (~10.80m) → 55-60 m²
- T4 : 2.5 trames (~13.50m) → 72-80 m²
- T5 : 3 trames (~16.20m) → 90-100 m²

**Placement optimisé par exposition :**
- T3/T4/T5 placés en priorité côté sud/ouest (meilleure exposition solaire — données du module orientation SP1)
- T1/T2 côté nord/est ou côté rue bruyante (données module bruit SP1)

### 4.5 Pièces intérieures

Surfaces calibrées pour correspondre aux fourchettes marché IDF :

| Pièce | T1 (25-30m²) | T2 (40-45m²) | T3 (55-60m²) | T4 (72-80m²) | T5 (90-100m²) |
|---|---|---|---|---|---|
| Séjour/cuisine | 16m² | 20m² | 24m² | 28m² | 32m² |
| Chambre 1 | — | 10m² | 11m² | 12m² | 13m² |
| Chambre 2 | — | — | 9m² | 11m² | 12m² |
| Chambre 3 | — | — | — | 9m² | 10m² |
| Chambre 4 | — | — | — | — | 9m² |
| SDB | 3m² | 4m² | 4m² | 5m² | 5m² |
| WC séparé | — | — | 1.5m² | 1.5m² | 1.5m² |
| Dégagement | 2m² | 3m² | 3.5m² | 4.5m² | 5.5m² |
| Loggia/balcon | 3m² | 4m² | 5m² | 6m² | 7m² |
| **Total** | **24m²** | **41m²** | **58m²** | **77m²** | **95m²** |

*Surfaces ajustées dynamiquement par le module pour tenir dans la trame et la profondeur de bâtiment disponibles. Les totaux ci-dessus sont des cibles centrales dans les fourchettes marché.*

### 4.6 Noyaux séparés LLS / accession

Quand le programme inclut des LLS et que le footprint le permet :
- Noyau A (accession) : dessert les logements en accession. Placé côté meilleure exposition.
- Noyau B (LLS) : dessert les logements sociaux.
- Perte SDP du 2ème noyau calculée (~30-40 m²/niveau).
- Proposé automatiquement si perte < 3% SDP. Option affichée avec chiffrage si ≥ 3%.

### 4.7 Output

```python
@dataclass
class Logement:
    id: str                    # "N2-T3-A" (niveau 2, T3, position A)
    typologie: str             # T1, T2, T3, T4, T5
    surface_m2: float
    niveau: int
    position: str              # A, B, C... (position sur le niveau)
    exposition: str            # N, NE, E, SE, S, SO, O, NO
    est_lls: bool
    pieces: list[dict]         # [{nom, surface_m2, largeur_m, longueur_m}]
    geometry: Polygon          # contour du logement en Lambert-93

@dataclass
class Noyau:
    id: str                    # "noyau_A", "noyau_B"
    type: str                  # accession, lls, mixte
    position: Point
    surface_m2: float
    dessert: list[str]         # IDs des logements desservis

@dataclass
class NiveauDistribution:
    niveau: int
    footprint: Polygon
    logements: list[Logement]
    noyaux: list[Noyau]
    couloirs: list[Polygon]    # géométries des circulations
    surface_utile_m2: float
    surface_circulations_m2: float

@dataclass
class DistributionResult:
    template: str              # barre_simple, plot, l_distribue, barre_double
    niveaux: list[NiveauDistribution]
    total_logements: int
    total_surface_utile_m2: float
    total_circulations_m2: float
    coefficient_utile: float   # surface_utile / SDP brute
```

---

## 5. Module D : Plans architecturaux

### 5.1 Architecture

Fichiers :
- `core/programming/plans/plan_masse.py` — plan masse SVG/DXF
- `core/programming/plans/plan_niveau.py` — plans de niveaux SVG/DXF
- `core/programming/plans/coupe.py` — coupe longitudinale SVG/DXF
- `core/programming/plans/facade.py` — façades SVG/DXF
- `core/programming/plans/renderer_svg.py` — moteur de rendu SVG
- `core/programming/plans/renderer_dxf.py` — moteur de rendu DXF

### 5.2 Plans générés

**1. Plan masse** :
- Parcelle avec contour et cotes
- Footprint du RDC positionné avec reculs cotés
- Voirie nommée
- Orientation nord (flèche)
- Emprise % et surface pleine terre
- Accès véhicules et piétons
- EBC si présent

**2. Plans de niveaux** (RDC + étage courant + dernier étage si différent) :
- Murs porteurs et cloisons
- Pièces nommées et cotées (surface m² par pièce)
- Menuiseries (portes avec arc d'ouverture, fenêtres avec symbole)
- Noyaux (escalier, ascenseur, palier)
- Circulations (couloirs cotés 1.20m)
- Logements identifiés (T2-A, T3-B, etc.)
- Cotations extérieures et intérieures

**3. Coupe longitudinale** :
- Hauteurs par niveau (plancher à plancher 3.00m)
- Cotes NGF (sol, chaque plancher, acrotère/faîtage)
- Gabarit-enveloppe oblique si applicable (ligne de prospect)
- Fondations schématiques
- Terrain naturel

**4. Façades** (au minimum rue + arrière) :
- Volumes et niveaux
- Ouvertures positionnées (fenêtres, portes-fenêtres, baies)
- Matériaux indiqués en légende (maçonnerie enduite, vitrage, garde-corps, etc.)
- Cotes de hauteur

### 5.3 Trois niveaux de détail

| Élément | Schématique | PC normé (PCMI) | Exécution |
|---|---|---|---|
| Murs porteurs | Trait épais rempli noir | Épaisseur 0.20m, hachure béton NF | Idem + isolation figurée |
| Cloisons | Trait fin | Épaisseur 0.07m | Idem + type (placo, brique) |
| Portes | Trait d'ouverture | Arc + sens d'ouverture NF | Idem + dimensions (0.80/0.90m) |
| Fenêtres | Trait sur mur | Symbole NF (allège + hauteur) | Idem + type vitrage |
| Cotations | Principales seulement | Extérieures + intérieures + hauteurs | Complètes + chaînes de cotes |
| Pièces | Nommées | Nommées + surfaces m² | Idem + usage détaillé |
| Mobilier | Non | Non | Lit, table, canapé indicatifs |
| Gaines techniques | Non | Non | VMC, EU/EP, colonnes |

**Toggle simplifié ↔ NF complet** en un clic dans l'interface. Change le rendu visuel (épaisseurs, hachures, symboles) sans recalculer la géométrie.

### 5.4 Formats de sortie

**SVG** :
- Vecteur pur, zoomable infini
- Intégré dans les rapports HTML/PDF
- Affiché dans le frontend (composants React)
- Calques CSS pour toggle simplifié/NF

**DXF** (via `ezdxf`) :
- Calques normés : `MURS_PORTEURS`, `CLOISONS`, `COTATIONS`, `MENUISERIES`, `TEXTES`, `MOBILIER`, `CIRCULATION`
- Compatible AutoCAD/ArchiCAD/Revit
- Export à l'échelle 1:1 (unités en mètres)

### 5.5 Conventions de dessin

Utilise la normothèque existante `core/drawing/conventions.py` (Phase 7) :
- Épaisseurs de trait NF P 02-001
- Polices : Inter pour les cotes, Playfair Display pour les titres
- Hachures matériaux normées
- Symboles normalisés (nord, escalier, ascenseur, portes)
- Cartouche avec paramètres agence

---

## 6. Intégration dans l'existant

### 6.1 Nouveau package `core/programming/`

```
core/programming/
├── __init__.py
├── segment_classifier.py      # classification segments parcelle
├── setback_engine.py          # reculs par demi-plans
├── envelope.py                # gabarit-enveloppe par tranches
├── solver.py                  # solver multi-scénarios
├── distribution.py            # distribution intérieure
├── schemas.py                 # tous les dataclasses/schemas
└── plans/
    ├── __init__.py
    ├── plan_masse.py
    ├── plan_niveau.py
    ├── coupe.py
    ├── facade.py
    ├── renderer_svg.py
    └── renderer_dxf.py
```

### 6.2 Nouvelles dépendances

- `ezdxf>=1.0` — génération DXF
- Pas d'autres nouvelles dépendances (shapely, math, pyproj déjà installés)

### 6.3 Nouveaux endpoints API

```
POST   /projects/{id}/program          → lance la programmation architecturale
GET    /projects/{id}/program/status    → statut du job
GET    /projects/{id}/scenarios         → liste des 3 scénarios
GET    /projects/{id}/scenarios/{nom}   → détail d'un scénario
GET    /projects/{id}/plans/{type}      → SVG d'un plan (masse, niveau_0, coupe, facade_rue)
GET    /projects/{id}/plans/{type}/dxf  → export DXF
```

### 6.4 Nouveaux composants frontend

- `<ScenarioComparator>` — tableau comparatif des 3 scénarios avec sélection
- `<FloorPlanViewer>` — affichage SVG interactif du plan de niveau (zoom, pan, toggle NF)
- `<SectionViewer>` — affichage coupe
- `<FacadeViewer>` — affichage façade
- `<PlanExportButton>` — export SVG/DXF
- `<LLSAccessToggle>` — toggle accès séparés LLS/accession

### 6.5 Worker ARQ

`workers/programming.py` — job async pour la programmation complète (footprint + solver + distribution + plans). Durée estimée : 5-15 secondes.

---

## 7. Critères de succès

| Critère | Seuil |
|---|---|
| Classification segments | ≥ 90% de concordance avec classification manuelle sur 5 parcelles test |
| SDP par tranches vs simplifié | Gain ≥ 5% sur parcelles avec recul paramétrique |
| Solver convergence | ≤ 5 itérations pour convergence (|SDP_n - SDP_n-1| < 1m²) |
| Plans de niveaux | Tous les logements respectent les surfaces cibles (±5%) |
| Circulations PMR | 100% des couloirs ≥ 1.20m, 100% des paliers ≥ 1.50m profondeur |
| Export DXF | Ouvrable sans erreur dans AutoCAD/ArchiCAD |
| Noyaux séparés | Perte SDP correctement calculée (±2m²) |
| Toggle NF | Switch instantané sans recalcul géométrique |

---

## Fin du document
