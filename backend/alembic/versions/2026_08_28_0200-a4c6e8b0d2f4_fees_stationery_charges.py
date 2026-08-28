"""fees: stationery catalog and quantity-priced challan lines

Revision ID: a4c6e8b0d2f4
Revises: f3a5c7e9b1d3
Create Date: 2026-08-28 02:00:00+00:00

WHY THIS MIGRATION EXISTS
    A school does not only charge fees, it SELLS things: copies, pencils, books,
    uniform. Those cannot be modelled as fee heads, because a head is a flat amount
    per period while an article is a unit price times a count that differs per
    student. A head per (article, quantity) pair would need four hundred heads for a
    forty-article catalog by December.

    So this adds one table -- `stationery_items`, the price list -- and teaches the
    two existing line tables to carry a line of either kind.

=============================================================================
THE LINE TABLES ARE WIDENED, NOT DUPLICATED
=============================================================================
    The tempting alternative was a parallel `fee_voucher_stationery_items` table.
    It was rejected: the voucher's subtotal would then be a sum over two tables, the
    challan renderer would iterate two lists with no defined order between them, and
    every future report would have to remember to UNION both or silently under-count.

    Instead both item tables gain a `line_type` discriminator, a nullable
    `stationery_item_id` beside the now-nullable `head_id`, and a `quantity` /
    `unit_price` pair whose product is the `amount` column that already existed. A
    fee line stores quantity 1 and unit_price = amount, so every total in the module
    keeps summing exactly one column and never has to ask what it is adding.

FIVE THINGS AUTOGENERATE WOULD NOT HAVE PRODUCED
    1. RLS on `stationery_items`. Alembic has never emitted `CREATE POLICY`; the
       table is tenant-owned, so it gets `setup_tenant_table()` like the other seven.

    2. The BACKFILL. `line_type`, `quantity` and `unit_price` are NOT NULL on tables
       that already hold rows. Each is added nullable, filled from what the row
       already means (every existing line is a fee line of one unit at its own
       amount), and only then made NOT NULL. Adding them NOT NULL with a server
       default would work too and would leave a default on the column that the model
       does not declare -- drift that autogenerate would then try to "fix" forever.

    3. The PARTIAL unique indexes. `UNIQUE (voucher_id, head_id)` cannot survive
       `head_id` becoming nullable: in PostgreSQL every NULL is distinct, so the
       constraint would permit unlimited duplicate stationery lines while still
       looking like it guaranteed something. Each old constraint is replaced by two
       partial indexes with `WHERE ... IS NOT NULL`, which `UniqueConstraint` cannot
       express.

    4. The `line_type_matches_reference` CHECKs, which make "a stationery line that
       points at a fee head" unrepresentable rather than merely undocumented.

    5. The RENAME of `fee_voucher_items.head_name` to `line_name`. A drop-and-add
       would destroy the snapshot that is the entire point of the column -- every
       challan ever issued would lose the frozen text it prints.

NO NEW PERMISSION CODES, so no catalog rows and no role backfill.
    The catalog is `fee:manage` (what may be charged) and charging an article is
    `fee:issue` (who is charged). See the note at the top of `fees/router.py`.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from alembic.rls import setup_tenant_table, teardown_tenant_table

revision: str = "a4c6e8b0d2f4"
down_revision: str | None = "f3a5c7e9b1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MONEY = sa.Numeric(12, 2)
_QUANTITY = sa.Numeric(10, 2)

# The two tables that gain a line type. Their migrations are near-identical, so the
# shared steps are driven off this rather than written twice and drifting apart.
_LINE_TABLES = ("fee_structure_items", "fee_voucher_items")

# Declared as a plain VARCHAR here, with the CHECK created by hand below, rather
# than as `sa.Enum(..., create_constraint=True)`. Inside `create_table` that form
# emits the constraint; through `op.add_column` it does not reliably do so, and the
# failure is silent -- the column ships with no CHECK at all while the model believes
# `ck_<table>_line_type` exists and a later autogenerate proposes to "add" it. The
# name below is the one `app/db/base.py`'s naming convention produces for
# `str_enum(FeeLineType, name="line_type")`, and it must stay in step with it.
_LINE_TYPE = sa.String(length=32)


def upgrade() -> None:
    # =====================================================================
    # 1. stationery_items -- the price list
    # =====================================================================
    op.create_table(
        "stationery_items",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
        sa.Column("code", sa.String(length=40), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "category",
            sa.Enum(
                "book",
                "notebook",
                "stationery",
                "uniform",
                "sports",
                "other",
                name="stationery_category",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "unit",
            sa.Enum(
                "piece",
                "dozen",
                "pack",
                "set",
                "pair",
                "ream",
                name="stationery_unit",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("unit_price", _MONEY, nullable=False),
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
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_stationery_items_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name=op.f("fk_stationery_items_school_id_schools"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_stationery_items")),
        # Per SCHOOL, exactly like `fee_heads.code`: two campuses of one trust sell
        # their own copies at their own prices.
        sa.UniqueConstraint("school_id", "code", name="uq_stationery_items_school_id_code"),
        sa.CheckConstraint(
            "unit_price >= 0", name=op.f("ck_stationery_items_unit_price_non_negative")
        ),
    )
    op.create_index(
        op.f("ix_stationery_items_organization_id"), "stationery_items", ["organization_id"]
    )
    op.create_index(op.f("ix_stationery_items_school_id"), "stationery_items", ["school_id"])
    op.create_index(op.f("ix_stationery_items_deleted_at"), "stationery_items", ["deleted_at"])
    op.create_index(
        "ix_stationery_items_school_id_is_active", "stationery_items", ["school_id", "is_active"]
    )
    op.create_index(
        "ix_stationery_items_school_id_category", "stationery_items", ["school_id", "category"]
    )

    # RLS. The step autogenerate would never have produced, and the one whose absence
    # would silently expose every tenant's catalog to every other tenant.
    setup_tenant_table("stationery_items")

    # =====================================================================
    # 2. Both line tables gain the discriminator and the unit pricing
    # =====================================================================
    for table in _LINE_TABLES:
        # Added NULLABLE, backfilled, then tightened -- see the header. Every row that
        # exists today is a fee line of one unit priced at its own amount, which is
        # what these three statements say.
        op.add_column(table, sa.Column("line_type", _LINE_TYPE, nullable=True))
        op.add_column(table, sa.Column("stationery_item_id", sa.UUID(), nullable=True))
        op.add_column(table, sa.Column("quantity", _QUANTITY, nullable=True))
        op.add_column(table, sa.Column("unit_price", _MONEY, nullable=True))

        op.execute(f"UPDATE {table} SET line_type = 'fee', quantity = 1, unit_price = amount")

        op.alter_column(table, "line_type", nullable=False)
        op.alter_column(table, "quantity", nullable=False)
        op.alter_column(table, "unit_price", nullable=False)

        # RESTRICT, matching `head_id`: tidying the catalog must never change what a
        # class is charged or what a challan says it charged.
        op.create_foreign_key(
            op.f(f"fk_{table}_stationery_item_id_stationery_items"),
            table,
            "stationery_items",
            ["stationery_item_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        op.create_index(op.f(f"ix_{table}_stationery_item_id"), table, ["stationery_item_id"])

        # A stationery line has no head, so the column can no longer be NOT NULL. The
        # CHECK below is what keeps it required on every line that is a fee line --
        # the only place the constraint ever meant anything.
        op.alter_column(table, "head_id", existing_type=sa.UUID(), nullable=True)

        op.create_check_constraint(
            op.f(f"ck_{table}_line_type"), table, "line_type IN ('fee', 'stationery')"
        )
        op.create_check_constraint(op.f(f"ck_{table}_quantity_positive"), table, "quantity > 0")
        op.create_check_constraint(
            op.f(f"ck_{table}_unit_price_non_negative"), table, "unit_price >= 0"
        )
        op.create_check_constraint(
            op.f(f"ck_{table}_line_type_matches_reference"),
            table,
            "(line_type = 'fee' AND head_id IS NOT NULL AND stationery_item_id IS NULL)"
            " OR (line_type = 'stationery'"
            " AND stationery_item_id IS NOT NULL AND head_id IS NULL)",
        )

    # =====================================================================
    # 3. Uniqueness, re-expressed as PARTIAL indexes
    # =====================================================================
    #
    # THE STEP THAT IS EASY TO GET WRONG. `UNIQUE (structure_id, head_id)` looks like
    # it still works once `head_id` is nullable, and it does not: PostgreSQL treats
    # every NULL as distinct, so it would happily accept fifty stationery lines for
    # the same article while continuing to appear to guarantee uniqueness. Each
    # constraint is therefore dropped and replaced by two partial indexes.
    op.drop_constraint(
        "uq_fee_structure_items_structure_head", "fee_structure_items", type_="unique"
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_fee_structure_items_structure_head
            ON fee_structure_items (structure_id, head_id)
         WHERE head_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_fee_structure_items_structure_stationery
            ON fee_structure_items (structure_id, stationery_item_id)
         WHERE stationery_item_id IS NOT NULL
        """
    )

    op.drop_constraint("uq_fee_voucher_items_voucher_head", "fee_voucher_items", type_="unique")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_fee_voucher_items_voucher_head
            ON fee_voucher_items (voucher_id, head_id)
         WHERE head_id IS NOT NULL
        """
    )
    # This one is what makes "add two more copies" an UPDATE of the line already
    # there rather than a second row reading "Copy x 2" beneath "Copy x 3".
    op.execute(
        """
        CREATE UNIQUE INDEX uq_fee_voucher_items_voucher_stationery
            ON fee_voucher_items (voucher_id, stationery_item_id)
         WHERE stationery_item_id IS NOT NULL
        """
    )

    # =====================================================================
    # 4. Challan lines: the snapshot columns
    # =====================================================================
    #
    # RENAME, never drop-and-add. `head_name` is the frozen text a challan prints;
    # recreating the column would blank it on every voucher ever issued, which is the
    # one thing this module promises never to happen.
    op.alter_column("fee_voucher_items", "head_name", new_column_name="line_name")

    # The unit a stationery line was SOLD in, frozen beside the name. If a school
    # switches an article from pieces to dozens, an old challan reading "Pencil x 12"
    # must keep meaning twelve pencils. NULL on every fee line, including all of the
    # existing ones -- which is why no backfill follows.
    op.add_column("fee_voucher_items", sa.Column("unit_label", sa.String(length=16), nullable=True))

    # `updated_at`, because these rows are no longer written exactly once: a DRAFT
    # voucher's lines can now be added, adjusted and removed while the bill is being
    # assembled. Backfilled from `created_at` so no row claims to have been touched
    # at migration time. (Issued vouchers remain immutable -- the service refuses
    # every line mutation the moment a voucher leaves DRAFT.)
    op.add_column(
        "fee_voucher_items",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.execute("UPDATE fee_voucher_items SET updated_at = created_at")


def downgrade() -> None:
    # Mirrors upgrade() in reverse. NOT loss-free, and it cannot be: a stationery
    # line has nowhere to go in a schema that only understands fee heads. Those rows
    # are deleted, which is why the deletes are explicit and ordered before the
    # columns that identify them disappear.
    op.drop_column("fee_voucher_items", "updated_at")
    op.drop_column("fee_voucher_items", "unit_label")
    op.alter_column("fee_voucher_items", "line_name", new_column_name="head_name")

    # The rows the old schema cannot represent. Dropped BEFORE `head_id` goes back to
    # NOT NULL, which would otherwise fail on exactly these rows.
    op.execute("DELETE FROM fee_voucher_items WHERE line_type = 'stationery'")
    op.execute("DELETE FROM fee_structure_items WHERE line_type = 'stationery'")

    op.execute("DROP INDEX IF EXISTS uq_fee_voucher_items_voucher_stationery")
    op.execute("DROP INDEX IF EXISTS uq_fee_voucher_items_voucher_head")
    op.create_unique_constraint(
        "uq_fee_voucher_items_voucher_head", "fee_voucher_items", ["voucher_id", "head_id"]
    )

    op.execute("DROP INDEX IF EXISTS uq_fee_structure_items_structure_stationery")
    op.execute("DROP INDEX IF EXISTS uq_fee_structure_items_structure_head")
    op.create_unique_constraint(
        "uq_fee_structure_items_structure_head",
        "fee_structure_items",
        ["structure_id", "head_id"],
    )

    for table in _LINE_TABLES:
        op.drop_constraint(op.f(f"ck_{table}_line_type_matches_reference"), table, type_="check")
        op.drop_constraint(op.f(f"ck_{table}_unit_price_non_negative"), table, type_="check")
        op.drop_constraint(op.f(f"ck_{table}_quantity_positive"), table, type_="check")
        op.drop_constraint(op.f(f"ck_{table}_line_type"), table, type_="check")
        op.alter_column(table, "head_id", existing_type=sa.UUID(), nullable=False)
        op.drop_index(op.f(f"ix_{table}_stationery_item_id"), table_name=table)
        op.drop_constraint(
            op.f(f"fk_{table}_stationery_item_id_stationery_items"), table, type_="foreignkey"
        )
        op.drop_column(table, "unit_price")
        op.drop_column(table, "quantity")
        op.drop_column(table, "stationery_item_id")
        op.drop_column(table, "line_type")

    teardown_tenant_table("stationery_items")
    op.drop_index("ix_stationery_items_school_id_category", table_name="stationery_items")
    op.drop_index("ix_stationery_items_school_id_is_active", table_name="stationery_items")
    op.drop_index(op.f("ix_stationery_items_deleted_at"), table_name="stationery_items")
    op.drop_index(op.f("ix_stationery_items_school_id"), table_name="stationery_items")
    op.drop_index(op.f("ix_stationery_items_organization_id"), table_name="stationery_items")
    op.drop_table("stationery_items")
