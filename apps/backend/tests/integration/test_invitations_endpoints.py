import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from db.models.workspace_invitations import WorkspaceInvitationRow

DATABASE_URL = (
    "postgresql+asyncpg://archiclaude:archiclaude@localhost:5432/archiclaude"
)


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@test.fr"


@pytest.fixture(autouse=True)
def _set_jwt_secret(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-integration")


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _register(
    client: AsyncClient, prefix: str, email: str | None = None
) -> tuple[str, str, str]:
    email = email or _unique_email(prefix)
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password_12345", "full_name": prefix},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    return email, data["access_token"], data["user"]["id"]


async def _get_invitation_token(email: str) -> str:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            inv = (
                await session.execute(
                    select(WorkspaceInvitationRow)
                    .where(
                        WorkspaceInvitationRow.email == email,
                        WorkspaceInvitationRow.accepted_at.is_(None),
                    )
                    .order_by(WorkspaceInvitationRow.created_at.desc())
                    .limit(1)
                )
            ).scalar_one()
            return inv.token
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_invite_and_list_pending(client: AsyncClient):
    _, admin_token, _ = await _register(client, "invadmin")
    ws_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Invite Agency"},
        headers=_auth(admin_token),
    )
    ws_id = ws_resp.json()["id"]

    invitee_email = _unique_email("invitee")
    inv_resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/invitations",
        json={"email": invitee_email, "role": "member"},
        headers=_auth(admin_token),
    )
    assert inv_resp.status_code == 201, inv_resp.text

    # Invitee registers with the invited email, then lists pending invitations
    _, invitee_token, _ = await _register(client, "invitee", email=invitee_email)
    mine = await client.get(
        "/api/v1/me/invitations", headers=_auth(invitee_token)
    )
    assert mine.status_code == 200
    items = mine.json()
    assert len(items) == 1
    assert items[0]["workspace_id"] == ws_id
    assert items[0]["role"] == "member"


@pytest.mark.asyncio
async def test_accept_invitation_idempotent(client: AsyncClient):
    _, admin_token, _ = await _register(client, "acceptadmin")
    ws_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Accept Agency"},
        headers=_auth(admin_token),
    )
    ws_id = ws_resp.json()["id"]

    invitee_email = _unique_email("accept")
    # Invitee registers first so we can authenticate
    _, invitee_token, invitee_user_id = await _register(
        client, "accept", email=invitee_email
    )

    inv_resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/invitations",
        json={"email": invitee_email, "role": "member"},
        headers=_auth(admin_token),
    )
    assert inv_resp.status_code == 201

    token = await _get_invitation_token(invitee_email)

    accept1 = await client.post(
        f"/api/v1/invitations/{token}/accept",
        headers=_auth(invitee_token),
    )
    assert accept1.status_code == 200, accept1.text
    assert accept1.json()["workspace_id"] == ws_id
    assert accept1.json()["role"] == "member"

    # Second accept should now return 400 (already accepted)
    accept2 = await client.post(
        f"/api/v1/invitations/{token}/accept",
        headers=_auth(invitee_token),
    )
    assert accept2.status_code == 400

    # Invitee should now see the workspace in their list
    my_ws = await client.get(
        "/api/v1/workspaces", headers=_auth(invitee_token)
    )
    assert my_ws.status_code == 200
    ids = [it["workspace"]["id"] for it in my_ws.json()]
    assert ws_id in ids


@pytest.mark.asyncio
async def test_accept_wrong_email_forbidden(client: AsyncClient):
    _, admin_token, _ = await _register(client, "wrongadmin")
    ws_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Wrong Email Agency"},
        headers=_auth(admin_token),
    )
    ws_id = ws_resp.json()["id"]

    target_email = _unique_email("target")
    inv_resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/invitations",
        json={"email": target_email, "role": "member"},
        headers=_auth(admin_token),
    )
    assert inv_resp.status_code == 201

    # Different user tries to accept
    _, other_token, _ = await _register(client, "other")
    token = await _get_invitation_token(target_email)
    resp = await client.post(
        f"/api/v1/invitations/{token}/accept",
        headers=_auth(other_token),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_decline_invitation(client: AsyncClient):
    _, admin_token, _ = await _register(client, "declineadmin")
    ws_resp = await client.post(
        "/api/v1/workspaces",
        json={"name": "Decline Agency"},
        headers=_auth(admin_token),
    )
    ws_id = ws_resp.json()["id"]

    invitee_email = _unique_email("decline")
    _, invitee_token, _ = await _register(
        client, "decline", email=invitee_email
    )
    inv_resp = await client.post(
        f"/api/v1/workspaces/{ws_id}/invitations",
        json={"email": invitee_email, "role": "viewer"},
        headers=_auth(admin_token),
    )
    assert inv_resp.status_code == 201
    token = await _get_invitation_token(invitee_email)

    resp = await client.post(
        f"/api/v1/invitations/{token}/decline",
        headers=_auth(invitee_token),
    )
    assert resp.status_code == 204

    # Invitation should no longer exist
    mine = await client.get(
        "/api/v1/me/invitations", headers=_auth(invitee_token)
    )
    assert mine.status_code == 200
    assert all(
        it["workspace_id"] != ws_id for it in mine.json()
    )
