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
from app.core.context import require_school_id
from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.modules.academics.service import AcademicsService
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
            await self._assert_seat_available()

        student = await self.repo.create(
            **payload.model_dump(),
            # From the verified JWT, never the request body. A client that could
            # supply this could write a row into another tenant.
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
            await self._assert_seat_available()

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

        # Bind BEFORE the lookup, not after. `schools` is itself RLS-protected with
        # an id-based policy, so on an unauthenticated session with no tenant bound
        # the predicate is `id = NULL` and every school reads as missing -- the
        # lookup below would 404 even for a perfectly valid application.
        #
        # Binding an attacker-supplied id grants nothing: the policy then exposes
        # exactly that one school, and the existence/active check immediately after
        # is what actually authorises the write.
        await bind_tenant(self.session, payload.school_id)

        school = await self.session.get(School, payload.school_id)
        if school is None or not school.is_active:
            # Deliberately identical to the not-found case. Distinguishing "no such
            # school" from "suspended school" would leak tenant existence to an
            # unauthenticated caller.
            raise NotFoundError("School not found or not accepting applications.")

        prefix = f"{datetime.now(UTC).year}-"
        admission_number = await self.repo.next_admission_number(prefix)

        student = await self.repo.create(
            **payload.model_dump(exclude={"school_id"}),
            school_id=school.id,
            admission_number=admission_number,
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

    async def _assert_seat_available(self) -> None:
        """Enforce the tenant's plan seat limit (`schools.max_students`)."""
        school = await self.session.get(School, require_school_id())
        if school is None:  # pragma: no cover - implies a token for a deleted tenant
            raise NotFoundError("School not found.")
        enrolled = await self.repo.count_enrolled()
        if enrolled >= school.max_students:
            raise ConflictError(
                f"Your plan allows {school.max_students} enrolled students "
                f"and {enrolled} are already active. Upgrade to add more.",
                code="STUDENT_LIMIT_REACHED",
            )
