"""textbook library: books, chapter lists, chapter uploads, pages, pgvector chunks, permissions

Revision ID: a8c0d2e4f6b8
Revises: f7b9c1e3a5d7
Create Date: 2026-10-07 19:51:00+00:00

WHY THIS MIGRATION EXISTS
    Storage for the textbook library: a book (Title, Class, Publisher, Version), its
    chapter list, the files a teacher uploads per chapter, the pages the agent reads
    out of them, and the embedded chunks it indexes. See
    `app/modules/books/models.py` for the modelling rationale.

REQUIRES THE `vector` EXTENSION (pgvector)
    `book_chunks.embedding` is `vector(1536)` with an HNSW cosine index. The
    extension must be INSTALLED on the server before this runs:

        Ubuntu/Debian, PostgreSQL 18:  sudo apt install postgresql-18-pgvector
        Docker:                        image pgvector/pgvector:pg16

    `CREATE EXTENSION` then runs here, as the migration (owner) role. The check
    below fails with that instruction rather than a bare "could not open extension
    control file".

THREE NEW PERMISSIONS, BACKFILLED
    principal  (system)  read + write + manage
    teacher    (system)  read + write -- upload books, change the ones they uploaded
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from alembic.rls import setup_tenant_table, teardown_tenant_table

revision: str = "a8c0d2e4f6b8"
down_revision: str | None = "f7b9c1e3a5d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# (code, resource, action, category, description, min_scope, dangerous) -- must
# match `app/modules/rbac/catalog.py`.
_NEW_PERMISSIONS = (
    (
        "book:read",
        "book",
        "read",
        "Academics",
        "View the textbook library and search books.",
        "school",
        False,
    ),
    (
        "book:write",
        "book",
        "write",
        "Academics",
        "Upload books and manage the books you uploaded.",
        "school",
        False,
    ),
    (
        "book:manage",
        "book",
        "manage",
        "Academics",
        "Change or delete any book in the library.",
        "school",
        False,
    ),
)

_GRANTS = (
    ("principal", ("book:read", "book:write", "book:manage")),
    ("teacher", ("book:read", "book:write")),
)

_TABLES = ("books", "book_chapters", "book_chapter_files", "book_pages", "book_chunks")


def _require_pgvector() -> None:
    available = (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'"))
        .scalar()
    )
    if not available:
        raise RuntimeError(
            "The pgvector extension is not installed on this PostgreSQL server. "
            "Install it first (Ubuntu: `sudo apt install postgresql-18-pgvector`, "
            "or use the pgvector/pgvector Docker image), then re-run the migration."
        )
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")


def upgrade() -> None:
    _require_pgvector()

    # --- books -------------------------------------------------------------
    op.create_table(
        "books",
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("publisher", sa.String(length=200), nullable=False),
        sa.Column("version", sa.String(length=60), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
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
            ["class_id"], ["classes.id"], name=op.f("fk_books_class_id_classes"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["users.id"],
            name=op.f("fk_books_created_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_books_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name=op.f("fk_books_school_id_schools"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["subjects.id"],
            name=op.f("fk_books_subject_id_subjects"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_books")),
        sa.UniqueConstraint(
            "school_id",
            "class_id",
            "title",
            "publisher",
            "version",
            name="uq_books_school_id_class_id_title_publisher_version",
        ),
    )
    op.create_index(op.f("ix_books_class_id"), "books", ["class_id"], unique=False)
    op.create_index(
        op.f("ix_books_created_by_user_id"), "books", ["created_by_user_id"], unique=False
    )
    op.create_index(op.f("ix_books_organization_id"), "books", ["organization_id"], unique=False)
    op.create_index(op.f("ix_books_school_id"), "books", ["school_id"], unique=False)
    op.create_index(op.f("ix_books_subject_id"), "books", ["subject_id"], unique=False)
    setup_tenant_table("books")

    # --- book_chapters -----------------------------------------------------
    op.create_table(
        "book_chapters",
        sa.Column("book_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "empty",
                "uploaded",
                "queued",
                "processing",
                "ready",
                "needs_review",
                "failed",
                name="book_chapter_status",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.String(length=1000), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
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
        sa.CheckConstraint(
            "number BETWEEN 1 AND 999", name=op.f("ck_book_chapters_number_in_range")
        ),
        sa.ForeignKeyConstraint(
            ["book_id"],
            ["books.id"],
            name=op.f("fk_book_chapters_book_id_books"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_book_chapters_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name=op.f("fk_book_chapters_school_id_schools"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_book_chapters")),
        sa.UniqueConstraint("book_id", "number", name="uq_book_chapters_book_id_number"),
    )
    op.create_index(op.f("ix_book_chapters_book_id"), "book_chapters", ["book_id"], unique=False)
    op.create_index(
        op.f("ix_book_chapters_organization_id"), "book_chapters", ["organization_id"], unique=False
    )
    op.create_index(
        op.f("ix_book_chapters_school_id"), "book_chapters", ["school_id"], unique=False
    )
    op.create_index(
        "ix_book_chapters_status_updated_at",
        "book_chapters",
        ["status", "updated_at"],
        unique=False,
    )
    setup_tenant_table("book_chapters")

    # --- book_chapter_files ------------------------------------------------
    op.create_table(
        "book_chapter_files",
        sa.Column("chapter_id", sa.UUID(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "pdf",
                "image",
                name="book_file_kind",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("original_name", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=500), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("uploaded_by_user_id", sa.UUID(), nullable=True),
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
            ["chapter_id"],
            ["book_chapters.id"],
            name=op.f("fk_book_chapter_files_chapter_id_book_chapters"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_book_chapter_files_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name=op.f("fk_book_chapter_files_school_id_schools"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"],
            ["users.id"],
            name=op.f("fk_book_chapter_files_uploaded_by_user_id_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_book_chapter_files")),
        sa.UniqueConstraint("chapter_id", "sha256", name="uq_book_chapter_files_chapter_id_sha256"),
    )
    op.create_index(
        op.f("ix_book_chapter_files_chapter_id"), "book_chapter_files", ["chapter_id"], unique=False
    )
    op.create_index(
        op.f("ix_book_chapter_files_organization_id"),
        "book_chapter_files",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_book_chapter_files_school_id"), "book_chapter_files", ["school_id"], unique=False
    )
    setup_tenant_table("book_chapter_files")

    # --- book_pages --------------------------------------------------------
    op.create_table(
        "book_pages",
        sa.Column("chapter_id", sa.UUID(), nullable=False),
        sa.Column("file_id", sa.UUID(), nullable=False),
        sa.Column("source_index", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("printed_page_number", sa.Integer(), nullable=True),
        sa.Column(
            "placement",
            sa.Enum(
                "printed_number",
                "pdf_order",
                "agent",
                "upload_order",
                name="book_page_placement",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "method",
            sa.Enum(
                "text_layer",
                "vision",
                name="book_page_method",
                native_enum=False,
                create_constraint=True,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("image_key", sa.String(length=500), nullable=True),
        sa.Column("detected_chapter_number", sa.Integer(), nullable=True),
        sa.Column("chapter_confidence", sa.Float(), nullable=True),
        sa.Column("opens_chapter", sa.Boolean(), nullable=False),
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
            ["chapter_id"],
            ["book_chapters.id"],
            name=op.f("fk_book_pages_chapter_id_book_chapters"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"],
            ["book_chapter_files.id"],
            name=op.f("fk_book_pages_file_id_book_chapter_files"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_book_pages_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name=op.f("fk_book_pages_school_id_schools"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_book_pages")),
        sa.UniqueConstraint("chapter_id", "position", name="uq_book_pages_chapter_id_position"),
    )
    op.create_index(op.f("ix_book_pages_chapter_id"), "book_pages", ["chapter_id"], unique=False)
    op.create_index(op.f("ix_book_pages_file_id"), "book_pages", ["file_id"], unique=False)
    op.create_index(
        op.f("ix_book_pages_organization_id"), "book_pages", ["organization_id"], unique=False
    )
    op.create_index(op.f("ix_book_pages_school_id"), "book_pages", ["school_id"], unique=False)
    setup_tenant_table("book_pages")

    # --- book_chunks -------------------------------------------------------
    op.create_table(
        "book_chunks",
        sa.Column("book_id", sa.UUID(), nullable=False),
        sa.Column("chapter_id", sa.UUID(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("page_start", sa.Integer(), nullable=False),
        sa.Column("page_end", sa.Integer(), nullable=False),
        sa.Column("printed_start", sa.Integer(), nullable=True),
        sa.Column("printed_end", sa.Integer(), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", Vector(1536), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
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
            ["book_id"], ["books.id"], name=op.f("fk_book_chunks_book_id_books"), ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["chapter_id"],
            ["book_chapters.id"],
            name=op.f("fk_book_chunks_chapter_id_book_chapters"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_book_chunks_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["school_id"],
            ["schools.id"],
            name=op.f("fk_book_chunks_school_id_schools"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_book_chunks")),
        sa.UniqueConstraint(
            "chapter_id", "chunk_index", name="uq_book_chunks_chapter_id_chunk_index"
        ),
    )
    op.create_index(op.f("ix_book_chunks_book_id"), "book_chunks", ["book_id"], unique=False)
    op.create_index(op.f("ix_book_chunks_chapter_id"), "book_chunks", ["chapter_id"], unique=False)
    op.create_index(
        "ix_book_chunks_embedding_hnsw",
        "book_chunks",
        ["embedding"],
        unique=False,
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
    op.create_index(
        op.f("ix_book_chunks_organization_id"), "book_chunks", ["organization_id"], unique=False
    )
    op.create_index(op.f("ix_book_chunks_school_id"), "book_chunks", ["school_id"], unique=False)
    setup_tenant_table("book_chunks")

    # --- permissions ------------------------------------------------------
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

    for role_code, codes in _GRANTS:
        for code in codes:
            op.execute(
                sa.text(
                    """
                    INSERT INTO role_permissions (role_id, organization_id, permission_code)
                    SELECT r.id, r.organization_id, :code
                      FROM roles r
                     WHERE r.code = :role_code
                       AND r.is_system IS TRUE
                    ON CONFLICT DO NOTHING
                    """
                ).bindparams(code=code, role_code=role_code)
            )
        op.execute(
            sa.text(
                "UPDATE roles SET permissions_version = permissions_version + 1 "
                "WHERE is_system IS TRUE AND code = :role_code"
            ).bindparams(role_code=role_code)
        )


def downgrade() -> None:
    codes = tuple(p[0] for p in _NEW_PERMISSIONS)
    op.execute(
        sa.text("DELETE FROM role_permissions WHERE permission_code IN :codes").bindparams(
            sa.bindparam("codes", value=codes, expanding=True)
        )
    )
    op.execute(
        "UPDATE roles SET permissions_version = permissions_version + 1 "
        "WHERE is_system IS TRUE AND code IN ('principal', 'teacher')"
    )
    op.execute(
        sa.text("DELETE FROM permissions WHERE code IN :codes").bindparams(
            sa.bindparam("codes", value=codes, expanding=True)
        )
    )

    for table in reversed(_TABLES):
        teardown_tenant_table(table)
        op.drop_table(table)
    # The `vector` extension is left installed: other database objects may use it,
    # and dropping an extension is not this module's decision to make.
