"""Organization and school routes (spec §8 "Organization", "Schools")."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import AuthContext, CurrentAuth, DbSession, require
from app.core.config import get_settings
from app.modules.billing.entitlements import EntitlementService
from app.modules.billing.gateways import build_gateway
from app.modules.billing.schemas import UsageItem, UsageResponse
from app.modules.billing.service import BillingService
from app.modules.tenancy.schemas import (
    OrganizationRead,
    OrganizationUpdate,
    SchoolCreate,
    SchoolRead,
    SchoolUpdate,
    TransferOwnershipRequest,
)
from app.modules.tenancy.service import TenancyService

org_router = APIRouter()
schools_router = APIRouter()


# ---------------------------------------------------------------------------
# Organization
# ---------------------------------------------------------------------------


@org_router.get("", response_model=OrganizationRead)
async def get_organization(
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("org:read"))],
) -> OrganizationRead:
    organization = await TenancyService(session).get_organization(ctx.organization_id)
    return OrganizationRead.model_validate(organization)


@org_router.patch("", response_model=OrganizationRead)
async def update_organization(
    payload: OrganizationUpdate,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("org:update"))],
) -> OrganizationRead:
    """Partial update.

    `exclude_unset=True` preserves PATCH semantics: a field the client omitted stays
    unchanged, while one explicitly sent as null is cleared. Collapsing those two
    into "falsy means clear" is how a PATCH silently wipes an organization's tax id.
    """
    organization = await TenancyService(session).update_organization(
        organization_id=ctx.organization_id,
        changes=payload.model_dump(exclude_unset=True),
        actor_user_id=ctx.user_id,
        actor_membership_id=ctx.membership_id,
    )
    return OrganizationRead.model_validate(organization)


@org_router.post("/transfer-ownership", response_model=OrganizationRead)
async def transfer_ownership(
    payload: TransferOwnershipRequest,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("org:transfer_ownership"))],
) -> OrganizationRead:
    """Hand the organization to another member. Atomic: promote, then demote."""
    organization = await TenancyService(session).transfer_ownership(
        organization_id=ctx.organization_id,
        new_owner_membership_id=payload.new_owner_membership_id,
        actor_user_id=ctx.user_id,
        actor_membership_id=ctx.membership_id,
    )
    return OrganizationRead.model_validate(organization)


@org_router.get("/usage", response_model=UsageResponse)
async def get_usage(session: DbSession, ctx: CurrentAuth) -> UsageResponse:
    """Live counters against plan limits (spec §8).

    Readable by ANY authenticated member, deliberately NOT gated behind
    `billing:read`. A teacher who hits a student limit needs to understand why the
    create failed; answering only "forbidden" sends them to ask the principal a
    question the UI could have answered itself.
    """
    gateway = build_gateway(get_settings())
    _, plan = await BillingService(session, gateway).get_subscription(ctx.organization_id)
    snapshots = await EntitlementService(session).snapshot(ctx.organization_id)

    return UsageResponse(
        plan_code=plan.code,
        organization_status=ctx.organization_status,
        items=[
            UsageItem(
                key=s.key,
                current=s.current,
                allowed=s.allowed,
                remaining=s.remaining,
                is_unlimited=s.is_unlimited,
                is_exhausted=s.is_exhausted,
            )
            for s in snapshots
        ],
    )


# ---------------------------------------------------------------------------
# Schools
# ---------------------------------------------------------------------------


@schools_router.get("", response_model=list[SchoolRead])
async def list_schools(
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("school:read"))],
) -> list[SchoolRead]:
    """Schools the caller can see.

    The principal (`ctx.school_id is None`) sees every school; a school-scoped member
    sees only their own. That is spec §2.3's soft boundary, applied here rather than
    by a policy.
    """
    # `principal` is the only org-level system role, and it is the one that manages
    # staffing across every branch. School-scoped roles stay confined to their own.
    school_filter = None if ctx.is_org_level else ctx.school_id
    schools = await TenancyService(session).list_schools(school_id_filter=school_filter)
    return [SchoolRead.model_validate(s) for s in schools]


@schools_router.post("", response_model=SchoolRead, status_code=status.HTTP_201_CREATED)
async def create_school(
    payload: SchoolCreate,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("school:create"))],
) -> SchoolRead:
    """Create a school. Entitlement-checked; 402 when the plan's limit is reached.

    `school:create` is an ORG-scoped permission, so this route is reachable only by
    the org-level principal. A school-scoped role cannot manufacture campuses the
    organization has not paid for.

    Returns the school and nothing else. The caller's access is unchanged by this
    call -- their org-level principal membership already covers the new campus -- so
    there is no membership grant for the response to report.
    """
    fields = payload.model_dump(exclude={"name", "code"}, exclude_unset=True)
    school = await TenancyService(session).create_school(
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        actor_membership_id=ctx.membership_id,
        name=payload.name,
        code=payload.code,
        **fields,
    )
    return SchoolRead.model_validate(school)


@schools_router.get("/{school_id}", response_model=SchoolRead)
async def get_school(
    school_id: UUID,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("school:read"))],
) -> SchoolRead:
    school = await TenancyService(session).get_school(school_id, allowed_school_id=ctx.school_id)
    return SchoolRead.model_validate(school)


@schools_router.patch("/{school_id}", response_model=SchoolRead)
async def update_school(
    school_id: UUID,
    payload: SchoolUpdate,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("school:update"))],
) -> SchoolRead:
    school = await TenancyService(session).update_school(
        school_id=school_id,
        organization_id=ctx.organization_id,
        changes=payload.model_dump(exclude_unset=True),
        actor_user_id=ctx.user_id,
        actor_membership_id=ctx.membership_id,
        allowed_school_id=ctx.school_id,
    )
    return SchoolRead.model_validate(school)


@schools_router.post("/{school_id}/archive", response_model=SchoolRead)
async def archive_school(
    school_id: UUID,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("school:archive"))],
) -> SchoolRead:
    """Archive a school. Records are retained; the plan seat is released."""
    school = await TenancyService(session).archive_school(
        school_id=school_id,
        organization_id=ctx.organization_id,
        actor_user_id=ctx.user_id,
        actor_membership_id=ctx.membership_id,
        allowed_school_id=ctx.school_id,
    )
    return SchoolRead.model_validate(school)
