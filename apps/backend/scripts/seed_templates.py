"""Load all templates from core/templates_library/seed/*.json into Postgres with OpenAI embeddings."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

# Resolve paths relative to this script's location
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
SEED_DIR = BACKEND_DIR / "core" / "templates_library" / "seed"

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+asyncpg://archiclaude:archiclaude@localhost:5432/archiclaude",
)


def _build_description(data: dict) -> str:
    """Build a plain-text description of a template for embedding."""
    parts = [
        f"Typologie: {data.get('typologie', '')}",
        f"Source: {data.get('source', '')}",
    ]
    if shab := data.get("surface_shab_range"):
        parts.append(f"Surface SHAB: {shab}")
    if orient := data.get("orientation_compatible"):
        parts.append(f"Orientation: {', '.join(orient) if isinstance(orient, list) else orient}")
    if pos := data.get("position_dans_etage"):
        parts.append(f"Position: {pos}")
    if tags := data.get("tags"):
        parts.append(f"Tags: {', '.join(tags) if isinstance(tags, list) else tags}")
    if topo := data.get("topologie"):
        pieces = list(topo.keys()) if isinstance(topo, dict) else []
        if pieces:
            parts.append(f"Pièces: {', '.join(pieces)}")
    return ". ".join(parts)


async def seed() -> None:
    """Main entry-point: load seed JSON files and upsert into templates table."""
    # Resolve OpenAI client or fall back to mock embeddings
    api_key = os.environ.get("OPENAI_API_KEY")
    use_mock = not api_key
    openai_client = None

    if use_mock:
        print("WARNING: OPENAI_API_KEY not set, using zero-mock embeddings")  # noqa: T201
    else:
        from openai import OpenAI  # imported lazily so the module loads without the key
        openai_client = OpenAI(api_key=api_key)

    # Import ORM model after path is set up
    import sys
    sys.path.insert(0, str(BACKEND_DIR))
    from db.models.templates import TemplateRow  # noqa: F401 — needed to register table

    engine = create_async_engine(DATABASE_URL, poolclass=NullPool, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

    seed_files = sorted(SEED_DIR.glob("*.json"))
    if not seed_files:
        print(f"No seed files found in {SEED_DIR}")  # noqa: T201
        await engine.dispose()
        return

    print(f"Found {len(seed_files)} seed file(s): {[f.name for f in seed_files]}")  # noqa: T201

    async with session_factory() as session:
        for path in seed_files:
            data = json.loads(path.read_text(encoding="utf-8"))
            template_id: str = data.get("id") or path.stem
            typologie: str = data.get("typologie", "")
            source: str = data.get("source", "manual")

            description = _build_description(data)

            if use_mock:
                embedding: list[float] = [0.0] * 1536
            else:
                emb_response = openai_client.embeddings.create(  # type: ignore[union-attr]
                    model="text-embedding-3-small",
                    input=description,
                    dimensions=1536,
                )
                embedding = emb_response.data[0].embedding

            stmt = (
                insert(TemplateRow)
                .values(
                    id=template_id,
                    typologie=typologie,
                    source=source,
                    json_data=data,
                    embedding=embedding,
                )
                .on_conflict_do_update(
                    index_elements=["id"],
                    set_={
                        "json_data": data,
                        "embedding": embedding,
                        "typologie": typologie,
                        "source": source,
                    },
                )
            )
            await session.execute(stmt)
            print(f"  Upserted template '{template_id}' ({typologie})")  # noqa: T201

        await session.commit()

    await engine.dispose()
    print("Done.")  # noqa: T201


if __name__ == "__main__":
    asyncio.run(seed())
