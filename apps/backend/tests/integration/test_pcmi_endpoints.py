"""Integration tests for /api/v1/projects/{project_id}/pcmi endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

_PROJECT_ID = "00000000-0000-0000-0000-000000000001"


class TestPcmiEndpoints:
    @pytest.mark.asyncio
    async def test_generate_returns_202(self, client: AsyncClient) -> None:
        """POST /projects/{id}/pcmi/generate should return 202 with job_id and status."""
        resp = await client.post(f"/api/v1/projects/{_PROJECT_ID}/pcmi/generate")
        assert resp.status_code == 202
        body = resp.json()
        assert "job_id" in body
        assert body["status"] == "queued"

    @pytest.mark.asyncio
    async def test_status(self, client: AsyncClient) -> None:
        """GET /projects/{id}/pcmi/status should return 200 with a status field."""
        resp = await client.get(f"/api/v1/projects/{_PROJECT_ID}/pcmi/status")
        assert resp.status_code == 200
        body = resp.json()
        assert "status" in body
        assert body["status"] == "not_generated"

    @pytest.mark.asyncio
    async def test_piece_svg(self, client: AsyncClient) -> None:
        """GET /projects/{id}/pcmi/PCMI1 should return SVG content-type."""
        resp = await client.get(f"/api/v1/projects/{_PROJECT_ID}/pcmi/PCMI1")
        assert resp.status_code == 200
        assert "image/svg+xml" in resp.headers["content-type"]
        assert "PCMI1" in resp.text

    @pytest.mark.asyncio
    async def test_piece_svg_contains_title(self, client: AsyncClient) -> None:
        """SVG response for PCMI4 should include the piece title."""
        resp = await client.get(f"/api/v1/projects/{_PROJECT_ID}/pcmi/PCMI4")
        assert resp.status_code == 200
        assert "Notice" in resp.text

    @pytest.mark.asyncio
    async def test_unknown_piece_404(self, client: AsyncClient) -> None:
        """GET /projects/{id}/pcmi/PCMI99 should return 404."""
        resp = await client.get(f"/api/v1/projects/{_PROJECT_ID}/pcmi/PCMI99")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_settings_update(self, client: AsyncClient) -> None:
        """PATCH /projects/{id}/pcmi/settings with map_base=planv2 should be accepted."""
        resp = await client.patch(
            f"/api/v1/projects/{_PROJECT_ID}/pcmi/settings",
            json={"map_base": "planv2"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["map_base"] == "planv2"

    @pytest.mark.asyncio
    async def test_settings_update_defaults_scan25(self, client: AsyncClient) -> None:
        """PATCH with no map_base should default to scan25."""
        resp = await client.patch(
            f"/api/v1/projects/{_PROJECT_ID}/pcmi/settings",
            json={},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["map_base"] == "scan25"

    @pytest.mark.asyncio
    async def test_dossier_pdf_placeholder(self, client: AsyncClient) -> None:
        """GET /projects/{id}/pcmi/dossier.pdf should return 200."""
        resp = await client.get(f"/api/v1/projects/{_PROJECT_ID}/pcmi/dossier.pdf")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_dossier_zip_placeholder(self, client: AsyncClient) -> None:
        """GET /projects/{id}/pcmi/dossier.zip should return 200."""
        resp = await client.get(f"/api/v1/projects/{_PROJECT_ID}/pcmi/dossier.zip")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_piece_pdf_placeholder(self, client: AsyncClient) -> None:
        """GET /projects/{id}/pcmi/PCMI2a/pdf should return 200 for known piece."""
        resp = await client.get(f"/api/v1/projects/{_PROJECT_ID}/pcmi/PCMI2a/pdf")
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_piece_pdf_unknown_404(self, client: AsyncClient) -> None:
        """GET /projects/{id}/pcmi/PCMI99/pdf should return 404."""
        resp = await client.get(f"/api/v1/projects/{_PROJECT_ID}/pcmi/PCMI99/pdf")
        assert resp.status_code == 404
