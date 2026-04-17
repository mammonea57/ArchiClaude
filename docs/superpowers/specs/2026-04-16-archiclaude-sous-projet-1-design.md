# ArchiClaude — Sous-projet 1 : Données & Faisabilité

**Document de spécification — Design validé**
Date : 2026-04-16
Statut : validé par l'utilisateur, prêt pour génération du plan d'implémentation

---

## 1. Contexte et vision

### 1.1 Contexte produit

ArchiClaude est une application web destinée aux **promoteurs immobiliers d'Île-de-France** (puis étendue au reste de la France), qui produit automatiquement les éléments d'analyse de faisabilité et les pièces graphiques d'un dossier de permis de construire (PCMI 1 à 8) pour une ou plusieurs parcelles cadastrales.

Le produit complet est découpé en **5 sous-projets** indépendants et construits séquentiellement :

1. **Données & Faisabilité** (le présent document) — récupération cadastre/PLU et rapport de capacité constructible
2. **Programmation architecturale** — génération automatique de volumes conformes et distribution programmatique
3. **Génération graphique 2D** — plans masse, plans de niveaux, coupes, façades en SVG normé
4. **Insertion & finitions** — PCMI1 situation, PCMI6 photomontage, export PDF du dossier complet
5. **Frontend web complet** — gestion des projets, partage, workflow de publication

### 1.2 Promesse utilisateur du sous-projet 1

Un promoteur saisit une ou plusieurs adresses/parcelles cadastrales en IDF, paramètre son brief (programme, hauteur cible, emprise, stationnement, espaces verts), et obtient **en moins de 2 minutes** un rapport de faisabilité au format HTML interactif et PDF imprimable qui répond à sept questions :

1. Quelles sont les règles PLU **exactes** applicables à ma parcelle (avec références d'articles et numéros de page) ?
2. Quel est le **maximum constructible théorique** sous ces règles (SDP, emprise, R+X, nb logements par typologie, stationnement) ?
3. Quel est l'**écart** entre mon brief et ce maximum (projet sous-exploité, cohérent, ou infaisable PLU) ?
4. Quels sont les **risques, alertes et points de vigilance** qu'un architecte soulèverait (ABF, PPRI, recours typiques, servitudes, insertion) ?
5. Quelles sont les **contraintes réglementaires complémentaires** au PLU : normes incendie (3ème/4ème famille IGH), accessibilité PMR, RE2020, obligation LLS au titre de la SRU, RSDU (Règlement Sanitaire Départemental) ?
6. Quels sont les **caractéristiques physiques et contextuelles du site** : photos Street View des façades visibles, orientation cardinale de chaque limite, exposition au bruit (classement sonore Cerema/Bruitparif), distance aux transports en commun (avec impact stationnement PLU), projets comparables acceptés récemment dans un rayon de 500m ?
7. Quelle est la **lecture jurisprudentielle** : décisions Conseil d'État / TA rendues sur des projets similaires en IDF, récurrence des motifs d'annulation, associations locales actives en recours dans la commune ?

Le livrable doit avoir le ton et la facture d'une **note d'opportunité d'architecte** (structure synthèse / opportunités / contraintes / alertes / recommandations, lexique métier, cartouche personnalisable agence/promoteur), pas d'un dump algorithmique de tableaux.

### 1.3 Périmètre (in / out of scope)

**Inclus dans le sous-projet 1 :**
- Couverture géographique Île-de-France (1280 communes), extensible
- Extraction des règles PLU/PLUi/PLUbioclim via stratégie hybride GPU + LLM
- Calcul de capacité constructible sous contraintes PLU (mode maximisation systématique)
- Contraintes réglementaires complémentaires appliquées au calcul : normes incendie (3ème/4ème famille, IGH), accessibilité PMR (ascenseur R+3, logements adaptables, stationnement PMR), RE2020 (seuils ic_construction et ic_energie prévisionnels), LLS/SRU (art. 55 — obligation pourcentage selon commune), RSDU (Règlement Sanitaire Départemental IDF)
- Données contextuelles site : photos Mapillary/Street View des façades visibles, orientation cardinale des limites, carte de bruit Cerema/Bruitparif, distance transports en commun (métro/RER/tram/bus), projets comparables récents (PC délivrés <500m, 3 dernières années)
- Voisinage enrichi : pour chaque bâtiment voisin direct, usage (résid./tertiaire via BDTopo + DPE), hauteur corrigée vision satellite, distance à la parcelle, détection d'ouvertures visibles via analyse Claude sur orthophoto
- DVF étendu voisinage (6 dernières années, par typologie) pour signal marché
- Classement énergétique DPE moyen voisinage
- Analyse architecte enrichie par RAG sur corpus de jurisprudences PLU (décisions CE/TA) et de recours associatifs locaux
- Mémoire des corrections utilisateur sur extractions LLM pour amélioration continue (few-shot learning des prompts)
- Rapport HTML interactif + export PDF imprimable avec **style note d'opportunité d'architecte**
- Cartouche personnalisable (nom agence/promoteur, logo, contact, N° d'ordre archi si applicable)
- Versionnage de projets (V1 préliminaire, V2 post-visite terrain, V3 post-RDV ABF, etc.) avec historique figé des rapports
- Multi-utilisateur avec authentification, hébergé
- Infrastructure technique solide : contract tests OpenAPI, fixtures de référence partagées, feature flags backend, playground admin, telemetry coûts LLM temps réel, telemetry corrections utilisateur

**Hors scope du sous-projet 1 (explicitement reportés) :**
- Tout plan dessiné (masse, niveaux, coupes, façades) — traité en sous-projet 3
- Volumétrie ou axonométrie 3D — traité en sous-projet 2
- Bilan financier promoteur (CA, marge, compte d'exploitation) — sous-projet dédié ultérieur
- Validation juridique opposable : ArchiClaude est un outil d'aide à la décision, pas un certificat d'urbanisme
- Mode comparaison A/B de briefs dans un même PDF → v1.1
- Export DOCX éditable → v1.1
- Dataset public de parcelles de référence → après stabilisation produit
- Onboarding guidé, notifications email, partage lecture seule, intégration calendrier → v1.1

**Amorcé en v1, livré progressivement :**
- Corpus RAG jurisprudences : ingestion initiale 200 décisions CE/TA PLU ; extension continue
- Corpus recours associatifs : base initiale 50 cas IDF ; enrichissement par veille
- Mémoire validations utilisateur : simple logging en v1, exploitation few-shot dans prompts en v1.1

### 1.4 Critères de succès

| Critère | Seuil de validation |
|---|---|
| Couverture géographique IDF | ≥ 95% des parcelles urbanisables retournent un rapport exploitable |
| Précision des règles extraites | Sur un échantillon de 10 zones de référence croisées avec règlement manuel, écart moyen ≤ 1% sur valeurs numériques |
| Précision capacité constructible | Sur 5 parcelles de référence avec SDP/emprise/logements publiés, écart ≤ 1% |
| Latence analyse complète | P95 ≤ 180 secondes (extraction + faisabilité + compliance + site + RAG + analyse + rendu HTML) |
| Coût marginal LLM par (commune, zone) nouvelle | ≤ 0,60€ amorti par cache permanent |
| Confidence minimale pour affichage sans validation user | ≥ 0,85 sur NumericRules |
| Multi-utilisateur | Auth fonctionnelle, RLS Postgres active, isolation stricte des projets |
| Qualité de la note d'opportunité (revue user) | Sur 5 projets test : structure respectée, lexique métier présent, citations articles PLU + jurisprudences pertinentes, note ≥ 4/5 en revue |
| Couverture photos site | Mapillary disponible sur ≥ 60% des parcelles IDF, Google Street View fallback comble à ≥ 95% |
| Pertinence comparables | Pour une parcelle IDF avec >10 PC délivrés dans 500m/36 mois, au moins 5 comparables retournés |
| Qualité RAG jurisprudences | Pour chaque projet analysé, au moins 2 décisions CE/TA pertinentes citées (corpus initial 200 décisions) |
| Couverture compliance | 100% des projets reçoivent classement incendie + PMR + LLS/SRU statut ; RE2020 affiché avec mention "indicatif" |
| Versionnage | 100% des analyses versionnées ; comparaison V1 vs V2 produit un diff interprétable |
| Telemetry | 100% des corrections user sur `NumericRules` enregistrées dans `extraction_feedback` |

### 1.5 Contrainte de précision absolue

**Toute valeur numérique ou règlementaire émise par le système doit être précise et correcte.** Aucune approximation acceptée : si une valeur ne peut pas être calculée précisément, le système affiche explicitement "non précisé dans le PLU" ou "à valider manuellement" plutôt qu'une estimation. Cette contrainte s'applique à :

- Surfaces (terrain, emprise, SDP, pleine terre) : calcul géométrique Shoelace sur coordonnées Lambert-93
- Hauteurs : priorité aux valeurs BDTopo, correction vision satellite si divergence, jamais interpolé
- Coefficients SDP brute→utile : valeurs métier par typologie, pas de coefficient unique 0,92 générique
- Règles PLU extraites : toujours avec article + page source, `extraction_confidence` < 0,85 déclenche validation user obligatoire
- Gabarit-enveloppe oblique : soit implémenté correctement, soit escaladé comme "à valider manuellement", jamais approximé en volume rectangulaire sans avertissement

Le moteur inclut une suite de tests avec jeu de référence chiffré (parcelles aux valeurs constructibles publiées) qui doit passer avec écart ≤ 1%.

---

## 2. Architecture système

### 2.1 Vue d'ensemble

Monorepo avec 3 services principaux + infrastructure managée.

```
┌─────────────────────────────────────────────────────────────────┐
│  Navigateur                                                     │
│  Next.js (Vercel) — UI, carte MapLibre, formulaires, viz       │
└────────────┬────────────────────────────────────────────────────┘
             │ HTTPS / JWT
             ▼
┌─────────────────────────────────────────────────────────────────┐
│  API FastAPI (Railway)                                          │
│  ├─ /auth         (JWT)                                         │
│  ├─ /parcels      (recherche, géocodage, sélection)             │
│  ├─ /plu          (zonage, règles, extraction LLM)              │
│  ├─ /projects     (CRUD projets, faisabilité)                   │
│  ├─ /reports      (génération HTML+PDF)                         │
│  └─ workers ARQ   (extraction LLM, génération PDF en background)│
└──┬──────────────┬──────────────┬───────────────┬────────────────┘
   │              │              │               │
   ▼              ▼              ▼               ▼
┌──────────┐ ┌──────────┐ ┌────────────┐ ┌────────────────────┐
│ Postgres │ │ Redis    │ │ S3-compat  │ │ APIs externes      │
│ +PostGIS │ │ (cache + │ │ (Cellar/R2)│ │ - GPU (urbanisme)  │
│ (Neon)   │ │  queue)  │ │ rapports   │ │ - IGN Géoplateforme│
│          │ │          │ │ PDF        │ │ - BAN (adresses)   │
│          │ │          │ │            │ │ - Anthropic API    │
└──────────┘ └──────────┘ └────────────┘ └────────────────────┘
```

### 2.2 Découpage modulaire du backend Python

Chaque module est un dossier testable indépendamment. `core/` ne dépend ni de FastAPI ni de la DB.

```
apps/backend/
├── core/                         # logique métier pure, ZÉRO import FastAPI/SQLAlchemy
│   ├── geo/                      # projections Lambert-93 ↔ WGS84, shapely/geopandas
│   ├── sources/                  # ports/adapters — un fichier par source externe
│   │   ├── ban.py
│   │   ├── cadastre.py
│   │   ├── gpu.py
│   │   ├── ign_bdtopo.py
│   │   ├── ign_bd_alti.py
│   │   ├── georisques.py
│   │   ├── pop.py
│   │   ├── dpe.py
│   │   ├── dvf.py
│   │   ├── mapillary.py          # street-level photos
│   │   ├── google_streetview.py  # fallback photos
│   │   ├── cerema_bruit.py       # classement sonore voies
│   │   ├── bruitparif.py         # cartes bruit IDF
│   │   ├── ign_transports.py     # arrêts TC
│   │   ├── sirh.py               # projets comparables (PC délivrés)
│   │   └── insee_sru.py          # obligations LLS commune
│   ├── plu/
│   │   ├── extractor.py          # port Python de parse-reglement/route.ts
│   │   ├── numericizer.py        # ParsedRules → NumericRules
│   │   ├── parsers/
│   │   │   └── paris_bioclim.py  # parser dédié PLU Bioclimatique Paris
│   │   └── schemas.py            # ParsedRules, NumericRules, ZoneRules
│   ├── feasibility/
│   │   ├── footprint.py          # shapely reculs, emprise max
│   │   ├── capacity.py           # SDP, niveaux, logements
│   │   └── servitudes.py         # ABF, PPRI, EBC, alignement
│   ├── compliance/               # NOUVEAU — contraintes réglementaires complémentaires
│   │   ├── incendie.py           # habitation 3ème/4ème famille, IGH
│   │   ├── pmr.py                # ascenseur, logements adaptables, stationnement PMR
│   │   ├── re2020.py             # ic_construction, ic_energie prévisionnels
│   │   ├── lls_sru.py            # obligation pourcentage LLS article 55 SRU
│   │   └── rsdu.py               # Règlement Sanitaire Départemental
│   ├── site/                     # NOUVEAU — caractéristiques physiques du site
│   │   ├── orientation.py        # azimut de chaque limite, exposition N/S/E/O
│   │   ├── bruit.py              # agrégation Cerema/Bruitparif
│   │   ├── transports.py         # distance TC + impact stationnement
│   │   └── voisinage.py          # BDTopo enrichi + ouvertures via vision Claude
│   ├── comparables/              # NOUVEAU — projets similaires récents
│   │   └── search.py             # PC délivrés <500m, filtres typologie
│   ├── architecture/             # NOUVEAU (graine sous-projet 2)
│   │   └── library.py            # trames BA, épaisseurs, circulations, ascenseurs
│   ├── drawing/                  # NOUVEAU (graine sous-projet 3)
│   │   └── conventions.py        # épaisseurs trait, hachures, polices, symboles, cartouches
│   ├── analysis/                 # prompt Claude Opus + contexte enrichi
│   │   ├── architect_prompt.py   # note d'opportunité (structure, lexique métier)
│   │   └── rag/                  # NOUVEAU
│   │       ├── jurisprudences.py # recherche pgvector CE/TA
│   │       └── recours.py        # corpus recours associatifs par commune
│   └── reports/
│       ├── templates/            # Jinja2 HTML — page titre, sommaire, cartouche persistant
│       ├── pdf.py                # WeasyPrint
│       └── versioning.py         # gestion V1/V2/V3 avec figeage valeurs
├── api/                          # routes FastAPI, schemas Pydantic, deps auth
├── workers/                      # tâches ARQ : extraction, feasibility, pdf, rag_ingest
├── db/                           # modèles SQLAlchemy 2.0, migrations Alembic
├── tests/
│   ├── fixtures/
│   │   └── parcelles_reference.yaml  # dataset partagé (valeurs attendues chiffrées)
│   ├── unit/
│   ├── integration/
│   └── contract/                 # contract tests OpenAPI ↔ frontend TS
└── pyproject.toml

apps/frontend/
├── src/
│   ├── app/              # App Router Next.js
│   ├── components/
│   │   ├── map/          # MapView (MapLibre), overlays
│   │   ├── panels/       # RulesPanel, FeasibilityDashboard
│   │   ├── forms/        # BriefForm, ParcelSearch, RuleValidator
│   │   └── ui/           # shadcn/ui imports
│   ├── lib/              # clients API, hooks, utilities
│   └── types/            # import depuis packages/shared-types
├── package.json
└── next.config.ts

packages/shared-types/    # schemas TS partagés (zod) générés depuis Pydantic
```

**Principe d'isolation** : le code `core/` doit être réutilisable tel quel dans les sous-projets 2 et 3. Il ne connaît ni HTTP ni DB.

### 2.3 Stack technique

| Couche | Technologie | Justification |
|---|---|---|
| Backend langage | Python 3.12 | écosystème géo/scientifique, stabilité, compatibilité sous-projets 2/3 |
| Backend framework | FastAPI | async natif, Pydantic, OpenAPI auto |
| ORM | SQLAlchemy 2.0 | typing moderne, async, reconnu |
| Migrations | Alembic | standard de facto Python |
| Workers | ARQ | simple, basé Redis, async |
| Géo | shapely, geopandas, pyproj | Lambert-93 ↔ WGS84, opérations spatiales |
| PDF | WeasyPrint | rendu HTML/CSS → PDF print-quality, supporte `@page` |
| Frontend langage | TypeScript 5 | typing, écosystème |
| Frontend framework | Next.js 16 (App Router) + React 19 | même version que bot existant |
| Carte | MapLibre GL JS | open source, moderne, meilleurs contrôles que Leaflet |
| UI | shadcn/ui + Tailwind v4 | cohérence visuelle, components accessibles |
| Charts | Recharts | simple, composable, SVG natif |
| Auth | Auth.js (NextAuth v5) | standard Next.js, Google + credentials |
| LLM | Anthropic SDK — Claude Sonnet 4.6 + Opus 4.6 | Sonnet pour extraction règles, Opus pour analyse architecte |

### 2.4 Infrastructure managée

| Ressource | Fournisseur | Plan |
|---|---|---|
| Frontend hosting | Vercel | Hobby (puis Pro 20€ si besoin) |
| Backend hosting | Railway | Starter ~10-20€ (FastAPI + workers ARQ sur même instance) |
| DB PostgreSQL+PostGIS | Neon | Free (3GB, 190h compute) |
| Cache/queue Redis | Upstash | Free (10K req/jour) |
| Stockage PDF | Cloudflare R2 | Free ≤10GB, egress gratuit |
| Auth OAuth | Google Cloud Console | Gratuit |
| LLM | Anthropic API | Pay-as-you-go, ~30-80€/mois v1 |
| Domaine | Registrar OVH/Gandi | ~15€/an |

---

## 3. Sources de données externes

Toutes les API utilisées sont publiques, françaises, et gratuites.

### 3.1 Géocodage

- **BAN — Base Adresse Nationale** (`api-adresse.data.gouv.fr`) : adresse → coordonnées Lambert-93 + `citycode` INSEE. Limite 50 req/s, sans clé.

### 3.2 Cadastre

- **API Carto IGN — module Cadastre** (`apicarto.ign.fr/api/cadastre`) : géométrie GeoJSON d'une parcelle par point ou référence (`commune+section+numero`). Sans clé.
- **Cadastre Etalab** (`cadastre.data.gouv.fr`) : fallback open data, dump par commune.

### 3.3 Urbanisme (cœur)

- **GPU — Géoportail de l'Urbanisme** (`apicarto.ign.fr/api/gpu` + `gpu.beta.gouv.fr/api`) :
  - Zonage PLU/PLUi en GeoJSON (`code_zone`, `libelle`, `libelong`, `typezone`, `id_doc`, `partition`, `nomfic`, `urlfic`)
  - Servitudes d'utilité publique (SUP)
  - Périmètres : EBC, éléments bâtis protégés, alignement
  - Documents règlement : URL directe PDF
- **Couverture IDF attendue** : ~95% des communes. Les 5% restantes (RNU ou non-publiantes) : mode dégradé "télécharger manuellement le règlement et saisir valeurs clés".

### 3.4 Topographie et contexte

- **IGN BD ALTI** via WMS Géoplateforme : altitude moyenne du terrain (pour calculs NGF futurs)
- **IGN BD TOPO** via WFS : bâti existant alentour (hauteurs, nb étages) → analyse insertion
- **IGN BD TOPO** + **DPE ADEME** (`data.ademe.fr/data-fair/api/v1/datasets/meg-83tjwtg8dyz4vv7h1dqe`) : nombre de niveaux par enrichissement croisé (stratégie type "immeuble" puis "tous types", mode parmi les 5 plus proches)
- **IGN orthophotos** via WMS : fond de carte aérien pour le rapport

### 3.5 Patrimoine et risques

- **API POP — Plateforme Ouverte du Patrimoine** (`pop.culture.gouv.fr/search/api`) : monuments historiques, sites classés. Vérification périmètre 500m.
- **GeoRisques** (`georisques.gouv.fr/api`) : PPRI, PPRT, retrait-gonflement argiles, sols pollués (BASIAS/BASOL).

### 3.6 Valeurs foncières (bonus decision support)

- **DVF — Demande de Valeurs Foncières** via `data.gouv.fr` ou base interne après ingestion : historique des ventes sur la parcelle et voisines (6 dernières années), agrégation par typologie (prix moyen m² appartement/maison/local pro).

### 3.7 Photos de site

- **Mapillary API** (`graph.mapillary.com`) : photos street-level contributives, accès gratuit avec clé API. Récupération des images les plus récentes depuis chaque voie adjacente, dans un rayon de 50m de la parcelle. Permet d'illustrer les façades visibles du projet et d'analyser le contexte urbain. Limite : couverture hétérogène en IDF (denser dans Paris et grandes banlieues).
- **Google Street View Static API** (fallback, via clé payante ~$7/1000 images) : couverture meilleure mais payant. Fallback si Mapillary ne trouve pas d'image proche pertinente.

### 3.8 Bruit

- **Cerema — Cartes de bruit stratégiques** (API data.gouv.fr ou WMS `carto.geosignal.fr`) : classement sonore des voies terrestres par catégorie 1 à 5 (routes + voies ferrées), isophones Lden (niveau jour-soir-nuit).
- **Bruitparif** (IDF spécifique, `rumeur.bruitparif.fr`) : cartographie IDF plus fine, mesures ponctuelles. Utilisé en complément de Cerema pour l'IDF.
- Impact règlementaire extrait : catégorie sonore → épaisseur isolation acoustique obligatoire menuiseries + façades (arrêté 30/05/1996 et suivants). Le rapport indique la catégorie et l'obligation applicable.

### 3.9 Transports en commun et mobilité

- **IGN Géoplateforme — WFS arrêts de transport** (dataset `transportcommun` + `voiesferres`) : géolocalisation arrêts métro/RER/tram/bus fréquent. Calcul distance au centroïde parcelle.
- **API Navitia** (via STIF Île-de-France Mobilités, `prim.iledefrance-mobilites.fr`) : informations temps réel et fréquence des lignes. Utilisé pour qualifier un "bus fréquent" (≥1 passage/15min en heure de pointe) — critère fréquent PLU pour exonérer stationnement.
- **Données ZFE** (site `zfe.urbanisme.gouv.fr` ou jeu de données data.gouv) : périmètres Zone à Faibles Émissions. Impact sur parc véhicules, politiques stationnement communales.

### 3.10 Projets comparables (PC délivrés)

- **Affichages légaux PC** (pas d'API centralisée nationale) : on ingère progressivement trois sources complémentaires :
  - **Service Sitadel** (Ministère Transition Écologique) : statistiques PC/PA au niveau communal, données agrégées.
  - **Open data communes** — les grandes villes IDF publient souvent leurs arrêtés de PC (ex Paris via `opendata.paris.fr` dataset "Permis de construire"). À agréger dataset par dataset.
  - **SIRH interne** (v1.1) : on construit notre propre base à partir de l'affichage légal en mairie (parsing OCR de photos) + signalements utilisateurs. Démarrage minimaliste en v1.
- Sortie attendue : pour une parcelle donnée, retourner les 10 PC délivrés dans un rayon 500m les 36 derniers mois, avec date, adresse, surface, nb logements, avec source de l'information.

### 3.11 LLS et SRU

- **INSEE / Ministère Logement** — bilan SRU communal (article 55 loi SRU) publié annuellement par la préfecture : identifie les communes carencées, en rattrapage, conformes. Taux d'obligation LLS (25% ou 30% selon décret commune-par-commune).
- Dataset open data via `data.gouv.fr` : `logements-sociaux` annuel par commune.
- Impact : si commune carencée, obligation LLS dans tout programme >800m² SDP (seuil courant PLU) ou >12 logements.

### 3.12 LLM

- **Anthropic API** via `anthropic` Python SDK :
  - **Claude Sonnet 4.6** pour extraction règles PLU (avec prompt caching `ephemeral`)
  - **Claude Haiku 4.5** en fallback sur PLU mono-commune courts pour économie
  - **Claude Opus 4.6** pour analyse architecte (raisonnement complexe)

### 3.13 Résilience

Chaque client `core/sources/*.py` implémente :
- Cache Redis avec TTL adapté : zonage PLU 30j, géocodage 90j, patrimoine 7j, DPE 7j, DVF 24h
- Retry avec backoff exponentiel (tenacity)
- Mode dégradé : si API down, le rapport signale "donnée X indisponible, à vérifier manuellement"
- Timeout strict (40s download PDF, 5s données légères)

---

## 4. Moteur PLU hybride

### 4.1 Architecture en trois couches

```
┌────────────────────────────────────────────────────────────┐
│ Couche 1 — Données structurées GPU (déjà machine-lisible) │
│ zones, servitudes, EBC → directement utilisables          │
└───────────────────────────┬────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────┐
│ Couche 2 — Extraction textuelle LLM (ParsedRules)         │
│ PDF règlement → strings "Bande principale : 25 m max..."  │
│ port fidèle de parse-reglement/route.ts en Python         │
└───────────────────────────┬────────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────────┐
│ Couche 3 — Conversion numérique (NumericRules)            │
│ strings → valeurs numériques exploitables par faisabilité │
│ avec formules paramétriques et bandes                     │
└────────────────────────────────────────────────────────────┘
```

### 4.2 Schéma ParsedRules (strings, textuel)

Identique au TS du bot existant, porté en Pydantic.

```python
class ParsedRules(BaseModel):
    hauteur: str | None
    emprise: str | None
    implantation_voie: str | None
    limites_separatives: str | None
    stationnement: str | None
    lls: str | None                    # logements locatifs sociaux
    espaces_verts: str | None
    destinations: str | None
    pages: dict[str, int | None]
    source: Literal['ai_parsed', 'cache', 'manual', 'paris_bioclim_parser']
    cached: bool = False
```

### 4.3 Schéma NumericRules (numérique, exploitable)

```python
class RuleFormula(BaseModel):
    """Formule paramétrique : ex 'L=H/2 min 4m' → evaluable avec H connu."""
    expression: str        # 'H/2'
    min_value: float | None # 4.0
    max_value: float | None
    units: str             # 'm'
    raw_text: str          # source textuelle

class Bande(BaseModel):
    """Bande constructible (principale vs secondaire en PLUi)."""
    name: Literal['principale', 'secondaire', 'fond']
    hauteur_max_m: float | None
    emprise_max_pct: float | None
    depth_from_voie_m: float | None  # profondeur de la bande depuis la voirie

class NumericRules(BaseModel):
    # Hauteur
    hauteur_max_m: float | None
    hauteur_max_niveaux: int | None         # nombre total de niveaux habitables y compris RDC (R+3 → 4)
    hauteur_max_ngf: float | None
    hauteur_facade_m: float | None          # gabarit-enveloppe
    # Emprise et implantation
    emprise_max_pct: float | None
    recul_voirie_m: float | None
    recul_voirie_formula: RuleFormula | None
    recul_limite_lat_m: float | None
    recul_limite_lat_formula: RuleFormula | None
    recul_fond_m: float | None
    recul_fond_formula: RuleFormula | None
    # Programme
    cos: float | None
    sdp_max_m2: float | None
    # Environnement
    pleine_terre_min_pct: float
    surface_vegetalisee_min_pct: float | None
    coef_biotope_min: float | None
    # Stationnement (par destination)
    stationnement_par_logement: float | None
    stationnement_par_m2_bureau: float | None
    stationnement_par_m2_commerce: float | None
    # Cas complexes
    bandes_constructibles: list[Bande] | None
    section_paris_bioclim: "ParisBioclimZone | None"
    # Méta
    article_refs: dict[str, str]
    extraction_confidence: float            # 0-1
    extraction_warnings: list[str]
```

### 4.4 Extracteur LLM (port du bot existant)

Le module `core/plu/extractor.py` est un **port Python fidèle** de `src/app/api/parse-reglement/route.ts` du bot `urbanisme-france-live`, avec tous ses raffinements :

1. **Multi-pass regex d'identification de section de zone** : variantes notation `UA1`, `UA-1`, `UA.1`, `UA 1`, préfixe alphabétique `UA`
2. **Extraction section complète via marqueur canonique** `Dispositions applicables à la zone X` avec fallback parent (`UB2a → UB2 → UB`)
3. **Filtrage PLUi multi-communes** (`stripOtherCommunesFromSection`) : retrait des paragraphes spécifiques à d'autres communes
4. **Pré-filtrage par fenêtre** autour des mentions de commune, respectant les boundaries de zone
5. **Scoring des candidats de section** : bonus mots règlementaires, bonus "Dispositions applicables", malus sommaire
6. **Double cache** : mémoire LRU + filesystem `/tmp/archiclaude-rules-cache/` + DB Postgres `zone_rules_text`
7. **Prompt caching** avec `cache_control: ephemeral` sur le texte PLU (~80% économie sur requêtes suivantes)
8. **Sélection de modèle** : Haiku 4.5 si PLU mono-commune court (<120K chars), Sonnet 4.6 sinon (PLUi ou gros PLU)
9. **Réparation JSON tronqué** : comptage guillemets impairs, fermeture accolades, retry si max_tokens atteint
10. **Retry avec fenêtre décalée** : si ≥4 champs manquants et texte tronqué, relance sur la dernière occurrence du libellé de zone
11. **Détection d'erreurs déguisées** : rejet de patterns "null", "non trouvé", "section incomplète"

Le prompt contient les consignes strictes vues dans le TS : instruction prioritaire de filtrage par commune pour PLUi, valeurs chiffrées précises, jamais d'explication narrative dans les valeurs, `"Non précisé dans ce règlement"` ou `"Non réglementé"` si absence.

### 4.5 Conversion ParsedRules → NumericRules

Module `core/plu/numericizer.py` :

1. Appel Claude Sonnet 4.6 avec prompt dédié qui prend en entrée `ParsedRules` et retourne `NumericRules` structuré via `tool_use`
2. Le prompt spécifie les unités attendues, la gestion des bandes, la reconnaissance des formules paramétriques
3. Auto-évaluation de `extraction_confidence` par le LLM lui-même sur chaque champ
4. Les formules paramétriques (`"L=H/2 min 4m"`) sont converties en `RuleFormula` avec expression évaluable par `asteval` (mini DSL restreint à `+ - * / min max H`)
5. Coût marginal : ~0,05-0,15€ par zone (texte court, output JSON court). S'ajoute au coût extraction string.

### 4.6 Validation utilisateur première utilisation

Tant que `zone_rules_numeric.validated_by_user_id IS NULL`, le rapport affiche :
- Un badge orange "Règles extraites automatiquement — à valider"
- Un lien vers la page `/rules/{zone_id}` qui montre côte-à-côte le texte brut PLU, les valeurs extraites, et un formulaire de correction
- Le calcul de faisabilité tourne quand même mais est marqué `confidence_score` réduit

Quand l'utilisateur valide (et éventuellement corrige), la zone devient **validée pour tous les utilisateurs** (règles publiques). Les éditions sont tracées dans `validation_edits` (diff JSON).

### 4.7 Parser dédié Paris Bioclimatique

Le **PLU Bioclimatique de Paris** approuvé le 20/11/2024 est suffisamment structuré pour un parser Python dédié `core/plu/parsers/paris_bioclim.py` :

- Tables de gabarits par zone (UG / UGSU / UV / UVE / UN / USC)
- Coefficients biotope par secteur
- Hauteurs plafond par niveau NGF et par bande
- Règles d'espaces verts par typologie de parcelle

Ce parser produit les mêmes objets `ParsedRules` et `NumericRules` que le pipeline LLM, mais avec :
- `source = 'paris_bioclim_parser'`
- `extraction_confidence = 1.0`
- `validated_by_user_id` pré-rempli automatiquement (données officielles)
- Zéro coût API

Gain estimé : ~75% du volume d'extraction IDF sans coût LLM et avec précision 100%.

### 4.8 Parcelle multi-zones

Quand une parcelle est à cheval sur plusieurs zones :

1. Intersection de la géométrie parcelle avec chaque zone
2. Calcul de la part surfacique de chaque zone (`surface_part_m2`)
3. Application des règles **par zone** pour le volume constructible (footprint calculé séparément, puis assemblé)
4. La contrainte la plus restrictive domine pour espaces verts et pleine terre
5. Le rapport affiche la répartition en pourcentage et précise quelles règles s'appliquent à quelle partie

Pas de moyenne pondérée : chaque zone produit ses propres calculs, qui sont présentés séparément puis totalisés.

### 4.9 Communes non couvertes par GPU

Pour les communes RNU ou non-publiantes :
- Affichage explicite "PLU non disponible automatiquement sur cette commune"
- Interface de saisie manuelle des valeurs clés (hauteur, emprise, reculs, pleine terre, stationnement)
- Les valeurs saisies sont enregistrées comme `source = 'manual'` et utilisables dans le calcul

---

## 5. Moteur de faisabilité

### 5.1 Entrée / sortie

**Entrée** : liste de parcelles (géométries GeoJSON), `NumericRules` applicables par zone, brief utilisateur (A-H).

**Sortie** : `FeasibilityResult` (schéma complet en §5.6).

### 5.2 Étape 1 — Footprint maximum constructible

Module `core/feasibility/footprint.py`, utilise shapely :

1. `terrain = unary_union(parcelles)` en projection Lambert-93 pour calculs métriques exacts
2. Identification des segments du terrain par rapport à leurs voisins :
   - **Voirie** : segments bordant un espace public (détecté via BAN + BD TOPO routes)
   - **Limites séparatives latérales** : segments bordant d'autres parcelles privées contiguës
   - **Fond de parcelle** : segment le plus éloigné de la voirie principale
3. Application des reculs respectifs par buffer négatif segment par segment :
   - `recul_voirie_m` (ou évaluation `recul_voirie_formula` avec H = hauteur retenue)
   - `recul_limite_lat_m`
   - `recul_fond_m`
4. Cap à l'emprise au sol max : si `footprint.area > emprise_max_pct × surface_terrain`, réduction géométrique optimale (pas d'homothétie simple — respect des reculs)
5. Soustraction des EBC éventuels sur la parcelle : `footprint = footprint.difference(ebc_geom)`

Sortie : `footprint_geom: Polygon | MultiPolygon`, `surface_emprise_m2`, `surface_pleine_terre_min_m2`.

### 5.3 Étape 2 — Volume et SDP

```python
# Hauteur retenue = min des contraintes
hauteur_m_niveaux = (niveaux_max * 3.0) + 0.5  # 3m/niveau utile + épaisseur plancher
hauteur_retenue_m = min(
    hauteur_max_m,
    hauteur_m_niveaux if niveaux_max else inf,
    hauteur_max_ngf - altitude_sol_m if hauteur_max_ngf else inf,
)
nb_niveaux_retenu = floor(hauteur_retenue_m / 3.0)

# SDP
surface_par_niveau = surface_emprise  # RDC identique aux étages en première approx
sdp_brute = surface_par_niveau * nb_niveaux_retenu

# Coefficient brute→utile par typologie. VALEURS EXACTES À VALIDER en Phase 3.2
# par référence CSTB / Observatoire FFB / Union sociale pour l'habitat avant utilisation.
# Les valeurs ci-dessous sont des ordres de grandeur indicatifs pour la conception, PAS
# à hardcoder tels quels : la contrainte précision absolue impose sourcing documenté.
coef_utile = {
    'collectif_dense': ...,     # immeuble urbain R+5 et +  ~0.78-0.82
    'collectif_standard': ...,  # R+2 à R+4                 ~0.83-0.87
    'intermediaire': ...,       # maisons accolées          ~0.86-0.90
    'individuel': ...,          # maison individuelle       ~0.90-0.94
}[typologie_dominante]

sdp_max = min(
    sdp_brute * coef_utile,
    sdp_max_plu if defined else inf,
    (cos * surface_terrain) if cos else inf,
)
```

### 5.4 Étape 3 — Gabarit-enveloppe et cas complexes

Si la règle de recul est paramétrique en fonction de la hauteur (`recul = H/2 min 4m`), l'enveloppe constructible devient oblique. Deux modes :

- **Mode simplifié v1** : calcul avec `recul = hauteur_retenue / 2` (forfait constant). Le footprint rectangulaire en découle, la SDP est sous-estimée.
- **Mode correct (v1.1)** : calcul par tranches horizontales, SDP par niveau décroissante vers le haut, sommée.

Dans le v1, si gabarit-enveloppe détecté, le système :
1. Calcule en mode simplifié et indique explicitement "calcul conservateur, gain de 5-15% possible par étude oblique"
2. Escalade en `alerte.type = 'oblique_a_valider'` pour revue architecte

### 5.5 Étape 4 — Programme et logements

```python
# Surface moyenne pondérée par mix typologique (valeurs SDP utiles).
# VALEURS À VALIDER en Phase 3.2 par référence (Observatoire logement neuf IDF,
# normes AFNOR NF P01-012, barème LLS USH). Ordres de grandeur indicatifs uniquement ici.
surface_par_typologie_m2 = {
    'T1': ...,  # ~28-35 m² SDP
    'T2': ...,  # ~42-50 m² SDP
    'T3': ...,  # ~58-70 m² SDP
    'T4': ...,  # ~75-90 m² SDP
    'T5': ...,  # ~95-115 m² SDP
}
surface_moy = sum(pct * surface_par_typologie_m2[t] for t, pct in mix.items())

nb_logements_max = floor(sdp_max / surface_moy)
nb_par_typologie = {t: round(nb_logements_max * pct) for t, pct in mix.items()}

# Stationnement
nb_places_logement = nb_logements_max * stationnement_par_logement
```

### 5.6 Étape 5 — Comparaison brief vs max

Pour chaque cible (B, C, D, E, F), classification :

| Ratio brief/max | Classification | Affichage |
|---|---|---|
| < 0.60 | très sous-exploité | rouge foncé — opportunité significative perdue |
| 0.60 - 0.85 | sous-exploité | orange — possibilité de pousser |
| 0.85 - 1.00 | cohérent | vert — projet bien dimensionné |
| 1.00 - 1.05 | limite | jaune — attention aux tolérances PLU |
| > 1.05 | infaisable | rouge — dépasse PLU, système cap au max |

### 5.7 Étape 6 — Servitudes et contraintes dures

Application systématique :

- **Monument historique <500m (périmètre AC1)** : alerte "Avis ABF obligatoire, recul/matériaux/teinte susceptibles d'imposer contraintes additionnelles non quantifiables automatiquement"
- **PPRI** : récupération cote NGF crue centennale via GeoRisques → calcul hauteur sol minimale → réduction SDP utile RDC éventuelle
- **EBC sur la parcelle** : géométrie retirée du terrain avant calcul footprint (§5.2)
- **Alignement** : recul voirie min imposé indépendamment du PLU
- **Sol pollué BASIAS/BASOL** : alerte "étude des sols obligatoire, dépollution potentiellement requise avant construction"
- **Retrait-gonflement argiles fort** : alerte "étude géotechnique G2 obligatoire"

### 5.8 Normes incendie (module `core/compliance/incendie.py`)

Classement selon `hauteur_retenue_m` mesuré du sol au plancher bas du dernier niveau (convention pompiers) :

| Classement | Critères | Impact principal sur SDP utile |
|---|---|---|
| Habitation 1ère famille | individuel isolé ≤R+1 | ~nul |
| Habitation 2ème famille | individuel R+1 à R+3, collectif ≤R+3 | ~nul |
| Habitation 3ème famille A | collectif plancher haut ≤28m, accès pompiers direct | ascenseur obligatoire >R+3, 1 seule cage escalier admise |
| Habitation 3ème famille B | collectif idem mais accès pompiers difficile | 2 cages escalier, coefficient utile -3 à -5% |
| Habitation 4ème famille | plancher haut 28m < H ≤ 50m | 2 cages, désenfumage mécanique, coefficient utile -5 à -8% |
| IGH classe A | H > 50m | procédures spécifiques lourdes, impact majeur coefficient utile -8 à -12% |

Le module ajuste `sdp_max_m2` par application d'un coefficient de réduction incendie après le calcul volumétrique brut. Les valeurs exactes (-3%, -5%, -8%, etc.) **doivent être validées en Phase 3.2 par référence à l'Arrêté du 31/01/1986 modifié** (classification habitations) et aux retours d'expérience BET structure. Pas d'invention : tant que non validées, valeurs indisponibles → escalade "à valider" dans le rapport.

### 5.9 Accessibilité PMR (module `core/compliance/pmr.py`)

Application des règles issues de la loi du 11/02/2005 et arrêté 24/12/2015 :
- **Ascenseur obligatoire dès R+3** en logement collectif neuf → coefficient utile réduit de la surface gaine ascenseur + palier (~12-20 m² par niveau selon typologie)
- **100% des logements accessibles** en construction neuve depuis 2023 (tous adaptables sans modification, cuisines et SDB aux dimensions réglementaires)
- **Stationnement PMR** : 2% min arrondi supérieur du total places, avec places ≥3,30m de large × 5m
- **Accès logement collectif** : cheminement extérieur 1,20m minimum

Le module calcule l'impact en :
1. Soustrayant la surface ascenseur + palier à `sdp_max` si R+3+ atteint
2. Imposant `nb_places_pmr = ceil(nb_places × 0.02)` minimum
3. Alertant si parcelle en pente forte >5% (cheminement PMR compromis)

### 5.10 RE2020 prévisionnel (module `core/compliance/re2020.py`)

Calcul indicatif (pas bloquant faisabilité mais à afficher) :
- **ic_construction** (kg CO2/m² SDP) : estimation selon typologie (collectif béton ~750, bois-béton ~550) et seuil réglementaire en vigueur l'année cible
- **ic_energie** (kg CO2/m²/an) : estimation selon typologie + zone climatique (IDF = H1a)
- **bbio_max** : selon surface moyenne logement + zone climatique
- **dh** (degrés-heures inconfort été) : évaluation qualitative selon exposition et taux vitrage brief

Les seuils évoluent : 2022 ic_construction ≤760, 2025 ≤650, 2028 ≤480 kg CO2/m². Le module prend en paramètre l'année cible de dépôt PC pour appliquer le bon seuil. Tant que les coefficients de conversion typologie → ic ne sont pas sourcés (base INIES, fiches FDES, retour SIA/CSTB), le module affiche "indicatif uniquement, à affiner par BET thermique".

### 5.11 LLS / SRU (module `core/compliance/lls_sru.py`)

Récupération du statut SRU de la commune depuis `core/sources/insee_sru.py` :
- Si commune **conforme** (>25% ou >30% LLS selon décret) : pas d'obligation supplémentaire
- Si commune **en rattrapage** : obligation LLS dans tout programme > seuil PLU (souvent 800m² SDP ou 12 logements). Pourcentage minimum imposé selon PLH local
- Si commune **carencée** : obligation renforcée, objectif de rattrapage sur 3 ans, pénalités si non atteint

Le module alerte si le brief ne mentionne pas de LLS alors que le programme dépasse le seuil d'obligation. Il ajuste `nb_par_typologie` pour inclure la proportion LLS exigée (impact mix). En contrepartie, certains PLU offrent bonus de constructibilité (jusqu'à +10% SDP) pour les programmes incluant >35% LLS → application du bonus si brief éligible.

### 5.12 Données de site contextuelles

Agrégées par le module `core/site/` lors de l'analyse :
- **Orientation** (`orientation.py`) : pour chaque segment du contour parcelle, calcul azimut et qualification N/NE/E/SE/S/SO/O/NO. Stocké en `FeasibilityResult.site.orientations`.
- **Bruit** (`bruit.py`) : catégorie sonore dominante des voies bordant la parcelle → `site.classement_sonore` (1 très bruyant à 5 calme) + obligation isolation acoustique.
- **Transports** (`transports.py`) : liste des arrêts TC <500m avec mode (métro/RER/tram/bus fréquent) et distance → `site.transports[]`. Qualification "bien desservie" si métro <400m OU ≥2 lignes bus fréquent <300m. Impact : peut exonérer du stationnement voiture selon PLU (`stationnement_exoneration_possible: bool`).
- **Voisinage enrichi** (`voisinage.py`) : pour chaque bâtiment BDTopo contigu ou en vis-à-vis direct, hauteur (corrigée vision satellite si divergence), usage (résid./tertiaire via DPE), détection ouvertures visibles par analyse Claude sur orthophoto → `site.voisins[]`. Utilisé par l'analyse architecte pour commentaires vis-à-vis / ombrage / recours.
- **DVF voisinage** (`core/sources/dvf.py`) : transactions 6 dernières années <300m, agrégation par typologie et année → `site.dvf_neighborhood`.
- **DPE voisinage** : classe énergétique moyenne des logements DPE <200m.

Ces données n'entrent pas dans le calcul de capacité constructible mais alimentent le rapport (section "Contexte du site") et le prompt Claude Opus pour l'analyse architecte.

### 5.13 Projets comparables

Le module `core/comparables/search.py` interroge les sources §3.10 pour retourner jusqu'à 10 PC délivrés dans un rayon de 500m sur les 36 derniers mois, filtrés par typologie compatible avec le brief (destination + ordre de grandeur SDP). Sortie : liste avec date, adresse, SDP, nb logements, R+X, source. Présenté dans le rapport en tableau "Ce qui a été accepté récemment dans le quartier" + carte de localisation. Signal fort pour calibrer le brief.

### 5.14 Schéma FeasibilityResult

```python
class ZoneApplicableInfo(BaseModel):
    zone_id: UUID
    code: str
    libelle: str
    surface_intersectee_m2: float
    pct_of_terrain: float
    rules_text: ParsedRules
    rules_numeric: NumericRules

class EcartItem(BaseModel):
    target: str
    brief_value: float
    max_value: float
    ratio: float
    classification: Literal['tres_sous_exploite','sous_exploite','coherent','limite','infaisable']
    commentaire: str

class Servitude(BaseModel):
    type: str
    libelle: str
    geom: dict
    attributes: dict

class Alert(BaseModel):
    level: Literal['info','warning','critical']
    type: str
    message: str
    source: str

class VigilancePoint(BaseModel):
    category: Literal['insertion','recours','patrimoine','environnement','technique']
    message: str

class ComplianceResult(BaseModel):
    """Résultat application règles complémentaires au PLU."""
    incendie_classement: Literal['1ere','2eme','3A','3B','4eme','IGH']
    incendie_coef_reduction_sdp: float        # ex 0.95 si 3B → -5%
    pmr_ascenseur_obligatoire: bool
    pmr_surface_circulations_m2: float
    pmr_nb_places_pmr: int
    re2020_ic_construction_estime: float | None  # kg CO2/m²
    re2020_ic_energie_estime: float | None
    re2020_seuil_applicable: str              # ex "2025" ou "2028"
    lls_commune_statut: Literal['conforme','rattrapage','carencee']
    lls_obligation_pct: float | None
    lls_bonus_constructibilite_pct: float | None  # bonus PLU si >35% LLS
    rsdu_applicable: bool                      # RSDU IDF
    rsdu_obligations: list[str]                # stationnement vélo, local poubelles, etc.

class SiteContext(BaseModel):
    """Contexte physique et urbain du site."""
    orientations: list[dict]                   # par segment : azimut, longueur, qualification N/S/E/O
    classement_sonore: int | None              # 1-5
    classement_sonore_source: str | None
    isolation_acoustique_obligatoire: bool
    transports: list[dict]                     # mode, nom, distance_m, frequence
    bien_desservie: bool
    stationnement_exoneration_possible: bool
    voisins: list[dict]                        # bâtiments voisins directs avec usage, hauteur, ouvertures
    photos_streetview: list[str]               # URLs signées ou cache R2
    dvf_neighborhood: dict                     # prix moyens par typologie/année
    dpe_neighborhood_mean: str | None          # classe moyenne A-G

class ComparableProject(BaseModel):
    date: date
    address: str
    sdp_m2: float | None
    nb_logements: int | None
    hauteur_niveaux: int | None
    source: str
    distance_m: float

class FeasibilityResult(BaseModel):
    parcelle_ids: list[UUID]
    surface_terrain_m2: float
    zones_applicables: list[ZoneApplicableInfo]
    # Capacité max (après application PLU + compliance)
    footprint_geojson: dict
    surface_emprise_m2: float
    surface_pleine_terre_m2: float
    hauteur_retenue_m: float
    nb_niveaux: int
    sdp_max_m2: float                         # après réduction compliance
    sdp_max_m2_avant_compliance: float        # traçabilité
    nb_logements_max: int
    nb_par_typologie: dict[str, int]
    nb_places_stationnement: int
    nb_places_pmr: int
    # Compliance complémentaire
    compliance: ComplianceResult
    # Contexte site
    site: SiteContext
    # Projets comparables
    comparables: list[ComparableProject]
    # Comparaison brief
    ecart_brief: dict[str, EcartItem]
    # Alertes
    servitudes_actives: list[Servitude]
    alertes_dures: list[Alert]
    points_vigilance: list[VigilancePoint]
    # Analyse architecte (bloc généré par Claude Opus, structure note d'opportunité)
    analyse_architecte_md: str                 # sections Synthèse/Opportunités/Contraintes/Alertes/Recommandations
    # RAG sources consultées (traçabilité)
    jurisprudences_citees: list[UUID]
    recours_cites: list[UUID]
    # Versionnage
    version_number: int
    version_label: str | None
    parent_version_id: UUID | None
    # Méta
    confidence_score: float
    warnings: list[str]
    computed_at: datetime
```

### 5.15 Module d'analyse architecte

Module `core/analysis/` utilise **Claude Opus 4.6** avec un prompt système détaillé "architecte d'Île-de-France expert PLU et contentieux PC". Entrée enrichie : `FeasibilityResult` déjà calculé + contexte parcelle (voisinage BDTopo enrichi, orthophoto, photos Mapillary/Street View, orientation, bruit, transports, DVF voisinage, DPE voisinage, projets comparables, jurisprudences pertinentes RAG, recours locaux RAG).

**Structure du livrable imposée par prompt** (style note d'opportunité d'architecte, pas dump algorithmique) :

1. **Synthèse** (5-8 lignes) : verdict global et chiffre clé, ton décisionnaire
2. **Opportunités** : points favorables (marché, exposition, desserte, comparables positifs, bonus constructibilité disponibles)
3. **Contraintes** : ce qui limite le projet (gabarit, servitudes, voisinage, bruit, LLS obligatoire, incendie 4ème famille)
4. **Alertes** : risques dur (ABF, PPRI, recours probable, sol pollué) avec ordre de gravité
5. **Recommandations** : 3-5 actions concrètes pour le promoteur (mandater géomètre, RDV pré-ABF, ajuster le brief sur tel axe)

Longueur cible : 600-1200 mots markdown. Lexique métier imposé (faîtage, acrotère, débord, loggia, trame, gabarit-enveloppe, vue droite/oblique, prospect, alignement, mitoyenneté). Références aux articles PLU cités + pages PDF dans le corps du texte.

**Intégration RAG** : avant l'appel LLM, récupération pgvector de :
- 5 décisions CE/TA pertinentes (similarité sémantique sur description du projet + commune)
- 3 cas de recours sur la commune si disponibles
- Injection dans le contexte du prompt sous forme de résumés tagués `[jurisprudence]` et `[recours_local]`

### 5.16 Versionnage des résultats

Chaque `FeasibilityResult` est **immuable** une fois généré. Chaque nouveau calcul sur le même projet crée une nouvelle version (`project_versions` table §6) avec :
- `version_number` auto-incrémenté par projet (V1, V2, V3...)
- `version_label` optionnel saisi par l'user ("Préliminaire", "Post-visite", "Post-ABF", etc.)
- Snapshot du brief, des règles utilisées, du footprint, du rapport généré, du PDF R2

Permet comparaison diff entre versions dans l'UI et conservation de traçabilité pour audit promoteur.

---

## 6. Modèle de données PostgreSQL+PostGIS

### 6.1 Extensions

```sql
CREATE EXTENSION postgis;
CREATE EXTENSION pgcrypto;
CREATE EXTENSION pg_trgm;
CREATE EXTENSION vector;            -- pgvector pour RAG jurisprudences/recours
```

> **Note** : `vector` n'est pas disponible sur tous les plans Neon free. Vérifier au setup que le projet Neon est sur un plan supportant pgvector (sinon upgrader, ~0€-19€/mois).

### 6.2 Tables (DDL complet)

```sql
-- ─── Auth & users ──────────────────────────────────────────
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT,                 -- NULL si OAuth-only
    full_name TEXT,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user','admin')),
    created_at TIMESTAMPTZ DEFAULT now(),
    last_login_at TIMESTAMPTZ
);

CREATE TABLE oauth_accounts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider TEXT NOT NULL CHECK (provider IN ('google')),
    provider_user_id TEXT NOT NULL,
    UNIQUE (provider, provider_user_id)
);

-- ─── Données immuables (cache public mutualisé) ────────────
CREATE TABLE parcels (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code_insee CHAR(5) NOT NULL,
    section VARCHAR(3) NOT NULL,
    numero VARCHAR(5) NOT NULL,
    contenance_m2 INTEGER,
    geom GEOMETRY(MultiPolygon, 4326) NOT NULL,
    address TEXT,
    fetched_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (code_insee, section, numero)
);
CREATE INDEX parcels_geom_gist ON parcels USING GIST(geom);
CREATE INDEX parcels_address_trgm ON parcels USING GIN (address gin_trgm_ops);

CREATE TABLE plu_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    code_insee CHAR(5) NOT NULL,
    gpu_doc_id TEXT UNIQUE,
    partition TEXT,
    type TEXT CHECK (type IN ('PLU','PLUi','PLUbioclim','POS','RNU','CC')),
    nomfic TEXT,
    pdf_url TEXT,
    pdf_sha256 CHAR(64),
    pdf_text_raw TEXT,
    fetched_at TIMESTAMPTZ,
    last_checked_at TIMESTAMPTZ
);

CREATE TABLE plu_zones (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plu_doc_id UUID NOT NULL REFERENCES plu_documents(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    libelle TEXT,
    libelong TEXT,
    typezone TEXT,
    geom GEOMETRY(MultiPolygon, 4326),
    UNIQUE (plu_doc_id, code)
);
CREATE INDEX plu_zones_geom_gist ON plu_zones USING GIST(geom);

CREATE TABLE servitudes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type TEXT NOT NULL,
    sous_type TEXT,
    libelle TEXT,
    geom GEOMETRY(Geometry, 4326),
    attributes JSONB,
    source TEXT,
    fetched_at TIMESTAMPTZ
);
CREATE INDEX servitudes_geom_gist ON servitudes USING GIST(geom);
CREATE INDEX servitudes_type ON servitudes(type);

-- ─── Règles extraites (mutualisées entre users) ────────────
CREATE TABLE zone_rules_text (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plu_zone_id UUID NOT NULL REFERENCES plu_zones(id) ON DELETE CASCADE,
    commune_insee CHAR(5),
    parsed_rules JSONB NOT NULL,
    pdf_text_hash CHAR(64),
    source TEXT CHECK (source IN ('llm_sonnet','llm_haiku','paris_bioclim_parser','manual')),
    model_used TEXT,
    extraction_cost_cents NUMERIC(10,4),
    extracted_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (plu_zone_id, commune_insee, pdf_text_hash)
);

CREATE TABLE zone_rules_numeric (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    zone_rules_text_id UUID NOT NULL UNIQUE REFERENCES zone_rules_text(id) ON DELETE CASCADE,
    numeric_rules JSONB NOT NULL,
    extraction_confidence NUMERIC(3,2) CHECK (extraction_confidence BETWEEN 0 AND 1),
    warnings JSONB,
    validated_by_user_id UUID REFERENCES users(id),
    validated_at TIMESTAMPTZ,
    validation_edits JSONB
);

-- ─── Données utilisateur (projets privés) ──────────────────
CREATE TABLE projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    brief JSONB NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','analyzed','archived')),
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE project_parcels (
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    parcel_id UUID NOT NULL REFERENCES parcels(id),
    ordering SMALLINT,
    PRIMARY KEY (project_id, parcel_id)
);

CREATE TABLE feasibility_results (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    result JSONB NOT NULL,
    footprint_geom GEOMETRY(MultiPolygon, 4326),
    zone_rules_used UUID[] NOT NULL,
    confidence_score NUMERIC(3,2),
    warnings JSONB,
    generated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    feasibility_result_id UUID NOT NULL REFERENCES feasibility_results(id) ON DELETE CASCADE,
    format TEXT NOT NULL CHECK (format IN ('html','pdf')),
    r2_key TEXT,
    sha256 CHAR(64),
    size_bytes INTEGER,
    generated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE audit_logs (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID REFERENCES users(id),
    action TEXT NOT NULL,
    entity_type TEXT,
    entity_id UUID,
    payload JSONB,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ─── Versionnage des analyses ──────────────────────────────
CREATE TABLE project_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    version_number INTEGER NOT NULL,
    version_label TEXT,                        -- "Préliminaire", "Post-ABF"...
    parent_version_id UUID REFERENCES project_versions(id),
    brief_snapshot JSONB NOT NULL,             -- brief figé à cette version
    feasibility_result_id UUID REFERENCES feasibility_results(id),
    pdf_report_id UUID REFERENCES reports(id),
    notes TEXT,                                -- note user (motif du nouveau run)
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (project_id, version_number)
);

-- ─── RAG : jurisprudences et recours ───────────────────────
CREATE TABLE jurisprudences (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,                      -- "CE", "TA_Paris", "TA_Versailles"...
    reference TEXT UNIQUE NOT NULL,            -- "CE 2024-10-15 n°475123"
    date DATE,
    commune_insee CHAR(5),                     -- NULL si décision de principe nationale
    motif_principal TEXT,                      -- "hauteur excessive", "vue plongeante"...
    articles_plu_cites TEXT[],
    resume TEXT NOT NULL,                      -- 200-500 mots
    decision TEXT,                             -- "annulation PC", "rejet recours"...
    embedding vector(1536),                    -- OpenAI ada-002 compat ou embed-french
    ingested_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX jurisprudences_embedding_idx ON jurisprudences USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX jurisprudences_commune ON jurisprudences(commune_insee);

CREATE TABLE recours_cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    commune_insee CHAR(5) NOT NULL,
    date_depot DATE,
    association TEXT,                          -- nom de l'asso porteuse
    projet_conteste TEXT,
    motifs TEXT[],
    resultat TEXT,                             -- "accepté", "rejeté", "en cours"
    resume TEXT,
    embedding vector(1536),
    ingested_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX recours_embedding_idx ON recours_cases USING ivfflat (embedding vector_cosine_ops);
CREATE INDEX recours_commune ON recours_cases(commune_insee);

-- ─── Telemetry apprentissage LLM ───────────────────────────
CREATE TABLE extraction_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    zone_rules_numeric_id UUID NOT NULL REFERENCES zone_rules_numeric(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id),
    diff JSONB NOT NULL,                       -- champ par champ : valeur LLM vs valeur user
    edit_reason TEXT,                          -- commentaire user optionnel
    created_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX extraction_feedback_zone ON extraction_feedback(zone_rules_numeric_id);

-- ─── Feature flags ─────────────────────────────────────────
CREATE TABLE feature_flags (
    key TEXT PRIMARY KEY,                      -- ex "enable_oblique_gabarit"
    enabled_globally BOOLEAN DEFAULT false,
    enabled_for_user_ids UUID[],               -- override par user
    description TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- ─── Paramètres agence / cartouche personnalisable ─────────
CREATE TABLE agency_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    agency_name TEXT,
    logo_r2_key TEXT,                          -- upload logo sur R2
    address TEXT,
    contact_email TEXT,
    contact_phone TEXT,
    archi_ordre_number TEXT,                   -- N° d'ordre architecte si applicable
    default_cartouche_footer TEXT,
    brand_primary_color TEXT,                  -- hex
    updated_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE (user_id)
);

-- ─── Projets comparables ingérés ───────────────────────────
CREATE TABLE comparable_projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,                      -- "sitadel", "opendata_paris", "ocr_user"...
    commune_insee CHAR(5) NOT NULL,
    date_arrete DATE,
    address TEXT,
    geom GEOMETRY(Point, 4326),
    sdp_m2 NUMERIC,
    nb_logements INTEGER,
    destination TEXT,
    hauteur_niveaux INTEGER,
    url_reference TEXT,
    ingested_at TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX comparable_projects_geom_gist ON comparable_projects USING GIST(geom);
CREATE INDEX comparable_projects_commune_date ON comparable_projects(commune_insee, date_arrete DESC);

-- ─── Statut SRU des communes (cache mutualisé) ─────────────
CREATE TABLE commune_sru (
    code_insee CHAR(5) PRIMARY KEY,
    annee_bilan INTEGER NOT NULL,
    taux_lls_actuel NUMERIC(5,2),
    taux_lls_cible NUMERIC(5,2),
    statut TEXT CHECK (statut IN ('conforme','rattrapage','carencee','non_soumise')),
    penalite_annuelle_eur NUMERIC,
    source_url TEXT,
    fetched_at TIMESTAMPTZ DEFAULT now()
);
```

### 6.3 Row Level Security

Activée sur les tables privées utilisateur :

```sql
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
CREATE POLICY projects_isolation ON projects
    USING (user_id = current_setting('app.user_id')::UUID);

ALTER TABLE feasibility_results ENABLE ROW LEVEL SECURITY;
CREATE POLICY feasibility_results_isolation ON feasibility_results
    USING (project_id IN (SELECT id FROM projects));

ALTER TABLE reports ENABLE ROW LEVEL SECURITY;
CREATE POLICY reports_isolation ON reports
    USING (feasibility_result_id IN (SELECT id FROM feasibility_results));
```

Le backend FastAPI exécute `SET LOCAL app.user_id = '<uuid>'` au début de chaque transaction authentifiée.

### 6.4 Invariants

- `parcels`, `plu_documents`, `plu_zones`, `servitudes`, `zone_rules_*` sont **mutualisés** tous users
- `projects`, `feasibility_results`, `reports` sont **privés user**
- `pdf_sha256` sur `plu_documents` : détection changement règlement → invalidation `zone_rules_text` liés
- Contrainte unique `(plu_zone_id, commune_insee, pdf_text_hash)` sur `zone_rules_text` : historique versions

### 6.5 Migrations Alembic

- Nomenclature : `YYYYMMDD_HHMM_description.py`
- Chaque migration idempotente
- Seed initial : données de test Paris 8e UG (bioclim) + Nogent-sur-Marne UB (PLUi) pour tests d'intégration

### 6.6 Volumes attendus

| Table | Volume v1 | Volume cible |
|---|---|---|
| parcels | 10K-100K (lazy) | 8M (IDF complet si ingest batch) |
| plu_zones | ~15K | ~15K IDF |
| zone_rules_text/numeric | ~5K-15K | ~15K IDF |
| servitudes | ~50K | ~50K |
| projects | ~100-1000/mois | selon adoption |

Neon free tier (3GB) suffisant pour la v1.

---

## 7. API FastAPI

### 7.1 Convention

- Préfixe : `/api/v1`
- Auth : JWT Bearer dans header `Authorization`, vérification par dépendance FastAPI
- Réponses : JSON, schémas Pydantic, OpenAPI auto-généré à `/docs`
- Pagination : cursor-based (`?cursor=&limit=`)
- Erreurs : format RFC 7807 (`{ type, title, status, detail, instance }`)

### 7.2 Endpoints

```
# ─── Auth ─────────────────────────────────────────────────
POST   /auth/register           body: { email, password, full_name }
                                → 201 { access_token, user }
POST   /auth/login              body: { email, password }
                                → 200 { access_token, user }
POST   /auth/google/callback    body: { code }
                                → 200 { access_token, user }
GET    /auth/me                 → 200 User
POST   /auth/logout             → 204

# ─── Recherche parcelles ──────────────────────────────────
GET    /parcels/search?q=<adresse>&limit=5
                                → 200 [{ address, lat, lng, citycode, score }]
GET    /parcels/at-point?lat=&lng=
                                → 200 Parcel
GET    /parcels/by-ref?insee=&section=&numero=
                                → 200 Parcel
GET    /parcels/{id}            → 200 Parcel

# ─── Urbanisme ────────────────────────────────────────────
GET    /plu/at-point?lat=&lng=  → 200 { zones[], servitudes[], sup[], ebc[], patrimoine[], risques[] }
GET    /plu/zone/{zone_id}      → 200 PluZone
GET    /plu/zone/{zone_id}/rules?commune_insee=
                                → 200 { text: ParsedRules, numeric: NumericRules,
                                         confidence, validated, sources }
POST   /plu/zone/{zone_id}/extract
                                body: { commune_insee? }
                                → 202 { job_id }
GET    /plu/extract/status/{job_id}
                                → 200 { status, progress, result? }
POST   /plu/zone/{zone_id}/validate
                                body: { edits: NumericRules }
                                → 200 { rules, validated_at }

# ─── Projets ──────────────────────────────────────────────
POST   /projects                body: { name, parcel_ids[], brief }
                                → 201 Project
GET    /projects?status=&limit=&cursor=
                                → 200 { items: Project[], next_cursor }
GET    /projects/{id}           → 200 Project
PATCH  /projects/{id}           body: { name?, brief?, parcel_ids? }
                                → 200 Project
DELETE /projects/{id}           → 204
POST   /projects/{id}/analyze   → 202 { job_id }
GET    /projects/{id}/analyze/status
                                → 200 { status, progress, steps[], result_id? }

# ─── Résultats & rapports ─────────────────────────────────
GET    /feasibility/{result_id} → 200 FeasibilityResult
GET    /feasibility/{result_id}/report.html
                                → 200 HTML
POST   /feasibility/{result_id}/report.pdf
                                → 202 { job_id }
GET    /reports/{report_id}/download
                                → 302 (redirect to signed R2 URL)

# ─── Versions de projet ───────────────────────────────────
POST   /projects/{id}/versions  body: { label?, notes? }
                                → 201 ProjectVersion  (relance un calcul sur brief actuel)
GET    /projects/{id}/versions  → 200 ProjectVersion[]
GET    /projects/{id}/versions/compare?a=<num>&b=<num>
                                → 200 { diff: {...}, ecarts: {...} }

# ─── Données de site ──────────────────────────────────────
GET    /site/photos?lat=&lng=&radius_m=50
                                → 200 { mapillary: [...], streetview: [...] }
GET    /site/orientation?parcelle_id=
                                → 200 { segments: [{azimut, longueur_m, qualification}] }
GET    /site/transports?lat=&lng=&radius_m=500
                                → 200 { arrets: [...], bien_desservie: bool }
GET    /site/bruit?lat=&lng=    → 200 { classement_sonore, source, obligation_acoustique }
GET    /site/voisinage?parcelle_id=
                                → 200 { batiments: [{geom, hauteur, usage, ouvertures_visibles}] }
GET    /site/comparables?parcelle_id=&radius_m=500&months=36
                                → 200 { projects: ComparableProject[] }
GET    /site/dvf?parcelle_id=&radius_m=300&years=6
                                → 200 { transactions: [...], aggregates: {...} }

# ─── RAG jurisprudences & recours ─────────────────────────
GET    /rag/jurisprudences/search?q=&commune_insee=&limit=5
                                → 200 { items: Jurisprudence[] }
GET    /rag/recours/search?commune_insee=&limit=5
                                → 200 { items: RecoursCase[] }

# ─── Feedback extraction règles (telemetry) ───────────────
POST   /rules/{zone_rules_numeric_id}/feedback
                                body: { diff, edit_reason? }
                                → 201  (stocké pour amélioration future)

# ─── Paramètres agence (cartouche) ────────────────────────
GET    /agency/settings         → 200 AgencySettings
PUT    /agency/settings         body: { agency_name, ... }
                                → 200 AgencySettings
POST   /agency/logo             multipart: { file }
                                → 200 { logo_url }

# ─── Admin & observabilité ────────────────────────────────
GET    /admin/extraction-costs?from=&to=
                                → 200 { by_day: {...}, by_zone: {...}, total_cents }
GET    /admin/validation-queue  → 200 { zones: [...] }
GET    /admin/feature-flags     → 200 FeatureFlag[]
PUT    /admin/feature-flags/{key}
                                body: { enabled_globally?, enabled_for_user_ids? }
                                → 200 FeatureFlag
POST   /admin/playground/test-extraction
                                body: { commune_insee, zone_code, pdf_url? }
                                → 200 ParsedRules  (test hors projet pour debug)
GET    /admin/telemetry/extraction-feedback?from=&to=&field=
                                → 200 { total_edits, per_field: {...}, worst_zones: [...] }
```

### 7.3 Workers ARQ

Trois queues Redis :

- **`extraction`** : extraction LLM d'une nouvelle zone (Sonnet 4.6, ~30-60s)
- **`feasibility`** : calcul complet faisabilité pour un projet (~10-30s)
- **`pdf`** : génération PDF via WeasyPrint (~5-15s), upload R2

Chaque job stocke son statut dans Redis (`job:<id>:status`) avec TTL 1h. Le frontend poll `/analyze/status` toutes les 1s ou consomme un flux SSE pour les updates live.

### 7.4 SSE pour live progress

Endpoint `GET /projects/{id}/analyze/stream` (Server-Sent Events). Événements typés :
- `{ step: 'fetch_parcelles', status: 'done' }`
- `{ step: 'identify_zones', status: 'done', zones_count: 2 }`
- `{ step: 'extract_rules', status: 'progress', zone: 'UG', model: 'sonnet-4-6', eta_s: 30 }`
- `{ step: 'extract_rules', status: 'done', zone: 'UG' }`
- `{ step: 'compute_footprint', status: 'done' }`
- `{ step: 'analyse_architecte', status: 'progress' }`
- `{ step: 'done', result_id: '<uuid>' }`

### 7.5 Validation entrées

Toutes les entrées Pydantic avec contraintes :
- `lat` ∈ [-90, 90], `lng` ∈ [-180, 180]
- `code_insee` : `^\d{5}$`
- `section` : `^[0-9A-Z]{1,3}$`
- `numero` : `^\d{1,5}$`
- Email validé via `email-validator`
- Password min 10 chars, pas de règle de complexité imposée (NIST 2017 recommendation)

### 7.6 Rate limiting

Via `slowapi` (clé = user_id ou IP en anonyme) :
- `/auth/register`, `/auth/login` : 5/min/IP
- `/plu/zone/*/extract` : 20/h/user (coût LLM)
- `/projects/*/analyze` : 30/h/user
- Autres : 300/min/user

---

## 8. Frontend Next.js

### 8.1 Pages (App Router)

```
/                        → landing + CTA "Commencer" (redirige /projects si logué)
/login                   → Auth.js (email/password + Google)
/signup                  → création compte
/projects                → liste projets user avec statut + confidence
/projects/new            → création projet : carte + sélection parcelles + formulaire brief
/projects/[id]           → dashboard projet (résumé + liens vers vues détaillées)
/projects/[id]/report    → rapport interactif complet (dernière version)
/projects/[id]/versions  → timeline des versions V1/V2/V3 + comparaison diff
/projects/[id]/settings  → nom, suppression, clonage
/rules/[zone_id]         → consultation/validation règles d'une zone
/agency                  → paramètres cartouche personnalisable (nom, logo, contact)
/account                 → profil, usage API
/admin                   → (role admin only) dashboard costs, flags, playground, telemetry
/admin/playground        → test extraction PLU hors projet
/admin/flags             → gestion feature flags
/admin/telemetry         → corrections user par champ, pire zones
```

### 8.2 Composants clés

| Composant | Rôle |
|---|---|
| `<MapView>` | MapLibre GL, fond IGN orthophotos, overlays parcelles/zones/servitudes, sélection multi-parcelles, toggles overlay bruit/transports/voisinage |
| `<ParcelSearch>` | Autocomplete BAN avec debounce 250ms |
| `<BriefForm>` | Formulaire A-H en tabs (Programme / Contraintes / Espaces verts / Stationnement) avec validation Zod |
| `<RulesPanel>` | Affichage `ParsedRules` texte + `NumericRules` chips, badges validation |
| `<RuleValidator>` | Diff extraction LLM vs formulaire édition, highlight low-confidence, bouton soumission feedback |
| `<FeasibilityDashboard>` | KPIs en cartes + barres comparaison brief/max |
| `<TypologyChart>` | Donut Recharts nb logements par typologie |
| `<ServitudesList>` | Badge + tooltip par servitude active |
| `<ComplianceSummary>` | Panel incendie / PMR / RE2020 / LLS-SRU avec explications vulgarisées |
| `<SitePhotosGallery>` | Galerie photos Mapillary/Street View avec légende direction |
| `<OrientationDiagram>` | Rose des vents avec façades colorées selon exposition solaire |
| `<NoiseOverlay>` | Overlay carto sonore Cerema/Bruitparif + panneau explication |
| `<TransportLayer>` | Pins stations TC avec modes et distances, isochrone 500m |
| `<VoisinageLayer>` | Voisins avec hauteurs, étiquettes usage, flèches ouvertures détectées |
| `<ComparableProjectsList>` | Tableau "Ce qui a été accepté récemment" + carte pins |
| `<DvfChart>` | Graph prix moyen m² par typologie/année, comparaison commune/voisinage |
| `<JurisprudencesSidebar>` | Sidebar cliquable avec décisions CE/TA citées dans l'analyse, lien source |
| `<RecoursLocauxList>` | Liste recours associatifs commune avec fréquence par motif |
| `<ArchitectureNoteRenderer>` | Rendu markdown structuré note d'opportunité : sections Synthèse / Opportunités / Contraintes / Alertes / Recommandations avec typographie dédiée |
| `<VersionTimeline>` | Timeline horizontale V1→V2→V3 avec indicateurs diff (SDP, nb logts, etc.) |
| `<VersionCompare>` | Vue split-screen diff entre 2 versions |
| `<CartoucheEditor>` | Formulaire agence + upload logo + preview live du cartouche sur template |
| `<ReportExportButton>` | Déclenche génération PDF, toast progress |
| `<AdminCostsDashboard>` | Courbes coût Anthropic par jour/user, alertes seuils |
| `<AdminFlagsTable>` | CRUD feature flags avec audit log |
| `<AdminPlayground>` | Test extraction PLU sur commune/zone/PDF arbitraire |
| `<AdminTelemetryPanel>` | Histogrammes champs les plus corrigés + worst zones |

### 8.3 Styles et design system

- Tailwind v4 (même version que bot existant)
- shadcn/ui pour les primitives (Button, Dialog, Tabs, Card, Badge, etc.)
- Palette : primary teal, accents ambre pour alertes, rouge pour infaisabilité
- Typographie : Inter pour UI, font-serif Playfair pour titres de rapport (conserve esthétique sobre architecture)
- Dark mode désactivé en v1 (rapport blanc impératif pour PDF)

### 8.4 Parcours utilisateur canonique

1. Login via Google OAuth (1 clic)
2. `/projects` → "Nouveau projet"
3. `/projects/new` : carte centrée sur Paris, recherche "12 rue de la Paix, Vincennes" → zoom, clic 2 parcelles contiguës
4. Panel droit : saisie brief (destination, 25 logts, mix, R+4, emprise 55%, 1 place/logt, pleine terre 25%)
5. "Analyser" → stream SSE des étapes : fetch ✓ / zones ✓ / extraction UB 42s / capacité ✓ / analyse ✓
6. Si zone non validée → modale `<RuleValidator>` pour validation (bloquant)
7. Redirection `/projects/[id]/report` : carte PLU + tableaux + KPIs + comparaison + servitudes + analyse architecte
8. "Exporter PDF" → toast, téléchargement automatique du fichier `rapport-<nom-projet>.pdf`
9. Retour `/projects` : projet listé avec badge "Analysé" et confidence affichée

### 8.5 Génération du rapport (HTML + PDF)

- Template Jinja2 unique `core/reports/templates/feasibility.html.j2`
- CSS print `@page` avec marges A4, header/footer, numérotation automatique, sauts de page contrôlés
- Carte statique via IGN WMS (`GetMap`) incrustée PNG/SVG
- Charts en SVG inline (Recharts serveur-side ou équivalent Python `matplotlib` sobre)
- Versions :
  - **HTML** : servi par FastAPI (`/feasibility/{id}/report.html`), rendu côté navigateur pour interactivité
  - **PDF** : généré par WeasyPrint (worker ARQ) puis uploadé R2 et accessible via signed URL

---

## 9. Authentification et sécurité

### 9.1 Stack

- **Frontend** : Auth.js (NextAuth v5) avec providers Google + Credentials
- **Backend** : vérification JWT HS256 via clé partagée `JWT_SECRET`, dépendance FastAPI `get_current_user`
- **Password hashing** : bcrypt rounds=12 via `passlib`

### 9.2 Sessions

- JWT signés HS256, durée 7 jours
- Refresh glissant : chaque requête authentifiée réémet un JWT frais si expire dans <24h
- Stockage côté Next.js : cookie `httpOnly` + `secure` + `sameSite=lax`

### 9.3 Sécurité applicative

- RLS Postgres activée (§6.3) + filtre défensif backend sur toutes queries
- CORS restrictif : origine `archiclaude.app` et `*.vercel.app` preview uniquement
- CSRF : géré automatiquement par Auth.js
- Headers : HSTS, CSP stricte, `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`
- HTTPS partout, HTTP → HTTPS redirect
- Rate limiting (§7.6)

### 9.4 Secrets

- `NEXTAUTH_SECRET` (sign JWT Next.js)
- `JWT_SECRET` (sign JWT backend — doit matcher Next.js)
- `DATABASE_URL` (Neon avec pgvector)
- `REDIS_URL` (Upstash)
- `ANTHROPIC_API_KEY`
- `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_ENDPOINT`
- `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`
- `MAPILLARY_CLIENT_TOKEN` (photos site principales)
- `GOOGLE_STREETVIEW_API_KEY` (fallback photos payant)
- `NAVITIA_API_KEY` (fréquence transports IDF via STIF)
- `OPENAI_API_KEY` OU `VOYAGE_API_KEY` (embeddings pgvector — choix en Phase 6 selon rapport qualité/coût)

Stockés dans Vercel env vars (frontend) et Railway secrets (backend). Jamais commités.

---

## 10. Déploiement et infrastructure

### 10.1 Environnements

| Env | Branche | Frontend | Backend | DB | Redis |
|---|---|---|---|---|---|
| dev | local | Next.js local hot-reload | FastAPI local | Postgres Docker | Redis Docker |
| staging | `staging` | Vercel preview | Railway staging | Neon staging branch | Upstash staging |
| production | `main` | Vercel production | Railway production | Neon production | Upstash production |

### 10.2 CI/CD — GitHub Actions

Workflow `.github/workflows/ci.yml` :
- Sur chaque PR : lint (ruff + eslint), typecheck (mypy + tsc), tests (pytest + vitest)
- Sur merge `main` : déploiement auto via Vercel et Railway (listeners git)
- Tests E2E Playwright sur preview deploy

### 10.3 Observabilité

- Logs structurés JSON (`structlog` Python, `pino` TS) → Railway dashboard
- Export vers Axiom.co (free tier) pour recherche longue durée
- Sentry pour erreurs frontend + backend (free tier)
- Métriques custom exposées `/metrics` (format Prometheus) : coût Anthropic/user/jour, latence analyze, cache hit rate

### 10.4 Coûts mensuels estimés v1 (~100 users actifs)

| Poste | Coût estimé |
|---|---|
| Vercel | 0€ (Hobby) |
| Railway | 15-25€ (FastAPI + workers + RAG ingest) |
| Neon | 0-19€ (free ou upgrade si pgvector requis) |
| Upstash | 0€ (free) |
| Cloudflare R2 | ~2€ (rapports PDF + logos + photos cache) |
| Anthropic API | 50-120€ (extraction + numericizer + Opus analyse + RAG embeddings si Anthropic utilisé) |
| OpenAI/Voyage embeddings | 5-10€ (si utilisés pour pgvector) |
| Mapillary | 0€ (gratuit avec clé) |
| Google Street View (fallback) | 3-8€ (~500-1200 images/mois) |
| Navitia API STIF | 0€ (gratuit pour IDF) |
| Domaine + DNS | 15€/an (~1€/mois) |
| **Total** | **~75-185€/mois** |

---

## 11. Roadmap d'implémentation

Découpage en **10 phases / ~50 chunks** ordonnés, chacun finissable et testable indépendamment.

### Phase 0 — Setup & infrastructure technique (1.5 jours)

- **0.1** Repo GitHub créé (nom et visibilité à confirmer en amont), monorepo `apps/backend`, `apps/frontend`, `packages/shared-types`, `docs/`
- **0.2** Docker Compose dev (Postgres+PostGIS+pgvector, Redis, backend FastAPI, frontend Next.js hot-reload)
- **0.3** `.vscode/launch.json` avec targets debug FastAPI, Next.js, worker ARQ + `.vscode/tasks.json`
- **0.4** CI GitHub Actions (lint ruff+eslint, typecheck mypy+tsc, tests pytest+vitest, contract tests)
- **0.5** Déploiement initial vide Vercel + Railway + Neon (pgvector) + Upstash + R2
- **0.6** Fixtures de référence partagées `tests/fixtures/parcelles_reference.yaml` (5 parcelles avec valeurs chiffrées attendues — à remplir au fil des phases)
- **0.7** Feature flags table + module `core/flags.py` + endpoints admin + `<AdminFlagsTable>` minimal
- **0.8** Telemetry coûts LLM : middleware qui logge chaque appel Anthropic avec prompt_tokens / completion_tokens / cost_cents dans `audit_logs`
- **0.9** Pydantic → zod/TS pipeline auto dans `packages/shared-types/` (regen sur build)

### Phase 1 — Données parcelle & urbanisme (2 jours)

- **1.1** Clients Python `core/sources/` ports fidèles du bot existant : `ban.py`, `cadastre.py`, `gpu.py`, `ign_bdtopo.py`, `ign_bd_alti.py`, `georisques.py`, `pop.py`, `dpe.py`, `dvf.py`
- **1.2** Modèles SQLAlchemy + migrations Alembic initiales (users, parcels, plu_documents, plu_zones, servitudes, audit_logs)
- **1.3** Endpoints `/parcels/search`, `/parcels/at-point`, `/parcels/by-ref`, `/plu/at-point` avec cache Redis
- **1.4** Tests d'intégration avec fixtures réelles Nogent-sur-Marne + Paris 8e

### Phase 2 — Sources de site enrichies (1.5 jours)

- **2.1** `core/sources/mapillary.py` + `google_streetview.py` (fallback) → endpoint `/site/photos`
- **2.2** `core/sources/cerema_bruit.py` + `bruitparif.py` → endpoint `/site/bruit`
- **2.3** `core/sources/ign_transports.py` + `navitia.py` → endpoint `/site/transports` avec critère "bien desservie"
- **2.4** `core/sources/sirh.py` + ingestion datasets open data communes (Paris, Saint-Denis) → table `comparable_projects` + endpoint `/site/comparables`
- **2.5** `core/sources/insee_sru.py` ingestion dataset annuel → table `commune_sru`
- **2.6** `core/site/orientation.py` (calcul azimut segments) → endpoint `/site/orientation`
- **2.7** `core/site/voisinage.py` (BDTopo enrichi + vision Claude orthophoto pour ouvertures) → endpoint `/site/voisinage`
- **2.8** Tests intégration (5 parcelles de référence avec données site attendues)

### Phase 3 — Extraction règles PLU (2-3 jours)

- **3.1** Port Python fidèle de `parse-reglement/route.ts` → `core/plu/extractor.py` avec TOUS les raffinements du TS (multi-pass regex, filtre PLUi par commune, pré-filtrage fenêtre, scoring candidats, réparation JSON, retry ciblé, double cache mémoire+FS+DB)
- **3.2** Schéma `ParsedRules` Pydantic identique au TS
- **3.3** Cache DB `zone_rules_text` avec `pdf_sha256` + worker ARQ extraction async
- **3.4** Conversion `ParsedRules` → `NumericRules` via LLM dédié `core/plu/numericizer.py`
- **3.5** Parser dédié Paris Bioclimatique `core/plu/parsers/paris_bioclim.py` (zéro coût LLM Paris)
- **3.6** Endpoints `/plu/zone/{id}/rules`, `/extract`, `/validate` + `<RuleValidator>` feedback endpoint `/rules/{id}/feedback`
- **3.7** Tests : 5 zones de référence avec valeurs attendues chiffrées précises (Nogent UB, Paris 8e UG, Saint-Denis UM, Versailles UA, Meaux UC) + alignement avec `parcelles_reference.yaml`

### Phase 4 — Moteur de faisabilité PLU (2 jours)

- **4.1** `core/feasibility/footprint.py` (shapely reculs segments avec identification voirie/séparative/fond), `capacity.py` (SDP/niveaux/logements), `servitudes.py` (contraintes dures ABF/PPRI/EBC/alignement)
- **4.2** Coefficients brute→utile par typologie — **valeurs sourcées CSTB/AFNOR/USH**, pas d'invention. Tant que non sourcées, escalade "à valider manuellement"
- **4.3** Gestion multi-zones (calcul par zone, agrégation) + gabarit-enveloppe (mode simplifié + escalade "à valider" si oblique)
- **4.4** Endpoint `/projects/{id}/analyze` + worker ARQ + endpoint status + stream SSE
- **4.5** Tests : jeu de référence chiffré (valeurs SDP/emprise/logements croisées avec architecte ou DPU mairie, écart ≤ 1%)

### Phase 5 — Compliance complémentaire (1.5 jours)

- **5.1** `core/compliance/incendie.py` — classement 3ème/4ème famille / IGH selon hauteur, coefficients réduction SDP sourcés (Arrêté 31/01/1986 modifié)
- **5.2** `core/compliance/pmr.py` — ascenseur R+3+, logements adaptables, places PMR 2%
- **5.3** `core/compliance/re2020.py` — estimations prévisionnelles ic_construction, ic_energie, bbio, dh (coefficients à sourcer base INIES, affiché "indicatif")
- **5.4** `core/compliance/lls_sru.py` — détection commune carencée/rattrapage, obligation % LLS, bonus constructibilité si >35%
- **5.5** `core/compliance/rsdu.py` — obligations RSDU IDF (stationnement vélo, local poubelles, aération)
- **5.6** Intégration pipeline : post-calcul PLU, application compliance, mise à jour `FeasibilityResult.compliance`
- **5.7** Tests : 3 scénarios (R+7 habitat 4ème famille, commune carencée, RE2020 2028)

### Phase 6 — RAG jurisprudences & recours + analyse architecte (2 jours)

- **6.1** Tables `jurisprudences` + `recours_cases` avec pgvector
- **6.2** Worker `workers/rag_ingest.py` : ingestion initiale 200 décisions CE/TA PLU (scraping Légifrance) + 50 cas recours IDF (BDPR, presse locale)
- **6.3** `core/analysis/rag/jurisprudences.py` + `recours.py` (recherche pgvector par similarité + filtre commune)
- **6.4** Endpoints `/rag/jurisprudences/search`, `/rag/recours/search`
- **6.5** Module `core/analysis/architect_prompt.py` — prompt Claude Opus 4.6 avec contexte enrichi (site, compliance, comparables, jurisprudences, recours) et structure **note d'opportunité** imposée (Synthèse / Opportunités / Contraintes / Alertes / Recommandations, lexique métier)
- **6.6** Intégration pipeline `/analyze` → enrichit `FeasibilityResult.analyse_architecte_md` + traçabilité sources citées
- **6.7** Tests qualité sur 5 projets de référence (revue user, critères : respect structure, présence lexique métier, citations articles + jurisprudences pertinentes)

### Phase 7 — Génération rapport + versionnage (2 jours)

- **7.1** Normothèque SVG `core/drawing/conventions.py` (épaisseurs, hachures, polices, symboles, cartouches) — graine sous-projet 3, utilisée en v1 pour symboles carte + cartouche rapport
- **7.2** Bibliothèque architecture `core/architecture/library.py` (trames BA, épaisseurs, circulations, ascenseurs) — graine sous-projet 2, utilisée en v1 pour raffinement coefficients SDP utile
- **7.3** Template Jinja2 `core/reports/templates/feasibility.html.j2` — page titre avec orthophoto + photos site, sommaire auto, sections structurées (Contexte / Règles / Capacité / Compliance / Analyse / Comparables / Annexes), cartouche persistant, pieds de page
- **7.4** CSS `@page` print A4 + responsive web + style note d'opportunité (typo sobre, sections claires)
- **7.5** WeasyPrint via worker ARQ, upload R2, signed URLs
- **7.6** `core/reports/versioning.py` + table `project_versions` + endpoints `/projects/{id}/versions` (POST/GET/compare)
- **7.7** Endpoints `/feasibility/{id}/report.html`, `/report.pdf`, `/reports/{id}/download`
- **7.8** Module `core/reports/cartouche.py` — injection settings agence dans template

### Phase 8 — Frontend (4-5 jours)

- **8.1** Auth.js + pages login/signup/account
- **8.2** `<MapView>` MapLibre + overlays (parcelles, zones PLU, servitudes) + toggles overlay bruit/transports/voisinage/comparables
- **8.3** `<ParcelSearch>` + `<BriefForm>` + page `/projects/new`
- **8.4** Panneaux rapport : `<RulesPanel>`, `<FeasibilityDashboard>`, `<TypologyChart>`, `<ServitudesList>`, `<ComplianceSummary>`
- **8.5** Blocs site : `<SitePhotosGallery>`, `<OrientationDiagram>`, `<NoiseOverlay>`, `<TransportLayer>`, `<VoisinageLayer>`, `<ComparableProjectsList>`, `<DvfChart>`
- **8.6** Analyse : `<ArchitectureNoteRenderer>` (markdown structuré note d'opportunité), `<JurisprudencesSidebar>`, `<RecoursLocauxList>`
- **8.7** `<RuleValidator>` flow + page `/rules/[zone_id]` + POST feedback
- **8.8** `<VersionTimeline>` + `<VersionCompare>` + page `/projects/[id]/versions`
- **8.9** `<CartoucheEditor>` + page `/agency` + upload logo R2
- **8.10** Pages admin : `<AdminCostsDashboard>`, `<AdminPlayground>`, `<AdminTelemetryPanel>`
- **8.11** `<ReportExportButton>` + toasts + états de chargement

### Phase 9 — Tests E2E & polish (1 jour)

- **9.1** Playwright : scénario complet création projet → analyse → rapport PDF → nouvelle version
- **9.2** Smoke tests production post-déploiement (healthchecks, tests extraction 1 zone connue)
- **9.3** Documentation utilisateur (README + guide "Premier projet" + guide "Paramètres agence")

---

**Total estimé** : **18-22 jours** de dev soutenu pour le sous-projet 1 avec l'ensemble des enrichissements.

### Ordre de démarrage recommandé

Phase 0 → Phase 1 → Phase 2 (partiel : photos + orientation + bruit + transports suffisent pour démarrer) → Phase 3 → Phase 4 → Phase 5 → Phase 8 (partiel carte + brief pour tester) → Phase 2 (final : comparables + voisinage) → Phase 6 → Phase 7 → Phase 8 (final) → Phase 9.

### Points de jalon (milestones livrables)

- **J+3** (fin Phase 1) : on peut voir parcelles IDF sur carte, click, zonage affiché. Pas de règles ni calcul.
- **J+5** (fin Phase 3) : règles PLU extraites sur une zone testée, affichées en JSON.
- **J+7** (fin Phase 4) : faisabilité PLU calculée, valeurs chiffrées sur 3 parcelles de référence validées à ±1%.
- **J+9** (fin Phase 5) : compliance (incendie/PMR/RE2020/LLS) appliquée.
- **J+12** (fin Phase 6) : analyse architecte enrichie générée, style note d'opportunité.
- **J+14** (fin Phase 7) : rapport HTML + PDF avec cartouche personnalisable + versionnage.
- **J+20** (fin Phase 8) : frontend complet, parcours utilisateur bout-en-bout fonctionnel.
- **J+22** (fin Phase 9) : tests E2E verts, docs à jour, produit déployé en prod.

---

## 12. Annexes

### 12.1 Brief utilisateur (schéma complet)

```python
class Brief(BaseModel):
    # Programme (A-D)
    destination: Literal['logement_collectif','residence_service','bureaux','commerce','mixte']
    cible_nb_logements: int | None  # B
    mix_typologique: dict[Literal['T1','T2','T3','T4','T5'], float]  # C, sum = 1.0
    cible_sdp_m2: float | None  # D (redondant avec B+C, traité comme contrôle croisé)
    # Règle de réconciliation B/C/D : quand plusieurs fournis, le système calcule
    # la SDP implicite depuis B+C (nb_logts × surface_moy_pondérée) et la compare à D.
    # Si divergence >10%, affiche un warning "cibles brief incohérentes" dans le rapport.
    # Aucune correction automatique : les deux valeurs sont présentées séparément dans
    # l'analyse d'écart, et l'utilisateur décide laquelle retenir pour les itérations.
    # Contraintes architecturales (E-F)
    hauteur_cible_niveaux: int | None  # E, nombre total de niveaux y compris RDC (R+3 → 4) ; l'UI saisit en R+X et convertit +1 avant stockage
    emprise_cible_pct: float | None  # F, 0-100
    # Stationnement, espaces verts (G-H)
    stationnement_cible_par_logement: float | None  # G
    espaces_verts_pleine_terre_cible_pct: float | None  # H
    # Toujours mode maximisation sous contraintes PLU (pas de mode manuel en v1)
```

### 12.2 Conventions de projection

- Données entrée utilisateur (lat/lng) : **WGS84 / EPSG:4326**
- Stockage Postgres : WGS84 (SRID 4326)
- Calculs métriques (surfaces, buffers, distances) : **Lambert-93 / EPSG:2154** (reprojection via `pyproj` ou `ST_Transform`)
- Affichage carte MapLibre : WGS84

### 12.3 Glossaire

- **PLU** : Plan Local d'Urbanisme (règlement communal d'urbanisme)
- **PLUi** : PLU intercommunal (plusieurs communes partageant un PLU)
- **PLU Bioclimatique** : PLU parisien approuvé 20/11/2024, intégrant coefficients biotope et contraintes climatiques
- **POS** : Plan d'Occupation des Sols (ancien format, remplacé par PLU)
- **RNU** : Règlement National d'Urbanisme (applicable si pas de PLU/POS)
- **CC** : Carte Communale (document d'urbanisme simplifié)
- **GPU** : Géoportail de l'Urbanisme (portail national de publication des documents d'urbanisme)
- **SDP** : Surface De Plancher (surface taxable/calcul densité)
- **SU** : Surface Utile (surface utile habitable)
- **EBC** : Espaces Boisés Classés (zones protégées)
- **SUP** : Servitudes d'Utilité Publique
- **ABF** : Architecte des Bâtiments de France (avis obligatoire périmètre monuments historiques)
- **NGF** : Nivellement Général de la France (référence altimétrique)
- **DVF** : Demande de Valeurs Foncières (open data des ventes immobilières)
- **DPE** : Diagnostic de Performance Énergétique
- **PCMI** : Pièces Cerfa du dossier de Permis de Construire Maison Individuelle (et par extension pour collectif)
- **BDTopo** : Base de données topographique IGN (bâti, routes, etc.)

### 12.4 Références réglementaires

- PLU Bioclimatique de Paris approuvé 20/11/2024
- Code de l'urbanisme — articles L.151-8 et suivants
- Loi ALUR 2014 — suppression COS par défaut
- Article R.151-39 code urbanisme — gabarit-enveloppe
- Géoportail de l'Urbanisme : standard CNIG de structuration des documents

---

## Fin du document
