"""add zone_rules_text, zone_rules_numeric, extraction_feedback tables

Revision ID: 20260417_0003
Revises: 20260417_0002
Create Date: 2026-04-17 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260417_0003"
down_revision: str | None = "20260417_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- zone_rules_text ---
    op.create_table(
        "zone_rules_text",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "plu_zone_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plu_zones.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("commune_insee", sa.String(5), nullable=True),
        sa.Column("parsed_rules", postgresql.JSONB(), nullable=False),
        sa.Column("pdf_text_hash", sa.String(64), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column("model_used", sa.Text(), nullable=True),
        sa.Column("extraction_cost_cents", sa.Numeric(10, 4), nullable=True),
        sa.Column(
            "extracted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_unique_constraint(
        "uq_zone_rules_text_zone_commune_hash",
        "zone_rules_text",
        ["plu_zone_id", "commune_insee", "pdf_text_hash"],
    )

    # --- zone_rules_numeric ---
    op.create_table(
        "zone_rules_numeric",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "zone_rules_text_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("zone_rules_text.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("numeric_rules", postgresql.JSONB(), nullable=False),
        sa.Column("extraction_confidence", sa.Numeric(3, 2), nullable=True),
        sa.Column("warnings", postgresql.JSONB(), nullable=True),
        sa.Column(
            "validated_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("validated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("validation_edits", postgresql.JSONB(), nullable=True),
        sa.CheckConstraint(
            "extraction_confidence >= 0 AND extraction_confidence <= 1",
            name="chk_zone_rules_numeric_confidence_range",
        ),
    )

    # --- extraction_feedback ---
    op.create_table(
        "extraction_feedback",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "zone_rules_numeric_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("zone_rules_numeric.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("diff", postgresql.JSONB(), nullable=False),
        sa.Column("edit_reason", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_extraction_feedback_zone_rules_numeric_id",
        "extraction_feedback",
        ["zone_rules_numeric_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_extraction_feedback_zone_rules_numeric_id",
        table_name="extraction_feedback",
    )
    op.drop_table("extraction_feedback")
    op.drop_table("zone_rules_numeric")
    op.drop_unique_constraint(
        "uq_zone_rules_text_zone_commune_hash",
        "zone_rules_text",
    )
    op.drop_table("zone_rules_text")
