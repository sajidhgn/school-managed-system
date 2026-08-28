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
from typing import Any
from uuid import UUID

from sqlalchemy import Select, func, select

from app.common.repository import BaseRepository
from app.core.context import get_school_id
from app.modules.attendance.models import (
    AttendanceRecord,
    AttendanceSession,
    AttendanceSessionStatus,
    AttendanceStatus,
)


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
