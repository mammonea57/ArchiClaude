# ArchiClaude

Plateforme web de faisabilité architecturale et de génération de dossiers PC pour promoteurs immobiliers en Île-de-France.

**Statut :** Phase 0 terminée — infrastructure technique prête.

## Documentation

- Spec sous-projet 1 : [docs/superpowers/specs/2026-04-16-archiclaude-sous-projet-1-design.md](docs/superpowers/specs/2026-04-16-archiclaude-sous-projet-1-design.md)
- Plan Phase 0 : [docs/superpowers/plans/2026-04-16-archiclaude-phase-0-setup.md](docs/superpowers/plans/2026-04-16-archiclaude-phase-0-setup.md)

## Stack technique

- **Backend** : Python 3.12, FastAPI, SQLAlchemy 2.0, Alembic, ARQ (workers), Anthropic SDK, shapely/geopandas/pyproj
- **Frontend** : Next.js 16, React 19, TypeScript 5, Tailwind v4, shadcn/ui, MapLibre GL (ajout Phase 6)
- **DB** : PostgreSQL 16 + PostGIS + pgvector (Neon en prod)
- **Cache/Queue** : Redis (Upstash en prod)
- **Stockage** : Cloudflare R2
- **Auth** : Auth.js (NextAuth v5) + JWT HS256
- **LLM** : Claude Sonnet 4.6 (extraction règles), Opus 4.6 (analyse), Haiku 4.5 (PLU mono-commune)

## Prérequis

- Node 20+, pnpm 9+
- Python 3.12+
- Docker Desktop
- Homebrew (macOS) pour `cairo`, `pango`, `geos`, `proj`
- Activer corepack : `corepack enable`

## Développement local

```bash
# 1. Installer les deps racine et frontend
pnpm install

# 2. Créer le venv backend et installer les deps Python
cd apps/backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cd ../..

# 3. Démarrer Postgres + Redis
docker compose up -d postgres redis

# 4. Appliquer les migrations
cd apps/backend
source .venv/bin/activate
DATABASE_URL="postgresql://archiclaude:archiclaude@localhost:5432/archiclaude" alembic upgrade head
cd ../..

# 5. Copier les variables d'env
cp .env.example .env
# Remplir les secrets ANTHROPIC_API_KEY, etc.

# 6. Lancer les services
# Option A — Via VSCode : "Run and Debug" (Cmd+Shift+D) → "🧱 Full Stack"
# Option B — Via terminal :
#   Terminal 1: cd apps/backend && source .venv/bin/activate && uvicorn api.main:app --reload --port 8000
#   Terminal 2: cd apps/backend && source .venv/bin/activate && arq workers.main.Worker
#   Terminal 3: pnpm --filter @archiclaude/frontend dev
```

Accès :
- Backend : http://localhost:8000 (docs Swagger : /docs)
- Frontend : http://localhost:3001
- Admin flags : http://localhost:3001/admin/flags

> Port 3001 choisi pour éviter le conflit avec l'autre application Urbanisme (port 3000).

## Tests

```bash
# Backend (23 tests)
cd apps/backend && source .venv/bin/activate
pytest -v

# Frontend (typecheck + build)
pnpm --filter @archiclaude/frontend typecheck
pnpm --filter @archiclaude/frontend build
```

## Régénérer les types partagés (Pydantic → TS)

```bash
cd apps/backend && source .venv/bin/activate
python scripts/generate_ts_schemas.py
```

## Structure du monorepo

```
apps/
  backend/    — API FastAPI + workers ARQ
  frontend/   — Next.js SPA
packages/
  shared-types/  — types TS générés depuis Pydantic
docs/
  superpowers/
    specs/     — spécifications produit
    plans/     — plans d'implémentation par phase
.github/workflows/
  ci.yml       — lint + typecheck + tests à chaque PR
.vscode/
  launch.json  — debug configs (Backend / Worker / Frontend / Full Stack)
docker-compose.yml  — stack dev locale
```

## Prochaine phase

Phase 1 — Données parcelle & urbanisme : ingestion cadastre, GPU, BAN, IGN BDTopo, endpoints `/parcels/*` et `/plu/at-point`.
