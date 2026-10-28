"""shared book library: one copy of each book for the platform, a shelf per campus

Revision ID: e5b7d9f1a3c5
Revises: d4f6a8c0e2b4
Create Date: 2026-10-27 10:00:00+00:00

WHY THIS MIGRATION EXISTS
    Books stop belonging to one campus. A book is uploaded once for every school
    on the platform, and each campus files it under its own class in
    `school_books`. See `app/modules/books/models.py` ("ONE LIBRARY, MANY
    SHELVES") for the model, `app/modules/books/catalog.py` for what makes two
    books the same one.

WHAT CHANGES
    * `school_books` -- new tenant table. Every existing book gets an entry on its
      own campus with the class and subject it was filed under.
    * `books.class_id` / `subject_id` -- moved into that entry and dropped. The
      book keeps a `grade` and `subject` LABEL (the class and subject names it was
      filed under), which is what other schools see and search by.
    * `books.catalog_key` -- unique. Where two existing books are already the same
      book (two schools uploaded it), the OLDEST gets the key and the others keep
      none: both stay, nothing is merged or deleted.
    * The five content tables get a second policy, `library_read`: every
      organization may SELECT them. `tenant_isolation` still decides who WRITES.
    * `library_book_schools(uuid[])` -- how many campuses use each book, counted
      across organizations. SECURITY DEFINER because shelves are tenant rows; it
      returns counts only. The service needs it before deleting a book's content.

THE MIGRATING ROLE MUST BYPASS RLS
    The backfill reads every organization's books, and the function above runs as
    its owner. A role subject to RLS would see nothing and count nothing -- and a
    count of zero would let an uploader delete a book other schools still use. The
    upgrade refuses to run as such a role rather than do that silently.

DOWNGRADE LOSES DATA
    Each book returns to its uploader's class. Entries on OTHER campuses are
    dropped, and a book its uploader had already removed (kept in the library
    for other schools) is deleted with its chapters.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from alembic.rls import APP_ROLE, setup_tenant_table, teardown_tenant_table

revision: str = "e5b7d9f1a3c5"
down_revision: str | None = "d4f6a8c0e2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONTENT_TABLES = ("books", "book_chapters", "book_chapter_files", "book_pages", "book_chunks")


# -- frozen copy of app/modules/books/catalog.py, for the backfill -------------

_NON_WORD = re.compile(r"[^\w]+")
_GRADE_WORDS = frozenset({"class", "grade", "standard", "std", "year", "level", "form"})
_NUMBER_WORDS = {
    word: number
    for number, words in enumerate(
        (
            ("one", "first", "i"),
            ("two", "second", "ii"),
            ("three", "third", "iii"),
            ("four", "fourth", "iv"),
            ("five", "fifth", "v"),
            ("six", "sixth", "vi"),
            ("seven", "seventh", "vii"),
            ("eight", "eighth", "viii"),
            ("nine", "ninth", "ix"),
            ("ten", "tenth", "x"),
            ("eleven", "eleventh", "xi"),
            ("twelve", "twelfth", "xii"),
        ),
        start=1,
    )
    for word in words
}
_ORDINAL = re.compile(r"^(\d{1,2})(st|nd|rd|th)?$")


def _normalise(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text).casefold()
    bare = "".join(ch for ch in folded if not unicodedata.combining(ch))
    return " ".join(_NON_WORD.sub(" ", bare).replace("_", " ").split())


def _grade_key(label: str) -> str:
    words = _normalise(label).split()
    numbers: list[int] = []
    for word in words:
        if word in _GRADE_WORDS:
            continue
        if match := _ORDINAL.match(word):
            numbers.append(int(match.group(1)))
        elif word in _NUMBER_WORDS:
            numbers.append(_NUMBER_WORDS[word])
        else:
            return " ".join(words)
    return str(numbers[0]) if len(numbers) == 1 else " ".join(words)


def _catalog_key(title: str, publisher: str, version: str, grade: str) -> str:
    return "|".join(
        (_normalise(title), _normalise(publisher), _normalise(version), _grade_key(grade))
    )


# ------------------------------------------------------------------------------


def _require_rls_bypass() -> None:
    bypasses = (
        op.get_bind()
        .execute(
            sa.text("SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user")
        )
        .scalar()
    )
    if not bypasses:
        raise RuntimeError(
            "This migration must run as a role that bypasses row-level security (the "
            "schema owner with BYPASSRLS, or a superuser): it reads every organization's "
            "books, and `library_book_schools` counts shelves across organizations as its "
            "owner. Set MIGRATION_USER to such a role and run it again."
        )


def upgrade() -> None:
    _require_rls_bypass()

    # --- school_books ------------------------------------------------------
    op.create_table(
        "school_books",
        sa.Column("book_id", sa.UUID(), nullable=False),
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("added_by_user_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("school_id", sa.UUID(), nullable=False),
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
            ["added_by_user_id"],
            ["users.id"],
            name=op.f("fk_school_books_added_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["book_id"],
            ["books.id"],
            name=op.f("fk_school_books_book_id_books"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["classes.id"],
            name=op.f("fk_school_books_class_id_classes"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_school_books_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name=op.f("fk_school_books_school_id_schools"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["subjects.id"],
            name=op.f("fk_school_books_subject_id_subjects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_school_books")),
        sa.UniqueConstraint("school_id", "book_id", name="uq_school_books_school_id_book_id"),
    )
    op.create_index(op.f("ix_school_books_book_id"), "school_books", ["book_id"], unique=False)
    op.create_index(op.f("ix_school_books_class_id"), "school_books", ["class_id"], unique=False)
    op.create_index(
        op.f("ix_school_books_organization_id"), "school_books", ["organization_id"], unique=False
    )
    op.create_index(op.f("ix_school_books_school_id"), "school_books", ["school_id"], unique=False)
    op.create_index(
        op.f("ix_school_books_subject_id"), "school_books", ["subject_id"], unique=False
    )
    setup_tenant_table("school_books")

    # --- books: the filing moves out, the labels and the key come in ------
    op.add_column("books", sa.Column("grade", sa.String(length=80), nullable=True))
    op.add_column("books", sa.Column("grade_key", sa.String(length=80), nullable=True))
    op.add_column("books", sa.Column("subject", sa.String(length=120), nullable=True))
    op.add_column("books", sa.Column("catalog_key", sa.String(length=600), nullable=True))

    op.execute(
        """
        INSERT INTO school_books
            (organization_id, school_id, book_id, class_id, subject_id,
             added_by_user_id, created_at, updated_at)
        SELECT organization_id, school_id, id, class_id, subject_id,
               created_by_user_id, created_at, created_at
        FROM books
        """
    )
    op.execute(
        "UPDATE books AS b SET grade = left(c.name, 80) FROM classes AS c WHERE c.id = b.class_id"
    )
    op.execute(
        "UPDATE books AS b SET subject = s.name FROM subjects AS s WHERE s.id = b.subject_id"
    )

    bind = op.get_bind()
    rows = bind.execute(
        sa.text("SELECT id, title, publisher, version, grade FROM books ORDER BY created_at, id")
    ).all()
    taken: set[str] = set()
    updates = []
    for book_id, title, publisher, version, grade in rows:
        key = _catalog_key(title, publisher, version, grade)
        updates.append(
            {"id": book_id, "grade_key": _grade_key(grade), "key": None if key in taken else key}
        )
        taken.add(key)
    if updates:
        bind.execute(
            sa.text("UPDATE books SET grade_key = :grade_key, catalog_key = :key WHERE id = :id"),
            updates,
        )

    op.alter_column("books", "grade", nullable=False)
    op.alter_column("books", "grade_key", nullable=False)
    op.drop_constraint("uq_books_school_id_class_id_title_publisher_version", "books")
    # Their foreign keys and indexes go with them.
    op.drop_column("books", "class_id")
    op.drop_column("books", "subject_id")
    op.create_unique_constraint(op.f("uq_books_catalog_key"), "books", ["catalog_key"])
    op.create_index(op.f("ix_books_grade_key"), "books", ["grade_key"], unique=False)

    # --- the library is readable by every organization --------------------
    for table in _CONTENT_TABLES:
        op.execute(f"CREATE POLICY library_read ON {table} FOR SELECT TO {APP_ROLE} USING (true)")

    op.execute(
        """
        CREATE FUNCTION library_book_schools(book_ids uuid[])
        RETURNS TABLE (book_id uuid, schools integer)
        LANGUAGE sql STABLE SECURITY DEFINER
        SET search_path = pg_catalog, public
        AS $$
            SELECT sb.book_id, count(*)::integer
            FROM public.school_books AS sb
            WHERE sb.book_id = ANY(book_ids)
            GROUP BY sb.book_id
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION library_book_schools(uuid[]) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION library_book_schools(uuid[]) TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS library_book_schools(uuid[])")
    for table in _CONTENT_TABLES:
        op.execute(f"DROP POLICY IF EXISTS library_read ON {table}")

    op.add_column("books", sa.Column("class_id", sa.UUID(), nullable=True))
    op.add_column("books", sa.Column("subject_id", sa.UUID(), nullable=True))
    op.execute(
        """
        UPDATE books AS b SET class_id = sb.class_id, subject_id = sb.subject_id
        FROM school_books AS sb
        WHERE sb.book_id = b.id AND sb.school_id = b.school_id
        """
    )
    op.execute("DELETE FROM books WHERE class_id IS NULL")
    op.alter_column("books", "class_id", nullable=False)
    op.create_foreign_key(
        op.f("fk_books_class_id_classes"),
        "books",
        "classes",
        ["class_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        op.f("fk_books_subject_id_subjects"),
        "books",
        "subjects",
        ["subject_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(op.f("ix_books_class_id"), "books", ["class_id"], unique=False)
    op.create_index(op.f("ix_books_subject_id"), "books", ["subject_id"], unique=False)
    op.create_unique_constraint(
        "uq_books_school_id_class_id_title_publisher_version",
        "books",
        ["school_id", "class_id", "title", "publisher", "version"],
    )

    op.drop_index(op.f("ix_books_grade_key"), table_name="books")
    op.drop_constraint(op.f("uq_books_catalog_key"), "books")
    op.drop_column("books", "catalog_key")
    op.drop_column("books", "subject")
    op.drop_column("books", "grade_key")
    op.drop_column("books", "grade")

    teardown_tenant_table("school_books")
    op.drop_table("school_books")
