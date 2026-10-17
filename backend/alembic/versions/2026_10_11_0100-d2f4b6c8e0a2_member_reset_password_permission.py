"""member:reset_password permission

Revision ID: d2f4b6c8e0a2
Revises: c1e3a5b7d9f1
Create Date: 2026-10-11 01:00:00+00:00

WHY THIS MIGRATION EXISTS
    The members edit dialog can now set a member's password. Doing so lets the
    administrator sign in as that person, so it is gated on its own permission
    rather than folded into `member:update` -- the same split as `member:suspend`.

ONE NEW PERMISSION, BACKFILLED
    principal  (system)  -- it holds the whole catalog, so it gets this too.
    Teacher and accountant do not; a school grants it to a custom role explicitly.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2f4b6c8e0a2"
down_revision: str | None = "c1e3a5b7d9f1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Must match `app/modules/rbac/catalog.py`.
_CODE = "member:reset_password"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO permissions
                (code, resource, action, category, description, min_scope, is_dangerous)
            VALUES (:code, 'member', 'reset_password', 'People & access',
                    'Set a new password for a member and sign them out.', 'school', TRUE)
            ON CONFLICT (code) DO UPDATE
                SET category = EXCLUDED.category,
                    description = EXCLUDED.description,
                    min_scope = EXCLUDED.min_scope,
                    is_dangerous = EXCLUDED.is_dangerous
            """
        ).bindparams(code=_CODE)
    )
    op.execute(
        sa.text(
            """
            INSERT INTO role_permissions (role_id, organization_id, permission_code)
            SELECT r.id, r.organization_id, :code
              FROM roles r
             WHERE r.code = 'principal'
               AND r.is_system IS TRUE
            ON CONFLICT DO NOTHING
            """
        ).bindparams(code=_CODE)
    )
    op.execute(
        "UPDATE roles SET permissions_version = permissions_version + 1 "
        "WHERE is_system IS TRUE AND code = 'principal'"
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE roles SET permissions_version = permissions_version + 1 "
            "WHERE id IN (SELECT role_id FROM role_permissions WHERE permission_code = :code)"
        ).bindparams(code=_CODE)
    )
    op.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_code = :code").bindparams(code=_CODE)
    )
    op.execute(sa.text("DELETE FROM permissions WHERE code = :code").bindparams(code=_CODE))
