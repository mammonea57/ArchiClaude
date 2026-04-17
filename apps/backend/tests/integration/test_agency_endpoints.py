"""Integration tests for /api/v1/agency endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


class TestAgencyEndpoints:
    @pytest.mark.asyncio
    async def test_get_settings(self, client: AsyncClient) -> None:
        """GET /agency/settings should return 200 with agency settings shape."""
        resp = await client.get("/api/v1/agency/settings")
        assert resp.status_code == 200
        body = resp.json()
        assert "agency_name" in body
        assert "logo_url" in body
        assert "contact_email" in body
        assert "brand_primary_color" in body

    @pytest.mark.asyncio
    async def test_update_settings(self, client: AsyncClient) -> None:
        """PUT /agency/settings should return 200 and echo back provided values."""
        resp = await client.put(
            "/api/v1/agency/settings",
            json={
                "agency_name": "Cabinet Test",
                "contact_email": "contact@test.fr",
                "brand_primary_color": "#FF5A00",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["agency_name"] == "Cabinet Test"
        assert body["contact_email"] == "contact@test.fr"
        assert body["brand_primary_color"] == "#FF5A00"

    @pytest.mark.asyncio
    async def test_update_settings_partial(self, client: AsyncClient) -> None:
        """PUT /agency/settings with partial data should not raise errors."""
        resp = await client.put(
            "/api/v1/agency/settings",
            json={"agency_name": "Partiel"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["agency_name"] == "Partiel"

    @pytest.mark.asyncio
    async def test_upload_logo(self, client: AsyncClient) -> None:
        """POST /agency/logo should return 200 with a logo_url field."""
        resp = await client.post("/api/v1/agency/logo")
        assert resp.status_code == 200
        body = resp.json()
        assert "logo_url" in body
