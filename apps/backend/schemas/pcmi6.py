"""API schemas for PCMI6 render endpoints."""
from datetime import datetime

from pydantic import BaseModel


class CameraConfig(BaseModel):
    lat: float
    lng: float
    heading: float
    pitch: float = 0.0
    fov: float = 60.0


class RenderCreate(BaseModel):
    label: str | None = None
    photo_source: str  # "mapillary" | "streetview"
    photo_source_id: str
    photo_base_url: str
    camera: CameraConfig
    materials_config: dict[str, str]  # {facade: "enduit_blanc", toiture: "zinc_patine", ...}
    # Layers sent via multipart upload, not JSON


class RenderOut(BaseModel):
    id: str
    label: str | None
    status: str
    project_id: str
    photo_source: str | None
    photo_base_url: str | None
    render_url: str | None
    render_variants: list[dict] | None = None
    mask_url: str | None = None
    normal_url: str | None = None
    depth_url: str | None = None
    prompt: str | None = None
    seed: int | None = None
    iou_quality_score: float | None = None
    selected_for_pc: bool
    created_at: datetime
    generation_duration_ms: int | None
    error_msg: str | None = None


class RenderListResponse(BaseModel):
    items: list[RenderOut]
    total: int


class RenderUpdate(BaseModel):
    label: str | None = None
    selected_for_pc: bool | None = None
