"""Row-Level Security helpers for migrations.

WHY THIS FILE EXISTS
    Alembic's autogenerate understands tables, columns, indexes and constraints. It
    does NOT understand RLS -- it will never emit `ENABLE ROW LEVEL SECURITY` or a
    `CREATE POLICY`. If we leave that to hand-written SQL in each migration, sooner
    or later a table ships with the tenant column but no policy, and that table
    silently leaks every school's data to every other school.

    These helpers make the correct thing a one-liner, so there is no excuse to skip
    it or to get the policy expression subtly wrong.

RESPONSIBILITY
    Emit the exact DDL that binds a table to the tenant GUC set by
    `app/db/session.py::_apply_tenant_guc`. The two files must agree on the GUC
    name -- that coupling is the entire mechanism, so it is stated explicitly here.

USAGE inside a migration:

    from alembic import op
    from alembic.rls import enable_tenant_rls, disable_tenant_rls

    def upgrade() -> None:
        op.create_table("students", ...)
        enable_tenant_rls("students")

    def downgrade() -> None:
        disable_tenant_rls("students")
        op.drop_table("students")
"""

from __future__ import annotations

from alembic import op

# MUST match app/db/session.py::TENANT_GUC and SUPER_ADMIN_GUC.
TENANT_GUC = "app.current_school_id"
SUPER_ADMIN_GUC = "app.is_super_admin"

# The application's runtime role. Created once in the bootstrap migration.
APP_ROLE = "sms_app"


def enable_tenant_rls(table: str, *, tenant_column: str = "school_id") -> None:
    """Enable RLS on `table` and install the tenant-isolation policy.

    THE POLICY EXPLAINED

        USING       -> filters which existing rows are VISIBLE (SELECT/UPDATE/DELETE)
        WITH CHECK  -> validates rows being WRITTEN (INSERT/UPDATE)

    Both are required. A USING-only policy would let a user of School A INSERT a row
    stamped with School B's id -- they could not read it back, but they would have
    written into another tenant's data. WITH CHECK closes that hole.

    THE SUPER-ADMIN ESCAPE HATCH
        `current_setting('app.is_super_admin', true) = 'on'` lets platform operators
        run cross-tenant queries for support and billing. The second argument
        (`missing_ok = true`) makes `current_setting` return NULL instead of raising
        when the GUC was never set -- important, because an unset GUC would
        otherwise turn every query into an error.

    NOTE ON `FORCE ROW LEVEL SECURITY`
        By default the table OWNER bypasses RLS entirely. FORCE removes that
        exemption. Without it, if the app ever connects as the owner role, every
        policy on this table is silently inert.
    """
    tenant_predicate = (
        f"({tenant_column} = NULLIF(current_setting('{TENANT_GUC}', true), '')::uuid"
        f" OR current_setting('{SUPER_ADMIN_GUC}', true) = 'on')"
    )

    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"FOR ALL TO {APP_ROLE} "
        f"USING {tenant_predicate} "
        f"WITH CHECK {tenant_predicate}"
    )


def disable_tenant_rls(table: str) -> None:
    """Reverse `enable_tenant_rls`. Call before dropping the table in downgrade()."""
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def grant_app_role(table: str) -> None:
    """Grant the application role DML rights on a table.

    The app role owns nothing and can create nothing -- it can only read and write
    rows that the policies permit. Principle of least privilege: a SQL-injection
    bug in application code cannot DROP a table it has no rights to.
    """
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")


def setup_tenant_table(table: str, *, tenant_column: str = "school_id") -> None:
    """Convenience: grant + enable RLS. Call this after every `create_table`."""
    grant_app_role(table)
    enable_tenant_rls(table, tenant_column=tenant_column)
