from collections.abc import AsyncIterator

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from api.main import create_app
from db.session import get_session

DATABASE_URL = "postgresql+asyncpg://archiclaude:archiclaude@localhost:5432/archiclaude"


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    # Use NullPool so each test gets fresh connections on the current event loop.
    engine = create_async_engine(DATABASE_URL, poolclass=NullPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    async def override_get_session() -> AsyncIterator[AsyncSession]:
        async with session_factory() as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = override_get_session
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    await engine.dispose()
