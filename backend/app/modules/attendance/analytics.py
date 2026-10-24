"""Attendance analytics -- the head teacher's view across classes, and every child in them.

WHY THIS FILE EXISTS
    `service.py` records registers and answers questions about ONE register, ONE
    section or ONE student. A principal asks a different kind of question: "which
    classes are slipping, which children are we losing, and is anyone not marking?"
    Answering that by calling the per-section report once per section is the N+1
    the module docstring of `repository.py` warns about, so this is its own read-only
    service over `AttendanceAnalyticsRepository`, which answers each question in a
    fixed number of grouped statements whatever the school's size.

    Three reads:

        analytics()         GET /attendance/analytics
                            per-section rows, a daily trend, the weekday pattern,
                            the at-risk list, and the today / month / year headline
        students()          GET /attendance/students
                            one row per child: today's line, this month, last month
                            and an overall range -- paginated, searchable, sortable
        student_calendar()  GET /attendance/students/{id}/calendar
                            one child day by day, with a rate per month

INTERACTIONS
    * `AttendanceAnalyticsRepository` -- every query; nothing here touches SQL.
    * `AcademicsService.get_visible_class` -- the class filter, so a class from
      another campus, another organization, or (for a teacher) one they do not teach
      is the same 404 as an id that never existed.
    * `SectionRepository` -- headcounts, class teacher names and section labels,
      reused so "how a section id becomes a name" keeps one implementation.
    * `router.py` passes `teacher_id` exactly as for the other attendance reads.

=============================================================================
THE RULES, AND WHERE THEY ARE NOT RESTATED
=============================================================================
    Every rate here follows the module's rules, which live on `AttendanceStatus`
    (spec section 4.2): only SUBMITTED registers count, EXCUSED leaves the
    denominator, HALF_DAY earns 0.5, LATE is present. `_percentage` below and
    `repository._rate_of` both read the enum's `credit` and
    `counts_toward_attendance` rather than spelling the numbers out again. A rate is
    None, never 0, when nothing is countable.

    What this file adds is ONE further rule: the unit is the WHOLE-DAY register
    (`period = 0`). A lesson register answers whether a child was in chemistry, and
    counting eight of them as a day would weight that day eight times. A school that
    marks only per lesson therefore sees empty analytics -- stated in the spec's
    Analytics section rather than papered over with a guess at how lessons add up to
    a day.

    The one consequence worth knowing: `GET /attendance/students/{id}/summary`
    predates this file and counts every register, lesson ones included. For a school
    that marks only whole-day registers -- nearly every school in this market -- the
    two agree exactly; for one that marks both, the analytics endpoints are the
    day-based figure and the summary is the register-based one.

=============================================================================
"SCHOOL DAYS" IS A PROXY
=============================================================================
    There is no holiday calendar (spec section 2), so a school day is a date on which
    at least one whole-day register was SUBMITTED among the sections the caller may
    see. Marking coverage is measured against that. A day nobody marked at all is
    therefore invisible here -- which is why the daily overview exists, to chase
    registers on the day rather than discover them missing in a report.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from math import ceil
from typing import Any
from uuid import UUID

from sqlalchemy import RowMapping
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas import PageMeta, PageParams, SortDirection, SortParams
from app.core.exceptions import NotFoundError, ValidationError
from app.modules.academics.repository import SectionRepository
from app.modules.academics.service import AcademicsService
from app.modules.attendance.models import (
    WHOLE_DAY_PERIOD,
    AttendanceSessionStatus,
    AttendanceStatus,
)
from app.modules.attendance.repository import (
    STUDENT_SORTS,
    AttendanceAnalyticsRepository,
    DateWindow,
    StatusCounts,
)
from app.modules.attendance.schemas import (
    AtRiskStudent,
    AttendanceAnalytics,
    AttendanceAnalyticsClass,
    AttendanceAnalyticsSummary,
    AttendanceDateRange,
    AttendanceHeadline,
    AttendanceRate,
    AttendanceStatusCounts,
    AttendanceTrendDay,
    AttendanceWeekday,
    AttendanceWindowRate,
    RegisterState,
    SectionAttendanceAnalytics,
    StudentAttendanceCalendar,
    StudentAttendanceCalendarDay,
    StudentAttendanceMonth,
    StudentAttendancePage,
    StudentAttendanceRow,
)
from app.modules.students.repository import StudentRepository

DEFAULT_RANGE_DAYS = 30
"""The analytics page's default window -- long enough that one bad week does not
dominate, short enough to be about the present."""

MAX_RANGE_DAYS = 366
"""One leap year. A longer range is almost always a mistyped year, and it is the
bound that keeps every grouped query here a fixed size."""

DEFAULT_THRESHOLD = 75.0
"""Percent. The figure most schools in this market and most exam boards use as the
attendance floor, and an easy one for a principal to change per request."""

DEFAULT_MIN_SESSIONS = 5
"""A child needs this many counted registers before they can be flagged at risk."""

AT_RISK_LIMIT = 100
"""The at-risk list is a worklist, not an export. The full count is in the summary."""

STREAK_LOOKBACK_DAYS = MAX_RANGE_DAYS
"""How far before `to_date` an absence streak may reach. A run longer than a year is
not a streak, it is a child who has left without anyone recording it."""


def _today() -> date:
    """The server's date, in UTC -- the same clock the rest of the module uses
    (`AttendanceService.open_session`), so "today" here is the "today" a register
    was opened for."""
    return datetime.now(UTC).date()


def _percentage(counts: Mapping[AttendanceStatus, int]) -> float | None:
    """The attendance rate, 0-100, from per-status counts -- None when nothing counts.

    Reads the rules off the enum rather than restating them; see the module
    docstring. Two decimal places, as `StudentAttendanceSummary.percentage`.
    """
    counted = sum(n for s, n in counts.items() if s.counts_toward_attendance)
    credit = sum(s.credit * n for s, n in counts.items() if s.counts_toward_attendance)
    return round(credit / counted * 100, 2) if counted else None


def _counted(counts: Mapping[AttendanceStatus, int]) -> int:
    return sum(n for s, n in counts.items() if s.counts_toward_attendance)


def _counts(counts: Mapping[AttendanceStatus, int]) -> AttendanceStatusCounts:
    return AttendanceStatusCounts(**{s.value: counts.get(s, 0) for s in AttendanceStatus})


def _rate_fields(counts: Mapping[AttendanceStatus, int]) -> dict[str, Any]:
    """The three fields every `AttendanceRate` shape carries."""
    return {
        "percentage": _percentage(counts),
        "counted": _counted(counts),
        "counts": _counts(counts),
    }


def _rate(counts: Mapping[AttendanceStatus, int]) -> AttendanceRate:
    return AttendanceRate(**_rate_fields(counts))


def _window_rate(
    counts: Mapping[AttendanceStatus, int], window: DateWindow
) -> AttendanceWindowRate:
    return AttendanceWindowRate(from_date=window[0], to_date=window[1], **_rate_fields(counts))


def _merge(*tallies: Mapping[AttendanceStatus, int]) -> StatusCounts:
    merged: StatusCounts = {}
    for tally in tallies:
        for status, n in tally.items():
            merged[status] = merged.get(status, 0) + n
    return merged


def _share(part: int, whole: int) -> float | None:
    return round(part / whole * 100, 2) if whole else None


def _this_month(today: date) -> DateWindow:
    return today.replace(day=1), today


def _previous_month(today: date) -> DateWindow:
    last = today.replace(day=1) - timedelta(days=1)
    return last.replace(day=1), last


def _validated(from_date: date, to_date: date) -> None:
    """The two range rules every analytics read shares.

    Same codes as the module's reports for the first (`INVALID_DATE_RANGE`), so a
    client handles a reversed range one way everywhere.
    """
    if to_date < from_date:
        raise ValidationError(
            "`to_date` must not be before `from_date`.", code="INVALID_DATE_RANGE"
        )
    if (to_date - from_date).days + 1 > MAX_RANGE_DAYS:
        raise ValidationError(
            f"A date range can span at most {MAX_RANGE_DAYS} days.",
            code="DATE_RANGE_TOO_LONG",
            details={"max_days": MAX_RANGE_DAYS},
        )


def _register_state(states: Sequence[tuple[int, AttendanceSessionStatus]]) -> RegisterState:
    """Today's state from the registers one section opened today.

    The daily overview's rule, so both screens agree: the whole-day register if
    there is one, otherwise whichever lesson register exists. A section with only
    lesson registers is "taken" on the chase list even though its lines do not reach
    these rates -- the chase list asks whether a teacher has marked, not how.
    """
    if not states:
        return RegisterState.NOT_STARTED
    whole_day = [state for period, state in states if period == WHOLE_DAY_PERIOD]
    state = whole_day[0] if whole_day else states[0][1]
    return (
        RegisterState.SUBMITTED
        if state is AttendanceSessionStatus.SUBMITTED
        else RegisterState.DRAFT
    )


def _full_name(first: str, last: str) -> str:
    """`Student.full_name`, for rows read as columns rather than as an ORM object."""
    return f"{first} {last}"


class AttendanceAnalyticsService:
    """Read-only analytics over submitted whole-day registers."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.academics = AcademicsService(session)
        self.sections = SectionRepository(session)
        self.student_repo = StudentRepository(session)

    def _repo(
        self, *, teacher_id: UUID | None, class_id: UUID | None = None
    ) -> AttendanceAnalyticsRepository:
        return AttendanceAnalyticsRepository(self.session, teacher_id=teacher_id, class_id=class_id)

    @staticmethod
    async def _year_so_far(repo: AttendanceAnalyticsRepository, to_date: date) -> date:
        """The default start of an "overall" range: the first day of the academic
        year containing `to_date`, or 365 days back for a school with no calendar.

        A year configured longer than the cap is clamped rather than refused -- the
        caller asked for nothing, so there would be nothing for them to fix.
        """
        start = await repo.year_start(to_date) or to_date - timedelta(days=364)
        return max(start, to_date - timedelta(days=MAX_RANGE_DAYS - 1))

    async def _check_class(self, class_id: UUID | None, teacher_id: UUID | None) -> None:
        """404 for a class the caller cannot see -- unknown, another campus or
        organization, or (for a teacher) untaught -- all worded identically."""
        if class_id is not None:
            await self.academics.get_visible_class(class_id, teacher_id=teacher_id)

    # -- the class-by-class view --------------------------------------------

    async def analytics(
        self,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        class_id: UUID | None = None,
        threshold: float = DEFAULT_THRESHOLD,
        min_sessions: int = DEFAULT_MIN_SESSIONS,
        teacher_id: UUID | None = None,
        today: date | None = None,
    ) -> AttendanceAnalytics:
        """Every section the caller may see, over one range, plus who is at risk.

        Defaults to the 30 days ending today. The previous period is the range of
        the same length immediately before it, so a trend always compares like with
        like -- a 7-day view against the 7 days before, not against last month.
        """
        today = today or _today()
        to_date = to_date or today
        from_date = from_date or to_date - timedelta(days=DEFAULT_RANGE_DAYS - 1)
        _validated(from_date, to_date)
        await self._check_class(class_id, teacher_id)

        span = (to_date - from_date).days + 1
        previous_to = from_date - timedelta(days=1)
        previous_from = previous_to - timedelta(days=span - 1)
        repo = self._repo(teacher_id=teacher_id, class_id=class_id)

        # Sequential, not gathered: one AsyncSession is one connection and cannot run
        # two statements at once. Each line is one grouped statement.
        visible = await repo.sections()
        daily = await repo.daily_counts(previous_from, to_date)
        by_section = await repo.section_counts(previous_from, from_date, to_date)
        registers = await repo.register_counts(from_date, to_date)
        school_days = await repo.school_days(from_date, to_date)
        today_registers = await repo.registers_on(today)
        at_risk_counts = await repo.at_risk_by_section(from_date, to_date, threshold, min_sessions)
        at_risk = await self._at_risk(repo, from_date, to_date, threshold, min_sessions)
        headline = await self._headline(repo, today)
        headcounts = await self.sections.headcounts()

        shown = [(s, c) for s, c in visible if class_id is None or c.id == class_id]
        teacher_names = await self.sections.teacher_names(
            {s.class_teacher_id for s, _ in shown if s.class_teacher_id is not None}
        )
        states: dict[UUID, list[tuple[int, AttendanceSessionStatus]]] = {}
        for section_id, period, state in today_registers:
            states.setdefault(section_id, []).append((period, state))

        rows: list[SectionAttendanceAnalytics] = []
        for section, school_class in shown:
            current = by_section.get((section.id, True), {})
            submitted = registers.get(section.id, {}).get(AttendanceSessionStatus.SUBMITTED, 0)
            rows.append(
                SectionAttendanceAnalytics(
                    section_id=section.id,
                    section_name=section.name,
                    class_id=school_class.id,
                    class_name=school_class.name,
                    class_level=school_class.level,
                    school_id=section.school_id,
                    class_teacher_id=section.class_teacher_id,
                    class_teacher_name=(
                        teacher_names.get(section.class_teacher_id)
                        if section.class_teacher_id is not None
                        else None
                    ),
                    students_on_roll=headcounts.get(section.id, 0),
                    percentage=_percentage(current),
                    previous_percentage=_percentage(by_section.get((section.id, False), {})),
                    counts=_counts(current),
                    registers_submitted=submitted,
                    registers_draft=registers.get(section.id, {}).get(
                        AttendanceSessionStatus.DRAFT, 0
                    ),
                    coverage_percentage=_share(submitted, school_days),
                    today_status=_register_state(states.get(section.id, [])),
                    at_risk_students=at_risk_counts.get(section.id, 0),
                )
            )

        current_days = {d: c for d, c in daily.items() if d >= from_date}
        current_total = _merge(*current_days.values())
        previous_total = _merge(*(c for d, c in daily.items() if d < from_date))
        # A section owes a register on every school day if it has children on roll
        # today, or if it was marked at all in the range (a class emptied by a
        # mid-range promotion still owed its registers before it emptied).
        owing = sum(1 for r in rows if r.students_on_roll > 0 or r.registers_submitted > 0)
        submitted_total = sum(r.registers_submitted for r in rows)
        expected = owing * school_days

        return AttendanceAnalytics(
            from_date=from_date,
            to_date=to_date,
            previous_from_date=previous_from,
            previous_to_date=previous_to,
            today=today,
            class_id=class_id,
            threshold=threshold,
            min_sessions=min_sessions,
            headline=headline,
            summary=AttendanceAnalyticsSummary(
                percentage=_percentage(current_total),
                previous_percentage=_percentage(previous_total),
                counts=_counts(current_total),
                counted=_counted(current_total),
                school_days=school_days,
                sections=len(rows),
                registers_submitted=submitted_total,
                registers_expected=expected,
                coverage_percentage=_share(submitted_total, expected),
                at_risk_students=sum(at_risk_counts.values()),
            ),
            sections=rows,
            days=[
                AttendanceTrendDay(
                    session_date=day,
                    percentage=_percentage(counts),
                    counted=_counted(counts),
                    absent=counts.get(AttendanceStatus.ABSENT, 0),
                )
                for day, counts in sorted(current_days.items())
            ],
            weekdays=self._weekdays(current_days),
            at_risk=at_risk,
            classes=self._class_options(visible),
        )

    async def _headline(
        self, repo: AttendanceAnalyticsRepository, today: date
    ) -> AttendanceHeadline:
        """Today, this month, last month and the academic year so far -- fixed to the
        calendar, NOT to the selected range, because they are the numbers a principal
        quotes ("we are at 91% this month") and must not move when someone drags a
        date picker. One statement for all four (conditional aggregation)."""
        windows: dict[str, DateWindow] = {
            "today": (today, today),
            "this_month": _this_month(today),
            "previous_month": _previous_month(today),
        }
        year_start = await repo.year_start(today)
        if year_start is not None:
            windows["year"] = (year_start, today)
        counts = await repo.window_counts(windows)
        return AttendanceHeadline(
            today=_window_rate(counts["today"], windows["today"]),
            this_month=_window_rate(counts["this_month"], windows["this_month"]),
            previous_month=_window_rate(counts["previous_month"], windows["previous_month"]),
            year_to_date=(
                _window_rate(counts["year"], windows["year"]) if "year" in windows else None
            ),
        )

    async def _at_risk(
        self,
        repo: AttendanceAnalyticsRepository,
        from_date: date,
        to_date: date,
        threshold: float,
        min_sessions: int,
    ) -> list[AtRiskStudent]:
        rows = await repo.at_risk_students(
            from_date, to_date, threshold, min_sessions, AT_RISK_LIMIT
        )
        ids = [row.id for row in rows]
        # Two batched lookups for the whole list -- never one per child.
        streaks = await repo.absence_streaks(
            ids, to_date - timedelta(days=STREAK_LOOKBACK_DAYS - 1), to_date
        )
        rolls = await repo.current_rolls(ids)
        return [
            AtRiskStudent(
                student_id=row.id,
                admission_number=row.admission_number,
                full_name=_full_name(row.first_name, row.last_name),
                section_id=row.section_id,
                class_name=row.class_name,
                section_name=row.section_name,
                roll_number=rolls.get(row.id),
                percentage=round(float(row.credit) / int(row.counted) * 100, 2),
                counted_sessions=int(row.counted),
                absent=int(row.absent),
                absence_streak=streaks.get(row.id, 0),
            )
            for row in rows
        ]

    @staticmethod
    def _weekdays(days: Mapping[date, StatusCounts]) -> list[AttendanceWeekday]:
        """Monday to Sunday, always all seven, so a chart never has to guess which
        are missing. A weekday the school never marked has no rate (None)."""
        buckets: dict[int, list[StatusCounts]] = {weekday: [] for weekday in range(1, 8)}
        for day, counts in days.items():
            buckets[day.isoweekday()].append(counts)
        result = []
        for weekday, tallies in buckets.items():
            total = _merge(*tallies)
            result.append(
                AttendanceWeekday(
                    weekday=weekday,
                    school_days=len(tallies),
                    percentage=_percentage(total),
                    absent=total.get(AttendanceStatus.ABSENT, 0),
                )
            )
        return result

    @staticmethod
    def _class_options(visible: Sequence[tuple[Any, Any]]) -> list[AttendanceAnalyticsClass]:
        seen: dict[UUID, AttendanceAnalyticsClass] = {}
        for _, school_class in visible:
            seen.setdefault(
                school_class.id,
                AttendanceAnalyticsClass(
                    class_id=school_class.id,
                    class_name=school_class.name,
                    level=school_class.level,
                    school_id=school_class.school_id,
                ),
            )
        return list(seen.values())

    # -- every child --------------------------------------------------------

    async def students(
        self,
        params: PageParams,
        sort: SortParams,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        class_id: UUID | None = None,
        section_id: UUID | None = None,
        search: str | None = None,
        teacher_id: UUID | None = None,
        today: date | None = None,
    ) -> StudentAttendancePage:
        """One row per student: today, this month, last month and an overall range.

        "Overall" defaults to the academic year containing today, from its first day
        to today; without a calendar, to the last 365 days. A teacher's rows are the
        children seated in their sections now; a principal's, the whole campus.

        Default order is WORST FIRST (overall rate ascending): the reason to open this
        table is to find the children who need a phone call, and they should not be on
        page four. Children with no rate yet sort last in either direction.
        """
        today = today or _today()
        to_date = to_date or today
        repo = self._repo(teacher_id=teacher_id, class_id=class_id)
        from_date = from_date or await self._year_so_far(repo, to_date)
        _validated(from_date, to_date)
        await self._check_class(class_id, teacher_id)
        if section_id is not None:
            # 404 for an unknown, cross-tenant or (for a teacher) untaught section --
            # the same message an id that never existed gets.
            await self.academics.get_section(section_id)
            await self.academics.assert_teaches_section(
                section_id, teacher_id=teacher_id, message="Section not found."
            )

        sort_by = sort.sort_by or "overall"
        if sort_by not in STUDENT_SORTS:
            raise ValidationError(
                f"Cannot sort by '{sort_by}'.",
                code="INVALID_SORT_FIELD",
                details={"allowed": sorted(STUDENT_SORTS)},
            )

        windows: dict[str, DateWindow] = {
            "this_month": _this_month(today),
            "previous_month": _previous_month(today),
            "overall": (from_date, to_date),
        }
        rows, total = await repo.student_page(
            today=today,
            windows=windows,
            section_id=section_id,
            search=search,
            sort_by=sort_by,
            descending=sort.sort_dir is SortDirection.DESC,
            offset=params.offset,
            limit=params.limit,
        )

        items: list[StudentAttendanceRow] = []
        for row in rows:
            data = row._mapping
            today_line = data["today"]
            items.append(
                StudentAttendanceRow(
                    student_id=data["id"],
                    admission_number=data["admission_number"],
                    full_name=_full_name(data["first_name"], data["last_name"]),
                    roll_number=data["roll_number"],
                    section_id=data["section_id"],
                    class_id=data["class_id"],
                    class_name=data["class_name"],
                    section_name=data["section_name"],
                    today_register=(
                        RegisterState.SUBMITTED
                        if today_line is not None
                        else RegisterState.DRAFT
                        if (data["today_drafts"] or 0) > 0
                        else RegisterState.NOT_STARTED
                    ),
                    # Only a SUBMITTED line is shown. A draft is pre-filled PRESENT
                    # (spec 5.2), so echoing it would report a child as present on the
                    # strength of a register nobody has asserted.
                    today_status=(AttendanceStatus(today_line) if today_line is not None else None),
                    this_month=_rate(_window_tally(data, "this_month")),
                    previous_month=_rate(_window_tally(data, "previous_month")),
                    overall=_rate(_window_tally(data, "overall")),
                )
            )

        page_meta = _page_meta(total, params)
        return StudentAttendancePage(
            items=items,
            meta=page_meta,
            today=today,
            this_month=_bounds(windows["this_month"]),
            previous_month=_bounds(windows["previous_month"]),
            overall=_bounds(windows["overall"]),
        )

    async def student_calendar(
        self,
        student_id: UUID,
        *,
        from_date: date | None = None,
        to_date: date | None = None,
        teacher_id: UUID | None = None,
        today: date | None = None,
    ) -> StudentAttendanceCalendar:
        """One child, day by day, with a rate for the range and for each month in it.

        Defaults to the academic year so far, so ONE request feeds the drill-down's
        month calendar and every month a reader can page to, as well as the overall
        figure. Month rates are computed here, from the same lines, under the same
        rules as the per-student table -- the calendar and the row it was opened from
        cannot disagree.
        """
        today = today or _today()
        to_date = to_date or today
        repo = self._repo(teacher_id=teacher_id)
        from_date = from_date or await self._year_so_far(repo, to_date)
        _validated(from_date, to_date)

        student = await self.student_repo.get(student_id)
        if student is None:
            raise NotFoundError("Student not found.")
        # Bounded by the child's CURRENT section, exactly as the student summary is:
        # a teacher answers for the children in their classes now.
        await self.academics.assert_teaches_section(
            student.section_id, teacher_id=teacher_id, message="Student not found."
        )

        lines = await repo.student_days(student.id, from_date, to_date)
        class_name: str | None = None
        section_name: str | None = None
        if student.section_id is not None:
            labels = await self.sections.labels({student.section_id})
            class_name, section_name = labels.get(student.section_id, (None, None))
        rolls = await repo.current_rolls([student.id])

        days: list[StudentAttendanceCalendarDay] = []
        months: dict[str, StatusCounts] = {}
        overall: StatusCounts = {}
        for day, state, status in lines:
            submitted = state is AttendanceSessionStatus.SUBMITTED
            days.append(
                StudentAttendanceCalendarDay(
                    session_date=day,
                    register_state=(RegisterState.SUBMITTED if submitted else RegisterState.DRAFT),
                    status=status if submitted else None,
                )
            )
            if submitted:
                bucket = months.setdefault(f"{day:%Y-%m}", {})
                bucket[status] = bucket.get(status, 0) + 1
                overall[status] = overall.get(status, 0) + 1

        return StudentAttendanceCalendar(
            student_id=student.id,
            admission_number=student.admission_number,
            full_name=student.full_name,
            section_id=student.section_id,
            class_name=class_name,
            section_name=section_name,
            roll_number=rolls.get(student.id),
            from_date=from_date,
            to_date=to_date,
            today=today,
            overall=_rate(overall),
            months=[
                StudentAttendanceMonth(month=month, **_rate_fields(months.get(month, {})))
                for month in _months_between(from_date, to_date)
            ],
            days=days,
        )


def _window_tally(data: RowMapping, name: str) -> StatusCounts:
    """One window's per-status counters off a per-student row. Every counter is NULL
    when the LEFT JOIN found no lines for the child, which reads as zero here."""
    return {s: int(data[f"{name}_{s.value}"] or 0) for s in AttendanceStatus}


def _bounds(window: DateWindow) -> AttendanceDateRange:
    return AttendanceDateRange(from_date=window[0], to_date=window[1])


def _months_between(first: date, last: date) -> list[str]:
    """`YYYY-MM` for every calendar month the range touches, oldest first -- months
    with no register included, so a month nobody marked reads as "no data" rather
    than vanishing from the drill-down's month picker."""
    labels: list[str] = []
    year, month = first.year, first.month
    while (year, month) <= (last.year, last.month):
        labels.append(f"{year:04d}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return labels


def _page_meta(total: int, params: PageParams) -> PageMeta:
    """`Page.create`'s arithmetic, for a page envelope that carries extra fields."""
    pages = ceil(total / params.size) if total else 0
    return PageMeta(
        page=params.page,
        size=params.size,
        total=total,
        pages=pages,
        has_next=params.page < pages,
        has_prev=params.page > 1,
    )
