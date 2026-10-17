"""test papers and question bank: questions, papers, paper_questions, permissions

Revision ID: b2d4f6a8c0e2
Revises: b8d0f2a4c6e8
Create Date: 2026-10-17 01:00:00+00:00

WHY THIS MIGRATION EXISTS
    Storage for test papers written from book chapters: the school's question bank,
    a paper (what was asked for, and the generation job's state), and the paper's
    ordered questions. See `app/modules/papers/models.py`.

THREE NEW PERMISSIONS, BACKFILLED
    principal  (system)  read + write + manage
    teacher    (system)  read + write -- generate papers, change the ones they made
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from alembic.rls import setup_tenant_table, teardown_tenant_table

revision: str = "b2d4f6a8c0e2"
down_revision: str | None = "b8d0f2a4c6e8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (code, resource, action, category, description, min_scope, dangerous) -- must
# match `app/modules/rbac/catalog.py`.
_NEW_PERMISSIONS = (
    (
        "paper:read",
        "paper",
        "read",
        "Academics",
        "View test papers and the question bank.",
        "school",
        False,
    ),
    (
        "paper:write",
        "paper",
        "write",
        "Academics",
        "Generate test papers and change the ones you made.",
        "school",
        False,
    ),
    (
        "paper:manage",
        "paper",
        "manage",
        "Academics",
        "Change or delete any test paper.",
        "school",
        False,
    ),
)

_GRANTS = (
    ("principal", ("paper:read", "paper:write", "paper:manage")),
    ("teacher", ("paper:read", "paper:write")),
)

_TABLES = ("questions", "papers", "paper_questions")


def _enum(name: str, *values: str, length: int = 32) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=length)


def _tenant_columns() -> list[sa.Column]:  # type: ignore[type-arg]
    return [
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
    ]


def _tenant_keys(table: str) -> list[sa.ForeignKeyConstraint]:
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


def _fk(table: str, column: str, target: str, ondelete: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        [column],
        [f"{target}.id"],
        name=op.f(f"fk_{table}_{column}_{target}"),
        ondelete=ondelete,
    )


def _indexes(table: str, *columns: str) -> None:
    for column in ("organization_id", "school_id", *columns):
        op.create_index(op.f(f"ix_{table}_{column}"), table, [column], unique=False)


def upgrade() -> None:
    # --- questions ---------------------------------------------------------
    op.create_table(
        "questions",
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("book_id", sa.UUID(), nullable=True),
        sa.Column("chapter_id", sa.UUID(), nullable=True),
        sa.Column(
            "type",
            _enum("question_type", "mcq", "true_false", "fill_blank", "short", "long"),
            nullable=False,
        ),
        sa.Column(
            "difficulty", _enum("question_difficulty", "easy", "medium", "hard"), nullable=False
        ),
        sa.Column("language", _enum("question_language", "en", "ur", length=8), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("correct_option", sa.Integer(), nullable=True),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column("marks", sa.Integer(), nullable=False),
        sa.Column("printed_page", sa.Integer(), nullable=True),
        sa.Column("origin", _enum("question_origin", "ai", "manual"), nullable=False),
        sa.Column("checks", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        *_tenant_columns(),
        sa.CheckConstraint("marks BETWEEN 1 AND 100", name=op.f("ck_questions_marks_in_range")),
        _fk("questions", "class_id", "classes", "CASCADE"),
        _fk("questions", "subject_id", "subjects", "SET NULL"),
        _fk("questions", "book_id", "books", "SET NULL"),
        _fk("questions", "chapter_id", "book_chapters", "SET NULL"),
        _fk("questions", "created_by_user_id", "users", "SET NULL"),
        *_tenant_keys("questions"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_questions")),
    )
    _indexes("questions", "class_id", "subject_id", "book_id", "chapter_id", "created_by_user_id")
    op.create_index(
        "ix_questions_school_id_class_id_type",
        "questions",
        ["school_id", "class_id", "type"],
        unique=False,
    )
    setup_tenant_table("questions")

    # --- papers ------------------------------------------------------------
    op.create_table(
        "papers",
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=True),
        sa.Column("book_id", sa.UUID(), nullable=True),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("language", _enum("paper_language", "en", "ur", length=8), nullable=False),
        sa.Column(
            "difficulty",
            _enum("paper_difficulty", "easy", "medium", "hard", "mixed"),
            nullable=False,
        ),
        sa.Column(
            "paper_type", _enum("paper_type", "objective", "subjective", "mix"), nullable=False
        ),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("instructions", sa.Text(), nullable=True),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            _enum("paper_status", "queued", "generating", "ready", "needs_review", "failed"),
            nullable=False,
        ),
        sa.Column("report", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.String(length=1000), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("created_by_user_id", sa.UUID(), nullable=True),
        *_tenant_columns(),
        sa.CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes BETWEEN 5 AND 600",
            name=op.f("ck_papers_duration_in_range"),
        ),
        _fk("papers", "class_id", "classes", "CASCADE"),
        _fk("papers", "subject_id", "subjects", "SET NULL"),
        _fk("papers", "book_id", "books", "SET NULL"),
        _fk("papers", "created_by_user_id", "users", "SET NULL"),
        *_tenant_keys("papers"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_papers")),
    )
    _indexes("papers", "class_id", "subject_id", "book_id", "created_by_user_id")
    op.create_index("ix_papers_status_updated_at", "papers", ["status", "updated_at"], unique=False)
    setup_tenant_table("papers")

    # --- paper_questions ---------------------------------------------------
    op.create_table(
        "paper_questions",
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column("question_id", sa.UUID(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("marks", sa.Integer(), nullable=False),
        sa.Column(
            "requested_difficulty",
            _enum("paper_question_difficulty", "easy", "medium", "hard"),
            nullable=True,
        ),
        *_tenant_columns(),
        sa.CheckConstraint(
            "marks BETWEEN 1 AND 100", name=op.f("ck_paper_questions_marks_in_range")
        ),
        _fk("paper_questions", "paper_id", "papers", "CASCADE"),
        _fk("paper_questions", "question_id", "questions", "CASCADE"),
        *_tenant_keys("paper_questions"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_paper_questions")),
        sa.UniqueConstraint("paper_id", "position", name="uq_paper_questions_paper_id_position"),
        sa.UniqueConstraint(
            "paper_id", "question_id", name="uq_paper_questions_paper_id_question_id"
        ),
    )
    _indexes("paper_questions", "paper_id", "question_id")
    setup_tenant_table("paper_questions")

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
