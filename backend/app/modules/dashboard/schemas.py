"""Dashboard analytics response contracts.

Every section is nullable, and None means exactly one thing: the caller does not
hold the permission that section is read under. An empty school is not None -- it is
a section of zeroes -- so the frontend can tell "you may not see this" from "there
is nothing here yet" without guessing.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.common.schemas import BaseSchema

# ---------------------------------------------------------------------------
# Students
# ---------------------------------------------------------------------------


class GenderSlice(BaseSchema):
    gender: str
    """`male`, `female`, `other`, or `unspecified` for a record with no value."""
    count: int


class ClassHeadcount(BaseSchema):
    class_name: str
    level: int
    count: int


class StudentPulse(BaseSchema):
    active: int
    pending: int
    """Admissions applications not yet accepted -- the registrar's queue."""
    joined_last_30_days: int
    gender: list[GenderSlice]
    by_class: list[ClassHeadcount]
    """Active students per grade, lowest level first. Students without a section are
    not in any class and so are absent here; `active` still counts them."""
    unplaced: int
    """Active students with no section -- enrolled but on no register."""


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------


class StatusMix(BaseSchema):
    present: int = 0
    late: int = 0
    absent: int = 0
    excused: int = 0
    half_day: int = 0


class AttendanceDay(BaseSchema):
    day: date
    rate: float | None
    """0..1, or None when no submitted register covers the day (a weekend, a
    holiday, or a day nobody marked). None is not 0: a zero would paint a holiday as
    a day the whole school stayed home."""
    marked: int
    """Lines counted toward the rate that day."""


class AttendanceToday(BaseSchema):
    sections_total: int
    """Sections with at least one active student -- the registers that are owed."""
    sections_submitted: int
    mix: StatusMix
    rate: float | None


class AttendancePulse(BaseSchema):
    today: AttendanceToday
    days: list[AttendanceDay]
    """Oldest first, one entry per calendar day, ending today."""
    rate_30d: float | None
    rate_prev_30d: float | None
    """The 30 days before that, so the card can say which way the school is moving."""
    mix_30d: StatusMix


# ---------------------------------------------------------------------------
# Fees
# ---------------------------------------------------------------------------


class MonthCollection(BaseSchema):
    month: str
    """`YYYY-MM`."""
    collected: Decimal


class FeePulse(BaseSchema):
    academic_year: str | None
    currency: str
    billed: Decimal
    collected: Decimal
    outstanding: Decimal
    overdue: Decimal
    collection_rate: float | None
    months: list[MonthCollection]
    """Twelve months of receipts by `received_on`, oldest first, gaps filled with 0.
    Read off payments rather than vouchers: it answers "when did the money arrive",
    which is the cash-flow question, not "when was it billed"."""


# ---------------------------------------------------------------------------
# Exams
# ---------------------------------------------------------------------------


class SubjectScore(BaseSchema):
    subject: str
    average_pct: float
    pass_rate: float | None
    """Share of graded sittings at or above the paper's pass mark. None when no
    paper for this subject has a pass mark set."""
    sat: int


class ExamPulse(BaseSchema):
    exam_name: str
    exam_status: str
    subjects: list[SubjectScore]
    """Strongest subject first."""


# ---------------------------------------------------------------------------
# The whole board
# ---------------------------------------------------------------------------


class DashboardAnalytics(BaseSchema):
    as_of: date
    students: StudentPulse | None
    attendance: AttendancePulse | None
    fees: FeePulse | None
    exams: ExamPulse | None
    """The one exception to the rule above: also None when no exam has marks yet,
    because an exam with nothing graded has no shape to draw."""
