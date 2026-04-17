# ArchiClaude — Phase 0 : Setup & Infrastructure Technique — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poser la fondation technique d'ArchiClaude : monorepo, Docker Compose dev, CI GitHub Actions, déploiement managé vide, modules transversaux (feature flags, telemetry coûts LLM, génération types partagés), fixtures de référence.

**Architecture:** Monorepo pnpm avec `apps/backend` (Python 3.12 + FastAPI + ARQ), `apps/frontend` (Next.js 16 + React 19 + Tailwind v4 + shadcn/ui), `packages/shared-types` (types TS auto-générés depuis Pydantic). PostgreSQL+PostGIS+pgvector local via Docker. CI GitHub Actions, déploiement Vercel + Railway + Neon + Upstash + Cloudflare R2.

**Tech Stack:** Python 3.12, FastAPI 0.115+, SQLAlchemy 2.0, Alembic, ARQ, Pydantic 2, pytest, Next.js 16, React 19, TypeScript 5, Tailwind v4, shadcn/ui, pnpm, Docker Compose, GitHub Actions.

**Spec source:** `docs/superpowers/specs/2026-04-16-archiclaude-sous-projet-1-design.md`

**Reference context:** User's existing working bot at `~/Desktop/Urbanisme app/urbanisme-france-live/` should be read-only referenced for patterns (especially `src/lib/api.ts` and `src/app/api/parse-reglement/route.ts`). Never modify files there.

---

## File Structure (final état Phase 0)

```
ArchiClaude/
├── .github/workflows/
│   ├── ci.yml
│   └── deploy-staging.yml
├── .vscode/
│   ├── launch.json
│   ├── tasks.json
│   └── settings.json
├── apps/
│   ├── backend/
│   │   ├── alembic/
│   │   │   ├── env.py
│   │   │   ├── script.py.mako
│   │   │   └── versions/20260416_0001_init.py
│   │   ├── core/__init__.py
│   │   ├── core/flags.py
│   │   ├── api/main.py
│   │   ├── api/deps.py
│   │   ├── api/routes/health.py
│   │   ├── api/routes/admin/flags.py
│   │   ├── api/middleware/cost_tracking.py
│   │   ├── api/middleware/request_id.py
│   │   ├── db/base.py
│   │   ├── db/session.py
│   │   ├── db/models/audit_logs.py
│   │   ├── db/models/feature_flags.py
│   │   ├── schemas/feature_flag.py
│   │   ├── schemas/audit_log.py
│   │   ├── workers/main.py
│   │   ├── scripts/generate_ts_schemas.py
│   │   ├── tests/conftest.py
│   │   ├── tests/fixtures/parcelles_reference.yaml
│   │   ├── tests/unit/test_health.py
│   │   ├── tests/unit/test_feature_flags.py
│   │   ├── tests/unit/test_cost_tracking.py
│   │   ├── tests/integration/test_flags_endpoints.py
│   │   ├── pyproject.toml
│   │   ├── alembic.ini
│   │   ├── Dockerfile.dev
│   │   └── .dockerignore
│   └── frontend/
│       ├── src/app/layout.tsx
│       ├── src/app/page.tsx
│       ├── src/app/admin/flags/page.tsx
│       ├── src/components/ui/             (shadcn seed)
│       ├── src/components/admin/FlagsTable.tsx
│       ├── src/lib/api.ts
│       ├── src/types/generated/.gitkeep
│       ├── next.config.ts
│       ├── package.json
│       ├── tsconfig.json
│       ├── tailwind.config.ts
│       ├── postcss.config.mjs
│       ├── components.json                  (shadcn)
│       ├── Dockerfile.dev
│       └── .dockerignore
├── packages/shared-types/
│   ├── package.json
│   ├── src/index.ts
│   ├── src/generated/.gitkeep
│   └── tsconfig.json
├── docs/superpowers/
│   ├── specs/2026-04-16-archiclaude-sous-projet-1-design.md (déjà présent)
│   └── plans/2026-04-16-archiclaude-phase-0-setup.md         (ce document)
├── docker-compose.yml
├── .env.example
├── .gitignore
├── README.md
├── pnpm-workspace.yaml
├── package.json
└── .nvmrc
```

**Responsabilités par fichier :**
- `apps/backend/api/main.py` : FastAPI app factory, registre routes, lifespan DB
- `apps/backend/api/deps.py` : dépendances injectables (db session, current user placeholder)
- `apps/backend/core/flags.py` : module métier feature flags (lecture + check), pur core
- `apps/backend/db/` : SQLAlchemy base, session async, modèles ORM
- `apps/backend/api/middleware/cost_tracking.py` : middleware qui log coût Anthropic
- `apps/backend/workers/main.py` : entry point ARQ (queues vides en Phase 0)
- `apps/backend/scripts/generate_ts_schemas.py` : génération JSON Schema → zod TS
- `apps/frontend/src/app/admin/flags/page.tsx` : page admin table feature flags
- `docker-compose.yml` : Postgres+PostGIS+pgvector, Redis, backend, frontend
- `.github/workflows/ci.yml` : lint, typecheck, tests

---

## Task 1: Initialiser le monorepo (git + pnpm workspace + fichiers racine)

**Files:**
- Create: `/Users/anthonymammone/Desktop/ArchiClaude/.gitignore`
- Create: `/Users/anthonymammone/Desktop/ArchiClaude/.nvmrc`
- Create: `/Users/anthonymammone/Desktop/ArchiClaude/README.md`
- Create: `/Users/anthonymammone/Desktop/ArchiClaude/package.json`
- Create: `/Users/anthonymammone/Desktop/ArchiClaude/pnpm-workspace.yaml`
- Create: `/Users/anthonymammone/Desktop/ArchiClaude/.env.example`

- [ ] **Step 1: Vérifier présence pnpm et installer Node 20 si manquant**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
node --version  # attendu: v20.x ou supérieur
pnpm --version  # attendu: 9.x ou supérieur
```

Si absent :
```bash
brew install pnpm
corepack enable
corepack prepare pnpm@latest --activate
```

- [ ] **Step 2: Initialiser le repo git**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git init -b main
```

- [ ] **Step 3: Créer `.gitignore` racine**

```gitignore
# Node
node_modules/
.pnpm-store/
.next/
out/
dist/
*.log
.turbo/

# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
.venv/
venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
htmlcov/
.coverage

# Editor
.vscode/*
!.vscode/launch.json
!.vscode/tasks.json
!.vscode/settings.json
!.vscode/extensions.json
.idea/
*.swp
.DS_Store

# Env
.env
.env.local
.env.*.local

# Build artefacts générés
apps/frontend/src/types/generated/*
!apps/frontend/src/types/generated/.gitkeep
packages/shared-types/src/generated/*
!packages/shared-types/src/generated/.gitkeep

# Docker
docker-compose.override.yml

# Cloud runtime files
tmp/
.vercel/
```

- [ ] **Step 4: Créer `.nvmrc`**

```
20
```

- [ ] **Step 5: Créer `README.md` minimal**

```markdown
# ArchiClaude

Plateforme web de faisabilité architecturale et de génération de dossiers PC pour promoteurs immobiliers en Île-de-France.

**Statut :** Phase 0 — setup infrastructure technique.

**Documentation :**
- Spec sous-projet 1 : [docs/superpowers/specs/2026-04-16-archiclaude-sous-projet-1-design.md](docs/superpowers/specs/2026-04-16-archiclaude-sous-projet-1-design.md)
- Plan Phase 0 : [docs/superpowers/plans/2026-04-16-archiclaude-phase-0-setup.md](docs/superpowers/plans/2026-04-16-archiclaude-phase-0-setup.md)

## Développement local

Prérequis : Node 20+, pnpm 9+, Python 3.12+, Docker Desktop.

```bash
pnpm install
docker compose up -d postgres redis
pnpm dev
```

Backend : http://localhost:8000/docs
Frontend : http://localhost:3001

> Port 3001 côté frontend pour ne pas entrer en conflit avec l'autre application Urbanisme (port 3000).
```

- [ ] **Step 6: Créer `pnpm-workspace.yaml`**

```yaml
packages:
  - 'apps/*'
  - 'packages/*'
```

- [ ] **Step 7: Créer `package.json` racine**

```json
{
  "name": "archiclaude",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "pnpm -r --parallel dev",
    "build": "pnpm -r build",
    "lint": "pnpm -r lint",
    "typecheck": "pnpm -r typecheck",
    "test": "pnpm -r test",
    "format": "prettier --write \"**/*.{ts,tsx,md,json,yml,yaml}\""
  },
  "devDependencies": {
    "prettier": "^3.3.3",
    "typescript": "^5.6.3"
  },
  "packageManager": "pnpm@9.12.3",
  "engines": {
    "node": ">=20.0.0",
    "pnpm": ">=9.0.0"
  }
}
```

- [ ] **Step 8: Créer `.env.example`**

```bash
# ─── Backend ──────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://archiclaude:archiclaude@localhost:5432/archiclaude
REDIS_URL=redis://localhost:6379/0
BACKEND_PORT=8000

# Secrets — remplir localement, JAMAIS committé
JWT_SECRET=change-me-32-chars-minimum-for-local-dev-only
ANTHROPIC_API_KEY=
OPENAI_API_KEY=
MAPILLARY_CLIENT_TOKEN=
GOOGLE_STREETVIEW_API_KEY=
NAVITIA_API_KEY=

# ─── Storage R2 (Cloudflare) ──────────────────────────────
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET=archiclaude-reports-dev
R2_ENDPOINT=

# ─── OAuth Google ─────────────────────────────────────────
GOOGLE_OAUTH_CLIENT_ID=
GOOGLE_OAUTH_CLIENT_SECRET=

# ─── Frontend ─────────────────────────────────────────────
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXT_PUBLIC_MAP_DEFAULT_LAT=48.8566
NEXT_PUBLIC_MAP_DEFAULT_LNG=2.3522
NEXTAUTH_URL=http://localhost:3001
NEXTAUTH_SECRET=change-me-32-chars-minimum-for-local-dev-only
```

- [ ] **Step 9: Installer les devDependencies racine**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
pnpm install
```

Expected: crée `node_modules/`, installe prettier + typescript.

- [ ] **Step 10: Premier commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add .gitignore .nvmrc README.md package.json pnpm-workspace.yaml .env.example pnpm-lock.yaml
git commit -m "chore: initialize monorepo with pnpm workspace"
```

---

## Task 2: Setup backend Python (pyproject.toml, venv, dépendances)

**Files:**
- Create: `apps/backend/pyproject.toml`
- Create: `apps/backend/.python-version`
- Create: `apps/backend/.dockerignore`

- [ ] **Step 1: Vérifier Python 3.12 présent**

```bash
python3.12 --version  # attendu: Python 3.12.x
```

Si absent :
```bash
brew install python@3.12
```

- [ ] **Step 2: Créer `apps/backend/.python-version`**

```
3.12
```

- [ ] **Step 3: Créer `apps/backend/pyproject.toml`**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "archiclaude-backend"
version = "0.1.0"
description = "ArchiClaude backend — faisabilité architecturale IDF"
requires-python = ">=3.12"
dependencies = [
    # Web framework
    "fastapi[standard]==0.115.4",
    "uvicorn[standard]==0.32.0",
    "python-multipart==0.0.17",

    # DB
    "sqlalchemy[asyncio]==2.0.36",
    "asyncpg==0.30.0",
    "alembic==1.13.3",
    "pgvector==0.3.5",

    # Data modeling
    "pydantic==2.9.2",
    "pydantic-settings==2.6.1",
    "email-validator==2.2.0",

    # HTTP client
    "httpx==0.27.2",
    "tenacity==9.0.0",

    # LLM
    "anthropic==0.39.0",

    # Workers
    "arq==0.26.1",
    "redis==5.2.0",

    # Geospatial
    "shapely==2.0.6",
    "pyproj==3.7.0",
    "geopandas==1.0.1",
    "rasterio==1.4.2",

    # PDF generation
    "weasyprint==63.0",
    "jinja2==3.1.4",
    "pypdf==5.1.0",
    "pdfplumber==0.11.4",

    # Auth
    "passlib[bcrypt]==1.7.4",
    "python-jose[cryptography]==3.3.0",
    "slowapi==0.1.9",

    # Logging / observabilité
    "structlog==24.4.0",

    # Config fixtures
    "pyyaml==6.0.2",
]

[project.optional-dependencies]
dev = [
    "pytest==8.3.3",
    "pytest-asyncio==0.24.0",
    "pytest-cov==6.0.0",
    "pytest-httpx==0.33.0",
    "ruff==0.7.4",
    "mypy==1.13.0",
    "types-PyYAML==6.0.12.20240917",
]

[tool.hatch.build.targets.wheel]
packages = ["api", "core", "db", "schemas", "workers"]

[tool.ruff]
line-length = 110
target-version = "py312"
exclude = ["alembic/versions"]

[tool.ruff.lint]
select = ["E", "F", "I", "N", "UP", "B", "A", "C4", "T20", "RET", "SIM", "TCH"]
ignore = ["E501"]  # line length géré par formatter

[tool.ruff.format]
quote-style = "double"

[tool.mypy]
python_version = "3.12"
strict = true
plugins = ["pydantic.mypy"]
exclude = ["alembic/"]

[[tool.mypy.overrides]]
module = ["shapely.*", "pyproj.*", "geopandas.*", "rasterio.*", "weasyprint.*"]
ignore_missing_imports = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-ra --cov=core --cov=api --cov=db --cov-report=term-missing"
```

- [ ] **Step 4: Créer `apps/backend/.dockerignore`**

```
__pycache__/
*.pyc
.venv/
.pytest_cache/
.mypy_cache/
.ruff_cache/
tests/
*.md
```

- [ ] **Step 5: Créer le venv et installer les deps**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
python3.12 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -e ".[dev]"
```

Expected: installation réussie, environnement activé. Si erreur `weasyprint`, installer `cairo` + `pango` via brew :
```bash
brew install cairo pango gdk-pixbuf libffi
```

- [ ] **Step 6: Créer structure de dossiers backend**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
mkdir -p core api/routes/admin api/middleware db/models schemas workers scripts tests/unit tests/integration tests/contract tests/fixtures alembic/versions
touch core/__init__.py api/__init__.py api/routes/__init__.py api/routes/admin/__init__.py api/middleware/__init__.py db/__init__.py db/models/__init__.py schemas/__init__.py workers/__init__.py tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py tests/contract/__init__.py
```

- [ ] **Step 7: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/pyproject.toml apps/backend/.python-version apps/backend/.dockerignore apps/backend/core apps/backend/api apps/backend/db apps/backend/schemas apps/backend/workers apps/backend/scripts apps/backend/tests apps/backend/alembic
git commit -m "chore(backend): scaffold Python project with pyproject.toml and dirs"
```

---

## Task 3: Backend — health check endpoint (TDD)

**Files:**
- Create: `apps/backend/api/main.py`
- Create: `apps/backend/api/routes/health.py`
- Create: `apps/backend/tests/conftest.py`
- Create: `apps/backend/tests/unit/test_health.py`

- [ ] **Step 1: Créer `tests/conftest.py`**

```python
from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient

from api.main import create_app


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
```

- [ ] **Step 2: Écrire le test de health check qui va échouer**

Fichier `apps/backend/tests/unit/test_health.py` :
```python
from httpx import AsyncClient


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "archiclaude-backend"}
```

- [ ] **Step 3: Lancer le test pour vérifier qu'il échoue**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
source .venv/bin/activate
pytest tests/unit/test_health.py -v
```

Expected: `ModuleNotFoundError: No module named 'api.main'` ou équivalent.

- [ ] **Step 4: Implémenter `api/routes/health.py`**

```python
from fastapi import APIRouter

router = APIRouter()


@router.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "archiclaude-backend"}
```

- [ ] **Step 5: Implémenter `api/main.py`**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import health


def create_app() -> FastAPI:
    app = FastAPI(
        title="ArchiClaude API",
        version="0.1.0",
        description="API faisabilité architecturale IDF",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3001", "http://127.0.0.1:3001"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api/v1")
    return app


app = create_app()
```

- [ ] **Step 6: Corriger le test (préfixe `/api/v1`)**

Modifier `tests/unit/test_health.py` :
```python
from httpx import AsyncClient


async def test_health_returns_ok(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "archiclaude-backend"}
```

- [ ] **Step 7: Lancer le test — doit passer**

```bash
pytest tests/unit/test_health.py -v
```

Expected: `1 passed`.

- [ ] **Step 8: Vérifier le démarrage du serveur**

```bash
uvicorn api.main:app --reload --port 8000
```

Dans un autre terminal :
```bash
curl http://localhost:8000/api/v1/health
```

Expected: `{"status":"ok","service":"archiclaude-backend"}`.

Ctrl+C pour arrêter.

- [ ] **Step 9: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/api apps/backend/tests
git commit -m "feat(backend): add health check endpoint with test"
```

---

## Task 4: Backend — SQLAlchemy async + Alembic + migration initiale

**Files:**
- Create: `apps/backend/db/base.py`
- Create: `apps/backend/db/session.py`
- Create: `apps/backend/alembic.ini`
- Create: `apps/backend/alembic/env.py`
- Create: `apps/backend/alembic/script.py.mako`
- Create: `apps/backend/alembic/versions/20260416_0001_init.py`
- Create: `apps/backend/tests/integration/test_db_connection.py`

- [ ] **Step 1: Créer `apps/backend/db/base.py`**

```python
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base SQLAlchemy 2.0 pour tous les modèles ORM."""
```

- [ ] **Step 2: Créer `apps/backend/db/session.py`**

```python
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


class DbSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+asyncpg://archiclaude:archiclaude@localhost:5432/archiclaude"


_settings = DbSettings()

engine = create_async_engine(
    _settings.database_url,
    echo=False,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
)

AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with AsyncSessionLocal() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
```

- [ ] **Step 3: Créer `apps/backend/alembic.ini`**

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
timezone = UTC
output_encoding = utf-8
sqlalchemy.url = postgresql://archiclaude:archiclaude@localhost:5432/archiclaude

[loggers]
keys = root,sqlalchemy,alembic

[handlers]
keys = console

[formatters]
keys = generic

[logger_root]
level = WARN
handlers = console
qualname =

[logger_sqlalchemy]
level = WARN
handlers =
qualname = sqlalchemy.engine

[logger_alembic]
level = INFO
handlers =
qualname = alembic

[handler_console]
class = StreamHandler
args = (sys.stderr,)
level = NOTSET
formatter = generic

[formatter_generic]
format = %(levelname)-5.5s [%(name)s] %(message)s
datefmt = %H:%M:%S
```

- [ ] **Step 4: Créer `apps/backend/alembic/env.py`**

```python
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from db.base import Base
# Import all models so Base.metadata is populated
from db.models import audit_logs, feature_flags  # noqa: F401

config = context.config

# Remplace l'URL synchrone par celle de l'env si présente (avec driver sync pour Alembic)
database_url = os.getenv("DATABASE_URL", "postgresql://archiclaude:archiclaude@localhost:5432/archiclaude")
# Alembic utilise le driver sync, pas asyncpg
sync_url = database_url.replace("postgresql+asyncpg://", "postgresql://")
config.set_main_option("sqlalchemy.url", sync_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section) or {},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
```

- [ ] **Step 5: Créer `apps/backend/alembic/script.py.mako`**

```python
"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

revision: str = ${repr(up_revision)}
down_revision: str | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}


def upgrade() -> None:
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    ${downgrades if downgrades else "pass"}
```

- [ ] **Step 6: Créer `apps/backend/alembic/versions/20260416_0001_init.py`**

```python
"""init: extensions postgis, pgcrypto, pg_trgm, vector

Revision ID: 20260416_0001
Revises:
Create Date: 2026-04-16 00:00:00

"""
from collections.abc import Sequence

from alembic import op

revision: str = "20260416_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS vector")
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
    op.execute("DROP EXTENSION IF EXISTS postgis")
```

- [ ] **Step 7: Créer placeholders pour modèles ORM (alembic/env.py les importe)**

`apps/backend/db/models/audit_logs.py` :
```python
"""Audit logs table. Vide en Phase 0, implémenté en tasks suivants."""
```

`apps/backend/db/models/feature_flags.py` :
```python
"""Feature flags table. Implémenté en Task 6."""
```

- [ ] **Step 8: Écrire test de connexion DB**

`apps/backend/tests/integration/test_db_connection.py` :
```python
import pytest
from sqlalchemy import text

from db.session import engine


@pytest.mark.asyncio
async def test_database_is_reachable() -> None:
    async with engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar() == 1


@pytest.mark.asyncio
async def test_postgis_extension_available() -> None:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname='postgis'")
        )
        assert result.scalar() == "postgis"


@pytest.mark.asyncio
async def test_pgvector_extension_available() -> None:
    async with engine.connect() as conn:
        result = await conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname='vector'")
        )
        assert result.scalar() == "vector"
```

- [ ] **Step 9: Lancer Docker Compose (on le créera en Task 11, pour le moment démarrer un Postgres ad-hoc)**

```bash
docker run --name archiclaude-pg-temp -d \
  -e POSTGRES_USER=archiclaude \
  -e POSTGRES_PASSWORD=archiclaude \
  -e POSTGRES_DB=archiclaude \
  -p 5432:5432 \
  pgvector/pgvector:pg16
```

Attendre 10s que Postgres démarre. Puis vérifier :
```bash
docker exec archiclaude-pg-temp pg_isready -U archiclaude
```

- [ ] **Step 10: Exécuter la migration initiale**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
source .venv/bin/activate
DATABASE_URL="postgresql://archiclaude:archiclaude@localhost:5432/archiclaude" alembic upgrade head
```

Expected: `Running upgrade -> 20260416_0001, init: extensions postgis, pgcrypto, pg_trgm, vector`.

Si PostGIS manque dans l'image (certaines builds `pgvector/pgvector:pg16` n'ont pas PostGIS), arrêter le container et utiliser une image combinée :
```bash
docker stop archiclaude-pg-temp && docker rm archiclaude-pg-temp
docker run --name archiclaude-pg-temp -d \
  -e POSTGRES_USER=archiclaude -e POSTGRES_PASSWORD=archiclaude -e POSTGRES_DB=archiclaude \
  -p 5432:5432 \
  postgis/postgis:16-3.4
# puis installer pgvector manuellement:
docker exec -u postgres archiclaude-pg-temp bash -c "apt-get update && apt-get install -y postgresql-16-pgvector"
```
**Note** : en Task 11, on construira une image custom qui intègre les deux. Pour le moment ce container temporaire suffit.

- [ ] **Step 11: Lancer les tests d'intégration**

```bash
pytest tests/integration/test_db_connection.py -v
```

Expected: `3 passed`.

- [ ] **Step 12: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/db apps/backend/alembic.ini apps/backend/alembic apps/backend/tests/integration
git commit -m "feat(backend): setup SQLAlchemy async + Alembic with initial migration (postgis, pgvector)"
```

---

## Task 5: Backend — Module feature flags + table + endpoints admin (TDD)

**Files:**
- Modify: `apps/backend/db/models/feature_flags.py`
- Create: `apps/backend/alembic/versions/20260416_0002_feature_flags.py`
- Create: `apps/backend/schemas/feature_flag.py`
- Create: `apps/backend/core/flags.py`
- Create: `apps/backend/api/routes/admin/flags.py`
- Modify: `apps/backend/api/main.py`
- Create: `apps/backend/tests/unit/test_feature_flags.py`
- Create: `apps/backend/tests/integration/test_flags_endpoints.py`

- [ ] **Step 1: Écrire le test unitaire du module core/flags.py (va échouer)**

`apps/backend/tests/unit/test_feature_flags.py` :
```python
from uuid import UUID, uuid4

import pytest

from core.flags import FeatureFlag, is_enabled


@pytest.mark.asyncio
async def test_flag_disabled_by_default() -> None:
    flag = FeatureFlag(
        key="enable_oblique_gabarit",
        enabled_globally=False,
        enabled_for_user_ids=[],
    )
    assert await is_enabled(flag, user_id=None) is False


@pytest.mark.asyncio
async def test_flag_enabled_globally_returns_true_for_any_user() -> None:
    flag = FeatureFlag(
        key="enable_oblique_gabarit",
        enabled_globally=True,
        enabled_for_user_ids=[],
    )
    assert await is_enabled(flag, user_id=None) is True
    assert await is_enabled(flag, user_id=uuid4()) is True


@pytest.mark.asyncio
async def test_flag_enabled_for_specific_user() -> None:
    user_id = uuid4()
    other_user_id = uuid4()
    flag = FeatureFlag(
        key="enable_oblique_gabarit",
        enabled_globally=False,
        enabled_for_user_ids=[user_id],
    )
    assert await is_enabled(flag, user_id=user_id) is True
    assert await is_enabled(flag, user_id=other_user_id) is False
    assert await is_enabled(flag, user_id=None) is False


@pytest.mark.asyncio
async def test_flag_global_wins_over_user_list() -> None:
    flag = FeatureFlag(
        key="enable_oblique_gabarit",
        enabled_globally=True,
        enabled_for_user_ids=[uuid4()],
    )
    assert await is_enabled(flag, user_id=None) is True
```

- [ ] **Step 2: Lancer le test — doit échouer**

```bash
pytest tests/unit/test_feature_flags.py -v
```

Expected: `ModuleNotFoundError: No module named 'core.flags'`.

- [ ] **Step 3: Implémenter `core/flags.py`**

```python
from dataclasses import dataclass, field
from uuid import UUID


@dataclass(frozen=True)
class FeatureFlag:
    key: str
    enabled_globally: bool
    enabled_for_user_ids: list[UUID] = field(default_factory=list)
    description: str | None = None


async def is_enabled(flag: FeatureFlag, user_id: UUID | None) -> bool:
    """Retourne True si le flag est actif pour cet utilisateur.

    Règles :
    - `enabled_globally=True` écrase tout (actif pour tout le monde, y compris anonymes)
    - sinon, actif uniquement si `user_id` est dans `enabled_for_user_ids`
    - anonyme (user_id=None) n'est jamais actif sauf si global
    """
    if flag.enabled_globally:
        return True
    if user_id is None:
        return False
    return user_id in flag.enabled_for_user_ids
```

- [ ] **Step 4: Relancer le test — doit passer**

```bash
pytest tests/unit/test_feature_flags.py -v
```

Expected: `4 passed`.

- [ ] **Step 5: Implémenter le modèle ORM `feature_flags`**

`apps/backend/db/models/feature_flags.py` :
```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import ARRAY, TIMESTAMP, Boolean, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class FeatureFlagRow(Base):
    __tablename__ = "feature_flags"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    enabled_globally: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    enabled_for_user_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PgUUID(as_uuid=True)),
        nullable=False,
        server_default="{}",
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
```

- [ ] **Step 6: Générer la migration pour la table**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
source .venv/bin/activate
DATABASE_URL="postgresql://archiclaude:archiclaude@localhost:5432/archiclaude" alembic revision --autogenerate -m "feature_flags table"
```

Expected: crée `alembic/versions/<timestamp>_feature_flags_table.py`. Renommer le fichier en `20260416_0002_feature_flags.py` pour cohérence, et modifier `revision` en `"20260416_0002"` et `down_revision = "20260416_0001"` en tête.

Vérifier que le fichier généré contient bien `op.create_table("feature_flags", ...)`. Sinon, écrire manuellement :

```python
"""feature_flags table

Revision ID: 20260416_0002
Revises: 20260416_0001
Create Date: 2026-04-16 00:01:00

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260416_0002"
down_revision: str | None = "20260416_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feature_flags",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("enabled_globally", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "enabled_for_user_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("feature_flags")
```

- [ ] **Step 7: Appliquer la migration**

```bash
DATABASE_URL="postgresql://archiclaude:archiclaude@localhost:5432/archiclaude" alembic upgrade head
```

Expected: `Running upgrade 20260416_0001 -> 20260416_0002, feature_flags table`.

- [ ] **Step 8: Créer le schéma Pydantic**

`apps/backend/schemas/feature_flag.py` :
```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class FeatureFlagBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    key: str
    enabled_globally: bool
    enabled_for_user_ids: list[UUID]
    description: str | None = None


class FeatureFlagRead(FeatureFlagBase):
    updated_at: datetime


class FeatureFlagUpdate(BaseModel):
    enabled_globally: bool | None = None
    enabled_for_user_ids: list[UUID] | None = None
    description: str | None = None


class FeatureFlagCreate(FeatureFlagBase):
    pass
```

- [ ] **Step 9: Écrire les tests d'intégration des endpoints (vont échouer)**

`apps/backend/tests/integration/test_flags_endpoints.py` :
```python
import pytest
from httpx import AsyncClient
from sqlalchemy import text

from db.session import engine


@pytest.fixture(autouse=True)
async def _reset_flags() -> None:
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE feature_flags"))


@pytest.mark.asyncio
async def test_list_flags_empty_initially(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/admin/feature-flags")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_put_flag_creates_if_missing(client: AsyncClient) -> None:
    resp = await client.put(
        "/api/v1/admin/feature-flags/enable_oblique_gabarit",
        json={"enabled_globally": True, "description": "Calcul gabarit oblique précis"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == "enable_oblique_gabarit"
    assert body["enabled_globally"] is True
    assert body["enabled_for_user_ids"] == []
    assert body["description"] == "Calcul gabarit oblique précis"


@pytest.mark.asyncio
async def test_put_flag_updates_if_exists(client: AsyncClient) -> None:
    await client.put(
        "/api/v1/admin/feature-flags/use_paris_bioclim_parser",
        json={"enabled_globally": False},
    )
    resp = await client.put(
        "/api/v1/admin/feature-flags/use_paris_bioclim_parser",
        json={"enabled_globally": True},
    )
    assert resp.status_code == 200
    assert resp.json()["enabled_globally"] is True


@pytest.mark.asyncio
async def test_list_returns_created_flag(client: AsyncClient) -> None:
    await client.put(
        "/api/v1/admin/feature-flags/flag_a",
        json={"enabled_globally": True},
    )
    await client.put(
        "/api/v1/admin/feature-flags/flag_b",
        json={"enabled_globally": False},
    )
    resp = await client.get("/api/v1/admin/feature-flags")
    assert resp.status_code == 200
    keys = [f["key"] for f in resp.json()]
    assert set(keys) == {"flag_a", "flag_b"}
```

- [ ] **Step 10: Lancer les tests — doivent échouer (route absente)**

```bash
pytest tests/integration/test_flags_endpoints.py -v
```

Expected: 404 ou route absente.

- [ ] **Step 11: Implémenter la route admin flags**

`apps/backend/api/routes/admin/flags.py` :
```python
from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models.feature_flags import FeatureFlagRow
from db.session import SessionDep
from schemas.feature_flag import FeatureFlagRead, FeatureFlagUpdate

router = APIRouter(prefix="/admin/feature-flags", tags=["admin"])


@router.get("", response_model=list[FeatureFlagRead])
async def list_flags(session: SessionDep) -> list[FeatureFlagRow]:
    result = await session.execute(select(FeatureFlagRow).order_by(FeatureFlagRow.key))
    return list(result.scalars().all())


@router.put("/{key}", response_model=FeatureFlagRead)
async def upsert_flag(
    key: str,
    payload: FeatureFlagUpdate,
    session: SessionDep,
) -> FeatureFlagRow:
    values = {
        "key": key,
        "enabled_globally": payload.enabled_globally if payload.enabled_globally is not None else False,
        "enabled_for_user_ids": payload.enabled_for_user_ids or [],
        "description": payload.description,
    }
    update_cols = {k: v for k, v in values.items() if k != "key" and v is not None or k == "enabled_globally"}

    stmt = (
        pg_insert(FeatureFlagRow)
        .values(**values)
        .on_conflict_do_update(index_elements=["key"], set_=update_cols)
        .returning(FeatureFlagRow)
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.scalar_one()
```

- [ ] **Step 12: Enregistrer la route dans `api/main.py`**

Modifier `apps/backend/api/main.py` :
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.routes import health
from api.routes.admin import flags as admin_flags


def create_app() -> FastAPI:
    app = FastAPI(
        title="ArchiClaude API",
        version="0.1.0",
        description="API faisabilité architecturale IDF",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:3001", "http://127.0.0.1:3001"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(health.router, prefix="/api/v1")
    app.include_router(admin_flags.router, prefix="/api/v1")
    return app


app = create_app()
```

- [ ] **Step 13: Relancer les tests — doivent passer**

```bash
pytest tests/integration/test_flags_endpoints.py -v
```

Expected: `4 passed`.

- [ ] **Step 14: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/core/flags.py apps/backend/db/models/feature_flags.py apps/backend/schemas/feature_flag.py apps/backend/api/routes/admin apps/backend/api/main.py apps/backend/alembic/versions apps/backend/tests
git commit -m "feat(backend): feature flags table, module, and admin CRUD endpoints"
```

---

## Task 6: Backend — Middleware de telemetry coûts LLM (TDD)

**Files:**
- Create: `apps/backend/db/models/audit_logs.py` (full)
- Create: `apps/backend/alembic/versions/20260416_0003_audit_logs.py`
- Create: `apps/backend/api/middleware/cost_tracking.py`
- Create: `apps/backend/tests/unit/test_cost_tracking.py`

- [ ] **Step 1: Implémenter le modèle ORM `audit_logs`**

`apps/backend/db/models/audit_logs.py` :
```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import JSON, TIMESTAMP, BigInteger, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class AuditLogRow(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    entity_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
```

- [ ] **Step 2: Créer la table users minimale (requise par FK audit_logs.user_id)**

`apps/backend/db/models/users.py` (nouveau fichier) :
```python
from datetime import datetime
from uuid import UUID

from sqlalchemy import TIMESTAMP, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class UserRow(Base):
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid())
    email: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(Text, nullable=True)
    full_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(String, nullable=False, server_default="user")
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False, server_default=func.now()
    )
    last_login_at: Mapped[datetime | None] = mapped_column(TIMESTAMP(timezone=True), nullable=True)
```

- [ ] **Step 3: Générer la migration**

`apps/backend/alembic/versions/20260416_0003_audit_logs.py` :
```python
"""users and audit_logs tables

Revision ID: 20260416_0003
Revises: 20260416_0002
Create Date: 2026-04-16 00:02:00

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260416_0003"
down_revision: str | None = "20260416_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.String(), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=True),
        sa.Column("full_name", sa.Text(), nullable=True),
        sa.Column("role", sa.String(), nullable=False, server_default="user"),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_login_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=True),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("users")
```

- [ ] **Step 4: Appliquer la migration**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
source .venv/bin/activate
DATABASE_URL="postgresql://archiclaude:archiclaude@localhost:5432/archiclaude" alembic upgrade head
```

Expected: `Running upgrade 20260416_0002 -> 20260416_0003, users and audit_logs tables`.

- [ ] **Step 5: Mettre à jour `alembic/env.py` pour importer le nouveau modèle**

Modifier `apps/backend/alembic/env.py`, remplacer la ligne d'import des modèles par :
```python
from db.models import audit_logs, feature_flags, users  # noqa: F401
```

- [ ] **Step 6: Écrire le test du cost tracker (va échouer)**

`apps/backend/tests/unit/test_cost_tracking.py` :
```python
from decimal import Decimal

import pytest

from api.middleware.cost_tracking import (
    AnthropicUsage,
    compute_cost_cents,
    MODEL_PRICING,
)


def test_cost_for_sonnet_4_6_standard_call() -> None:
    usage = AnthropicUsage(
        model="claude-sonnet-4-6",
        input_tokens=10_000,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=1_500,
    )
    # Sonnet 4.6: $3/MTok input, $15/MTok output
    # input: 10_000 * 3 / 1_000_000 = 0.03 USD
    # output: 1_500 * 15 / 1_000_000 = 0.0225 USD
    # Total: 0.0525 USD = 5.25 cents (rounded to 4 decimals)
    cost = compute_cost_cents(usage)
    assert cost == Decimal("5.2500")


def test_cost_for_haiku_4_5() -> None:
    usage = AnthropicUsage(
        model="claude-haiku-4-5-20251001",
        input_tokens=10_000,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=1_500,
    )
    # Haiku 4.5: $1/MTok input, $5/MTok output
    # input: 10_000 * 1 / 1_000_000 = 0.01 USD
    # output: 1_500 * 5 / 1_000_000 = 0.0075 USD
    # Total: 0.0175 USD = 1.75 cents
    cost = compute_cost_cents(usage)
    assert cost == Decimal("1.7500")


def test_cost_with_cache_read_discount() -> None:
    usage = AnthropicUsage(
        model="claude-sonnet-4-6",
        input_tokens=0,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=100_000,
        output_tokens=500,
    )
    # Cache read Sonnet: $0.30/MTok (10% of input price)
    # cache read: 100_000 * 0.3 / 1_000_000 = 0.03 USD
    # output: 500 * 15 / 1_000_000 = 0.0075 USD
    # Total: 0.0375 USD = 3.75 cents
    cost = compute_cost_cents(usage)
    assert cost == Decimal("3.7500")


def test_cost_with_cache_creation_premium() -> None:
    usage = AnthropicUsage(
        model="claude-sonnet-4-6",
        input_tokens=0,
        cache_creation_input_tokens=50_000,
        cache_read_input_tokens=0,
        output_tokens=0,
    )
    # Cache creation Sonnet: $3.75/MTok (125% of input price)
    # 50_000 * 3.75 / 1_000_000 = 0.1875 USD = 18.75 cents
    cost = compute_cost_cents(usage)
    assert cost == Decimal("18.7500")


def test_unknown_model_raises() -> None:
    usage = AnthropicUsage(
        model="claude-mystery-v99",
        input_tokens=100,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
        output_tokens=50,
    )
    with pytest.raises(ValueError, match="Unknown Anthropic model"):
        compute_cost_cents(usage)


def test_model_pricing_has_required_keys() -> None:
    for model, pricing in MODEL_PRICING.items():
        assert "input_per_mtok_usd" in pricing, model
        assert "output_per_mtok_usd" in pricing, model
        assert "cache_read_per_mtok_usd" in pricing, model
        assert "cache_creation_per_mtok_usd" in pricing, model
```

- [ ] **Step 7: Lancer le test — doit échouer**

```bash
pytest tests/unit/test_cost_tracking.py -v
```

Expected: `ModuleNotFoundError: No module named 'api.middleware.cost_tracking'`.

- [ ] **Step 8: Implémenter le cost tracker**

`apps/backend/api/middleware/cost_tracking.py` :
```python
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

# Pricing source: Anthropic pricing page, snapshot 2026-04-16.
# Prices in USD per million tokens.
# Cache read: 10% of input price. Cache creation: 125% of input price (5min TTL).
MODEL_PRICING: dict[str, dict[str, Decimal]] = {
    "claude-opus-4-6": {
        "input_per_mtok_usd": Decimal("15"),
        "output_per_mtok_usd": Decimal("75"),
        "cache_read_per_mtok_usd": Decimal("1.50"),
        "cache_creation_per_mtok_usd": Decimal("18.75"),
    },
    "claude-sonnet-4-6": {
        "input_per_mtok_usd": Decimal("3"),
        "output_per_mtok_usd": Decimal("15"),
        "cache_read_per_mtok_usd": Decimal("0.30"),
        "cache_creation_per_mtok_usd": Decimal("3.75"),
    },
    "claude-haiku-4-5-20251001": {
        "input_per_mtok_usd": Decimal("1"),
        "output_per_mtok_usd": Decimal("5"),
        "cache_read_per_mtok_usd": Decimal("0.10"),
        "cache_creation_per_mtok_usd": Decimal("1.25"),
    },
}


@dataclass(frozen=True)
class AnthropicUsage:
    model: str
    input_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    output_tokens: int


def compute_cost_cents(usage: AnthropicUsage) -> Decimal:
    """Calcule le coût d'un appel Anthropic en centimes de dollar US (précision 4 décimales).

    Utilise `MODEL_PRICING` pour les tarifs. Lève ValueError si modèle inconnu.
    """
    pricing = MODEL_PRICING.get(usage.model)
    if pricing is None:
        raise ValueError(f"Unknown Anthropic model: {usage.model}")

    cost_usd = (
        Decimal(usage.input_tokens) * pricing["input_per_mtok_usd"] / Decimal(1_000_000)
        + Decimal(usage.cache_creation_input_tokens) * pricing["cache_creation_per_mtok_usd"] / Decimal(1_000_000)
        + Decimal(usage.cache_read_input_tokens) * pricing["cache_read_per_mtok_usd"] / Decimal(1_000_000)
        + Decimal(usage.output_tokens) * pricing["output_per_mtok_usd"] / Decimal(1_000_000)
    )
    cost_cents = cost_usd * Decimal(100)
    return cost_cents.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def extract_usage_from_anthropic_message(response: Any, model: str) -> AnthropicUsage:
    """Extrait AnthropicUsage depuis une réponse `anthropic` SDK (messages.create)."""
    u = response.usage
    return AnthropicUsage(
        model=model,
        input_tokens=int(u.input_tokens),
        cache_creation_input_tokens=int(getattr(u, "cache_creation_input_tokens", 0) or 0),
        cache_read_input_tokens=int(getattr(u, "cache_read_input_tokens", 0) or 0),
        output_tokens=int(u.output_tokens),
    )
```

- [ ] **Step 9: Relancer le test — doit passer**

```bash
pytest tests/unit/test_cost_tracking.py -v
```

Expected: `6 passed`.

- [ ] **Step 10: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/db/models/users.py apps/backend/db/models/audit_logs.py apps/backend/api/middleware/cost_tracking.py apps/backend/alembic apps/backend/tests
git commit -m "feat(backend): LLM cost tracking module + users and audit_logs tables"
```

---

## Task 7: Backend — ARQ worker skeleton

**Files:**
- Create: `apps/backend/workers/main.py`

- [ ] **Step 1: Créer le worker entry point**

`apps/backend/workers/main.py` :
```python
from __future__ import annotations

from arq.connections import RedisSettings
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    redis_url: str = "redis://localhost:6379/0"


_worker_settings = WorkerSettings()


async def noop_task(ctx: dict, message: str) -> str:
    """Tâche placeholder Phase 0. Remplacée par extraction/feasibility/pdf en phases suivantes."""
    return f"noop: {message}"


class Worker:
    """ARQ worker settings. Entry point: `arq workers.main.Worker`."""

    functions = [noop_task]
    redis_settings = RedisSettings.from_dsn(_worker_settings.redis_url)
    max_jobs = 10
    job_timeout = 600  # 10min max par tâche
    keep_result = 3600  # 1h TTL résultat
```

- [ ] **Step 2: Lancer Redis pour tester**

```bash
docker run --name archiclaude-redis-temp -d -p 6379:6379 redis:7-alpine
```

- [ ] **Step 3: Smoke test : worker démarre sans crash**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
source .venv/bin/activate
REDIS_URL="redis://localhost:6379/0" timeout 3 arq workers.main.Worker || true
```

Expected: messages de log ARQ indiquant connexion Redis OK, puis timeout. Pas d'exception non contrôlée.

- [ ] **Step 4: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/workers
git commit -m "feat(backend): ARQ worker skeleton with noop task"
```

---

## Task 8: Backend — Script génération types TS depuis Pydantic

**Files:**
- Create: `apps/backend/scripts/generate_ts_schemas.py`
- Create: `packages/shared-types/package.json`
- Create: `packages/shared-types/tsconfig.json`
- Create: `packages/shared-types/src/index.ts`
- Create: `packages/shared-types/src/generated/.gitkeep`
- Create: `apps/frontend/src/types/generated/.gitkeep`

- [ ] **Step 1: Installer datamodel-code-generator dans les deps dev backend**

Modifier `apps/backend/pyproject.toml`, ajouter à `[project.optional-dependencies].dev` :
```toml
"datamodel-code-generator==0.26.3",
```

Puis :
```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
source .venv/bin/activate
pip install -e ".[dev]"
```

- [ ] **Step 2: Créer `packages/shared-types/package.json`**

```json
{
  "name": "@archiclaude/shared-types",
  "version": "0.1.0",
  "private": true,
  "main": "./src/index.ts",
  "types": "./src/index.ts",
  "scripts": {
    "typecheck": "tsc --noEmit",
    "generate": "node scripts/generate.mjs"
  },
  "devDependencies": {
    "typescript": "^5.6.3"
  },
  "dependencies": {
    "zod": "^3.23.8"
  }
}
```

- [ ] **Step 3: Créer `packages/shared-types/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "ESNext",
    "moduleResolution": "bundler",
    "esModuleInterop": true,
    "forceConsistentCasingInFileNames": true,
    "strict": true,
    "skipLibCheck": true,
    "declaration": true,
    "allowImportingTsExtensions": false,
    "resolveJsonModule": true,
    "noEmit": true
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 4: Créer `packages/shared-types/src/index.ts`**

```typescript
// Re-export générés depuis les schémas Pydantic backend.
// Toute modif manuelle sera écrasée par `pnpm --filter @archiclaude/shared-types generate`.
export * from "./generated/schemas";
```

- [ ] **Step 5: Créer `packages/shared-types/src/generated/.gitkeep`**

Fichier vide pour maintenir le dossier en git (contenu sera généré).

```bash
mkdir -p /Users/anthonymammone/Desktop/ArchiClaude/packages/shared-types/src/generated
touch /Users/anthonymammone/Desktop/ArchiClaude/packages/shared-types/src/generated/.gitkeep
```

- [ ] **Step 6: Créer `apps/backend/scripts/generate_ts_schemas.py`**

```python
"""Génération des schémas TypeScript (zod) depuis les modèles Pydantic.

Stratégie Phase 0 : on exporte d'abord en JSON Schema, puis on utilise un post-processing
minimal pour produire un fichier TypeScript avec types + zod schemas. En Phase 1+, on
passera à un outil plus complet (`pydantic-to-zod` ou équivalent) si le volume le justifie.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from pydantic import BaseModel

# Ajoute le répertoire backend au path pour les imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from schemas.feature_flag import FeatureFlagCreate, FeatureFlagRead, FeatureFlagUpdate

OUTPUT_DIR = Path(__file__).parent.parent.parent.parent / "packages" / "shared-types" / "src" / "generated"
OUTPUT_FILE = OUTPUT_DIR / "schemas.ts"

EXPORTED_MODELS: list[type[BaseModel]] = [
    FeatureFlagCreate,
    FeatureFlagRead,
    FeatureFlagUpdate,
]


def pydantic_to_ts_type(schema: dict) -> str:
    """Conversion minimale JSON Schema → TypeScript interface."""
    lines = [f"export interface {schema['title']} {{"]
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))
    for name, prop in properties.items():
        ts_type = _jsonschema_to_ts(prop)
        optional_marker = "" if name in required else "?"
        lines.append(f"  {name}{optional_marker}: {ts_type};")
    lines.append("}")
    return "\n".join(lines)


def _jsonschema_to_ts(prop: dict) -> str:
    t = prop.get("type")
    if t == "string":
        if prop.get("format") == "uuid":
            return "string"
        if prop.get("format") == "date-time":
            return "string"
        return "string"
    if t == "integer" or t == "number":
        return "number"
    if t == "boolean":
        return "boolean"
    if t == "array":
        items = prop.get("items", {})
        return f"{_jsonschema_to_ts(items)}[]"
    if t == "null":
        return "null"
    if "anyOf" in prop:
        return " | ".join(_jsonschema_to_ts(opt) for opt in prop["anyOf"])
    if "$ref" in prop:
        return prop["$ref"].split("/")[-1]
    return "unknown"


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    parts = [
        "// AUTO-GENERATED by apps/backend/scripts/generate_ts_schemas.py",
        "// DO NOT EDIT — regenerate with `pnpm --filter @archiclaude/backend generate-types`",
        "",
    ]
    for model in EXPORTED_MODELS:
        schema = model.model_json_schema()
        parts.append(pydantic_to_ts_type(schema))
        parts.append("")

    OUTPUT_FILE.write_text("\n".join(parts))
    print(f"Wrote {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Ajouter un script d'export dans le pyproject.toml backend**

Modifier `apps/backend/pyproject.toml`, ajouter sous `[project]` :
```toml
[project.scripts]
generate-ts-schemas = "scripts.generate_ts_schemas:main"
```

Et ajouter dans `package.json` racine un script de convenance :
```json
"generate:types": "cd apps/backend && source .venv/bin/activate && python scripts/generate_ts_schemas.py"
```

- [ ] **Step 8: Lancer la génération**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
source .venv/bin/activate
python scripts/generate_ts_schemas.py
```

Expected: `Wrote .../packages/shared-types/src/generated/schemas.ts`.

Vérifier le contenu :
```bash
cat /Users/anthonymammone/Desktop/ArchiClaude/packages/shared-types/src/generated/schemas.ts
```

Doit contenir les interfaces `FeatureFlagCreate`, `FeatureFlagRead`, `FeatureFlagUpdate`.

- [ ] **Step 9: Créer `apps/frontend/src/types/generated/.gitkeep`**

```bash
mkdir -p /Users/anthonymammone/Desktop/ArchiClaude/apps/frontend/src/types/generated
touch /Users/anthonymammone/Desktop/ArchiClaude/apps/frontend/src/types/generated/.gitkeep
```

- [ ] **Step 10: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add packages/shared-types apps/backend/scripts apps/backend/pyproject.toml package.json apps/frontend/src/types
git commit -m "feat: Pydantic to TS schema generation pipeline"
```

---

## Task 9: Frontend — Scaffold Next.js 16 + Tailwind v4 + shadcn/ui

**Files:**
- Create: `apps/frontend/package.json`
- Create: `apps/frontend/tsconfig.json`
- Create: `apps/frontend/next.config.ts`
- Create: `apps/frontend/tailwind.config.ts`
- Create: `apps/frontend/postcss.config.mjs`
- Create: `apps/frontend/components.json`
- Create: `apps/frontend/src/app/layout.tsx`
- Create: `apps/frontend/src/app/page.tsx`
- Create: `apps/frontend/src/app/globals.css`
- Create: `apps/frontend/.env.example`
- Create: `apps/frontend/.gitignore`
- Create: `apps/frontend/.dockerignore`
- Create: `apps/frontend/src/lib/utils.ts`
- Create: `apps/frontend/src/lib/api.ts`

- [ ] **Step 1: Créer `apps/frontend/package.json`**

```json
{
  "name": "@archiclaude/frontend",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev -p 3001 --turbopack",
    "build": "next build",
    "start": "next start -p 3001",
    "lint": "eslint . --ext ts,tsx",
    "typecheck": "tsc --noEmit",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "@archiclaude/shared-types": "workspace:*",
    "@radix-ui/react-dialog": "^1.1.2",
    "@radix-ui/react-label": "^2.1.0",
    "@radix-ui/react-slot": "^1.1.0",
    "@radix-ui/react-switch": "^1.1.1",
    "@radix-ui/react-toast": "^1.2.2",
    "class-variance-authority": "^0.7.0",
    "clsx": "^2.1.1",
    "lucide-react": "^0.454.0",
    "next": "^16.2.0",
    "react": "^19.2.4",
    "react-dom": "^19.2.4",
    "tailwind-merge": "^2.5.4",
    "zod": "^3.23.8"
  },
  "devDependencies": {
    "@tailwindcss/postcss": "^4.0.0",
    "@types/node": "^20.17.6",
    "@types/react": "^19.0.1",
    "@types/react-dom": "^19.0.0",
    "@vitejs/plugin-react": "^4.3.3",
    "eslint": "^9.14.0",
    "eslint-config-next": "^16.2.0",
    "tailwindcss": "^4.0.0",
    "typescript": "^5.6.3",
    "vitest": "^2.1.5"
  }
}
```

- [ ] **Step 2: Créer `apps/frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "ES2022"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": {
      "@/*": ["./src/*"]
    }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 3: Créer `apps/frontend/next.config.ts`**

```typescript
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  transpilePackages: ["@archiclaude/shared-types"],
  experimental: {
    reactCompiler: false,
  },
};

export default nextConfig;
```

- [ ] **Step 4: Créer `apps/frontend/tailwind.config.ts`**

```typescript
import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        serif: ["Playfair Display", "serif"],
      },
      colors: {
        // Palette brand ArchiClaude (cohérence avec rapport)
        brand: {
          50: "#f0fafa",
          500: "#0d7678",
          700: "#0a4d4f",
          900: "#052627",
        },
      },
    },
  },
  plugins: [],
};

export default config;
```

- [ ] **Step 5: Créer `apps/frontend/postcss.config.mjs`**

```javascript
export default {
  plugins: {
    "@tailwindcss/postcss": {},
  },
};
```

- [ ] **Step 6: Créer `apps/frontend/components.json` (shadcn config)**

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "rsc": true,
  "tsx": true,
  "tailwind": {
    "config": "tailwind.config.ts",
    "css": "src/app/globals.css",
    "baseColor": "slate",
    "cssVariables": true,
    "prefix": ""
  },
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  },
  "iconLibrary": "lucide"
}
```

- [ ] **Step 7: Créer `apps/frontend/src/app/globals.css`**

```css
@import "tailwindcss";

:root {
  --background: 0 0% 100%;
  --foreground: 222.2 84% 4.9%;
  --card: 0 0% 100%;
  --card-foreground: 222.2 84% 4.9%;
  --primary: 180 85% 26%;
  --primary-foreground: 210 40% 98%;
  --muted: 210 40% 96.1%;
  --muted-foreground: 215.4 16.3% 46.9%;
  --border: 214.3 31.8% 91.4%;
  --ring: 180 85% 26%;
  --radius: 0.5rem;
}

body {
  @apply bg-[hsl(var(--background))] text-[hsl(var(--foreground))] font-sans;
}
```

- [ ] **Step 8: Créer `apps/frontend/src/app/layout.tsx`**

```tsx
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ArchiClaude",
  description: "Faisabilité architecturale et dossier PC pour promoteurs IDF",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="fr">
      <body>{children}</body>
    </html>
  );
}
```

- [ ] **Step 9: Créer `apps/frontend/src/app/page.tsx`**

```tsx
export default function HomePage() {
  return (
    <main className="min-h-screen flex items-center justify-center p-8">
      <div className="max-w-2xl text-center space-y-4">
        <h1 className="font-serif text-5xl">ArchiClaude</h1>
        <p className="text-lg text-slate-600">
          Faisabilité architecturale et dossier PC pour promoteurs en Île-de-France.
        </p>
        <p className="text-sm text-slate-500">
          Phase 0 — setup infrastructure. Prochain jalon : sélection de parcelles sur carte.
        </p>
      </div>
    </main>
  );
}
```

- [ ] **Step 10: Créer `apps/frontend/src/lib/utils.ts`**

```typescript
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 11: Créer `apps/frontend/src/lib/api.ts`**

```typescript
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly body: unknown,
  ) {
    super(`API error ${status}`);
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}/api/v1${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body);
  }
  return res.json() as Promise<T>;
}
```

- [ ] **Step 12: Créer `apps/frontend/.env.example`**

```bash
NEXT_PUBLIC_API_URL=http://localhost:8000
NEXTAUTH_URL=http://localhost:3001
NEXTAUTH_SECRET=change-me-32-chars-minimum
```

- [ ] **Step 13: Créer `apps/frontend/.gitignore` et `.dockerignore`**

`apps/frontend/.gitignore` :
```
node_modules/
.next/
out/
.env.local
.env.*.local
*.tsbuildinfo
next-env.d.ts
```

`apps/frontend/.dockerignore` :
```
node_modules
.next
.git
*.log
.env*
!.env.example
```

- [ ] **Step 14: Installer les deps frontend**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
pnpm install
```

Expected: installation réussie, `apps/frontend/node_modules` et `packages/shared-types/node_modules` créés.

- [ ] **Step 15: Lancer le dev server frontend et vérifier la page**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/frontend
pnpm dev
```

Dans un autre terminal :
```bash
curl -s http://localhost:3001 | head -20
```

Expected: HTML contenant "ArchiClaude" et "Phase 0 — setup infrastructure".

Ctrl+C pour arrêter.

- [ ] **Step 16: Vérifier le typecheck**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/frontend
pnpm typecheck
```

Expected: pas d'erreur.

- [ ] **Step 17: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/frontend packages/shared-types pnpm-lock.yaml
git commit -m "feat(frontend): scaffold Next.js 16 + Tailwind v4 + shadcn config"
```

---

## Task 10: Frontend — Page admin flags table

**Files:**
- Create: `apps/frontend/src/app/admin/flags/page.tsx`
- Create: `apps/frontend/src/components/admin/FlagsTable.tsx`
- Create: `apps/frontend/src/app/admin/layout.tsx`

- [ ] **Step 1: Créer le layout admin**

`apps/frontend/src/app/admin/layout.tsx` :
```tsx
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen p-8">
      <header className="mb-8 pb-4 border-b">
        <h1 className="font-serif text-3xl">ArchiClaude — Admin</h1>
        <nav className="mt-2 flex gap-4 text-sm text-slate-600">
          <a href="/admin/flags" className="hover:underline">
            Feature flags
          </a>
        </nav>
      </header>
      {children}
    </div>
  );
}
```

- [ ] **Step 2: Créer le composant FlagsTable**

`apps/frontend/src/components/admin/FlagsTable.tsx` :
```tsx
"use client";

import { useEffect, useState } from "react";
import type { FeatureFlagRead } from "@archiclaude/shared-types";

import { ApiError, apiFetch } from "@/lib/api";

export function FlagsTable() {
  const [flags, setFlags] = useState<FeatureFlagRead[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<FeatureFlagRead[]>("/admin/feature-flags")
      .then(setFlags)
      .catch((e: ApiError) => setError(`Erreur ${e.status}: ${JSON.stringify(e.body)}`));
  }, []);

  async function toggle(key: string, currentValue: boolean) {
    try {
      const updated = await apiFetch<FeatureFlagRead>(`/admin/feature-flags/${key}`, {
        method: "PUT",
        body: JSON.stringify({ enabled_globally: !currentValue }),
      });
      setFlags((prev) => (prev ? prev.map((f) => (f.key === key ? updated : f)) : prev));
    } catch (e) {
      setError(e instanceof ApiError ? `Erreur ${e.status}` : "Erreur inconnue");
    }
  }

  if (error) return <p className="text-red-600">{error}</p>;
  if (flags === null) return <p className="text-slate-500">Chargement…</p>;
  if (flags.length === 0) return <p className="text-slate-500">Aucun flag défini.</p>;

  return (
    <table className="w-full text-left">
      <thead className="border-b text-sm text-slate-500">
        <tr>
          <th className="py-2">Clé</th>
          <th>Global</th>
          <th>Users override</th>
          <th>Description</th>
          <th>Actions</th>
        </tr>
      </thead>
      <tbody>
        {flags.map((f) => (
          <tr key={f.key} className="border-b">
            <td className="py-2 font-mono text-sm">{f.key}</td>
            <td>{f.enabled_globally ? "✓" : "—"}</td>
            <td className="text-sm text-slate-500">{f.enabled_for_user_ids.length}</td>
            <td className="text-sm">{f.description ?? ""}</td>
            <td>
              <button
                type="button"
                className="rounded bg-slate-200 px-3 py-1 text-sm hover:bg-slate-300"
                onClick={() => toggle(f.key, f.enabled_globally)}
              >
                Toggle global
              </button>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
```

- [ ] **Step 3: Créer la page `/admin/flags`**

`apps/frontend/src/app/admin/flags/page.tsx` :
```tsx
import { FlagsTable } from "@/components/admin/FlagsTable";

export default function AdminFlagsPage() {
  return (
    <section>
      <h2 className="text-xl mb-4">Feature flags</h2>
      <FlagsTable />
    </section>
  );
}
```

- [ ] **Step 4: Smoke test manuel**

Démarrer le backend :
```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
source .venv/bin/activate
DATABASE_URL="postgresql+asyncpg://archiclaude:archiclaude@localhost:5432/archiclaude" uvicorn api.main:app --port 8000 --reload
```

Créer 2 flags via curl :
```bash
curl -X PUT http://localhost:8000/api/v1/admin/feature-flags/use_paris_bioclim_parser \
  -H "Content-Type: application/json" \
  -d '{"enabled_globally": true, "description": "Parser dédié Paris bioclimatique"}'
curl -X PUT http://localhost:8000/api/v1/admin/feature-flags/enable_oblique_gabarit \
  -H "Content-Type: application/json" \
  -d '{"enabled_globally": false, "description": "Calcul oblique précis"}'
```

Démarrer le frontend :
```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/frontend
pnpm dev
```

Ouvrir http://localhost:3001/admin/flags — doit afficher les 2 flags dans un tableau, avec boutons Toggle fonctionnels.

- [ ] **Step 5: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/frontend/src/app/admin apps/frontend/src/components/admin
git commit -m "feat(frontend): admin flags table page with backend integration"
```

---

## Task 11: Docker Compose dev stack

**Files:**
- Create: `docker-compose.yml`
- Create: `apps/backend/Dockerfile.dev`
- Create: `apps/frontend/Dockerfile.dev`
- Create: `docker/postgres/Dockerfile` (image custom postgis+pgvector)

- [ ] **Step 1: Créer `apps/backend/Dockerfile.dev`**

```dockerfile
FROM python:3.12-slim

# Système : dépendances WeasyPrint + asyncpg
RUN apt-get update && apt-get install -y \
    build-essential \
    libcairo2 \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    libproj-dev \
    proj-data \
    libgeos-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install -e ".[dev]"

COPY . .

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

- [ ] **Step 2: Créer `apps/frontend/Dockerfile.dev`**

```dockerfile
FROM node:20-alpine

WORKDIR /app

RUN corepack enable && corepack prepare pnpm@9.12.3 --activate

# Copier les manifests (mieux exploiter le cache Docker)
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/frontend/package.json ./apps/frontend/
COPY packages/shared-types/package.json ./packages/shared-types/

RUN pnpm install --frozen-lockfile

# Copier le reste
COPY . .

EXPOSE 3001

CMD ["pnpm", "--filter", "@archiclaude/frontend", "dev"]
```

- [ ] **Step 3: Créer `docker/postgres/Dockerfile` — image custom Postgres+PostGIS+pgvector**

```bash
mkdir -p /Users/anthonymammone/Desktop/ArchiClaude/docker/postgres
```

`docker/postgres/Dockerfile` :
```dockerfile
FROM postgis/postgis:16-3.4

# Installe pgvector depuis les paquets Debian officiels (compatible PG16)
USER root
RUN apt-get update && \
    apt-get install -y --no-install-recommends postgresql-16-pgvector && \
    rm -rf /var/lib/apt/lists/*
USER postgres
```

- [ ] **Step 4: Créer `docker-compose.yml` racine**

```yaml
name: archiclaude

services:
  postgres:
    build:
      context: ./docker/postgres
    container_name: archiclaude-postgres
    environment:
      POSTGRES_USER: archiclaude
      POSTGRES_PASSWORD: archiclaude
      POSTGRES_DB: archiclaude
    ports:
      - "5432:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U archiclaude"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    container_name: archiclaude-redis
    ports:
      - "6379:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  backend:
    build:
      context: ./apps/backend
      dockerfile: Dockerfile.dev
    container_name: archiclaude-backend
    environment:
      DATABASE_URL: postgresql+asyncpg://archiclaude:archiclaude@postgres:5432/archiclaude
      REDIS_URL: redis://redis:6379/0
    ports:
      - "8000:8000"
    volumes:
      - ./apps/backend:/app
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    profiles: ["full"]

  worker:
    build:
      context: ./apps/backend
      dockerfile: Dockerfile.dev
    container_name: archiclaude-worker
    environment:
      DATABASE_URL: postgresql+asyncpg://archiclaude:archiclaude@postgres:5432/archiclaude
      REDIS_URL: redis://redis:6379/0
    command: ["arq", "workers.main.Worker"]
    volumes:
      - ./apps/backend:/app
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    profiles: ["full"]

  frontend:
    build:
      context: .
      dockerfile: apps/frontend/Dockerfile.dev
    container_name: archiclaude-frontend
    environment:
      NEXT_PUBLIC_API_URL: http://localhost:8000
    ports:
      - "3001:3001"
    depends_on:
      - backend
    profiles: ["full"]

volumes:
  postgres_data:
```

- [ ] **Step 5: Arrêter les containers temporaires (Task 4/7)**

```bash
docker stop archiclaude-pg-temp archiclaude-redis-temp 2>/dev/null
docker rm archiclaude-pg-temp archiclaude-redis-temp 2>/dev/null
```

- [ ] **Step 6: Build l'image Postgres custom et démarrer postgres + redis**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
docker compose build postgres
docker compose up -d postgres redis
```

Attendre healthchecks :
```bash
docker compose ps
```

Expected: postgres et redis en `healthy`.

- [ ] **Step 7: Re-appliquer migrations (sur la nouvelle DB vierge)**

```bash
cd apps/backend
source .venv/bin/activate
DATABASE_URL="postgresql://archiclaude:archiclaude@localhost:5432/archiclaude" alembic upgrade head
```

Expected: migrations 0001, 0002, 0003 appliquées sans erreur. Vérifier que pgvector est bien présent :
```bash
docker exec archiclaude-postgres psql -U archiclaude -d archiclaude -c "SELECT extname FROM pg_extension WHERE extname IN ('postgis','vector','pgcrypto','pg_trgm');"
```

Expected: 4 lignes retournées.

- [ ] **Step 8: Smoke test : compose full**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
docker compose --profile full up -d
```

Attendre 30s puis :
```bash
curl http://localhost:8000/api/v1/health
curl http://localhost:3001
```

Les deux doivent répondre 200. Ensuite arrêter le profil full :
```bash
docker compose --profile full down
```

- [ ] **Step 9: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add docker-compose.yml apps/backend/Dockerfile.dev apps/frontend/Dockerfile.dev docker/postgres/Dockerfile
git commit -m "feat: Docker Compose dev stack with custom Postgres+PostGIS+pgvector image"
```

---

## Task 12: VSCode launch configs (.vscode/launch.json + tasks.json + settings.json)

**Files:**
- Create: `.vscode/launch.json`
- Create: `.vscode/tasks.json`
- Create: `.vscode/settings.json`
- Create: `.vscode/extensions.json`

- [ ] **Step 1: Créer `.vscode/launch.json`**

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "🚀 Backend (FastAPI)",
      "type": "debugpy",
      "request": "launch",
      "module": "uvicorn",
      "args": ["api.main:app", "--reload", "--port", "8000"],
      "cwd": "${workspaceFolder}/apps/backend",
      "python": "${workspaceFolder}/apps/backend/.venv/bin/python",
      "envFile": "${workspaceFolder}/.env",
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://archiclaude:archiclaude@localhost:5432/archiclaude",
        "REDIS_URL": "redis://localhost:6379/0",
        "PYTHONPATH": "${workspaceFolder}/apps/backend"
      },
      "justMyCode": false
    },
    {
      "name": "⚙️ Worker (ARQ)",
      "type": "debugpy",
      "request": "launch",
      "module": "arq",
      "args": ["workers.main.Worker"],
      "cwd": "${workspaceFolder}/apps/backend",
      "python": "${workspaceFolder}/apps/backend/.venv/bin/python",
      "envFile": "${workspaceFolder}/.env",
      "env": {
        "DATABASE_URL": "postgresql+asyncpg://archiclaude:archiclaude@localhost:5432/archiclaude",
        "REDIS_URL": "redis://localhost:6379/0",
        "PYTHONPATH": "${workspaceFolder}/apps/backend"
      },
      "justMyCode": false
    },
    {
      "name": "🌐 Frontend (Next.js)",
      "type": "node",
      "request": "launch",
      "runtimeExecutable": "pnpm",
      "runtimeArgs": ["--filter", "@archiclaude/frontend", "dev"],
      "cwd": "${workspaceFolder}",
      "console": "integratedTerminal",
      "skipFiles": ["<node_internals>/**"]
    },
    {
      "name": "🧪 Tests Backend (pytest current file)",
      "type": "debugpy",
      "request": "launch",
      "module": "pytest",
      "args": ["${file}", "-v"],
      "cwd": "${workspaceFolder}/apps/backend",
      "python": "${workspaceFolder}/apps/backend/.venv/bin/python",
      "env": {
        "PYTHONPATH": "${workspaceFolder}/apps/backend"
      },
      "justMyCode": false
    }
  ],
  "compounds": [
    {
      "name": "🧱 Full Stack (Backend + Worker + Frontend)",
      "configurations": ["🚀 Backend (FastAPI)", "⚙️ Worker (ARQ)", "🌐 Frontend (Next.js)"],
      "stopAll": true,
      "presentation": {
        "hidden": false,
        "order": 1
      }
    }
  ]
}
```

- [ ] **Step 2: Créer `.vscode/tasks.json`**

```json
{
  "version": "2.0.0",
  "tasks": [
    {
      "label": "🐳 docker: up (postgres+redis)",
      "type": "shell",
      "command": "docker compose up -d postgres redis",
      "problemMatcher": [],
      "presentation": { "reveal": "silent", "panel": "shared" }
    },
    {
      "label": "🐳 docker: down",
      "type": "shell",
      "command": "docker compose down",
      "problemMatcher": [],
      "presentation": { "reveal": "silent", "panel": "shared" }
    },
    {
      "label": "🐳 docker: up full (all services)",
      "type": "shell",
      "command": "docker compose --profile full up -d",
      "problemMatcher": [],
      "presentation": { "reveal": "always", "panel": "shared" }
    },
    {
      "label": "🔄 alembic: upgrade head",
      "type": "shell",
      "command": "source .venv/bin/activate && DATABASE_URL='postgresql://archiclaude:archiclaude@localhost:5432/archiclaude' alembic upgrade head",
      "options": {
        "cwd": "${workspaceFolder}/apps/backend",
        "shell": { "executable": "/bin/bash", "args": ["-c"] }
      },
      "problemMatcher": []
    },
    {
      "label": "🧪 pytest (all backend)",
      "type": "shell",
      "command": "source .venv/bin/activate && pytest -v",
      "options": {
        "cwd": "${workspaceFolder}/apps/backend",
        "shell": { "executable": "/bin/bash", "args": ["-c"] }
      },
      "group": { "kind": "test", "isDefault": true },
      "problemMatcher": []
    },
    {
      "label": "🎨 format: ruff + prettier",
      "type": "shell",
      "command": "cd apps/backend && source .venv/bin/activate && ruff format . && ruff check --fix . && cd ../.. && pnpm format",
      "options": { "shell": { "executable": "/bin/bash", "args": ["-c"] } },
      "problemMatcher": []
    },
    {
      "label": "🔧 generate types (Pydantic → TS)",
      "type": "shell",
      "command": "cd apps/backend && source .venv/bin/activate && python scripts/generate_ts_schemas.py",
      "options": { "shell": { "executable": "/bin/bash", "args": ["-c"] } },
      "problemMatcher": []
    }
  ]
}
```

- [ ] **Step 3: Créer `.vscode/settings.json`**

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/apps/backend/.venv/bin/python",
  "python.analysis.extraPaths": ["${workspaceFolder}/apps/backend"],
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": ["apps/backend/tests"],
  "python.testing.unittestEnabled": false,
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll.ruff": "explicit",
      "source.organizeImports.ruff": "explicit"
    }
  },
  "[typescript]": {
    "editor.defaultFormatter": "esbenp.prettier-vscode",
    "editor.formatOnSave": true
  },
  "[typescriptreact]": {
    "editor.defaultFormatter": "esbenp.prettier-vscode",
    "editor.formatOnSave": true
  },
  "typescript.tsdk": "node_modules/typescript/lib",
  "eslint.workingDirectories": [{ "pattern": "apps/frontend" }]
}
```

- [ ] **Step 4: Créer `.vscode/extensions.json`**

```json
{
  "recommendations": [
    "ms-python.python",
    "ms-python.debugpy",
    "charliermarsh.ruff",
    "ms-python.mypy-type-checker",
    "dbaeumer.vscode-eslint",
    "esbenp.prettier-vscode",
    "bradlc.vscode-tailwindcss",
    "ms-azuretools.vscode-docker",
    "tamasfe.even-better-toml",
    "redhat.vscode-yaml"
  ]
}
```

- [ ] **Step 5: Smoke test : ouvrir "Run and Debug" dans VSCode**

Dans VSCode, ouvrir le sidebar "Run and Debug" (Cmd+Shift+D). Vérifier que les 4 configurations individuelles + le compound "🧱 Full Stack" apparaissent dans le dropdown.

Lancer "🚀 Backend (FastAPI)" → attendre "Uvicorn running on http://0.0.0.0:8000". Puis Stop.

Lancer "🌐 Frontend (Next.js)" → attendre "Ready in X seconds". Puis Stop.

Lancer "🧱 Full Stack" → les 3 services démarrent en parallèle.

- [ ] **Step 6: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add .vscode
git commit -m "feat: VSCode launch configs with compound Full Stack target + tasks"
```

---

## Task 13: GitHub Actions CI (lint + typecheck + tests)

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Créer `.github/workflows/ci.yml`**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: true

jobs:
  backend:
    name: Backend (Python)
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgis/postgis:16-3.4
        env:
          POSTGRES_USER: archiclaude
          POSTGRES_PASSWORD: archiclaude
          POSTGRES_DB: archiclaude
        ports:
          - 5432:5432
        options: >-
          --health-cmd="pg_isready -U archiclaude"
          --health-interval=5s
          --health-timeout=3s
          --health-retries=10
      redis:
        image: redis:7-alpine
        ports:
          - 6379:6379
        options: >-
          --health-cmd="redis-cli ping"
          --health-interval=5s
          --health-timeout=3s
          --health-retries=10

    defaults:
      run:
        working-directory: apps/backend

    steps:
      - uses: actions/checkout@v4

      - name: Setup Python 3.12
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"
          cache: pip

      - name: Install system deps for WeasyPrint + GEOS
        run: |
          sudo apt-get update
          sudo apt-get install -y libcairo2 libpango-1.0-0 libpangoft2-1.0-0 libgdk-pixbuf-2.0-0 libgeos-dev libproj-dev proj-data postgresql-16-pgvector

      - name: Enable pgvector in Postgres
        run: |
          PGPASSWORD=archiclaude psql -h localhost -U archiclaude -d archiclaude -c "CREATE EXTENSION IF NOT EXISTS vector;"

      - name: Install Python deps
        run: |
          pip install --upgrade pip
          pip install -e ".[dev]"

      - name: Ruff lint
        run: ruff check .

      - name: Ruff format check
        run: ruff format --check .

      - name: Mypy
        run: mypy .

      - name: Alembic upgrade
        env:
          DATABASE_URL: postgresql://archiclaude:archiclaude@localhost:5432/archiclaude
        run: alembic upgrade head

      - name: Pytest
        env:
          DATABASE_URL: postgresql+asyncpg://archiclaude:archiclaude@localhost:5432/archiclaude
          REDIS_URL: redis://localhost:6379/0
        run: pytest -v

  frontend:
    name: Frontend (Next.js)
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Node 20
        uses: actions/setup-node@v4
        with:
          node-version: "20"

      - name: Setup pnpm
        uses: pnpm/action-setup@v4
        with:
          version: 9.12.3

      - name: Install deps
        run: pnpm install --frozen-lockfile

      - name: Lint (eslint)
        run: pnpm --filter @archiclaude/frontend lint

      - name: Typecheck
        run: pnpm --filter @archiclaude/frontend typecheck

      - name: Build
        run: pnpm --filter @archiclaude/frontend build
```

- [ ] **Step 2: Vérifier localement que `ruff check` et `ruff format --check` passent**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
source .venv/bin/activate
ruff check .
ruff format --check .
```

Si erreurs, corriger puis :
```bash
ruff format .
ruff check --fix .
```

- [ ] **Step 3: Vérifier localement que `mypy` passe**

```bash
mypy .
```

Corriger les erreurs strict types si nécessaire (en ajoutant annotations manquantes).

- [ ] **Step 4: Vérifier localement que `pytest -v` passe**

```bash
DATABASE_URL="postgresql+asyncpg://archiclaude:archiclaude@localhost:5432/archiclaude" pytest -v
```

Expected: tous tests passent.

- [ ] **Step 5: Vérifier localement que le build frontend passe**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
pnpm --filter @archiclaude/frontend typecheck
pnpm --filter @archiclaude/frontend build
```

Expected: build réussit sans erreur.

- [ ] **Step 6: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add .github
git commit -m "feat(ci): GitHub Actions workflow with backend + frontend jobs"
```

---

## Task 14: Fixtures de référence — dataset YAML partagé

**Files:**
- Create: `apps/backend/tests/fixtures/parcelles_reference.yaml`
- Create: `apps/backend/tests/fixtures/__init__.py`
- Create: `apps/backend/tests/fixtures/loader.py`
- Create: `apps/backend/tests/unit/test_fixtures_loader.py`

- [ ] **Step 1: Créer le fichier YAML squelette**

`apps/backend/tests/fixtures/parcelles_reference.yaml` :
```yaml
# Dataset de référence ArchiClaude — parcelles aux valeurs attendues pré-validées.
# Chaque entrée DOIT avoir été vérifiée manuellement contre le PLU officiel et les
# annexes mairie. Les valeurs chiffrées servent aux tests de régression (écart ≤ 1%).
#
# Les entrées sont remplies progressivement au fil des phases :
#   - Phase 1 (données) : champ `parcelle` et `zone_gpu`
#   - Phase 3 (extraction règles) : champ `parsed_rules_expected` et `numeric_rules_expected`
#   - Phase 4 (faisabilité) : champ `capacity_expected`
#   - Phase 5 (compliance) : champ `compliance_expected`

parcelles:
  - id: paris_8e_ug_reference
    address: "8 Rue de la Paix, 75002 Paris"
    insee: "75102"
    section: "AB"
    numero: "0001"
    zone_plu_code: "UG"
    # TODO Phase 1 : compléter la géométrie récupérée via cadastre
    # TODO Phase 3 : compléter les parsed_rules_expected
    # TODO Phase 4 : compléter capacity_expected

  - id: nogent_sur_marne_ub_reference
    address: "Exemple à préciser"
    insee: "94052"
    section: "A"
    numero: "0001"
    zone_plu_code: "UB"
    # TODO Phase 1 : compléter

  - id: saint_denis_um_reference
    address: "Exemple à préciser"
    insee: "93066"
    section: "A"
    numero: "0001"
    zone_plu_code: "UM"
    # TODO Phase 1 : compléter

  - id: versailles_ua_reference
    address: "Exemple à préciser"
    insee: "78646"
    section: "A"
    numero: "0001"
    zone_plu_code: "UA"
    # TODO Phase 1 : compléter

  - id: meaux_uc_reference
    address: "Exemple à préciser"
    insee: "77284"
    section: "A"
    numero: "0001"
    zone_plu_code: "UC"
    # TODO Phase 1 : compléter
```

- [ ] **Step 2: Créer `tests/fixtures/__init__.py`** (vide)

```bash
touch /Users/anthonymammone/Desktop/ArchiClaude/apps/backend/tests/fixtures/__init__.py
```

- [ ] **Step 3: Écrire le test du loader (va échouer)**

`apps/backend/tests/unit/test_fixtures_loader.py` :
```python
from pathlib import Path

import pytest

from tests.fixtures.loader import ReferenceParcel, load_reference_parcels


def test_loader_returns_all_5_reference_parcels() -> None:
    parcels = load_reference_parcels()
    ids = [p.id for p in parcels]
    assert set(ids) == {
        "paris_8e_ug_reference",
        "nogent_sur_marne_ub_reference",
        "saint_denis_um_reference",
        "versailles_ua_reference",
        "meaux_uc_reference",
    }


def test_reference_parcel_has_required_fields() -> None:
    parcels = load_reference_parcels()
    for p in parcels:
        assert p.id
        assert p.insee and len(p.insee) == 5
        assert p.section
        assert p.numero
        assert p.zone_plu_code


def test_loader_raises_if_file_missing(tmp_path: Path) -> None:
    missing = tmp_path / "nonexistent.yaml"
    with pytest.raises(FileNotFoundError):
        load_reference_parcels(path=missing)
```

- [ ] **Step 4: Lancer le test — doit échouer**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude/apps/backend
source .venv/bin/activate
pytest tests/unit/test_fixtures_loader.py -v
```

Expected: `ModuleNotFoundError: No module named 'tests.fixtures.loader'`.

- [ ] **Step 5: Implémenter le loader**

`apps/backend/tests/fixtures/loader.py` :
```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_FIXTURES_PATH = Path(__file__).parent / "parcelles_reference.yaml"


@dataclass(frozen=True)
class ReferenceParcel:
    id: str
    address: str
    insee: str
    section: str
    numero: str
    zone_plu_code: str
    extra: dict[str, Any]  # pour champs remplis aux phases ultérieures


def load_reference_parcels(path: Path = DEFAULT_FIXTURES_PATH) -> list[ReferenceParcel]:
    if not path.exists():
        raise FileNotFoundError(f"Fixtures file not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    parcels_raw = data.get("parcelles", [])
    parcels: list[ReferenceParcel] = []
    for raw in parcels_raw:
        known_keys = {"id", "address", "insee", "section", "numero", "zone_plu_code"}
        extra = {k: v for k, v in raw.items() if k not in known_keys}
        parcels.append(
            ReferenceParcel(
                id=raw["id"],
                address=raw["address"],
                insee=raw["insee"],
                section=raw["section"],
                numero=raw["numero"],
                zone_plu_code=raw["zone_plu_code"],
                extra=extra,
            )
        )
    return parcels
```

- [ ] **Step 6: Relancer le test — doit passer**

```bash
pytest tests/unit/test_fixtures_loader.py -v
```

Expected: `3 passed`.

- [ ] **Step 7: Commit**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add apps/backend/tests/fixtures apps/backend/tests/unit/test_fixtures_loader.py
git commit -m "feat(backend): reference fixtures YAML + loader with schema"
```

---

## Task 15: Installer gh CLI et créer le repo GitHub ArchiClaude (privé)

**Files:**
- Aucun nouveau fichier, opération GitHub uniquement

- [ ] **Step 1: Installer gh CLI**

```bash
brew install gh
```

Expected: installation réussie.

- [ ] **Step 2: Authentifier gh avec le compte GitHub perso**

```bash
gh auth login
```

Suivre les prompts interactifs :
- Where do you use GitHub? → **GitHub.com**
- What is your preferred protocol? → **HTTPS**
- Authenticate Git with your GitHub credentials? → **Yes**
- How would you like to authenticate? → **Login with a web browser**

Copier le code à coller dans le navigateur et valider l'auth.

Vérifier :
```bash
gh auth status
```

Expected: `Logged in to github.com as mammonea57`.

- [ ] **Step 3: Créer le repo privé**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
gh repo create ArchiClaude --private --source=. --remote=origin --description="Faisabilité architecturale et dossier PC pour promoteurs en Île-de-France"
```

Expected: repo créé à `https://github.com/mammonea57/ArchiClaude` (privé), remote `origin` ajouté localement.

Vérifier :
```bash
git remote -v
```

Expected:
```
origin  https://github.com/mammonea57/ArchiClaude.git (fetch)
origin  https://github.com/mammonea57/ArchiClaude.git (push)
```

- [ ] **Step 4: Premier push**

```bash
git push -u origin main
```

Expected: tous les commits poussés, branche `main` trackée.

- [ ] **Step 5: Vérifier que la CI se déclenche**

Ouvrir `https://github.com/mammonea57/ArchiClaude/actions` dans le navigateur. Le workflow "CI" doit être en cours ou terminé.

Si le job "frontend — Build" échoue faute de variables d'environnement, ce n'est pas bloquant en Phase 0 (pas d'env de prod encore).

- [ ] **Step 6: Commit post-push (rien à commit, juste vérification)**

```bash
git status
```

Expected: `nothing to commit, working tree clean`.

---

## Task 16: Provisionner les services managés (Neon, Upstash, Cloudflare R2, Railway, Vercel)

**Files:**
- Create: `docs/superpowers/plans/deployment-secrets.md`

> **Note** : cette tâche comprend des actions manuelles sur consoles web externes. Les étapes ci-dessous documentent précisément ce qu'il faut créer, dans quel ordre, et comment enregistrer les secrets. Aucun code déployé en Phase 0, juste les services prêts à accueillir le code Phase 1+.

- [ ] **Step 1: Neon (Postgres+PostGIS+pgvector)**

1. Aller sur https://console.neon.tech et créer un compte (Google OAuth recommandé).
2. Cliquer "New Project" :
   - Name: **ArchiClaude**
   - Region: **AWS Europe (Frankfurt)**
   - Postgres version: **16**
3. Dans le projet créé :
   - Aller sur **Branches** → vérifier que `main` est la branche de production
   - Créer une branche **staging** (copie de `main`)
4. Dans **Settings** → **Extensions**, activer : `postgis`, `pgcrypto`, `pg_trgm`, `vector`.
5. Copier les `DATABASE_URL` pour `main` et `staging` (format `postgresql://user:pwd@host/archiclaude`). On les mettra dans Railway en Step 4.

- [ ] **Step 2: Upstash Redis**

1. Aller sur https://console.upstash.com et créer un compte.
2. Cliquer "Create Database" :
   - Name: **archiclaude**
   - Type: **Regional**
   - Region: **eu-central-1**
   - Plan: **Free**
3. Copier la `REDIS_URL` (format `rediss://default:<token>@host:port`).

- [ ] **Step 3: Cloudflare R2**

1. Aller sur https://dash.cloudflare.com → R2 (créer compte si besoin).
2. Cliquer "Create bucket" : name **archiclaude-reports-prod**, location auto.
3. Créer un second bucket **archiclaude-reports-staging**.
4. Dans **Manage R2 API Tokens**, créer un token :
   - Name: **archiclaude-backend**
   - Permissions: **Object Read & Write**
   - Specify buckets: `archiclaude-reports-prod`, `archiclaude-reports-staging`
5. Copier `Access Key ID`, `Secret Access Key`, `Endpoint URL`.

- [ ] **Step 4: Railway (backend + worker)**

1. Aller sur https://railway.com et créer un compte (GitHub OAuth).
2. Cliquer "New Project" → "Deploy from GitHub repo" → sélectionner `mammonea57/ArchiClaude`.
3. Dans le projet créé :
   - Cliquer "Add Service" → sélectionner le repo → choisir dossier **apps/backend** avec commande `uvicorn api.main:app --host 0.0.0.0 --port $PORT`
   - Ajouter un deuxième service (worker) : même repo, dossier `apps/backend`, commande `arq workers.main.Worker`
4. Configurer les variables d'environnement (onglet **Variables**) pour les 2 services :
   ```
   DATABASE_URL=<Neon main URL>
   REDIS_URL=<Upstash URL>
   ANTHROPIC_API_KEY=<à demander à l'utilisateur>
   JWT_SECRET=<générer 32 chars avec `openssl rand -base64 32`>
   R2_ACCESS_KEY_ID=<Cloudflare>
   R2_SECRET_ACCESS_KEY=<Cloudflare>
   R2_BUCKET=archiclaude-reports-prod
   R2_ENDPOINT=<Cloudflare endpoint>
   GOOGLE_OAUTH_CLIENT_ID=<créé Step 6>
   GOOGLE_OAUTH_CLIENT_SECRET=<créé Step 6>
   MAPILLARY_CLIENT_TOKEN=<à demander à l'utilisateur, Phase 2>
   GOOGLE_STREETVIEW_API_KEY=<optionnel, Phase 2>
   NAVITIA_API_KEY=<optionnel, Phase 2>
   ```
5. Dans **Settings** de chaque service :
   - Deploy branch: `main`
   - Auto-deploy: enabled
6. Générer un domaine public pour le backend : `api.archiclaude.app` (ou sous-domaine Railway par défaut en attendant l'achat du domaine).

- [ ] **Step 5: Vercel (frontend)**

1. Aller sur https://vercel.com et créer un compte (GitHub OAuth).
2. Cliquer "Add New" → "Project" → importer `mammonea57/ArchiClaude`.
3. Configurer :
   - Framework preset: **Next.js**
   - Root directory: **apps/frontend**
   - Build command: `cd ../.. && pnpm install && pnpm --filter @archiclaude/frontend build`
   - Output directory: `apps/frontend/.next`
   - Install command: `pnpm install`
4. Variables d'environnement :
   ```
   NEXT_PUBLIC_API_URL=https://<railway-backend-url>
   NEXTAUTH_URL=https://archiclaude.vercel.app
   NEXTAUTH_SECRET=<générer 32 chars>
   ```
5. Deploy.

- [ ] **Step 6: Google Cloud Console (OAuth)**

1. Aller sur https://console.cloud.google.com → créer projet "ArchiClaude".
2. **APIs & Services** → **Credentials** → "Create Credentials" → "OAuth Client ID" :
   - Type: **Web application**
   - Name: **ArchiClaude Production**
   - Authorized JavaScript origins: `https://archiclaude.vercel.app`
   - Authorized redirect URIs: `https://archiclaude.vercel.app/api/auth/callback/google`
3. Copier `Client ID` et `Client Secret` → les mettre dans Vercel + Railway.
4. Faire un second OAuth client pour dev local :
   - Name: **ArchiClaude Dev**
   - Origin: `http://localhost:3001`
   - Redirect: `http://localhost:3001/api/auth/callback/google`

- [ ] **Step 7: Documenter les secrets dans un doc privé**

Créer `docs/superpowers/plans/deployment-secrets.md` (à committer **uniquement** avec les **noms** des secrets, jamais les valeurs) :

```markdown
# ArchiClaude — inventaire des secrets de déploiement

Ce document liste **les noms** des secrets stockés dans chaque plateforme. Les valeurs sont uniquement dans les consoles des plateformes respectives.

## Vercel (Frontend)

| Secret | Usage |
|---|---|
| `NEXT_PUBLIC_API_URL` | URL publique du backend Railway |
| `NEXTAUTH_URL` | URL publique Vercel |
| `NEXTAUTH_SECRET` | Signature JWT Auth.js |
| `GOOGLE_OAUTH_CLIENT_ID` | OAuth Google (public) |

## Railway (Backend + Worker)

| Secret | Usage |
|---|---|
| `DATABASE_URL` | Neon Postgres+PostGIS+pgvector |
| `REDIS_URL` | Upstash Redis |
| `ANTHROPIC_API_KEY` | Claude Sonnet/Opus/Haiku |
| `OPENAI_API_KEY` | Embeddings pgvector (Phase 6) |
| `JWT_SECRET` | Match NEXTAUTH_SECRET |
| `GOOGLE_OAUTH_CLIENT_ID` + `GOOGLE_OAUTH_CLIENT_SECRET` | OAuth Google |
| `R2_ACCESS_KEY_ID` + `R2_SECRET_ACCESS_KEY` + `R2_BUCKET` + `R2_ENDPOINT` | Cloudflare R2 |
| `MAPILLARY_CLIENT_TOKEN` | Photos site (Phase 2) |
| `GOOGLE_STREETVIEW_API_KEY` | Fallback photos (Phase 2) |
| `NAVITIA_API_KEY` | Fréquence transports IDF (Phase 2) |

## Procédure de rotation

Tous les 90 jours ou suite à suspicion de fuite :
1. Générer nouvelle valeur (`openssl rand -base64 32` pour tous les secrets ≥32 chars)
2. Mettre à jour sur la plateforme cible
3. Redéployer les services impactés
4. Révoquer l'ancienne valeur dans la console source (Google, Anthropic, etc.)
```

- [ ] **Step 8: Commit la documentation secrets**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add docs/superpowers/plans/deployment-secrets.md
git commit -m "docs: inventory of deployment secrets across Vercel/Railway"
git push origin main
```

- [ ] **Step 9: Vérifier que les déploiements automatiques sont fonctionnels**

Attendre quelques minutes puis :
- Vercel dashboard → vérifier déploiement réussi → visiter l'URL publique, doit afficher la landing page
- Railway dashboard → vérifier build + deploy réussis pour les 2 services → visiter `<api-url>/api/v1/health`, doit retourner `{"status":"ok","service":"archiclaude-backend"}`

Si un déploiement échoue, corriger via commit puis push. La CI et les auto-deploy se redéclenchent.

---

## Task 17: README final Phase 0 + smoke test complet bout-en-bout

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Enrichir `README.md` avec instructions complètes**

Remplacer intégralement le contenu de `/Users/anthonymammone/Desktop/ArchiClaude/README.md` par :

```markdown
# ArchiClaude

Plateforme web de faisabilité architecturale et de génération de dossiers PC pour promoteurs immobiliers en Île-de-France.

**Statut :** Phase 0 terminée — infrastructure technique prête.

## Documentation

- Spec sous-projet 1 : [docs/superpowers/specs/2026-04-16-archiclaude-sous-projet-1-design.md](docs/superpowers/specs/2026-04-16-archiclaude-sous-projet-1-design.md)
- Plan Phase 0 : [docs/superpowers/plans/2026-04-16-archiclaude-phase-0-setup.md](docs/superpowers/plans/2026-04-16-archiclaude-phase-0-setup.md)
- Inventaire secrets : [docs/superpowers/plans/deployment-secrets.md](docs/superpowers/plans/deployment-secrets.md)

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
- Homebrew (macOS) pour `gh`, `cairo`, `pango`, `geos`, `proj`

## Développement local (natif)

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
DATABASE_URL="postgresql://archiclaude:archiclaude@localhost:5432/archiclaude" alembic upgrade head
cd ../..

# 5. Copier les variables d'env
cp .env.example .env
# Remplir les secrets ANTHROPIC_API_KEY, etc.

# 6. Lancer les 3 services (Backend + Worker + Frontend)
# Option A — Via VSCode : sélectionner "🧱 Full Stack" dans "Run and Debug" (Cmd+Shift+D)
# Option B — Via terminal (3 panels) :
#   Terminal 1: cd apps/backend && source .venv/bin/activate && uvicorn api.main:app --reload --port 8000
#   Terminal 2: cd apps/backend && source .venv/bin/activate && arq workers.main.Worker
#   Terminal 3: pnpm --filter @archiclaude/frontend dev
```

Accès :
- Backend : http://localhost:8000 (docs Swagger : /docs)
- Frontend : http://localhost:3001
- Admin flags : http://localhost:3001/admin/flags

> Port 3001 choisi pour éviter le conflit avec l'autre application Urbanisme (port 3000).

## Développement Docker (full stack)

```bash
docker compose --profile full up --build
```

## Tests

```bash
# Backend
cd apps/backend && source .venv/bin/activate
pytest -v

# Frontend
pnpm --filter @archiclaude/frontend typecheck
pnpm --filter @archiclaude/frontend build
```

## Régénérer les types partagés (Pydantic → TS)

```bash
cd apps/backend && source .venv/bin/activate
python scripts/generate_ts_schemas.py
```

Les types sont générés dans `packages/shared-types/src/generated/schemas.ts`.

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

Phase 1 — Données parcelle & urbanisme : ingestion cadastre, GPU, BAN, IGN BDTopo, endpoints `/parcels/*` et `/plu/at-point`. Voir plan à rédiger dans `docs/superpowers/plans/2026-04-16-archiclaude-phase-1-...md`.
```

- [ ] **Step 2: Smoke test complet — chaque commande produit le résultat attendu**

```bash
# 2.1 Backend up
cd /Users/anthonymammone/Desktop/ArchiClaude
docker compose up -d postgres redis
sleep 5
docker compose ps  # healthy expected

# 2.2 Migrations
cd apps/backend && source .venv/bin/activate
DATABASE_URL="postgresql://archiclaude:archiclaude@localhost:5432/archiclaude" alembic upgrade head
# expected: "already at head" ou migrations appliquées

# 2.3 Tests backend
DATABASE_URL="postgresql+asyncpg://archiclaude:archiclaude@localhost:5432/archiclaude" pytest -v
# expected: tous tests passent

# 2.4 Ruff + mypy
ruff check .
ruff format --check .
mypy .
# expected: pas d'erreur

# 2.5 Frontend typecheck + build
cd ../..
pnpm --filter @archiclaude/frontend typecheck
pnpm --filter @archiclaude/frontend build
# expected: build réussit

# 2.6 Types partagés
cd apps/backend && source .venv/bin/activate
python scripts/generate_ts_schemas.py
cat ../../packages/shared-types/src/generated/schemas.ts
# expected: fichier TS avec interfaces
```

- [ ] **Step 3: Commit final Phase 0**

```bash
cd /Users/anthonymammone/Desktop/ArchiClaude
git add README.md
git commit -m "docs: final README for Phase 0 with setup instructions"
git push origin main
```

- [ ] **Step 4: Vérifier sur GitHub**

Ouvrir https://github.com/mammonea57/ArchiClaude :
- Repo privé visible
- README rendu correctement (avec liens internes valides)
- Action CI "CI" au vert sur le dernier commit

- [ ] **Step 5: Marquer Phase 0 terminée**

Créer un tag git :
```bash
git tag -a phase-0-complete -m "Phase 0 setup infrastructure complete"
git push origin phase-0-complete
```

Sur GitHub, transformer le tag en Release (UI : Releases → Draft a new release → choisir le tag → publier avec titre "Phase 0 — Infrastructure ready").

---

## Vérification finale Phase 0

Après exécution des 17 tasks, l'état doit être :

- ✅ Monorepo pnpm fonctionnel avec `apps/backend`, `apps/frontend`, `packages/shared-types`
- ✅ Backend FastAPI démarre, endpoint `/api/v1/health` répond
- ✅ Worker ARQ démarre sans erreur (noop task)
- ✅ Frontend Next.js démarre sur port 3001, landing page rendue
- ✅ Page `/admin/flags` affiche la table depuis le backend
- ✅ PostgreSQL+PostGIS+pgvector provisionnée localement (Docker) et en staging/prod (Neon)
- ✅ Redis local et Upstash provisionnés
- ✅ R2 buckets créés (staging + prod)
- ✅ Feature flags : table + module core + endpoints CRUD + UI admin
- ✅ Telemetry coûts LLM : module `cost_tracking` testé sur 4 modèles avec cache
- ✅ Pipeline Pydantic → TS : script + types générés dans `packages/shared-types`
- ✅ Docker Compose dev stack fonctionnelle (profile default et full)
- ✅ VSCode `.vscode/launch.json` avec 4 configs + compound Full Stack
- ✅ GitHub Actions CI : backend (ruff, mypy, pytest) + frontend (eslint, tsc, build) au vert
- ✅ Fixtures YAML de référence avec loader testé
- ✅ Repo GitHub privé `mammonea57/ArchiClaude` créé avec push initial
- ✅ Vercel + Railway + Google OAuth provisionnés, déploiements automatiques fonctionnels
- ✅ README à jour, secrets documentés sans valeurs

**Temps estimé** : 1.5 jours de dev focus.

**Prochaine étape** : rédaction du plan Phase 1 (`docs/superpowers/plans/2026-04-16-archiclaude-phase-1-donnees-parcelle.md`).
