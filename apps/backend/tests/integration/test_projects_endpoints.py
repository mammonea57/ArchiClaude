"""Integration tests for /api/v1/projects endpoints.

Tests use the conftest `client` fixture (ASGI transport, real DB).
A truncate fixture keeps the projects table clean between tests.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

DATABASE_URL = "postgresql+asyncpg://archiclaude:archiclaude@localhost:5432/archiclaude"

_SAMPLE_BRIEF = {"destination": "logement_collectif", "mix_typologique": {"T3": 1.0}}
# Must match api/routes/projects.py _PLACEHOLDER_USER_ID
_PLACEHOLDER_USER_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture(autouse=True)
async def _reset_projects() -> None:
    """Truncate projects (and cascade) and ensure placeholder user exists."""
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE projects CASCADE"))
        # Ensure the placeholder user referenced by the routes exists
        await conn.execute(
            text(
                """
                INSERT INTO users (id, email, role)
                VALUES (:id, 'placeholder@archiclaude.test', 'user')
                ON CONFLICT (id) DO NOTHING
                """
            ),
            {"id": _PLACEHOLDER_USER_ID},
        )
    await engine.dispose()


class TestProjectsEndpoints:
    @pytest.mark.asyncio
    async def test_create_project(self, client: AsyncClient) -> None:
        """POST /projects should return 201 with id, name, status."""
        resp = await client.post(
            "/api/v1/projects",
            json={"name": "Test Project", "brief": _SAMPLE_BRIEF},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["name"] == "Test Project"
        assert body["status"] == "draft"
        assert "id" in body

    @pytest.mark.asyncio
    async def test_list_projects_empty_initially(self, client: AsyncClient) -> None:
        """GET /projects should return 200 with empty list when no projects."""
        resp = await client.get("/api/v1/projects")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_projects_after_create(self, client: AsyncClient) -> None:
        """GET /projects should return created project."""
        await client.post(
            "/api/v1/projects",
            json={"name": "Projet Alpha", "brief": _SAMPLE_BRIEF},
        )
        resp = await client.get("/api/v1/projects")
        assert resp.status_code == 200
        projects = resp.json()
        assert len(projects) == 1
        assert projects[0]["name"] == "Projet Alpha"

    @pytest.mark.asyncio
    async def test_get_project_by_id(self, client: AsyncClient) -> None:
        """GET /projects/{id} should return project detail including brief."""
        create_resp = await client.post(
            "/api/v1/projects",
            json={"name": "Projet Beta", "brief": _SAMPLE_BRIEF},
        )
        project_id = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/projects/{project_id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == project_id
        assert body["name"] == "Projet Beta"
        assert "brief" in body
        assert body["brief"]["destination"] == "logement_collectif"

    @pytest.mark.asyncio
    async def test_get_project_not_found(self, client: AsyncClient) -> None:
        """GET /projects/{unknown-id} should return 404."""
        resp = await client.get("/api/v1/projects/00000000-0000-0000-0000-000000000099")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_analyze_returns_202(self, client: AsyncClient) -> None:
        """POST /projects/{id}/analyze should return 202 with job_id."""
        resp = await client.post("/api/v1/projects/test-id/analyze")
        assert resp.status_code == 202
        body = resp.json()
        assert "job_id" in body
        assert body["status"] == "queued"

    @pytest.mark.asyncio
    async def test_analyze_status(self, client: AsyncClient) -> None:
        """GET /projects/{id}/analyze/status should return 200 with status."""
        resp = await client.get("/api/v1/projects/test-id/analyze/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert "job_id" in body

    @pytest.mark.asyncio
    async def test_create_multiple_projects(self, client: AsyncClient) -> None:
        """Multiple projects should all be listed."""
        for i in range(3):
            await client.post(
                "/api/v1/projects",
                json={"name": f"Projet {i}", "brief": _SAMPLE_BRIEF},
            )
        resp = await client.get("/api/v1/projects")
        assert resp.status_code == 200
        assert len(resp.json()) == 3
