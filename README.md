# ArchiClaude

Plateforme web de faisabilité architecturale automatisée pour promoteurs immobiliers en Île-de-France. Analyse une parcelle, extrait les règles PLU, génère une étude de faisabilité complète et produit un dossier exportable en PDF.

**Statut :** Phase 9 terminée — application complète, 520 tests backend, 5 tests E2E, 27 endpoints.

---

## Démarrage rapide (Docker Compose)

```bash
# Cloner et installer
git clone <repo>
cd archiclaude
corepack enable
pnpm install

# Démarrer Postgres + Redis
docker compose up -d postgres redis

# Migrations
cd apps/backend
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
DATABASE_URL="postgresql://archiclaude:archiclaude@localhost:5432/archiclaude" alembic upgrade head
cd ../..

# Variables d'environnement
cp .env.example .env
# Remplir ANTHROPIC_API_KEY et les autres secrets

# Lancer tous les services
#   Terminal 1 : cd apps/backend && source .venv/bin/activate && uvicorn api.main:app --reload --port 8000
#   Terminal 2 : cd apps/backend && source .venv/bin/activate && arq workers.main.Worker
#   Terminal 3 : pnpm --filter @archiclaude/frontend dev
```

Accès :
- **Frontend** — http://localhost:3010
- **API (Swagger)** — http://localhost:8000/docs
- **Admin flags** — http://localhost:3010/admin/flags

> Port 3010 pour éviter tout conflit avec d'autres apps sur le port 3000.

---

## Architecture

Monorepo pnpm contenant deux applications principales et un package partagé.

```
archiclaude/
├── apps/
│   ├── backend/          — API FastAPI + workers ARQ
│   │   ├── api/          — routes HTTP (27 endpoints)
│   │   ├── core/         — logique métier (PLU, parcelles, site, RAG)
│   │   ├── db/           — modèles SQLAlchemy + Alembic
│   │   ├── schemas/      — Pydantic v2 (source de vérité des types)
│   │   ├── workers/      — tâches asynchrones (analyse, PDF)
│   │   ├── scripts/      — outils dev + smoke_test.py
│   │   └── tests/        — 520 tests (unit / integration / contract)
│   └── frontend/         — Next.js 16 (15 pages, ~35 composants)
│       ├── src/app/      — routes App Router
│       ├── src/components/ — UI components (shadcn/ui)
│       ├── src/lib/      — hooks, API client, types
│       └── e2e/          — tests Playwright (5 tests)
├── packages/
│   └── shared-types/     — types TypeScript générés depuis Pydantic
├── docs/
│   ├── guides/           — guides utilisateur en français
│   └── superpowers/      — specs et plans d'implémentation
├── docker/               — Dockerfiles pour déploiement
├── docker-compose.yml    — stack dev locale
└── .github/workflows/    — CI (lint + typecheck + 520 tests)
```

---

## Stack technique

| Couche | Technologie |
|---|---|
| Backend API | Python 3.12, FastAPI, Uvicorn |
| ORM / Migrations | SQLAlchemy 2.0, Alembic |
| Workers async | ARQ (Redis-backed) |
| Base de données | PostgreSQL 16 + PostGIS + pgvector |
| Cache / Queue | Redis |
| Stockage fichiers | Cloudflare R2 |
| LLM | Claude Sonnet 4.6, Opus 4.6, Haiku 4.5 (Anthropic) |
| Geo | shapely, geopandas, pyproj |
| Frontend | Next.js 16, React 19, TypeScript 5 |
| CSS | Tailwind CSS v4 |
| Composants UI | shadcn/ui (Radix UI) |
| Cartographie | MapLibre GL, react-map-gl |
| Auth | Auth.js (NextAuth v5) + JWT HS256 |
| Tests backend | pytest, pytest-asyncio, httpx |
| Tests E2E | Playwright (Chromium) |
| CI | GitHub Actions |

---

## Commandes de développement

```bash
# --- Backend ---
cd apps/backend && source .venv/bin/activate

# Lancer les tests (520 tests)
pytest -v

# Lancer les tests en mode watch
pytest -v --tb=short -x

# Linter + formatage
ruff check .
ruff format .

# Régénérer les migrations
alembic revision --autogenerate -m "description"
alembic upgrade head

# --- Frontend ---

# Développement (port 3010)
pnpm --filter @archiclaude/frontend dev

# Vérification TypeScript
pnpm --filter @archiclaude/frontend typecheck

# Build de production
pnpm --filter @archiclaude/frontend build

# Tests E2E Playwright
pnpm --filter @archiclaude/frontend test:e2e

# --- Outils partagés ---

# Régénérer les types TypeScript depuis Pydantic
cd apps/backend && source .venv/bin/activate
python scripts/generate_ts_schemas.py

# Smoke test post-déploiement
python scripts/smoke_test.py https://api.mondomaine.com
```

---

## API — 27 endpoints

### Santé
| Méthode | Endpoint | Description |
|---|---|---|
| GET | `/api/v1/health` | Statut du service |

### Parcelles (`/api/v1/parcels`)
| Méthode | Endpoint | Description |
|---|---|---|
| GET | `/parcels/search?q=` | Géocodage d'adresse (BAN) |
| GET | `/parcels/at-point?lat=&lng=` | Parcelle cadastrale au point GPS |
| GET | `/parcels/by-ref?ref=` | Parcelle par référence cadastrale |

### PLU (`/api/v1/plu`)
| Méthode | Endpoint | Description |
|---|---|---|
| GET | `/plu/at-point?lat=&lng=` | Zone PLU + règles à une coordonnée |
| GET | `/plu/zone/{zone_id}/rules` | Règles d'une zone PLU |
| POST | `/plu/zone/{zone_id}/extract` | Lancer l'extraction LLM des règles |
| GET | `/plu/extract/status/{job_id}` | Statut d'un job d'extraction |
| POST | `/plu/zone/{zone_id}/validate` | Valider les règles extraites |
| POST | `/plu/rules/{id}/feedback` | Enregistrer un retour utilisateur |

### Projets (`/api/v1/projects`)
| Méthode | Endpoint | Description |
|---|---|---|
| GET | `/projects` | Lister tous les projets |
| POST | `/projects` | Créer un nouveau projet |
| GET | `/projects/{id}` | Détail d'un projet |
| POST | `/projects/{id}/analyze` | Lancer l'analyse de faisabilité |
| GET | `/projects/{id}/analyze/status` | Statut de l'analyse en cours |

### Versions (`/api/v1/projects/{id}/versions`)
| Méthode | Endpoint | Description |
|---|---|---|
| GET | `/versions` | Lister les versions d'un projet |
| POST | `/versions` | Créer une version |
| GET | `/versions/compare` | Comparer deux versions |

### Site (`/api/v1/site`)
| Méthode | Endpoint | Description |
|---|---|---|
| GET | `/site/photos` | Photos aériennes et street-view |
| GET | `/site/bruit?lat=&lng=` | Classement sonore des voies |
| GET | `/site/transports?lat=&lng=` | Transports en commun proches |
| GET | `/site/voisinage?lat=&lng=` | Analyse du voisinage |
| GET | `/site/comparables` | Programmes comparables |
| GET | `/site/dvf` | Transactions DVF (prix foncier) |

### Rapports (`/api/v1`)
| Méthode | Endpoint | Description |
|---|---|---|
| GET | `/feasibility/{result_id}/report.html` | Rapport HTML de faisabilité |
| POST | `/feasibility/{result_id}/report.pdf` | Générer le PDF |
| GET | `/reports/{report_id}/download` | Télécharger le PDF |

### RAG (`/api/v1/rag`)
| Méthode | Endpoint | Description |
|---|---|---|
| GET | `/rag/jurisprudences/search?q=` | Recherche jurisprudence PLU |
| GET | `/rag/recours/search?q=` | Recherche recours contentieux |

### Administration (`/api/v1/admin`)
| Méthode | Endpoint | Description |
|---|---|---|
| GET | `/admin/feature-flags` | Lister les feature flags |
| PUT | `/admin/feature-flags/{key}` | Activer / désactiver un flag |

### Agence (`/api/v1/agency`)
| Méthode | Endpoint | Description |
|---|---|---|
| GET | `/agency/settings` | Paramètres de l'agence |
| PUT | `/agency/settings` | Mettre à jour les paramètres |
| POST | `/agency/logo` | Uploader le logo de l'agence |

---

## Prérequis

- Node 20+, pnpm 9+ (`corepack enable`)
- Python 3.12+
- Docker Desktop
- Homebrew (macOS) — `brew install cairo pango geos proj`

---

## Documentation

- [Guide : Premier projet](docs/guides/premier-projet.md)
- [Guide : Paramètres agence](docs/guides/parametres-agence.md)
- [Spec sous-projet 1](docs/superpowers/specs/2026-04-16-archiclaude-sous-projet-1-design.md)
- [Plan Phase 0](docs/superpowers/plans/2026-04-16-archiclaude-phase-0-setup.md)
