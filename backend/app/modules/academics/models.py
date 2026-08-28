"""Academics models -- the class/section hierarchy a school is organised by.

WHY THIS FILE EXISTS
    The PDF marks "Class & Section Setup" as Critical: a school creates grades
    (Grade 10) and sub-sections within them (Section A, B). Almost everything that
    follows hangs off this hierarchy -- students enroll into a section, attendance
    is taken per section, a timetable slots lessons into a section, and fee
    structures are defined per class. Getting the shape right here is load-bearing
    for every later module.

RESPONSIBILITY
    Define `SchoolClass` (a grade level) and `Section` (a sub-division of one), plus
    the constraints that keep them unique *within a tenant*.

INTERACTIONS
    * Both carry `TenantMixin` (organization_id -> RLS) and `RequiredSchoolMixin`
      (school_id -> scope filter), so both get a policy via `setup_tenant_table()`.
    * `Section.class_teacher_id` points at `users.id` -- the assignment that the
      PDF's "Teacher (limited to assigned classes)" RBAC rule will be read from.
    * `students.Student.section_id` points at `sections.id`.

WHY `SchoolClass` AND NOT `Class`
    `class` is a Python keyword. The table is still `classes`; only the Python
    identifier is prefixed, which is why `__tablename__` is set explicitly rather
    than left to the automatic convention in db/base.py.

=============================================================================
THE CALENDAR AND THE SUBJECT LIST LIVE HERE TOO -- and why that is not a dump
=============================================================================
    This module owns four aggregates, not two:

        AcademicYear -> Term        the CALENDAR a school runs on
        Subject      -> ClassSubject the CURRICULUM a grade studies
        SchoolClass  -> Section      the STRUCTURE students sit in

    They are one module because they are one setup screen and one permission
    (`class:read` / `class:manage` family, plus `subject:*` for the curriculum
    half), and because every one of them is a dimension that attendance, the
    gradebook, the timetable and the report card index into. Splitting the
    calendar into its own module would give it its own router, its own
    permissions and its own doc for four columns that nothing reads without also
    reading a section.

    WHY THE CALENDAR IS A TABLE AND NOT A STRING
        `fees` already carries `academic_year` as free text ("2026-2027"), which
        works because a challan only ever needs to *label* a year. Attendance
        cannot: computing "Ali was present 168 of 190 school days" requires
        knowing when the year STARTED, when it ENDED, and which days inside it the
        school was actually open. A string cannot answer any of those, and three
        modules independently parsing "2026-2027" into dates is three chances to
        disagree about whether the year starts in March or April.

        The fees column is deliberately left alone: re-keying issued challans onto
        a foreign key is a data migration on financial records, and this slice does
        not need it. `AcademicYear.name` uses the identical format, so the two are
        joinable by label the day that migration is worth doing.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
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

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, types only
    from app.modules.students.models import Student


# =============================================================================
# TWO SCOPE COLUMNS, NOT ONE -- and they do different jobs
# =============================================================================
#   `organization_id` (TenantMixin)      -- the RLS key. The database refuses to
#                                           return these rows to another tenant.
#   `school_id`       (RequiredSchoolMixin) -- the scope filter. Enforced by the
#                                           permission dependency, not by a policy.
#
# A class belongs to exactly one campus, so `school_id` is NOT NULL here. The
# unique constraints below stay keyed on `school_id` because that is the level at
# which "Grade 10" must be unique: an organization running three campuses has three
# legitimate "Grade 10"s, and keying them on `organization_id` would collide them.


class SchoolClass(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin, SoftDeleteMixin
):
    """A grade level within one school, e.g. "Grade 10"."""

    __tablename__ = "classes"

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    """Display name, e.g. "Grade 10" or "Year 6".

    Free text rather than a fixed ladder: naming differs per country and per school
    (Grade/Year/Form/Class), and forcing a canonical scheme would make the product
    unusable outside the region it was designed in.
    """

    level: Mapped[int] = mapped_column(Integer, nullable=False)
    """Numeric rank used for ordering, e.g. 10 for "Grade 10".

    Sorting on `name` alphabetically puts "Grade 10" before "Grade 2", which is
    wrong in every school report. An explicit integer keeps ordering correct and
    lets later modules express "promote everyone one level up" arithmetically.
    """

    sections: Mapped[list[Section]] = relationship(
        back_populates="school_class",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        # Scoped to the school, NOT global -- every school has its own "Grade 10".
        # This is the single most repeated multi-tenant modelling mistake: a global
        # unique index here would let the first school to create "Grade 10" block
        # every other tenant from doing the same.
        UniqueConstraint("school_id", "name", name="uq_classes_school_id_name"),
        UniqueConstraint("school_id", "level", name="uq_classes_school_id_level"),
        # Short name only -- the convention in db/base.py prefixes it to
        # `ck_classes_level_non_negative`. Passing the full name here would yield
        # `ck_classes_ck_classes_level_non_negative`.
        CheckConstraint("level >= 0", name="level_non_negative"),
        Index("ix_classes_school_id_level", "school_id", "level"),
    )


class Section(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin, SoftDeleteMixin
):
    """A sub-division of a class, e.g. "A" within "Grade 10"."""

    __tablename__ = "sections"

    class_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("classes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(40), nullable=False)
    """Section label, e.g. "A", "Blue", "Morning"."""

    capacity: Mapped[int | None] = mapped_column(Integer)
    """Optional seat limit, enforced by the service on enrollment.

    Nullable because plenty of schools do not cap sections, and a sentinel value
    like 0 or 9999 would be indistinguishable from a real (if silly) limit.
    """

    class_teacher_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # SET NULL, not CASCADE: a teacher leaving must not delete the section and
        # every student record hanging off it. The section simply becomes unassigned.
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )

    school_class: Mapped[SchoolClass] = relationship(back_populates="sections")
    students: Mapped[list[Student]] = relationship(back_populates="section")

    __table_args__ = (
        # `class_id` alone would be enough for correctness, since a class belongs to
        # exactly one school. `school_id` is included so the constraint still holds
        # if a section is ever re-parented, and so the index is directly usable by
        # the RLS predicate, which always filters on school_id first.
        UniqueConstraint("school_id", "class_id", "name", name="uq_sections_school_class_name"),
        CheckConstraint("capacity IS NULL OR capacity > 0", name="capacity_positive"),
    )


# =============================================================================
# THE CALENDAR -- academic years and the terms inside them
# =============================================================================


class AcademicYear(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin, SoftDeleteMixin
):
    """One school year, e.g. "2026-2027", with real start and end dates.

    WHY A ROW AND NOT A STRING
        See the module docstring. The short version: attendance percentages,
        promotion, and report cards all need to know the year's BOUNDS, and only a
        row carries them.

    WHY SCHOOL-SCOPED AND NOT ORGANIZATION-SCOPED
        A trust running a city campus and a rural campus routinely runs two
        calendars -- the rural campus shifts its year around the harvest, and
        international branches run September-June against a local April-March. One
        org-level calendar would force one of those campuses to record attendance
        against dates it was closed.

        The cost is that a trust with a genuinely shared calendar creates the same
        year once per campus. That is a few seconds of setup, paid once a year, in
        exchange for not making the multi-calendar case unrepresentable.
    """

    __tablename__ = "academic_years"

    name: Mapped[str] = mapped_column(String(32), nullable=False)
    """Display label, e.g. "2026-2027".

    Free text and deliberately the SAME format `fees.academic_year` already uses, so
    the two are joinable by label until the fees column is migrated onto this key.
    """

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """Which year new work defaults to.

    A DERIVED answer -- "the year whose bounds contain today" -- is wrong twice a
    year: during the summer gap no year contains today, and in the fortnight where a
    school is finalising last year's results while enrolling for the next, two are
    legitimately live. An explicit flag lets the registrar say which one the app
    should default to, and the partial unique index in the migration
    (`WHERE is_current`) guarantees there is at most one per school.
    """

    terms: Mapped[list[Term]] = relationship(
        back_populates="academic_year",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Term.sequence",
    )

    __table_args__ = (
        UniqueConstraint("school_id", "name", name="uq_academic_years_school_id_name"),
        CheckConstraint("end_date > start_date", name="dates_ordered"),
        Index("ix_academic_years_school_id_start_date", "school_id", "start_date"),
        # NOTE: "at most one current year per school" is a PARTIAL unique index
        # (`WHERE is_current`), which `UniqueConstraint` cannot express. It is raw
        # DDL in the migration -- see `uq_academic_years_one_current`.
    )

    def contains(self, day: date) -> bool:
        """Whether `day` falls inside this year, inclusive of both bounds."""
        return self.start_date <= day <= self.end_date


class Term(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin, SoftDeleteMixin
):
    """A reporting period inside an academic year, e.g. "Term 1" or "Spring Semester".

    WHY TERMS EXIST BEFORE THE GRADEBOOK DOES
        A term is the unit a report card is issued for and the unit an attendance
        percentage is quoted over ("92% this term"). Both consumers need the same
        boundaries, and defining them in whichever module lands first would make the
        second one import from it -- gradebook importing attendance, or worse, both
        keeping their own copy.

    TERMS MAY NOT OVERLAP within a year. That is enforced in the service rather than
    by a constraint: PostgreSQL can express it with an exclusion constraint over a
    daterange, but doing so requires btree_gist and makes the error message a raw
    constraint violation rather than something a registrar can act on.
    """

    __tablename__ = "terms"

    academic_year_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("academic_years.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(60), nullable=False)

    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    """1-based ordering within the year.

    Same reason `SchoolClass.level` exists: sorting "Term 1, Term 10, Term 2"
    alphabetically is wrong on every report card, and "which term came before this
    one?" is arithmetic the gradebook needs for cumulative averages.
    """

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    academic_year: Mapped[AcademicYear] = relationship(back_populates="terms")

    __table_args__ = (
        UniqueConstraint("academic_year_id", "sequence", name="uq_terms_academic_year_id_sequence"),
        UniqueConstraint("academic_year_id", "name", name="uq_terms_academic_year_id_name"),
        CheckConstraint("end_date > start_date", name="dates_ordered"),
        CheckConstraint("sequence >= 1", name="sequence_positive"),
    )


# =============================================================================
# THE CURRICULUM -- subjects, and which grade studies them
# =============================================================================


class SubjectKind(StrEnum):
    """Whether every student in the grade takes this subject.

    Drives two concrete behaviours rather than being decoration: the gradebook
    must not show an ELECTIVE as missing for a student who never chose it, and the
    timetable may schedule two electives into the same slot but never two cores.
    """

    CORE = "core"
    ELECTIVE = "elective"
    ACTIVITY = "activity"
    """Sports, clubs, library period. Timetabled and attended, but not graded --
    which is why it is a third value rather than an `is_graded` boolean bolted onto
    a two-value enum."""


class Subject(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin, SoftDeleteMixin
):
    """One teachable subject at one school, e.g. "Mathematics"."""

    __tablename__ = "subjects"

    code: Mapped[str] = mapped_column(String(24), nullable=False)
    """Short handle, e.g. "MATH". Unique per school.

    Exists because a timetable grid and a report-card column are both too narrow for
    "Mathematics", and letting each screen invent its own abbreviation produces
    "Math", "Maths" and "MTH" for one subject.
    """

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    kind: Mapped[SubjectKind] = mapped_column(
        str_enum(SubjectKind, name="kind"),
        nullable=False,
        default=SubjectKind.CORE,
    )

    __table_args__ = (
        UniqueConstraint("school_id", "code", name="uq_subjects_school_id_code"),
        UniqueConstraint("school_id", "name", name="uq_subjects_school_id_name"),
    )


class ClassSubject(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin, SoftDeleteMixin
):
    """A subject taught to one class, optionally by a named teacher.

    WHY THE CURRICULUM IS KEYED ON THE CLASS AND NOT THE SECTION
        "Grade 10 studies Physics" is a curriculum decision; "Grade 10-B's Physics is
        taught by Mrs Khan" is a staffing one. Keying the row on the class keeps the
        first fact stated once instead of once per section, which is what stops
        Grade 10-A and Grade 10-B silently drifting onto different syllabi.

        `teacher_id` is therefore nullable and means "the default teacher for this
        subject across the grade". Per-section assignment is a timetable concern and
        lands with the timetable, which owns the (section, subject, slot, teacher)
        tuple. Putting a `section_id` here now would create a second, competing
        answer to "who teaches this" that the timetable would immediately contradict.
    """

    __tablename__ = "class_subjects"

    class_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("classes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # RESTRICT, not CASCADE: deleting a subject that a grade still studies would
        # silently strip it from the curriculum (and, once the gradebook lands, orphan
        # its marks). The service refuses the delete and names the classes instead.
        ForeignKey("subjects.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    teacher_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # SET NULL: a teacher leaving must not remove the subject from the curriculum.
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )

    weekly_periods: Mapped[int | None] = mapped_column(Integer)
    """How many lessons a week this subject gets. Read by the timetable generator;
    nullable because a school setting up its curriculum has not necessarily decided
    the timetable yet."""

    subject: Mapped[Subject] = relationship()
    school_class: Mapped[SchoolClass] = relationship()

    __table_args__ = (
        UniqueConstraint("class_id", "subject_id", name="uq_class_subjects_class_id_subject_id"),
        CheckConstraint(
            "weekly_periods IS NULL OR weekly_periods > 0", name="weekly_periods_positive"
        ),
        Index("ix_class_subjects_school_id_class_id", "school_id", "class_id"),
    )
