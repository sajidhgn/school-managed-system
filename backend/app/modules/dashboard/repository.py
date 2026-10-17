"""Dashboard SQL -- grouped aggregates only, never a row per student.

Every method here returns a handful of numbers whatever the school's size. The
dashboard is the first screen after sign-in, so it is the one read that every
member pays for on every visit; a query here that scales with headcount would make
the biggest customers' first impression the slowest one.

SCOPING
    Same rule as the fees repository's `_scope`: the campus predicate comes from the
    verified token's ContextVar and is skipped only for an organization-level
    principal with no campus open, which is how they get the group-wide picture. The
    tenant boundary itself is PostgreSQL RLS, not this filter.

    A teacher without `class:view_all` is narrowed further, to their assigned
    sections (`academics/teaching_scope.py`): students and registers by section,
    exam marks by the student's section AND the paper's (class, subject), so a maths
    teacher's board shows maths, not their pupils' English results.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy import case as sa_case
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.core.context import get_school_id
from app.modules.academics.models import AcademicYear, SchoolClass, Section, Subject
from app.modules.academics.teaching_scope import taught_section_ids
from app.modules.attendance.models import (
    AttendanceRecord,
    AttendanceSession,
    AttendanceSessionStatus,
    AttendanceStatus,
)
from app.modules.exams.models import Exam, ExamMark, ExamPaper
from app.modules.exams.repository import taught_students, visible_paper
from app.modules.fees.models import FeePayment, FeePaymentStatus
from app.modules.students.models import Student, StudentStatus


def _scope[T: tuple[Any, ...]](stmt: Select[T], column: InstrumentedAttribute[Any]) -> Select[T]:
    school_id = get_school_id()
    return stmt if school_id is None else stmt.where(column == school_id)


# The attendance percentage, stated once in SQL with the same rules as
# `AttendanceStatus.credit` and `counts_toward_attendance`: LATE is attended,
# HALF_DAY earns half, EXCUSED leaves the denominator.
_CREDIT = func.sum(
    sa_case(
        (AttendanceRecord.status.in_([AttendanceStatus.PRESENT, AttendanceStatus.LATE]), 1.0),
        (AttendanceRecord.status == AttendanceStatus.HALF_DAY, 0.5),
        else_=0.0,
    )
)
_COUNTED = func.sum(sa_case((AttendanceRecord.status == AttendanceStatus.EXCUSED, 0), else_=1))


class DashboardRepository:
    def __init__(self, session: AsyncSession, teacher_id: UUID | None = None) -> None:
        self.session = session
        self.teacher_id = teacher_id

    # Each returns no condition for an unbound caller, so `.where(*...)` is a no-op.

    def _taught_students(self) -> list[ColumnElement[bool]]:
        if self.teacher_id is None:
            return []
        return [Student.section_id.in_(taught_section_ids(self.teacher_id))]

    def _taught_registers(self) -> list[ColumnElement[bool]]:
        if self.teacher_id is None:
            return []
        return [AttendanceSession.section_id.in_(taught_section_ids(self.teacher_id))]

    def _taught_marks(self) -> list[ColumnElement[bool]]:
        """Marks of the teacher's pupils on papers of subjects they answer for.

        The exams module's own helpers, so the dashboard and the marks screen agree
        on which papers and pupils a teacher can see.
        """
        if self.teacher_id is None:
            return []
        return [
            ExamMark.student_id.in_(taught_students(self.teacher_id)),
            visible_paper(self.teacher_id),
        ]

    # -- students -----------------------------------------------------------

    async def student_status_counts(self, joined_since: date) -> tuple[int, int, int, int]:
        """(active, pending, joined since `joined_since`, active without a section)."""
        is_active = Student.status == StudentStatus.ACTIVE
        stmt = select(
            func.count().filter(is_active),
            func.count().filter(Student.status == StudentStatus.PENDING),
            func.count().filter(is_active, Student.enrolled_on >= joined_since),
            func.count().filter(is_active, Student.section_id.is_(None)),
        ).where(Student.deleted_at.is_(None), *self._taught_students())
        active, pending, joined, unplaced = (
            await self.session.execute(_scope(stmt, Student.school_id))
        ).one()
        return int(active), int(pending), int(joined), int(unplaced)

    async def gender_counts(self) -> Sequence[tuple[str | None, int]]:
        stmt = (
            select(Student.gender, func.count())
            .where(
                Student.deleted_at.is_(None),
                Student.status == StudentStatus.ACTIVE,
                *self._taught_students(),
            )
            .group_by(Student.gender)
        )
        rows = (await self.session.execute(_scope(stmt, Student.school_id))).all()
        return [(g.value if g is not None else None, int(n)) for g, n in rows]

    async def class_headcounts(self) -> Sequence[tuple[str, int, int]]:
        """(class name, level, active students). Grouped on name AND level so an
        organization-wide view merges every campus's "Grade 5" into one bar."""
        stmt = (
            select(SchoolClass.name, SchoolClass.level, func.count(Student.id))
            .join(Section, Section.id == Student.section_id)
            .join(SchoolClass, SchoolClass.id == Section.class_id)
            .where(
                Student.deleted_at.is_(None),
                Student.status == StudentStatus.ACTIVE,
                SchoolClass.deleted_at.is_(None),
                *self._taught_students(),
            )
            .group_by(SchoolClass.name, SchoolClass.level)
            .order_by(SchoolClass.level, SchoolClass.name)
        )
        rows = (await self.session.execute(_scope(stmt, Student.school_id))).all()
        return [(name, int(level), int(n)) for name, level, n in rows]

    # -- attendance ---------------------------------------------------------

    async def daily_rates(self, start: date, end: date) -> Sequence[tuple[date, float, int]]:
        """(day, credit, counted) per day with at least one submitted register."""
        stmt = (
            select(AttendanceSession.session_date, _CREDIT, _COUNTED)
            .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
            .where(
                AttendanceSession.status == AttendanceSessionStatus.SUBMITTED,
                AttendanceSession.session_date >= start,
                AttendanceSession.session_date <= end,
                *self._taught_registers(),
            )
            .group_by(AttendanceSession.session_date)
        )
        rows = (await self.session.execute(_scope(stmt, AttendanceSession.school_id))).all()
        return [(d, float(c or 0), int(n or 0)) for d, c, n in rows]

    async def status_mix(self, start: date, end: date) -> dict[str, int]:
        stmt = (
            select(AttendanceRecord.status, func.count())
            .join(AttendanceSession, AttendanceSession.id == AttendanceRecord.session_id)
            .where(
                AttendanceSession.status == AttendanceSessionStatus.SUBMITTED,
                AttendanceSession.session_date >= start,
                AttendanceSession.session_date <= end,
                *self._taught_registers(),
            )
            .group_by(AttendanceRecord.status)
        )
        rows = (await self.session.execute(_scope(stmt, AttendanceSession.school_id))).all()
        return {status.value: int(n) for status, n in rows}

    async def sections_owed(self) -> int:
        """Sections with at least one active student -- the registers due today."""
        stmt = select(func.count(func.distinct(Student.section_id))).where(
            Student.deleted_at.is_(None),
            Student.status == StudentStatus.ACTIVE,
            Student.section_id.is_not(None),
            *self._taught_students(),
        )
        return int((await self.session.execute(_scope(stmt, Student.school_id))).scalar_one())

    async def sections_submitted(self, day: date) -> int:
        stmt = select(func.count(func.distinct(AttendanceSession.section_id))).where(
            AttendanceSession.session_date == day,
            AttendanceSession.status == AttendanceSessionStatus.SUBMITTED,
            *self._taught_registers(),
        )
        scoped = _scope(stmt, AttendanceSession.school_id)
        return int((await self.session.execute(scoped)).scalar_one())

    # -- fees ---------------------------------------------------------------

    async def current_year_name(self) -> str | None:
        """The flagged current year. For an org-level view with several campuses,
        the most recently started one -- campuses in one group share a calendar in
        practice, and the label is what fees join on."""
        stmt = (
            select(AcademicYear.name)
            .where(AcademicYear.is_current.is_(True), AcademicYear.deleted_at.is_(None))
            .order_by(AcademicYear.start_date.desc())
            .limit(1)
        )
        scoped = _scope(stmt, AcademicYear.school_id)
        return (await self.session.execute(scoped)).scalar_one_or_none()

    async def monthly_receipts(self, start: date) -> Sequence[tuple[str, Decimal]]:
        month = func.to_char(FeePayment.received_on, "YYYY-MM")
        stmt = (
            select(month, func.coalesce(func.sum(FeePayment.amount), 0))
            .where(
                FeePayment.status == FeePaymentStatus.RECORDED,
                FeePayment.received_on >= start,
            )
            .group_by(month)
        )
        rows = (await self.session.execute(_scope(stmt, FeePayment.school_id))).all()
        return [(m, Decimal(total)) for m, total in rows]

    # -- exams --------------------------------------------------------------

    async def latest_marked_exam(self) -> tuple[Any, str, str] | None:
        """(id, name, status) of the most recent exam that has any marks entered.

        "Most recent" by start date, then creation, so an exam scheduled with no
        dates still sorts sensibly. An exam with no marks is skipped: a chart of
        empty bars for a test nobody has graded yet tells the reader nothing.
        """
        has_marks = (
            select(ExamMark.id)
            .join(ExamPaper, ExamPaper.id == ExamMark.paper_id)
            .where(
                ExamPaper.exam_id == Exam.id,
                ExamPaper.deleted_at.is_(None),
                ExamMark.deleted_at.is_(None),
                ExamMark.marks_obtained.is_not(None),
                # Bounded here too, so a teacher's board shows the latest exam with
                # marks THEY can see, not an empty chart for someone else's.
                *self._taught_marks(),
            )
            .exists()
        )
        stmt = (
            select(Exam.id, Exam.name, Exam.status)
            .where(Exam.deleted_at.is_(None), has_marks)
            .order_by(Exam.start_date.desc().nulls_last(), Exam.created_at.desc())
            .limit(1)
        )
        row = (await self.session.execute(_scope(stmt, Exam.school_id))).first()
        return None if row is None else (row[0], row[1], row[2].value)

    async def subject_scores(self, exam_id: Any) -> Sequence[tuple[str, float, float | None, int]]:
        """(subject, average %, pass rate or None, sittings) for one exam."""
        pct = ExamMark.marks_obtained * 100.0 / ExamPaper.max_marks
        with_pass_mark = ExamPaper.pass_marks.is_not(None)
        stmt = (
            select(
                Subject.name,
                func.avg(pct),
                func.avg(
                    sa_case((ExamMark.marks_obtained >= ExamPaper.pass_marks, 1.0), else_=0.0)
                ).filter(with_pass_mark),
                func.count(ExamMark.id),
            )
            .join(ExamPaper, ExamPaper.id == ExamMark.paper_id)
            .join(Subject, Subject.id == ExamPaper.subject_id)
            .where(
                ExamPaper.exam_id == exam_id,
                ExamPaper.deleted_at.is_(None),
                ExamMark.deleted_at.is_(None),
                ExamMark.is_absent.is_(False),
                ExamMark.marks_obtained.is_not(None),
                ExamPaper.max_marks > 0,
                *self._taught_marks(),
            )
            .group_by(Subject.name)
        )
        rows = (await self.session.execute(_scope(stmt, ExamPaper.school_id))).all()
        return [
            (name, float(avg), None if passed is None else float(passed), int(n))
            for name, avg, passed, n in rows
        ]
