"""Attendance API contracts.

WHY SEPARATE FROM models.py
    These describe what a client may SEND and what it WILL RECEIVE. `organization_id`
    and `school_id` appear in no Create schema: both are taken from the verified JWT,
    never from the request body. Accepting either would be a mass-assignment hole that
    lets a caller write a register into another tenant.

THE REGISTER RESPONSE INLINES THE STUDENT
    `AttendanceEntryRead` carries the student's name, admission number and roll
    number rather than just an id. A register screen renders thirty names on first
    paint; returning ids would guarantee thirty follow-up requests -- an N+1 moved
    out of the database and into the browser, where it is slower.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import Field, model_validator

from app.common.schemas import BaseSchema
from app.modules.attendance.models import (
    WHOLE_DAY_PERIOD,
    AttendanceSessionStatus,
    AttendanceStatus,
)

# ---------------------------------------------------------------------------
# Sessions (registers)
# ---------------------------------------------------------------------------


class AttendanceSessionOpen(BaseSchema):
    """Open a register for one section on one date.

    Idempotent by design at the service layer: opening a register that already
    exists returns the existing one rather than conflicting. A teacher who taps
    "take attendance" twice, or two teachers who tap it at once, must not produce
    two registers for one lesson -- and the unique constraint would otherwise turn
    that double tap into a 409 the user cannot act on.
    """

    section_id: UUID
    session_date: date | None = Field(
        default=None, description="Defaults to today, in the server's timezone."
    )
    period: int = Field(
        default=WHOLE_DAY_PERIOD,
        ge=0,
        le=20,
        description=(
            "Lesson slot, or 0 for a whole-day register. Primary schools mark once a "
            "day (0); secondary schools mark per lesson."
        ),
    )
    subject_id: UUID | None = Field(
        default=None,
        description="Which lesson this is. Rejected when `period` is 0 -- a whole-day "
        "register covers every lesson and so is about no single subject.",
    )
    notes: str | None = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def _whole_day_has_no_subject(self) -> AttendanceSessionOpen:
        """Mirrors `ck_attendance_sessions_whole_day_has_no_subject`.

        The constraint is the guarantee; this is the error message. A raw check
        violation reaches the client as a 409 naming a constraint, which tells a
        teacher nothing about which of the two fields to change.
        """
        if self.period == WHOLE_DAY_PERIOD and self.subject_id is not None:
            raise ValueError("A whole-day register (period 0) cannot name a subject.")
        return self


class AttendanceEntryInput(BaseSchema):
    """One student's status on a register."""

    student_id: UUID
    status: AttendanceStatus
    minutes_late: int | None = Field(default=None, ge=0, le=600)
    remarks: str | None = Field(default=None, max_length=300)


class AttendanceMarkRequest(BaseSchema):
    """Set statuses for some or all students on a register.

    PARTIAL BY DESIGN. A teacher marks the four absentees and leaves twenty-six
    students alone; sending the whole register on every keystroke would be a
    write amplification of 30x for no gain. Students not named keep whatever they
    already have -- which, for a freshly opened register, is `present`.
    """

    entries: list[AttendanceEntryInput] = Field(min_length=1, max_length=500)
    reason: str | None = Field(
        default=None,
        max_length=300,
        description=(
            "Why a SUBMITTED register is being changed. Required for amendments and "
            "recorded in the audit trail; ignored while the register is still a draft."
        ),
    )


class AttendanceEntryRead(BaseSchema):
    id: UUID
    student_id: UUID
    admission_number: str
    full_name: str
    roll_number: str | None
    status: AttendanceStatus
    minutes_late: int | None
    remarks: str | None


class AttendanceSessionRead(BaseSchema):
    """A register without its lines -- for lists and the not-yet-submitted view."""

    id: UUID
    section_id: UUID
    academic_year_id: UUID
    session_date: date
    period: int
    subject_id: UUID | None
    status: AttendanceSessionStatus
    taken_by_user_id: UUID | None
    submitted_at: datetime | None
    notes: str | None
    present_count: int = 0
    absent_count: int = 0
    total_count: int = 0
    created_at: datetime
    updated_at: datetime


class AttendanceSessionDetail(AttendanceSessionRead):
    """A register with every line on it, in roll order.

    `entries` has no default. A default would make it OPTIONAL in the generated
    OpenAPI schema, and every frontend caller would then have to null-check a field
    that is always present -- which in practice means they stop checking and the
    type stops meaning anything. A register always has its lines; the contract says so.
    """

    entries: list[AttendanceEntryRead]


class SectionDayStatus(BaseSchema):
    """One section's attendance state for one date.

    THE POINT OF THE MODULE'S SESSION TABLE. A flat attendance table cannot tell
    "nobody marked Grade 10-B today" apart from "Grade 10-B was fully present",
    because both are an absence of rows. `session_id is None` is that distinction,
    and it is what the head teacher's morning chase list is built from.
    """

    section_id: UUID
    section_name: str
    class_id: UUID
    class_name: str
    class_teacher_id: UUID | None
    class_teacher_name: str | None
    """Who to chase when this row says nobody has marked the register.

    The SECTION's class teacher, deliberately -- not whoever took the register. The
    rows that matter most on this screen are the ones with no register at all, and
    "who took it" is necessarily blank on exactly those. A chase list has to name
    someone precisely where nothing has happened yet.
    """
    session_id: UUID | None
    status: AttendanceSessionStatus | None
    present_count: int
    absent_count: int
    total_count: int


class DailyOverview(BaseSchema):
    session_date: date
    sections: list[SectionDayStatus]
    sections_total: int
    sections_submitted: int
    sections_not_started: int


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


class StudentAttendanceSummary(BaseSchema):
    """One student's attendance over a date range.

    `percentage` is computed as `attended_credit / counted_sessions`, where an
    EXCUSED absence is excluded from BOTH -- an authorised absence is neither
    attendance nor a failure to attend, and counting it either way misreports the
    child. A half day contributes 0.5. See `AttendanceStatus` for why.
    """

    student_id: UUID
    admission_number: str
    full_name: str
    from_date: date
    to_date: date
    total_sessions: int
    """Every register this student appeared on, including excused ones."""
    counted_sessions: int
    """The denominator: `total_sessions` minus excused absences."""
    present: int
    absent: int
    late: int
    excused: int
    half_day: int
    percentage: float | None
    """None -- not 0.0 -- when `counted_sessions` is zero. A student with no
    countable registers has no attendance rate, and reporting 0% would put a
    disciplinary-looking figure against a child nobody has marked yet."""


class SectionAttendanceDay(BaseSchema):
    """One day's headline numbers for one section."""

    session_date: date
    present: int
    absent: int
    late: int
    excused: int
    half_day: int
    total: int


class SectionAttendanceReport(BaseSchema):
    section_id: UUID
    from_date: date
    to_date: date
    days: list[SectionAttendanceDay]
    average_percentage: float | None
