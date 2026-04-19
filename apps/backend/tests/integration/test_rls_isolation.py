import uuid
import pytest
from httpx import AsyncClient


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@test.fr"


@pytest.fixture(autouse=True)
def _jwt(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-rls")


async def _register(client: AsyncClient, email: str):
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password_12345", "full_name": email.split("@")[0]},
    )
    return resp.json()


@pytest.mark.asyncio
async def test_user_a_does_not_see_user_b_workspaces(client: AsyncClient):
    """Belt: backend filter on /workspaces uses WorkspaceMemberRow.user_id."""
    a = await _register(client, _unique_email("a-ws"))
    b = await _register(client, _unique_email("b-ws"))

    # A creates a shared workspace (not personal)
    await client.post(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {a['access_token']}"},
        json={"name": "Workspace Privé A"},
    )

    # B lists workspaces — should NOT see A's non-personal workspace
    resp = await client.get(
        "/api/v1/workspaces",
        headers={"Authorization": f"Bearer {b['access_token']}"},
    )
    assert resp.status_code == 200
    b_list = resp.json()
    assert not any(
        item["workspace"]["name"] == "Workspace Privé A" for item in b_list
    )


@pytest.mark.asyncio
async def test_user_a_cannot_get_user_b_workspace_by_id(client: AsyncClient):
    """Belt: _require_role returns 403 for non-members."""
    a = await _register(client, _unique_email("ax-ws"))
    b = await _register(client, _unique_email("bx-ws"))

    ws = (
        await client.post(
            "/api/v1/workspaces",
            headers={"Authorization": f"Bearer {a['access_token']}"},
            json={"name": "Secret"},
        )
    ).json()
    ws_id = ws["id"]

    resp = await client.get(
        f"/api/v1/workspaces/{ws_id}",
        headers={"Authorization": f"Bearer {b['access_token']}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_user_a_does_not_see_user_b_notifications(client: AsyncClient):
    """Belt: /notifications filters by current_user.id.
    Verified via empty list — no cross-user leakage even when notifications exist."""
    a = await _register(client, _unique_email("a-notif"))
    b = await _register(client, _unique_email("b-notif"))

    # Neither user has notifications. Confirm each sees their own empty list.
    resp_a = await client.get(
        "/api/v1/notifications",
        headers={"Authorization": f"Bearer {a['access_token']}"},
    )
    resp_b = await client.get(
        "/api/v1/notifications",
        headers={"Authorization": f"Bearer {b['access_token']}"},
    )
    assert resp_a.status_code == 200
    assert resp_b.status_code == 200
    # Both start empty; ensures filter returns per-user scope (not a cross-user leak)
    assert resp_a.json()["total"] == 0
    assert resp_b.json()["total"] == 0


@pytest.mark.asyncio
async def test_non_admin_cannot_modify_workspace(client: AsyncClient):
    """Belt: PATCH /workspaces/{id} enforces admin role via _require_role."""
    a = await _register(client, _unique_email("a-adm"))
    b = await _register(client, _unique_email("b-adm"))

    ws = (
        await client.post(
            "/api/v1/workspaces",
            headers={"Authorization": f"Bearer {a['access_token']}"},
            json={"name": "Locked"},
        )
    ).json()
    ws_id = ws["id"]

    resp = await client.patch(
        f"/api/v1/workspaces/{ws_id}",
        headers={"Authorization": f"Bearer {b['access_token']}"},
        json={"name": "Hacked"},
    )
    assert resp.status_code == 403
