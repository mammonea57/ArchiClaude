"""enable RLS on private tables

Revision ID: 20260419_0004
Revises: 20260419_0003

Note: Policies are created but NOT FORCED. Postgres RLS is bypassed for table
owners. In production, the application must connect as a non-owner role to
activate enforcement. These policies are the second layer of defense — the
primary layer is backend query filters (user_id/workspace_id checks in route
handlers).
"""
from alembic import op

revision = "20260419_0004"
down_revision = "20260419_0003"
branch_labels = None
depends_on = None


def upgrade():
    # projects scoped by workspace membership
    op.execute("ALTER TABLE projects ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY projects_workspace_isolation ON projects
        USING (
            workspace_id IS NULL
            OR workspace_id IN (
                SELECT workspace_id FROM workspace_members
                WHERE user_id = NULLIF(current_setting('app.user_id', true), '')::UUID
            )
        )
    """)

    # tables scoped via projects (transitively protected)
    for tbl in [
        "feasibility_results",
        "pcmi_dossiers",
        "pcmi6_renders",
        "project_versions",
    ]:
        op.execute(f"ALTER TABLE {tbl} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY {tbl}_isolation ON {tbl}
            USING (project_id IN (SELECT id FROM projects))
        """)

    # reports are transitively protected via feasibility_results -> projects
    op.execute("ALTER TABLE reports ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY reports_isolation ON reports
        USING (
            feasibility_result_id IN (
                SELECT id FROM feasibility_results
                WHERE project_id IN (SELECT id FROM projects)
            )
        )
    """)

    # agency_settings scoped by user
    op.execute("ALTER TABLE agency_settings ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY agency_isolation ON agency_settings
        USING (
            user_id = NULLIF(current_setting('app.user_id', true), '')::UUID
        )
    """)

    # notifications scoped by user
    op.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
    op.execute("""
        CREATE POLICY notifications_isolation ON notifications
        USING (
            user_id = NULLIF(current_setting('app.user_id', true), '')::UUID
        )
    """)


def downgrade():
    # notifications / agency_settings use non-{tbl}_isolation names
    op.execute("DROP POLICY IF EXISTS notifications_isolation ON notifications")
    op.execute("ALTER TABLE notifications DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS agency_isolation ON agency_settings")
    op.execute("ALTER TABLE agency_settings DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS reports_isolation ON reports")
    op.execute("ALTER TABLE reports DISABLE ROW LEVEL SECURITY")

    for tbl in [
        "project_versions",
        "pcmi6_renders",
        "pcmi_dossiers",
        "feasibility_results",
    ]:
        op.execute(f"DROP POLICY IF EXISTS {tbl}_isolation ON {tbl}")
        op.execute(f"ALTER TABLE {tbl} DISABLE ROW LEVEL SECURITY")

    op.execute("DROP POLICY IF EXISTS projects_workspace_isolation ON projects")
    op.execute("ALTER TABLE projects DISABLE ROW LEVEL SECURITY")
