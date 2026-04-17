"""add reports and agency_settings tables

Revision ID: 20260418_0003
Revises: 20260418_0002
Create Date: 2026-04-18 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260418_0003"
down_revision: str | None = "20260418_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- reports ---
    op.create_table(
        "reports",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "feasibility_result_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("feasibility_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("r2_key", sa.Text(), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_reports_feasibility_result_id", "reports", ["feasibility_result_id"]
    )

    # --- agency_settings ---
    op.create_table(
        "agency_settings",
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
        sa.Column("agency_name", sa.Text(), nullable=True),
        sa.Column("logo_r2_key", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("contact_email", sa.Text(), nullable=True),
        sa.Column("contact_phone", sa.Text(), nullable=True),
        sa.Column("archi_ordre_number", sa.Text(), nullable=True),
        sa.Column("default_cartouche_footer", sa.Text(), nullable=True),
        sa.Column("brand_primary_color", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("user_id", name="uq_agency_settings_user_id"),
    )
    op.create_index("ix_agency_settings_user_id", "agency_settings", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_agency_settings_user_id", table_name="agency_settings")
    op.drop_table("agency_settings")

    op.drop_index("ix_reports_feasibility_result_id", table_name="reports")
    op.drop_table("reports")
