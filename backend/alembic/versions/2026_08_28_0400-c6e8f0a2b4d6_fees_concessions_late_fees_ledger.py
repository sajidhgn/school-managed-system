"""fees: concessions, per-student overrides, late-fee policy and the student ledger

Revision ID: c6e8f0a2b4d6
Revises: b5d7f9a1c3e5
Create Date: 2026-08-28 04:00:00+00:00

WHY THIS MIGRATION EXISTS
    It closes the four deferrals `docs/modules/fees.md` §2 recorded as "considered and
    deferred; none requires a table rewrite to add". That claim is now tested: every
    change below is additive, and no existing column changes meaning.

        1. SCHOLARSHIPS AND CONCESSIONS -- `fee_concessions` holds the named scheme,
           and `student_fee_assignments` gains a DISCOUNT mode that either points at
           one or carries its own rate. The `discount_amount` column that has been on
           `fee_voucher_items` since slice 1, zero on every row, now gets written.

        2. PER-STUDENT OVERRIDES -- an OVERRIDE mode on the same table, restating a
           class line's amount rather than adding a line beside it.

        3. AUTOMATIC LATE FEES -- `fee_late_fee_policies` holds the rule, and
           `fee_vouchers` gains `origin` and `source_voucher_id` so a fine can be its
           own challan pointing back at the one it punishes.

        4. THE RUNNING LEDGER -- `student_ledger_entries`, append-only, plus
           `fee_vouchers.arrears_brought_forward` to snapshot the balance a challan
           was printed with.

=============================================================================
THE FINE IS A NEW CHALLAN, WHICH IS WHY `fee_vouchers` NEEDED TWO COLUMNS
=============================================================================
    Rule 1 of this module is that an issued bill is never rewritten. A fine assessed
    three weeks after issue would rewrite one -- so it cannot be a line added to the
    late challan, and the alternative of a separate "fines" table would need its own
    numbering, its own payment path, its own PDF and its own void path, all parallel
    to machinery that already exists and is already audited.

    So the late-fee job MINTS a voucher. `origin` says what produced it and
    `source_voucher_id` says which challan it punishes, which is also how a recurring
    policy counts what it has already charged instead of fining the same delay twice.

=============================================================================
ARREARS ARE SNAPSHOTTED, NOT BILLED -- and the column name says so
=============================================================================
    `arrears_brought_forward` is printed on the challan and deliberately NOT added to
    `total`. Adding it would bill the same rupee twice: once on the older challan
    that is still outstanding, and again here. The school would discover it at the
    counter, with the parent holding both pieces of paper.

THINGS AUTOGENERATE WOULD NOT HAVE PRODUCED
    1. RLS on all three new tables. Autogenerate has never emitted a policy. A fee
       concession table without one exposes which families at every school in the
       system are on charity.

    2. The REPLACED `ck_student_fee_assignments_mode` and
       `ck_student_fee_assignments_amount_matches_mode`. The mode column is a VARCHAR
       with a CHECK (native_enum=False), so widening the enum means dropping and
       recreating the constraint -- autogenerate emits neither.

    3. `uq_fee_late_fee_policies_one_active` -- a PARTIAL unique index. Two live
       policies for one school-year would make the fine a family owes depend on which
       row the job happened to read first.

    4. `ix_student_ledger_entries_school_id_student_id_created_at`, which every
       statement read and every `append()` balance lock uses.

NO NEW PERMISSION CODES, so no catalog rows and no role backfill. A concession scheme
and a fine policy are both `fee:manage` -- they answer the question fee heads answer,
what this campus may put on a challan. A manual ledger adjustment is `fee:void`,
because it is the one action here that can make money disappear with no receipt
behind it. See the note in `fees/router.py`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from alembic.rls import setup_tenant_table, teardown_tenant_table

revision: str = "c6e8f0a2b4d6"
down_revision: str | None = "b5d7f9a1c3e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# The four modes a per-student arrangement may take, after this migration. Spelled
# out here rather than imported from the model: a migration must keep describing the
# database as it was when it ran, and an import would silently re-point at whatever
# the enum becomes three releases from now.
_MODES = ("added", "excluded", "override", "discount")

# Written once and reused by upgrade/downgrade so the two cannot drift apart.
_AMOUNT_MATCHES_MODE = (
    "(mode = 'added' AND amount IS NOT NULL AND amount >= 0"
    " AND percent IS NULL AND concession_id IS NULL)"
    " OR (mode = 'excluded' AND amount IS NULL"
    " AND percent IS NULL AND concession_id IS NULL)"
    " OR (mode = 'override' AND amount IS NOT NULL AND amount >= 0"
    " AND percent IS NULL AND concession_id IS NULL)"
    " OR (mode = 'discount' AND ("
    "   (concession_id IS NOT NULL AND amount IS NULL AND percent IS NULL)"
    "   OR (concession_id IS NULL AND amount IS NOT NULL AND amount >= 0"
    "       AND percent IS NULL)"
    "   OR (concession_id IS NULL AND percent IS NOT NULL"
    "       AND percent > 0 AND percent <= 100 AND amount IS NULL)"
    " ))"
)

_LEGACY_AMOUNT_MATCHES_MODE = (
    "(mode = 'added' AND amount IS NOT NULL AND amount >= 0)"
    " OR (mode = 'excluded' AND amount IS NULL)"
)


def _timestamps() -> list[sa.Column[sa.DateTime]]:
    return [
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
    ]


def _tenant_columns() -> list[sa.Column[sa.Uuid]]:
    return [
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
    ]


def _tenant_fks(table: str) -> list[sa.ForeignKeyConstraint]:
    return [
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f(f"fk_{table}_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name=op.f(f"fk_{table}_school_id_schools"),
            ondelete="CASCADE",
        ),
    ]


def upgrade() -> None:
    # =====================================================================
    # 1. Fee concessions -- the named scheme a family is put ON
    # =====================================================================
    op.create_table(
        "fee_concessions",
        *_tenant_columns(),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "kind",
            sa.Enum(
                "percent",
                "amount",
                name="kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("value", sa.Numeric(12, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        *_timestamps(),
        *_tenant_fks("fee_concessions"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fee_concessions")),
        sa.UniqueConstraint("school_id", "code", name="uq_fee_concessions_school_id_code"),
        # A percentage over 100 is a scheme that pays the family to attend, and a
        # zero-value scheme is a scheme that does nothing -- both are data-entry
        # accidents rather than policies anyone agreed.
        sa.CheckConstraint(
            "(kind = 'percent' AND value > 0 AND value <= 100) OR (kind = 'amount' AND value > 0)",
            name=op.f("ck_fee_concessions_value_matches_kind"),
        ),
    )
    op.create_index(
        op.f("ix_fee_concessions_organization_id"), "fee_concessions", ["organization_id"]
    )
    op.create_index(op.f("ix_fee_concessions_school_id"), "fee_concessions", ["school_id"])
    op.create_index(op.f("ix_fee_concessions_deleted_at"), "fee_concessions", ["deleted_at"])
    setup_tenant_table("fee_concessions")

    # =====================================================================
    # 2. Per-student arrangements gain DISCOUNT and OVERRIDE
    # =====================================================================
    op.add_column("student_fee_assignments", sa.Column("percent", sa.Numeric(5, 2), nullable=True))
    op.add_column("student_fee_assignments", sa.Column("concession_id", sa.UUID(), nullable=True))
    op.create_index(
        op.f("ix_student_fee_assignments_concession_id"),
        "student_fee_assignments",
        ["concession_id"],
    )
    op.create_foreign_key(
        op.f("fk_student_fee_assignments_concession_id_fee_concessions"),
        "student_fee_assignments",
        "fee_concessions",
        ["concession_id"],
        ["id"],
        # RESTRICT: deleting a scheme children are still on would silently restore
        # them to full fees, and nobody would find out until the challans printed.
        ondelete="RESTRICT",
    )

    # `mode` is a VARCHAR with a CHECK (native_enum=False), so widening the enum is a
    # constraint swap rather than an ALTER TYPE. Both constraints are dropped and
    # rebuilt; no existing row changes, because every one of them is 'added' or
    # 'excluded' and both remain legal.
    op.drop_constraint("ck_student_fee_assignments_mode", "student_fee_assignments")
    op.create_check_constraint(
        "mode",
        "student_fee_assignments",
        sa.text("mode IN :modes").bindparams(sa.bindparam("modes", _MODES, expanding=True)),
    )
    op.drop_constraint("ck_student_fee_assignments_amount_matches_mode", "student_fee_assignments")
    op.create_check_constraint(
        "amount_matches_mode", "student_fee_assignments", _AMOUNT_MATCHES_MODE
    )

    # =====================================================================
    # 3. Late fee policy -- the rule the fine job applies
    # =====================================================================
    op.create_table(
        "fee_late_fee_policies",
        *_tenant_columns(),
        sa.Column("academic_year", sa.String(length=9), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("head_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "fixed",
                "percent",
                name="kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("value", sa.Numeric(12, 2), nullable=False),
        sa.Column("grace_days", sa.Integer(), nullable=False),
        sa.Column(
            "recurrence",
            sa.Enum(
                "once",
                "weekly",
                "monthly",
                name="recurrence",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("max_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("min_outstanding", sa.Numeric(12, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        *_timestamps(),
        *_tenant_fks("fee_late_fee_policies"),
        # RESTRICT: deleting the head a year of fines was billed under would orphan
        # the reason those challans exist.
        sa.ForeignKeyConstraint(
            ["head_id"],
            ["fee_heads.id"],
            name=op.f("fk_fee_late_fee_policies_head_id_fee_heads"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fee_late_fee_policies")),
        sa.CheckConstraint("value > 0", name=op.f("ck_fee_late_fee_policies_value_positive")),
        sa.CheckConstraint(
            "grace_days >= 0 AND grace_days <= 365",
            name=op.f("ck_fee_late_fee_policies_grace_days_sane"),
        ),
        sa.CheckConstraint(
            "max_amount IS NULL OR max_amount > 0",
            name=op.f("ck_fee_late_fee_policies_max_amount_positive"),
        ),
        sa.CheckConstraint(
            "min_outstanding >= 0",
            name=op.f("ck_fee_late_fee_policies_min_outstanding_non_negative"),
        ),
        sa.CheckConstraint(
            "kind <> 'percent' OR (value > 0 AND value <= 100)",
            name=op.f("ck_fee_late_fee_policies_percent_within_range"),
        ),
    )
    op.create_index(
        op.f("ix_fee_late_fee_policies_organization_id"),
        "fee_late_fee_policies",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_fee_late_fee_policies_school_id"), "fee_late_fee_policies", ["school_id"]
    )
    op.create_index(
        op.f("ix_fee_late_fee_policies_deleted_at"), "fee_late_fee_policies", ["deleted_at"]
    )
    op.create_index(op.f("ix_fee_late_fee_policies_head_id"), "fee_late_fee_policies", ["head_id"])
    op.create_index(
        "ix_fee_late_fee_policies_school_id_academic_year",
        "fee_late_fee_policies",
        ["school_id", "academic_year"],
    )
    # ONE LIVE POLICY PER SCHOOL PER YEAR. Partial, so retired and soft-deleted
    # policies do not collide with the current one -- last year's rule must stay on
    # file to explain last year's fines.
    op.create_index(
        "uq_fee_late_fee_policies_one_active",
        "fee_late_fee_policies",
        ["school_id", "academic_year"],
        unique=True,
        postgresql_where=sa.text("is_active AND deleted_at IS NULL"),
    )
    setup_tenant_table("fee_late_fee_policies")

    # =====================================================================
    # 4. Vouchers learn where they came from, and what was owed before them
    # =====================================================================
    op.add_column(
        "fee_vouchers",
        sa.Column(
            "origin",
            sa.Enum(
                "regular",
                "late_fee",
                name="origin",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
            # Every voucher that predates this migration is a regular challan, so the
            # default backfills them correctly and no data migration is needed.
            server_default="regular",
        ),
    )
    op.add_column("fee_vouchers", sa.Column("source_voucher_id", sa.UUID(), nullable=True))
    op.add_column(
        "fee_vouchers",
        sa.Column(
            "arrears_brought_forward",
            sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        op.f("ix_fee_vouchers_source_voucher_id"), "fee_vouchers", ["source_voucher_id"]
    )
    op.create_foreign_key(
        op.f("fk_fee_vouchers_source_voucher_id_fee_vouchers"),
        "fee_vouchers",
        "fee_vouchers",
        ["source_voucher_id"],
        ["id"],
        # RESTRICT both ways: a fine and the challan it punishes are both financial
        # records, and destroying one must not take the other with it.
        ondelete="RESTRICT",
    )

    # =====================================================================
    # 5. The student ledger -- append-only running account
    # =====================================================================
    op.create_table(
        "student_ledger_entries",
        *_tenant_columns(),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column(
            "entry_type",
            sa.Enum(
                "charge",
                "payment",
                "payment_reversed",
                "voucher_voided",
                "late_fee",
                "adjustment",
                name="entry_type",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("voucher_id", sa.UUID(), nullable=True),
        sa.Column("payment_id", sa.UUID(), nullable=True),
        sa.Column("academic_year", sa.String(length=9), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("balance_after", sa.Numeric(12, 2), nullable=False),
        sa.Column("occurred_on", sa.Date(), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        # APPEND-ONLY: created_at and nothing else. No `updated_at` because no path
        # updates a row here, and no `deleted_at` because a correction is a new entry.
        # The missing columns are the contract.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        *_tenant_fks("student_ledger_entries"),
        # RESTRICT throughout: every row here is a financial record and must outlive
        # any deletion path that touches what it points at.
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name=op.f("fk_student_ledger_entries_student_id_students"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["voucher_id"],
            ["fee_vouchers.id"],
            name=op.f("fk_student_ledger_entries_voucher_id_fee_vouchers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["payment_id"],
            ["fee_payments.id"],
            name=op.f("fk_student_ledger_entries_payment_id_fee_payments"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_student_ledger_entries_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_student_ledger_entries")),
        # A zero-value movement is a row saying nothing happened -- it lengthens a
        # statement without informing it, and hides the entries that matter.
        sa.CheckConstraint("amount <> 0", name=op.f("ck_student_ledger_entries_amount_non_zero")),
        sa.CheckConstraint(
            "(entry_type = 'adjustment') OR voucher_id IS NOT NULL OR payment_id IS NOT NULL",
            name=op.f("ck_student_ledger_entries_entry_has_justification"),
        ),
    )
    op.create_index(
        op.f("ix_student_ledger_entries_organization_id"),
        "student_ledger_entries",
        ["organization_id"],
    )
    op.create_index(
        op.f("ix_student_ledger_entries_school_id"), "student_ledger_entries", ["school_id"]
    )
    op.create_index(
        op.f("ix_student_ledger_entries_student_id"), "student_ledger_entries", ["student_id"]
    )
    op.create_index(
        op.f("ix_student_ledger_entries_voucher_id"), "student_ledger_entries", ["voucher_id"]
    )
    op.create_index(
        op.f("ix_student_ledger_entries_payment_id"), "student_ledger_entries", ["payment_id"]
    )
    op.create_index(
        op.f("ix_student_ledger_entries_created_by_user_id"),
        "student_ledger_entries",
        ["created_by_user_id"],
    )
    # THE INDEX EVERY READ USES: one student's statement in order, and the balance
    # lock `append()` takes to derive the next running total.
    op.create_index(
        "ix_student_ledger_entries_school_id_student_id_created_at",
        "student_ledger_entries",
        ["school_id", "student_id", "created_at"],
    )
    op.create_index(
        "ix_student_ledger_entries_school_id_academic_year",
        "student_ledger_entries",
        ["school_id", "academic_year"],
    )
    setup_tenant_table("student_ledger_entries")


def downgrade() -> None:
    teardown_tenant_table("student_ledger_entries")
    for index in (
        "ix_student_ledger_entries_school_id_academic_year",
        "ix_student_ledger_entries_school_id_student_id_created_at",
        op.f("ix_student_ledger_entries_created_by_user_id"),
        op.f("ix_student_ledger_entries_payment_id"),
        op.f("ix_student_ledger_entries_voucher_id"),
        op.f("ix_student_ledger_entries_student_id"),
        op.f("ix_student_ledger_entries_school_id"),
        op.f("ix_student_ledger_entries_organization_id"),
    ):
        op.drop_index(index, table_name="student_ledger_entries")
    op.drop_table("student_ledger_entries")

    op.drop_constraint(
        op.f("fk_fee_vouchers_source_voucher_id_fee_vouchers"), "fee_vouchers", type_="foreignkey"
    )
    op.drop_index(op.f("ix_fee_vouchers_source_voucher_id"), table_name="fee_vouchers")
    op.drop_column("fee_vouchers", "arrears_brought_forward")
    op.drop_column("fee_vouchers", "source_voucher_id")
    # Dropping the column takes its CHECK with it, so `ck_fee_vouchers_origin` needs
    # no separate statement.
    op.drop_column("fee_vouchers", "origin")

    teardown_tenant_table("fee_late_fee_policies")
    for index in (
        "uq_fee_late_fee_policies_one_active",
        "ix_fee_late_fee_policies_school_id_academic_year",
        op.f("ix_fee_late_fee_policies_head_id"),
        op.f("ix_fee_late_fee_policies_deleted_at"),
        op.f("ix_fee_late_fee_policies_school_id"),
        op.f("ix_fee_late_fee_policies_organization_id"),
    ):
        op.drop_index(index, table_name="fee_late_fee_policies")
    op.drop_table("fee_late_fee_policies")

    # Back to the two-mode world. Any DISCOUNT or OVERRIDE row would violate the
    # restored constraint, so they are removed FIRST and deliberately: a downgrade
    # that leaves rows the schema forbids is a downgrade that fails halfway.
    op.execute("DELETE FROM student_fee_assignments WHERE mode IN ('discount', 'override')")
    op.drop_constraint("ck_student_fee_assignments_amount_matches_mode", "student_fee_assignments")
    op.create_check_constraint(
        "amount_matches_mode", "student_fee_assignments", _LEGACY_AMOUNT_MATCHES_MODE
    )
    op.drop_constraint("ck_student_fee_assignments_mode", "student_fee_assignments")
    op.create_check_constraint(
        "mode",
        "student_fee_assignments",
        sa.text("mode IN :modes").bindparams(
            sa.bindparam("modes", ("added", "excluded"), expanding=True)
        ),
    )
    op.drop_constraint(
        op.f("fk_student_fee_assignments_concession_id_fee_concessions"),
        "student_fee_assignments",
        type_="foreignkey",
    )
    op.drop_index(
        op.f("ix_student_fee_assignments_concession_id"), table_name="student_fee_assignments"
    )
    op.drop_column("student_fee_assignments", "concession_id")
    op.drop_column("student_fee_assignments", "percent")

    teardown_tenant_table("fee_concessions")
    for index in (
        op.f("ix_fee_concessions_deleted_at"),
        op.f("ix_fee_concessions_school_id"),
        op.f("ix_fee_concessions_organization_id"),
    ):
        op.drop_index(index, table_name="fee_concessions")
    op.drop_table("fee_concessions")
