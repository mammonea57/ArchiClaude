"""add projects, project_parcels, feasibility_results tables

Revision ID: 20260418_0001
Revises: 20260417_0003
Create Date: 2026-04-18 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260418_0001"
down_revision: str | None = "20260417_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- projects ---
    op.create_table(
        "projects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("brief", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_projects_user_id", "projects", ["user_id"])

    # --- project_parcels ---
    op.create_table(
        "project_parcels",
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "parcel_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("parcels.id"),
            primary_key=True,
        ),
        sa.Column("ordering", sa.SmallInteger(), nullable=True),
    )

    # --- feasibility_results ---
    op.create_table(
        "feasibility_results",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(), nullable=False),
        sa.Column(
            "footprint_geom",
            sa.Text(),  # stored as WKT/WKB text; typed at application layer via geoalchemy2
            nullable=True,
        ),
        sa.Column(
            "zone_rules_used",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
        ),
        sa.Column("confidence_score", sa.Numeric(3, 2), nullable=True),
        sa.Column("warnings", postgresql.JSONB(), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_feasibility_results_project_id", "feasibility_results", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_feasibility_results_project_id", table_name="feasibility_results")
    op.drop_table("feasibility_results")
    op.drop_table("project_parcels")
    op.drop_index("ix_projects_user_id", table_name="projects")
    op.drop_table("projects")
