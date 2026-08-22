"""Shared FastAPI dependencies -- authentication, authorization, and session wiring.

WHY THIS FILE EXISTS
    Spec §5.4 is blunt about it: "One dependency, used on every route. No ad-hoc
    `if user.role == 'principal'` anywhere in the codebase -- that check is a bug
    waiting to happen." This module is that dependency.

    A role-name comparison scattered through handlers fails in three ways at once:
    it cannot express custom roles (which customers create), it drifts as roles gain
    permissions, and it is invisible to review -- nobody can answer "who can invite
    staff?" without grepping. Resolving an explicit permission set in one place makes
    that question a lookup.

RESPONSIBILITY
    Provide request-scoped collaborators: settings, DB session, the authenticated
    context, and the permission guard. No business logic.

INTERACTIONS
    Imported by every route module. Publishes the tenant into `core.context` so
    `db.session` can stamp the RLS GUCs, and reads permission sets through
    `core.cache`.

=============================================================================
ORDERING IS LOAD-BEARING
=============================================================================
    `get_access_claims` MUST run before the database session is created, because it
    is what publishes `organization_id` into the ContextVar that `get_db` reads when
    it issues `set_config('app.current_org_id', ...)`. That GUC is the value every
    RLS policy compares against.

    FastAPI resolves the dependency graph depth-first, so `get_tenant_db` takes the
    claims as an explicitly unused parameter to force that order rather than leaving
    it to declaration luck. Removing that parameter would silently produce sessions
    with no tenant bound -- which, thanks to `NULLIF(..., '')` in the policies,
    returns zero rows rather than everything. Safe, but baffling to debug.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.common.schemas import PageParams, SortParams
from app.core.cache import get_role_permissions
from app.core.config import Settings, get_settings
from app.core.context import (
    reset_context,
    set_organization_id,
    set_platform_admin,
    set_school_id,
    set_user_id,
)
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.logging import get_logger
from app.core.security import AccessClaims, PrincipalType, decode_access_token
from app.db.session import get_db
from app.modules.platform_admin.models import PlatformAdmin
from app.modules.rbac.models import Membership, MembershipStatus, Role, RolePermission
from app.modules.tenancy.models import Organization

logger = get_logger(__name__)

SettingsDep = Annotated[Settings, Depends(get_settings)]

# HTTP methods that do not modify state. Used to keep a suspended organization
# readable (spec §6.3) rather than locked out entirely.
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


# ---------------------------------------------------------------------------
# Token extraction
# ---------------------------------------------------------------------------


def _extract_token(request: Request, settings: Settings) -> str | None:
    """Read the access token from the Authorization header, else the cookie.

    TWO TRANSPORTS ON PURPOSE. The browser app uses an httpOnly cookie, because a
    token reachable from JavaScript is a token any XSS payload can exfiltrate. But
    non-browser callers -- the test suite, CI, future server-to-server integrations
    -- have no cookie jar and must send a bearer header.

    The header is checked FIRST so that an explicit credential always wins over an
    ambient one. If a developer pastes a bearer token into a browser session that
    already holds a cookie, they get the identity they asked for rather than a
    confusing mix.
    """
    header = request.headers.get("Authorization")
    if header and header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get(settings.ACCESS_COOKIE_NAME)


async def get_access_claims(request: Request, settings: SettingsDep) -> AccessClaims:
    """Verify the access token and publish the caller into the request context.

    THE SIDE EFFECT IS THE POINT: setting the organization in the ContextVar here is
    what makes tenant isolation work. See the module docstring on ordering.

    `settings` is injected rather than read from the global singleton so token
    verification honours `dependency_overrides[get_settings]` -- e.g. a test key.
    """
    reset_context()

    token = _extract_token(request, settings)
    if not token:
        raise AuthenticationError("Missing access token.", code="TOKEN_MISSING")

    claims = decode_access_token(token, settings=settings)

    set_user_id(claims.user_id)
    set_organization_id(claims.organization_id)
    set_school_id(claims.school_id)
    # NEVER armed from a token claim alone. A platform admin reads across tenants
    # only inside an explicit impersonation context, which sets this separately --
    # see `modules/platform_admin/service.py`. Defaulting it on for any token
    # carrying `typ: platform` would make every platform request a cross-tenant read.
    set_platform_admin(False)

    return claims


CurrentClaims = Annotated[AccessClaims, Depends(get_access_claims)]


# ---------------------------------------------------------------------------
# Database session
# ---------------------------------------------------------------------------

# Unauthenticated session: for public routes (pricing, invitation verify, webhooks).
# Carries no tenant, so RLS-protected tables return zero rows through it -- which is
# exactly right for a caller who has not proven which tenant they are.
PublicDbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_tenant_db(
    _claims: CurrentClaims,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AsyncSession:
    """Authenticated, tenant-bound session.

    The unused `_claims` parameter is not decoration -- it forces FastAPI to resolve
    authentication BEFORE `get_db` runs, which is the ordering guarantee that makes
    the RLS GUCs correct.
    """
    return session


DbSession = Annotated[AsyncSession, Depends(get_tenant_db)]


# ---------------------------------------------------------------------------
# The authenticated context
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AuthContext:
    """Everything a handler needs to know about its caller.

    Frozen: a handler must not be able to widen its own context mid-request. If a
    route needs to act in a different scope -- an owner reaching into one of their
    schools -- it says so explicitly rather than mutating this.
    """

    user_id: UUID
    organization_id: UUID
    membership_id: UUID
    role_id: UUID
    role_code: str
    permissions: frozenset[str]
    school_id: UUID | None
    organization_status: str

    @property
    def is_org_level(self) -> bool:
        """True for the owner: spans every school in the organization (spec §2.3)."""
        return self.school_id is None

    def has(self, *codes: str) -> bool:
        """Whether the caller holds every one of `codes`.

        ALL, not ANY. A route asking for two permissions is describing an action that
        genuinely needs both, and `any` semantics there would let a partial grant
        through -- the kind of default that looks harmless until the one route that
        relied on it turns out to be the destructive one.
        """
        return all(code in self.permissions for code in codes)

    def require_school(self) -> UUID:
        """The active school, or raise if this is an org-level context.

        For handlers whose work is meaningless without a campus. The owner reaching
        such a route must first pick a school -- which is a real product decision,
        not an error: "mark attendance" has no answer at organization level.
        """
        if self.school_id is None:
            raise AuthorizationError(
                "This action requires an active school context. Select a school first.",
                code="NO_SCHOOL_CONTEXT",
            )
        return self.school_id


async def _load_permission_codes(session: AsyncSession, role_id: UUID) -> frozenset[str]:
    """Authoritative read of a role's permission set from Postgres.

    Passed to the cache as the miss-path loader, so this runs only on a cold key.
    """
    result = await session.execute(
        select(RolePermission.permission_code).where(RolePermission.role_id == role_id)
    )
    return frozenset(result.scalars().all())


async def _resolve_context(
    claims: AccessClaims,
    session: AsyncSession,
    settings: Settings,
) -> AuthContext:
    """Turn verified token claims into a live, checked authorization context.

    =========================================================================
    WHY THE MEMBERSHIP IS RE-READ ON EVERY REQUEST
    =========================================================================
        The token already names the membership, org, school and role. Trusting it
        outright would save a query -- and would mean a member suspended two minutes
        ago keeps full access until their token expires. Revocation that takes effect
        "within 15 minutes" is not revocation; it is a delay.

        So: one indexed primary-key lookup, joined to the role and the organization,
        on every authorised request. That is the price of same-request revocation and
        it is worth paying.

    =========================================================================
    THE ROLE'S CURRENT `permissions_version` IS AUTHORITATIVE, NOT THE TOKEN'S
    =========================================================================
        The token carries `pv` as it was at issue time. The cache key is built from
        the row's CURRENT `permissions_version`, which is what makes spec §4.2 work:
        when a principal edits a role the counter increments, so tokens minted before
        the edit resolve against a fresh key and pick up the new set immediately.

        Using the token's `pv` for the key would cache the stale set under the stale
        key and serve it happily until expiry -- reintroducing exactly the bug the
        version number exists to eliminate. The token's value is kept only as a
        signal worth logging.
    """
    if claims.is_platform:
        raise AuthorizationError(
            "This endpoint requires an organization context; a platform token was presented.",
            code="WRONG_TOKEN_TYPE",
        )
    if claims.membership_id is None or claims.organization_id is None:
        raise AuthenticationError(
            "No active membership on this token. Select a context first.",
            code="NO_ACTIVE_CONTEXT",
        )

    membership = (
        await session.execute(
            select(Membership)
            .options(joinedload(Membership.role), joinedload(Membership.organization))
            .where(Membership.id == claims.membership_id)
        )
    ).scalar_one_or_none()

    # RLS already scoped this query to the token's organization, so a membership
    # belonging to another tenant simply is not returned -- there is no separate
    # cross-tenant check to forget here.
    if membership is None or membership.deleted_at is not None:
        raise AuthenticationError("This membership no longer exists.", code="MEMBERSHIP_REVOKED")
    if membership.status is not MembershipStatus.ACTIVE:
        raise AuthorizationError("This membership is suspended.", code="MEMBERSHIP_SUSPENDED")
    if membership.user_id != claims.user_id:
        # Only reachable via a forged or mis-minted token; treat as hostile.
        raise AuthenticationError("Token does not match its membership.", code="TOKEN_INVALID")

    organization: Organization = membership.organization
    if not organization.is_active and not organization.is_read_only:
        raise AuthorizationError(
            "This organization is no longer active.", code="ORGANIZATION_INACTIVE"
        )

    role: Role = membership.role
    if claims.permissions_version is not None and claims.permissions_version != (
        role.permissions_version
    ):
        logger.info(
            "permission_version_stale",
            role_id=str(role.id),
            token_pv=claims.permissions_version,
            current_pv=role.permissions_version,
        )

    permissions = await get_role_permissions(
        str(role.id),
        role.permissions_version,
        lambda: _load_permission_codes(session, role.id),
        settings=settings,
    )

    return AuthContext(
        user_id=membership.user_id,
        organization_id=membership.organization_id,
        membership_id=membership.id,
        role_id=role.id,
        role_code=role.code,
        permissions=permissions,
        school_id=membership.school_id,
        organization_status=organization.status.value,
    )


async def get_auth_context(
    claims: CurrentClaims,
    session: DbSession,
    settings: SettingsDep,
) -> AuthContext:
    """The authenticated context with NO permission requirement.

    For routes any authenticated member may reach -- `GET /auth/me`, the context
    switcher, the school list. Everything else should use `require(...)`.
    """
    return await _resolve_context(claims, session, settings)


CurrentAuth = Annotated[AuthContext, Depends(get_auth_context)]


def require(*codes: str):  # type: ignore[no-untyped-def]
    """Dependency factory: demand specific permissions (spec §5.4).

        @router.post("/schools/{school_id}/members")
        async def invite_member(
            payload: InviteCreate,
            ctx: AuthContext = Depends(require("member:invite")),
        ):
            ...

    Resolves the token, loads the permission set, verifies the organization is not
    read-only for this method, and returns the `AuthContext`. A missing permission
    is a 403 naming exactly what was required -- an opaque "forbidden" forces the
    frontend to guess, and guesses become hardcoded role checks in the UI.

    A factory (a function returning a dependency) is the idiomatic way to
    parameterise a FastAPI dependency, and it keeps the required permissions visible
    in the route signature, where a reviewer reads them.
    """

    async def _guard(
        request: Request,
        claims: CurrentClaims,
        session: DbSession,
        settings: SettingsDep,
    ) -> AuthContext:
        ctx = await _resolve_context(claims, session, settings)

        # Spec §6.3: a suspended organization keeps read access and exports. Never
        # lock a school out of its own student records over a payment dispute --
        # the records are the school's, not ours, and withholding them is leverage
        # no software vendor should hold over a school mid-term.
        if ctx.organization_status == "suspended" and request.method not in _SAFE_METHODS:
            raise AuthorizationError(
                "This organization is suspended and is currently read-only.",
                code="ORGANIZATION_READ_ONLY",
                details={"upgrade_url": "/billing/plans"},
            )

        missing = [code for code in codes if code not in ctx.permissions]
        if missing:
            raise AuthorizationError(
                "You do not have permission to perform this action.",
                code="FORBIDDEN",
                details={"required": list(codes), "missing": missing},
            )
        return ctx

    return _guard


# ---------------------------------------------------------------------------
# Platform admin
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlatformContext:
    """The authenticated platform operator."""

    admin_id: UUID
    session_id: UUID


async def require_platform_admin(
    claims: CurrentClaims,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> PlatformContext:
    """Guard for `/platform/*` routes.

    Checks the `typ` claim rather than the absence of an `org` claim. Spec §9 wants
    the platform surface unreachable with a tenant token and vice versa, and an
    explicit discriminator is the only version of that check which cannot be
    satisfied by a token that merely happens to be missing a field.

    THE ACCOUNT IS RE-READ ON EVERY REQUEST, for the same reason tenant memberships
    are: deactivating an operator must take effect immediately, not whenever their
    token happens to expire. This is the most privileged role on the platform, so a
    15-minute window between "revoked" and "actually revoked" is the least
    acceptable place to have one.

    Note this does NOT arm the cross-tenant read GUC. Reading another organization's
    rows is a separate, audited, time-boxed impersonation step.
    """
    if claims.principal_type is not PrincipalType.PLATFORM:
        raise AuthorizationError(
            "Platform administrator access required.", code="PLATFORM_ACCESS_REQUIRED"
        )

    admin = await session.get(PlatformAdmin, claims.user_id)
    if admin is None or not admin.is_active:
        raise AuthorizationError(
            "This operator account is no longer active.", code="PLATFORM_ACCOUNT_INACTIVE"
        )

    return PlatformContext(admin_id=admin.id, session_id=claims.session_id)


PlatformAuth = Annotated[PlatformContext, Depends(require_platform_admin)]


async def get_platform_db(
    _ctx: PlatformAuth,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AsyncSession:
    """Session for platform routes. Same ordering trick as `get_tenant_db`."""
    return session


PlatformDbSession = Annotated[AsyncSession, Depends(get_platform_db)]


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------

Pagination = Annotated[PageParams, Depends()]
Sorting = Annotated[SortParams, Depends()]


async def get_search_query(
    q: Annotated[str | None, Query(min_length=1, max_length=200, description="Search term")] = None,
) -> str | None:
    """Free-text search term, shared by list endpoints."""
    return q.strip() if q else None


SearchQuery = Annotated[str | None, Depends(get_search_query)]


async def get_client_ip(request: Request, settings: SettingsDep) -> str | None:
    """Best-effort client IP for audit rows.

    Prefers the leftmost `X-Forwarded-For` entry, since the app runs behind a proxy
    in every deployed environment. This value is ATTACKER-CONTROLLED unless the proxy
    is configured to overwrite the header -- so it is recorded for investigation and
    never used for an authorization decision. Rate limiting that trusted it would be
    trivially bypassed by spoofing.
    """
    peer = request.client.host if request.client else None
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded and peer in settings.TRUSTED_PROXY_IPS:
        return forwarded.split(",")[0].strip()[:45]
    return peer


ClientIp = Annotated[str | None, Depends(get_client_ip)]
