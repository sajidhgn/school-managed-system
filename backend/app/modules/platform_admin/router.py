"""Platform console routes (spec §8 "Platform").

WHY THIS FILE EXISTS
    The operator surface. Every route here except login sits behind
    `require_platform_admin`, which checks the token's `typ` claim -- so a tenant
    token, however privileged inside its organization, cannot reach any of it.

RESPONSIBILITY
    Route definitions and response assembly for the platform console.

INTERACTIONS
    `modules/platform_admin/service.py` for every operation.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, Query, Request, Response, status
from sqlalchemy import select

from app.api.cookies import set_auth_cookies
from app.api.deps import (
    ClientIp,
    PlatformAuth,
    PlatformDbSession,
    PublicDbSession,
    SettingsDep,
)
from app.core.exceptions import AuthorizationError
from app.core.security import (
    PrincipalType,
    create_access_token,
    generate_opaque_token,
    hash_token,
)
from app.db.session import bind_tenant
from app.modules.auth.models import Session
from app.modules.auth.router import _attach_body_tokens, _wants_body_tokens
from app.modules.auth.service import IssuedTokens
from app.modules.platform_admin.models import Plan, PlatformAdmin, PlatformAuditLog
from app.modules.platform_admin.schemas import (
    ImpersonateRequest,
    ImpersonationGrant,
    MetricsResponse,
    OrganizationDetail,
    OrganizationStatusUpdate,
    OrganizationSummary,
    PlanAdminRead,
    PlanImpactRequest,
    PlanImpactResponse,
    PlanOverrideRequest,
    PlanPatch,
    PlanWrite,
    PlatformAdminRead,
    PlatformAuditRead,
    PlatformLoginRequest,
)
from app.modules.platform_admin.service import PlatformService

router = APIRouter()


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


@router.post("/auth/login", response_model=PlatformAdminRead)
async def platform_login(
    payload: PlatformLoginRequest,
    response: Response,
    request: Request,
    session: PublicDbSession,
    settings: SettingsDep,
    ip: ClientIp,
    x_token_transport: Annotated[str | None, Header()] = None,
) -> PlatformAdminRead:
    """Sign in as a platform operator (spec §4.3A).

    THERE IS NO REGISTRATION ROUTE, and there never will be. Accounts are minted by
    `python -m app.cli seed`, and credentials rotate through the CLI. An emailed
    password reset for this role would reduce the platform's security to the security
    of one inbox -- and this role can read every school's records.
    """
    admin = await PlatformService(session, settings).authenticate(
        email=payload.email, password=payload.password, ip=ip
    )

    raw_refresh = generate_opaque_token()
    session_row = Session(
        user_id=None,
        platform_admin_id=admin.id,
        refresh_token_hash=hash_token(raw_refresh),
        family_id=uuid4(),
        expires_at=datetime.now(UTC) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        ip=ip,
        user_agent=request.headers.get("User-Agent"),
    )
    session.add(session_row)
    await session.flush()

    access = create_access_token(
        user_id=admin.id,
        session_id=session_row.id,
        # The claim that keeps the two surfaces apart. Spec §9 requires the platform
        # group to be unreachable with a tenant token and vice versa, and an explicit
        # discriminator is the only version of that check which a token merely
        # missing a field cannot satisfy.
        principal_type=PrincipalType.PLATFORM,
        settings=settings,
    )
    set_auth_cookies(response, access_token=access, refresh_token=raw_refresh, settings=settings)

    if _wants_body_tokens(x_token_transport):
        # For the Next.js BFF, which is a confidential client holding the session on
        # the operator's behalf. The cookies above are scoped to THIS API's origin and
        # are useless to a caller whose browser talks to a different host, so the pair
        # is also offered as headers on explicit request.
        _attach_body_tokens(
            response,
            IssuedTokens(
                access_token=access,
                refresh_token=raw_refresh,
                session_id=session_row.id,
                expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            ),
            settings,
        )

    return PlatformAdminRead(
        id=admin.id,
        email=admin.email,
        full_name=admin.full_name,
        is_active=admin.is_active,
        mfa_enabled=admin.mfa_secret is not None,
        last_login_at=admin.last_login_at,
    )


@router.get("/auth/me", response_model=PlatformAdminRead)
async def platform_me(ctx: PlatformAuth, session: PlatformDbSession) -> PlatformAdminRead:
    admin = await session.get(PlatformAdmin, ctx.admin_id)
    if admin is None or not admin.is_active:
        raise AuthorizationError("This operator account is no longer active.")
    return PlatformAdminRead(
        id=admin.id,
        email=admin.email,
        full_name=admin.full_name,
        is_active=admin.is_active,
        mfa_enabled=admin.mfa_secret is not None,
        last_login_at=admin.last_login_at,
    )


# ---------------------------------------------------------------------------
# Organizations
# ---------------------------------------------------------------------------


def _summary(row: dict[str, Any]) -> OrganizationSummary:
    organization = row["organization"]
    plan = row.get("plan")
    usage = row.get("usage")
    subscription = row.get("subscription")
    return OrganizationSummary(
        id=organization.id,
        name=organization.name,
        slug=organization.slug,
        status=organization.status.value,
        country=organization.country,
        billing_email=organization.billing_email,
        plan_code=plan.code if plan else None,
        plan_name=plan.name if plan else None,
        subscription_status=subscription.status.value if subscription else None,
        schools_count=usage.schools_count if usage else 0,
        staff_count=usage.staff_count if usage else 0,
        students_count=usage.students_count if usage else 0,
        created_at=organization.created_at,
    )


@router.get("/organizations", response_model=list[OrganizationSummary])
async def list_organizations(
    session: PlatformDbSession,
    settings: SettingsDep,
    ctx: PlatformAuth,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    plan: Annotated[str | None, Query()] = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[OrganizationSummary]:
    """Every organization on the platform (spec §8)."""
    rows = await PlatformService(session, settings).list_organizations(
        status_filter=status_filter, plan_code=plan, query=q, limit=limit, offset=offset
    )
    return [_summary(r) for r in rows]


@router.get("/organizations/{organization_id}", response_model=OrganizationDetail)
async def get_organization(
    organization_id: UUID,
    session: PlatformDbSession,
    settings: SettingsDep,
    ctx: PlatformAuth,
) -> OrganizationDetail:
    row = await PlatformService(session, settings).get_organization(organization_id)
    organization = row["organization"]
    subscription = row["subscription"]
    plan = row["plan"]

    return OrganizationDetail(
        **_summary(row).model_dump(),
        owner_user_id=organization.owner_user_id,
        currency=organization.currency,
        timezone=organization.timezone,
        trial_ends_at=subscription.trial_ends_at if subscription else None,
        current_period_end=subscription.current_period_end if subscription else None,
        limits=plan.limits if plan else None,
    )


@router.patch("/organizations/{organization_id}/status", response_model=OrganizationSummary)
async def set_organization_status(
    organization_id: UUID,
    payload: OrganizationStatusUpdate,
    session: PlatformDbSession,
    settings: SettingsDep,
    ctx: PlatformAuth,
    ip: ClientIp,
) -> OrganizationSummary:
    """Suspend or reactivate (spec §8).

    Suspension is READ-ONLY, not a lockout: the customer keeps read and export access
    to their own records. See the service for why that is not negotiable.
    """
    service = PlatformService(session, settings)
    await service.set_organization_status(
        admin_id=ctx.admin_id,
        organization_id=organization_id,
        suspend=payload.suspend,
        reason=payload.reason,
        ip=ip,
    )
    return _summary(await service.get_organization(organization_id))


@router.post("/organizations/{organization_id}/plan", response_model=OrganizationSummary)
async def override_plan(
    organization_id: UUID,
    payload: PlanOverrideRequest,
    session: PlatformDbSession,
    settings: SettingsDep,
    ctx: PlatformAuth,
    ip: ClientIp,
) -> OrganizationSummary:
    """Assign any plan manually, including hidden ones (spec §8)."""
    service = PlatformService(session, settings)
    await service.override_plan(
        admin_id=ctx.admin_id,
        organization_id=organization_id,
        plan_code=payload.plan_code,
        ip=ip,
    )
    return _summary(await service.get_organization(organization_id))


@router.post("/organizations/{organization_id}/impersonate", response_model=ImpersonationGrant)
async def impersonate(
    organization_id: UUID,
    payload: ImpersonateRequest,
    session: PlatformDbSession,
    settings: SettingsDep,
    ctx: PlatformAuth,
    ip: ClientIp,
) -> ImpersonationGrant:
    """Open an audited, time-boxed, READ-ONLY window into one organization (spec §8).

    Read-only is enforced by the database, not by this endpoint: the `WITH CHECK`
    half of every RLS policy has no platform-admin escape, so writes through a
    platform context fail at the policy regardless of what the application intends.
    """
    grant = await PlatformService(session, settings).begin_impersonation(
        admin_id=ctx.admin_id,
        organization_id=organization_id,
        reason=payload.reason,
        ip=ip,
    )
    return ImpersonationGrant.model_validate(grant)


# ---------------------------------------------------------------------------
# Plans
# ---------------------------------------------------------------------------


@router.get("/plans", response_model=list[PlanAdminRead])
async def list_plans(
    session: PlatformDbSession, settings: SettingsDep, ctx: PlatformAuth
) -> list[Plan]:
    """Every plan, including hidden and retired ones."""
    return await PlatformService(session, settings).list_plans()


@router.post("/plans", response_model=PlanAdminRead, status_code=status.HTTP_201_CREATED)
async def create_plan(
    payload: PlanWrite,
    session: PlatformDbSession,
    settings: SettingsDep,
    ctx: PlatformAuth,
) -> Plan:
    return await PlatformService(session, settings).create_plan(
        admin_id=ctx.admin_id, data=payload.model_dump()
    )


@router.patch("/plans/{plan_id}", response_model=PlanAdminRead)
async def update_plan(
    plan_id: UUID,
    payload: PlanPatch,
    session: PlatformDbSession,
    settings: SettingsDep,
    ctx: PlatformAuth,
) -> Plan:
    return await PlatformService(session, settings).update_plan(
        admin_id=ctx.admin_id,
        plan_id=plan_id,
        changes=payload.model_dump(exclude_unset=True, exclude_none=True),
    )


@router.post("/plans/{plan_id}/impact", response_model=PlanImpactResponse)
async def plan_impact(
    plan_id: UUID,
    payload: PlanImpactRequest,
    session: PlatformDbSession,
    settings: SettingsDep,
    ctx: PlatformAuth,
) -> PlanImpactResponse:
    """Dry-run a limit change: who is on this plan, and who would be pushed over.

    POST rather than GET despite being read-only, because the proposed limits are a
    structured body. Encoding six integers into a query string would work and would
    read badly at every call site.

    NOTHING IS WRITTEN. The console calls this before a save so the operator sees the
    consequence -- named organizations, not a count -- while they can still change
    their mind. See `PlatformService.plan_impact` for why that matters more here than
    anywhere else in the console.
    """
    result = await PlatformService(session, settings).plan_impact(
        plan_id=plan_id, proposed_limits=payload.limits
    )
    return PlanImpactResponse.model_validate(result)


@router.delete("/plans/{plan_id}", response_model=PlanAdminRead)
async def retire_plan(
    plan_id: UUID,
    session: PlatformDbSession,
    settings: SettingsDep,
    ctx: PlatformAuth,
) -> Plan:
    """Retire a plan. NEVER a hard delete -- existing subscribers keep their terms."""
    return await PlatformService(session, settings).retire_plan(
        admin_id=ctx.admin_id, plan_id=plan_id
    )


# ---------------------------------------------------------------------------
# Metrics & audit
# ---------------------------------------------------------------------------


@router.get("/metrics", response_model=MetricsResponse)
async def metrics(
    session: PlatformDbSession, settings: SettingsDep, ctx: PlatformAuth
) -> MetricsResponse:
    """MRR, organization counts, seats and churn (spec §8)."""
    return MetricsResponse.model_validate(await PlatformService(session, settings).metrics())


@router.get("/audit-logs", response_model=list[PlatformAuditRead])
async def platform_audit_logs(
    session: PlatformDbSession,
    ctx: PlatformAuth,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[PlatformAuditLog]:
    """What operators have done, newest first (spec §8)."""
    await bind_tenant(session, None, platform_admin=True)
    try:
        rows = await session.execute(
            select(PlatformAuditLog)
            .order_by(PlatformAuditLog.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows.scalars().all())
    finally:
        await bind_tenant(session, None)
