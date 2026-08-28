"""Guardian registry endpoints -- the STAFF view of parents.

Handlers are one line of delegation each. Anything longer belongs in the service.

AUTHORISATION SHAPE
    Every route names the permission it needs, resolved through `require()` against
    the shared catalog: `guardian:read` to look, `guardian:create` to register,
    `guardian:update` to edit and to change a child link, `guardian:delete` to remove.

    `guardian:portal` is its own code and guards two routes only -- changing the login
    phone, and enabling or disabling portal access. Both hand out or take away the
    ability to sign in and read a child's records, which is a materially different act
    from correcting a spelling. A single `guardian:manage` would mean the clerk who
    fixes typos can also re-point a father's login at their own handset.

WHY THE STUDENT-SIDE ROUTE LIVES HERE AND NOT IN `students/router.py`
    `GET /guardians/students/{id}` reads guardian data and is gated on
    `guardian:read`. Mounting it in the students module would put a route secured with
    one module's permission inside another module's file, which is exactly how a route
    ends up guarded by the wrong one after a refactor.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import AuthContext, DbSession, Pagination, SearchQuery, Sorting, require
from app.common.schemas import Page
from app.modules.guardians.schemas import (
    GuardianCreate,
    GuardianDetail,
    GuardianLinkCreate,
    GuardianLinkUpdate,
    GuardianPhoneChange,
    GuardianPortalToggle,
    GuardianRead,
    GuardianUpdate,
    LinkedStudentRead,
    StudentGuardianRead,
)
from app.modules.guardians.service import GuardianService

router = APIRouter()


# ---------------------------------------------------------------------------
# Contacts for one student
# ---------------------------------------------------------------------------
#
# NOTE ON ROUTE ORDER: `/students/{student_id}` is declared BEFORE `/{guardian_id}`.
# Starlette matches in declaration order, and the reverse would make `students` parse
# as a guardian_id and fail with a 422 UUID error.


@router.get(
    "/students/{student_id}",
    response_model=list[StudentGuardianRead],
    summary="List the guardians of one student",
    dependencies=[Depends(require("guardian:read"))],
)
async def guardians_of_student(student_id: UUID, db: DbSession) -> list[StudentGuardianRead]:
    """The contact card: every linked guardian, primary contact first."""
    return await GuardianService(db).list_for_student(student_id)


# ---------------------------------------------------------------------------
# Guardians
# ---------------------------------------------------------------------------


@router.get(
    "",
    response_model=Page[GuardianRead],
    summary="List guardians",
    dependencies=[Depends(require("guardian:read"))],
)
async def list_guardians(
    db: DbSession,
    params: Pagination,
    sort: Sorting,
    search: SearchQuery = None,
    student_id: UUID | None = Query(
        default=None, description="Only guardians linked to this student."
    ),
) -> Page[GuardianRead]:
    return await GuardianService(db).list_guardians(
        params=params, sort=sort, search=search, student_id=student_id
    )


@router.post(
    "",
    response_model=GuardianRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a guardian",
)
async def register_guardian(
    payload: GuardianCreate,
    db: DbSession,
    ctx: AuthContext = Depends(require("guardian:create")),
) -> GuardianRead:
    """Create this organization's record for a parent.

    If the phone already belongs to a guardian identity -- because another school
    group registered them, or because this group did and then removed the record --
    the existing identity is reused, so one handset stays one login. That reuse is not
    reported back: confirming that a given number is known to the platform would leak
    across the tenant boundary.
    """
    return await GuardianService(db).register(payload, actor_id=ctx.user_id)


@router.get(
    "/{guardian_id}",
    response_model=GuardianDetail,
    summary="Get a guardian with their children",
    dependencies=[Depends(require("guardian:read"))],
)
async def get_guardian(guardian_id: UUID, db: DbSession) -> GuardianDetail:
    return await GuardianService(db).detail(guardian_id)


@router.patch(
    "/{guardian_id}",
    response_model=GuardianRead,
    summary="Update a guardian",
)
async def update_guardian(
    guardian_id: UUID,
    payload: GuardianUpdate,
    db: DbSession,
    ctx: AuthContext = Depends(require("guardian:update")),
) -> GuardianRead:
    return await GuardianService(db).update(guardian_id, payload, actor_id=ctx.user_id)


@router.put(
    "/{guardian_id}/phone",
    response_model=GuardianRead,
    summary="Change the phone number a guardian signs in with",
)
async def change_guardian_phone(
    guardian_id: UUID,
    payload: GuardianPhoneChange,
    db: DbSession,
    ctx: AuthContext = Depends(require("guardian:portal")),
) -> GuardianRead:
    """Re-point this record at a different handset.

    A CREDENTIAL CHANGE, not a profile edit -- see the service. PUT rather than PATCH
    because it replaces the whole identifier, and a separate permission because it
    hands portal access to whoever holds the new number.
    """
    return await GuardianService(db).change_phone(guardian_id, payload.phone, actor_id=ctx.user_id)


@router.put(
    "/{guardian_id}/portal",
    response_model=GuardianRead,
    summary="Enable or disable parent-portal access",
)
async def set_portal_access(
    guardian_id: UUID,
    payload: GuardianPortalToggle,
    db: DbSession,
    ctx: AuthContext = Depends(require("guardian:portal")),
) -> GuardianRead:
    """Close the portal for THIS organization's records only.

    The same person's login at another school group is untouched, which is why the
    flag lives on the record rather than on the identity.
    """
    return await GuardianService(db).set_portal_access(
        guardian_id, enabled=payload.enabled, actor_id=ctx.user_id
    )


@router.delete(
    "/{guardian_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a guardian with no linked children",
)
async def remove_guardian(
    guardian_id: UUID,
    db: DbSession,
    ctx: AuthContext = Depends(require("guardian:delete")),
) -> None:
    await GuardianService(db).remove(guardian_id, actor_id=ctx.user_id)


# ---------------------------------------------------------------------------
# Links (nested under their guardian)
# ---------------------------------------------------------------------------


@router.post(
    "/{guardian_id}/students",
    response_model=LinkedStudentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Link a guardian to a student",
)
async def link_student(
    guardian_id: UUID,
    payload: GuardianLinkCreate,
    db: DbSession,
    ctx: AuthContext = Depends(require("guardian:update")),
) -> LinkedStudentRead:
    return await GuardianService(db).link_student(guardian_id, payload, actor_id=ctx.user_id)


@router.patch(
    "/{guardian_id}/students/{student_id}",
    response_model=LinkedStudentRead,
    summary="Change what a guardian may do for one student",
)
async def update_link(
    guardian_id: UUID,
    student_id: UUID,
    payload: GuardianLinkUpdate,
    db: DbSession,
    ctx: AuthContext = Depends(require("guardian:update")),
) -> LinkedStudentRead:
    return await GuardianService(db).update_link(
        guardian_id, student_id, payload, actor_id=ctx.user_id
    )


@router.delete(
    "/{guardian_id}/students/{student_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unlink a guardian from a student",
)
async def unlink_student(
    guardian_id: UUID,
    student_id: UUID,
    db: DbSession,
    ctx: AuthContext = Depends(require("guardian:update")),
) -> None:
    await GuardianService(db).unlink_student(guardian_id, student_id, actor_id=ctx.user_id)
