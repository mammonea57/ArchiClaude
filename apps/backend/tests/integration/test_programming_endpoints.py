"""Integration tests for /api/v1/projects/{id}/program and related endpoints.

Tests use the conftest ``client`` fixture (ASGI transport, real DB).
All endpoints are v1 stubs so no external calls are made.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient


class TestProgrammingEndpoints:
    @pytest.mark.asyncio
    async def test_start_programming_202(self, client: AsyncClient) -> None:
        """POST /projects/{id}/program should return 202 with job_id."""
        resp = await client.post("/api/v1/projects/test-id/program")
        assert resp.status_code == 202
        body = resp.json()
        assert "job_id" in body
        assert body["status"] == "queued"

    @pytest.mark.asyncio
    async def test_status(self, client: AsyncClient) -> None:
        """GET /projects/{id}/program/status should return 200 with status."""
        resp = await client.get("/api/v1/projects/test-id/program/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body

    @pytest.mark.asyncio
    async def test_scenarios_list(self, client: AsyncClient) -> None:
        """GET /projects/{id}/scenarios should return 200 with scenarios list."""
        resp = await client.get("/api/v1/projects/test-id/scenarios")
        assert resp.status_code == 200
        body = resp.json()
        assert "scenarios" in body
        assert isinstance(body["scenarios"], list)

    @pytest.mark.asyncio
    async def test_scenario_by_name(self, client: AsyncClient) -> None:
        """GET /projects/{id}/scenarios/{nom} should return scenario placeholder."""
        resp = await client.get("/api/v1/projects/test-id/scenarios/optimiste")
        assert resp.status_code == 200
        body = resp.json()
        assert body["nom"] == "optimiste"

    @pytest.mark.asyncio
    async def test_plan_svg(self, client: AsyncClient) -> None:
        """GET /projects/{id}/plans/masse should return SVG content."""
        resp = await client.get("/api/v1/projects/test-id/plans/masse")
        assert resp.status_code == 200
        assert "svg" in resp.headers.get("content-type", "")

    @pytest.mark.asyncio
    async def test_plan_dxf(self, client: AsyncClient) -> None:
        """GET /projects/{id}/plans/masse/dxf should return DXF attachment."""
        resp = await client.get("/api/v1/projects/test-id/plans/masse/dxf")
        assert resp.status_code == 200
        assert "dxf" in resp.headers.get("content-type", "")
        assert "masse.dxf" in resp.headers.get("content-disposition", "")
