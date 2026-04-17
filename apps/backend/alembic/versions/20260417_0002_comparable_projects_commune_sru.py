"""add comparable_projects and commune_sru tables

Revision ID: 20260417_0002
Revises: 20260417_0001
Create Date: 2026-04-17 00:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision: str = "20260417_0002"
down_revision: str | None = "20260417_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- comparable_projects ---
    op.create_table(
        "comparable_projects",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("commune_insee", sa.String(5), nullable=False),
        sa.Column("date_arrete", sa.Text(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("geom", Geometry("POINT", srid=4326), nullable=True),
        sa.Column("sdp_m2", sa.Numeric(), nullable=True),
        sa.Column("nb_logements", sa.Integer(), nullable=True),
        sa.Column("destination", sa.Text(), nullable=True),
        sa.Column("hauteur_niveaux", sa.Integer(), nullable=True),
        sa.Column("url_reference", sa.Text(), nullable=True),
        sa.Column(
            "ingested_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "comparable_projects_geom_gist",
        "comparable_projects",
        ["geom"],
        postgresql_using="gist",
    )
    op.create_index(
        "comparable_projects_commune_date_idx",
        "comparable_projects",
        ["commune_insee", sa.text("date_arrete DESC")],
    )

    # --- commune_sru ---
    op.create_table(
        "commune_sru",
        sa.Column("code_insee", sa.String(5), primary_key=True),
        sa.Column("annee_bilan", sa.Integer(), nullable=False),
        sa.Column("taux_lls_actuel", sa.Numeric(5, 2), nullable=True),
        sa.Column("taux_lls_cible", sa.Numeric(5, 2), nullable=True),
        sa.Column("statut", sa.Text(), nullable=True),
        sa.Column("penalite_annuelle_eur", sa.Numeric(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("commune_sru")
    op.drop_index("comparable_projects_commune_date_idx", table_name="comparable_projects")
    op.drop_index("comparable_projects_geom_gist", table_name="comparable_projects")
    op.drop_table("comparable_projects")
