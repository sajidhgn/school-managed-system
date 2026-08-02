"""Row-Level Security helpers for migrations.

WHY THIS FILE EXISTS
    Alembic's autogenerate understands tables, columns, indexes and constraints. It
    does NOT understand RLS -- it will never emit `ENABLE ROW LEVEL SECURITY` or a
    `CREATE POLICY`. If we leave that to hand-written SQL in each migration, sooner
    or later a table ships with the tenant column but no policy, and that table
    silently leaks every organization's data to every other organization.

    These helpers make the correct thing a one-liner, so there is no excuse to skip
    it or to get the policy expression subtly wrong.

RESPONSIBILITY
    Emit the exact DDL that binds a table to the GUCs set by
    `app/db/session.py::_apply_tenant_gucs`. The two files must agree on the GUC
    names -- that coupling is the entire mechanism, so it is stated explicitly here.

USAGE inside a migration:

    from alembic import op
    from alembic.rls import setup_tenant_table, teardown_tenant_table

    def upgrade() -> None:
        op.create_table("schools", ...)
        setup_tenant_table("schools")

    def downgrade() -> None:
        teardown_tenant_table("schools")
        op.drop_table("schools")

=============================================================================
THE TENANT KEY IS `organization_id`, NOT `school_id` -- spec decision D3
=============================================================================
    The organization is the billing and isolation boundary; a school is a scope
    *inside* it. An owner with three schools must be able to read across all three,
    so school cannot be the RLS key without locking the owner out of their own
    data. School scoping is enforced one layer up, in the permission dependency
    and the repository base query.

    `schools` itself still uses `organization_id` as its policy column -- it is an
    ordinary tenant-owned table. Only `organizations` is special-cased, since its
    tenant key is its own primary key (see `setup_organizations_table`).
"""

from __future__ import annotations

from alembic import op

# MUST match app/db/session.py::ORG_GUC / SCHOOL_GUC / PLATFORM_ADMIN_GUC.
ORG_GUC = "app.current_org_id"
PLATFORM_ADMIN_GUC = "app.is_platform_admin"

# The application's runtime role. Created once in the bootstrap migration.
APP_ROLE = "sms_app"


def _org_predicate(tenant_column: str) -> str:
    """The USING clause: which existing rows this connection may SEE.

    `NULLIF(..., '')` maps the unset/empty GUC to NULL, and `NULL = anything` is
    NULL (not true), so a connection that never bound a tenant sees zero rows
    rather than erroring or -- far worse -- seeing everything.

    The second argument to `current_setting` (`missing_ok = true`) returns NULL
    instead of raising when the GUC was never defined at all, which is what happens
    on a fresh pooled connection.
    """
    return (
        f"({tenant_column} = NULLIF(current_setting('{ORG_GUC}', true), '')::uuid"
        f" OR current_setting('{PLATFORM_ADMIN_GUC}', true) = 'on')"
    )


def _write_predicate(tenant_column: str) -> str:
    """The WITH CHECK clause: which rows this connection may WRITE.

    DELIBERATELY NARROWER THAN `USING` -- spec §2.2 is explicit that WITH CHECK has
    no platform-admin escape hatch. A platform admin may READ across tenants for
    support and billing; they may not WRITE into one. Writes on a tenant's behalf go
    through dedicated admin endpoints that first bind `app.current_org_id` to the
    target organization, which makes the write appear in that org's own audit trail
    instead of materialising from nowhere.

    Without this asymmetry, one buggy admin endpoint could stamp rows into an
    arbitrary organization, and nothing in the database would object.
    """
    return f"({tenant_column} = NULLIF(current_setting('{ORG_GUC}', true), '')::uuid)"


def enable_tenant_rls(table: str, *, tenant_column: str = "organization_id") -> None:
    """Enable RLS on `table` and install the tenant-isolation policy.

    THE POLICY EXPLAINED

        USING       -> filters which existing rows are VISIBLE (SELECT/UPDATE/DELETE)
        WITH CHECK  -> validates rows being WRITTEN (INSERT/UPDATE)

    Both are required. A USING-only policy would let a user of Org A INSERT a row
    stamped with Org B's id -- they could not read it back, but they would have
    written into another tenant's data. WITH CHECK closes that hole.

    NOTE ON `FORCE ROW LEVEL SECURITY`
        By default the table OWNER bypasses RLS entirely. FORCE removes that
        exemption. Without it, if the app ever connects as the owner role, every
        policy on this table is silently inert -- which is the single most common
        way multi-tenant isolation fails in production.
    """
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {table} "
        f"FOR ALL TO {APP_ROLE} "
        f"USING {_org_predicate(tenant_column)} "
        f"WITH CHECK {_write_predicate(tenant_column)}"
    )


def disable_tenant_rls(table: str) -> None:
    """Reverse `enable_tenant_rls`. Call before dropping the table in downgrade()."""
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


def grant_app_role(table: str) -> None:
    """Grant the application role DML rights on a table.

    The app role owns nothing and can create nothing -- it can only read and write
    rows the policies permit. Principle of least privilege: a SQL-injection bug in
    application code cannot DROP a table it has no rights to.
    """
    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE}")


def setup_tenant_table(table: str, *, tenant_column: str = "organization_id") -> None:
    """Convenience: grant + enable RLS. Call this after every tenant `create_table`."""
    grant_app_role(table)
    enable_tenant_rls(table, tenant_column=tenant_column)


def teardown_tenant_table(table: str) -> None:
    """Convenience inverse of `setup_tenant_table`, for downgrade()."""
    disable_tenant_rls(table)


def setup_organizations_table() -> None:
    """RLS for `organizations` itself, whose tenant key IS its primary key.

    Every other table answers "which org owns this row?" with an `organization_id`
    column. This table answers it with `id` -- giving it an `organization_id`
    pointing at itself would be circular. Same policy shape, different column.
    """
    grant_app_role("organizations")
    enable_tenant_rls("organizations", tenant_column="id")


def setup_platform_table(table: str) -> None:
    """Grant DML on a platform table WITHOUT enabling RLS.

    `platform_admins`, `plans` and `platform_audit_logs` live outside tenancy by
    design (spec §3.1): plans are global catalog data served to the public pricing
    page, and platform admins belong to no organization. Enabling RLS on them would
    make them invisible to every request, since no `organization_id` exists to
    compare against.

    Called out as its own function rather than a bare `grant_app_role` so that a
    reviewer can see the RLS omission was a decision, not an oversight.
    """
    grant_app_role(table)
