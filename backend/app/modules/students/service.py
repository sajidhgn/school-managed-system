"""Student business rules -- the SIS directory and admissions intake.

WHY THIS FILE EXISTS
    What is allowed when enrolling a student: admission numbers unique within the
    tenant, the school's plan seat limit respected, section capacity respected, and
    a public applicant never able to admit themselves.

INTERACTIONS
    * `AcademicsService.assert_section_capacity` gates every seat assignment.
    * `TenancyService`/`School.max_students` caps total enrollment per plan.
    * `router.py` translates HTTP; nothing here imports fastapi.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditAction, record_audit
from app.common.schemas import Page, PageParams, SortParams
from app.core.context import require_organization_id, require_school_id
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.modules.academics.service import AcademicCalendarService, AcademicsService
from app.modules.billing.entitlements import EntitlementService
from app.modules.fees.repository import FeeVoucherRepository
from app.modules.students.models import Student, StudentEnrollment, StudentStatus
from app.modules.students.repository import StudentEnrollmentRepository, StudentRepository
from app.modules.students.schemas import (
    AdmissionResponse,
    EnrollmentBackfillResult,
    EnrollmentPlacement,
    EnrollmentRead,
    FeeStandingFilter,
    PromotionRequest,
    PromotionResult,
    PromotionSkip,
    SectionRosterEntry,
    StudentAdmissionRequest,
    StudentCreate,
    StudentDues,
    StudentListRow,
    StudentRead,
    StudentUpdate,
)
from app.modules.tenancy.models import School

logger = get_logger(__name__)


class StudentService:
    """Student directory CRUD and admissions."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = StudentRepository(session)
        self.academics = AcademicsService(session)
        self.enrollments = EnrollmentService(session)

    # -- staff-facing CRUD --------------------------------------------------

    async def create(self, payload: StudentCreate) -> StudentRead:
        if await self.repo.admission_number_taken(payload.admission_number):
            raise ConflictError(f"Admission number '{payload.admission_number}' is already in use.")

        if payload.section_id is not None:
            await self.academics.assert_section_capacity(payload.section_id)

        if payload.status is StudentStatus.ACTIVE:
            await self._reserve_seat()

        student = await self.repo.create(
            **payload.model_dump(),
            # Both from the verified JWT, never the request body. A client that could
            # supply `organization_id` could write a row into another tenant.
            organization_id=require_organization_id(),
            school_id=require_school_id(),
        )
        # Open the history row alongside the record. Opportunistic: a school that has
        # not set up its academic calendar yet still gets a student, just no ledger
        # entry until `backfill` runs. See `EnrollmentService`.
        if student.status is StudentStatus.ACTIVE:
            await self.enrollments.sync_placement(
                student, section_id=student.section_id, effective=student.enrolled_on
            )

        logger.info(
            "student_created",
            student_id=str(student.id),
            admission_number=student.admission_number,
        )
        return await self._read(student)

    async def _read(
        self, student: Student, labels: dict[UUID, tuple[str, str]] | None = None
    ) -> StudentRead:
        """One `Student` row as a `StudentRead`, with its class and section named.

        `labels` is passed in by `list`, which resolves every section on the page in a
        single query. Omitting it (the single-record paths) resolves just this one.
        The parameter exists so the list path cannot accidentally become an N+1 -- the
        expensive shape is the one that has to be spelled out.
        """
        if labels is None:
            labels = await self.academics.sections.labels(
                {student.section_id} if student.section_id is not None else set()
            )
        pair = labels.get(student.section_id) if student.section_id is not None else None

        # Read the ORM-backed fields off the row, then add the two derived ones. Done
        # this way rather than with a default of `None` on the schema, which would make
        # both fields OPTIONAL in the generated OpenAPI -- and every frontend caller
        # would start null-checking a field that is always present. Same argument as
        # `AttendanceSessionDetail.entries`.
        payload: dict[str, Any] = {
            name: getattr(student, name)
            for name in StudentRead.model_fields
            if hasattr(student, name)
        }
        payload["class_name"] = pair[0] if pair else None
        payload["section_name"] = pair[1] if pair else None
        return StudentRead.model_validate(payload)

    async def get(self, student_id: UUID) -> StudentRead:
        return await self._read(await self._get_or_404(student_id))

    def _fee_standing_condition(self, standing: FeeStandingFilter) -> ColumnElement[bool]:
        """Turn "owes money" into a WHERE clause on `students`.

        A SUBQUERY, not a join and not a prefetched list of ids. A join to
        `fee_vouchers` would multiply a student by their unpaid challans and quietly
        corrupt both the page and its total; fetching the ids first would move a
        school-sized list through Python between two queries. `IN (SELECT ...)` lets
        PostgreSQL answer it in one pass, and the pagination count stays honest.

        What counts as owing belongs to the fees module and is defined there -- see
        `FeeVoucherRepository.students_owing`. This method only chooses which
        question to ask.
        """
        vouchers = FeeVoucherRepository(self.session)
        if standing is FeeStandingFilter.CLEAR:
            # NOT IN the "any balance" set, so a student who has never been billed is
            # included. See `FeeStandingFilter.CLEAR` for why that is the right answer
            # rather than an omission.
            return Student.id.notin_(vouchers.students_owing())
        due_before = datetime.now(UTC).date() if standing is FeeStandingFilter.OVERDUE else None
        return Student.id.in_(vouchers.students_owing(due_before=due_before))

    async def list(
        self,
        params: PageParams,
        sort: SortParams,
        *,
        search: str | None = None,
        section_id: UUID | None = None,
        status: StudentStatus | None = None,
        fee_standing: FeeStandingFilter | None = None,
    ) -> Page[StudentListRow]:
        conditions = []
        if search:
            conditions.append(self.repo.search_filter(search))
        if section_id is not None:
            conditions.append(Student.section_id == section_id)
        if status is not None:
            conditions.append(Student.status == status)
        if fee_standing is not None:
            conditions.append(self._fee_standing_condition(fee_standing))

        rows, total = await self.repo.list(*conditions, params=params, sort=sort)
        # Every section on the page resolved once, not once per child.
        labels = await self.academics.sections.labels(
            {r.section_id for r in rows if r.section_id is not None}
        )
        dues = await self._dues_for(rows, fee_standing)
        items = [
            StudentListRow.model_validate(
                (await self._read(r, labels)).model_dump() | {"dues": dues.get(r.id)}
            )
            for r in rows
        ]
        return Page.create(items, total, params)

    async def _dues_for(
        self, rows: Sequence[Student], standing: FeeStandingFilter | None
    ) -> dict[UUID, StudentDues]:
        """Balances for the students on THIS page, matching the filter that selected
        them.

        Returns empty when no fee filter was applied -- which is also the permission
        boundary. The `fees` parameter requires `fee:read`, so declining to compute
        amounts without it is what keeps balances off a roll that a teacher can read.

        `CLEAR` is skipped rather than queried: those students were selected precisely
        because they owe nothing, and the answer for every one of them is zero.
        """
        if standing is None or standing is FeeStandingFilter.CLEAR:
            return {}

        due_before = datetime.now(UTC).date() if standing is FeeStandingFilter.OVERDUE else None
        raw = await FeeVoucherRepository(self.session).dues_by_student(
            {r.id for r in rows}, due_before=due_before
        )
        return {
            student_id: StudentDues(
                amount=row.amount,
                currency=row.currency,
                overdue_amount=row.overdue,
                periods=row.periods,
            )
            for student_id, row in raw.items()
        }

    async def update(self, student_id: UUID, payload: StudentUpdate) -> StudentRead:
        student = await self._get_or_404(student_id)
        values = payload.model_dump(exclude_unset=True)

        # Only check capacity when the student is actually moving. Re-checking on an
        # unrelated PATCH would reject edits to a student already sitting in a full
        # section -- correct seat count, nonsensical user experience.
        new_section = values.get("section_id")
        if "section_id" in values and new_section != student.section_id and new_section is not None:
            await self.academics.assert_section_capacity(new_section)

        # Reactivating a student consumes a seat, so the plan limit applies again.
        new_status = values.get("status")
        if new_status is StudentStatus.ACTIVE and student.status is not StudentStatus.ACTIVE:
            await self._reserve_seat()
        elif (
            "status" in values
            and student.status is StudentStatus.ACTIVE
            and new_status is not StudentStatus.ACTIVE
        ):
            await EntitlementService(self.session).release(
                require_organization_id(), "max_students"
            )

        # Snapshot BEFORE the write. `repo.update` mutates and refreshes this very
        # instance, so reading `student.status` afterwards reads the NEW value and
        # every "did it change?" test below silently evaluates false.
        previous_status = student.status
        previous_section_id = student.section_id

        updated = await self.repo.update(student, **values)

        # Mirror the change into the ledger. A section move opens a new placement; a
        # status leaving ACTIVE closes the open one, because a withdrawn student
        # occupies no seat and belongs on no register.
        if "section_id" in values and values["section_id"] != previous_section_id:
            await self.enrollments.sync_placement(updated, section_id=values["section_id"])
        if (
            "status" in values
            and new_status is not StudentStatus.ACTIVE
            and previous_status is StudentStatus.ACTIVE
        ):
            await self.enrollments.close_open(student_id)

        logger.info("student_updated", student_id=str(student_id), fields=sorted(values))
        return await self._read(updated)

    async def delete(self, student_id: UUID) -> None:
        """Soft delete.

        Never a hard delete: a student's fee history, attendance record and issued
        certificates are financial and legal records that must survive the removal
        of the student from the active directory.
        """
        student = await self._get_or_404(student_id)
        if student.status is StudentStatus.ACTIVE:
            await EntitlementService(self.session).release(
                require_organization_id(), "max_students"
            )
        # Close the placement before removing the record from the directory. The
        # enrollment row survives -- it is history, and `student_enrollments` has no
        # soft delete for exactly that reason -- but it stops claiming the student is
        # currently seated, which is what every roster query keys on.
        await self.enrollments.close_open(student_id)
        await self.repo.soft_delete(student)
        logger.info("student_deleted", student_id=str(student_id))

    # -- admissions (public) ------------------------------------------------

    async def admit(self, payload: StudentAdmissionRequest) -> AdmissionResponse:
        """Accept a public admissions-form application (PDF: Digital Admissions Form).

        Runs on an UNAUTHENTICATED session, so there is no ambient tenant and RLS
        would reject the insert. The school id therefore comes from the request body
        and is bound explicitly -- but only after confirming the school exists and is
        active, so the endpoint cannot be used to probe for valid tenant ids or to
        write into a suspended school.

        The applicant lands as PENDING with a generated admission number: they are
        not enrolled, occupy no seat, and appear on no class register until a school
        admin accepts them.
        """
        from app.db.session import bind_tenant  # local: avoids an import cycle at module load

        # =====================================================================
        # A TWO-STEP BIND, BECAUSE THE CALLER KNOWS THE SCHOOL BUT NOT THE ORG
        # =====================================================================
        #   `schools` is RLS-protected on `organization_id`. An anonymous applicant
        #   has a school id from a public admissions link and no idea which
        #   organization owns it -- so the org GUC cannot be set before the lookup,
        #   and with it empty the policy matches zero rows and every school reads as
        #   missing.
        #
        #   So: arm the cross-tenant read just long enough to resolve school -> org,
        #   then bind that organization properly for the INSERT.
        #
        #   Binding an attacker-supplied school id grants nothing. The window is a
        #   single primary-key SELECT, it exposes only the row whose id was already
        #   supplied, and the `is_active` check immediately after is what actually
        #   authorises the write. Crucially the second bind is NOT platform-admin, so
        #   the INSERT is governed by the ordinary WITH CHECK policy.
        await bind_tenant(self.session, None, platform_admin=True)
        school = await self.session.get(School, payload.school_id)

        if school is None or not school.is_active:
            # Deliberately identical to the not-found case. Distinguishing "no such
            # school" from "suspended school" would leak tenant existence to an
            # unauthenticated caller.
            await bind_tenant(self.session, None)
            raise NotFoundError("School not found or not accepting applications.")

        organization_id = school.organization_id
        await bind_tenant(self.session, organization_id, school_id=school.id)

        prefix = f"{datetime.now(UTC).year}-"
        admission_number = await self.repo.next_admission_number(prefix, school_id=school.id)

        student = await self.repo.create(
            **payload.model_dump(exclude={"school_id"}),
            organization_id=organization_id,
            school_id=school.id,
            admission_number=admission_number,
            # PENDING, so a public application consumes no plan seat until staff
            # accept it. Otherwise anyone with the link could exhaust a school's
            # student allowance by submitting the form repeatedly.
            status=StudentStatus.PENDING,
        )
        logger.info(
            "admission_application_received",
            student_id=str(student.id),
            school_id=str(school.id),
        )
        return AdmissionResponse(
            id=student.id,
            admission_number=student.admission_number,
            status=student.status,
        )

    # -- internals ----------------------------------------------------------

    async def _get_or_404(self, student_id: UUID) -> Student:
        """A cross-tenant id is filtered out by RLS and lands here as None, so it
        becomes a 404 -- never a 403, which would confirm the record exists."""
        student = await self.repo.get(student_id)
        if student is None:
            raise NotFoundError("Student not found.")
        return student

    async def _reserve_seat(self) -> None:
        """Consume one student seat against the organization's plan.

        =====================================================================
        WHY THIS REPLACED A `COUNT(*) >= school.max_students` CHECK
        =====================================================================
            The old form had two problems that the entitlement service exists to fix.

            RACE. Counting and then inserting is a read-modify-write with no lock
            between the halves. Two simultaneous enrolments both count 499 against a
            500 limit, both pass, and the school ends up with 501. The limit was not
            enforced, merely usually observed. `check_and_consume` fuses the check
            into the UPDATE's WHERE clause, so the database serialises them.

            WRONG SCOPE. The limit belongs to the ORGANIZATION's plan, not to one
            campus -- a group of three schools buys 2,500 students between them, not
            2,500 each. The old `schools.max_students` column could not express that.

            It also now raises 402 with the limit and an upgrade URL, rather than a
            409, so the frontend can show an upgrade prompt instead of an error.
        """
        await EntitlementService(self.session).check_and_consume(
            require_organization_id(), "max_students"
        )


class EnrollmentService:
    """The enrollment ledger: seating, transfers, promotion and history.

    WHY THIS IS A SEPARATE CLASS FROM `StudentService`
        `StudentService` owns the student RECORD -- name, admission number, plan
        seat. This owns their PLACEMENT over time, which is a different lifecycle
        with different rules and, once bulk promotion is included, roughly as much
        code again. `StudentService` calls into it for the two moments a record
        change implies a placement change (enrolment, section move), and nothing
        here reaches back.

    =========================================================================
    THE LEDGER IS OPPORTUNISTIC, AND THAT IS DELIBERATE
    =========================================================================
        Opening an enrollment needs an academic year, and a school that has not set
        one up yet has none. The obvious design -- refuse to enrol a student until
        the calendar exists -- makes the calendar a hard prerequisite for the single
        most basic action in the product, and breaks every existing installation on
        the day this ships.

        So `sync_placement` returns None instead of raising when there is no current
        year. The student is still created, still seated, still on the register; they
        simply have no history row yet. `backfill` is the catch-up, run once against
        an explicit year, and it is why the migration deliberately populated nothing.

        The cost is that history can start late. That is strictly better than the
        alternative, which is a product that cannot enrol a student on day one.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = StudentEnrollmentRepository(session)
        self.students = StudentRepository(session)
        self.academics = AcademicsService(session)
        self.calendar = AcademicCalendarService(session)

    # -- history ------------------------------------------------------------

    async def history(self, student_id: UUID) -> list[EnrollmentRead]:
        await self._get_student(student_id)  # 404 for an unknown or cross-tenant id
        return [EnrollmentRead.model_validate(e) for e in await self.repo.history(student_id)]

    async def roster(self, section_id: UUID) -> list[SectionRosterEntry]:
        """The class register for a section, in roll order.

        READ FROM `student_enrollments`, NOT FROM `students.section_id`. Both would
        answer correctly today; only this one keeps answering correctly for a section
        whose students were promoted out of it, which is what a printed register for
        last term needs.

        Falls back to the student pointer when the section has no enrollment rows at
        all -- an installation whose ledger has not been backfilled yet still needs a
        usable register.
        """
        await self.academics.get_section(section_id)

        enrollments = await self.repo.open_in_section(section_id)
        if enrollments:
            students = {
                s.id: s
                for s in await self.students.list_by_ids([e.student_id for e in enrollments])
            }
            return [
                self._roster_entry(student, enrollment.roll_number)
                for enrollment in enrollments
                if (student := students.get(enrollment.student_id)) is not None
            ]

        rows, _ = await self.students.list(
            Student.section_id == section_id,
            Student.status == StudentStatus.ACTIVE,
            params=PageParams(page=1, size=100),
        )
        return [self._roster_entry(student, None) for student in rows]

    # -- placement ----------------------------------------------------------

    async def place(
        self, student_id: UUID, payload: EnrollmentPlacement, *, actor_id: UUID
    ) -> EnrollmentRead:
        """Seat a student in a section, closing whatever placement came before.

        The explicit, dated version of what `PATCH /students/{id}` does implicitly
        when it changes `section_id`. A registrar correcting a mid-year transfer
        needs to say WHEN it happened, and a PATCH cannot carry that.
        """
        student = await self._get_student(student_id)
        section = await self.academics.assert_section_capacity(payload.section_id)
        year = (
            await self.calendar.get_year(payload.academic_year_id)
            if payload.academic_year_id is not None
            else await self.calendar.require_current()
        )
        effective = payload.effective_date or datetime.now(UTC).date()

        open_row = await self.repo.get_open(student_id)
        if open_row is not None and open_row.section_id == section.id:
            raise ConflictError("This student is already enrolled in that section.")

        roll_number = payload.roll_number
        if roll_number is None:
            roll_number = await self.repo.next_roll_number(section.id, year.id)
        elif await self.repo.roll_number_taken(section.id, year.id, roll_number):
            raise ConflictError(f"Roll number '{roll_number}' is already used in this section.")

        enrollment = await self._transition(
            student,
            section_id=section.id,
            class_id=section.class_id,
            academic_year_id=year.id,
            effective=effective,
            roll_number=roll_number,
            notes=payload.notes,
            is_promotion=False,
        )
        await self._audit(
            AuditAction.STUDENT_TRANSFERRED if open_row else AuditAction.STUDENT_ENROLLED,
            student_id=student_id,
            actor_id=actor_id,
            before={"section_id": str(open_row.section_id)} if open_row else None,
            after={"section_id": str(section.id), "roll_number": roll_number},
        )
        return EnrollmentRead.model_validate(enrollment)

    async def sync_placement(
        self,
        student: Student,
        *,
        section_id: UUID | None,
        effective: date | None = None,
        is_promotion: bool = False,
    ) -> StudentEnrollment | None:
        """Keep the ledger in step with a change made through the student record.

        Returns None -- rather than raising -- when the school has no current
        academic year. See the class docstring: a missing calendar must not block
        enrolling a student.

        Called by `StudentService` on create and on a section change. Not exposed
        over HTTP: the dated, explicit path is `place`.
        """
        if section_id is None:
            return None
        year = await self.calendar.years.get_current()
        if year is None:
            return None

        open_row = await self.repo.get_open(student.id)
        if open_row is not None and open_row.section_id == section_id:
            return open_row

        section = await self.academics.get_section(section_id)
        return await self._transition(
            student,
            section_id=section.id,
            class_id=section.class_id,
            academic_year_id=year.id,
            effective=effective or datetime.now(UTC).date(),
            roll_number=await self.repo.next_roll_number(section.id, year.id),
            notes=None,
            is_promotion=is_promotion,
        )

    async def close_open(
        self, student_id: UUID, *, left_on: date | None = None, actor_id: UUID | None = None
    ) -> None:
        """End the student's current placement.

        Called when a student stops being enrolled -- withdrawn, graduated,
        transferred out, removed from the directory. Silently does nothing when
        there is no open row, so the callers do not each have to check.
        """
        open_row = await self.repo.get_open(student_id)
        if open_row is None:
            return
        await self.repo.update(open_row, left_on=left_on or datetime.now(UTC).date())
        if actor_id is not None:
            await self._audit(
                AuditAction.STUDENT_ENROLLMENT_CLOSED,
                student_id=student_id,
                actor_id=actor_id,
                before={"section_id": str(open_row.section_id)},
            )

    # -- bulk operations ----------------------------------------------------

    async def promote(self, payload: PromotionRequest, *, actor_id: UUID) -> PromotionResult:
        """Move a section's students up into a section of the next year.

        =====================================================================
        PARTIAL SUCCESS IS THE CONTRACT, NOT A COMPROMISE
        =====================================================================
            This runs over a whole section at the end of a year. Aborting the entire
            batch because one student is already seated in the target -- which is
            exactly the state a half-finished earlier run leaves behind -- would make
            the operation impossible to retry, and retrying is the first thing anyone
            does after a timeout.

            So each student is attempted independently and the failures come back
            named, in `skipped`. The whole run is still ONE transaction: either every
            successful move lands or none does, and a retry is safe because the
            already-promoted are skipped rather than re-promoted.

        CAPACITY IS CHECKED ONCE FOR THE BATCH, not per student. Thirty
        `assert_section_capacity` calls would each count the same section and pass
        thirty times against one free seat.
        """
        source = await self.academics.get_section(payload.from_section_id)
        target = await self.academics.get_section(payload.to_section_id)
        year = await self.calendar.get_year(payload.to_academic_year_id)

        if source.id == target.id:
            raise ValidationError(
                "The source and target sections are the same.", code="PROMOTION_NO_OP"
            )

        effective = payload.effective_date or year.start_date

        enrollments = list(await self.repo.open_in_section(source.id))
        if payload.student_ids is not None:
            wanted = set(payload.student_ids)
            enrollments = [e for e in enrollments if e.student_id in wanted]

        students = {
            s.id: s for s in await self.students.list_by_ids([e.student_id for e in enrollments])
        }

        if target.capacity is not None:
            seated = await self.academics.sections.enrolled_count(target.id)
            if seated + len(enrollments) > target.capacity:
                raise ConflictError(
                    f"Section '{target.name}' has room for {target.capacity - seated} more "
                    f"student(s); this promotion would move {len(enrollments)}."
                )

        promoted = 0
        skipped: list[PromotionSkip] = []
        next_roll = 1

        for enrollment in enrollments:
            student = students.get(enrollment.student_id)
            if student is None:
                continue
            if student.status is not StudentStatus.ACTIVE:
                skipped.append(
                    self._skip(student, f"Status is '{student.status.value}', not active.")
                )
                continue

            if payload.reset_roll_numbers:
                roll_number: str | None = str(next_roll)
                next_roll += 1
            else:
                roll_number = enrollment.roll_number
                if roll_number is not None and await self.repo.roll_number_taken(
                    target.id, year.id, roll_number
                ):
                    # Keeping last year's number collided. Dropping the number is
                    # better than failing the student out of the promotion: an
                    # unnumbered student is on the register and can be numbered by
                    # hand, while a skipped one is not enrolled at all.
                    roll_number = None

            await self._transition(
                student,
                section_id=target.id,
                class_id=target.class_id,
                academic_year_id=year.id,
                effective=effective,
                roll_number=roll_number,
                notes=None,
                is_promotion=True,
            )
            promoted += 1

        await self._audit(
            AuditAction.STUDENT_PROMOTED,
            student_id=source.id,
            actor_id=actor_id,
            entity_type="section",
            after={
                "from_section_id": str(source.id),
                "to_section_id": str(target.id),
                "academic_year_id": str(year.id),
                "promoted": promoted,
                "skipped": len(skipped),
            },
        )
        logger.info(
            "students_promoted",
            from_section_id=str(source.id),
            to_section_id=str(target.id),
            promoted=promoted,
            skipped=len(skipped),
        )
        return PromotionResult(
            promoted=promoted,
            skipped=skipped,
            from_section_id=source.id,
            to_section_id=target.id,
            to_academic_year_id=year.id,
        )

    async def backfill(self, year_id: UUID, *, actor_id: UUID) -> EnrollmentBackfillResult:
        """Open an enrollment for every seated, active student who has none.

        The catch-up for installations that had students before they had a calendar
        -- which is every installation upgrading through this release, because the
        migration deliberately populated nothing (an enrollment needs a year, and no
        school had one).

        IDEMPOTENT. A student who already has an open enrollment is counted and left
        alone, so a second run after a timeout is safe and changes nothing.
        """
        year = await self.calendar.get_year(year_id)

        rows, _ = await self.students.list(
            Student.status == StudentStatus.ACTIVE,
            params=PageParams(page=1, size=100),
        )
        # `list` is capped at one page by the shared pagination contract; the backfill
        # must see every student, so it pages explicitly rather than raising the cap
        # and loading an unbounded school into memory.
        students: list[Student] = list(rows)
        page = 2
        while True:
            more, _ = await self.students.list(
                Student.status == StudentStatus.ACTIVE,
                params=PageParams(page=page, size=100),
            )
            if not more:
                break
            students.extend(more)
            page += 1

        opened = already = unplaced = 0
        for student in students:
            if student.section_id is None:
                unplaced += 1
                continue
            if await self.repo.get_open(student.id) is not None:
                already += 1
                continue

            section = await self.academics.get_section(student.section_id)
            await self.repo.create(
                student_id=student.id,
                academic_year_id=year.id,
                class_id=section.class_id,
                section_id=section.id,
                roll_number=await self.repo.next_roll_number(section.id, year.id),
                enrolled_on=student.enrolled_on or year.start_date,
                is_promotion=False,
                organization_id=student.organization_id,
                school_id=student.school_id,
            )
            opened += 1

        logger.info(
            "enrollment_backfill_completed",
            academic_year_id=str(year_id),
            opened=opened,
            already=already,
            unplaced=unplaced,
        )
        return EnrollmentBackfillResult(
            academic_year_id=year.id,
            opened=opened,
            already_enrolled=already,
            unplaced=unplaced,
        )

    # -- internals ----------------------------------------------------------

    async def _transition(
        self,
        student: Student,
        *,
        section_id: UUID,
        class_id: UUID,
        academic_year_id: UUID,
        effective: date,
        roll_number: str | None,
        notes: str | None,
        is_promotion: bool,
    ) -> StudentEnrollment:
        """Close the open enrollment and open a new one, in one transaction.

        The boundary day belongs to the NEW placement: `left_on` and `enrolled_on`
        are both `effective`. Attendance for that day is therefore taken in the
        section the student moved to, which is where they actually sat.

        `students.section_id` is updated in the same breath. It is the head of this
        ledger (see `students/models.py`), and letting the two disagree would make
        every roster read depend on which of them the caller happened to consult.
        """
        open_row = await self.repo.get_open(student.id)
        if open_row is not None:
            await self.repo.update(open_row, left_on=effective)

        enrollment = await self.repo.create(
            student_id=student.id,
            academic_year_id=academic_year_id,
            class_id=class_id,
            section_id=section_id,
            roll_number=roll_number,
            enrolled_on=effective,
            is_promotion=is_promotion,
            notes=notes,
            organization_id=student.organization_id,
            school_id=student.school_id,
        )
        if student.section_id != section_id:
            await self.students.update(student, section_id=section_id)
        return enrollment

    async def _get_student(self, student_id: UUID) -> Student:
        student = await self.students.get(student_id)
        if student is None:
            raise NotFoundError("Student not found.")
        return student

    @staticmethod
    def _roster_entry(student: Student, roll_number: str | None) -> SectionRosterEntry:
        return SectionRosterEntry(
            student_id=student.id,
            admission_number=student.admission_number,
            full_name=student.full_name,
            roll_number=roll_number,
            status=student.status,
            photo_url=student.photo_url,
            guardian_phone=student.guardian_phone,
        )

    @staticmethod
    def _skip(student: Student, reason: str) -> PromotionSkip:
        return PromotionSkip(
            student_id=student.id,
            admission_number=student.admission_number,
            full_name=student.full_name,
            reason=reason,
        )

    async def _audit(
        self,
        action: str,
        *,
        student_id: UUID,
        actor_id: UUID,
        entity_type: str = "student",
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        await record_audit(
            self.session,
            organization_id=require_organization_id(),
            school_id=require_school_id(),
            actor_user_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=student_id,
            before=before,
            after=after,
        )
