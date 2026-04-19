# apps/backend/tests/integration/test_template_selector.py
import os

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from core.building_model.schemas import Typologie
from core.building_model.solver import ApartmentSlot
from core.templates_library.selector import TemplateSelector
from shapely.geometry import Polygon

pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY") or not os.environ.get("RUN_INTEGRATION_TESTS"),
    reason="Requires OPENAI_API_KEY and RUN_INTEGRATION_TESTS=1 + seeded DB",
)


@pytest.mark.asyncio
async def test_selector_returns_compatible_template_for_t3(session: AsyncSession):
    """Requires seeded DB — skip if empty."""
    slot = ApartmentSlot(
        id="s_test_t3", polygon=Polygon([(0,0),(8,0),(8,10),(0,10)]),
        surface_m2=68.0, target_typologie=Typologie.T3,
        orientations=["sud", "nord"], position_in_floor="milieu",
    )
    selector = TemplateSelector(session=session)
    result = await selector.select_for_slot(slot)
    assert result is not None
    assert result.template.typologie == "T3"
    assert 60 <= result.template.surface_shab_range[0]


@pytest.mark.asyncio
async def test_selector_returns_none_for_impossible_typo(session: AsyncSession):
    slot = ApartmentSlot(
        id="s_test_x", polygon=Polygon([(0,0),(3,0),(3,3),(0,3)]),
        surface_m2=9.0, target_typologie=Typologie.T5,  # T5 can't fit in 9m²
        orientations=["sud"], position_in_floor="milieu",
    )
    selector = TemplateSelector(session=session)
    result = await selector.select_for_slot(slot)
    # Either returns nothing or returns a template tagged fallback-needed
    # Implementation returns None to signal "no compatible template"
    assert result is None or result.confidence < 0.5


@pytest_asyncio.fixture
async def session():
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    engine = create_async_engine(
        "postgresql+asyncpg://archiclaude:archiclaude@localhost:5432/archiclaude"
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as sess:
        yield sess
    await engine.dispose()
