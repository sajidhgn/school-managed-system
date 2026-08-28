"""fees: unattended monthly generation, and challans that absorb what is still owed

Revision ID: f9b1d3e5a7c9
Revises: e8a0c2b4d6f8
Create Date: 2026-08-29 01:00:00+00:00

WHY THIS MIGRATION EXISTS
    Two facts the fees schema could not hold, both of which a school states out loud
    on day one:

      1. "WE BILL ON THE 25TH." Generation was entirely manual -- an operator opened
         a dialog per class, per month, and typed the same three dates. A campus with
         eighteen classes does that eighteen times a month, and the failure mode is
         not an error message: it is a class quietly unbilled because somebody was on
         leave, discovered when the money does not arrive.

         `fee_billing_schedules` is that sentence as a row. The cron becomes dumb on
         purpose -- it wakes daily and asks each campus whether today is its day --
         so the part that varies per school lives where the school's owner can read
         it and change it.

      2. "PUT LAST MONTH'S ARREARS ON THIS MONTH'S CHALLAN." The schema already
         snapshotted `arrears_brought_forward` and printed it BESIDE the total,
         deliberately outside it, because the older challan carrying that balance was
         still outstanding and adding it would bill the same rupee twice.

         `superseded_by_voucher_id` is what makes the other answer safe. The new
         challan bills the arrears as a real line AND cancels the challans the money
         came from, so exactly one document is payable and nothing is counted twice.

WHAT AUTOGENERATE WOULD NOT HAVE PRODUCED
    1. RLS on the new table, as always -- `setup_tenant_table()`.

    2. THE PARTIAL UNIQUE INDEX `uq_fee_billing_schedules_one_active`. A plain
       UniqueConstraint on (school_id, academic_year) cannot express it: a superseded
       schedule is switched off and KEPT, so the same campus and year legitimately
       holds several rows and at most one live one. Without the WHERE clause, an
       owner who paused automation in March could never configure it again.

       Two live schedules would mean the day a family is billed depends on which row
       the job happened to read first.

    3. THE SELF-REFERENTIAL FK on `fee_vouchers`, at RESTRICT. A voucher is voided
       rather than deleted so it never fires today; it exists so that if a hard-delete
       path is ever added, removing a consolidating challan cannot silently erase the
       record of why four older ones were cancelled.

WHY THE COLUMN IS NULLABLE AND NOTHING IS BACKFILLED
    Every challan that exists before this migration was billed under the old rule --
    arrears printed, never absorbed -- and that is the truth about them. A backfill
    guessing which older challan "would have been" superseded would invent a
    cancellation that never happened, on financial records that are supposed to be
    immutable.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from alembic.rls import setup_tenant_table, teardown_tenant_table

revision: str = "f9b1d3e5a7c9"
down_revision: str | None = "e8a0c2b4d6f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fee_billing_schedules",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
        sa.Column("academic_year", sa.String(length=9), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("generate_day", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("due_day_offset", sa.Integer(), server_default=sa.text("10"), nullable=False),
        # Both default to the CAUTIOUS setting rather than the convenient one. A
        # school that upgrades into this feature and does not read the form gets
        # drafts for a human to issue, and no re-billed book set.
        sa.Column(
            "issue_immediately", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "include_stationery", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column(
            "carry_forward_dues", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
        sa.Column("carry_forward_head_id", sa.UUID(), nullable=True),
        sa.Column("last_run_period", sa.String(length=40), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_created", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("last_run_skipped", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
            name=op.f("fk_fee_billing_schedules_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name=op.f("fk_fee_billing_schedules_school_id_schools"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["carry_forward_head_id"],
            ["fee_heads.id"],
            name=op.f("fk_fee_billing_schedules_carry_forward_head_id_fee_heads"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fee_billing_schedules")),
        sa.CheckConstraint(
            "generate_day BETWEEN 1 AND 28",
            name=op.f("ck_fee_billing_schedules_generate_day_in_month"),
        ),
        sa.CheckConstraint(
            "due_day_offset BETWEEN 0 AND 90",
            name=op.f("ck_fee_billing_schedules_due_day_offset_reasonable"),
        ),
        sa.CheckConstraint(
            "NOT carry_forward_dues OR carry_forward_head_id IS NOT NULL",
            name=op.f("ck_fee_billing_schedules_carry_forward_needs_head"),
        ),
        sa.CheckConstraint(
            "last_run_created >= 0 AND last_run_skipped >= 0",
            name=op.f("ck_fee_billing_schedules_counts_non_negative"),
        ),
    )
    op.create_index(
        op.f("ix_fee_billing_schedules_organization_id"),
        "fee_billing_schedules",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_fee_billing_schedules_school_id"), "fee_billing_schedules", ["school_id"]
    )
    op.create_index(
        op.f("ix_fee_billing_schedules_deleted_at"), "fee_billing_schedules", ["deleted_at"]
    )
    op.create_index(
        op.f("ix_fee_billing_schedules_carry_forward_head_id"),
        "fee_billing_schedules",
        ["carry_forward_head_id"],
    )
    op.create_index(
        "ix_fee_billing_schedules_school_id_academic_year",
        "fee_billing_schedules",
        ["school_id", "academic_year"],
    )
    # ONE LIVE SCHEDULE PER CAMPUS PER YEAR -- see the header for why this cannot be
    # a UniqueConstraint.
    op.execute(
        "CREATE UNIQUE INDEX uq_fee_billing_schedules_one_active"
        " ON fee_billing_schedules (school_id, academic_year)"
        " WHERE is_active AND deleted_at IS NULL"
    )

    setup_tenant_table("fee_billing_schedules")

    # --- Consolidation ----------------------------------------------------
    op.add_column("fee_vouchers", sa.Column("carry_forward_head_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_fee_vouchers_carry_forward_head_id_fee_heads"),
        "fee_vouchers",
        "fee_heads",
        ["carry_forward_head_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.add_column("fee_vouchers", sa.Column("superseded_by_voucher_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_fee_vouchers_superseded_by_voucher_id_fee_vouchers"),
        "fee_vouchers",
        "fee_vouchers",
        ["superseded_by_voucher_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    # Read once per consolidating issue, to find every challan reserved against the
    # one being issued. Partial: the column is NULL on all but a handful of rows, and
    # a school with five years of challans should not carry a full index of nulls.
    op.execute(
        "CREATE INDEX ix_fee_vouchers_superseded_by_voucher_id"
        " ON fee_vouchers (superseded_by_voucher_id)"
        " WHERE superseded_by_voucher_id IS NOT NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_fee_vouchers_superseded_by_voucher_id")
    op.drop_constraint(
        op.f("fk_fee_vouchers_superseded_by_voucher_id_fee_vouchers"),
        "fee_vouchers",
        type_="foreignkey",
    )
    op.drop_column("fee_vouchers", "superseded_by_voucher_id")
    op.drop_constraint(
        op.f("fk_fee_vouchers_carry_forward_head_id_fee_heads"),
        "fee_vouchers",
        type_="foreignkey",
    )
    op.drop_column("fee_vouchers", "carry_forward_head_id")

    teardown_tenant_table("fee_billing_schedules")
    op.execute("DROP INDEX IF EXISTS uq_fee_billing_schedules_one_active")
    op.drop_index(
        "ix_fee_billing_schedules_school_id_academic_year", table_name="fee_billing_schedules"
    )
    op.drop_index(
        op.f("ix_fee_billing_schedules_carry_forward_head_id"), table_name="fee_billing_schedules"
    )
    op.drop_index(op.f("ix_fee_billing_schedules_deleted_at"), table_name="fee_billing_schedules")
    op.drop_index(op.f("ix_fee_billing_schedules_school_id"), table_name="fee_billing_schedules")
    op.drop_index(
        op.f("ix_fee_billing_schedules_organization_id"), table_name="fee_billing_schedules"
    )
    op.drop_table("fee_billing_schedules")
