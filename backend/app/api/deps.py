"""Shared FastAPI dependencies.

WHY THIS FILE EXISTS
    Dependency Injection is FastAPI's core composition mechanism. Centralising the
    reusable dependencies means auth, pagination and session handling are declared
    once and referenced everywhere -- and, critically, that they appear in the
    OpenAPI schema automatically (so Swagger shows a lock icon on protected routes).

RESPONSIBILITY
    Provide request-scoped collaborators: settings, DB session, current user,
    tenant, and role guards.

INTERACTIONS
    Imported by every route module. Depends on `core.security` to verify tokens and
    `core.context` to publish the tenant so `db.session` can apply RLS.

STYLE NOTE
    We use `Annotated[X, Depends(...)]` aliases rather than default-argument
    `Depends()`. Annotated aliases are reusable, compose cleanly, and keep route
    signatures readable:

        async def list_students(db: DbSession, user: CurrentUser) -> Page[StudentRead]:

    versus the older, noisier:

        async def list_students(db: AsyncSession = Depends(get_db), ...):

    ORDERING IS LOAD-BEARING: `get_current_principal` must run before the session is
    created, because it is what publishes `school_id` into the ContextVar that
    `get_db` reads when it stamps the RLS variable. FastAPI resolves the dependency
    graph depth-first, and `DbSession` here depends on the principal to guarantee
    that order rather than leaving it to declaration luck.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas import PageParams, SortParams
from app.core.config import Settings, get_settings
from app.core.context import set_school_id, set_super_admin, set_user_id
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.core.security import TokenType, decode_token
from app.db.session import get_db

# auto_error=False so a missing header raises OUR AuthenticationError (rendered as
# Problem Details) rather than Starlette's bespoke 403 body.
bearer_scheme = HTTPBearer(auto_error=False, description="JWT access token")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SettingsDep = Annotated[Settings, Depends(get_settings)]


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Principal:
    """The authenticated caller, decoded from the JWT.

    Deliberately NOT the ORM `User` object. Most requests only need the id, tenant
    and role -- all of which are in the signed token -- so materialising a Principal
    costs zero database queries. Routes that genuinely need the full user row can
    load it explicitly.
    """

    user_id: UUID
    school_id: UUID | None
    role: str | None
    is_super_admin: bool


async def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    settings: SettingsDep,
) -> Principal:
    """Verify the bearer token and publish the caller into the request context.

    THE SIDE EFFECT IS THE POINT: setting `school_id` in the ContextVar here is what
    makes tenant isolation work. `db.session.get_db` reads it moments later and
    issues `set_config('app.current_school_id', ...)`, which is the value every RLS
    policy compares against.

    `settings` is injected (not read from the global singleton) so token verification
    honours `dependency_overrides[get_settings]` -- e.g. a test signing key.
    """
    if credentials is None:
        raise AuthenticationError("Missing Authorization header.", code="TOKEN_MISSING")

    payload = decode_token(
        credentials.credentials, expected_type=TokenType.ACCESS, settings=settings
    )

    try:
        user_id = UUID(payload["sub"])
        raw_school = payload.get("sid")
        school_id = UUID(raw_school) if raw_school else None
    except (KeyError, ValueError) as exc:
        raise AuthenticationError("Token claims are malformed.", code="TOKEN_INVALID") from exc

    principal = Principal(
        user_id=user_id,
        school_id=school_id,
        role=payload.get("role"),
        is_super_admin=bool(payload.get("sa", False)),
    )

    set_user_id(principal.user_id)
    set_school_id(principal.school_id)
    set_super_admin(principal.is_super_admin)
    return principal


CurrentUser = Annotated[Principal, Depends(get_current_principal)]


async def get_current_school(principal: CurrentUser) -> UUID:
    """Require a tenant-scoped caller and return the school id.

    Platform super-admins carry no `sid` claim, so they cannot reach school-scoped
    routes without first selecting a school. That is intentional: it forces an
    explicit, auditable act of impersonation rather than ambient god-mode.
    """
    if principal.school_id is None:
        raise AuthorizationError(
            "This endpoint requires a school context.", code="NO_SCHOOL_CONTEXT"
        )
    return principal.school_id


CurrentSchool = Annotated[UUID, Depends(get_current_school)]


def require_roles(*allowed: str):  # type: ignore[no-untyped-def]
    """Dependency factory for role-based access control.

        @router.delete("/{id}", dependencies=[Depends(require_roles("school_admin"))])

    A factory (a function returning a dependency) is the idiomatic way to
    parameterise a FastAPI dependency. Super admins bypass role checks.
    """

    async def _check(principal: CurrentUser) -> Principal:
        if principal.is_super_admin:
            return principal
        if principal.role not in allowed:
            raise AuthorizationError(
                f"Requires one of: {', '.join(allowed)}.",
                code="INSUFFICIENT_ROLE",
                details={"required": list(allowed), "actual": principal.role},
            )
        return principal

    return _check


async def require_super_admin(principal: CurrentUser) -> Principal:
    """Guard for platform-level routes (onboarding schools, subscriptions)."""
    if not principal.is_super_admin:
        raise AuthorizationError("Platform administrator access required.")
    return principal


SuperAdmin = Annotated[Principal, Depends(require_super_admin)]


# ---------------------------------------------------------------------------
# Database session
# ---------------------------------------------------------------------------

# Unauthenticated session: for public routes such as the admissions form and login.
# Carries no tenant, so RLS-protected tables return zero rows through it.
PublicDbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_tenant_db(
    _principal: CurrentUser,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AsyncSession:
    """Authenticated, tenant-bound session.

    The unused `_principal` parameter is not decoration -- it forces FastAPI to
    resolve authentication BEFORE `get_db` runs, which is the ordering guarantee
    that makes the RLS variable correct. Removing it would silently produce
    sessions with no tenant bound.
    """
    return session


DbSession = Annotated[AsyncSession, Depends(get_tenant_db)]


# ---------------------------------------------------------------------------
# Query parameters
# ---------------------------------------------------------------------------

Pagination = Annotated[PageParams, Depends()]
Sorting = Annotated[SortParams, Depends()]


async def get_search_query(
    q: Annotated[str | None, Query(min_length=1, max_length=200, description="Search term")] = None,
) -> str | None:
    """Free-text search term, shared by list endpoints and the global omnibar."""
    return q.strip() if q else None


SearchQuery = Annotated[str | None, Depends(get_search_query)]
