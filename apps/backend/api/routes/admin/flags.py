from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models.feature_flags import FeatureFlagRow
from db.session import SessionDep
from schemas.feature_flag import FeatureFlagRead, FeatureFlagUpdate

router = APIRouter(prefix="/admin/feature-flags", tags=["admin"])


@router.get("", response_model=list[FeatureFlagRead])
async def list_flags(session: SessionDep) -> list[FeatureFlagRow]:
    result = await session.execute(select(FeatureFlagRow).order_by(FeatureFlagRow.key))
    return list(result.scalars().all())


@router.put("/{key}", response_model=FeatureFlagRead)
async def upsert_flag(
    key: str,
    payload: FeatureFlagUpdate,
    session: SessionDep,
) -> FeatureFlagRow:
    values = {
        "key": key,
        "enabled_globally": payload.enabled_globally if payload.enabled_globally is not None else False,
        "enabled_for_user_ids": payload.enabled_for_user_ids or [],
        "description": payload.description,
    }
    update_cols = {k: v for k, v in values.items() if k != "key" and v is not None or k == "enabled_globally"}

    stmt = (
        pg_insert(FeatureFlagRow)
        .values(**values)
        .on_conflict_do_update(index_elements=["key"], set_=update_cols)
        .returning(FeatureFlagRow)
    )
    result = await session.execute(stmt)
    await session.commit()
    return result.scalar_one()
