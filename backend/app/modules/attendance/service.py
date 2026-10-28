"""Attendance business rules -- opening, marking, submitting and amending registers.

WHY THIS FILE EXISTS
    Everything that decides *what is allowed* when recording who was in the room:
    that a register is opened once per section per date per period, that it is
    pre-filled from the live roster rather than typed from scratch, that a submitted
    register cannot be quietly rewritten by the person who submitted it, and that a
    percentage excludes authorised absences from its denominator.

INTERACTIONS
    * `AcademicsService` resolves and validates the section.
    * `AcademicCalendarService.resolve_for_date` supplies the academic year a
      register belongs to -- which is the year containing its DATE, not necessarily
      the current one. Back-filling last June's register must not restate this
      year's figures.
    * `EnrollmentService.roster` supplies who should be on the register.
    * `router.py` translates HTTP; nothing here imports fastapi.
    * `teaching_scope` bounds every method to the caller's assigned sections when
      the router passes a `teacher_id` (see "THE TEACHER'S BOUNDARY" below).

=============================================================================
THE TWO RULES THAT SHAPE EVERY METHOD BELOW
=============================================================================
1.  A REGISTER IS PRE-FILLED PRESENT, AND THE TEACHER MARKS THE EXCEPTIONS.
    Opening a register writes one `present` row per student on the roster. A
    teacher then flips the three or four absentees.

    The alternative -- an empty register the teacher fills in student by student --
    is both slower for the 95% case and, more importantly, produces a register that
    is ambiguous when half-finished: an unmarked student is indistinguishable from
    one nobody got to. Pre-filling makes a DRAFT register complete by construction,
    so the only question left is whether it has been ASSERTED, which is what
    `status` answers.

    The honest cost: a teacher who opens a register and abandons it leaves thirty
    `present` rows. That is why those rows do not count until the register is
    SUBMITTED, and why `discard` exists.

2.  SUBMITTED IS A ONE-WAY DOOR WITHOUT A SECOND PERMISSION.
    `attendance:mark` moves DRAFT -> SUBMITTED. Only `attendance:amend` moves it
    back or changes a line afterwards, and every such change writes before/after
    into `audit_logs` with the reason the caller gave.

    A system where the person who records absences can also erase them has no
    attendance record, only an attendance opinion -- and attendance records are
    what truancy proceedings, fee concessions and safeguarding referrals are built
    on. It is the same separation `fee:collect` and `fee:void` draw across a cash
    drawer.

3.  A REGISTER LOCKS ONCE THE DAY AFTER ITS DATE IS OVER.
    `attendance:mark` may open, mark, submit or discard a register only through
    the day after its date -- a full 24 hours after the school day it records has
    ended. After that it is LOCKED, draft or not, and only `attendance:amend` can
    change it. Without the lock, "submitted" is the only thing protecting history,
    and a register nobody submitted could be rewritten by its teacher weeks later.

=============================================================================
THE TEACHER'S BOUNDARY
=============================================================================
    Every public method takes `teacher_id` -- None for a caller holding
    `class:view_all`, otherwise the user whose assignments bound them. Lists drop
    the untaught sections in SQL; a single register, section or student outside them
    is a 404 with the SAME message an unknown id gets, so the response cannot be
    used to probe which ids exist next door. Writes are bounded too: a teacher who
    can mark 9-A must not be able to open, mark or discard 10-B's register by id.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditAction, record_audit
from app.common.schemas import Page, PageParams, SortParams
from app.core.context import get_school_id, require_organization_id, require_school_id
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.modules.academics.models import SchoolClass, Section
from app.modules.academics.service import AcademicCalendarService, AcademicsService
from app.modules.academics.teaching_scope import taught_section_ids
from app.modules.attendance.models import (
    WHOLE_DAY_PERIOD,
    AttendanceRecord,
    AttendanceSession,
    AttendanceSessionStatus,
    AttendanceStatus,
)
from app.modules.attendance.repository import (
    AttendanceRecordRepository,
    AttendanceSessionRepository,
)
from app.modules.attendance.schemas import (
    AttendanceEntryRead,
    AttendanceMarkRequest,
    AttendanceSessionDetail,
    AttendanceSessionOpen,
    AttendanceSessionRead,
    DailyOverview,
    SectionAttendanceDay,
    SectionAttendanceReport,
    SectionDayStatus,
    StudentAttendanceSummary,
)
from app.modules.students.repository import StudentRepository
from app.modules.students.service import EnrollmentService
from app.modules.whatsapp.service import WhatsAppService

logger = get_logger(__name__)

# How many days after its date a register stays open to `attendance:mark` -- rule 3
# in the module docstring. 1 = today's and yesterday's registers; the day before
# yesterday's is locked.
#
# The day after, not just the day itself: registers are routinely finished the next
# morning (a late note from home, a teacher off sick), and a lock that shut at
# midnight would send every one of those to the principal.
_MARK_WINDOW_DAYS = 1

# How far back even an `attendance:amend` holder may open a register.
#
# NOT A SECURITY BOUNDARY -- the marking window above is the one that holds teachers
# back. This exists because the overwhelmingly common cause of a register dated three
# months ago is a mistyped date, and a system that accepts it silently files a class's
# attendance into a term that has already been reported on.
_BACKDATE_LIMIT_DAYS = 30


class AttendanceService:
    """Register lifecycle and the reports read off it."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.sessions = AttendanceSessionRepository(session)
        self.records = AttendanceRecordRepository(session)
        self.academics = AcademicsService(session)
        self.calendar = AcademicCalendarService(session)
        self.enrollments = EnrollmentService(session)
        self.students = StudentRepository(session)

    # -- opening ------------------------------------------------------------

    async def open_session(
        self,
        payload: AttendanceSessionOpen,
        *,
        actor_id: UUID,
        may_amend: bool,
        teacher_id: UUID | None = None,
    ) -> AttendanceSessionDetail:
        """Open (or return) the register for one section, date and period.

        IDEMPOTENT, AND THAT IS THE FEATURE. Two teachers tapping "take attendance"
        at once, or one teacher tapping twice on a slow connection, must not produce
        two registers for one lesson. The unique constraint would turn the second
        attempt into a 409 the user cannot act on; returning the existing register
        turns it into the thing they wanted.
        """
        section = await self.academics.get_section(payload.section_id)
        await self._assert_teaches(section.id, teacher_id, "Section not found.")
        session_date = payload.session_date or datetime.now(UTC).date()
        self._assert_markable_date(session_date)
        self._assert_not_locked(session_date, may_amend=may_amend)

        existing = await self.sessions.find_register(section.id, session_date, payload.period)
        if existing is not None:
            return await self.detail(existing.id)

        year = await self.calendar.resolve_for_date(session_date)
        if payload.subject_id is not None:
            # 404 rather than 422 for a subject from another campus: confirming it
            # exists elsewhere would leak across the school boundary.
            from app.modules.academics.service import CurriculumService

            await CurriculumService(self.session).get_subject(payload.subject_id)

        register = await self.sessions.create(
            section_id=section.id,
            academic_year_id=year.id,
            session_date=session_date,
            period=payload.period,
            subject_id=payload.subject_id,
            status=AttendanceSessionStatus.DRAFT,
            taken_by_user_id=actor_id,
            notes=payload.notes,
            # Inherited from the section rather than re-read from context, so a
            # register can never end up scoped differently from the class it covers.
            organization_id=section.organization_id,
            school_id=section.school_id,
        )

        roster = await self.enrollments.roster(section.id)
        if not roster:
            raise ValidationError(
                f"Section '{section.name}' has no enrolled students to mark.",
                code="EMPTY_ROSTER",
            )

        # Pre-filled PRESENT -- see rule 1 in the module docstring.
        #
        # `add_all` + ONE flush, deliberately not `records.create` per student.
        # `BaseRepository.create` flushes AND refreshes on every call, so a 60-student
        # section would cost 120 round-trips to write rows whose values are already
        # known. Nothing here reads a generated id back, so there is nothing to refresh.
        self.session.add_all(
            [
                AttendanceRecord(
                    session_id=register.id,
                    student_id=entry.student_id,
                    status=AttendanceStatus.PRESENT,
                    marked_by_user_id=actor_id,
                    organization_id=section.organization_id,
                    school_id=section.school_id,
                )
                for entry in roster
            ]
        )
        await self.session.flush()

        await self._audit(
            AuditAction.ATTENDANCE_SESSION_OPENED,
            session_id=register.id,
            actor_id=actor_id,
            after={
                "section_id": str(section.id),
                "session_date": str(session_date),
                "period": payload.period,
                "roster_size": len(roster),
            },
        )
        logger.info(
            "attendance_session_opened",
            session_id=str(register.id),
            section_id=str(section.id),
            session_date=str(session_date),
            roster_size=len(roster),
        )
        return await self.detail(register.id)

    # -- reading ------------------------------------------------------------

    async def detail(
        self, session_id: UUID, *, teacher_id: UUID | None = None
    ) -> AttendanceSessionDetail:
        """One register with every line, in roll order.

        Roll order, not insertion order: a register is read aloud and checked
        against a printed list, and a teacher scanning for roll 17 in a list sorted
        by database insertion has to read all thirty names.
        """
        register = await self._get_or_404(session_id, teacher_id)
        records = await self.records.list_for_session(session_id)

        student_ids = [r.student_id for r in records]
        students = {s.id: s for s in await self.students.list_by_ids(student_ids)}
        # Read from the enrollment rows that covered THIS section in THIS register's
        # year -- closed ones included. Taking them from the current roster instead
        # would renumber a historical register every time it was reopened, and would
        # blank the numbers entirely once the cohort had been promoted out.
        rolls = await self.enrollments.repo.roll_numbers(
            register.section_id, register.academic_year_id, student_ids
        )

        entries = [
            AttendanceEntryRead(
                id=record.id,
                student_id=record.student_id,
                admission_number=student.admission_number,
                full_name=student.full_name,
                roll_number=rolls.get(record.student_id),
                status=record.status,
                minutes_late=record.minutes_late,
                remarks=record.remarks,
            )
            for record in records
            if (student := students.get(record.student_id)) is not None
        ]
        entries.sort(key=self._roll_sort_key)

        tally = self._tally(records)
        return AttendanceSessionDetail(
            **self._session_fields(register, tally),
            entries=entries,
        )

    async def list_sessions(
        self,
        params: PageParams,
        sort: SortParams,
        *,
        section_id: UUID | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        session_status: AttendanceSessionStatus | None = None,
        teacher_id: UUID | None = None,
    ) -> Page[AttendanceSessionRead]:
        conditions: list[ColumnElement[bool]] = []
        if teacher_id is not None:
            conditions.append(AttendanceSession.section_id.in_(taught_section_ids(teacher_id)))
        if section_id is not None:
            conditions.append(AttendanceSession.section_id == section_id)
        if from_date is not None:
            conditions.append(AttendanceSession.session_date >= from_date)
        if to_date is not None:
            conditions.append(AttendanceSession.session_date <= to_date)
        if session_status is not None:
            conditions.append(AttendanceSession.status == session_status)

        rows, total = await self.sessions.list(*conditions, params=params, sort=sort)
        tallies = await self.sessions.tallies([r.id for r in rows])
        items = [
            AttendanceSessionRead(**self._session_fields(r, tallies.get(r.id, {}))) for r in rows
        ]
        return Page.create(items, total, params)

    async def daily_overview(
        self, session_date: date | None = None, *, teacher_id: UUID | None = None
    ) -> DailyOverview:
        """Every section on the campus and whether its register has been taken.

        THE QUESTION THE SESSION TABLE EXISTS TO ANSWER. In a flat attendance table,
        "nobody marked Grade 10-B" and "Grade 10-B was fully present" are both an
        absence of rows. Here the first is `session_id is None`, and it is what a
        head teacher's 09:15 chase list is built from.

        Whole-day registers only (`period = 0` is preferred when both exist): a
        secondary school marking eight periods would otherwise render eight rows per
        section on a screen whose entire job is to be scanned in ten seconds.
        """
        day = session_date or datetime.now(UTC).date()

        sections = await self._all_sections(teacher_id)
        # Registers of sections not on the screen are dropped before tallying -- for a
        # teacher that is most of the campus, and counting it would be wasted work.
        shown = {section.id for section, _ in sections}
        registers = [r for r in await self.sessions.list_for_date(day) if r.section_id in shown]
        tallies = await self.sessions.tallies([r.id for r in registers])

        by_section: dict[UUID, AttendanceSession] = {}
        for register in registers:
            current = by_section.get(register.section_id)
            if current is None or (
                register.period == WHOLE_DAY_PERIOD and current.period != WHOLE_DAY_PERIOD
            ):
                by_section[register.section_id] = register

        # One lookup for every class teacher on the screen, reusing the academics
        # repository so "how a teacher id becomes a name" has a single implementation.
        # Per-row would be an N+1 on a view that renders the entire campus.
        teacher_names = await self.academics.sections.teacher_names(
            {s.class_teacher_id for s, _ in sections if s.class_teacher_id is not None}
        )

        rows: list[SectionDayStatus] = []
        for section, school_class in sections:
            taken = by_section.get(section.id)
            tally = tallies.get(taken.id, {}) if taken else {}
            rows.append(
                SectionDayStatus(
                    section_id=section.id,
                    section_name=section.name,
                    class_id=school_class.id,
                    class_name=school_class.name,
                    class_teacher_id=section.class_teacher_id,
                    class_teacher_name=(
                        teacher_names.get(section.class_teacher_id)
                        if section.class_teacher_id is not None
                        else None
                    ),
                    session_id=taken.id if taken else None,
                    status=taken.status if taken else None,
                    present_count=self._present_from(tally),
                    absent_count=tally.get(AttendanceStatus.ABSENT.value, 0),
                    total_count=sum(tally.values()),
                )
            )

        submitted = sum(1 for r in rows if r.status is AttendanceSessionStatus.SUBMITTED)
        not_started = sum(1 for r in rows if r.session_id is None)
        return DailyOverview(
            session_date=day,
            locked=self._is_locked(day),
            sections=rows,
            sections_total=len(rows),
            sections_submitted=submitted,
            sections_not_started=not_started,
        )

    # -- marking ------------------------------------------------------------

    async def mark(
        self,
        session_id: UUID,
        payload: AttendanceMarkRequest,
        *,
        actor_id: UUID,
        may_amend: bool,
        teacher_id: UUID | None = None,
    ) -> AttendanceSessionDetail:
        """Set statuses for some of the students on a register.

        `may_amend` is passed in by the router rather than resolved here, because
        permission resolution is an HTTP-layer concern and this service must stay
        callable from a CLI or a worker. What the service owns is the RULE: a
        SUBMITTED or LOCKED register is closed to `attendance:mark`, and every change
        to a submitted one is audited individually with the reason given.
        """
        register = await self._get_or_404(session_id, teacher_id)
        is_amendment = register.status is AttendanceSessionStatus.SUBMITTED

        # Before the submitted check: past the window, reopening would not hand the
        # register back to its teacher either, so "locked" is the honest answer.
        self._assert_not_locked(register.session_date, may_amend=may_amend)
        if is_amendment and not may_amend:
            raise ConflictError(
                "This register has been submitted. Correcting it requires the "
                "'attendance:amend' permission.",
                code="ATTENDANCE_SUBMITTED",
            )
        if is_amendment and not payload.reason:
            # A reason is REQUIRED for an amendment and ignored for a draft edit.
            # An audit row saying only "a status changed" answers none of the
            # questions an amendment gets asked six months later.
            raise ValidationError(
                "Amending a submitted register requires a reason.",
                code="AMENDMENT_REASON_REQUIRED",
            )

        # DRAFT EDITS ARE NOT AUDITED, AND THAT IS DELIBERATE.
        #
        # A teacher marking a register taps a dozen times before deciding; auditing
        # each tap would write thousands of rows a day recording a decision that had
        # not been made yet, and would bury the amendments -- the only attendance
        # changes anyone ever investigates -- under them. The submission event records
        # the totals the teacher asserted, and everything after it is audited per
        # student. What is lost is the ability to reconstruct a draft's keystrokes,
        # which nothing asks for.
        existing = await self.records.by_student(session_id)
        changed = 0

        for entry in payload.entries:
            record = existing.get(entry.student_id)
            if record is None:
                # A student not on the register is not marked into it. Adding them
                # here would let a caller create an attendance row for a child in
                # another section -- the roster, not the request body, decides who
                # this register covers.
                raise ValidationError(
                    "One or more students are not on this register. Re-open it to "
                    "pick up roster changes.",
                    code="STUDENT_NOT_ON_REGISTER",
                    details={"student_id": str(entry.student_id)},
                )

            before = {
                "status": record.status.value,
                "minutes_late": record.minutes_late,
                "remarks": record.remarks,
            }
            after = {
                "status": entry.status.value,
                # `minutes_late` is meaningful only alongside LATE. Clearing it when
                # the status moves away keeps "absent, 15 minutes late" -- a
                # contradiction the UI would happily render -- unrepresentable.
                "minutes_late": (
                    entry.minutes_late if entry.status is AttendanceStatus.LATE else None
                ),
                "remarks": entry.remarks,
            }
            if before == after:
                continue

            await self.records.update(
                record,
                status=entry.status,
                minutes_late=after["minutes_late"],
                remarks=entry.remarks,
                marked_by_user_id=actor_id,
            )
            changed += 1

            if is_amendment:
                # ONE AUDIT ROW PER AMENDED STUDENT, not one for the batch. "Who
                # changed Ali's 12 March absence to present, and why" is the question
                # an amendment trail is read with, and a single row saying "8 records
                # amended" cannot answer it.
                await self._audit(
                    AuditAction.ATTENDANCE_AMENDED,
                    session_id=session_id,
                    actor_id=actor_id,
                    entity_type="attendance_record",
                    entity_id=record.id,
                    before=before,
                    after={**after, "reason": payload.reason, "student_id": str(record.student_id)},
                )

        logger.info(
            "attendance_marked",
            session_id=str(session_id),
            changed=changed,
            amendment=is_amendment,
        )
        return await self.detail(session_id)

    async def submit(
        self,
        session_id: UUID,
        *,
        actor_id: UUID,
        may_amend: bool,
        teacher_id: UUID | None = None,
    ) -> AttendanceSessionDetail:
        """Assert that the register is complete and correct.

        From here it feeds reports and absence alerts, and further changes need
        `attendance:amend`. A draft left past the marking window is submitted by an
        amender, not by the teacher who abandoned it.
        """
        register = await self._get_or_404(session_id, teacher_id)
        if register.status is AttendanceSessionStatus.SUBMITTED:
            raise ConflictError("This register has already been submitted.")
        self._assert_not_locked(register.session_date, may_amend=may_amend)

        records = await self.records.list_for_session(session_id)
        tally = self._tally(records)
        await self.sessions.update(
            register,
            status=AttendanceSessionStatus.SUBMITTED,
            submitted_at=datetime.now(UTC),
            taken_by_user_id=register.taken_by_user_id or actor_id,
        )
        # Absence alerts: a WHOLE-DAY register, for TODAY. A lesson register would
        # text a parent once per period, and a register back-filled days later would
        # tell them "today" about a day that is long gone. Queued in this transaction,
        # so a submit that fails queues nothing; the campus switch decides whether any.
        today = datetime.now(UTC).date()
        if register.period == WHOLE_DAY_PERIOD and register.session_date == today:
            await WhatsAppService(self.session).queue_absence_alerts(
                school_id=register.school_id,
                session_date=register.session_date,
                absent_student_ids=[
                    r.student_id for r in records if r.status is AttendanceStatus.ABSENT
                ],
            )
        await self._audit(
            AuditAction.ATTENDANCE_SESSION_SUBMITTED,
            session_id=session_id,
            actor_id=actor_id,
            after={
                "session_date": str(register.session_date),
                "section_id": str(register.section_id),
                **tally,
            },
        )
        logger.info("attendance_session_submitted", session_id=str(session_id))
        return await self.detail(session_id)

    async def reopen(
        self, session_id: UUID, *, reason: str, actor_id: UUID, teacher_id: UUID | None = None
    ) -> AttendanceSessionDetail:
        """Move a submitted register back to DRAFT. Requires `attendance:amend`."""
        register = await self._get_or_404(session_id, teacher_id)
        if register.status is not AttendanceSessionStatus.SUBMITTED:
            raise ConflictError("Only a submitted register can be reopened.")

        await self.sessions.update(
            register, status=AttendanceSessionStatus.DRAFT, submitted_at=None
        )
        await self._audit(
            AuditAction.ATTENDANCE_SESSION_REOPENED,
            session_id=session_id,
            actor_id=actor_id,
            before={"status": AttendanceSessionStatus.SUBMITTED.value},
            after={"status": AttendanceSessionStatus.DRAFT.value, "reason": reason},
        )
        logger.info("attendance_session_reopened", session_id=str(session_id))
        return await self.detail(session_id)

    async def discard(
        self,
        session_id: UUID,
        *,
        actor_id: UUID,
        may_amend: bool,
        teacher_id: UUID | None = None,
    ) -> None:
        """Delete a DRAFT register and its pre-filled lines.

        A hard delete, and only ever of a draft. A draft was never asserted, so it is
        not history -- keeping thirty abandoned `present` rows would make the table
        grow with mistakes. A SUBMITTED register is refused: correcting one is an
        amendment, which leaves a trail.
        """
        register = await self._get_or_404(session_id, teacher_id)
        if register.status is not AttendanceSessionStatus.DRAFT:
            raise ConflictError(
                "A submitted register cannot be discarded. Reopen and amend it instead."
            )
        self._assert_not_locked(register.session_date, may_amend=may_amend)

        await self.records.delete_for_session(session_id)
        await self.session.delete(register)
        await self.session.flush()
        await self._audit(
            AuditAction.ATTENDANCE_SESSION_DISCARDED,
            session_id=session_id,
            actor_id=actor_id,
            before={
                "section_id": str(register.section_id),
                "session_date": str(register.session_date),
            },
        )

    # -- reports ------------------------------------------------------------

    async def student_summary(
        self,
        student_id: UUID,
        from_date: date,
        to_date: date,
        *,
        teacher_id: UUID | None = None,
    ) -> StudentAttendanceSummary:
        """One student's attendance rate over a range.

        See `AttendanceStatus` for why EXCUSED leaves the denominator and HALF_DAY
        contributes 0.5. Those two rules are stated once, on the enum, so that this
        report and the section report below cannot drift apart.
        """
        if to_date < from_date:
            raise ValidationError(
                "`to_date` must not be before `from_date`.", code="INVALID_DATE_RANGE"
            )

        student = await self.students.get(student_id)
        if student is None:
            raise NotFoundError("Student not found.")
        # Bounded by the student's CURRENT section: a teacher answers for the children
        # in their classes now, not for every child who once passed through them.
        await self._assert_teaches(student.section_id, teacher_id, "Student not found.")

        tally = await self.records.student_tally(student_id, from_date, to_date)
        total = sum(tally.values())
        counted = sum(c for s, c in tally.items() if s.counts_toward_attendance)
        credit = sum(s.credit * c for s, c in tally.items() if s.counts_toward_attendance)

        return StudentAttendanceSummary(
            student_id=student.id,
            admission_number=student.admission_number,
            full_name=student.full_name,
            from_date=from_date,
            to_date=to_date,
            total_sessions=total,
            counted_sessions=counted,
            present=tally.get(AttendanceStatus.PRESENT, 0),
            absent=tally.get(AttendanceStatus.ABSENT, 0),
            late=tally.get(AttendanceStatus.LATE, 0),
            excused=tally.get(AttendanceStatus.EXCUSED, 0),
            half_day=tally.get(AttendanceStatus.HALF_DAY, 0),
            # None, not 0.0, when nothing counts. A student nobody has marked yet has
            # no attendance rate, and 0% would put a disciplinary-looking figure
            # against them.
            percentage=round(credit / counted * 100, 2) if counted else None,
        )

    async def section_report(
        self,
        section_id: UUID,
        from_date: date,
        to_date: date,
        *,
        teacher_id: UUID | None = None,
    ) -> SectionAttendanceReport:
        if to_date < from_date:
            raise ValidationError(
                "`to_date` must not be before `from_date`.", code="INVALID_DATE_RANGE"
            )
        await self.academics.get_section(section_id)
        await self._assert_teaches(section_id, teacher_id, "Section not found.")

        daily = await self.records.section_daily_tally(section_id, from_date, to_date)

        days: list[SectionAttendanceDay] = []
        credit_total = 0.0
        counted_total = 0
        for day in sorted(daily):
            tally = daily[day]
            counted = sum(c for s, c in tally.items() if s.counts_toward_attendance)
            credit_total += sum(
                s.credit * c for s, c in tally.items() if s.counts_toward_attendance
            )
            counted_total += counted
            days.append(
                SectionAttendanceDay(
                    session_date=day,
                    present=tally.get(AttendanceStatus.PRESENT, 0),
                    absent=tally.get(AttendanceStatus.ABSENT, 0),
                    late=tally.get(AttendanceStatus.LATE, 0),
                    excused=tally.get(AttendanceStatus.EXCUSED, 0),
                    half_day=tally.get(AttendanceStatus.HALF_DAY, 0),
                    total=sum(tally.values()),
                )
            )

        return SectionAttendanceReport(
            section_id=section_id,
            from_date=from_date,
            to_date=to_date,
            days=days,
            average_percentage=(
                round(credit_total / counted_total * 100, 2) if counted_total else None
            ),
        )

    # -- internals ----------------------------------------------------------

    async def _get_or_404(
        self, session_id: UUID, teacher_id: UUID | None = None
    ) -> AttendanceSession:
        """A cross-tenant or cross-campus id is filtered out and lands here as None,
        so it becomes a 404 -- never a 403, which would confirm the register exists.

        A register of a section the teacher does not teach is filtered in the same
        query, so it is indistinguishable from one that does not exist.
        """
        conditions: list[ColumnElement[bool]] = [AttendanceSession.id == session_id]
        if teacher_id is not None:
            conditions.append(AttendanceSession.section_id.in_(taught_section_ids(teacher_id)))
        register = await self.sessions.find_one(*conditions)
        if register is None:
            raise NotFoundError("Attendance register not found.")
        return register

    async def _assert_teaches(
        self, section_id: UUID | None, teacher_id: UUID | None, message: str
    ) -> None:
        """404 with the caller's own not-found `message` unless the section is taught.

        The message matches the unknown-id case on purpose: a different wording for
        "exists but not yours" would confirm the id is real. A student with no
        section is outside every teacher's classes.
        """
        if teacher_id is None:
            return
        if section_id is None or section_id not in await self.academics.taught_sections(teacher_id):
            raise NotFoundError(message)

    @staticmethod
    def _assert_markable_date(session_date: date) -> None:
        """Reject a register dated in the future or absurdly far in the past.

        A future date is always an error: nobody can record who was present at a
        lesson that has not happened. A very old date is usually a mistyped year, and
        accepting it silently files a class's attendance into a term that has already
        been reported on. `attendance:amend` holders route around this through
        `reopen`, so the window bounds mistakes rather than authority.
        """
        today = datetime.now(UTC).date()
        if session_date > today:
            raise ValidationError(
                "Attendance cannot be recorded for a future date.", code="FUTURE_DATE"
            )
        if (today - session_date).days > _BACKDATE_LIMIT_DAYS:
            raise ValidationError(
                f"Attendance can only be opened for the last {_BACKDATE_LIMIT_DAYS} days. "
                "Check the date.",
                code="DATE_TOO_OLD",
            )

    @staticmethod
    def _is_locked(session_date: date) -> bool:
        """Whether `session_date` is past the marking window -- rule 3.

        Same clock as `_assert_markable_date` and the daily overview, so the date a
        register can be opened for and the date it locks on cannot disagree.
        """
        return (datetime.now(UTC).date() - session_date).days > _MARK_WINDOW_DAYS

    @classmethod
    def _assert_not_locked(cls, session_date: date, *, may_amend: bool) -> None:
        """409 for an `attendance:mark`-only caller writing to a locked date."""
        if may_amend or not cls._is_locked(session_date):
            return
        raise ConflictError(
            f"Attendance for {session_date:%d %b %Y} is locked. Registers can be changed "
            "until the end of the following day; correcting it now requires the "
            "'attendance:amend' permission.",
            code="ATTENDANCE_LOCKED",
        )

    async def _all_sections(
        self, teacher_id: UUID | None = None
    ) -> list[tuple[Section, SchoolClass]]:
        """Every section on the campus (or that the teacher teaches) with its class,
        ordered for display.

        ONE join, not a section query followed by a class lookup per row. The daily
        overview renders the whole school.
        """
        stmt = (
            select(Section, SchoolClass)
            .join(SchoolClass, SchoolClass.id == Section.class_id)
            .where(Section.deleted_at.is_(None), SchoolClass.deleted_at.is_(None))
            .order_by(SchoolClass.level, Section.name)
        )
        # `get_school_id`, not `require_school_id`: an org-level principal viewing
        # the whole organization has no active campus, and the overview should then
        # span every section RLS lets them see rather than raising.
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(Section.school_id == school_id)
        if teacher_id is not None:
            stmt = stmt.where(Section.id.in_(taught_section_ids(teacher_id)))
        rows = (await self.session.execute(stmt)).all()
        return [(section, school_class) for section, school_class in rows]

    @staticmethod
    def _tally(records: Sequence[AttendanceRecord]) -> dict[str, int]:
        """Status counts for one already-loaded register.

        In Python rather than SQL because the caller has the rows in hand: a GROUP BY
        here would be a second round-trip for data already in memory. The batched
        path (`AttendanceSessionRepository.tallies`) is the SQL one, for the case
        where the rows are NOT loaded.
        """
        tally: dict[str, int] = {}
        for record in records:
            tally[record.status.value] = tally.get(record.status.value, 0) + 1
        return tally

    @staticmethod
    def _present_from(tally: dict[str, int]) -> int:
        """Present, late and half-day all mean the student was in the building."""
        return sum(tally.get(status.value, 0) for status in AttendanceStatus if status.is_present)

    @staticmethod
    def _roll_sort_key(entry: AttendanceEntryRead) -> tuple[int, int, str]:
        """Numeric rolls in numeric order, then lettered rolls, then unnumbered.

        A plain string sort puts roll 10 before roll 2, which is wrong on every
        printed register -- the same reason `SchoolClass.level` exists.
        """
        roll = entry.roll_number
        if roll is None:
            return (2, 0, entry.full_name)
        if roll.isdigit():
            return (0, int(roll), entry.full_name)
        return (1, 0, roll)

    def _session_fields(self, register: AttendanceSession, tally: dict[str, int]) -> dict[str, Any]:
        return {
            "id": register.id,
            "section_id": register.section_id,
            "academic_year_id": register.academic_year_id,
            "session_date": register.session_date,
            "period": register.period,
            "subject_id": register.subject_id,
            "status": register.status,
            "taken_by_user_id": register.taken_by_user_id,
            "submitted_at": register.submitted_at,
            "notes": register.notes,
            "locked": self._is_locked(register.session_date),
            "present_count": self._present_from(tally),
            "absent_count": tally.get(AttendanceStatus.ABSENT.value, 0),
            "total_count": sum(tally.values()),
            "created_at": register.created_at,
            "updated_at": register.updated_at,
        }

    async def _audit(
        self,
        action: str,
        *,
        session_id: UUID,
        actor_id: UUID,
        entity_type: str = "attendance_session",
        entity_id: UUID | None = None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        """Append the audit row inside the caller's transaction.

        Same transaction as the change it describes, per `common/audit.py`: either
        both the mutation and its record land, or neither does.
        """
        await record_audit(
            self.session,
            organization_id=require_organization_id(),
            school_id=require_school_id(),
            actor_user_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id or session_id,
            before=before,
            after=after,
        )
