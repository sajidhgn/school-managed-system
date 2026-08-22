"""billing request idempotency

Revision ID: b8e0f2a4c6d8
Revises: a7d9e1f3b5c7
Create Date: 2026-08-22 03:00:00+00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from alembic.rls import setup_tenant_table, teardown_tenant_table
from sqlalchemy.dialects import postgresql

revision: str = "b8e0f2a4c6d8"
down_revision: str | None = "a7d9e1f3b5c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "billing_idempotency_keys",
        sa.Column("operation", sa.String(length=80), nullable=False),
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("response_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "id",
            sa.UUID(),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_billing_idempotency_keys_organization_id",
        "billing_idempotency_keys",
        ["organization_id"],
    )
    op.create_index(
        "ix_billing_idempotency_keys_created_at",
        "billing_idempotency_keys",
        ["created_at"],
    )
    op.create_index(
        "uq_billing_idempotency_keys_org_operation_key",
        "billing_idempotency_keys",
        ["organization_id", "operation", "key"],
        unique=True,
    )
    setup_tenant_table("billing_idempotency_keys")


def downgrade() -> None:
    teardown_tenant_table("billing_idempotency_keys")
    op.drop_index(
        "uq_billing_idempotency_keys_org_operation_key",
        table_name="billing_idempotency_keys",
    )
    op.drop_index(
        "ix_billing_idempotency_keys_created_at",
        table_name="billing_idempotency_keys",
    )
    op.drop_index(
        "ix_billing_idempotency_keys_organization_id",
        table_name="billing_idempotency_keys",
    )
    op.drop_table("billing_idempotency_keys")
