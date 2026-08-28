"""Student models -- the Student Information System record.

WHY THIS FILE EXISTS
    The PDF marks "Student Directory CRUD" as Critical and specifies the payload:
    demographics and emergency contacts. The student row is the spine of the rest of
    the product -- attendance, fee vouchers, ID cards, certificates and the global
    search omnibar all read from it.

RESPONSIBILITY
    Define the `Student` entity, its enrollment lifecycle, and the guardian/emergency
    contact fields the PDF calls for.

INTERACTIONS
    * `TenantMixin` (organization_id) -> RLS policy installed by
      `setup_tenant_table("students")`; `RequiredSchoolMixin` (school_id) is the
      campus scope filter, applied by the permission dependency rather than a policy.
    * `section_id` -> `sections.id` (academics module).
    * Future: attendance, fees and certificate modules all reference `students.id`.

=============================================================================
THE GUARDIAN COLUMNS BELOW ARE A DENORMALISED CACHE. `guardians` IS THE TRUTH.
=============================================================================
    This file used to argue that guardian details belonged here as columns, on the
    grounds that a directory CRUD only needs one reachable number per student and a
    join table would add a write path nothing asked for. That argument had a stated
    expiry -- "when parent logins arrive, promote this into its own aggregate" --
    and `modules/guardians` is that promotion.

    WHAT CHANGED AND WHY IT HAD TO
        The columns cannot express the three things the product now needs:

        1. SIBLINGS. One father with three children was three rows holding the same
           phone number. Correcting it meant editing three students, and the fee
           module's "one bill per family" and the portal's "show me my children"
           both need the opposite direction -- guardian -> students -- which a
           column cannot be queried in.
        2. A LOGIN. A parent portal needs a guardian to be a `users` row. A varchar
           cannot hold an account.
        3. MORE THAN ONE. A child in shared custody has two guardians who both
           receive the absence alert, and exactly one of whom is billed. Two
           `guardian_name` columns is where that road ends.

    WHY THE COLUMNS SURVIVE ANYWAY
        They are kept as a cache of the primary guardian, written by the guardian
        service whenever that link changes. Three reasons:

          * The WhatsApp absence alert and the fee reminder both send to "the
            student's number", and a hot path that must join two tables to find a
            phone number is a join on every message in a 2,000-message batch.
          * The global search omnibar matches on guardian name; a trigram index on
            a column here is a straight substitution for the index that already
            exists.
          * Dropping them would break the students CSV export and every frontend
            table mid-release, for no gain the same release delivers.

        The contract is one-directional and stated once here: the guardian tables
        are written by hand, these columns are written by the system. Nothing
        outside the guardian service may set them.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import Boolean, Date, ForeignKey, Index, String, Text, UniqueConstraint
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
    from app.modules.academics.models import Section


class StudentStatus(StrEnum):
    """Enrollment lifecycle.

    PENDING is what makes the PDF's "Digital Admissions Form" work: a public
    application lands as PENDING and appears in an admissions queue, without ever
    counting as an enrolled student or appearing in a class register.
    """

    PENDING = "pending"  # applied via the admissions form, not yet accepted
    ACTIVE = "active"  # currently enrolled
    INACTIVE = "inactive"  # temporarily withdrawn (long illness, unpaid fees)
    GRADUATED = "graduated"
    TRANSFERRED = "transferred"  # left for another school


class Gender(StrEnum):
    MALE = "male"
    FEMALE = "female"
    OTHER = "other"


class Student(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin, SoftDeleteMixin
):
    """One enrolled (or applying) student at one school."""

    __tablename__ = "students"

    # --- Identity ----------------------------------------------------------
    admission_number: Mapped[str] = mapped_column(String(32), nullable=False)
    """School-issued roll number. Unique per school, not globally -- two schools
    may legitimately both issue "2024-001"."""

    first_name: Mapped[str] = mapped_column(String(80), nullable=False)
    last_name: Mapped[str] = mapped_column(String(80), nullable=False)

    # --- Demographics (PDF: "demographics") --------------------------------
    date_of_birth: Mapped[date | None] = mapped_column(Date)
    """`Date`, not `DateTime`: a birthday is a calendar date, and storing it with a
    timezone makes it shift by a day depending on where it is read."""

    gender: Mapped[Gender | None] = mapped_column(str_enum(Gender, name="gender"))
    address: Mapped[str | None] = mapped_column(Text)
    photo_url: Mapped[str | None] = mapped_column(String(500))
    """Used by the ID Card Generator feature."""

    # --- Guardian contact CACHE (see the module docstring) ------------------
    #
    # Mirrors this student's PRIMARY guardian, maintained by the guardian service.
    # Read freely; write only through `GuardianService`.
    guardian_name: Mapped[str | None] = mapped_column(String(160))
    guardian_phone: Mapped[str | None] = mapped_column(String(32))
    """The number the WhatsApp absence-alert and fee-reminder features message."""
    guardian_email: Mapped[str | None] = mapped_column(String(320))
    emergency_contact_name: Mapped[str | None] = mapped_column(String(160))
    emergency_contact_phone: Mapped[str | None] = mapped_column(String(32))

    # --- Enrollment --------------------------------------------------------
    section_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # SET NULL: dissolving a section must not delete its students. They become
        # unassigned and show up in an "unplaced" filter for the admin to re-seat.
        ForeignKey("sections.id", ondelete="SET NULL"),
        index=True,
    )
    """Nullable by design -- an admitted student may not be placed in a section yet,
    and every PENDING applicant has no section at all."""

    status: Mapped[StudentStatus] = mapped_column(
        str_enum(StudentStatus, name="status"),
        nullable=False,
        default=StudentStatus.ACTIVE,
    )
    enrolled_on: Mapped[date | None] = mapped_column(Date)

    section: Mapped[Section | None] = relationship(back_populates="students")
    enrollments: Mapped[list[StudentEnrollment]] = relationship(
        back_populates="student",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="StudentEnrollment.enrolled_on.desc()",
    )

    __table_args__ = (
        UniqueConstraint(
            "school_id", "admission_number", name="uq_students_school_id_admission_number"
        ),
        # Serves the two hot listings: the section register ("show me everyone in
        # Grade 10-A") and the directory filtered by status. Composite and
        # school-first so the RLS predicate can use the same index.
        Index("ix_students_school_id_section_id", "school_id", "section_id"),
        Index("ix_students_school_id_status", "school_id", "status"),
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    @property
    def is_enrolled(self) -> bool:
        """Whether this student occupies a seat and belongs on a class register."""
        return self.status is StudentStatus.ACTIVE and self.deleted_at is None


# =============================================================================
# ENROLLMENT HISTORY -- where a student sat, and when
# =============================================================================


class StudentEnrollment(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin
):
    """One continuous period a student spent in one section.

    =========================================================================
    WHY `students.section_id` IS NOT ENOUGH, AND WHY IT STAYS ANYWAY
    =========================================================================
        `students.section_id` answers "where is this child NOW". Every module that
        lands next needs to answer "where were they THEN":

          * ATTENDANCE. A register for 12 March belongs to the section the student
            was in on 12 March. Promote them in April and a `section_id`-only join
            silently re-files the whole year's attendance under the new grade, so
            last year's register stops reconciling against last year's roll.
          * REPORT CARDS. "Grade 9, Section B, 2025-2026" is printed on the
            certificate. After promotion the student row says Grade 10.
          * PROMOTION ITSELF. "Move Grade 9-B up to Grade 10-B" has to record what
            it did, or a mistaken bulk promotion cannot be undone -- and bulk
            promotion is a once-a-year, whole-school, irreversible-looking action.

        The current pointer stays because it is on the hot path of every roster
        read, and resolving "the open enrollment" on each of them would turn a
        column read into a correlated subquery. The service writes both together in
        one transaction; this table is the ledger and the column is its head.

    APPEND-MOSTLY, AND THEREFORE NO `deleted_at`
        A closed enrollment is a historical fact. Correcting a mis-seated student
        means closing the wrong row and opening a right one, which is why
        `SoftDeleteMixin` is absent -- the same reasoning that keeps it off
        `fee_vouchers`. `left_on` is how a row ends.
    """

    __tablename__ = "student_enrollments"

    student_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    academic_year_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # RESTRICT: deleting a year that students were enrolled in would erase the
        # record of an entire cohort. The academics service refuses the delete.
        ForeignKey("academic_years.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    class_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("classes.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    section_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("sections.id", ondelete="SET NULL"),
        index=True,
    )
    """Nullable for the same reason `Student.section_id` is: a student can be
    admitted into a grade before being placed in a section, and dissolving a section
    must not erase the enrollment that ran through it."""

    roll_number: Mapped[str | None] = mapped_column(String(16))
    """Position in the class register, e.g. "17".

    DISTINCT FROM `admission_number`, which is issued once and never changes. The
    roll number is re-assigned every year in register order, is the number a teacher
    calls out, and is what a mark sheet is sorted by. Conflating them is why schools
    end up reading admission numbers aloud at assembly.
    """

    enrolled_on: Mapped[date] = mapped_column(Date, nullable=False)
    left_on: Mapped[date | None] = mapped_column(Date)
    """NULL means this is the OPEN enrollment -- the student is currently seated
    here. A partial unique index in the migration enforces at most one open row per
    student; see `uq_student_enrollments_one_open`."""

    is_promotion: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """Whether this row was created by the year-end bulk promotion rather than by a
    hand placement. Kept so an accidental promotion run can be identified and
    reversed as a set, rather than by guessing from timestamps."""

    notes: Mapped[str | None] = mapped_column(Text)

    student: Mapped[Student] = relationship(back_populates="enrollments")

    __table_args__ = (
        Index("ix_student_enrollments_school_id_section_id", "school_id", "section_id"),
        Index(
            "ix_student_enrollments_academic_year_id_class_id",
            "academic_year_id",
            "class_id",
        ),
        # A roll number identifies a student within one section for one year. Scoped
        # to the section rather than the class, because two sections of Grade 10 each
        # legitimately have a roll 1. Partial (`WHERE roll_number IS NOT NULL`) so any
        # number of unnumbered enrollments may coexist -- raw DDL in the migration.
    )

    @property
    def is_open(self) -> bool:
        return self.left_on is None
