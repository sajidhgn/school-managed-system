"""signup plan intent

Revision ID: c9f1a3b5d7e9
Revises: b8e0f2a4c6d8
Create Date: 2026-08-22 04:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9f1a3b5d7e9"
down_revision: str | None = "b8e0f2a4c6d8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "requested_plan_code",
            sa.String(length=50),
            server_default="free",
            nullable=False,
        ),
    )
    op.add_column(
        "organizations",
        sa.Column(
            "requested_billing_cycle",
            sa.String(length=10),
            server_default="monthly",
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "requested_billing_cycle",
        "organizations",
        "requested_billing_cycle IN ('monthly', 'yearly')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_organizations_requested_billing_cycle",
        "organizations",
        type_="check",
    )
    op.drop_column("organizations", "requested_billing_cycle")
    op.drop_column("organizations", "requested_plan_code")
