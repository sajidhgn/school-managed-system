"""fees: per-student fee assignments (optional services)

Revision ID: b5d7f9a1c3e5
Revises: a4c6e8b0d2f4
Create Date: 2026-08-28 03:00:00+00:00

WHY THIS MIGRATION EXISTS
    Students in one class are not all charged the same thing. One takes the bus, one
    boards, one walks. Until now the only answer was the class structure, which bills
    every student in the class identically.

    This adds ONE table recording where a single student DEPARTS from their class:
    a head they pay that the class does not (at their own rate -- transport is priced
    by route), or a head the class pays that they do not.

=============================================================================
A DELTA TABLE, NOT A PER-STUDENT FEE PLAN
=============================================================================
    The obvious alternative -- give every student their own complete list of heads
    and amounts -- was rejected. Two days decide it:

      * A NEW ADMISSION arrives mid-term. With a delta the child is billed correctly
        the moment they are placed in a section, because the class structure already
        says what Grade 10 pays. With per-student plans somebody must type six lines
        first, and the day they forget, the child is billed NOTHING and nobody
        notices until year-end.

      * TUITION RISES 8%. One edit to the structure and everyone on the standard rate
        follows. Per-student plans mean five hundred edits, and the missed ones are
        invisible because there is no "standard" left to compare against.

    So a student with no rows in this table is billed their class's structure exactly
    -- the overwhelmingly common case, costing nothing to express.

THINGS AUTOGENERATE WOULD NOT HAVE PRODUCED
    1. RLS. The table is tenant-owned, so it gets `setup_tenant_table()`. Missing it
       would expose every school's fee arrangements to every other tenant.

    2. `ck_..._amount_matches_mode`. An ADDED row must carry an amount and an
       EXCLUDED row must not: an excluded head means the line is ABSENT from the
       challan, not zero, and a "Transport 0.00" row is a question a parent phones
       about. Without the CHECK, a row's two halves can disagree about what it means.

    3. `ix_student_fee_assignments_school_id_academic_year`. Generation fetches the
       assignments for up to 500 students in one query keyed on exactly these
       columns. Without it, every billing run sequentially scans the school's whole
       assignment table.

NO NEW PERMISSION CODES, so no catalog rows and no role backfill. Assigning a student
to a head is `fee:manage` -- it is a pricing decision that recurs, the same kind of
decision as adding a line to a structure. See the note in `fees/router.py`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from alembic.rls import setup_tenant_table, teardown_tenant_table

revision: str = "b5d7f9a1c3e5"
down_revision: str | None = "a4c6e8b0d2f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "student_fee_assignments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("head_id", sa.UUID(), nullable=False),
        sa.Column("academic_year", sa.String(length=9), nullable=False),
        sa.Column(
            "mode",
            sa.Enum(
                "added",
                "excluded",
                name="mode",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("note", sa.String(length=500), nullable=True),
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
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_student_fee_assignments_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name=op.f("fk_student_fee_assignments_school_id_schools"),
            ondelete="CASCADE",
        ),
        # CASCADE, unlike `fee_vouchers.student_id` which is RESTRICT. The difference
        # is deliberate: a voucher is a financial record that must outlive any
        # deletion path, while this row is configuration. If a student row is ever
        # truly destroyed, "Ali takes the bus" is meaningless and should go with it.
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name=op.f("fk_student_fee_assignments_student_id_students"),
            ondelete="CASCADE",
        ),
        # RESTRICT, matching `fee_structure_items.head_id`. Tidying the head list must
        # not silently stop billing a student for their hostel place -- damage that
        # stays invisible until the money does not arrive.
        sa.ForeignKeyConstraint(
            ["head_id"],
            ["fee_heads.id"],
            name=op.f("fk_student_fee_assignments_head_id_fee_heads"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_student_fee_assignments")),
        # One arrangement per head per student per year. A student cannot be both
        # charged and not charged for transport, nor added twice at two rates.
        sa.UniqueConstraint(
            "student_id",
            "academic_year",
            "head_id",
            name="uq_student_fee_assignments_student_year_head",
        ),
        sa.CheckConstraint(
            "(mode = 'added' AND amount IS NOT NULL AND amount >= 0)"
            " OR (mode = 'excluded' AND amount IS NULL)",
            name=op.f("ck_student_fee_assignments_amount_matches_mode"),
        ),
    )
    op.create_index(
        op.f("ix_student_fee_assignments_organization_id"),
        "student_fee_assignments",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_student_fee_assignments_school_id"), "student_fee_assignments", ["school_id"]
    )
    op.create_index(
        op.f("ix_student_fee_assignments_deleted_at"), "student_fee_assignments", ["deleted_at"]
    )
    op.create_index(
        op.f("ix_student_fee_assignments_student_id"), "student_fee_assignments", ["student_id"]
    )
    op.create_index(
        op.f("ix_student_fee_assignments_head_id"), "student_fee_assignments", ["head_id"]
    )
    # THE INDEX GENERATION READS -- see the header.
    op.create_index(
        "ix_student_fee_assignments_school_id_academic_year",
        "student_fee_assignments",
        ["school_id", "academic_year"],
    )

    setup_tenant_table("student_fee_assignments")


def downgrade() -> None:
    teardown_tenant_table("student_fee_assignments")
    op.drop_index(
        "ix_student_fee_assignments_school_id_academic_year",
        table_name="student_fee_assignments",
    )
    op.drop_index(op.f("ix_student_fee_assignments_head_id"), table_name="student_fee_assignments")
    op.drop_index(
        op.f("ix_student_fee_assignments_student_id"), table_name="student_fee_assignments"
    )
    op.drop_index(
        op.f("ix_student_fee_assignments_deleted_at"), table_name="student_fee_assignments"
    )
    op.drop_index(
        op.f("ix_student_fee_assignments_school_id"), table_name="student_fee_assignments"
    )
    op.drop_index(
        op.f("ix_student_fee_assignments_organization_id"), table_name="student_fee_assignments"
    )
    op.drop_table("student_fee_assignments")
