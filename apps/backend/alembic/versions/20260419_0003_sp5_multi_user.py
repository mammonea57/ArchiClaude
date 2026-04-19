"""sp5 multi-user + workspaces + notifications

Revision ID: 20260419_0003
Revises: 20260419_0002
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260419_0003"
down_revision = "20260419_0002"
branch_labels = None
depends_on = None


def upgrade():
    # --- Tables workspaces ---
    op.create_table(
        "workspaces",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("slug", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("logo_url", sa.Text, nullable=True),
        sa.Column("is_personal", sa.Boolean, nullable=False, server_default="false"),
        sa.Column(
            "created_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("slug", name="uq_workspaces_slug"),
    )
    op.create_index("workspaces_created_by", "workspaces", ["created_by"])

    op.create_table(
        "workspace_members",
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column(
            "invited_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("invited_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('admin','member','viewer')", name="workspace_members_role_check"
        ),
    )
    op.create_index("workspace_members_user", "workspace_members", ["user_id"])

    op.create_table(
        "workspace_invitations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column("role", sa.Text, nullable=False),
        sa.Column(
            "invited_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("token", sa.Text, nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("token", name="uq_invitations_token"),
        sa.CheckConstraint(
            "role IN ('admin','member','viewer')", name="invitations_role_check"
        ),
    )
    op.execute(
        "CREATE INDEX invitations_email_pending ON workspace_invitations(email) "
        "WHERE accepted_at IS NULL"
    )

    # --- OAuth accounts ---
    op.create_table(
        "oauth_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider", sa.Text, nullable=False),
        sa.Column("provider_user_id", sa.Text, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint(
            "provider", "provider_user_id", name="uq_oauth_provider_user"
        ),
    )

    # --- Status history ---
    op.create_table(
        "project_status_history",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "project_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("from_status", sa.Text, nullable=True),
        sa.Column("to_status", sa.Text, nullable=False),
        sa.Column(
            "changed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
        sa.Column("changed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("notes", sa.Text, nullable=True),
    )
    op.create_index(
        "project_status_history_project",
        "project_status_history",
        ["project_id", "changed_at"],
    )

    # --- Notifications ---
    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("title", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("link", sa.Text, nullable=True),
        sa.Column("extra", postgresql.JSONB, nullable=True),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("notifications_user_unread", "notifications", ["user_id", "read_at"])

    op.create_table(
        "notification_preferences",
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("in_app_enabled", sa.Boolean, server_default="true"),
        sa.Column("email_workspace_invitations", sa.Boolean, server_default="true"),
        sa.Column("email_project_analyzed", sa.Boolean, server_default="true"),
        sa.Column("email_project_ready_for_pc", sa.Boolean, server_default="true"),
        sa.Column("email_mentions", sa.Boolean, server_default="true"),
        sa.Column("email_comments", sa.Boolean, server_default="false"),
        sa.Column("email_pcmi6_generated", sa.Boolean, server_default="false"),
        sa.Column("email_weekly_digest", sa.Boolean, server_default="false"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    # --- Alter projects (status already exists — only add workspace_id + status_changed_* + CHECK constraint) ---
    op.add_column(
        "projects",
        sa.Column(
            "workspace_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("workspaces.id"),
            nullable=True,
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "status_changed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )
    op.add_column(
        "projects",
        sa.Column(
            "status_changed_by",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=True,
        ),
    )
    op.create_check_constraint(
        "projects_status_check",
        "projects",
        "status IN ('draft','analyzed','reviewed','ready_for_pc','archived')",
    )

    # --- Data migration: create personal workspace for each existing user, assign existing projects ---
    op.execute(
        """
        INSERT INTO workspaces (id, name, slug, is_personal, created_by)
        SELECT
            gen_random_uuid(),
            COALESCE(u.full_name, u.email) || ' — Espace personnel',
            'personal-' || u.id::text,
            true,
            u.id
        FROM users u
        """
    )

    op.execute(
        """
        INSERT INTO workspace_members (workspace_id, user_id, role, joined_at)
        SELECT w.id, w.created_by, 'admin', now()
        FROM workspaces w
        WHERE w.is_personal = true
        """
    )

    op.execute(
        """
        UPDATE projects p
        SET workspace_id = (
            SELECT w.id FROM workspaces w
            WHERE w.is_personal = true AND w.created_by = p.user_id
            LIMIT 1
        )
        WHERE p.workspace_id IS NULL
        """
    )


def downgrade():
    op.drop_constraint("projects_status_check", "projects", type_="check")
    op.drop_column("projects", "status_changed_by")
    op.drop_column("projects", "status_changed_at")
    op.drop_column("projects", "workspace_id")
    op.drop_table("notification_preferences")
    op.drop_index("notifications_user_unread", table_name="notifications")
    op.drop_table("notifications")
    op.drop_index(
        "project_status_history_project", table_name="project_status_history"
    )
    op.drop_table("project_status_history")
    op.drop_table("oauth_accounts")
    op.execute("DROP INDEX IF EXISTS invitations_email_pending")
    op.drop_table("workspace_invitations")
    op.drop_index("workspace_members_user", table_name="workspace_members")
    op.drop_table("workspace_members")
    op.drop_index("workspaces_created_by", table_name="workspaces")
    op.drop_table("workspaces")
