"""add jurisprudences, recours_cases, project_versions tables for RAG

Revision ID: 20260418_0002
Revises: 20260418_0001
Create Date: 2026-04-18 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260418_0002"
down_revision: str | None = "20260418_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Ensure pgvector extension is available
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # --- jurisprudences ---
    op.create_table(
        "jurisprudences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("reference", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=True),
        sa.Column("commune_insee", sa.String(5), nullable=True),
        sa.Column("motif_principal", sa.Text(), nullable=True),
        sa.Column("articles_plu_cites", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("resume", sa.Text(), nullable=False),
        sa.Column("decision", sa.Text(), nullable=True),
        sa.Column("embedding", sa.Text(), nullable=True),  # declared as Text; managed by pgvector
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("reference", name="uq_jurisprudences_reference"),
    )
    op.create_index("ix_jurisprudences_commune_insee", "jurisprudences", ["commune_insee"])
    # Use HNSW — works on empty tables (IVFFlat requires training rows)
    op.execute(
        "ALTER TABLE jurisprudences ALTER COLUMN embedding TYPE vector(1536) USING NULL"
    )
    op.execute(
        "CREATE INDEX jurisprudences_embedding_idx ON jurisprudences "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    # --- recours_cases ---
    op.create_table(
        "recours_cases",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("commune_insee", sa.String(5), nullable=False),
        sa.Column("date_depot", sa.Date(), nullable=True),
        sa.Column("association", sa.Text(), nullable=True),
        sa.Column("projet_conteste", sa.Text(), nullable=True),
        sa.Column("motifs", postgresql.ARRAY(sa.Text()), nullable=True),
        sa.Column("resultat", sa.Text(), nullable=True),
        sa.Column("resume", sa.Text(), nullable=True),
        sa.Column("embedding", sa.Text(), nullable=True),  # declared as Text; managed by pgvector
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_recours_cases_commune_insee", "recours_cases", ["commune_insee"])
    op.execute(
        "ALTER TABLE recours_cases ALTER COLUMN embedding TYPE vector(1536) USING NULL"
    )
    op.execute(
        "CREATE INDEX recours_cases_embedding_idx ON recours_cases "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    # --- project_versions ---
    op.create_table(
        "project_versions",
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
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("version_label", sa.Text(), nullable=True),
        sa.Column(
            "parent_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("project_versions.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("brief_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column(
            "feasibility_result_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("feasibility_results.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("pdf_report_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("project_id", "version_number", name="uq_project_versions_project_version"),
    )
    op.create_index("ix_project_versions_project_id", "project_versions", ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_project_versions_project_id", table_name="project_versions")
    op.drop_table("project_versions")

    op.execute("DROP INDEX IF EXISTS recours_cases_embedding_idx")
    op.drop_index("ix_recours_cases_commune_insee", table_name="recours_cases")
    op.drop_table("recours_cases")

    op.execute("DROP INDEX IF EXISTS jurisprudences_embedding_idx")
    op.drop_index("ix_jurisprudences_commune_insee", table_name="jurisprudences")
    op.drop_table("jurisprudences")
