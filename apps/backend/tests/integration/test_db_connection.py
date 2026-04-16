import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

DATABASE_URL = "postgresql+asyncpg://archiclaude:archiclaude@localhost:5432/archiclaude"


@pytest.fixture
async def db_engine():
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    yield engine
    await engine.dispose()


@pytest.mark.asyncio
async def test_database_is_reachable(db_engine) -> None:
    async with db_engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar() == 1


@pytest.mark.asyncio
async def test_postgis_extension_available(db_engine) -> None:
    async with db_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname='postgis'")
        )
        assert result.scalar() == "postgis"


@pytest.mark.asyncio
async def test_pgvector_extension_available(db_engine) -> None:
    async with db_engine.connect() as conn:
        result = await conn.execute(
            text("SELECT extname FROM pg_extension WHERE extname='vector'")
        )
        assert result.scalar() == "vector"
