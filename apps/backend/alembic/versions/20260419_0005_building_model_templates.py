"""sp2v2a building_models + templates + renders + pgvector

Revision ID: 20260419_0005
Revises: 20260419_0004
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260419_0005"
down_revision = "20260419_0004"
branch_labels = None
depends_on = None


def upgrade():
    # Enable pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- building_models ---
    op.create_table(
        "building_models",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("model_json", postgresql.JSONB, nullable=False),
        sa.Column("conformite_check", postgresql.JSONB, nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "generated_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column(
            "parent_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("building_models.id"),
            nullable=True,
        ),
        sa.Column("dirty", sa.Boolean, nullable=False, server_default="false"),
        sa.UniqueConstraint("project_id", "version", name="uq_building_models_project_version"),
        sa.CheckConstraint(
            "source IN ('auto','user_edit','regen')",
            name="building_models_source_check",
        ),
    )
    op.create_index(
        "idx_building_models_project", "building_models", ["project_id"]
    )
    op.execute(
        "CREATE INDEX idx_building_models_model_json "
        "ON building_models USING GIN (model_json)"
    )

    # --- templates ---
    op.create_table(
        "templates",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("typologie", sa.String(10), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("json_data", postgresql.JSONB, nullable=False),
        sa.Column("preview_svg", sa.Text, nullable=True),
        # embedding column added via raw SQL (SQLAlchemy can't emit vector type yet)
        sa.Column("rating_avg", sa.Numeric(3, 2), nullable=True),
        sa.Column("usage_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "source IN ('manual','scraped','llm_gen','llm_augmented')",
            name="templates_source_check",
        ),
    )
    op.execute("ALTER TABLE templates ADD COLUMN embedding vector(1536)")
    op.execute(
        "CREATE INDEX idx_templates_embedding "
        "ON templates USING ivfflat (embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )
    op.create_index("idx_templates_typologie", "templates", ["typologie"])

    # --- renders (preparé pour SP2-v2b) ---
    op.create_table(
        "renders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "building_model_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("building_models.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.String(50), nullable=False),
        sa.Column("format", sa.String(10), nullable=False),
        sa.Column("s3_key", sa.Text, nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("generation_duration_ms", sa.Integer, nullable=True),
        sa.Column("size_bytes", sa.Integer, nullable=True),
        sa.Column("checksum", sa.String(64), nullable=True),
    )
    op.create_index(
        "idx_renders_project_bm",
        "renders",
        ["project_id", "building_model_id"],
    )


def downgrade():
    op.drop_table("renders")
    op.execute("DROP INDEX IF EXISTS idx_templates_embedding")
    op.drop_index("idx_templates_typologie", table_name="templates")
    op.drop_table("templates")
    op.execute("DROP INDEX IF EXISTS idx_building_models_model_json")
    op.drop_index("idx_building_models_project", table_name="building_models")
    op.drop_table("building_models")
    # Keep vector extension (used elsewhere potentially)
