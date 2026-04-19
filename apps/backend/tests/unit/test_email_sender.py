from unittest.mock import MagicMock, patch

import pytest

from core.notifications.email_sender import _render, send


def test_render_workspace_invitation():
    subject, html = _render("workspace_invitation", {
        "workspace_name": "TeamX",
        "invited_by_email": "admin@test.fr",
        "token": "abc",
    })
    assert "TeamX" in subject
    assert "admin@test.fr" in html
    assert "abc" in html


def test_render_project_analyzed():
    subject, html = _render("project_analyzed", {
        "project_name": "Projet Lyon",
        "project_id": "123",
    })
    assert "Projet Lyon" in subject
    assert "Projet Lyon" in html


@pytest.mark.asyncio
async def test_send_without_api_key_returns_false(monkeypatch):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    result = await send(to="x@test.fr", template="workspace_invitation", variables={
        "workspace_name": "X", "invited_by_email": "a@test.fr", "token": "t",
    })
    assert result is False


@pytest.mark.asyncio
async def test_send_with_api_key_calls_resend(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    with patch("resend.Emails") as mock_emails:
        mock_emails.send = MagicMock()
        result = await send(to="x@test.fr", template="workspace_invitation", variables={
            "workspace_name": "X", "invited_by_email": "a@test.fr", "token": "t",
        })
        assert result is True
        assert mock_emails.send.called
