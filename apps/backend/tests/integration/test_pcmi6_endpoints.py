import pytest
from httpx import AsyncClient


class TestRenderingEndpoints:
    @pytest.mark.asyncio
    async def test_materials_list(self, client: AsyncClient):
        resp = await client.get("/api/v1/rendering/materials")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 65
        assert len(data["items"]) == data["total"]

    @pytest.mark.asyncio
    async def test_quota(self, client: AsyncClient):
        resp = await client.get("/api/v1/rendering/quota")
        assert resp.status_code == 200
        data = resp.json()
        assert "credits_remaining" in data
        assert data["provider"] == "rerender"


class TestPcmi6Endpoints:
    @pytest.mark.asyncio
    async def test_create_render_202(self, client: AsyncClient):
        body = {
            "photo_source": "mapillary",
            "photo_source_id": "abc",
            "photo_base_url": "https://r2.example.com/p.jpg",
            "camera": {"lat": 48.85, "lng": 2.35, "heading": 90},
            "materials_config": {"facade": "enduit_blanc_lisse"},
        }
        resp = await client.post("/api/v1/projects/test-id/pcmi6/renders", json=body)
        assert resp.status_code == 202
        assert "render_id" in resp.json()

    @pytest.mark.asyncio
    async def test_list_renders(self, client: AsyncClient):
        resp = await client.get("/api/v1/projects/test-id/pcmi6/renders")
        assert resp.status_code == 200
        assert "items" in resp.json()

    @pytest.mark.asyncio
    async def test_get_render_not_found(self, client: AsyncClient):
        resp = await client.get("/api/v1/projects/test-id/pcmi6/renders/unknown")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_update_render(self, client: AsyncClient):
        resp = await client.patch(
            "/api/v1/projects/test-id/pcmi6/renders/r1",
            json={"label": "Variante enduit blanc", "selected_for_pc": True},
        )
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_render(self, client: AsyncClient):
        resp = await client.delete("/api/v1/projects/test-id/pcmi6/renders/r1")
        assert resp.status_code == 204

    @pytest.mark.asyncio
    async def test_regenerate_variants(self, client: AsyncClient):
        resp = await client.post(
            "/api/v1/projects/test-id/pcmi6/renders/r1/regenerate_variants",
        )
        assert resp.status_code == 202
        assert len(resp.json()["variant_jobs"]) == 3
