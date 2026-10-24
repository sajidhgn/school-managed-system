"""Attendance data access. SQL only -- no business rules.

Organization isolation comes from PostgreSQL RLS. Campus isolation is separate: the
shared repository injects the active school for ordinary CRUD, and every custom
aggregate below applies the same scope explicitly, because a grouped query built
from `select(func.count())` does not go through `_base_select`.

WHY SO MANY AGGREGATES LIVE HERE
    Attendance is the one module in this system whose row count grows without bound
    -- roughly 228,000 rows a year for a 1,200-student school. Every report below is
    written as ONE grouped query rather than as a loop in the service, because the
    loop version degrades exactly as a school accumulates history, which is the
    point at which nobody is looking at it any more.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any, cast
from uuid import UUID

from sqlalchemy import ColumnElement, Row, Select, Subquery, and_, case, func, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repository import BaseRepository
from app.core.context import get_school_id
from app.modules.academics.models import AcademicYear, SchoolClass, Section
from app.modules.academics.teaching_scope import taught_section_ids
from app.modules.attendance.models import (
    WHOLE_DAY_PERIOD,
    AttendanceRecord,
    AttendanceSession,
    AttendanceSessionStatus,
    AttendanceStatus,
)
from app.modules.students.models import Student, StudentEnrollment, StudentStatus


class AttendanceSessionRepository(BaseRepository[AttendanceSession]):
    model = AttendanceSession
    sortable_fields = frozenset({"session_date", "period", "status", "created_at"})

    async def find_register(
        self, section_id: UUID, session_date: date, period: int
    ) -> AttendanceSession | None:
        """The existing register for this exact slot, if one was already opened.

        Read before every open so that a double tap returns the register rather than
        colliding with `uq_attendance_sessions_section_id_session_date_period`.
        """
        return await self.find_one(
            AttendanceSession.section_id == section_id,
            AttendanceSession.session_date == session_date,
            AttendanceSession.period == period,
        )

    async def list_for_date(self, session_date: date) -> Sequence[AttendanceSession]:
        """Every register taken across the campus on one date."""
        stmt = (
            self._base_select()
            .where(AttendanceSession.session_date == session_date)
            .order_by(AttendanceSession.period, AttendanceSession.created_at)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def list_in_range(
        self, section_id: UUID, from_date: date, to_date: date
    ) -> Sequence[AttendanceSession]:
        stmt = (
            self._base_select()
            .where(
                AttendanceSession.section_id == section_id,
                AttendanceSession.session_date >= from_date,
                AttendanceSession.session_date <= to_date,
            )
            .order_by(AttendanceSession.session_date, AttendanceSession.period)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def tallies(self, session_ids: Sequence[UUID]) -> dict[UUID, dict[str, int]]:
        """Present/absent/total per register, for a batch of registers.

        ONE grouped query for the whole page of registers. Counting per register is
        the N+1 that makes a month-at-a-glance screen unusable by the end of a term.
        """
        if not session_ids:
            return {}
        stmt = (
            select(
                AttendanceRecord.session_id,
                AttendanceRecord.status,
                func.count(AttendanceRecord.id),
            )
            .where(AttendanceRecord.session_id.in_(session_ids))
            .group_by(AttendanceRecord.session_id, AttendanceRecord.status)
        )
        stmt = self._scope(stmt, AttendanceRecord)

        tallies: dict[UUID, dict[str, int]] = {}
        for session_id, status, count in (await self.session.execute(stmt)).all():
            bucket = tallies.setdefault(session_id, {})
            bucket[str(status.value if hasattr(status, "value") else status)] = int(count)
        return tallies

    @staticmethod
    def _scope[T: tuple[Any, ...]](stmt: Select[T], model: type[AttendanceRecord]) -> Select[T]:
        """Apply the campus filter to a hand-built aggregate.

        `_base_select` does this for ordinary CRUD, but a `select(func.count())` never
        passes through it. Skipping this on one aggregate would let a school-scoped
        member read another campus's numbers -- RLS would not object, because both
        campuses are inside the same organization.
        """
        if (school_id := get_school_id()) is not None:
            return stmt.where(model.school_id == school_id)
        return stmt


class AttendanceRecordRepository(BaseRepository[AttendanceRecord]):
    model = AttendanceRecord
    sortable_fields = frozenset({"status", "created_at"})

    async def list_for_session(self, session_id: UUID) -> Sequence[AttendanceRecord]:
        stmt = self._base_select().where(AttendanceRecord.session_id == session_id)
        return (await self.session.execute(stmt)).scalars().all()

    async def by_student(self, session_id: UUID) -> dict[UUID, AttendanceRecord]:
        """The register's lines keyed by student, for an O(1) lookup while marking."""
        return {r.student_id: r for r in await self.list_for_session(session_id)}

    async def student_tally(
        self, student_id: UUID, from_date: date, to_date: date
    ) -> dict[AttendanceStatus, int]:
        """How many of each status one student has, over a date range.

        Counts only SUBMITTED registers. A draft is a teacher's work in progress --
        half-marked, possibly abandoned -- and letting it into a percentage means the
        number a parent is shown changes during the school day for reasons nobody can
        explain.
        """
        stmt = (
            select(AttendanceRecord.status, func.count(AttendanceRecord.id))
            .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
            .where(
                AttendanceRecord.student_id == student_id,
                AttendanceSession.status == AttendanceSessionStatus.SUBMITTED,
                AttendanceSession.session_date >= from_date,
                AttendanceSession.session_date <= to_date,
            )
            .group_by(AttendanceRecord.status)
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(AttendanceRecord.school_id == school_id)
        rows = (await self.session.execute(stmt)).all()
        return {AttendanceStatus(status): int(count) for status, count in rows}

    async def section_daily_tally(
        self, section_id: UUID, from_date: date, to_date: date
    ) -> dict[date, dict[AttendanceStatus, int]]:
        """Per-day status counts for one section.

        ONE query over the whole range. The obvious alternative -- a query per day --
        issues 180 round-trips for a term report, and each of them is cheap enough
        that the problem is invisible in development and obvious in production.
        """
        stmt = (
            select(
                AttendanceSession.session_date,
                AttendanceRecord.status,
                func.count(AttendanceRecord.id),
            )
            .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
            .where(
                AttendanceSession.section_id == section_id,
                AttendanceSession.status == AttendanceSessionStatus.SUBMITTED,
                AttendanceSession.session_date >= from_date,
                AttendanceSession.session_date <= to_date,
            )
            .group_by(AttendanceSession.session_date, AttendanceRecord.status)
            .order_by(AttendanceSession.session_date)
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(AttendanceRecord.school_id == school_id)

        daily: dict[date, dict[AttendanceStatus, int]] = {}
        for day, status, count in (await self.session.execute(stmt)).all():
            daily.setdefault(day, {})[AttendanceStatus(status)] = int(count)
        return daily

    async def delete_for_session(self, session_id: UUID) -> None:
        """Remove every line of a register. Only ever called on a DRAFT.

        A hard delete, not a soft one: `attendance_records` has no `deleted_at` by
        design, and a discarded draft is not history -- it is a register that was
        never asserted. Discarding a SUBMITTED register is refused by the service.
        """
        for record in await self.list_for_session(session_id):
            await self.session.delete(record)
        await self.session.flush()


# ---------------------------------------------------------------------------
# Analytics
# ---------------------------------------------------------------------------
#
# The attendance percentage in SQL, DERIVED from `AttendanceStatus` rather than
# restated: the enum's `credit` and `counts_toward_attendance` are the single
# statement of the rules (spec section 4.2), and generating the expressions from them
# means the at-risk HAVING clause and the per-student sort below cannot disagree with
# the Python that computes every other rate in this module. Hand-writing "late = 1.0,
# half_day = 0.5" here would be a second copy waiting to drift.
COUNTED_STATUSES = tuple(s for s in AttendanceStatus if s.counts_toward_attendance)
_CREDIT_CASE = case(
    *[(AttendanceRecord.status == s, s.credit) for s in COUNTED_STATUSES if s.credit > 0],
    else_=0.0,
)
_CREDIT = func.sum(_CREDIT_CASE)
_COUNTED = func.count().filter(AttendanceRecord.status.in_(COUNTED_STATUSES))
_ABSENT = func.count().filter(AttendanceRecord.status == AttendanceStatus.ABSENT)
_SUBMITTED = AttendanceSession.status == AttendanceSessionStatus.SUBMITTED

StatusCounts = dict[AttendanceStatus, int]
DateWindow = tuple[date, date]
"""An inclusive `(first, last)` date range."""

STUDENT_SORTS = frozenset(
    {"overall", "this_month", "previous_month", "name", "admission_number", "roll_number", "class"}
)
"""The per-student table's sort allowlist -- the same allowlist rule as
`BaseRepository.sortable_fields`: a client string never reaches ORDER BY unless it is
named here."""

_STUDENT_WINDOWS = ("this_month", "previous_month", "overall")


def _rate_of(columns: dict[AttendanceStatus, Any]) -> ColumnElement[Any]:
    """`credit / counted` over already-aggregated per-status count columns, NULL when
    nothing counts -- the SQL twin of `analytics._percentage`, built from the enum."""
    credit = sum((columns[s] * s.credit for s in COUNTED_STATUSES), start=literal(0.0))
    counted = sum((columns[s] for s in COUNTED_STATUSES), start=literal(0))
    return cast(ColumnElement[Any], credit / func.nullif(counted, 0))


class AttendanceAnalyticsRepository:
    """Grouped reads behind the attendance analytics endpoints.

    Not a `BaseRepository`: it owns no table and creates nothing. Every method is a
    fixed number of grouped statements whose result size is bounded by sections,
    dates, a page size or an explicit LIMIT -- never by how many register lines the
    range holds, which for a 1,200-student school over a year is ~228,000.

    THE SCOPE EVERY QUERY SHARES
        `_registers()` is the one definition of "the registers a report reads":

          * SUBMITTED only (unless a method asks for drafts) -- a draft is a
            teacher's work in progress and reaches no report (spec 5.2);
          * `period = 0` only -- the whole-day register is the unit of a school day.
            A lesson register answers "was the child in chemistry", a different
            question, and folding eight of them into one day would weight that day
            eight times. The daily overview makes the same choice;
          * the active campus, applied by hand because none of these selects passes
            through `_base_select` (see `AttendanceSessionRepository._scope`);
          * the teacher's assigned sections and the class filter -- on the
            SECTION-centred reads only.

    SECTION-CENTRED VERSUS STUDENT-CENTRED
        A section's rate is about the registers taken FOR that section, so those
        reads bound registers by section. A student's rate is about the child, so
        those reads bound the STUDENT (by current section, exactly as
        `AttendanceService.student_summary` bounds a teacher) and then count every
        register the child is on. Otherwise a child who moved from 9-B to 9-A last
        month would show 9-A's teacher a rate missing half the month, and a
        different number from the one on the child's own page.

    `teacher_id` and `class_id` are fixed per instance because they are fixed per
    request; only the dates vary between the calls one report makes.
    """

    def __init__(
        self,
        session: AsyncSession,
        *,
        teacher_id: UUID | None = None,
        class_id: UUID | None = None,
    ) -> None:
        self.session = session
        self.teacher_id = teacher_id
        self.class_id = class_id

    # -- scope --------------------------------------------------------------

    def _bound(
        self, column: Any, *, with_class: bool = True, with_teacher: bool = True
    ) -> list[ColumnElement[bool]]:
        """Teacher and class bounds on any `section_id` column."""
        conditions: list[ColumnElement[bool]] = []
        if with_teacher and self.teacher_id is not None:
            conditions.append(column.in_(taught_section_ids(self.teacher_id)))
        if with_class and self.class_id is not None:
            conditions.append(
                column.in_(
                    select(Section.id).where(
                        Section.class_id == self.class_id, Section.deleted_at.is_(None)
                    )
                )
            )
        return conditions

    def _registers(
        self,
        start: date,
        end: date,
        *,
        submitted_only: bool = True,
        with_class: bool = True,
        with_teacher: bool = True,
    ) -> list[ColumnElement[bool]]:
        conditions: list[ColumnElement[bool]] = [
            AttendanceSession.period == WHOLE_DAY_PERIOD,
            AttendanceSession.session_date >= start,
            AttendanceSession.session_date <= end,
            *self._bound(
                AttendanceSession.section_id, with_class=with_class, with_teacher=with_teacher
            ),
        ]
        if submitted_only:
            conditions.append(_SUBMITTED)
        if (school_id := get_school_id()) is not None:
            conditions.append(AttendanceSession.school_id == school_id)
        return conditions

    def _current_students(self) -> list[ColumnElement[bool]]:
        """Students someone could act on today: active, not deleted, on the campus,
        and -- for a bound teacher or a class filter -- seated NOW in a section the
        report covers. A teacher answers for the children in their classes now, and
        every student row links to a page that would otherwise be a 404 for them."""
        conditions: list[ColumnElement[bool]] = [
            Student.deleted_at.is_(None),
            Student.status == StudentStatus.ACTIVE,
            *self._bound(Student.section_id),
        ]
        if (school_id := get_school_id()) is not None:
            conditions.append(Student.school_id == school_id)
        return conditions

    def _student_registers(self, start: date, end: date) -> list[ColumnElement[bool]]:
        """Registers counted for a STUDENT: campus and dates only -- see "SECTION-
        CENTRED VERSUS STUDENT-CENTRED" in the class docstring."""
        return self._registers(start, end, with_class=False, with_teacher=False)

    # -- sections -----------------------------------------------------------

    async def sections(self) -> list[tuple[Section, SchoolClass]]:
        """Every live section the caller may see, with its class, in school order.

        The same rule as `AttendanceService._all_sections` (campus, then teacher),
        and deliberately WITHOUT the class filter: the caller needs the full list to
        offer as filter options, and narrowing a list already in memory is free.
        `get_school_id`, not `require_school_id`: an organization-level principal
        with no campus open reads every section RLS lets them see.
        """
        stmt = (
            select(Section, SchoolClass)
            .join(SchoolClass, SchoolClass.id == Section.class_id)
            .where(
                Section.deleted_at.is_(None),
                SchoolClass.deleted_at.is_(None),
                *self._bound(Section.id, with_class=False),
            )
            .order_by(SchoolClass.level, SchoolClass.name, Section.name)
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(Section.school_id == school_id)
        rows = (await self.session.execute(stmt)).all()
        return [(section, school_class) for section, school_class in rows]

    async def year_start(self, day: date) -> date | None:
        """First day of the academic year containing `day`, or None without one.

        Not `AcademicYearRepository.find_containing`: that expects one row, and an
        organization-level principal with no campus open sees every campus's year.
        The latest-starting one wins -- campuses of one group share a calendar in
        practice, the same assumption the dashboard's fee card makes.
        """
        stmt = (
            select(AcademicYear.start_date)
            .where(
                AcademicYear.start_date <= day,
                AcademicYear.end_date >= day,
                AcademicYear.deleted_at.is_(None),
            )
            .order_by(AcademicYear.start_date.desc())
            .limit(1)
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(AcademicYear.school_id == school_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # -- section-centred tallies --------------------------------------------

    async def daily_counts(self, start: date, end: date) -> dict[date, StatusCounts]:
        """Status counts per school day. Feeds the summary, both periods, the daily
        trend and the weekday pattern -- one statement, at most 732 dates x 5
        statuses back, whatever the school's size."""
        stmt = (
            select(AttendanceSession.session_date, AttendanceRecord.status, func.count())
            .select_from(AttendanceRecord)
            .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
            .where(*self._registers(start, end))
            .group_by(AttendanceSession.session_date, AttendanceRecord.status)
        )
        daily: dict[date, StatusCounts] = {}
        for day, status, count in (await self.session.execute(stmt)).all():
            daily.setdefault(day, {})[AttendanceStatus(status)] = int(count)
        return daily

    async def window_counts(self, windows: dict[str, DateWindow]) -> dict[str, StatusCounts]:
        """Status counts for several named date windows in ONE statement.

        Conditional aggregation -- one `count(*) FILTER (WHERE date in window)` per
        window -- over the union of the windows, so "today", "this month", "last
        month" and "this year" cost one scan rather than four. At most five rows
        come back (one per status).
        """
        lo = min(first for first, _ in windows.values())
        hi = max(last for _, last in windows.values())
        columns = [
            func.count()
            .filter(AttendanceSession.session_date >= first, AttendanceSession.session_date <= last)
            .label(name)
            for name, (first, last) in windows.items()
        ]
        stmt = (
            select(AttendanceRecord.status, *columns)
            .select_from(AttendanceRecord)
            .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
            .where(*self._registers(lo, hi))
            .group_by(AttendanceRecord.status)
        )
        counts: dict[str, StatusCounts] = {name: {} for name in windows}
        for row in (await self.session.execute(stmt)).all():
            status = AttendanceStatus(row[0])
            for index, name in enumerate(windows, start=1):
                counts[name][status] = int(row[index])
        return counts

    async def section_counts(
        self, previous_from: date, from_date: date, to_date: date
    ) -> dict[tuple[UUID, bool], StatusCounts]:
        """Status counts per section, split into (current range, previous range).

        ONE scan over both ranges, bucketed by a CASE on the date, rather than the
        same query twice: the ranges are adjacent, so it is one contiguous index
        read either way, and this halves the round trips. Keyed `(section_id,
        is_current)`.
        """
        current = case((AttendanceSession.session_date >= from_date, True), else_=False)
        stmt = (
            select(AttendanceSession.section_id, current, AttendanceRecord.status, func.count())
            .select_from(AttendanceRecord)
            .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
            .where(*self._registers(previous_from, to_date))
            .group_by(AttendanceSession.section_id, current, AttendanceRecord.status)
        )
        counts: dict[tuple[UUID, bool], StatusCounts] = {}
        for section_id, is_current, status, count in (await self.session.execute(stmt)).all():
            key = (section_id, bool(is_current))
            counts.setdefault(key, {})[AttendanceStatus(status)] = int(count)
        return counts

    async def register_counts(
        self, start: date, end: date
    ) -> dict[UUID, dict[AttendanceSessionStatus, int]]:
        """Whole-day registers per section and state -- submitted AND draft.

        Counts registers, not lines, so it reads `attendance_sessions` alone. Drafts
        are included on purpose: a register opened and never submitted is the one
        state a coverage figure would otherwise hide.
        """
        stmt = (
            select(AttendanceSession.section_id, AttendanceSession.status, func.count())
            .where(*self._registers(start, end, submitted_only=False))
            .group_by(AttendanceSession.section_id, AttendanceSession.status)
        )
        counts: dict[UUID, dict[AttendanceSessionStatus, int]] = {}
        for section_id, status, count in (await self.session.execute(stmt)).all():
            counts.setdefault(section_id, {})[AttendanceSessionStatus(status)] = int(count)
        return counts

    async def school_days(self, start: date, end: date) -> int:
        """Distinct dates with at least one SUBMITTED whole-day register.

        The "was the school open" proxy -- see `AttendanceAnalyticsSummary.school_days`.
        WITHOUT the class filter: whether the school was open does not depend on
        which class the reader is looking at, and a class that missed a day the rest
        of the campus marked is exactly what coverage is for. WITH the teacher bound:
        a teacher's denominator is built from their own sections, so the figure
        cannot be used to learn what happened in classes they do not teach.
        """
        stmt = select(func.count(func.distinct(AttendanceSession.session_date))).where(
            *self._registers(start, end, with_class=False)
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    async def registers_on(self, day: date) -> Sequence[tuple[UUID, int, AttendanceSessionStatus]]:
        """(section, period, state) for every register opened on one date, any period.

        Any period, unlike the tallies: "has this section's register been taken
        today" must give the same answer as the daily overview, which falls back to a
        lesson register when no whole-day one exists.
        """
        stmt = select(
            AttendanceSession.section_id, AttendanceSession.period, AttendanceSession.status
        ).where(
            AttendanceSession.session_date == day,
            *self._bound(AttendanceSession.section_id),
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(AttendanceSession.school_id == school_id)
        rows = (await self.session.execute(stmt)).all()
        return [(s, int(p), AttendanceSessionStatus(st)) for s, p, st in rows]

    # -- at-risk students (student-centred) ---------------------------------

    def _below_threshold(
        self, start: date, end: date, threshold: float, min_sessions: int
    ) -> Subquery:
        """Per-student credit and denominator over the range, for students under
        `threshold` percent with at least `min_sessions` counted registers.

        THE MINIMUM IS WHAT MAKES THE LIST WORTH READING. Without it, one absence on
        the first school day of a range is 0% and tops the list above a child who has
        missed a fortnight. `counted * threshold > credit * 100` rather than a
        division, so the comparison is exact and never divides by zero.
        """
        return (
            select(
                AttendanceRecord.student_id.label("student_id"),
                _CREDIT.label("credit"),
                _COUNTED.label("counted"),
                _ABSENT.label("absent"),
            )
            .select_from(AttendanceRecord)
            .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
            .where(
                AttendanceRecord.student_id.in_(
                    select(Student.id).where(*self._current_students())
                ),
                *self._student_registers(start, end),
            )
            .group_by(AttendanceRecord.student_id)
            .having(min_sessions <= _COUNTED, _COUNTED * threshold > _CREDIT * 100)
            .subquery("below_threshold")
        )

    async def at_risk_by_section(
        self, start: date, end: date, threshold: float, min_sessions: int
    ) -> dict[UUID | None, int]:
        """How many at-risk students each section has -- ALL of them, not the capped
        list, so a section's count and the summary total are true."""
        below = self._below_threshold(start, end, threshold, min_sessions)
        stmt = (
            select(Student.section_id, func.count())
            .select_from(below)
            .join(Student, Student.id == below.c.student_id)
            .group_by(Student.section_id)
        )
        return {section_id: int(n) for section_id, n in (await self.session.execute(stmt)).all()}

    async def at_risk_students(
        self, start: date, end: date, threshold: float, min_sessions: int, limit: int
    ) -> Sequence[Row[Any]]:
        """The worst `limit` students under the threshold, with their placement.

        Ordered by rate, then by absences (two children at 40% are not equal if one
        was marked twice as often), then by name for a stable list. Outer joins to
        section and class because a student can be active and unplaced.
        """
        below = self._below_threshold(start, end, threshold, min_sessions)
        rate = below.c.credit / below.c.counted
        stmt = (
            select(
                Student.id,
                Student.admission_number,
                Student.first_name,
                Student.last_name,
                Student.section_id,
                SchoolClass.name.label("class_name"),
                Section.name.label("section_name"),
                below.c.credit,
                below.c.counted,
                below.c.absent,
            )
            .select_from(below)
            .join(Student, Student.id == below.c.student_id)
            .outerjoin(Section, Section.id == Student.section_id)
            .outerjoin(SchoolClass, SchoolClass.id == Section.class_id)
            .order_by(rate.asc(), below.c.absent.desc(), Student.first_name, Student.last_name)
            .limit(limit)
        )
        return (await self.session.execute(stmt)).all()

    async def absence_streaks(
        self, student_ids: Sequence[UUID], since: date, until: date
    ) -> dict[UUID, int]:
        """Consecutive most-recent submitted whole-day registers marked ABSENT.

        Gaps-and-islands in one statement: number each student's registers newest
        first, and the streak is the position of the first non-ABSENT line minus one
        -- or every line, when there is no such line. Bounded below by `since` so a
        student's whole history is never sorted to answer a question about the last
        few weeks.
        """
        if not student_ids:
            return {}
        ordered = (
            select(
                AttendanceRecord.student_id.label("student_id"),
                AttendanceRecord.status.label("status"),
                func.row_number()
                .over(
                    partition_by=AttendanceRecord.student_id,
                    order_by=AttendanceSession.session_date.desc(),
                )
                .label("position"),
            )
            .select_from(AttendanceRecord)
            .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
            .where(
                AttendanceRecord.student_id.in_(student_ids),
                *self._student_registers(since, until),
            )
            .subquery("ordered")
        )
        first_break = func.min(ordered.c.position).filter(
            ordered.c.status != AttendanceStatus.ABSENT
        )
        stmt = select(
            ordered.c.student_id,
            func.coalesce(first_break, func.max(ordered.c.position) + 1) - 1,
        ).group_by(ordered.c.student_id)
        return {sid: int(n) for sid, n in (await self.session.execute(stmt)).all()}

    async def current_rolls(self, student_ids: Sequence[UUID]) -> dict[UUID, str]:
        """Each student's roll number on their OPEN placement -- the one a teacher
        calls today. `uq_student_enrollments_one_open` makes it unique."""
        if not student_ids:
            return {}
        stmt = select(StudentEnrollment.student_id, StudentEnrollment.roll_number).where(
            StudentEnrollment.student_id.in_(student_ids),
            StudentEnrollment.left_on.is_(None),
            StudentEnrollment.roll_number.is_not(None),
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(StudentEnrollment.school_id == school_id)
        rows = (await self.session.execute(stmt)).tuples().all()
        return {sid: roll for sid, roll in rows if roll is not None}

    # -- the per-student table (student-centred) ----------------------------

    def _student_filters(
        self, section_id: UUID | None, search: str | None
    ) -> list[ColumnElement[bool]]:
        conditions = self._current_students()
        if section_id is not None:
            conditions.append(Student.section_id == section_id)
        if search:
            # Parameterised, never interpolated -- the term is raw client input. A roll
            # number matches exactly ("7" must not also find 17, 27 and 70); names and
            # admission numbers match anywhere, as on the students list.
            pattern = f"%{search}%"
            conditions.append(
                or_(
                    Student.first_name.ilike(pattern),
                    Student.last_name.ilike(pattern),
                    (Student.first_name + " " + Student.last_name).ilike(pattern),
                    Student.admission_number.ilike(pattern),
                    StudentEnrollment.roll_number == search,
                )
            )
        return conditions

    @staticmethod
    def _open_enrollment() -> ColumnElement[bool]:
        return and_(
            StudentEnrollment.student_id == Student.id,
            StudentEnrollment.left_on.is_(None),
        )

    async def student_page(
        self,
        *,
        today: date,
        windows: dict[str, DateWindow],
        section_id: UUID | None,
        search: str | None,
        sort_by: str,
        descending: bool,
        offset: int,
        limit: int,
    ) -> tuple[Sequence[Row[Any]], int]:
        """One page of students with today's line and per-window status counts.

        TWO STATEMENTS, WHATEVER THE PAGE OR SCHOOL SIZE: the page and its total.

        The page is the student list LEFT JOINed to one grouped subquery over their
        register lines, which carries a `count(*) FILTER (...)` per (window, status)
        -- fifteen counters -- plus today's line. Conditional aggregation rather than
        a query per window or per student: the windows overlap (this month sits
        inside the year), so one scan of the union answers all of them. The
        subquery is restricted to the filtered students up front, so a teacher's
        thirty children never cost a scan of the whole campus.

        LEFT JOIN, because a child nobody has marked yet is still on the table --
        with nulls, not zeros, and sorted after everyone who has a rate.

        `windows` must name `this_month`, `previous_month` and `overall`.
        """
        lo = min(min(first for first, _ in windows.values()), today)
        hi = max(max(last for _, last in windows.values()), today)
        students = select(Student.id).where(*self._current_students())
        if section_id is not None:
            students = students.where(Student.section_id == section_id)

        is_today = AttendanceSession.session_date == today
        counters = [
            func.count()
            .filter(
                _SUBMITTED,
                AttendanceSession.session_date >= windows[name][0],
                AttendanceSession.session_date <= windows[name][1],
                AttendanceRecord.status == status,
            )
            .label(f"{name}_{status.value}")
            for name in _STUDENT_WINDOWS
            for status in AttendanceStatus
        ]
        lines = (
            select(
                AttendanceRecord.student_id.label("student_id"),
                # One whole-day register per section per date, so a student has one
                # line today unless they changed section mid-morning; then any
                # SUBMITTED one is as true as the other.
                func.max(AttendanceRecord.status).filter(is_today, _SUBMITTED).label("today"),
                func.count()
                .filter(is_today, AttendanceSession.status == AttendanceSessionStatus.DRAFT)
                .label("today_drafts"),
                *counters,
            )
            .select_from(AttendanceRecord)
            .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
            .where(
                AttendanceRecord.student_id.in_(students),
                *self._registers(
                    lo, hi, submitted_only=False, with_class=False, with_teacher=False
                ),
            )
            .group_by(AttendanceRecord.student_id)
            .subquery("lines")
        )

        roll = StudentEnrollment.roll_number
        rates = {
            name: _rate_of({s: lines.c[f"{name}_{s.value}"] for s in AttendanceStatus})
            for name in _STUDENT_WINDOWS
        }
        sort_keys: dict[str, list[Any]] = {
            **{name: [rate] for name, rate in rates.items()},
            "name": [Student.first_name, Student.last_name],
            "admission_number": [Student.admission_number],
            # Length first, so numeric rolls sort 2 before 10 without a cast that
            # would fail on a lettered roll -- the same problem `SchoolClass.level`
            # solves for class names.
            "roll_number": [func.length(roll), roll],
            "class": [SchoolClass.level, SchoolClass.name, Section.name, func.length(roll), roll],
        }
        order = [
            (key.desc() if descending else key.asc()).nulls_last() for key in sort_keys[sort_by]
        ]

        filters = self._student_filters(section_id, search)
        stmt = (
            select(
                Student.id,
                Student.admission_number,
                Student.first_name,
                Student.last_name,
                Student.section_id,
                SchoolClass.id.label("class_id"),
                SchoolClass.name.label("class_name"),
                Section.name.label("section_name"),
                roll.label("roll_number"),
                lines,
            )
            .select_from(Student)
            .outerjoin(Section, Section.id == Student.section_id)
            .outerjoin(SchoolClass, SchoolClass.id == Section.class_id)
            .outerjoin(StudentEnrollment, self._open_enrollment())
            .outerjoin(lines, lines.c.student_id == Student.id)
            .where(*filters)
            .order_by(*order, Student.first_name, Student.last_name, Student.id)
            .offset(offset)
            .limit(limit)
        )
        rows = (await self.session.execute(stmt)).all()

        total_stmt = (
            select(func.count())
            .select_from(Student)
            .outerjoin(StudentEnrollment, self._open_enrollment())
            .where(*filters)
        )
        total = int((await self.session.execute(total_stmt)).scalar_one() or 0)
        return rows, total

    async def student_days(
        self, student_id: UUID, start: date, end: date
    ) -> Sequence[tuple[date, AttendanceSessionStatus, AttendanceStatus]]:
        """Every whole-day register line for one student over a range, drafts too,
        oldest first -- the day-by-day calendar. The caller hides a draft's status."""
        stmt = (
            select(
                AttendanceSession.session_date, AttendanceSession.status, AttendanceRecord.status
            )
            .select_from(AttendanceRecord)
            .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
            .where(
                AttendanceRecord.student_id == student_id,
                *self._registers(
                    start, end, submitted_only=False, with_class=False, with_teacher=False
                ),
            )
            .order_by(AttendanceSession.session_date)
        )
        rows = (await self.session.execute(stmt)).all()
        return [
            (day, AttendanceSessionStatus(state), AttendanceStatus(status))
            for day, state, status in rows
        ]
