"""contain role permissions by tenant

Revision ID: 8f4c1a2b3d5e
Revises: 21c252f1123a
Create Date: 2026-08-22 01:00:00+00:00

`role_permissions` previously relied on its parent `roles` table for tenancy, but
direct DML against the join table never touches that parent's RLS policy. Give the
join its own tenant key and forced policy, with a composite foreign key preventing
the duplicated organization id from disagreeing with the parent role.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from alembic.rls import setup_tenant_table, teardown_tenant_table

revision: str = "8f4c1a2b3d5e"
down_revision: str | None = "21c252f1123a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("role_permissions", sa.Column("organization_id", sa.UUID(), nullable=True))
    op.execute(
        """
        UPDATE role_permissions AS rp
        SET organization_id = roles.organization_id
        FROM roles
        WHERE roles.id = rp.role_id
        """
    )
    op.alter_column("role_permissions", "organization_id", nullable=False)

    op.create_unique_constraint("uq_roles_id_organization_id", "roles", ["id", "organization_id"])
    op.drop_constraint("fk_role_permissions_role_id_roles", "role_permissions", type_="foreignkey")
    op.create_foreign_key(
        "fk_role_permissions_role_id_organization_id_roles",
        "role_permissions",
        "roles",
        ["role_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_role_permissions_organization_id_organizations",
        "role_permissions",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_role_permissions_organization_id",
        "role_permissions",
        ["organization_id"],
    )
    setup_tenant_table("role_permissions")


def downgrade() -> None:
    teardown_tenant_table("role_permissions")
    op.drop_index("ix_role_permissions_organization_id", table_name="role_permissions")
    op.drop_constraint(
        "fk_role_permissions_organization_id_organizations",
        "role_permissions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_role_permissions_role_id_organization_id_roles",
        "role_permissions",
        type_="foreignkey",
    )
    op.create_foreign_key(
        "fk_role_permissions_role_id_roles",
        "role_permissions",
        "roles",
        ["role_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.drop_constraint("uq_roles_id_organization_id", "roles", type_="unique")
    op.drop_column("role_permissions", "organization_id")
