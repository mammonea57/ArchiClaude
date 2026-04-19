import uuid

import pytest
from httpx import AsyncClient


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@test.fr"


@pytest.fixture(autouse=True)
def _set_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration")


async def _register(client: AsyncClient, prefix: str) -> tuple[str, str, str]:
    email = _unique_email(prefix)
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password_12345", "full_name": prefix},
    )
    assert resp.status_code == 201
    data = resp.json()
    return email, data["access_token"], data["user"]["id"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_workspace(client: AsyncClient):
    _, token, _ = await _register(client, "wscreate")
    resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Agence Test", "description": "desc"},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["name"] == "Agence Test"
    assert data["is_personal"] is False

    # Creator should be admin — verified via list
    list_resp = await client.get("/api/v1/workspaces", headers=_auth(token))
    assert list_resp.status_code == 200
    items = list_resp.json()
    created = next(
        (it for it in items if it["workspace"]["id"] == data["id"]), None
    )
    assert created is not None
    assert created["role"] == "admin"


@pytest.mark.asyncio
async def test_list_workspaces_includes_personal(client: AsyncClient):
    _, token, _ = await _register(client, "wslist")
    resp = await client.get("/api/v1/workspaces", headers=_auth(token))
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 1
    assert any(it["workspace"]["is_personal"] is True for it in items)


@pytest.mark.asyncio
async def test_cannot_delete_personal_workspace(client: AsyncClient):
    _, token, _ = await _register(client, "wspersonal")
    list_resp = await client.get("/api/v1/workspaces", headers=_auth(token))
    personal = next(
        it for it in list_resp.json() if it["workspace"]["is_personal"] is True
    )
    ws_id = personal["workspace"]["id"]
    resp = await client.delete(
        f"/api/v1/workspaces/{ws_id}", headers=_auth(token)
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_non_admin_cannot_modify(client: AsyncClient):
    _, token_a, _ = await _register(client, "wsadmin")
    _, token_b, _ = await _register(client, "wsintruder")

    create_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Agence A"},
        headers=_auth(token_a),
    )
    assert create_resp.status_code == 201
    ws_id = create_resp.json()["id"]

    # User B has no membership — PATCH must 403
    resp = await client.patch(
        f"/api/v1/workspaces/{ws_id}",
        json={"name": "Hacked"},
        headers=_auth(token_b),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_list_members_includes_creator(client: AsyncClient):
    email, token, user_id = await _register(client, "wsmem")
    create_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Agence Members"},
        headers=_auth(token),
    )
    ws_id = create_resp.json()["id"]

    resp = await client.get(
        f"/api/v1/workspaces/{ws_id}/members", headers=_auth(token)
    )
    assert resp.status_code == 200
    members = resp.json()
    assert len(members) == 1
    assert members[0]["email"] == email
    assert members[0]["role"] == "admin"
    assert members[0]["user_id"] == user_id


@pytest.mark.asyncio
async def test_admin_can_update_workspace(client: AsyncClient):
    _, token, _ = await _register(client, "wsupd")
    create_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Old Name"},
        headers=_auth(token),
    )
    ws_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/workspaces/{ws_id}",
        json={"name": "New Name"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "New Name"
