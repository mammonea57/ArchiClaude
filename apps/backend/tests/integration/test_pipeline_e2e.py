# apps/backend/tests/integration/test_pipeline_e2e.py
import os

import pytest
import pytest_asyncio
from uuid import uuid4

from core.building_model.pipeline import generate_building_model, GenerationInputs
from core.feasibility.schemas import Brief
from core.plu.schemas import NumericRules
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

pytestmark = pytest.mark.skipif(
    not os.environ.get("OPENAI_API_KEY") or not os.environ.get("RUN_INTEGRATION_TESTS"),
    reason="Requires OPENAI_API_KEY and RUN_INTEGRATION_TESTS=1 + seeded DB",
)


@pytest.mark.asyncio
async def test_pipeline_generates_valid_building_model(session: AsyncSession):
    inputs = GenerationInputs(
        project_id=uuid4(),
        parcelle_geojson={"type": "Polygon", "coordinates": [[[0,0],[20,0],[20,18],[0,18],[0,0]]]},
        parcelle_surface_m2=360.0,
        voirie_orientations=["sud"],
        north_angle_deg=0.0,
        plu_rules=NumericRules(
            emprise_max_pct=40.0, hauteur_max_m=18.0,
            pleine_terre_min_pct=30.0, retrait_voirie_m=None,
            retrait_limite_m=4.0, stationnement_pct=100.0,
            hauteur_max_niveaux=5,
        ),
        zone_plu="UA",
        brief=Brief(
            destination="logements",
            cible_nb_logements=12, cible_sdp_m2=900,
            mix_typologique={"T2": 0.4, "T3": 0.4, "T4": 0.2},
        ),
        footprint_recommande_geojson={"type": "Polygon", "coordinates": [[[2,2],[16,2],[16,14],[2,14],[2,2]]]},
        niveaux_recommandes=4,
        hauteur_recommandee_m=12.0,
        emprise_pct_recommandee=40.0,
    )
    bm = await generate_building_model(inputs, session=session)
    assert bm.metadata.project_id == inputs.project_id
    assert bm.envelope.niveaux == 4
    assert len(bm.niveaux) == 4
    # At least some apartments placed
    total_logements = sum(
        1 for niv in bm.niveaux for c in niv.cellules if c.type.value == "logement"
    )
    assert total_logements >= 6  # some reasonable count for 4 floors × 12 logements target
    # Conformite check exists
    assert bm.conformite_check is not None


@pytest_asyncio.fixture
async def session():
    engine = create_async_engine(
        "postgresql+asyncpg://archiclaude:archiclaude@localhost:5432/archiclaude"
    )
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with session_factory() as sess:
        yield sess
    await engine.dispose()
