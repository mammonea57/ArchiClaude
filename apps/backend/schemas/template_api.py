from pydantic import BaseModel


class TemplateOut(BaseModel):
    id: str
    typologie: str
    source: str
    surface_shab_range: list[float]
    orientation_compatible: list[str]
    position_dans_etage: list[str]
    tags: list[str]
    preview_svg: str | None = None
    rating_avg: float | None = None


class TemplatesListOut(BaseModel):
    items: list[TemplateOut]
    total: int
