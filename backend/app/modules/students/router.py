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

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import (
    AuthContext,
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
from app.core.exceptions import AuthorizationError
from app.core.rate_limit import enforce_rate_limit
from app.modules.students.models import StudentStatus
from app.modules.students.schemas import (
    AdmissionResponse,
    EnrollmentPlacement,
    EnrollmentRead,
    FeeStandingFilter,
    PromotionRequest,
    PromotionResult,
    StudentAdmissionRequest,
    StudentCreate,
    StudentListRow,
    StudentRead,
    StudentUpdate,
)
from app.modules.students.service import EnrollmentService, StudentService

router = APIRouter()

# Captured as contexts rather than bare `dependencies=[...]` guards because the
# enrollment routes write audit rows and therefore need the actor's identity.
StudentReadCtx = Annotated[AuthContext, Depends(require("student:read"))]
StudentUpdateCtx = Annotated[AuthContext, Depends(require("student:update"))]
# Its own code, not `student:update`. Promotion is whole-school, once-a-year and
# looks irreversible from the UI -- exactly the shape of action that should require
# an explicit grant rather than riding along with "edit a student".
PromoteCtx = Annotated[AuthContext, Depends(require("student:promote"))]


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
    response_model=Page[StudentListRow],
    summary="List and search students",
)
async def list_students(
    db: DbSession,
    params: Pagination,
    sort: Sorting,
    ctx: StudentReadCtx,
    search: SearchQuery = None,
    section_id: UUID | None = Query(default=None, description="Filter by section."),
    student_status: StudentStatus | None = Query(
        default=None,
        alias="status",
        description="Filter by enrollment status, e.g. `pending` for the admissions queue.",
    ),
    fee_standing: FeeStandingFilter | None = Query(
        default=None,
        alias="fees",
        description=(
            "Filter by what the family owes. `pending` is any live challan still "
            "carrying a balance, `overdue` only those past their due date, and "
            "`clear` those with nothing outstanding (including students never billed)."
        ),
    ),
) -> Page[StudentListRow]:
    """The `fees` filter needs `fee:read` ON TOP of `student:read`.

    =====================================================================
    WHY A "JUST A FILTER" NEEDS ITS OWN PERMISSION
    =====================================================================
        It returns no amount, no challan and no payment -- only which students come
        back. That is precisely the problem: `?fees=overdue` is a list of the families
        behind on their payments, and the seeded `teacher` role does NOT hold
        `fee:read`. Leaving it ungated would let anyone who can see a class roll
        enumerate which children's parents are struggling, which is exactly the
        disclosure `fee:read` exists to control. That the answer is one bit per
        student makes it easier to read, not less sensitive.

    403 rather than silently ignoring the parameter. A filter that quietly does
    nothing returns the whole roll, and "everyone" and "everyone who owes money" are
    indistinguishable to the caller -- so a school would read an unfiltered list as
    having no defaulters.
    """
    if fee_standing is not None and not ctx.has("fee:read"):
        raise AuthorizationError(
            "Filtering students by fee standing requires permission to view fees.",
            code="FEE_READ_REQUIRED",
        )
    return await StudentService(db).list(
        params,
        sort,
        search=search,
        section_id=section_id,
        status=student_status,
        fee_standing=fee_standing,
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


# ---------------------------------------------------------------------------
# Enrollment history
# ---------------------------------------------------------------------------
#
# `/promote` is declared BEFORE `/{student_id}/...` for the usual reason: Starlette
# matches in declaration order, and a literal segment placed after a parameter is a
# segment that never matches.


@router.post(
    "/promote",
    response_model=PromotionResult,
    summary="Promote a section's students into the next academic year",
)
async def promote_students(
    payload: PromotionRequest, db: DbSession, ctx: PromoteCtx
) -> PromotionResult:
    """Bulk, once-a-year, and gated on its own `student:promote` permission.

    Partial success is the contract: students who cannot be moved come back named
    in `skipped` rather than aborting the batch. See `EnrollmentService.promote`.
    """
    return await EnrollmentService(db).promote(payload, actor_id=ctx.user_id)


@router.get(
    "/{student_id}/enrollments",
    response_model=list[EnrollmentRead],
    summary="Where this student has sat, newest first",
)
async def student_enrollments(
    student_id: UUID, db: DbSession, _ctx: StudentReadCtx
) -> list[EnrollmentRead]:
    return await EnrollmentService(db).history(student_id)


@router.post(
    "/{student_id}/enrollments",
    response_model=EnrollmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Seat a student in a section from a given date",
)
async def place_student(
    student_id: UUID, payload: EnrollmentPlacement, db: DbSession, ctx: StudentUpdateCtx
) -> EnrollmentRead:
    """The dated version of changing `section_id` through PATCH.

    A registrar recording a transfer that happened last Monday needs to say so; a
    PATCH has nowhere to put the date, so it assumes today.
    """
    return await EnrollmentService(db).place(student_id, payload, actor_id=ctx.user_id)
