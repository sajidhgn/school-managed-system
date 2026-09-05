"""Exam models -- the assessment layer over the academic foundation.

WHY THIS FILE EXISTS
    The spec's gradebook starts here: a school schedules an EXAM ("Mid-Term
    2026-27"), the exam is sat as PAPERS (one per class per subject, each with a
    date and a maximum), and a paper produces MARKS (one row per student). Report
    cards, rankings and progress views are all reads over these three tables.

RESPONSIBILITY
    Define `Exam`, `ExamPaper` and `ExamMark`, plus the constraints that keep one
    student from having two marks for one paper and one class from sitting the
    same subject twice in one exam.

INTERACTIONS
    * All three carry `TenantMixin` (RLS) and `RequiredSchoolMixin` (campus
      scope), the same double boundary as the academics tables they reference.
    * `ExamPaper` indexes into the curriculum's dimensions -- `classes` and
      `subjects` -- rather than duplicating them.
    * Permissions are the already-seeded `grade:read` / `grade:manage` pair; no
      new codes, so every existing custom role keeps working on day one.

WHY MARKS HANG OFF THE PAPER AND NOT THE STUDENT
    "Enter Grade 5's maths marks" is the unit of work: a teacher sits with one
    paper's stack and keys a column of numbers. Keying marks per student would
    model the reading ("show me Ali's report card") instead of the writing, and
    the writing is what needs the uniqueness guard and the bulk endpoint.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, str_enum
from app.db.mixins import (
    RequiredSchoolMixin,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

# Numeric(6, 2), never float or plain integer: half marks ("42.5") are routine in
# subcontinental marking, and floats would make two 42.5s sum to 84.99 on the one
# document parents compare digit by digit.
_MARKS = Numeric(6, 2)


class ExamStatus(StrEnum):
    """Where an exam is in its life.

    Three states, not a workflow engine: SCHEDULED is the default from creation
    (papers being added, dates settling), COMPLETED means the sitting is over and
    marks are being entered, PUBLISHED means results are final. The transition is
    a plain PATCH -- the value drives display (a published exam's marks screen
    warns before editing) rather than hard write-locks, because the person who
    can publish is the person who could unlock anyway.
    """

    SCHEDULED = "scheduled"
    COMPLETED = "completed"
    PUBLISHED = "published"


class Exam(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin, SoftDeleteMixin
):
    """One examination event at one school, e.g. "Mid-Term 2026-27"."""

    __tablename__ = "exams"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    """Display name. Unique per school, so recurring exams carry their session in
    the name ("Mid-Term 2026-27") the same way `fees.academic_year` labels do."""

    term_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # SET NULL: deleting a term must not delete the marks sat in it. The exam
        # simply loses its calendar link and keeps its own dates.
        ForeignKey("terms.id", ondelete="SET NULL"),
        index=True,
    )
    """The reporting period this exam belongs to, when the school keeps a
    calendar. Nullable: an exam can be scheduled before terms are defined."""

    start_date: Mapped[date | None] = mapped_column(Date)
    end_date: Mapped[date | None] = mapped_column(Date)
    """The sitting window. Both nullable -- an exam is often named and staffed
    before its dates are settled -- and only loosely validated (end >= start):
    the authoritative per-subject date lives on the paper."""

    status: Mapped[ExamStatus] = mapped_column(
        str_enum(ExamStatus, name="status"),
        nullable=False,
        default=ExamStatus.SCHEDULED,
    )

    papers: Mapped[list[ExamPaper]] = relationship(
        back_populates="exam",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("school_id", "name", name="uq_exams_school_id_name"),
        CheckConstraint(
            "end_date IS NULL OR start_date IS NULL OR end_date >= start_date",
            name="dates_ordered",
        ),
        Index("ix_exams_school_id_start_date", "school_id", "start_date"),
    )


class ExamPaper(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin, SoftDeleteMixin
):
    """One subject sat by one class within an exam, e.g. Grade 5 · Mathematics."""

    __tablename__ = "exam_papers"

    exam_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("exams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    class_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # RESTRICT: deleting a class that has sat papers would orphan its marks.
        # The class-delete service already refuses non-empty classes; this is the
        # database saying the same thing about examined ones.
        ForeignKey("classes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # RESTRICT for the same reason as `class_subjects.subject_id`: a subject
        # with marks against it is history, not clutter.
        ForeignKey("subjects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    scheduled_on: Mapped[date | None] = mapped_column(Date)

    max_marks: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    pass_marks: Mapped[int | None] = mapped_column(Integer)
    """Nullable: not every school states a per-paper pass line, and inventing a
    default (40%?) would print a pass/fail verdict nobody configured."""

    exam: Mapped[Exam] = relationship(back_populates="papers")

    __table_args__ = (
        # One paper per subject per class per exam. Two would make "Grade 5's
        # maths mark" ambiguous on the report card.
        UniqueConstraint(
            "exam_id", "class_id", "subject_id", name="uq_exam_papers_exam_class_subject"
        ),
        CheckConstraint("max_marks > 0", name="max_marks_positive"),
        CheckConstraint(
            "pass_marks IS NULL OR (pass_marks >= 0 AND pass_marks <= max_marks)",
            name="pass_marks_within_max",
        ),
        Index("ix_exam_papers_school_id_exam_id", "school_id", "exam_id"),
    )


class ExamMark(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin, SoftDeleteMixin
):
    """One student's result on one paper.

    ABSENCE IS A FLAG, NOT A NULL MARK. A row with `is_absent` records "was not
    examined"; a missing row records "not yet entered". Collapsing the two into
    NULL marks would make a half-entered paper indistinguishable from one where
    half the class was away -- and those print very differently on a report card
    (blank vs "AB").
    """

    __tablename__ = "exam_marks"

    paper_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("exam_papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # CASCADE: erasing a student (the GDPR path) erases their marks with them.
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    marks_obtained: Mapped[Decimal | None] = mapped_column(_MARKS)
    """NULL exactly when `is_absent` -- the CHECK below makes the pairing a
    database fact rather than a convention."""

    is_absent: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    remarks: Mapped[str | None] = mapped_column(String(200))

    __table_args__ = (
        UniqueConstraint("paper_id", "student_id", name="uq_exam_marks_paper_student"),
        CheckConstraint(
            "(is_absent AND marks_obtained IS NULL) OR (NOT is_absent AND marks_obtained IS NOT NULL)",
            name="absent_xor_marks",
        ),
        CheckConstraint("marks_obtained IS NULL OR marks_obtained >= 0", name="marks_non_negative"),
        Index("ix_exam_marks_school_id_student_id", "school_id", "student_id"),
    )
