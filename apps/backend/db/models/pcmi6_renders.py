"""SQLAlchemy model for PCMI6 renders."""
import uuid

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,  # noqa: F401
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from db.base import Base


class Pcmi6RenderRow(Base):
    __tablename__ = "pcmi6_renders"

    id = Column(PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    project_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
    )
    project_version_id = Column(
        PgUUID(as_uuid=True),
        ForeignKey("project_versions.id"),
        nullable=True,
    )

    label = Column(Text, nullable=True)

    camera_lat = Column(Numeric, nullable=True)
    camera_lng = Column(Numeric, nullable=True)
    camera_heading = Column(Numeric, nullable=True)
    camera_pitch = Column(Numeric, nullable=True)
    camera_fov = Column(Numeric, nullable=True)

    materials_config = Column(JSONB, nullable=False)

    photo_source = Column(Text, nullable=True)
    photo_source_id = Column(Text, nullable=True)
    photo_base_url = Column(Text, nullable=True)

    mask_url = Column(Text, nullable=True)
    normal_url = Column(Text, nullable=True)
    depth_url = Column(Text, nullable=True)

    render_url = Column(Text, nullable=True)
    render_variants = Column(JSONB, nullable=True)

    rerender_job_id = Column(Text, nullable=True)
    prompt = Column(Text, nullable=True)
    negative_prompt = Column(Text, nullable=True)
    creativity = Column(Numeric, nullable=True)
    seed = Column(Integer, nullable=True)

    status = Column(Text, nullable=False, server_default="queued")
    error_msg = Column(Text, nullable=True)

    iou_quality_score = Column(Numeric, nullable=True)

    selected_for_pc = Column(Boolean, nullable=False, server_default="false")
    purged = Column(Boolean, nullable=False, server_default="false")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    generation_duration_ms = Column(Integer, nullable=True)
    cost_cents = Column(Numeric(10, 4), nullable=True)

    __table_args__ = (
        Index("pcmi6_renders_project_created", "project_id", "created_at"),
    )
