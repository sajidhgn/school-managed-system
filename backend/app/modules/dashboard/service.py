"""Dashboard analytics -- decide which sections the caller may see, then build them.

AUTHORISATION IS PER SECTION, NOT PER ROUTE
    Same shape as global search. A `require("dashboard:read")` would be a new code
    that grants nothing on its own; a `require("fee:read")` would blank the board for
    a teacher who may see attendance but not money. So each section is gated on the
    permission its own module's list endpoint uses, and a section the caller may not
    read is returned as None -- never computed and then hidden.

    Fee totals are delegated to `FeeService.summary` rather than recomputed, so the
    collection rate on the dashboard and the one on the Fees screen cannot disagree.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dashboard.repository import DashboardRepository
from app.modules.dashboard.schemas import (
    AttendanceDay,
    AttendancePulse,
    AttendanceToday,
    ClassHeadcount,
    DashboardAnalytics,
    ExamPulse,
    FeePulse,
    GenderSlice,
    MonthCollection,
    StatusMix,
    StudentPulse,
    SubjectScore,
)
from app.modules.fees.service import FeeService

ATTENDANCE_DAYS = 35
"""Five weeks: enough for the heatmap to show a weekly rhythm, and it divides into
whole calendar rows."""

RATE_WINDOW = 30
FEE_MONTHS = 12


def _rate(credit: float, counted: int) -> float | None:
    return None if counted == 0 else round(credit / counted, 4)


def _month_starts(today: date, count: int) -> list[str]:
    """`YYYY-MM` labels for the last `count` months, oldest first, ending this month."""
    year, month = today.year, today.month
    labels: list[str] = []
    for _ in range(count):
        labels.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return labels[::-1]


class DashboardService:
    def __init__(self, session: AsyncSession, permissions: frozenset[str]) -> None:
        self.session = session
        self.permissions = permissions
        self.repo = DashboardRepository(session)

    async def analytics(self, today: date | None = None) -> DashboardAnalytics:
        today = today or date.today()
        # Sequential, not gathered: one AsyncSession is one connection and cannot run
        # two statements at once. Each section is a few grouped queries.
        return DashboardAnalytics(
            as_of=today,
            students=await self._students(today) if "student:read" in self.permissions else None,
            attendance=(
                await self._attendance(today) if "attendance:read" in self.permissions else None
            ),
            fees=await self._fees(today) if "fee:read" in self.permissions else None,
            exams=await self._exams() if "grade:read" in self.permissions else None,
        )

    async def _students(self, today: date) -> StudentPulse:
        active, pending, joined, unplaced = await self.repo.student_status_counts(
            today - timedelta(days=30)
        )
        gender = [
            GenderSlice(gender=g or "unspecified", count=n)
            for g, n in await self.repo.gender_counts()
        ]
        gender.sort(key=lambda s: s.count, reverse=True)
        return StudentPulse(
            active=active,
            pending=pending,
            joined_last_30_days=joined,
            gender=gender,
            by_class=[
                ClassHeadcount(class_name=name, level=level, count=n)
                for name, level, n in await self.repo.class_headcounts()
            ],
            unplaced=unplaced,
        )

    async def _attendance(self, today: date) -> AttendancePulse:
        # One range query covers the heatmap, both 30-day windows and today.
        span = max(ATTENDANCE_DAYS, RATE_WINDOW * 2)
        start = today - timedelta(days=span - 1)
        by_day = {d: (c, n) for d, c, n in await self.repo.daily_rates(start, today)}

        days = []
        for offset in range(ATTENDANCE_DAYS - 1, -1, -1):
            day = today - timedelta(days=offset)
            credit, counted = by_day.get(day, (0.0, 0))
            days.append(AttendanceDay(day=day, rate=_rate(credit, counted), marked=counted))

        def window(first: date, last: date) -> float | None:
            picked = [v for d, v in by_day.items() if first <= d <= last]
            return _rate(sum(c for c, _ in picked), sum(n for _, n in picked))

        recent_start = today - timedelta(days=RATE_WINDOW - 1)
        prev_end = recent_start - timedelta(days=1)
        today_credit, today_counted = by_day.get(today, (0.0, 0))

        return AttendancePulse(
            today=AttendanceToday(
                sections_total=await self.repo.sections_owed(),
                sections_submitted=await self.repo.sections_submitted(today),
                mix=StatusMix(**await self.repo.status_mix(today, today)),
                rate=_rate(today_credit, today_counted),
            ),
            days=days,
            rate_30d=window(recent_start, today),
            rate_prev_30d=window(prev_end - timedelta(days=RATE_WINDOW - 1), prev_end),
            mix_30d=StatusMix(**await self.repo.status_mix(recent_start, today)),
        )

    async def _fees(self, today: date) -> FeePulse:
        labels = _month_starts(today, FEE_MONTHS)
        first = date(int(labels[0][:4]), int(labels[0][5:]), 1)
        received = dict(await self.repo.monthly_receipts(first))
        months = [MonthCollection(month=m, collected=received.get(m, Decimal(0))) for m in labels]

        year = await self.repo.current_year_name()
        if year is None:
            zero = Decimal(0)
            return FeePulse(
                academic_year=None,
                currency="PKR",
                billed=zero,
                collected=zero,
                outstanding=zero,
                overdue=zero,
                collection_rate=None,
                months=months,
            )

        summary = await FeeService(self.session).summary(year, None)
        return FeePulse(
            academic_year=year,
            currency=summary.currency,
            billed=summary.billed,
            collected=summary.collected,
            outstanding=summary.outstanding,
            overdue=summary.overdue,
            collection_rate=(
                None if summary.billed == 0 else round(float(summary.collected / summary.billed), 4)
            ),
            months=months,
        )

    async def _exams(self) -> ExamPulse | None:
        exam = await self.repo.latest_marked_exam()
        if exam is None:
            return None
        exam_id, name, status = exam
        subjects = [
            SubjectScore(
                subject=subject,
                average_pct=round(avg, 1),
                pass_rate=None if passed is None else round(passed, 4),
                sat=sat,
            )
            for subject, avg, passed, sat in await self.repo.subject_scores(exam_id)
        ]
        subjects.sort(key=lambda s: s.average_pct, reverse=True)
        return ExamPulse(exam_name=name, exam_status=status, subjects=subjects)
