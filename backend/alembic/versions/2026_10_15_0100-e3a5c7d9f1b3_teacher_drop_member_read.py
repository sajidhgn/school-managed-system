"""teacher role loses member:read

Revision ID: e3a5c7d9f1b3
Revises: d2f4b6c8e0a2
Create Date: 2026-10-15 01:00:00+00:00

WHY THIS MIGRATION EXISTS
    The staff directory (emails, roles, branch assignments) is an administrator's
    view, so the seeded teacher role no longer carries `member:read`. The catalog
    change only affects organizations seeded from now on; this brings the existing
    system teacher roles in line.

ONLY THE SYSTEM ROLE
    Custom roles a principal built are left alone -- if they granted `member:read`
    to a role of their own, that was their decision. `permissions_version` is bumped
    so tokens minted before the change stop carrying the code.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3a5c7d9f1b3"
down_revision: str | None = "d2f4b6c8e0a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Must match `app/modules/rbac/catalog.py`.
_CODE = "member:read"
_TEACHER_ROLES = "SELECT id FROM roles WHERE is_system IS TRUE AND code = 'teacher'"


def upgrade() -> None:
    op.execute(
        sa.text(
            f"DELETE FROM role_permissions WHERE permission_code = :code "
            f"AND role_id IN ({_TEACHER_ROLES})"
        ).bindparams(code=_CODE)
    )
    op.execute(
        f"UPDATE roles SET permissions_version = permissions_version + 1 WHERE id IN ({_TEACHER_ROLES})"
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            f"""
            INSERT INTO role_permissions (role_id, organization_id, permission_code)
            SELECT r.id, r.organization_id, :code
              FROM roles r
             WHERE r.id IN ({_TEACHER_ROLES})
            ON CONFLICT DO NOTHING
            """
        ).bindparams(code=_CODE)
    )
    op.execute(
        f"UPDATE roles SET permissions_version = permissions_version + 1 WHERE id IN ({_TEACHER_ROLES})"
    )
