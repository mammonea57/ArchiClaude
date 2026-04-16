"""feature_flags table

Revision ID: 20260416_0002
Revises: 20260416_0001
Create Date: 2026-04-16 00:01:00

"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260416_0002"
down_revision: str | None = "20260416_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feature_flags",
        sa.Column("key", sa.String(), primary_key=True),
        sa.Column("enabled_globally", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column(
            "enabled_for_user_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("feature_flags")
