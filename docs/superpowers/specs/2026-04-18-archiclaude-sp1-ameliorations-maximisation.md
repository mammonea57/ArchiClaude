# ArchiClaude — Améliorations sous-projet 1 : Maximisation acceptation PC

**Document de spécification — Design validé**
Date : 2026-04-18
Statut : validé par l'utilisateur, prêt pour génération du plan d'implémentation

---

## 1. Contexte et objectif

### 1.1 Objectif

Renforcer le sous-projet 1 (Données & Faisabilité) avec 6 modules d'intelligence supplémentaires pour **maximiser la surface construite tout en optimisant les chances d'acceptation du permis de construire** en mairie et à l'urbanisme.

### 1.2 Philosophie fondamentale

**Le bot maximise TOUJOURS le programme.** Il ne réduit jamais automatiquement le programme proposé. Si le PLU autorise R+5 et 3167 m² SDP, le bot propose R+5 et 3167 m² SDP (ou 96-100% selon le risque) en affichant les alertes de risque à côté.

C'est au promoteur de décider s'il prend le risque. Le bot informe, il ne bride pas.

La marge de sécurité (93-100%) ne joue que sur la SDP brute — jamais sur le nombre de niveaux ou l'emprise qui restent toujours au maximum autorisé par le PLU.

### 1.3 Modules ajoutés

1. **Score de risque recours hybride** — score calculé + score Opus combinés
2. **Motifs de refus géolocalisés** — patterns de refus dans un rayon 500m, pas par commune
3. **Checklist pré-instruction** — démarches hiérarchisées avant dépôt PC
4. **Analyse vue droite / vue oblique** — détection conflits articles R.111-18/19
5. **Simulation ombre portée** — deux modes (diagramme solaire + contextuel voisins)
6. **Marge de sécurité PLU adaptative** — 93-100% selon score de risque

---

## 2. Module 1 : Score de risque recours hybride

### 2.1 Architecture

Fichier : `core/analysis/risk_score.py`

Deux composantes combinées en score final :

```
score_final = 0.4 × score_calculé + 0.6 × score_opus
```

### 2.2 Score calculé (0-100)

Basé sur les données objectives disponibles :

| Facteur | Poids | Source |
|---|---|---|
| Nb recours historiques sur la commune (3 dernières années) | 20 pts max | `recours_cases` |
| Nb recours dans un rayon 500m de la parcelle | 15 pts max | `recours_cases` + géolocalisation |
| Présence d'associations actives connues sur la commune | 10 pts max | `recours_cases.association` |
| Match entre caractéristiques projet et motifs de refus locaux | 25 pts max | Module motifs de refus (§3) |
| Dépassement du gabarit dominant voisinage (hauteur projet vs hauteur moyenne BDTopo 200m) | 20 pts max | `ign_bdtopo` |
| ABF obligatoire (périmètre monument historique) | 10 pts fixe si oui | `pop` |

Formule : somme plafonnée à 100.

### 2.3 Score Opus

Demandé dans le même appel Claude Opus que l'analyse architecte (zéro coût supplémentaire). Le prompt enrichi demande :

```
En plus de ta note d'opportunité, évalue le risque de recours sur ce projet sur une échelle de 0 à 100.
Justifie ton score en 2-3 lignes.
Prends en compte : le contexte local, les jurisprudences citées, la sensibilité du voisinage,
l'insertion dans le gabarit existant, et les associations actives.
```

Output ajouté au JSON de réponse Opus : `risk_score_opus: int`, `risk_score_justification: str`.

### 2.4 Score final

```python
score_final = round(0.4 * score_calcule + 0.6 * score_opus)
```

Opus a plus de poids car il intègre le contexte qualitatif. Le score calculé empêche les hallucinations (si 15 recours historiques, le score ne peut pas être bas).

### 2.5 Affichage

- Jauge colorée dans le rapport (vert 0-30, jaune 30-60, orange 60-80, rouge 80-100)
- Justification Opus affichée sous la jauge
- Détail du score calculé accessible en hover/clic

---

## 3. Module 2 : Motifs de refus géolocalisés

### 3.1 Architecture

Fichier : `core/analysis/refusal_patterns.py`

### 3.2 Principe

L'analyse est **géolocalisée**, pas communale. Un refus de R+5 en centre-ville n'a aucun rapport avec un refus de R+5 en secteur pavillonnaire de la même commune.

### 3.3 Périmètre d'analyse

- **Rayon primaire : 500m** autour du centroïde de la parcelle
- **Rayon secondaire : 200m** pour le gabarit dominant de la rue

### 3.4 Données analysées

1. **PC refusés dans le rayon 500m** (table `comparable_projects` + enrichissement futur)
   - Motifs de refus si disponibles
   - Date, adresse, programme refusé
   - **Dédoublonnage refusé→accepté** : un même projet peut apparaître comme un PC refusé puis un PC accepté (après modification et nouveau dépôt). Le système relie les PC à la même adresse + même parcelle + dates proches (<18 mois) comme un même projet. Si un PC refusé a un PC accepté ultérieur au même endroit, le refus est reclassé comme "refusé puis accepté après modification" et ne compte PAS comme un refus pur dans le calcul du score de risque. Seuls les refus sans suite favorable comptent.

2. **Gabarit dominant de la rue** (rayon 200m)
   - Hauteurs BDTopo des bâtiments voisins directs
   - Calcul : médiane des hauteurs dans le rayon
   - Qualification : le projet dépasse / est cohérent / est en-dessous du gabarit dominant

3. **PC acceptés dans le rayon 500m** (table `comparable_projects`)
   - Quel R+X passe dans ce périmètre ?
   - Quelle SDP est acceptée ?

4. **Jurisprudences dans le rayon ou la commune**
   - Motifs récurrents (hauteur, vis-à-vis, ombre, insertion)

### 3.5 Output

```python
@dataclass
class RefusalPattern:
    motif: str                    # "hauteur_excessive", "vis_a_vis", "ombre", "insertion"
    occurrences_500m: int         # nb de fois ce motif apparaît dans 500m
    dernier_cas: str | None       # "R+6 refusé au 12 rue X en 2024"
    projet_concerne: bool         # True si le projet actuel matche ce pattern
    recommandation: str           # "Le gabarit dominant est R+3, votre R+5 dépasse de 2 niveaux — prévoir argument insertion"

@dataclass  
class LocalContext:
    gabarit_dominant_niveaux: int  # médiane des R+X dans 200m
    gabarit_dominant_m: float     # médiane hauteur en mètres
    projet_depasse_gabarit: bool  # True si le projet est au-dessus
    depassement_niveaux: int      # +2 niveaux par rapport au gabarit
    pc_acceptes_500m: list        # PC acceptés récemment
    pc_refuses_500m: list         # PC refusés récemment
    patterns: list[RefusalPattern]
```

### 3.6 Principe fondamental

**Le bot ne réduit JAMAIS le programme.** Si le projet est R+5 et le gabarit dominant est R+3, le bot :
- Propose quand même R+5 (conforme PLU)
- Affiche l'alerte : "Le gabarit dominant à 200m est R+3. Votre projet dépasse de 2 niveaux."
- Recommande : "Prévoir argument d'insertion dans le dossier PC. RDV pré-instruction conseillé."

---

## 4. Module 3 : Checklist pré-instruction

### 4.1 Architecture

Fichier : `core/analysis/pre_instruction.py`

### 4.2 Principe

Checklist hiérarchisée de démarches à effectuer AVANT le dépôt du PC, avec timing recommandé. Adaptative : seules les démarches pertinentes au contexte du projet.

### 4.3 Démarches possibles

| Démarche | Timing | Condition déclenchement |
|---|---|---|
| Mandater géomètre-expert (bornage + topographie) | J-90 | Toujours |
| Étude de sol G2 | J-75 | Si argiles fort OU sol pollué |
| RDV pré-instruction mairie/urbanisme | J-60 | Toujours recommandé, obligatoire si score risque > 40 |
| RDV Architecte des Bâtiments de France | J-45 | Si périmètre MH (alerte ABF) |
| Étude acoustique | J-45 | Si classement sonore 1-2 |
| RDV concessionnaires réseaux | J-30 | Si parcelle > 2000m² ou R+5+ |
| Étude thermique RE2020 prévisionnelle | J-30 | Si R+3+ (3ème famille ou plus) |
| Notification aux voisins (anticipée) | J-15 | Si score risque > 60 |
| Vérification servitudes notariales | J-60 | Toujours |

### 4.4 Génération

Généré par une fonction Python déterministe (pas LLM) basée sur les alertes et le score de risque. Puis enrichi par Opus dans l'analyse architecte avec des recommandations contextuelles.

### 4.5 Output

```python
@dataclass
class PreInstructionItem:
    demarche: str
    timing_jours: int              # J-X avant dépôt
    priorite: Literal["obligatoire", "fortement_recommande", "recommande"]
    raison: str                    # pourquoi cette démarche est nécessaire
    contact_type: str | None       # "geometre", "mairie", "abf", "bet_sol"
```

---

## 5. Module 4 : Analyse vue droite / vue oblique

### 5.1 Architecture

Fichier : `core/analysis/vue_analysis.py`

### 5.2 Cadre réglementaire

- **Vue droite** (article R.111-18 code urbanisme) : distance minimale **19 mètres** entre une ouverture et la propriété voisine en vis-à-vis direct (regard perpendiculaire)
- **Vue oblique** (article R.111-19) : distance minimale **6 mètres** pour un regard en angle

### 5.3 Pipeline de détection des fenêtres voisines

1. **Récupération photos Street View** pour chaque façade visible des bâtiments voisins directs (dans un rayon 50m)
   - Google Street View Static API avec heading ajustable (0-360°) et pitch (haut/bas)
   - On scanne chaque façade voisine en ajustant le heading vers chaque bâtiment BDTopo
2. **Analyse Vision Claude** sur chaque photo
   - Prompt : "Identifie toutes les fenêtres et ouvertures visibles sur cette façade. Pour chaque ouverture, indique : position approximative (étage, position horizontale), type (fenêtre, porte-fenêtre, balcon, loggia), et taille estimée."
   - Output structuré : liste de `{etage: int, position: str, type: str, largeur_estimee_m: float}`
3. **Calcul des distances**
   - Pour chaque ouverture détectée sur un bâtiment voisin
   - Calcul distance entre le point le plus proche de notre footprint et la position de l'ouverture
   - Classification vue droite (perpendiculaire ±45°) vs vue oblique (>45°)
4. **Détection des conflits**
   - Vue droite < 19m → conflit
   - Vue oblique < 6m → conflit
   - Chaque conflit génère une alerte avec : bâtiment source, étage, distance, type de vue

### 5.4 Output

```python
@dataclass
class Ouverture:
    batiment_id: str              # ref BDTopo
    etage: int
    type: str                     # fenetre, porte_fenetre, balcon, loggia
    lat: float
    lng: float

@dataclass
class VueConflict:
    ouverture: Ouverture
    distance_m: float
    type_vue: Literal["droite", "oblique"]
    distance_min_requise_m: float  # 19 ou 6
    deficit_m: float              # combien il manque
    commentaire: str

@dataclass
class VueAnalysisResult:
    ouvertures_detectees: list[Ouverture]
    conflits: list[VueConflict]
    nb_conflits_droite: int
    nb_conflits_oblique: int
    risque_vue: Literal["aucun", "mineur", "majeur"]  # majeur si ≥1 vue droite < 19m
```

### 5.5 Impact sur le score de risque

Chaque conflit de vue droite ajoute 15 points au score de risque calculé. Chaque conflit de vue oblique ajoute 5 points.

---

## 6. Module 5 : Simulation ombre portée

### 6.1 Architecture

Fichier : `core/analysis/shadow.py`

### 6.2 Deux modes (switch en un clic dans l'UI)

#### Mode A — Diagramme solaire annuel

Calcul de la projection d'ombre du projet (footprint + hauteur retenue) sur le terrain environnant :
- **Position solaire** : calcul astronomique pour Paris (48.8566°N, 2.3522°E)
- **Heures simulées** : toutes les heures de 8h à 18h, pour le 21 de chaque mois (12 jours × 11 heures = 132 positions solaires)
- **Output** : diagramme solaire SVG montrant l'étendue maximale de l'ombre dans chaque direction
- **Mise en avant** : 3 positions critiques (solstice d'hiver 21 décembre à 10h, 12h, 14h) qui représentent le pire cas

Calcul de la projection d'ombre :
```python
# Longueur de l'ombre
shadow_length = hauteur / tan(elevation_solaire)

# Direction de l'ombre (opposée au soleil)
shadow_azimuth = (azimut_solaire + 180) % 360

# Projection du footprint dans la direction de l'ombre
shadow_polygon = translate(footprint, dx=shadow_length * sin(shadow_azimuth_rad), 
                                       dy=shadow_length * cos(shadow_azimuth_rad))
```

#### Mode B — Contextuel avec voisins (BDTopo)

Même calcul mais en incluant les bâtiments voisins existants (hauteurs BDTopo) :
- Calcul de l'ombre actuelle (sans le projet) : `ombre_existante`
- Calcul de l'ombre future (avec le projet) : `ombre_future`
- **Aggravation** : `ombre_ajoutee = ombre_future.difference(ombre_existante)`
- **Métrique clé** : `pct_aggravation = area(ombre_ajoutee) / area(ombre_future) * 100`
- **Argument juridique** : "Le projet n'aggrave l'ombrage que de X% par rapport à la situation existante"

### 6.3 Output

```python
@dataclass
class ShadowResult:
    # Mode A — diagramme solaire
    shadow_polygons_svg: str         # SVG du diagramme d'ombre annuel
    critical_shadows: list[dict]     # 3 ombres critiques (21 déc 10h/12h/14h)
    max_shadow_length_m: float       # portée max de l'ombre (solstice hiver midi)
    
    # Mode B — contextuel
    ombre_existante_m2: float | None
    ombre_future_m2: float | None
    ombre_ajoutee_m2: float | None
    pct_aggravation: float | None
    
    # Parcelles/bâtiments impactés
    batiments_impactes: list[dict]   # [{batiment_id, surface_ombre_m2, pct_facade_ombree}]
```

### 6.4 Frontend

Composant `<ShadowSimulation>` avec toggle Mode A / Mode B. SVG overlay sur le plan masse MapLibre. Slider horaire pour animer l'ombre au cours de la journée (solstice hiver).

---

## 7. Module 6 : Marge de sécurité PLU adaptative

### 7.1 Architecture

Fichier : `core/feasibility/smart_margin.py`

### 7.2 Principe

La marge ne joue QUE sur la SDP brute. Le nombre de niveaux et l'emprise restent toujours au maximum PLU.

### 7.3 Table de marge

| Score risque | Marge SDP | Justification |
|---|---|---|
| < 20 (très safe) | **100%** du max PLU | Aucun historique, commune tranquille, gabarit cohérent |
| 20-40 (safe) | **98%** | Léger historique mais projet conforme |
| 40-60 (moyen) | **97%** | Recours possibles, marge de sécurité sur les calculs |
| 60-80 (élevé) | **96%** | Contentieux fréquents dans le secteur |
| > 80 (très élevé) | **96%** + alerte forte | Zone très contentieuse, mais on ne descend JAMAIS sous 96% |

**Règle absolue : la marge ne descend JAMAIS en dessous de 96%.** Le promoteur a besoin de maximiser la surface pour maximiser les profits. Même en zone très contentieuse, 96% est le plancher.

### 7.4 Ajustement par comparables

Si des comparables (PC acceptés dans 500m, 36 derniers mois) montrent que des projets au-dessus de la marge standard ont été acceptés, la marge est relevée vers 100%.

Exemple : score risque = 50 (marge standard 96%), mais 3 PC à 99% du max ont été acceptés dans le quartier → marge relevée à 98%.

### 7.5 Affichage

Deux colonnes dans le rapport et le dashboard :

```
| Indicateur      | Max PLU théorique | Programme recommandé |
|-----------------|-------------------|----------------------|
| SDP             | 3167 m²           | 3040 m² (96%)        |
| Niveaux         | R+5 (18m)         | R+5 (18m)            |
| Emprise         | 60% (750 m²)      | 60% (750 m²)         |
| Logements       | 32                | 31                   |
| Stationnement   | 32 places         | 31 places            |
```

Le promoteur voit les deux et choisit. Le bot ne masque jamais le max théorique.

---

## 8. Intégration dans l'existant

### 8.1 Modifications au FeasibilityResult

Nouveaux champs ajoutés à `core/feasibility/schemas.py` :

```python
class FeasibilityResult(BaseModel):
    # ... champs existants ...
    
    # Nouveaux champs Phase améliorations
    risk_score: RiskScore | None = None
    refusal_patterns: LocalContext | None = None
    pre_instruction_checklist: list[PreInstructionItem] = []
    vue_analysis: VueAnalysisResult | None = None
    shadow_analysis: ShadowResult | None = None
    recommended_programme: RecommendedProgramme | None = None  # avec marge appliquée
```

### 8.2 Modifications au prompt Opus

Le prompt `core/analysis/architect_prompt.py` est enrichi pour demander en plus :
- Score de risque recours (0-100) + justification
- Recommandations pré-instruction contextuelles
- Commentaire sur les conflits de vue détectés
- Commentaire sur l'ombre portée

Zéro coût supplémentaire — même appel Opus, contexte enrichi.

### 8.3 Nouveaux composants frontend

- `<RiskScoreGauge>` — jauge circulaire colorée avec score 0-100
- `<RefusalPatternsAlert>` — bannière d'alertes géolocalisées
- `<PreInstructionChecklist>` — checklist interactive avec timeline
- `<VueConflictsMap>` — carte des conflits de vue sur plan masse
- `<ShadowSimulation>` — SVG ombre avec toggle Mode A/B + slider horaire
- `<SmartMarginTable>` — tableau max PLU vs recommandé

### 8.4 Pipeline d'exécution enrichi

Le pipeline `/projects/{id}/analyze` est enrichi :

```
1. Fetch parcelles + PLU zones          (existant)
2. Extract rules + numericize           (existant)
3. Compute footprint + capacity         (existant)
4. Compute compliance                   (existant)
5. Detect servitudes                    (existant)
6. ── NOUVEAU ──
7. Analyse vue droite/oblique           (nouveau — Vision Claude sur Street View)
8. Simulation ombre portée              (nouveau — calcul géométrique)
9. Analyse motifs de refus géolocalisés (nouveau — requête DB)
10. Calcul score de risque calculé      (nouveau — agrégation)
11. Calcul marge intelligente           (nouveau — score → marge → programme recommandé)
12. ── FIN NOUVEAU ──
13. RAG jurisprudences + recours        (existant)
14. Analyse architecte Opus enrichie    (existant, prompt enrichi)
15. Génération rapport                  (existant, sections ajoutées)
```

---

## 9. Critères de succès

| Critère | Seuil |
|---|---|
| Score de risque recours | Corrélation ≥ 70% avec l'issue réelle sur échantillon de 20 PC historiques |
| Détection vue droite/oblique | ≥ 80% des fenêtres détectées sur photos Street View test (5 parcelles) |
| Ombre portée | Écart ≤ 5% avec calcul manuel sur 3 parcelles de référence |
| Marge intelligente | 100% des recommandations dans la fourchette 96-100% selon le score |
| Checklist pré-instruction | 100% des démarches obligatoires générées quand les conditions sont réunies |
| Motifs géolocalisés | Rayon 500m respecté, gabarit dominant calculé sur ≥ 3 bâtiments BDTopo |

---

## Fin du document
