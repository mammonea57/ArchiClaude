"""add parcels plu_documents plu_zones servitudes

Revision ID: 20260417_0001
Revises: 20260416_0003
Create Date: 2026-04-17 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision: str = "20260417_0001"
down_revision: str | None = "20260416_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- parcels ---
    op.create_table(
        "parcels",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("code_insee", sa.String(5), nullable=False),
        sa.Column("section", sa.String(3), nullable=False),
        sa.Column("numero", sa.String(5), nullable=False),
        sa.Column("contenance_m2", sa.Integer(), nullable=True),
        sa.Column(
            "geom",
            Geometry("MULTIPOLYGON", srid=4326),
            nullable=False,
        ),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("code_insee", "section", "numero", name="uq_parcels_id"),
    )
    op.create_index(
        "parcels_geom_gist",
        "parcels",
        ["geom"],
        postgresql_using="gist",
    )
    # GIN trigram index on address — must use raw SQL (gin_trgm_ops not supported natively)
    op.execute(
        "CREATE INDEX parcels_address_trgm ON parcels USING GIN (address gin_trgm_ops)"
    )

    # --- plu_documents ---
    op.create_table(
        "plu_documents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("code_insee", sa.String(5), nullable=False),
        sa.Column("gpu_doc_id", sa.Text(), unique=True, nullable=True),
        sa.Column("partition", sa.Text(), nullable=True),
        sa.Column("type", sa.String(20), nullable=True),
        sa.Column("nomfic", sa.Text(), nullable=True),
        sa.Column("pdf_url", sa.Text(), nullable=True),
        sa.Column("pdf_sha256", sa.String(64), nullable=True),
        sa.Column("pdf_text_raw", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
    )

    # --- plu_zones ---
    op.create_table(
        "plu_zones",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "plu_doc_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("plu_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("libelle", sa.Text(), nullable=True),
        sa.Column("libelong", sa.Text(), nullable=True),
        sa.Column("typezone", sa.Text(), nullable=True),
        sa.Column(
            "geom",
            Geometry("MULTIPOLYGON", srid=4326),
            nullable=True,
        ),
        sa.UniqueConstraint("plu_doc_id", "code", name="uq_plu_zones_doc_code"),
    )
    op.create_index(
        "plu_zones_geom_gist",
        "plu_zones",
        ["geom"],
        postgresql_using="gist",
    )

    # --- servitudes ---
    op.create_table(
        "servitudes",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("sous_type", sa.Text(), nullable=True),
        sa.Column("libelle", sa.Text(), nullable=True),
        sa.Column(
            "geom",
            Geometry("GEOMETRY", srid=4326),
            nullable=True,
        ),
        sa.Column("attributes", postgresql.JSONB(), nullable=True),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "servitudes_geom_gist",
        "servitudes",
        ["geom"],
        postgresql_using="gist",
    )
    op.create_index("servitudes_type_idx", "servitudes", ["type"])


def downgrade() -> None:
    op.drop_index("servitudes_type_idx", table_name="servitudes")
    op.drop_index("servitudes_geom_gist", table_name="servitudes")
    op.drop_table("servitudes")

    op.drop_index("plu_zones_geom_gist", table_name="plu_zones")
    op.drop_table("plu_zones")

    op.drop_table("plu_documents")

    op.execute("DROP INDEX IF EXISTS parcels_address_trgm")
    op.drop_index("parcels_geom_gist", table_name="parcels")
    op.drop_table("parcels")
