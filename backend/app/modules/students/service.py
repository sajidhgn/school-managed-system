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

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas import Page, PageParams, SortParams
from app.core.context import require_organization_id, require_school_id
from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.modules.academics.service import AcademicsService
from app.modules.billing.entitlements import EntitlementService
from app.modules.students.models import Student, StudentStatus
from app.modules.students.repository import StudentRepository
from app.modules.students.schemas import (
    AdmissionResponse,
    StudentAdmissionRequest,
    StudentCreate,
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
        logger.info(
            "student_created",
            student_id=str(student.id),
            admission_number=student.admission_number,
        )
        return StudentRead.model_validate(student)

    async def get(self, student_id: UUID) -> StudentRead:
        return StudentRead.model_validate(await self._get_or_404(student_id))

    async def list(
        self,
        params: PageParams,
        sort: SortParams,
        *,
        search: str | None = None,
        section_id: UUID | None = None,
        status: StudentStatus | None = None,
    ) -> Page[StudentRead]:
        conditions = []
        if search:
            conditions.append(self.repo.search_filter(search))
        if section_id is not None:
            conditions.append(Student.section_id == section_id)
        if status is not None:
            conditions.append(Student.status == status)

        rows, total = await self.repo.list(*conditions, params=params, sort=sort)
        return Page.create([StudentRead.model_validate(r) for r in rows], total, params)

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

        updated = await self.repo.update(student, **values)
        logger.info("student_updated", student_id=str(student_id), fields=sorted(values))
        return StudentRead.model_validate(updated)

    async def delete(self, student_id: UUID) -> None:
        """Soft delete.

        Never a hard delete: a student's fee history, attendance record and issued
        certificates are financial and legal records that must survive the removal
        of the student from the active directory.
        """
        student = await self._get_or_404(student_id)
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
