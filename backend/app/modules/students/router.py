"""Student HTTP endpoints -- the SIS directory and public admissions.

AUTHORISATION SHAPE
    Every route names the permission it needs, resolved through `require()` against
    the shared catalog: `student:read` for the directory, `student:create`,
    `student:update` and `student:delete` for the writes.

    This replaced `require_roles("school_admin")`. A role-name check cannot express
    the custom roles customers create -- a school defining "Registrar" and expecting
    them to enrol students would have to be handed the full admin role instead,
    which is how least-privilege quietly stops being practised.

    Admissions is unauthenticated and therefore the most carefully constrained
    endpoint in the module. See the service for why it cannot be used to probe for
    schools, to self-enroll, or to exhaust a school's plan seats.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    ClientIp,
    DbSession,
    Pagination,
    PublicDbSession,
    SearchQuery,
    SettingsDep,
    Sorting,
    require,
)
from app.common.schemas import Page
from app.core.rate_limit import enforce_rate_limit
from app.modules.students.models import StudentStatus
from app.modules.students.schemas import (
    AdmissionResponse,
    StudentAdmissionRequest,
    StudentCreate,
    StudentRead,
    StudentUpdate,
)
from app.modules.students.service import StudentService

router = APIRouter()


@router.post(
    "/admissions",
    response_model=AdmissionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit a public admissions application",
)
async def submit_admission(
    payload: StudentAdmissionRequest,
    db: PublicDbSession,
    settings: SettingsDep,
    ip: ClientIp,
) -> AdmissionResponse:
    """Public endpoint backing the Next.js admissions form.

    `PublicDbSession`, not `DbSession`: there is no caller identity. Declared before
    `/{student_id}` so "admissions" is never parsed as a student id.
    """
    await enforce_rate_limit(
        "public_admission",
        ip or "unknown",
        limit=settings.PUBLIC_MUTATION_RATE_LIMIT,
        window_seconds=settings.PUBLIC_MUTATION_RATE_WINDOW_SECONDS,
    )
    return await StudentService(db).admit(payload)


@router.get(
    "",
    response_model=Page[StudentRead],
    summary="List and search students",
    dependencies=[Depends(require("student:read"))],
)
async def list_students(
    db: DbSession,
    params: Pagination,
    sort: Sorting,
    search: SearchQuery = None,
    section_id: UUID | None = Query(default=None, description="Filter by section."),
    student_status: StudentStatus | None = Query(
        default=None,
        alias="status",
        description="Filter by enrollment status, e.g. `pending` for the admissions queue.",
    ),
) -> Page[StudentRead]:
    return await StudentService(db).list(
        params, sort, search=search, section_id=section_id, status=student_status
    )


@router.post(
    "",
    response_model=StudentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Enroll a student",
    dependencies=[Depends(require("student:create"))],
)
async def create_student(payload: StudentCreate, db: DbSession) -> StudentRead:
    return await StudentService(db).create(payload)


@router.get(
    "/{student_id}",
    response_model=StudentRead,
    summary="Get a student",
    dependencies=[Depends(require("student:read"))],
)
async def get_student(student_id: UUID, db: DbSession) -> StudentRead:
    return await StudentService(db).get(student_id)


@router.patch(
    "/{student_id}",
    response_model=StudentRead,
    summary="Update a student",
    dependencies=[Depends(require("student:update"))],
)
async def update_student(student_id: UUID, payload: StudentUpdate, db: DbSession) -> StudentRead:
    return await StudentService(db).update(student_id, payload)


@router.delete(
    "/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a student from the directory",
    dependencies=[Depends(require("student:delete"))],
)
async def delete_student(student_id: UUID, db: DbSession) -> None:
    """Soft delete -- fee, attendance and certificate history is preserved."""
    await StudentService(db).delete(student_id)
