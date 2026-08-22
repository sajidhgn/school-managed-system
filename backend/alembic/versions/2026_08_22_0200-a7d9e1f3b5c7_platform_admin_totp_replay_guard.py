"""platform admin totp replay guard

Revision ID: a7d9e1f3b5c7
Revises: 8f4c1a2b3d5e
Create Date: 2026-08-22 02:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7d9e1f3b5c7"
down_revision: str | None = "8f4c1a2b3d5e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "platform_admins",
        "mfa_secret",
        existing_type=sa.String(length=64),
        type_=sa.Text(),
        existing_nullable=True,
    )
    op.add_column("platform_admins", sa.Column("mfa_last_used_step", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("platform_admins", "mfa_last_used_step")
    op.alter_column(
        "platform_admins",
        "mfa_secret",
        existing_type=sa.Text(),
        type_=sa.String(length=64),
        existing_nullable=True,
    )
