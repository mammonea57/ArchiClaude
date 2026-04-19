"""Integration tests for project status transitions + history endpoints."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


def _unique_email(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8]}@test.fr"


@pytest.fixture(autouse=True)
def _jwt(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-status")


async def _register_and_project(client: AsyncClient, prefix: str):
    reg = (
        await client.post(
            "/api/v1/auth/register",
            json={
                "email": _unique_email(prefix),
                "password": "password_12345",
                "full_name": "S",
            },
        )
    ).json()
    token = reg["access_token"]
    # /projects POST is currently unauthenticated (placeholder user). Pass minimal brief.
    proj = (
        await client.post(
            "/api/v1/projects",
            json={"name": "Test Project", "brief": {}},
        )
    ).json()
    return token, proj["id"]


@pytest.mark.asyncio
async def test_valid_transition_draft_to_analyzed(client: AsyncClient):
    token, pid = await _register_and_project(client, "valid")
    resp = await client.patch(
        f"/api/v1/projects/{pid}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "analyzed"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "analyzed"


@pytest.mark.asyncio
async def test_invalid_transition_draft_to_ready_for_pc(client: AsyncClient):
    token, pid = await _register_and_project(client, "invalid")
    resp = await client.patch(
        f"/api/v1/projects/{pid}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "ready_for_pc"},
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_status_history_tracks_changes(client: AsyncClient):
    token, pid = await _register_and_project(client, "hist")
    await client.patch(
        f"/api/v1/projects/{pid}/status",
        headers={"Authorization": f"Bearer {token}"},
        json={"status": "analyzed", "notes": "Analyse terminée"},
    )
    hist = (
        await client.get(
            f"/api/v1/projects/{pid}/status_history",
            headers={"Authorization": f"Bearer {token}"},
        )
    ).json()
    assert len(hist["items"]) >= 1
    assert hist["items"][0]["to_status"] == "analyzed"
    assert hist["items"][0]["notes"] == "Analyse terminée"


@pytest.mark.asyncio
async def test_status_transition_requires_auth(client: AsyncClient):
    _, pid = await _register_and_project(client, "noauth")
    resp = await client.patch(
        f"/api/v1/projects/{pid}/status",
        json={"status": "analyzed"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_archived_to_draft_allowed(client: AsyncClient):
    token, pid = await _register_and_project(client, "arch")
    h = {"Authorization": f"Bearer {token}"}
    r1 = await client.patch(
        f"/api/v1/projects/{pid}/status", headers=h, json={"status": "archived"}
    )
    assert r1.status_code == 200
    r2 = await client.patch(
        f"/api/v1/projects/{pid}/status", headers=h, json={"status": "draft"}
    )
    assert r2.status_code == 200
