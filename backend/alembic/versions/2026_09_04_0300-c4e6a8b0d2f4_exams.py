"""exams: the assessment layer -- exams, papers per class/subject, marks

Revision ID: c4e6a8b0d2f4
Revises: b1d3f5a7c9e2
Create Date: 2026-09-04 03:00:00+00:00

WHY THIS MIGRATION EXISTS
    The gradebook's storage. An EXAM ("Mid-Term 2026-27") is sat as PAPERS (one
    per class per subject, each with a date and marks scheme), and a paper
    produces MARKS (one row per student, absence a flag rather than a null).
    Report cards, rankings and progress views are all reads over these three
    tables. See `app/modules/exams/models.py` for the modelling rationale.

NO NEW PERMISSIONS. `grade:read` / `grade:manage` were seeded ahead of this
    module (the "wired but unimplemented" block in the RBAC catalog), teacher
    and principal roles already hold them, so this migration is tables + RLS
    only and every existing custom role keeps working on the day exams appear.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from alembic.rls import setup_tenant_table, teardown_tenant_table

revision: str = "c4e6a8b0d2f4"
down_revision: str | None = "b1d3f5a7c9e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Created parents-first, dropped children-first.
_TABLES = ("exams", "exam_papers", "exam_marks")


# --- Shared column helpers, matching the academic_foundation migration --------


def _tenant_columns() -> list[sa.Column]:
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
    op.create_index(op.f(f"ix_{table}_organization_id"), table, ["organization_id"])
    op.create_index(op.f(f"ix_{table}_school_id"), table, ["school_id"])


def _timestamps() -> list[sa.Column]:
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


def _pk() -> sa.Column:
    return sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def _enum(*values: str, name: str) -> sa.Enum:
    """VARCHAR + CHECK, matching `db/base.py::str_enum` -- reversible, unlike
    a native PostgreSQL ENUM."""
    return sa.Enum(*values, name=name, native_enum=False, create_constraint=True, length=32)


def upgrade() -> None:
    # =====================================================================
    # 1. exams -- one examination event per school
    # =====================================================================
    op.create_table(
        "exams",
        _pk(),
        *_tenant_columns(),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("term_id", sa.UUID(), nullable=True),
        sa.Column("start_date", sa.Date(), nullable=True),
        sa.Column("end_date", sa.Date(), nullable=True),
        sa.Column("status", _enum("scheduled", "completed", "published", name="status"), nullable=False),
        *_timestamps(),
        *_tenant_constraints("exams"),
        # SET NULL: deleting a term must not delete the marks sat in it.
        sa.ForeignKeyConstraint(
            ["term_id"], ["terms.id"], name=op.f("fk_exams_term_id_terms"), ondelete="SET NULL"
        ),
        sa.UniqueConstraint("school_id", "name", name="uq_exams_school_id_name"),
        sa.CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name=op.f("ck_exams_dates_ordered"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exams")),
    )
    _tenant_indexes("exams")
    op.create_index(op.f("ix_exams_term_id"), "exams", ["term_id"])
    op.create_index("ix_exams_school_id_start_date", "exams", ["school_id", "start_date"])

    # =====================================================================
    # 2. exam_papers -- one subject sat by one class within an exam
    # =====================================================================
    op.create_table(
        "exam_papers",
        _pk(),
        *_tenant_columns(),
        sa.Column("exam_id", sa.UUID(), nullable=False),
        sa.Column("class_id", sa.UUID(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("scheduled_on", sa.Date(), nullable=True),
        sa.Column("max_marks", sa.Integer(), nullable=False),
        sa.Column("pass_marks", sa.Integer(), nullable=True),
        *_timestamps(),
        *_tenant_constraints("exam_papers"),
        sa.ForeignKeyConstraint(
            ["exam_id"], ["exams.id"], name=op.f("fk_exam_papers_exam_id_exams"), ondelete="CASCADE"
        ),
        # RESTRICT on both dimensions: a class or subject with sat papers is
        # history, and deleting it would orphan a cohort's results.
        sa.ForeignKeyConstraint(
            ["class_id"],
            ["classes.id"],
            name=op.f("fk_exam_papers_class_id_classes"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["subject_id"],
            ["subjects.id"],
            name=op.f("fk_exam_papers_subject_id_subjects"),
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "exam_id", "class_id", "subject_id", name="uq_exam_papers_exam_class_subject"
        ),
        sa.CheckConstraint("max_marks > 0", name=op.f("ck_exam_papers_max_marks_positive")),
        sa.CheckConstraint(
            "pass_marks IS NULL OR (pass_marks >= 0 AND pass_marks <= max_marks)",
            name=op.f("ck_exam_papers_pass_marks_within_max"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exam_papers")),
    )
    _tenant_indexes("exam_papers")
    op.create_index(op.f("ix_exam_papers_exam_id"), "exam_papers", ["exam_id"])
    op.create_index(op.f("ix_exam_papers_class_id"), "exam_papers", ["class_id"])
    op.create_index(op.f("ix_exam_papers_subject_id"), "exam_papers", ["subject_id"])
    op.create_index("ix_exam_papers_school_id_exam_id", "exam_papers", ["school_id", "exam_id"])

    # =====================================================================
    # 3. exam_marks -- one student's result on one paper
    # =====================================================================
    op.create_table(
        "exam_marks",
        _pk(),
        *_tenant_columns(),
        sa.Column("paper_id", sa.UUID(), nullable=False),
        sa.Column("student_id", sa.UUID(), nullable=False),
        # Numeric(6,2), never float: two 42.5s must sum to 85 on the document
        # parents compare digit by digit.
        sa.Column("marks_obtained", sa.Numeric(6, 2), nullable=True),
        sa.Column("is_absent", sa.Boolean(), nullable=False),
        sa.Column("remarks", sa.String(length=200), nullable=True),
        *_timestamps(),
        *_tenant_constraints("exam_marks"),
        sa.ForeignKeyConstraint(
            ["paper_id"],
            ["exam_papers.id"],
            name=op.f("fk_exam_marks_paper_id_exam_papers"),
            ondelete="CASCADE",
        ),
        # CASCADE: erasing a student (the GDPR path) erases their marks too.
        sa.ForeignKeyConstraint(
            ["student_id"],
            ["students.id"],
            name=op.f("fk_exam_marks_student_id_students"),
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("paper_id", "student_id", name="uq_exam_marks_paper_student"),
        # Absence is a FLAG, not a null mark: a missing row is "not yet
        # entered", `is_absent` is "was away". The XOR keeps the two meanings
        # from blurring into each other.
        sa.CheckConstraint(
            "(is_absent AND marks_obtained IS NULL) OR (NOT is_absent AND marks_obtained IS NOT NULL)",
            name=op.f("ck_exam_marks_absent_xor_marks"),
        ),
        sa.CheckConstraint(
            "marks_obtained IS NULL OR marks_obtained >= 0",
            name=op.f("ck_exam_marks_marks_non_negative"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exam_marks")),
    )
    _tenant_indexes("exam_marks")
    op.create_index(op.f("ix_exam_marks_paper_id"), "exam_marks", ["paper_id"])
    op.create_index(op.f("ix_exam_marks_student_id"), "exam_marks", ["student_id"])
    op.create_index("ix_exam_marks_school_id_student_id", "exam_marks", ["school_id", "student_id"])

    # =====================================================================
    # 4. RLS on all three tables
    # =====================================================================
    for table in _TABLES:
        setup_tenant_table(table)


def downgrade() -> None:
    for table in reversed(_TABLES):
        teardown_tenant_table(table)
        op.drop_table(table)
