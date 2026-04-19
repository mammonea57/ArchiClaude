from fastapi import APIRouter, Query
from sqlalchemy import func, select

from api.deps import CurrentUserDep
from db.models.templates import TemplateRow
from db.session import SessionDep
from schemas.template_api import TemplateOut, TemplatesListOut


router = APIRouter(prefix="/templates", tags=["templates"])


def _to_out(row: TemplateRow) -> TemplateOut:
    data = row.json_data
    return TemplateOut(
        id=row.id, typologie=row.typologie, source=row.source,
        surface_shab_range=data.get("surface_shab_range", [0, 0]),
        orientation_compatible=data.get("orientation_compatible", []),
        position_dans_etage=data.get("position_dans_etage", []),
        tags=data.get("tags", []),
        preview_svg=row.preview_svg,
        rating_avg=float(row.rating_avg) if row.rating_avg is not None else None,
    )


@router.get("", response_model=TemplatesListOut)
async def list_templates(
    session: SessionDep,
    current_user: CurrentUserDep,
    typologie: str | None = Query(default=None),
) -> TemplatesListOut:
    stmt = select(TemplateRow)
    if typologie:
        stmt = stmt.where(TemplateRow.typologie == typologie)
    rows = (await session.execute(stmt.order_by(TemplateRow.id))).scalars().all()
    total = (await session.execute(select(func.count()).select_from(TemplateRow))).scalar_one()
    return TemplatesListOut(items=[_to_out(r) for r in rows], total=total)


@router.get("/{template_id}", response_model=TemplateOut)
async def get_template(
    template_id: str,
    session: SessionDep,
    current_user: CurrentUserDep,
) -> TemplateOut:
    row = (await session.execute(
        select(TemplateRow).where(TemplateRow.id == template_id)
    )).scalar_one_or_none()
    if row is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Template not found")
    return _to_out(row)
