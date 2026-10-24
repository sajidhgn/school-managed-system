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
from enum import StrEnum
from uuid import UUID

from pydantic import Field, model_validator

from app.common.schemas import BaseSchema, PageMeta
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
    locked: bool = Field(
        description=(
            "Past the marking window -- the day after `session_date` is over -- so only "
            "`attendance:amend` can change it, draft or submitted. Computed when read."
        )
    )
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
    locked: bool = Field(
        description=(
            "Registers for this date are past the marking window: `attendance:mark` "
            "can no longer open or change them, only `attendance:amend` can."
        )
    )
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


# ---------------------------------------------------------------------------
# Analytics -- the class-by-class view a head teacher reads
# ---------------------------------------------------------------------------
#
# EVERY RATIO IN THIS BLOCK IS ON THE 0-100 SCALE, rounded to two places, the same
# scale `StudentAttendanceSummary.percentage` uses -- so the `threshold` a caller
# passes (75 means 75%) compares directly against the numbers that come back. The
# dashboard's own pulse uses 0..1; this endpoint belongs to the attendance module and
# speaks its units.
#
# And every one of them is None, not 0, when there is nothing to divide by -- for the
# reason `StudentAttendanceSummary.percentage` gives.


class RegisterState(StrEnum):
    """Where a section's register for TODAY stands.

    Three values, not `AttendanceSessionStatus | None`, because "nobody has opened
    it" is the state this field exists to surface, and a null is too easy to render
    as a blank cell. Same distinction `SectionDayStatus.session_id is None` draws on
    the daily overview.
    """

    NOT_STARTED = "not_started"
    DRAFT = "draft"
    SUBMITTED = "submitted"


class AttendanceStatusCounts(BaseSchema):
    """Register lines by status. Counts of LINES (student-days), not of students.

    No defaults: every response states all five, so the generated client type has no
    optional field for a caller to null-check.
    """

    present: int
    absent: int
    late: int
    excused: int
    half_day: int


class AttendanceRate(BaseSchema):
    """A rate and what it was computed from."""

    percentage: float | None
    counted: int
    """The denominator: lines that count toward attendance (every status but
    EXCUSED)."""
    counts: AttendanceStatusCounts


class AttendanceDateRange(BaseSchema):
    """An inclusive date range, as resolved by the server."""

    from_date: date
    to_date: date


class AttendanceWindowRate(AttendanceRate):
    """A rate over a named calendar window, with the window's dates."""

    from_date: date
    to_date: date


class AttendanceHeadline(BaseSchema):
    """The numbers a principal quotes: fixed to the CALENDAR, not to the selected
    range, so they do not move when someone changes the date picker. Bounded exactly
    like the rest of the response -- a teacher's are their own sections'."""

    today: AttendanceWindowRate
    this_month: AttendanceWindowRate
    """From the 1st of this month to today."""
    previous_month: AttendanceWindowRate
    """The whole of last calendar month."""
    year_to_date: AttendanceWindowRate | None
    """From the first day of the academic year containing today. None when no year
    in the calendar contains today -- there is no "year" to report on."""


class AttendanceAnalyticsSummary(BaseSchema):
    percentage: float | None
    """The range's attendance rate under the module's rules: SUBMITTED whole-day
    registers only, EXCUSED out of the denominator, HALF_DAY worth 0.5."""
    previous_percentage: float | None
    """The same rate over the equal-length range immediately before -- the trend."""
    counts: AttendanceStatusCounts
    counted: int
    """The denominator: lines that count toward attendance (every status but
    EXCUSED)."""
    school_days: int
    """Distinct dates in the range on which at least one whole-day register was
    SUBMITTED among the sections the caller may see.

    A PROXY, AND DELIBERATELY SO. The module owns no holiday calendar (spec section 2),
    so "the school was open" is inferred from "somebody asserted a register". A day
    on which every teacher forgot is therefore not a school day here -- which is why
    `coverage_percentage` can only ever flag a section that fell behind its
    colleagues, never a whole campus that stopped marking."""
    sections: int
    """Rows in `sections` -- the sections this summary covers."""
    registers_submitted: int
    registers_expected: int
    """`school_days` times the sections that owe a register: those with students on
    roll today, or that were marked at all in the range."""
    coverage_percentage: float | None
    """`registers_submitted / registers_expected`. None when no school day exists."""
    at_risk_students: int
    """Every student under `threshold`, not just the ones listed in `at_risk`."""


class SectionAttendanceAnalytics(BaseSchema):
    """One section's attendance over the range."""

    section_id: UUID
    section_name: str
    class_id: UUID
    class_name: str
    class_level: int
    school_id: UUID
    """Distinguishes "Grade 9 - A" on two campuses when an organization-level
    principal reads with no campus open."""
    class_teacher_id: UUID | None
    class_teacher_name: str | None
    """Who to talk to about this row -- the section's class teacher, as on the daily
    overview, not whoever happened to take the registers."""
    students_on_roll: int
    """Active students seated in the section TODAY."""
    percentage: float | None
    previous_percentage: float | None
    counts: AttendanceStatusCounts
    registers_submitted: int
    """Whole-day registers SUBMITTED in the range: one per date at most, by the
    `(section_id, session_date, period)` unique constraint."""
    registers_draft: int
    """Whole-day registers opened in the range and never submitted. Each is a day
    whose attendance reaches no report until someone asserts it."""
    coverage_percentage: float | None
    """`registers_submitted / school_days` -- how many of the days the school was
    marking this section was marked too."""
    today_status: RegisterState
    at_risk_students: int


class AttendanceTrendDay(BaseSchema):
    """One school day in the range. Only dates with a submitted register appear: a
    weekend is not a day of zero attendance, and listing it as one would draw every
    Sunday as a cliff."""

    session_date: date
    percentage: float | None
    """None only when every line that day was EXCUSED."""
    counted: int
    absent: int


class AttendanceWeekday(BaseSchema):
    """The rate on one day of the week, across the range.

    Exists for the pattern a principal looks for and a daily line hides: Mondays
    after a long weekend, Saturdays in a five-and-a-half-day week.
    """

    weekday: int
    """ISO weekday: 1 Monday ... 7 Sunday. All seven are always present, in order."""
    school_days: int
    percentage: float | None
    absent: int


class AtRiskStudent(BaseSchema):
    """A student whose rate over the range is below the caller's threshold."""

    student_id: UUID
    admission_number: str
    full_name: str
    section_id: UUID | None
    class_name: str | None
    section_name: str | None
    """The student's CURRENT placement -- where someone would go to find them."""
    roll_number: str | None
    percentage: float
    counted_sessions: int
    absent: int
    absence_streak: int
    """Consecutive most-recent submitted whole-day registers, up to `to_date`, on
    which this student is ABSENT. Any other status ends the run -- EXCUSED included,
    because an authorised absence means the school already knows why the child is
    out, and an unexplained run is what this number is for."""


class AttendanceAnalyticsClass(BaseSchema):
    """One option for the class filter -- bounded exactly as the data is, so a teacher
    is never offered a class the endpoint would answer with a 404."""

    class_id: UUID
    class_name: str
    level: int
    school_id: UUID


class AttendanceAnalytics(BaseSchema):
    """Attendance across every section the caller may see, over one date range."""

    from_date: date
    to_date: date
    previous_from_date: date
    previous_to_date: date
    today: date
    """The server's date, which `today_status` on each row refers to -- not
    necessarily inside the range."""
    class_id: UUID | None
    threshold: float
    min_sessions: int
    headline: AttendanceHeadline
    summary: AttendanceAnalyticsSummary
    sections: list[SectionAttendanceAnalytics]
    """Lowest class level first, then section name -- the order of the school, not
    of the numbers. Ranking is the reader's choice and the client's job."""
    days: list[AttendanceTrendDay]
    weekdays: list[AttendanceWeekday]
    at_risk: list[AtRiskStudent]
    """Worst first, capped (see `summary.at_risk_students` for the full count)."""
    classes: list[AttendanceAnalyticsClass]
    """Every class the caller may filter by, whatever `class_id` is set to."""


# ---------------------------------------------------------------------------
# Every child -- the per-student table and its drill-down
# ---------------------------------------------------------------------------


class StudentAttendanceRow(BaseSchema):
    """One student: today's line, this month, last month and the overall range."""

    student_id: UUID
    admission_number: str
    full_name: str
    roll_number: str | None
    section_id: UUID | None
    class_id: UUID | None
    class_name: str | None
    section_name: str | None
    today_register: RegisterState
    """Whether a whole-day register covering this child today exists, and whether it
    has been SUBMITTED. `not_started` -- nobody has marked them -- is a different fact
    from `present`, and the reason this field is separate from `today_status`."""
    today_status: AttendanceStatus | None
    """The child's line today, ONLY once the register is submitted. A draft is
    pre-filled `present` (spec 5.2), so echoing it would report a child as present on
    the strength of a register nobody has asserted."""
    this_month: AttendanceRate
    previous_month: AttendanceRate
    overall: AttendanceRate


class StudentAttendancePage(BaseSchema):
    """`Page[StudentAttendanceRow]`'s envelope -- `items` and `meta` exactly as every
    paginated list (ADR 0001) -- plus the windows the row rates refer to, stated once
    rather than repeated on every row."""

    items: list[StudentAttendanceRow]
    meta: PageMeta
    today: date
    this_month: AttendanceDateRange
    previous_month: AttendanceDateRange
    overall: AttendanceDateRange
    """The academic year so far unless the caller passed a range."""


class StudentAttendanceCalendarDay(BaseSchema):
    """One whole-day register the child is on."""

    session_date: date
    register_state: RegisterState
    """`submitted` or `draft` -- a day with no register has no entry at all."""
    status: AttendanceStatus | None
    """None while the register is a draft, for the reason
    `StudentAttendanceRow.today_status` gives."""


class StudentAttendanceMonth(AttendanceRate):
    month: str
    """`YYYY-MM`. Every month the range touches appears, marked or not."""


class StudentAttendanceCalendar(BaseSchema):
    """One child, day by day, with a rate for the range and for each month in it."""

    student_id: UUID
    admission_number: str
    full_name: str
    section_id: UUID | None
    class_name: str | None
    section_name: str | None
    roll_number: str | None
    from_date: date
    to_date: date
    today: date
    overall: AttendanceRate
    months: list[StudentAttendanceMonth]
    """Oldest first."""
    days: list[StudentAttendanceCalendarDay]
    """Oldest first; only dates with a register."""
