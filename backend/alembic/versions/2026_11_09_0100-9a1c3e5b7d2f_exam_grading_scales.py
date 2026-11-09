"""exams: the campus grading scale

Revision ID: 9a1c3e5b7d2f
Revises: 8f236ce675a8
Create Date: 2026-11-09 10:00:00+00:00

WHY THIS MIGRATION EXISTS
    The result card graded on one scale hard-coded in the browser, and the result
    sheet and parent portal did not grade at all. A campus had nowhere to say which
    percentage earns an A, and the three surfaces could not agree.

WHAT CHANGES
    One table, `exam_grading_scales`, one row per campus: the bands as one JSONB
    document (see `ExamGradingScale` for why one document rather than a row per band).
    Grades are computed when a sheet is read; no mark, paper or exam column changes.

    NOTHING IS BACKFILLED. A campus with no row grades on the board scale the result
    card has always printed (`grading.BOARD_SCALE`), so this migration changes no
    grade anywhere; a row appears only when a campus saves a scale of its own.

THINGS AUTOGENERATE WOULD NOT HAVE PRODUCED
    RLS on the new table, like every tenant table.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from alembic.rls import setup_tenant_table, teardown_tenant_table
from sqlalchemy.dialects import postgresql

revision: str = "9a1c3e5b7d2f"
down_revision: str | None = "8f236ce675a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "exam_grading_scales"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
        sa.Column("bands", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{_TABLE}")),
        # One scale per campus. Two would grade the same child twice.
        sa.UniqueConstraint("school_id", name=f"uq_{_TABLE}_school_id"),
        # A JSON array, never an object or a scalar: the reader iterates it.
        sa.CheckConstraint(
            "jsonb_typeof(bands) = 'array'", name=op.f(f"ck_{_TABLE}_bands_is_array")
        ),
    )
    for column in ("organization_id", "school_id"):
        op.create_index(op.f(f"ix_{_TABLE}_{column}"), _TABLE, [column])
    setup_tenant_table(_TABLE)


def downgrade() -> None:
    teardown_tenant_table(_TABLE)
    for column in ("organization_id", "school_id"):
        op.drop_index(op.f(f"ix_{_TABLE}_{column}"), table_name=_TABLE)
    op.drop_table(_TABLE)
