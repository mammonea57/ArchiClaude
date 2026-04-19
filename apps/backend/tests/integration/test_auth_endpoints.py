import uuid

import pytest
from httpx import AsyncClient


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@test.fr"


@pytest.fixture(autouse=True)
def _set_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration")


@pytest.mark.asyncio
async def test_register_creates_user_and_workspace(client: AsyncClient):
    email = _unique_email("newuser")
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password_12345", "full_name": "New User"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["user"]["email"] == email
    assert "access_token" in data
    assert "default_workspace_id" in data


@pytest.mark.asyncio
async def test_register_duplicate_email_conflict(client: AsyncClient):
    email = _unique_email("dup")
    payload = {"email": email, "password": "password_12345", "full_name": "X"}
    r1 = await client.post("/api/v1/auth/register", json=payload)
    assert r1.status_code == 201
    r2 = await client.post("/api/v1/auth/register", json=payload)
    assert r2.status_code == 409


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient):
    email = _unique_email("login")
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password_12345", "full_name": "L"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password_12345"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_login_wrong_password(client: AsyncClient):
    email = _unique_email("pw")
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "correct_pass_1", "full_name": "X"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "wrong_pass"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_with_valid_token(client: AsyncClient):
    email = _unique_email("me")
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password_12345", "full_name": "Me"},
    )
    token = reg.json()["access_token"]
    resp = await client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == email


@pytest.mark.asyncio
async def test_oauth_callback_new_user(client: AsyncClient):
    email = _unique_email("oauth")
    provider_sub = f"google-sub-{uuid.uuid4().hex[:10]}"
    resp = await client.post(
        "/api/v1/auth/oauth/callback",
        json={
            "provider": "google",
            "email": email,
            "name": "OAuth User",
            "provider_user_id": provider_sub,
        },
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["email"] == email


@pytest.mark.asyncio
async def test_oauth_callback_existing_user_by_provider(client: AsyncClient):
    email = _unique_email("oauth2")
    provider_sub = f"google-sub-{uuid.uuid4().hex[:10]}"
    payload = {
        "provider": "google",
        "email": email,
        "name": "X",
        "provider_user_id": provider_sub,
    }
    r1 = await client.post("/api/v1/auth/oauth/callback", json=payload)
    uid1 = r1.json()["user"]["id"]
    r2 = await client.post("/api/v1/auth/oauth/callback", json=payload)
    uid2 = r2.json()["user"]["id"]
    assert uid1 == uid2
