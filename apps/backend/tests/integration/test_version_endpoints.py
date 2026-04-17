"""Integration tests for /api/v1/projects/{id}/versions endpoints."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


class TestVersionEndpoints:
    @pytest.mark.asyncio
    async def test_create_version_201(self, client: AsyncClient) -> None:
        """POST /projects/{id}/versions should return 201 with version data."""
        project_id = str(uuid.uuid4())
        resp = await client.post(f"/api/v1/projects/{project_id}/versions")
        assert resp.status_code == 201
        body = resp.json()
        assert "id" in body
        assert "version_number" in body
        assert "created_at" in body
        # id should be a valid UUID
        uuid.UUID(body["id"])

    @pytest.mark.asyncio
    async def test_create_version_with_label(self, client: AsyncClient) -> None:
        """POST /projects/{id}/versions?label=... should echo the label."""
        project_id = str(uuid.uuid4())
        resp = await client.post(
            f"/api/v1/projects/{project_id}/versions",
            params={"label": "v1-initial"},
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["version_label"] == "v1-initial"

    @pytest.mark.asyncio
    async def test_list_versions(self, client: AsyncClient) -> None:
        """GET /projects/{id}/versions should return 200 with a list."""
        project_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/projects/{project_id}/versions")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_compare_versions(self, client: AsyncClient) -> None:
        """GET /projects/{id}/versions/compare?a=1&b=2 should return 200 with diff."""
        project_id = str(uuid.uuid4())
        resp = await client.get(
            f"/api/v1/projects/{project_id}/versions/compare",
            params={"a": 1, "b": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert "diff" in body
        assert isinstance(body["diff"], dict)
