"""Per-request ambient context (request id, tenant, actor).

WHY THIS FILE EXISTS
    Three facts are needed almost everywhere but belong in no function signature:
      * the request id      -- for log correlation
      * the current school  -- the tenant boundary, needed by *every* query
      * the acting user     -- for audit columns (created_by / updated_by)

    Threading these through router -> service -> repository -> model as explicit
    arguments would pollute every signature in the codebase. `ContextVar` gives us
    request-scoped ambient state that is safe under asyncio concurrency: each task
    gets its own copy, so two concurrent requests can never see each other's tenant.

RESPONSIBILITY
    Own the ContextVars and provide a typed accessor + setter API. Nothing more --
    no business logic, no I/O.

INTERACTIONS
    * `middleware/request_context.py` populates request_id at the edge.
    * `api/deps.py` populates school_id / user_id after JWT verification.
    * `db/session.py` reads school_id to emit `SET LOCAL app.current_school_id`,
      which is what actually activates PostgreSQL Row-Level Security.
    * `core/logging.py` reads request_id to stamp every log line.

CAUTION
    ContextVars do not propagate into threads started with `run_in_executor` unless
    the context is copied explicitly. Keep tenant-sensitive work on the event loop.
"""

from __future__ import annotations

from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)
_school_id: ContextVar[UUID | None] = ContextVar("school_id", default=None)
_user_id: ContextVar[UUID | None] = ContextVar("user_id", default=None)
_is_super_admin: ContextVar[bool] = ContextVar("is_super_admin", default=False)


@dataclass(frozen=True, slots=True)
class RequestContext:
    """Immutable snapshot of the ambient context, for logging and audit."""

    request_id: str | None
    school_id: UUID | None
    user_id: UUID | None
    is_super_admin: bool


def get_context() -> RequestContext:
    return RequestContext(
        request_id=_request_id.get(),
        school_id=_school_id.get(),
        user_id=_user_id.get(),
        is_super_admin=_is_super_admin.get(),
    )


# --- request id ------------------------------------------------------------


def set_request_id(value: str) -> Token[str | None]:
    return _request_id.set(value)


def get_request_id() -> str | None:
    return _request_id.get()


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous value. Pass the token returned by `set_request_id`.

    Resetting matters because the asyncio task that served this request may be
    reused; a stale id would silently mislabel a later log line.
    """
    _request_id.reset(token)


# --- tenant ----------------------------------------------------------------


def set_school_id(value: UUID | None) -> Token[UUID | None]:
    return _school_id.set(value)


def get_school_id() -> UUID | None:
    """Current tenant, or None for unauthenticated / platform-level requests."""
    return _school_id.get()


def require_school_id() -> UUID:
    """Tenant id, or raise.

    Use in code paths that are *only* reachable by a school-scoped actor. A miss
    here is a programming error (a route wired without the tenant dependency),
    not a user error -- hence RuntimeError rather than an HTTP exception.
    """
    school_id = _school_id.get()
    if school_id is None:
        raise RuntimeError("No tenant in context. This route must depend on `get_current_school`.")
    return school_id


# --- actor -----------------------------------------------------------------


def set_user_id(value: UUID | None) -> Token[UUID | None]:
    return _user_id.set(value)


def get_user_id() -> UUID | None:
    return _user_id.get()


def set_super_admin(value: bool) -> Token[bool]:
    return _is_super_admin.set(value)


def is_super_admin() -> bool:
    return _is_super_admin.get()
