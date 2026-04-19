"""pcmi6_renders

Revision ID: 20260419_0002
Revises: 20260419_0001
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260419_0002"
down_revision = "20260419_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pcmi6_renders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_versions.id"),
            nullable=True,
        ),
        sa.Column("label", sa.Text, nullable=True),
        sa.Column("camera_lat", sa.Numeric, nullable=True),
        sa.Column("camera_lng", sa.Numeric, nullable=True),
        sa.Column("camera_heading", sa.Numeric, nullable=True),
        sa.Column("camera_pitch", sa.Numeric, nullable=True),
        sa.Column("camera_fov", sa.Numeric, nullable=True),
        sa.Column("materials_config", postgresql.JSONB, nullable=False),
        sa.Column("photo_source", sa.Text, nullable=True),
        sa.Column("photo_source_id", sa.Text, nullable=True),
        sa.Column("photo_base_url", sa.Text, nullable=True),
        sa.Column("mask_url", sa.Text, nullable=True),
        sa.Column("normal_url", sa.Text, nullable=True),
        sa.Column("depth_url", sa.Text, nullable=True),
        sa.Column("render_url", sa.Text, nullable=True),
        sa.Column("render_variants", postgresql.JSONB, nullable=True),
        sa.Column("rerender_job_id", sa.Text, nullable=True),
        sa.Column("prompt", sa.Text, nullable=True),
        sa.Column("negative_prompt", sa.Text, nullable=True),
        sa.Column("creativity", sa.Numeric, nullable=True),
        sa.Column("seed", sa.Integer, nullable=True),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("error_msg", sa.Text, nullable=True),
        sa.Column("iou_quality_score", sa.Numeric, nullable=True),
        sa.Column("selected_for_pc", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("purged", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("generation_duration_ms", sa.Integer, nullable=True),
        sa.Column("cost_cents", sa.Numeric(10, 4), nullable=True),
    )
    op.create_index("pcmi6_renders_project_created", "pcmi6_renders", ["project_id", "created_at"])
    op.execute(
        "CREATE UNIQUE INDEX pcmi6_selected_per_version ON pcmi6_renders(project_version_id) WHERE selected_for_pc = true"
    )


def downgrade():
    op.drop_index("pcmi6_selected_per_version", table_name="pcmi6_renders")
    op.drop_index("pcmi6_renders_project_created", table_name="pcmi6_renders")
    op.drop_table("pcmi6_renders")
