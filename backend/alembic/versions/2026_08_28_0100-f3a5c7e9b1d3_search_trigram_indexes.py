"""global search: trigram indexes for the tables that grow

Revision ID: f3a5c7e9b1d3
Revises: e1b3c5d7f9a1
Create Date: 2026-08-28 01:00:00+00:00

WHY THIS MIGRATION EXISTS
    `modules/search` matches text two ways, and neither can use a btree index:

        column ILIKE '%needle%'      -- leading wildcard defeats btree entirely
        lower(column) % 'needle'     -- pg_trgm similarity, for typo tolerance

    `pg_trgm` (installed in the bootstrap migration) makes both index-usable via a
    GIN index with `gin_trgm_ops`. Without one, every keystroke in the omnibar is a
    sequential scan of the students table.

WHY ONLY THREE TABLES
    Search reads from eleven. Eight of them are configuration a school edits by
    hand -- classes, sections, roles, fee heads, fee structures, campuses. A school
    has tens of those, not thousands, and on a table that small a sequential scan is
    already faster than an index lookup. Indexing them would add write cost and GIN
    maintenance to buy nothing measurable.

    The three here are the ones whose row count is a function of how long the
    customer has been using the product:

        students        one row per child, forever (soft-deleted, never removed)
        fee_vouchers    one row per student per billing period -- the fastest-
                        growing table in the schema by a wide margin
        users           one row per human across every tenant, and NOT tenant-
                        scoped, so it is the only search table where one customer's
                        growth slows another customer's queries

=============================================================================
THE INDEX EXPRESSIONS MUST MATCH `repository._text` EXACTLY
=============================================================================
    PostgreSQL uses an expression index only for a syntactically identical
    expression. These are built on

        lower(coalesce(<column>, ''))

    which is precisely what `modules/search/repository._text` emits -- including
    the `''` being a SQL literal rather than a bind parameter, because a parameter
    is not a constant at planning time and would not match.

    That coupling is deliberate but fragile, so it is documented on both sides. If
    `_text` changes shape, these indexes silently stop being used: queries stay
    correct and quietly get slower, which is the worst kind of regression to
    notice. `EXPLAIN` on a fuzzy search should show a Bitmap Heap Scan, not a Seq
    Scan.

WHY MULTICOLUMN GIN RATHER THAN ONE INDEX PER COLUMN
    A multicolumn GIN index can serve a query touching any SUBSET of its columns,
    which is exactly the access pattern here -- the student search ORs across five
    columns and any of them may be the one that matches. Five separate indexes
    would work too, at five times the write amplification on the busiest insert
    path in the product.

ON `CREATE INDEX` VERSUS `CREATE INDEX CONCURRENTLY`
    Plain `CREATE INDEX` takes a lock that blocks writes to the table for the
    duration of the build. That is fine at the size these tables are today, and it
    is the only form that works inside Alembic's transaction -- `CONCURRENTLY`
    cannot run in one.

    For a deployment where `students` is already large, run the three statements
    below by hand with `CONCURRENTLY` (outside a transaction) BEFORE applying this
    migration; the `IF NOT EXISTS` clauses then make this a no-op, and the
    `alembic_version` row still advances.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "f3a5c7e9b1d3"
down_revision: str | None = "e1b3c5d7f9a1"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


# (index name, table, indexed expressions) -- see the docstring on why these three.
_INDEXES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "ix_students_search_trgm",
        "students",
        (
            "first_name",
            "last_name",
            "admission_number",
            "guardian_name",
            "guardian_phone",
        ),
    ),
    ("ix_fee_vouchers_search_trgm", "fee_vouchers", ("voucher_number",)),
    # `full_name` only. `email` is CITEXT, which has no `gin_trgm_ops` operator
    # class -- and an email is looked up by exact address far more often than by
    # fuzzy fragment, which the existing unique index already serves.
    ("ix_users_search_trgm", "users", ("full_name",)),
)


def _expression(column: str) -> str:
    """One indexed expression, in the exact shape `repository._text` emits."""
    return f"(lower(coalesce({column}, ''))) gin_trgm_ops"


def upgrade() -> None:
    for name, table, columns in _INDEXES:
        expressions = ",\n            ".join(_expression(column) for column in columns)
        op.execute(
            f"CREATE INDEX IF NOT EXISTS {name} ON {table} USING gin (\n            {expressions})"
        )


def downgrade() -> None:
    for name, _table, _columns in _INDEXES:
        op.execute(f"DROP INDEX IF EXISTS {name}")
