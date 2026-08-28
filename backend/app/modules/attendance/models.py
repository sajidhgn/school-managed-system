"""Attendance models -- who was in the room, on which day, and who says so.

WHY THIS FILE EXISTS
    `docs/modules/attendance.md` is the agreed behaviour; this is its schema.
    Attendance is the highest-frequency write in a school management system: one
    row per student per day, every day, forever. A 1,200-student school generates
    roughly 228,000 rows a year. Every decision below is made with that number in
    view.

RESPONSIBILITY
    Two tables:

        attendance_sessions   ONE register: this section, this date, this period
          attendance_records    ONE line on it: this student, this status

INTERACTIONS
    * `TenantMixin` (organization_id) -> the RLS key; both tables get a policy via
      `setup_tenant_table()` in the migration.
    * `RequiredSchoolMixin` (school_id) -> the campus scope filter, NOT NULL. There
      is no organization-level register.
    * `attendance_sessions.section_id` -> `sections.id` (academics).
    * `attendance_sessions.academic_year_id` -> `academic_years.id`. Denormalised
      onto the session rather than derived from the date, so a term report is an
      indexed equality filter instead of a range scan over every register ever
      taken.
    * `attendance_records.student_id` -> `students.id`.

=============================================================================
FOUR DECISIONS THAT SHAPE EVERYTHING BELOW
=============================================================================

1.  A REGISTER IS A ROW, NOT AN IMPLICIT GROUPING.
    The obvious schema is one flat `attendance` table keyed (student, date,
    status). It cannot answer the question a head teacher actually asks, which is
    "which classes have not submitted today?" -- because an unmarked register and
    a register of thirty present students are both, in a flat table, an absence of
    rows. Making the register a first-class row with a `status` turns "not taken"
    into a fact that can be listed, chased and reported on.

    It also gives the audit trail somewhere to point. "Mrs Khan submitted Grade
    10-B for 12 March at 08:41" is a statement about a register.

2.  `period` IS NOT NULL, WITH 0 MEANING "WHOLE DAY".
    Primary schools mark attendance once a day; secondary schools mark it every
    lesson. Both must be representable, so the register is keyed on a period.

    The natural encoding of "whole day" is `period = NULL`, and it is a trap:
    PostgreSQL treats NULLs as distinct in a unique index, so
    `UNIQUE (section_id, date, period)` would happily accept the same daily
    register five times. The alternatives are a partial index plus a
    `COALESCE`-based second index, or one honest sentinel. The sentinel wins --
    one constraint, one index, and no query that has to remember which of two
    uniqueness rules applies to it.

3.  ABSENCE IS RECORDED, NOT INFERRED.
    Every student on the roster gets a row, including the present ones. Storing
    only absences would halve the table, and would make "was Ali marked present,
    or was Ali simply forgotten?" unanswerable -- which is the one question a
    parent disputing a fine will ask. The register's `status` bounds the cost: a
    submitted register is complete by construction.

4.  RECORDS ARE AMENDED, NEVER DELETED, ONCE SUBMITTED.
    Same reasoning as `fee_payments`. Neither table carries `deleted_at`. A draft
    register can be discarded wholesale; a submitted one is corrected through an
    amendment that writes `before`/`after` into `audit_logs`, gated on a separate
    `attendance:amend` permission. The teacher who marks is not automatically the
    person who can rewrite last month.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
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
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, types only
    from app.modules.students.models import Student


# The sentinel for "this register covers the whole day" -- see decision 2 above.
WHOLE_DAY_PERIOD = 0


class AttendanceStatus(StrEnum):
    """What one student's line on one register says.

    WHY FIVE VALUES AND NOT TWO
        Present/absent is what a database designer writes and what no school uses.
        Each extra value below exists because it changes a downstream number:

          LATE      counts as attended for the percentage a report card prints, but
                    is what a punctuality warning is issued from. Folding it into
                    PRESENT loses the warning; folding it into ABSENT understates
                    attendance and triggers absence alerts for children who are in
                    the building.
          EXCUSED   an absence the school authorised -- illness with a note, a
                    funeral, a sanctioned trip. Excluded from the DENOMINATOR of the
                    attendance percentage, which is the whole point: a child off
                    sick for a fortnight with notes should not fail an attendance
                    threshold they were excused from.
          HALF_DAY  counts as half a day present. Standard in this market for a
                    child collected after the morning session.

        `is_present` and `counts_toward_attendance` below are where those rules are
        stated once, so no report re-derives them.
    """

    PRESENT = "present"
    ABSENT = "absent"
    LATE = "late"
    EXCUSED = "excused"
    HALF_DAY = "half_day"

    @property
    def is_present(self) -> bool:
        """Whether the student was physically in the building."""
        return self in {AttendanceStatus.PRESENT, AttendanceStatus.LATE, AttendanceStatus.HALF_DAY}

    @property
    def credit(self) -> float:
        """How much of a day's attendance this status earns. HALF_DAY earns half."""
        if self is AttendanceStatus.HALF_DAY:
            return 0.5
        return 1.0 if self.is_present else 0.0

    @property
    def counts_toward_attendance(self) -> bool:
        """Whether this status belongs in the percentage's DENOMINATOR.

        EXCUSED does not: an authorised absence is neither attendance nor a failure
        to attend, and counting it either way misreports the child.
        """
        return self is not AttendanceStatus.EXCUSED


class AttendanceSessionStatus(StrEnum):
    """The register's own lifecycle.

    DRAFT -> SUBMITTED is one-way through the ordinary `attendance:mark` path.
    Going back requires `attendance:amend`, which is a different permission held by
    a different person -- the same separation `fee:collect` and `fee:void` draw
    across a cash drawer.
    """

    DRAFT = "draft"
    """Opened, partially marked, not yet asserted. Editable freely; discardable."""

    SUBMITTED = "submitted"
    """The teacher has asserted this register is complete and correct. It now feeds
    reports and absence alerts, and every further change is an audited amendment."""


class AttendanceSession(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin
):
    """One register: one section, one date, one period."""

    __tablename__ = "attendance_sessions"

    section_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # RESTRICT: dissolving a section must not erase the registers taken for it.
        # The academics service already refuses to delete a section with students in
        # it; this refuses to delete one with history behind it.
        ForeignKey("sections.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    academic_year_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("academic_years.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    session_date: Mapped[date] = mapped_column(Date, nullable=False)
    """`Date`, not `DateTime`. A register belongs to a school DAY, and storing it
    with a timezone makes "12 March" become "11 March" for a reader in another
    zone -- which for an attendance record is not a display bug, it is a wrong
    answer about whether a child was in school."""

    period: Mapped[int] = mapped_column(Integer, nullable=False, default=WHOLE_DAY_PERIOD)
    """Lesson slot, or 0 for a whole-day register. See decision 2 in the module
    docstring for why this is not nullable."""

    subject_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="SET NULL"),
        index=True,
    )
    """Which lesson this period-register belongs to.

    Always NULL for a whole-day register, and optional even for a period one -- a
    school can mark per period without having entered its curriculum. Enforced by a
    CHECK: a whole-day register with a subject is a contradiction, not a preference.
    """

    status: Mapped[AttendanceSessionStatus] = mapped_column(
        str_enum(AttendanceSessionStatus, name="status"),
        nullable=False,
        default=AttendanceSessionStatus.DRAFT,
        index=True,
    )

    taken_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # SET NULL: a teacher leaving the school must not delete every register they
        # ever took. The audit log retains their identity against the submission.
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    notes: Mapped[str | None] = mapped_column(Text)
    """Register-level context: "half day -- sports", "exam hall". Distinct from a
    per-student remark, and the thing that explains an anomalous day to whoever
    reads the report six months later."""

    records: Mapped[list[AttendanceRecord]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        # The duplicate-register guard, and the reason `period` is not nullable.
        UniqueConstraint(
            "section_id",
            "session_date",
            "period",
            name="uq_attendance_sessions_section_id_session_date_period",
        ),
        CheckConstraint("period >= 0", name="period_non_negative"),
        # A whole-day register covers every lesson, so it cannot be about one subject.
        CheckConstraint(
            "period > 0 OR subject_id IS NULL",
            name="whole_day_has_no_subject",
        ),
        # The two hot reads: "today's registers for this campus" (the head teacher's
        # not-yet-submitted list) and "this section's registers over a date range"
        # (every report). School-first so the campus scope filter uses the same index.
        Index("ix_attendance_sessions_school_id_session_date", "school_id", "session_date"),
        Index(
            "ix_attendance_sessions_section_id_session_date",
            "section_id",
            "session_date",
        ),
    )

    @property
    def is_whole_day(self) -> bool:
        return self.period == WHOLE_DAY_PERIOD

    @property
    def is_editable(self) -> bool:
        """Whether ordinary `attendance:mark` may still change this register."""
        return self.status is AttendanceSessionStatus.DRAFT


class AttendanceRecord(Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin):
    """One student's line on one register."""

    __tablename__ = "attendance_records"

    session_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("attendance_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    student_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # RESTRICT: a student is soft-deleted, never hard-deleted, so this should
        # never fire. It is here so that if someone ever adds a hard delete, the
        # database refuses rather than silently erasing an attendance history that
        # a parent, an inspector or a court may later ask about.
        ForeignKey("students.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    status: Mapped[AttendanceStatus] = mapped_column(
        str_enum(AttendanceStatus, name="status"),
        nullable=False,
        default=AttendanceStatus.PRESENT,
    )

    minutes_late: Mapped[int | None] = mapped_column(Integer)
    """Only meaningful with `status = late`. Nullable rather than 0-defaulted so
    "marked late, minutes not recorded" stays distinguishable from "late by zero
    minutes", which is not a thing."""

    remarks: Mapped[str | None] = mapped_column(String(300))
    """Per-student note: "left early -- dentist", "note from mother received"."""

    marked_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    """Whose keystroke set this value. Denormalised off the session because an
    amendment changes one line, by a different person, days later -- and attributing
    that to the teacher who submitted the register would be a false record."""

    session: Mapped[AttendanceSession] = relationship(back_populates="records")
    student: Mapped[Student] = relationship()

    __table_args__ = (
        UniqueConstraint(
            "session_id", "student_id", name="uq_attendance_records_session_id_student_id"
        ),
        CheckConstraint(
            "minutes_late IS NULL OR minutes_late >= 0", name="minutes_late_non_negative"
        ),
        # THE index for every per-student report: "Ali's attendance this term" and
        # "who has been absent more than five times". Student first because the
        # student is what those queries filter on; school second so the campus scope
        # predicate is still satisfied from the index.
        Index("ix_attendance_records_student_id_status", "student_id", "status"),
        Index("ix_attendance_records_school_id_student_id", "school_id", "student_id"),
    )
