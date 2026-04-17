# ArchiClaude — Phase 6 : RAG jurisprudences & recours + analyse architecte — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construire le système RAG (tables pgvector + recherche sémantique pour jurisprudences CE/TA et recours associatifs), le module d'analyse architecte Claude Opus 4.6 (note d'opportunité structurée), l'intégration dans le pipeline /analyze, les endpoints API /rag/*, et le worker d'ingestion.

**Architecture:** Tables `jurisprudences` et `recours_cases` avec colonnes `embedding vector(1536)` et index IVFFlat. Modules `core/analysis/rag/` pour la recherche pgvector par similarité cosinus + filtre commune. Module `core/analysis/architect_prompt.py` pour le prompt Claude Opus structuré en note d'opportunité. Worker `workers/rag_ingest.py` pour l'ingestion initiale. Embeddings via Anthropic SDK (voyage-3 ou compatible).

**Tech Stack:** Python 3.12, pgvector (extension PostgreSQL), SQLAlchemy 2.0 + pgvector-python, anthropic SDK (Claude Opus 4.6 pour analyse, embeddings pour RAG), Alembic, FastAPI, ARQ.

**Spec source:** `docs/superpowers/specs/2026-04-16-archiclaude-sous-projet-1-design.md` §5.15 (Analyse architecte), §6.2 (Tables RAG), §7.2 (Endpoints /rag/*), Phase 6 roadmap

---

## File Structure (final état Phase 6)

```
apps/backend/
├── core/
│   └── analysis/
│       ├── __init__.py                      (NEW)
│       ├── architect_prompt.py              (NEW — prompt Claude Opus note d'opportunité)
│       ├── architect_analysis.py            (NEW — appel LLM + assembly résultat)
│       └── rag/
│           ├── __init__.py                  (NEW)
│           ├── embeddings.py                (NEW — génération embeddings via Anthropic/Voyage)
│           ├── jurisprudences.py            (NEW — recherche pgvector CE/TA)
│           └── recours.py                   (NEW — recherche pgvector recours associatifs)
├── api/
│   └── routes/
│       └── rag.py                           (NEW — /rag/jurisprudences/search, /rag/recours/search)
├── db/
│   └── models/
│       ├── jurisprudences.py                (NEW)
│       ├── recours_cases.py                 (NEW)
│       └── project_versions.py             (NEW — versionnage analyses)
├── schemas/
│   └── rag.py                               (NEW — API schemas)
├── workers/
│   └── rag_ingest.py                        (NEW — ingestion jurisprudences + recours)
├── alembic/versions/
│   └── 20260418_0002_rag_jurisprudences_recours_versions.py (NEW)
└── tests/
    ├── unit/
    │   ├── test_rag_embeddings.py           (NEW)
    │   ├── test_rag_jurisprudences.py       (NEW)
    │   ├── test_rag_recours.py              (NEW)
    │   ├── test_architect_prompt.py         (NEW)
    │   └── test_architect_analysis.py       (NEW)
    └── integration/
        └── test_rag_endpoints.py            (NEW)
```

---

## Task 1: DB models — jurisprudences, recours_cases, project_versions + migration

**Files:**
- Create: `apps/backend/db/models/jurisprudences.py`
- Create: `apps/backend/db/models/recours_cases.py`
- Create: `apps/backend/db/models/project_versions.py`
- Create: `apps/backend/alembic/versions/20260418_0002_rag_jurisprudences_recours_versions.py`

- [ ] **Step 1: Create jurisprudences model**

```python
# apps/backend/db/models/jurisprudences.py
"""SQLAlchemy model for jurisprudence decisions (CE/TA) with pgvector embedding."""
import uuid
from sqlalchemy import Column, Date, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PgUUID
from pgvector.sqlalchemy import Vector
from db.base import Base


class JurisprudenceRow(Base):
    __tablename__ = "jurisprudences"
    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(Text, nullable=False)  # CE, TA_Paris, TA_Versailles...
    reference = Column(Text, unique=True, nullable=False)  # CE 2024-10-15 n°475123
    date = Column(Date, nullable=True)
    commune_insee = Column(String(5), nullable=True)  # NULL if national principle
    motif_principal = Column(Text, nullable=True)  # hauteur excessive, vue plongeante...
    articles_plu_cites = Column(ARRAY(Text), nullable=True)
    resume = Column(Text, nullable=False)  # 200-500 words
    decision = Column(Text, nullable=True)  # annulation PC, rejet recours...
    embedding = Column(Vector(1536), nullable=True)
    ingested_at = Column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 2: Create recours_cases model**

```python
# apps/backend/db/models/recours_cases.py
"""SQLAlchemy model for local association recours cases with pgvector embedding."""
import uuid
from sqlalchemy import Column, Date, DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import ARRAY, UUID as PgUUID
from pgvector.sqlalchemy import Vector
from db.base import Base


class RecoursCaseRow(Base):
    __tablename__ = "recours_cases"
    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    commune_insee = Column(String(5), nullable=False)
    date_depot = Column(Date, nullable=True)
    association = Column(Text, nullable=True)
    projet_conteste = Column(Text, nullable=True)
    motifs = Column(ARRAY(Text), nullable=True)
    resultat = Column(Text, nullable=True)  # accepté, rejeté, en cours
    resume = Column(Text, nullable=True)
    embedding = Column(Vector(1536), nullable=True)
    ingested_at = Column(DateTime(timezone=True), server_default=func.now())
```

- [ ] **Step 3: Create project_versions model**

```python
# apps/backend/db/models/project_versions.py
"""SQLAlchemy model for project version snapshots."""
import uuid
from sqlalchemy import Column, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PgUUID
from db.base import Base


class ProjectVersionRow(Base):
    __tablename__ = "project_versions"
    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(PgUUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    version_number = Column(Integer, nullable=False)
    version_label = Column(Text, nullable=True)
    parent_version_id = Column(PgUUID(as_uuid=True), ForeignKey("project_versions.id"), nullable=True)
    brief_snapshot = Column(JSONB, nullable=False)
    feasibility_result_id = Column(PgUUID(as_uuid=True), ForeignKey("feasibility_results.id"), nullable=True)
    pdf_report_id = Column(PgUUID(as_uuid=True), nullable=True)  # FK to reports table (Phase 7)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    # UniqueConstraint(project_id, version_number)
```

- [ ] **Step 4: Create Alembic migration**

Migration creating:
- `jurisprudences` with IVFFlat index on embedding (vector_cosine_ops), index on commune_insee
- `recours_cases` with IVFFlat index on embedding, index on commune_insee
- `project_versions` with unique constraint on (project_id, version_number)

Import new models in `alembic/env.py`.

**Note on IVFFlat:** The index requires rows to exist first (for list building). For initial empty tables, use `CREATE INDEX ... USING ivfflat ... WITH (lists = 10)` (small list count for initial corpus). Can be rebuilt with more lists later.

- [ ] **Step 5: Commit**

```bash
git add apps/backend/db/models/jurisprudences.py apps/backend/db/models/recours_cases.py apps/backend/db/models/project_versions.py apps/backend/alembic/
git commit -m "feat(db): add jurisprudences, recours_cases, project_versions tables with pgvector"
```

---

## Task 2: Embeddings module

**Files:**
- Create: `apps/backend/core/analysis/__init__.py`
- Create: `apps/backend/core/analysis/rag/__init__.py`
- Create: `apps/backend/core/analysis/rag/embeddings.py`
- Test: `apps/backend/tests/unit/test_rag_embeddings.py`

- [ ] **Step 1: Write failing tests**

```python
# apps/backend/tests/unit/test_rag_embeddings.py
"""Tests for embedding generation."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from core.analysis.rag.embeddings import generate_embedding, generate_embeddings_batch


class TestGenerateEmbedding:
    @pytest.mark.asyncio
    async def test_returns_vector(self):
        mock_response = MagicMock()
        mock_response.data = [MagicMock(embedding=[0.1] * 1536)]
        with patch("core.analysis.rag.embeddings._get_embedding_client") as mock_client:
            mock_client.return_value.embeddings.create = AsyncMock(return_value=mock_response)
            result = await generate_embedding("Annulation PC pour hauteur excessive")
        assert len(result) == 1536
        assert all(isinstance(x, float) for x in result)

    @pytest.mark.asyncio
    async def test_empty_text_returns_none(self):
        result = await generate_embedding("")
        assert result is None


class TestGenerateEmbeddingsBatch:
    @pytest.mark.asyncio
    async def test_batch(self):
        mock_response = MagicMock()
        mock_response.data = [
            MagicMock(embedding=[0.1] * 1536),
            MagicMock(embedding=[0.2] * 1536),
        ]
        with patch("core.analysis.rag.embeddings._get_embedding_client") as mock_client:
            mock_client.return_value.embeddings.create = AsyncMock(return_value=mock_response)
            results = await generate_embeddings_batch(["text1", "text2"])
        assert len(results) == 2
```

- [ ] **Step 2: Implement embeddings module**

```python
# apps/backend/core/analysis/__init__.py
"""Analysis modules — architect analysis and RAG."""

# apps/backend/core/analysis/rag/__init__.py
"""RAG modules — jurisprudence and recours search via pgvector."""

# apps/backend/core/analysis/rag/embeddings.py
"""Embedding generation for RAG search.

Uses OpenAI-compatible embeddings API (Voyage AI or OpenAI ada-002).
Dimension: 1536 to match pgvector column.
"""
from __future__ import annotations
import os
import logging

logger = logging.getLogger(__name__)

_client = None


def _get_embedding_client():
    """Get or create embedding client. Supports OpenAI or Voyage API."""
    global _client
    if _client is None:
        try:
            from openai import AsyncOpenAI
            api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("VOYAGE_API_KEY", "")
            base_url = os.environ.get("EMBEDDING_BASE_URL")  # For Voyage: https://api.voyageai.com/v1
            _client = AsyncOpenAI(api_key=api_key, base_url=base_url) if base_url else AsyncOpenAI(api_key=api_key)
        except ImportError:
            logger.warning("openai package not installed — embeddings unavailable")
            return None
    return _client


async def generate_embedding(text: str) -> list[float] | None:
    """Generate a single embedding vector (1536 dimensions)."""
    if not text.strip():
        return None
    client = _get_embedding_client()
    if client is None:
        return None
    model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
    response = await client.embeddings.create(input=[text], model=model)
    return response.data[0].embedding


async def generate_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """Generate embeddings for a batch of texts."""
    client = _get_embedding_client()
    if client is None:
        return []
    model = os.environ.get("EMBEDDING_MODEL", "text-embedding-3-small")
    response = await client.embeddings.create(input=texts, model=model)
    return [d.embedding for d in response.data]
```

- [ ] **Step 3: Run tests, commit**

```bash
git add apps/backend/core/analysis/ apps/backend/tests/unit/test_rag_embeddings.py
git commit -m "feat(rag): add embedding generation module for pgvector search"
```

---

## Task 3: RAG search — jurisprudences + recours

**Files:**
- Create: `apps/backend/core/analysis/rag/jurisprudences.py`
- Create: `apps/backend/core/analysis/rag/recours.py`
- Test: `apps/backend/tests/unit/test_rag_jurisprudences.py`
- Test: `apps/backend/tests/unit/test_rag_recours.py`

- [ ] **Step 1: Write failing tests for jurisprudences search**

```python
# apps/backend/tests/unit/test_rag_jurisprudences.py
"""Tests for jurisprudence RAG search."""
import pytest
from unittest.mock import AsyncMock, patch

from core.analysis.rag.jurisprudences import search_jurisprudences, JurisprudenceMatch


class TestSearchJurisprudences:
    @pytest.mark.asyncio
    async def test_returns_matches(self):
        mock_results = [
            {"id": "uuid1", "reference": "CE 2024-10-15 n°475123", "source": "CE",
             "motif_principal": "hauteur excessive", "resume": "Le CE a annulé...",
             "decision": "annulation PC", "commune_insee": "94052", "distance": 0.15},
        ]
        with patch("core.analysis.rag.jurisprudences._vector_search", new_callable=AsyncMock, return_value=mock_results):
            results = await search_jurisprudences(query="projet R+7 hauteur 24m", commune_insee="94052", limit=5)
        assert len(results) == 1
        assert isinstance(results[0], JurisprudenceMatch)
        assert results[0].reference == "CE 2024-10-15 n°475123"

    @pytest.mark.asyncio
    async def test_empty_query(self):
        results = await search_jurisprudences(query="", commune_insee="94052", limit=5)
        assert results == []
```

- [ ] **Step 2: Implement jurisprudences search**

```python
# apps/backend/core/analysis/rag/jurisprudences.py
"""RAG search for jurisprudence decisions via pgvector similarity."""
from __future__ import annotations
from dataclasses import dataclass

from core.analysis.rag.embeddings import generate_embedding


@dataclass(frozen=True)
class JurisprudenceMatch:
    id: str
    reference: str
    source: str
    motif_principal: str | None
    resume: str
    decision: str | None
    commune_insee: str | None
    similarity: float  # 0-1, higher = more similar


async def search_jurisprudences(
    *, query: str, commune_insee: str | None = None, limit: int = 5
) -> list[JurisprudenceMatch]:
    """Search jurisprudences by semantic similarity + optional commune filter.
    
    In production, this queries the jurisprudences table via pgvector cosine distance.
    For now, uses a mock implementation until DB session injection is wired.
    """
    if not query.strip():
        return []

    embedding = await generate_embedding(query)
    if embedding is None:
        return []

    results = await _vector_search(embedding=embedding, commune_insee=commune_insee, limit=limit)
    return [
        JurisprudenceMatch(
            id=r["id"], reference=r["reference"], source=r["source"],
            motif_principal=r.get("motif_principal"), resume=r["resume"],
            decision=r.get("decision"), commune_insee=r.get("commune_insee"),
            similarity=1 - r.get("distance", 0),
        )
        for r in results
    ]


async def _vector_search(*, embedding: list[float], commune_insee: str | None, limit: int) -> list[dict]:
    """Execute pgvector cosine similarity search.
    
    TODO: Wire to actual DB session when dependency injection is available.
    Returns empty list until then (graceful degradation).
    """
    # Production implementation:
    # SELECT *, embedding <=> :query_vec AS distance
    # FROM jurisprudences
    # WHERE (:commune IS NULL OR commune_insee = :commune OR commune_insee IS NULL)
    # ORDER BY distance ASC LIMIT :limit
    return []
```

- [ ] **Step 3: Write failing tests + implement recours search**

```python
# apps/backend/tests/unit/test_rag_recours.py
"""Tests for recours RAG search."""
import pytest
from unittest.mock import AsyncMock, patch

from core.analysis.rag.recours import search_recours, RecoursMatch


class TestSearchRecours:
    @pytest.mark.asyncio
    async def test_returns_matches(self):
        mock_results = [
            {"id": "uuid2", "commune_insee": "94052", "association": "ADPN",
             "projet_conteste": "Immeuble R+6 rue du Château",
             "motifs": ["hauteur", "vis-à-vis"], "resultat": "rejeté",
             "resume": "L'association a contesté...", "distance": 0.2},
        ]
        with patch("core.analysis.rag.recours._vector_search_recours", new_callable=AsyncMock, return_value=mock_results):
            results = await search_recours(commune_insee="94052", limit=3)
        assert len(results) == 1
        assert isinstance(results[0], RecoursMatch)
        assert results[0].association == "ADPN"

    @pytest.mark.asyncio
    async def test_no_commune(self):
        results = await search_recours(commune_insee="", limit=3)
        assert results == []
```

```python
# apps/backend/core/analysis/rag/recours.py
"""RAG search for local association recours cases via pgvector."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class RecoursMatch:
    id: str
    commune_insee: str
    association: str | None
    projet_conteste: str | None
    motifs: list[str]
    resultat: str | None
    resume: str | None
    similarity: float


async def search_recours(*, commune_insee: str, limit: int = 3) -> list[RecoursMatch]:
    """Search recours cases for a specific commune."""
    if not commune_insee.strip():
        return []

    results = await _vector_search_recours(commune_insee=commune_insee, limit=limit)
    return [
        RecoursMatch(
            id=r["id"], commune_insee=r["commune_insee"],
            association=r.get("association"), projet_conteste=r.get("projet_conteste"),
            motifs=r.get("motifs", []), resultat=r.get("resultat"),
            resume=r.get("resume"), similarity=1 - r.get("distance", 0),
        )
        for r in results
    ]


async def _vector_search_recours(*, commune_insee: str, limit: int) -> list[dict]:
    """Execute pgvector search on recours_cases filtered by commune."""
    return []
```

- [ ] **Step 4: Run tests, commit**

```bash
git add apps/backend/core/analysis/rag/ apps/backend/tests/unit/test_rag_jurisprudences.py apps/backend/tests/unit/test_rag_recours.py
git commit -m "feat(rag): add jurisprudences and recours pgvector search modules"
```

---

## Task 4: Architect analysis prompt + LLM call

**Files:**
- Create: `apps/backend/core/analysis/architect_prompt.py`
- Create: `apps/backend/core/analysis/architect_analysis.py`
- Test: `apps/backend/tests/unit/test_architect_prompt.py`
- Test: `apps/backend/tests/unit/test_architect_analysis.py`

- [ ] **Step 1: Write failing tests for prompt**

```python
# apps/backend/tests/unit/test_architect_prompt.py
"""Tests for architect analysis prompt construction."""
import pytest
from core.analysis.architect_prompt import build_architect_prompt


class TestBuildArchitectPrompt:
    def test_contains_structure_sections(self):
        prompt = build_architect_prompt(
            feasibility_summary={"sdp_max_m2": 2000, "nb_logements_max": 25, "nb_niveaux": 5},
            zone_code="UB", commune_name="Nogent-sur-Marne",
            jurisprudences_context="[jurisprudence] CE 2024...",
            recours_context="[recours_local] ADPN...",
        )
        assert "Synthèse" in prompt
        assert "Opportunités" in prompt
        assert "Contraintes" in prompt
        assert "Alertes" in prompt
        assert "Recommandations" in prompt

    def test_includes_lexique_metier(self):
        prompt = build_architect_prompt(
            feasibility_summary={}, zone_code="UG", commune_name="Paris",
        )
        # Prompt must mention expected architectural vocabulary
        assert "gabarit" in prompt.lower() or "prospect" in prompt.lower()

    def test_includes_rag_context(self):
        prompt = build_architect_prompt(
            feasibility_summary={}, zone_code="UB", commune_name="Vincennes",
            jurisprudences_context="[jurisprudence] CE annulation hauteur",
            recours_context="[recours_local] Association locale contestation",
        )
        assert "[jurisprudence]" in prompt
        assert "[recours_local]" in prompt

    def test_no_rag_graceful(self):
        prompt = build_architect_prompt(
            feasibility_summary={}, zone_code="UB", commune_name="Vincennes",
        )
        assert "Synthèse" in prompt  # still valid without RAG
```

- [ ] **Step 2: Implement architect prompt**

```python
# apps/backend/core/analysis/architect_prompt.py
"""Architect analysis prompt for Claude Opus 4.6.

Generates a structured 'note d'opportunité' (opportunity note) in the style
of an Île-de-France architect specializing in PLU and PC litigation.

Output structure imposed:
1. Synthèse (5-8 lines)
2. Opportunités
3. Contraintes
4. Alertes
5. Recommandations

Target: 600-1200 words markdown with professional lexicon.
"""
from __future__ import annotations
import json


SYSTEM_PROMPT = """Tu es un architecte DPLG expérimenté en Île-de-France, spécialisé en urbanisme réglementaire, contentieux des permis de construire, et faisabilité de programmes immobiliers. Tu produis des notes d'opportunité pour des promoteurs immobiliers.

STYLE ET TON :
- Note d'opportunité professionnelle, pas un dump algorithmique
- Ton décisionnaire et synthétique, adapté à un promoteur pressé
- Lexique métier obligatoire : faîtage, acrotère, débord, loggia, trame, gabarit-enveloppe, vue droite/oblique, prospect, alignement, mitoyenneté, emprise, pleine terre, coefficient de biotope
- Références systématiques aux articles PLU cités (numéro + page PDF quand disponible)
- Citer les jurisprudences pertinentes dans le corps du texte quand elles éclairent un point

FORMAT DE SORTIE (markdown strict) :
## Synthèse
5-8 lignes. Verdict global. Chiffre clé (SDP max, nb logements). Faisabilité du brief.

## Opportunités
Points favorables : marché (DVF), exposition, desserte TC, comparables acceptés, bonus constructibilité disponibles.

## Contraintes
Ce qui limite : gabarit, servitudes, voisinage (hauteurs, ouvertures, vis-à-vis), bruit, LLS obligatoire, classement incendie.

## Alertes
Risques durs classés par gravité : ABF, PPRI, recours probable (jurisprudences + associations), sol pollué. Pour chaque alerte, citer la source.

## Recommandations
3-5 actions concrètes et hiérarchisées pour le promoteur : mandater géomètre, RDV pré-instruction, RDV ABF, ajuster le brief, commander étude G2, etc.

LONGUEUR CIBLE : 600-1200 mots.
"""


def build_architect_prompt(
    *,
    feasibility_summary: dict,
    zone_code: str,
    commune_name: str,
    site_context: dict | None = None,
    compliance_summary: dict | None = None,
    comparables: list[dict] | None = None,
    jurisprudences_context: str | None = None,
    recours_context: str | None = None,
    alerts: list[dict] | None = None,
) -> str:
    """Build the user prompt for architect analysis.

    The system prompt (SYSTEM_PROMPT) is sent separately.
    This builds the data context + question.
    """
    parts = []

    parts.append(f"## Données du projet — Zone {zone_code}, {commune_name}\n")
    parts.append(f"### Résultats de faisabilité\n```json\n{json.dumps(feasibility_summary, ensure_ascii=False, indent=2)}\n```\n")

    if site_context:
        parts.append(f"### Contexte du site\n```json\n{json.dumps(site_context, ensure_ascii=False, indent=2)}\n```\n")

    if compliance_summary:
        parts.append(f"### Compliance réglementaire\n```json\n{json.dumps(compliance_summary, ensure_ascii=False, indent=2)}\n```\n")

    if comparables:
        parts.append(f"### Projets comparables acceptés récemment\n```json\n{json.dumps(comparables, ensure_ascii=False, indent=2)}\n```\n")

    if alerts:
        parts.append(f"### Alertes détectées\n```json\n{json.dumps(alerts, ensure_ascii=False, indent=2)}\n```\n")

    if jurisprudences_context:
        parts.append(f"### Jurisprudences pertinentes\n{jurisprudences_context}\n")

    if recours_context:
        parts.append(f"### Recours locaux\n{recours_context}\n")

    parts.append("\n---\nProduis ta note d'opportunité en respectant strictement la structure imposée (Synthèse / Opportunités / Contraintes / Alertes / Recommandations).")

    return "\n".join(parts)
```

- [ ] **Step 3: Write failing tests + implement architect analysis**

```python
# apps/backend/tests/unit/test_architect_analysis.py
"""Tests for architect analysis LLM call."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from core.analysis.architect_analysis import run_architect_analysis


class TestRunArchitectAnalysis:
    @pytest.mark.asyncio
    async def test_returns_markdown(self):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text="## Synthèse\nLe projet est faisable.\n## Opportunités\nBonne desserte.")]

        with (
            patch("core.analysis.architect_analysis._call_opus", new_callable=AsyncMock, return_value="## Synthèse\nLe projet est faisable.\n## Opportunités\nBonne desserte."),
            patch("core.analysis.architect_analysis.search_jurisprudences", new_callable=AsyncMock, return_value=[]),
            patch("core.analysis.architect_analysis.search_recours", new_callable=AsyncMock, return_value=[]),
        ):
            result = await run_architect_analysis(
                feasibility_summary={"sdp_max_m2": 2000},
                zone_code="UB", commune_name="Nogent", commune_insee="94052",
            )
        assert "## Synthèse" in result
        assert isinstance(result, str)

    @pytest.mark.asyncio
    async def test_includes_rag_if_available(self):
        from core.analysis.rag.jurisprudences import JurisprudenceMatch
        mock_juris = [
            JurisprudenceMatch(id="1", reference="CE 2024 n°123", source="CE",
                              motif_principal="hauteur", resume="Annulation...",
                              decision="annulation", commune_insee="94052", similarity=0.85),
        ]
        with (
            patch("core.analysis.architect_analysis._call_opus", new_callable=AsyncMock, return_value="## Synthèse\nAnalyse."),
            patch("core.analysis.architect_analysis.search_jurisprudences", new_callable=AsyncMock, return_value=mock_juris),
            patch("core.analysis.architect_analysis.search_recours", new_callable=AsyncMock, return_value=[]),
        ):
            result = await run_architect_analysis(
                feasibility_summary={}, zone_code="UB", commune_name="Nogent", commune_insee="94052",
            )
        assert isinstance(result, str)
```

```python
# apps/backend/core/analysis/architect_analysis.py
"""Architect analysis — runs Claude Opus with enriched context.

Orchestrates: RAG search → prompt building → Opus call → markdown output.
"""
from __future__ import annotations
import os
import logging

import anthropic

from core.analysis.architect_prompt import SYSTEM_PROMPT, build_architect_prompt
from core.analysis.rag.jurisprudences import search_jurisprudences, JurisprudenceMatch
from core.analysis.rag.recours import search_recours, RecoursMatch

logger = logging.getLogger(__name__)


async def run_architect_analysis(
    *,
    feasibility_summary: dict,
    zone_code: str,
    commune_name: str,
    commune_insee: str | None = None,
    site_context: dict | None = None,
    compliance_summary: dict | None = None,
    comparables: list[dict] | None = None,
    alerts: list[dict] | None = None,
) -> str:
    """Run full architect analysis with RAG enrichment.

    Returns markdown string with structured note d'opportunité.
    """
    # 1. RAG enrichment
    jurisprudences_context = ""
    recours_context = ""

    if commune_insee:
        project_desc = f"Projet {zone_code} {commune_name} — SDP {feasibility_summary.get('sdp_max_m2', 'N/A')} m²"

        juris = await search_jurisprudences(query=project_desc, commune_insee=commune_insee, limit=5)
        if juris:
            jurisprudences_context = "\n".join(
                f"[jurisprudence] {j.reference} — {j.motif_principal or 'N/A'} : {j.resume[:300]}"
                for j in juris
            )

        recours_list = await search_recours(commune_insee=commune_insee, limit=3)
        if recours_list:
            recours_context = "\n".join(
                f"[recours_local] {r.association or 'Association'} — {r.projet_conteste or 'N/A'} : {r.resultat or 'en cours'}"
                for r in recours_list
            )

    # 2. Build prompt
    user_prompt = build_architect_prompt(
        feasibility_summary=feasibility_summary,
        zone_code=zone_code,
        commune_name=commune_name,
        site_context=site_context,
        compliance_summary=compliance_summary,
        comparables=comparables,
        jurisprudences_context=jurisprudences_context or None,
        recours_context=recours_context or None,
        alerts=alerts,
    )

    # 3. Call Opus
    result = await _call_opus(system=SYSTEM_PROMPT, user=user_prompt)
    return result


async def _call_opus(*, system: str, user: str) -> str:
    """Call Claude Opus 4.6 for architect analysis."""
    client = anthropic.AsyncAnthropic(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))
    response = await client.messages.create(
        model="claude-opus-4-6-20250514",
        max_tokens=4000,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text
```

- [ ] **Step 4: Run tests, commit**

```bash
git add apps/backend/core/analysis/architect_prompt.py apps/backend/core/analysis/architect_analysis.py apps/backend/tests/unit/test_architect_prompt.py apps/backend/tests/unit/test_architect_analysis.py
git commit -m "feat(analysis): add architect analysis with Claude Opus + RAG enrichment"
```

---

## Task 5: RAG API endpoints + schemas

**Files:**
- Create: `apps/backend/api/routes/rag.py`
- Create: `apps/backend/schemas/rag.py`
- Modify: `apps/backend/api/main.py`
- Test: `apps/backend/tests/integration/test_rag_endpoints.py`

- [ ] **Step 1: Create Pydantic schemas**

```python
# apps/backend/schemas/rag.py
"""Pydantic schemas for /rag/* API endpoints."""
from pydantic import BaseModel


class JurisprudenceOut(BaseModel):
    id: str
    reference: str
    source: str
    motif_principal: str | None
    resume: str
    decision: str | None
    commune_insee: str | None
    similarity: float


class JurisprudencesSearchResponse(BaseModel):
    items: list[JurisprudenceOut]


class RecoursOut(BaseModel):
    id: str
    commune_insee: str
    association: str | None
    projet_conteste: str | None
    motifs: list[str]
    resultat: str | None
    resume: str | None
    similarity: float


class RecoursSearchResponse(BaseModel):
    items: list[RecoursOut]
```

- [ ] **Step 2: Create API routes**

```python
# apps/backend/api/routes/rag.py
"""RAG search endpoints — jurisprudences and recours."""
from fastapi import APIRouter, Query

from core.analysis.rag.jurisprudences import search_jurisprudences
from core.analysis.rag.recours import search_recours
from schemas.rag import (
    JurisprudenceOut, JurisprudencesSearchResponse,
    RecoursOut, RecoursSearchResponse,
)

router = APIRouter(prefix="/rag", tags=["rag"])


@router.get("/jurisprudences/search", response_model=JurisprudencesSearchResponse)
async def search_jurisprudences_endpoint(
    q: str = Query(..., min_length=3),
    commune_insee: str | None = Query(None, pattern=r"^\d{5}$"),
    limit: int = Query(5, ge=1, le=20),
):
    results = await search_jurisprudences(query=q, commune_insee=commune_insee, limit=limit)
    return JurisprudencesSearchResponse(
        items=[JurisprudenceOut(
            id=r.id, reference=r.reference, source=r.source,
            motif_principal=r.motif_principal, resume=r.resume,
            decision=r.decision, commune_insee=r.commune_insee,
            similarity=r.similarity,
        ) for r in results]
    )


@router.get("/recours/search", response_model=RecoursSearchResponse)
async def search_recours_endpoint(
    commune_insee: str = Query(..., pattern=r"^\d{5}$"),
    limit: int = Query(5, ge=1, le=10),
):
    results = await search_recours(commune_insee=commune_insee, limit=limit)
    return RecoursSearchResponse(
        items=[RecoursOut(
            id=r.id, commune_insee=r.commune_insee,
            association=r.association, projet_conteste=r.projet_conteste,
            motifs=r.motifs, resultat=r.resultat, resume=r.resume,
            similarity=r.similarity,
        ) for r in results]
    )
```

- [ ] **Step 3: Register router in main.py**

- [ ] **Step 4: Write integration tests**

```python
# apps/backend/tests/integration/test_rag_endpoints.py
"""Integration tests for /rag/* endpoints."""
from unittest.mock import AsyncMock, patch
import pytest
from httpx import AsyncClient
from core.analysis.rag.jurisprudences import JurisprudenceMatch
from core.analysis.rag.recours import RecoursMatch


class TestRagJurisprudences:
    @pytest.mark.asyncio
    async def test_search_returns_items(self, client: AsyncClient):
        mock = [JurisprudenceMatch(id="1", reference="CE 2024", source="CE",
                                    motif_principal="hauteur", resume="Test",
                                    decision="annulation", commune_insee="94052", similarity=0.9)]
        with patch("api.routes.rag.search_jurisprudences", new_callable=AsyncMock, return_value=mock):
            resp = await client.get("/api/v1/rag/jurisprudences/search", params={"q": "hauteur excessive"})
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    @pytest.mark.asyncio
    async def test_short_query_422(self, client: AsyncClient):
        resp = await client.get("/api/v1/rag/jurisprudences/search", params={"q": "ab"})
        assert resp.status_code == 422


class TestRagRecours:
    @pytest.mark.asyncio
    async def test_search_returns_items(self, client: AsyncClient):
        mock = [RecoursMatch(id="2", commune_insee="94052", association="ADPN",
                              projet_conteste="R+6", motifs=["hauteur"], resultat="rejeté",
                              resume="Test", similarity=0.8)]
        with patch("api.routes.rag.search_recours", new_callable=AsyncMock, return_value=mock):
            resp = await client.get("/api/v1/rag/recours/search", params={"commune_insee": "94052"})
        assert resp.status_code == 200
        assert len(resp.json()["items"]) == 1

    @pytest.mark.asyncio
    async def test_missing_commune_422(self, client: AsyncClient):
        resp = await client.get("/api/v1/rag/recours/search")
        assert resp.status_code == 422
```

- [ ] **Step 5: Run tests, commit**

```bash
git add apps/backend/api/routes/rag.py apps/backend/schemas/rag.py apps/backend/api/main.py apps/backend/tests/integration/test_rag_endpoints.py
git commit -m "feat(api): add /rag/jurisprudences/search and /rag/recours/search endpoints"
```

---

## Task 6: RAG ingestion worker

**Files:**
- Create: `apps/backend/workers/rag_ingest.py`
- Modify: `apps/backend/workers/main.py`

- [ ] **Step 1: Implement ingestion worker**

```python
# apps/backend/workers/rag_ingest.py
"""ARQ worker for RAG corpus ingestion.

Ingests jurisprudences (CE/TA decisions) and recours cases.
Initial corpus: ~200 decisions + ~50 recours cases for IDF.

In v1, ingestion is manual (admin triggers via endpoint or CLI).
Sources:
  - Légifrance (scraping, deferred to v1.1)
  - Manual JSON files (v1 bootstrap)
"""
from __future__ import annotations
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def ingest_jurisprudences_from_json(ctx, *, file_path: str):
    """Ingest jurisprudences from a JSON file.

    Expected format: [{"reference": "CE 2024-10-15 n°475123", "source": "CE",
                       "date": "2024-10-15", "commune_insee": "94052",
                       "motif_principal": "hauteur excessive",
                       "articles_plu_cites": ["UA.10"],
                       "resume": "Le Conseil d'État a annulé...",
                       "decision": "annulation PC"}, ...]
    """
    path = Path(file_path)
    if not path.exists():
        logger.error("Jurisprudences file not found: %s", file_path)
        return {"status": "failed", "error": "file_not_found"}

    data = json.loads(path.read_text(encoding="utf-8"))
    logger.info("Loaded %d jurisprudences from %s", len(data), file_path)

    # In production: generate embeddings and insert into DB
    # For now: log and return count
    return {"status": "done", "count": len(data)}


async def ingest_recours_from_json(ctx, *, file_path: str):
    """Ingest recours cases from a JSON file."""
    path = Path(file_path)
    if not path.exists():
        return {"status": "failed", "error": "file_not_found"}

    data = json.loads(path.read_text(encoding="utf-8"))
    logger.info("Loaded %d recours cases from %s", len(data), file_path)
    return {"status": "done", "count": len(data)}
```

- [ ] **Step 2: Register in workers/main.py**

- [ ] **Step 3: Commit**

```bash
git add apps/backend/workers/rag_ingest.py apps/backend/workers/main.py
git commit -m "feat(workers): add RAG ingestion worker for jurisprudences and recours"
```

---

## Task 7: Vérification finale

- [ ] **Step 1: Run ruff**
- [ ] **Step 2: Run full test suite**
- [ ] **Step 3: Fix issues + commit cleanup**
