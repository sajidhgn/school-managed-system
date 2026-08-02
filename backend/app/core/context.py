"""Per-request ambient context (request id, organization, school, actor).

WHY THIS FILE EXISTS
    Four facts are needed almost everywhere but belong in no function signature:
      * the request id        -- for log correlation
      * the current ORG       -- the hard tenant boundary, read by every RLS policy
      * the current SCHOOL    -- the soft scope filter inside that boundary
      * the acting user       -- for audit rows

    Threading these through router -> service -> repository as explicit arguments
    would pollute every signature in the codebase. `ContextVar` gives request-scoped
    ambient state that is safe under asyncio concurrency: each task gets its own
    copy, so two concurrent requests can never see each other's tenant.

RESPONSIBILITY
    Own the ContextVars and provide a typed accessor + setter API. Nothing more --
    no business logic, no I/O.

INTERACTIONS
    * `middleware/request_context.py` populates request_id at the edge.
    * `api/deps.py` populates org/school/user after JWT verification.
    * `db/session.py` reads them to emit the three `SET LOCAL` GUCs that activate
      PostgreSQL Row-Level Security.
    * `core/logging.py` reads request_id to stamp every log line.

=============================================================================
WHY TWO SCOPES AND NOT ONE -- spec decision D3
=============================================================================
    `organization_id` is the HARD boundary, enforced by the database. Every tenant
    table carries it and every RLS policy compares against it. Nothing an
    application bug can do will leak a row across it.

    `school_id` is the SOFT boundary, enforced by the permission dependency and a
    repository-level filter. It is deliberately weaker, because an organization
    owner legitimately needs to read across all their schools while a teacher must
    never escape theirs. Those are two different problems and they get two different
    mechanisms; collapsing them into one would either imprison the owner or free
    the teacher.

CAUTION
    ContextVars do not propagate into threads started with `run_in_executor` unless
    the context is copied explicitly. Keep tenant-sensitive work on the event loop.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_organization_id: ContextVar[UUID | None] = ContextVar("organization_id", default=None)
_school_id: ContextVar[UUID | None] = ContextVar("school_id", default=None)
_user_id: ContextVar[UUID | None] = ContextVar("user_id", default=None)
_is_platform_admin: ContextVar[bool] = ContextVar("is_platform_admin", default=False)


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Immutable snapshot of the ambient context, for logging and audit."""

    request_id: str | None
    organization_id: UUID | None
    school_id: UUID | None
    user_id: UUID | None
    is_platform_admin: bool


def get_context() -> RequestContext:
    return RequestContext(
        request_id=_request_id.get(),
        organization_id=_organization_id.get(),
        school_id=_school_id.get(),
        user_id=_user_id.get(),
        is_platform_admin=_is_platform_admin.get(),
    )


def reset_context() -> None:
    """Clear every tenant-scoped var.

    Used at the start of unauthenticated handling and in tests. Explicit clearing
    matters because asyncio tasks are reused: a leftover org id from a previous
    request would be stamped onto the next one's GUC.
    """
    _organization_id.set(None)
    _school_id.set(None)
    _user_id.set(None)
    _is_platform_admin.set(False)


# --- request id ------------------------------------------------------------


def set_request_id(value: str) -> Token[str | None]:
    return _request_id.set(value)


def get_request_id() -> str | None:
    return _request_id.get()


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous value. Pass the token returned by `set_request_id`."""
    _request_id.reset(token)


# --- organization: the hard tenant boundary --------------------------------


def set_organization_id(value: UUID | None) -> Token[UUID | None]:
    return _organization_id.set(value)


def get_organization_id() -> UUID | None:
    """Current tenant, or None for unauthenticated / platform-level requests."""
    return _organization_id.get()


def require_organization_id() -> UUID:
    """Tenant id, or raise.

    A miss here is a programming error -- a route wired without the tenant
    dependency -- not a user error, hence RuntimeError rather than an HTTP
    exception. Returning None silently instead would produce a query that matches
    zero rows and looks like an empty database.
    """
    organization_id = _organization_id.get()
    if organization_id is None:
        raise RuntimeError(
            "No organization in context. This route must depend on an authenticated "
            "tenant context (see api/deps.py::require)."
        )
    return organization_id


# --- school: the soft scope filter -----------------------------------------


def set_school_id(value: UUID | None) -> Token[UUID | None]:
    return _school_id.set(value)


def get_school_id() -> UUID | None:
    """Active school, or None for an org-level actor (the owner) who spans schools."""
    return _school_id.get()


def require_school_id() -> UUID:
    """Active school id, or raise. For routes only reachable by a school-scoped actor."""
    school_id = _school_id.get()
    if school_id is None:
        raise RuntimeError("No school in context. This route requires a school-scoped membership.")
    return school_id


# --- actor -----------------------------------------------------------------


def set_user_id(value: UUID | None) -> Token[UUID | None]:
    return _user_id.set(value)


def get_user_id() -> UUID | None:
    return _user_id.get()


def set_platform_admin(value: bool) -> Token[bool]:
    return _is_platform_admin.set(value)


def is_platform_admin() -> bool:
    """Whether the RLS cross-tenant READ escape hatch is armed for this request.

    Spec §2.2: this must never default to on. It is armed only inside an explicit,
    audited platform-admin or impersonation context, and it grants reads only --
    the `WITH CHECK` half of every policy has no admin escape, so a platform admin
    cannot write into a tenant except through endpoints that first bind that
    tenant's own org id.
    """
    return _is_platform_admin.get()
