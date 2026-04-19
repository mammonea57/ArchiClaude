import uuid

import pytest
from httpx import AsyncClient


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@test.fr"


@pytest.fixture(autouse=True)
def _jwt(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-tpl")


@pytest.mark.asyncio
async def test_list_templates(client: AsyncClient):
    user = (await client.post("/api/v1/auth/register",
        json={"email": _unique_email("tpl"), "password": "password_12345", "full_name": "x"})).json()
    token = user["access_token"]
    resp = await client.get("/api/v1/templates",
        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    # Tests assume DB seeded with 5 templates from Task 13
    assert data["total"] >= 5


@pytest.mark.asyncio
async def test_list_templates_filter_by_typologie(client: AsyncClient):
    user = (await client.post("/api/v1/auth/register",
        json={"email": _unique_email("tpl2"), "password": "password_12345", "full_name": "x"})).json()
    token = user["access_token"]
    resp = await client.get("/api/v1/templates?typologie=T3",
        headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    data = resp.json()
    for item in data["items"]:
        assert item["typologie"] == "T3"
