"""Parent-portal read endpoints -- what a guardian may see about their own children.

WHY THIS ROUTER IS SEPARATE FROM BOTH OTHERS
    `router.py` is staff-only and permission-gated. `auth_router.py` is
    unauthenticated. These routes are authenticated as a GUARDIAN, which is neither
    posture, and the three are kept apart so that no route can drift into the wrong
    one.

=============================================================================
AUTHORISATION HERE IS PER CHILD, NOT PER ROUTE
=============================================================================
    Every other router in this codebase answers "may this caller do X?" with a
    permission code. That model does not fit a parent: there is no useful permission
    called `student:read` for them, because the question is never "may you read
    students" -- it is "may you read THIS student".

    So the boundary is the LINK ROW. `GuardianStudent.can_view_results` decides, per
    child, whether this guardian sees academic and fee records, and every read below
    resolves the child through that filter before returning anything. The neighbour
    who is authorised only to collect the child at the gate holds `can_pickup=true`
    and `can_view_results=false`, and gets an empty list here.

    RLS still bounds everything to the organization named in the token, so a bug in
    the link filter cannot cross a school group -- only, at worst, a family inside
    one. That is why the filter is applied in the repository rather than the handler.

WHY THE PROJECTION IS NARROWER THAN THE STAFF ONE
    `GuardianChildRead` is not `StudentRead`. The staff record carries the other
    guardian's phone number, the family address and free-text staff notes. Separated
    parents are a routine case, and the portal must not become the way one of them
    reads the other's contact details. Fields are added to that schema one at a time,
    deliberately.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentGuardian, GuardianDbSession, SettingsDep
from app.modules.guardians.portal_service import GuardianPortalService
from app.modules.guardians.schemas import GuardianChildRead, GuardianProfile

router = APIRouter()


@router.get(
    "/me",
    response_model=GuardianProfile,
    summary="The signed-in guardian and the school group they are viewing",
)
async def me(ctx: CurrentGuardian, db: GuardianDbSession, settings: SettingsDep) -> GuardianProfile:
    return await GuardianPortalService(db, settings).profile(ctx)


@router.get(
    "/children",
    response_model=list[GuardianChildRead],
    summary="The children this guardian may view",
)
async def children(
    ctx: CurrentGuardian, db: GuardianDbSession, settings: SettingsDep
) -> list[GuardianChildRead]:
    """Only children linked with `can_view_results`. See the module docstring.

    Returns a list rather than a `Page`: a guardian has a handful of children, and
    pagination on a list that never exceeds single digits is machinery the portal UI
    would have to implement for no benefit.
    """
    return await GuardianPortalService(db, settings).children(ctx)


@router.get(
    "/children/{student_id}",
    response_model=GuardianChildRead,
    summary="One child",
)
async def child(
    student_id: str,
    ctx: CurrentGuardian,
    db: GuardianDbSession,
    settings: SettingsDep,
) -> GuardianChildRead:
    """404 for a child this guardian is not linked to -- never 403.

    A 403 would confirm that the id names a real student at this school, which is a
    small but real leak on a surface reachable by anyone with a handset and a code.
    """
    return await GuardianPortalService(db, settings).child(ctx, student_id)
