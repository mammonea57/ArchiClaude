"""Integration tests for /api/v1/feasibility/{id}/report.* and /api/v1/reports/* endpoints."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


class TestReportEndpoints:
    @pytest.mark.asyncio
    async def test_html_report_200(self, client: AsyncClient) -> None:
        """GET /feasibility/{id}/report.html should return 200 with text/html content."""
        result_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/feasibility/{result_id}/report.html")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    @pytest.mark.asyncio
    async def test_html_report_contains_project_name(self, client: AsyncClient) -> None:
        """HTML report body should include the project name derived from result_id."""
        result_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/feasibility/{result_id}/report.html")
        assert resp.status_code == 200
        # The renderer uses the first 8 chars of result_id in the project name
        assert result_id[:8] in resp.text

    @pytest.mark.asyncio
    async def test_pdf_report_202(self, client: AsyncClient) -> None:
        """POST /feasibility/{id}/report.pdf should return 202 with a job_id."""
        result_id = str(uuid.uuid4())
        resp = await client.post(f"/api/v1/feasibility/{result_id}/report.pdf")
        assert resp.status_code == 202
        body = resp.json()
        assert "job_id" in body
        assert body["status"] == "queued"
        # job_id should be a valid UUID
        uuid.UUID(body["job_id"])

    @pytest.mark.asyncio
    async def test_download_report(self, client: AsyncClient) -> None:
        """GET /reports/{id}/download should return 200 with a url field."""
        report_id = str(uuid.uuid4())
        resp = await client.get(f"/api/v1/reports/{report_id}/download")
        assert resp.status_code == 200
        body = resp.json()
        assert "url" in body
        assert report_id in body["url"]
