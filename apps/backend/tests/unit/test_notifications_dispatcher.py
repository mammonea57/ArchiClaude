from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest


@pytest.mark.asyncio
async def test_notify_creates_in_app_row_and_respects_email_pref(monkeypatch):
    from core.notifications import dispatcher, email_sender
    # Stub email_sender.send to track calls
    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(email_sender, "send", send_mock)

    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    # Preferences stub: email_project_analyzed = True
    class StubPrefs:
        email_project_analyzed = True
    async def fake_get_or_create(session, user_id):
        return StubPrefs()
    monkeypatch.setattr("core.notifications.preferences.get_or_create", fake_get_or_create)

    await dispatcher.notify(
        session=session,
        user_id=uuid4(),
        type="project_analyzed",
        title="Analyse OK",
        body="X",
        email_to="u@test.fr",
        email_vars={"project_name": "P", "project_id": "1"},
    )

    session.add.assert_called_once()
    send_mock.assert_called_once()


@pytest.mark.asyncio
async def test_notify_skips_email_when_pref_false(monkeypatch):
    from core.notifications import dispatcher, email_sender
    send_mock = AsyncMock(return_value=True)
    monkeypatch.setattr(email_sender, "send", send_mock)

    session = MagicMock()
    session.add = MagicMock()
    session.flush = AsyncMock()

    class StubPrefs:
        email_project_analyzed = False
    async def fake_get_or_create(session, user_id):
        return StubPrefs()
    monkeypatch.setattr("core.notifications.preferences.get_or_create", fake_get_or_create)

    await dispatcher.notify(
        session=session,
        user_id=uuid4(),
        type="project_analyzed",
        title="Analyse OK",
        email_to="u@test.fr",
    )

    send_mock.assert_not_called()
