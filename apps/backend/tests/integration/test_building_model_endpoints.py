# apps/backend/tests/integration/test_building_model_endpoints.py
import os
import uuid

import pytest
from httpx import AsyncClient


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@test.fr"


@pytest.fixture(autouse=True)
def _jwt(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-bm")


async def _register(client: AsyncClient, email: str):
    return (await client.post("/api/v1/auth/register",
        json={"email": email, "password": "password_12345", "full_name": email})).json()


@pytest.mark.skipif(not os.environ.get("OPENAI_API_KEY"), reason="needs OPENAI_API_KEY")
@pytest.mark.asyncio
async def test_generate_building_model_e2e(client: AsyncClient):
    user = await _register(client, _unique_email("bm"))
    token = user["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create project — no auth required on POST /projects
    proj = (await client.post("/api/v1/projects",
        json={"name": "Test BM", "brief": {
            "destination": "logement_collectif",
            "cible_nb_logements": 12,
            "mix_typologique": {"T2": 0.5, "T3": 0.5},
        }}
    )).json()
    pid = proj["id"]

    # Generate BM
    resp = await client.post(f"/api/v1/projects/{pid}/building_model/generate",
        headers=headers, json={"commerces_rdc": False})
    assert resp.status_code == 201
    data = resp.json()
    assert data["version"] == 1
    assert data["project_id"] == pid
    assert "niveaux" in data["model_json"]

    # Get current
    resp2 = await client.get(f"/api/v1/projects/{pid}/building_model", headers=headers)
    assert resp2.status_code == 200
    assert resp2.json()["version"] == 1

    # List versions
    resp3 = await client.get(f"/api/v1/projects/{pid}/building_model/versions", headers=headers)
    assert resp3.status_code == 200
    assert len(resp3.json()["items"]) == 1


@pytest.mark.asyncio
async def test_get_building_model_404_when_none(client: AsyncClient):
    user = await _register(client, _unique_email("bm404"))
    token = user["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    # Create project — no auth required on POST /projects
    proj = (await client.post("/api/v1/projects",
        json={"name": "Empty BM", "brief": {}})).json()
    pid = proj["id"]

    resp = await client.get(f"/api/v1/projects/{pid}/building_model", headers=headers)
    assert resp.status_code == 404
