"""Integration tests for PLU zone rules API endpoints (Task 10)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


class TestPluRulesEndpoints:
    @pytest.mark.asyncio
    async def test_extract_returns_202(self, client: AsyncClient) -> None:
        """POST /zone/{id}/extract returns 202 and a job_id."""
        resp = await client.post("/api/v1/plu/zone/test-zone-id/extract")
        assert resp.status_code == 202
        data = resp.json()
        assert "job_id" in data
        assert data["status"] == "queued"

    @pytest.mark.asyncio
    async def test_extract_job_id_is_uuid(self, client: AsyncClient) -> None:
        """job_id returned by extract endpoint should be a valid UUID string."""
        import uuid

        resp = await client.post("/api/v1/plu/zone/test-zone-id/extract")
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]
        # Should not raise
        uuid.UUID(job_id)

    @pytest.mark.asyncio
    async def test_status_returns_pending(self, client: AsyncClient) -> None:
        """GET /extract/status/{job_id} returns 200 with pending status."""
        resp = await client.get("/api/v1/plu/extract/status/fake-job-id")
        assert resp.status_code == 200
        data = resp.json()
        assert data["job_id"] == "fake-job-id"
        assert data["status"] == "pending"

    @pytest.mark.asyncio
    async def test_rules_not_found(self, client: AsyncClient) -> None:
        """GET /zone/{id}/rules returns 404 when rules not yet extracted."""
        resp = await client.get("/api/v1/plu/zone/unknown/rules")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_validate_returns_ok(self, client: AsyncClient) -> None:
        """POST /zone/{id}/validate returns 200."""
        resp = await client.post("/api/v1/plu/zone/test-id/validate")
        assert resp.status_code == 200
        assert resp.json()["status"] == "validated"

    @pytest.mark.asyncio
    async def test_feedback_returns_201(self, client: AsyncClient) -> None:
        """POST /rules/{id}/feedback returns 201."""
        resp = await client.post("/api/v1/plu/rules/test-id/feedback")
        assert resp.status_code == 201
        assert resp.json()["status"] == "recorded"

    @pytest.mark.asyncio
    async def test_extract_with_commune_insee_query(self, client: AsyncClient) -> None:
        """POST extract accepts optional commune_insee query param."""
        resp = await client.post(
            "/api/v1/plu/zone/test-zone-id/extract",
            params={"commune_insee": "75108"},
        )
        assert resp.status_code == 202
        assert "job_id" in resp.json()

    @pytest.mark.asyncio
    async def test_rules_with_commune_insee_query(self, client: AsyncClient) -> None:
        """GET rules accepts optional commune_insee query param (still 404)."""
        resp = await client.get(
            "/api/v1/plu/zone/unknown/rules",
            params={"commune_insee": "75108"},
        )
        assert resp.status_code == 404
