"""fees: the campus sibling rule

Revision ID: 8f236ce675a8
Revises: 7e125bd564f7
Create Date: 2026-10-28 14:00:00+00:00

WHY THIS MIGRATION EXISTS
    `docs/modules/fees.md` §2 deferred sibling remission until a guardian aggregate
    existed, so that families could be found by who their parents are rather than by
    a surname match. The guardian registry now exists.

WHAT CHANGES
    One table, `fee_sibling_rules`, one row per campus: the head the remission comes
    off and the concession scheme for the second, third and fourth-and-later child.
    Nothing in billing reads it. It drives a review screen, and staff apply what it
    proposes as ordinary DISCOUNT arrangements -- so no existing table changes.

THINGS AUTOGENERATE WOULD NOT HAVE PRODUCED
    RLS on the new table. A sibling rule names the schemes families are on, and every
    tenant table gets a policy.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from alembic.rls import setup_tenant_table, teardown_tenant_table

revision: str = "8f236ce675a8"
down_revision: str | None = "7e125bd564f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "fee_sibling_rules"
_CONCESSION_COLUMNS = ("second_concession_id", "third_concession_id", "later_concession_id")


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
        sa.Column("head_id", sa.UUID(), nullable=False),
        sa.Column("second_concession_id", sa.UUID(), nullable=False),
        sa.Column("third_concession_id", sa.UUID(), nullable=True),
        sa.Column("later_concession_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f(f"fk_{_TABLE}_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name=op.f(f"fk_{_TABLE}_school_id_schools"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["head_id"],
            ["fee_heads.id"],
            name=op.f(f"fk_{_TABLE}_head_id_fee_heads"),
            ondelete="RESTRICT",
        ),
        *(
            sa.ForeignKeyConstraint(
                [column],
                ["fee_concessions.id"],
                name=op.f(f"fk_{_TABLE}_{column}_fee_concessions"),
                ondelete="RESTRICT",
            )
            for column in _CONCESSION_COLUMNS
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
        # One rule per campus. Two would make a family's discount depend on which row
        # the review read first.
        sa.UniqueConstraint("school_id", name=f"uq_{_TABLE}_school_id"),
    )
    for column in ("organization_id", "school_id", "head_id", *_CONCESSION_COLUMNS):
        op.create_index(op.f(f"ix_{_TABLE}_{column}"), _TABLE, [column])
    setup_tenant_table(_TABLE)


def downgrade() -> None:
    teardown_tenant_table(_TABLE)
    for column in ("organization_id", "school_id", "head_id", *_CONCESSION_COLUMNS):
        op.drop_index(op.f(f"ix_{_TABLE}_{column}"), table_name=_TABLE)
    op.drop_table(_TABLE)
