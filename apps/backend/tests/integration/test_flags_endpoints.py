import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

DATABASE_URL = "postgresql+asyncpg://archiclaude:archiclaude@localhost:5432/archiclaude"


@pytest.fixture(autouse=True)
async def _reset_flags() -> None:
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text("TRUNCATE TABLE feature_flags"))
    await engine.dispose()


@pytest.mark.asyncio
async def test_list_flags_empty_initially(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/admin/feature-flags")
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_put_flag_creates_if_missing(client: AsyncClient) -> None:
    resp = await client.put(
        "/api/v1/admin/feature-flags/enable_oblique_gabarit",
        json={"enabled_globally": True, "description": "Calcul gabarit oblique précis"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["key"] == "enable_oblique_gabarit"
    assert body["enabled_globally"] is True
    assert body["enabled_for_user_ids"] == []
    assert body["description"] == "Calcul gabarit oblique précis"


@pytest.mark.asyncio
async def test_put_flag_updates_if_exists(client: AsyncClient) -> None:
    await client.put(
        "/api/v1/admin/feature-flags/use_paris_bioclim_parser",
        json={"enabled_globally": False},
    )
    resp = await client.put(
        "/api/v1/admin/feature-flags/use_paris_bioclim_parser",
        json={"enabled_globally": True},
    )
    assert resp.status_code == 200
    assert resp.json()["enabled_globally"] is True


@pytest.mark.asyncio
async def test_list_returns_created_flag(client: AsyncClient) -> None:
    await client.put(
        "/api/v1/admin/feature-flags/flag_a",
        json={"enabled_globally": True},
    )
    await client.put(
        "/api/v1/admin/feature-flags/flag_b",
        json={"enabled_globally": False},
    )
    resp = await client.get("/api/v1/admin/feature-flags")
    assert resp.status_code == 200
    keys = [f["key"] for f in resp.json()]
    assert set(keys) == {"flag_a", "flag_b"}
