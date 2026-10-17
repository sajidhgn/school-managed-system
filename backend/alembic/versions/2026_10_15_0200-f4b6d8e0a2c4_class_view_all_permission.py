"""class:view_all permission -- teachers see only their assigned classes

Revision ID: f4b6d8e0a2c4
Revises: e3a5c7d9f1b3
Create Date: 2026-10-15 02:00:00+00:00

WHY THIS MIGRATION EXISTS
    Classes, students, registers, marks and diaries are now bounded to a member's
    teaching assignments unless their role holds `class:view_all`. The principal
    toggles it per role in the role editor.

BACKFILLED SO NOTHING SHRINKS OVERNIGHT
    principal (system)   -- holds the whole catalog, so it gets this too.
    accountant (system)  -- bills the whole roll; matches the catalog.
    every CUSTOM role that reads academic data -- it saw every class yesterday and
        keeps doing so until the principal decides otherwise.
    teacher (system)     -- deliberately NOT. That is the change being shipped.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f4b6d8e0a2c4"
down_revision: str | None = "e3a5c7d9f1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Must match `app/modules/rbac/catalog.py`.
_CODE = "class:view_all"

_RECIPIENTS = """
    SELECT r.id, r.organization_id
      FROM roles r
     WHERE (r.is_system IS TRUE AND r.code IN ('principal', 'accountant'))
        OR (r.is_system IS NOT TRUE AND EXISTS (
                SELECT 1 FROM role_permissions rp
                 WHERE rp.role_id = r.id
                   AND rp.permission_code IN (
                       'student:read', 'class:read', 'subject:read', 'attendance:read',
                       'grade:read', 'diary:read', 'guardian:read'
                   )))
"""


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO permissions
                (code, resource, action, category, description, min_scope, is_dangerous)
            VALUES (:code, 'class', 'view_all', 'Academics',
                    'See every class, section and student -- not only the ones assigned.',
                    'school', FALSE)
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
            f"""
            INSERT INTO role_permissions (role_id, organization_id, permission_code)
            SELECT recipient.id, recipient.organization_id, :code
              FROM ({_RECIPIENTS}) AS recipient
            ON CONFLICT DO NOTHING
            """
        ).bindparams(code=_CODE)
    )
    op.execute(
        sa.text(
            "UPDATE roles SET permissions_version = permissions_version + 1 "
            "WHERE id IN (SELECT role_id FROM role_permissions WHERE permission_code = :code)"
        ).bindparams(code=_CODE)
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
