"""fees module: heads, structures, vouchers, payments

Revision ID: e1b3c5d7f9a1
Revises: d0a2b4c6e8f0
Create Date: 2026-08-24 01:00:00+00:00

WHY THIS MIGRATION EXISTS
    First slice of the fees module (`docs/modules/fees.md`): what a school bills its
    students, as opposed to `modules/billing`, which is what the school owes
    EduCloud. Six tables in three layers -- heads, structures (+ items), vouchers
    (+ items) and payments.

THE THREE THINGS AUTOGENERATE WOULD NOT HAVE PRODUCED
    1. RLS. Alembic understands tables, columns, indexes and constraints; it has
       never emitted `ENABLE ROW LEVEL SECURITY` or a `CREATE POLICY`. Every one of
       these six tables is tenant-owned, so every one gets `setup_tenant_table()`.
       Missing it on a single table silently exposes that table to every tenant.

    2. The duplicate-billing guard, which is a PARTIAL unique index:

           UNIQUE (school_id, student_id, academic_year, period_label)
           WHERE status <> 'void'

       Partial so that voiding a challan frees the period for a corrected reissue.
       `UniqueConstraint` cannot express a WHERE clause, so it is raw DDL here and a
       comment in the model points at it.

    3. The permission backfill at the bottom. `fee:issue`, `fee:collect` and
       `fee:void` are new codes. A principal provisioned before this migration holds
       the old catalog, and `_PRINCIPAL_PERMISSIONS` is `ALL_CODES` -- so without the
       backfill, every existing principal would get a 403 on every new fee route the
       moment this ships. That is not a seed-time concern; it is a data migration.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from alembic.rls import setup_tenant_table, teardown_tenant_table

revision: str = "e1b3c5d7f9a1"
down_revision: str | None = "d0a2b4c6e8f0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Created children-last, dropped children-first.
_FEE_TABLES = (
    "fee_heads",
    "fee_structures",
    "fee_structure_items",
    "fee_vouchers",
    "fee_voucher_items",
    "fee_payments",
)

# The catalog rows this migration introduces. Kept in sync with
# `app/modules/rbac/catalog.py`; `make seed` upserts the same set, so a fresh
# database and an upgraded one converge on identical data.
_NEW_PERMISSIONS = (
    ("fee:issue", "fee", "issue", "Finance", "Generate and issue fee vouchers.", "school", False),
    (
        "fee:collect",
        "fee",
        "collect",
        "Finance",
        "Record fee payments and issue receipts.",
        "school",
        False,
    ),
    (
        "fee:void",
        "fee",
        "void",
        "Finance",
        "Void a fee voucher or reverse a recorded payment.",
        "school",
        True,
    ),
)

# The wording of the two existing fee codes changed when the module landed. Updated
# in place so the role editor's checkbox labels match the catalog rather than
# describing capabilities that no longer exist in that shape.
_REWORDED_PERMISSIONS = (
    ("fee:read", "View fee heads, structures, vouchers and payments."),
    ("fee:manage", "Define fee heads and fee structures."),
)

_MONEY = sa.Numeric(12, 2)


def _tenant_columns() -> list[sa.Column]:
    """`organization_id` (the RLS key) and `school_id` (the campus scope).

    Both NOT NULL on every table in this module: there is no org-level fee record.
    `organization_id` CASCADEs from `organizations` so offboarding a tenant removes
    its fee data in one statement, which is the GDPR erasure path.
    """
    return [
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
    ]


def _tenant_constraints(table: str) -> list[sa.schema.SchemaItem]:
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


def _tenant_indexes(table: str) -> None:
    """Every RLS policy adds an implicit `WHERE organization_id = ...` to every query
    on the table, so this index sits on the hot path of literally every read."""
    op.create_index(op.f(f"ix_{table}_organization_id"), table, ["organization_id"])
    op.create_index(op.f(f"ix_{table}_school_id"), table, ["school_id"])


def upgrade() -> None:
    # =====================================================================
    # 1. fee_heads -- what may be charged
    # =====================================================================
    op.create_table(
        "fee_heads",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        *_tenant_columns(),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "recurrence",
            sa.Enum(
                "monthly",
                "term",
                "annual",
                "one_time",
                name="recurrence",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("is_refundable", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
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
        *_tenant_constraints("fee_heads"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fee_heads")),
        # Per SCHOOL, not per organization: a trust running three campuses has three
        # legitimate "TUITION" heads at three different amounts.
        sa.UniqueConstraint("school_id", "code", name="uq_fee_heads_school_id_code"),
    )
    _tenant_indexes("fee_heads")
    op.create_index(op.f("ix_fee_heads_deleted_at"), "fee_heads", ["deleted_at"])
    op.create_index("ix_fee_heads_school_id_is_active", "fee_heads", ["school_id", "is_active"])

    # =====================================================================
    # 2. fee_structures -- what one class is charged for one academic year
    # =====================================================================
    op.create_table(
        "fee_structures",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        *_tenant_columns(),
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column("academic_year", sa.String(length=9), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "active",
                "archived",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
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
        *_tenant_constraints("fee_structures"),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["classes.id"],
            name=op.f("fk_fee_structures_class_id_classes"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fee_structures")),
        sa.UniqueConstraint(
            "school_id",
            "class_id",
            "academic_year",
            name="uq_fee_structures_school_id_class_id_academic_year",
        ),
    )
    _tenant_indexes("fee_structures")
    op.create_index(op.f("ix_fee_structures_class_id"), "fee_structures", ["class_id"])
    op.create_index(op.f("ix_fee_structures_deleted_at"), "fee_structures", ["deleted_at"])
    op.create_index("ix_fee_structures_school_id_status", "fee_structures", ["school_id", "status"])

    # =====================================================================
    # 3. fee_structure_items -- head -> amount
    # =====================================================================
    op.create_table(
        "fee_structure_items",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        *_tenant_columns(),
        sa.Column("structure_id", sa.UUID(), nullable=False),
        sa.Column("head_id", sa.UUID(), nullable=False),
        sa.Column("amount", _MONEY, nullable=False),
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
        *_tenant_constraints("fee_structure_items"),
        sa.ForeignKeyConstraint(
            ["structure_id"],
            ["fee_structures.id"],
            name=op.f("fk_fee_structure_items_structure_id_fee_structures"),
            ondelete="CASCADE",
        ),
        # RESTRICT: silently dropping a priced line because someone tidied the head
        # list would change what a class is billed without anyone deciding to.
        sa.ForeignKeyConstraint(
            ["head_id"],
            ["fee_heads.id"],
            name=op.f("fk_fee_structure_items_head_id_fee_heads"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fee_structure_items")),
        sa.UniqueConstraint(
            "structure_id", "head_id", name="uq_fee_structure_items_structure_head"
        ),
        sa.CheckConstraint("amount >= 0", name=op.f("ck_fee_structure_items_amount_non_negative")),
    )
    _tenant_indexes("fee_structure_items")
    op.create_index(
        op.f("ix_fee_structure_items_structure_id"), "fee_structure_items", ["structure_id"]
    )
    op.create_index(op.f("ix_fee_structure_items_head_id"), "fee_structure_items", ["head_id"])

    # =====================================================================
    # 4. fee_vouchers -- the challan. NO deleted_at: voided, never deleted.
    # =====================================================================
    op.create_table(
        "fee_vouchers",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        *_tenant_columns(),
        sa.Column("student_id", sa.UUID(), nullable=False),
        sa.Column("structure_id", sa.UUID(), nullable=True),
        sa.Column("voucher_number", sa.String(length=40), nullable=False),
        sa.Column("academic_year", sa.String(length=9), nullable=False),
        sa.Column("period_label", sa.String(length=40), nullable=False),
        sa.Column("issue_date", sa.Date(), nullable=False),
        sa.Column("due_date", sa.Date(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "issued",
                "partly_paid",
                "paid",
                "overdue",
                "void",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("subtotal", _MONEY, nullable=False),
        sa.Column("discount_total", _MONEY, nullable=False),
        sa.Column("total", _MONEY, nullable=False),
        sa.Column("paid_total", _MONEY, nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("voided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("void_reason", sa.String(length=500), nullable=True),
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
        *_tenant_constraints("fee_vouchers"),
        # RESTRICT: students are soft-deleted, so this never fires in normal
        # operation. It exists so a future hard-delete path cannot quietly destroy a
        # financial record as a side effect.
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name=op.f("fk_fee_vouchers_student_id_students"),
            ondelete="RESTRICT",
        ),
        # SET NULL: the voucher already snapshotted everything it needs; losing the
        # link to its structure must not take the bill with it.
        sa.ForeignKeyConstraint(
            ["structure_id"],
            ["fee_structures.id"],
            name=op.f("fk_fee_vouchers_structure_id_fee_structures"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fee_vouchers")),
        sa.UniqueConstraint(
            "school_id", "voucher_number", name="uq_fee_vouchers_school_id_voucher_number"
        ),
        sa.CheckConstraint(
            "subtotal >= 0 AND discount_total >= 0 AND total >= 0 AND paid_total >= 0",
            name=op.f("ck_fee_vouchers_amounts_non_negative"),
        ),
        sa.CheckConstraint("due_date >= issue_date", name=op.f("ck_fee_vouchers_due_after_issue")),
    )
    _tenant_indexes("fee_vouchers")
    op.create_index(op.f("ix_fee_vouchers_student_id"), "fee_vouchers", ["student_id"])
    op.create_index(op.f("ix_fee_vouchers_structure_id"), "fee_vouchers", ["structure_id"])
    op.create_index("ix_fee_vouchers_school_id_status", "fee_vouchers", ["school_id", "status"])
    op.create_index(
        "ix_fee_vouchers_school_id_student_id", "fee_vouchers", ["school_id", "student_id"]
    )
    op.create_index("ix_fee_vouchers_school_id_due_date", "fee_vouchers", ["school_id", "due_date"])

    # THE DUPLICATE-BILLING GUARD. Partial, so voiding a challan frees the period for
    # a corrected reissue. `UniqueConstraint` cannot express the WHERE clause, which
    # is why this is raw DDL rather than part of the table definition above.
    op.execute(
        """
        CREATE UNIQUE INDEX uq_fee_vouchers_student_period
            ON fee_vouchers (school_id, student_id, academic_year, period_label)
         WHERE status <> 'void'
        """
    )

    # =====================================================================
    # 5. fee_voucher_items -- the snapshot
    # =====================================================================
    op.create_table(
        "fee_voucher_items",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        *_tenant_columns(),
        sa.Column("voucher_id", sa.UUID(), nullable=False),
        sa.Column("head_id", sa.UUID(), nullable=False),
        # The frozen name. Renaming a head must never reword a challan a parent
        # already holds.
        sa.Column("head_name", sa.String(length=120), nullable=False),
        sa.Column("amount", _MONEY, nullable=False),
        sa.Column("discount_amount", _MONEY, nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        *_tenant_constraints("fee_voucher_items"),
        sa.ForeignKeyConstraint(
            ["voucher_id"],
            ["fee_vouchers.id"],
            name=op.f("fk_fee_voucher_items_voucher_id_fee_vouchers"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["head_id"],
            ["fee_heads.id"],
            name=op.f("fk_fee_voucher_items_head_id_fee_heads"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fee_voucher_items")),
        sa.UniqueConstraint("voucher_id", "head_id", name="uq_fee_voucher_items_voucher_head"),
        sa.CheckConstraint(
            "amount >= 0 AND discount_amount >= 0 AND discount_amount <= amount",
            name=op.f("ck_fee_voucher_items_amounts_valid"),
        ),
    )
    _tenant_indexes("fee_voucher_items")
    op.create_index(op.f("ix_fee_voucher_items_voucher_id"), "fee_voucher_items", ["voucher_id"])
    op.create_index(op.f("ix_fee_voucher_items_head_id"), "fee_voucher_items", ["head_id"])

    # =====================================================================
    # 6. fee_payments -- reversed, never deleted
    # =====================================================================
    op.create_table(
        "fee_payments",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        *_tenant_columns(),
        sa.Column("voucher_id", sa.UUID(), nullable=False),
        sa.Column("receipt_number", sa.String(length=40), nullable=False),
        sa.Column("amount", _MONEY, nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "method",
            sa.Enum(
                "cash",
                "bank_transfer",
                "cheque",
                "card",
                "online",
                "other",
                name="method",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("reference", sa.String(length=120), nullable=True),
        sa.Column("received_on", sa.Date(), nullable=False),
        sa.Column("received_by_user_id", sa.UUID(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "recorded",
                "reversed",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("reversed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reversal_reason", sa.String(length=500), nullable=True),
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
        *_tenant_constraints("fee_payments"),
        sa.ForeignKeyConstraint(
            ["voucher_id"],
            ["fee_vouchers.id"],
            name=op.f("fk_fee_payments_voucher_id_fee_vouchers"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["received_by_user_id"],
            ["users.id"],
            name=op.f("fk_fee_payments_received_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fee_payments")),
        sa.UniqueConstraint(
            "school_id", "receipt_number", name="uq_fee_payments_school_id_receipt_number"
        ),
        # Strictly positive: a zero receipt is a data-entry accident, a negative one
        # is a refund pretending to be a payment.
        sa.CheckConstraint("amount > 0", name=op.f("ck_fee_payments_amount_positive")),
    )
    _tenant_indexes("fee_payments")
    op.create_index(op.f("ix_fee_payments_voucher_id"), "fee_payments", ["voucher_id"])
    op.create_index(
        op.f("ix_fee_payments_received_by_user_id"), "fee_payments", ["received_by_user_id"]
    )
    op.create_index(
        "ix_fee_payments_school_id_received_on", "fee_payments", ["school_id", "received_on"]
    )
    op.create_index("ix_fee_payments_school_id_status", "fee_payments", ["school_id", "status"])

    # =====================================================================
    # 7. RLS -- the step autogenerate would never have produced
    # =====================================================================
    for table in _FEE_TABLES:
        setup_tenant_table(table)

    # =====================================================================
    # 8. Permission catalog + backfill
    # =====================================================================
    #
    # Order matters: the catalog rows must exist before `role_permissions` can
    # reference them (FK on `permissions.code`).
    for code, resource, action, category, description, min_scope, dangerous in _NEW_PERMISSIONS:
        op.execute(
            sa.text(
                """
                INSERT INTO permissions
                    (code, resource, action, category, description, min_scope, is_dangerous)
                VALUES (:code, :resource, :action, :category, :description, :min_scope, :dangerous)
                ON CONFLICT (code) DO UPDATE
                    SET category = EXCLUDED.category,
                        description = EXCLUDED.description,
                        min_scope = EXCLUDED.min_scope,
                        is_dangerous = EXCLUDED.is_dangerous
                """
            ).bindparams(
                code=code,
                resource=resource,
                action=action,
                category=category,
                description=description,
                min_scope=min_scope,
                dangerous=dangerous,
            )
        )

    for code, description in _REWORDED_PERMISSIONS:
        op.execute(
            sa.text(
                "UPDATE permissions SET description = :description WHERE code = :code"
            ).bindparams(description=description, code=code)
        )

    # The principal holds the ENTIRE catalog by definition (`_PRINCIPAL_PERMISSIONS =
    # ALL_CODES`). Without this, every principal created before today would get a 403
    # on every fee route the moment this ships -- a broken release, not a seed gap.
    op.execute(
        """
        INSERT INTO role_permissions (role_id, organization_id, permission_code)
        SELECT r.id, r.organization_id, p.code
          FROM roles r
         CROSS JOIN (VALUES ('fee:issue'), ('fee:collect'), ('fee:void')) AS p(code)
         WHERE r.code = 'principal'
           AND r.is_system IS TRUE
        ON CONFLICT DO NOTHING
        """
    )

    # The accountant gains issue and collect. NOT `fee:void`: the person who records
    # money coming in must not be the one who can make a record of it disappear.
    # Customers who want otherwise grant it explicitly. See docs/modules/fees.md §3.
    op.execute(
        """
        INSERT INTO role_permissions (role_id, organization_id, permission_code)
        SELECT r.id, r.organization_id, p.code
          FROM roles r
         CROSS JOIN (VALUES ('fee:issue'), ('fee:collect')) AS p(code)
         WHERE r.code = 'accountant'
           AND r.is_system IS TRUE
        ON CONFLICT DO NOTHING
        """
    )

    # Bump the version on every role whose grants just changed. `core/cache.py` keys
    # the cached permission set on `(role_id, permissions_version)`, so without this
    # a warm cache would keep serving the pre-migration set until it expired -- and
    # the new routes would 403 for exactly as long.
    op.execute(
        """
        UPDATE roles
           SET permissions_version = permissions_version + 1
         WHERE is_system IS TRUE
           AND code IN ('principal', 'accountant')
        """
    )


def downgrade() -> None:
    # Grants first: `role_permissions.permission_code` is RESTRICT, so the catalog
    # rows cannot be removed while any role still references them.
    op.execute(
        "DELETE FROM role_permissions "
        "WHERE permission_code IN ('fee:issue', 'fee:collect', 'fee:void')"
    )
    op.execute(
        "UPDATE roles SET permissions_version = permissions_version + 1 "
        "WHERE is_system IS TRUE AND code IN ('principal', 'accountant')"
    )
    op.execute("DELETE FROM permissions WHERE code IN ('fee:issue', 'fee:collect', 'fee:void')")

    for table in reversed(_FEE_TABLES):
        teardown_tenant_table(table)

    op.execute("DROP INDEX IF EXISTS uq_fee_vouchers_student_period")
    for table in reversed(_FEE_TABLES):
        op.drop_table(table)
