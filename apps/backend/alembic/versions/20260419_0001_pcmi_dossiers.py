"""add pcmi_dossiers table

Revision ID: 20260419_0001
Revises: 20260418_0003
Create Date: 2026-04-19 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260419_0001"
down_revision: str | None = "20260418_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pcmi_dossiers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.Text, nullable=False, server_default="queued"),
        sa.Column("indice_revision", sa.String(2), nullable=False),
        sa.Column("map_base", sa.Text, nullable=True, server_default="scan25"),
        sa.Column("pdf_unique_r2_key", sa.Text, nullable=True),
        sa.Column("zip_r2_key", sa.Text, nullable=True),
        sa.Column("pieces_status", postgresql.JSONB(), nullable=True),
        sa.Column("error_msg", sa.Text, nullable=True),
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
        sa.UniqueConstraint(
            "project_id", "indice_revision", name="uq_pcmi_project_indice"
        ),
    )
    op.create_index(
        "ix_pcmi_dossiers_project_id",
        "pcmi_dossiers",
        ["project_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_pcmi_dossiers_project_id", table_name="pcmi_dossiers")
    op.drop_table("pcmi_dossiers")
