import uuid

import pytest
from httpx import AsyncClient


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@test.fr"


@pytest.fixture(autouse=True)
def _jwt(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-notif")


async def _register(client, email):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password_12345", "full_name": email},
    )
    return resp.json()


@pytest.mark.asyncio
async def test_list_notifications_empty(client: AsyncClient):
    reg = await _register(client, _unique_email("notif-empty"))
    token = reg["access_token"]
    resp = await client.get(
        "/api/v1/notifications",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert data["total"] == 0
    assert data["unread"] == 0


@pytest.mark.asyncio
async def test_unread_count(client: AsyncClient):
    reg = await _register(client, _unique_email("notif-count"))
    token = reg["access_token"]
    resp = await client.get(
        "/api/v1/notifications/unread-count",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 0


@pytest.mark.asyncio
async def test_get_default_preferences(client: AsyncClient):
    reg = await _register(client, _unique_email("notif-prefs"))
    token = reg["access_token"]
    resp = await client.get(
        "/api/v1/account/notifications",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["in_app_enabled"] is True
    assert data["email_workspace_invitations"] is True
    assert data["email_comments"] is False  # default False


@pytest.mark.asyncio
async def test_update_preferences(client: AsyncClient):
    reg = await _register(client, _unique_email("notif-update"))
    token = reg["access_token"]
    resp = await client.patch(
        "/api/v1/account/notifications",
        headers={"Authorization": f"Bearer {token}"},
        json={"email_workspace_invitations": False, "email_weekly_digest": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["email_workspace_invitations"] is False
    assert data["email_weekly_digest"] is True
    assert data["email_project_analyzed"] is True  # unchanged
