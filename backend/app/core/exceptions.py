"""Domain exception hierarchy.

WHY THIS FILE EXISTS
    Services and repositories must be able to signal failure *without* importing
    `fastapi.HTTPException`. The moment a service raises an HTTP exception, that
    service is no longer usable from a CLI command, a Celery worker, or a test --
    it has become coupled to the web transport. That violates Clean Architecture's
    dependency rule: inner layers must not depend on outer layers.

    So: the domain raises `AppError` subclasses. A single handler in
    `api/errors.py` -- the *only* place that knows about HTTP -- translates them
    into responses.

RESPONSIBILITY
    Define a small, closed set of failure categories with a stable machine-readable
    `code` and a default HTTP status. Nothing else.

INTERACTIONS
    Raised by: services, repositories, dependencies.
    Caught by: `api/errors.py::app_error_handler`, which renders RFC 9457
    Problem Details JSON.

CONVENTION
    `code` is a stable SCREAMING_SNAKE string that frontend code may branch on.
    `message` is human-readable and may change freely. Never put secrets, SQL, or
    stack traces in `message` -- it is returned to the client verbatim.
"""

from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for every expected, domain-level failure.

    Anything that is *not* an AppError escaping to the handler is treated as an
    unexpected bug: logged with a stack trace and rendered as a generic 500 so we
    never leak internals to the client.
    """

    status_code: int = 500
    code: str = "INTERNAL_ERROR"
    message: str = "An unexpected error occurred."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.message
        self.code = code or self.code
        self.details = details or {}
        super().__init__(self.message)


# --- 4xx: caller's fault ---------------------------------------------------


class ValidationError(AppError):
    """Input is well-formed but semantically invalid.

    Use for rules Pydantic cannot express, e.g. "admission date must fall inside
    the selected academic year". Pure shape/type errors are caught by Pydantic
    and surface as 422 through a different handler.
    """

    status_code = 422
    code = "VALIDATION_ERROR"
    message = "The submitted data is invalid."


class NotFoundError(AppError):
    """Requested resource does not exist, or is invisible to this tenant.

    IMPORTANT: under Row-Level Security, a row belonging to another school is
    simply not returned by the query -- so cross-tenant access naturally produces
    404, not 403. That is the desired behaviour: a 403 would confirm the resource
    exists, leaking information across the tenant boundary.
    """

    status_code = 404
    code = "NOT_FOUND"
    message = "The requested resource was not found."


class ConflictError(AppError):
    """Request conflicts with current state (duplicate key, illegal transition)."""

    status_code = 409
    code = "CONFLICT"
    message = "The request conflicts with the current state of the resource."


class AuthenticationError(AppError):
    """Caller is not authenticated, or the token is invalid/expired."""

    status_code = 401
    code = "UNAUTHENTICATED"
    message = "Authentication credentials were missing or invalid."


class AuthorizationError(AppError):
    """Caller is authenticated but lacks the required role/permission."""

    status_code = 403
    code = "FORBIDDEN"
    message = "You do not have permission to perform this action."


class RateLimitError(AppError):
    status_code = 429
    code = "RATE_LIMITED"
    message = "Too many requests. Please retry later."


# --- 5xx: our fault, or a dependency's ------------------------------------


class ExternalServiceError(AppError):
    """A third-party call failed (WhatsApp API, payment gateway, LLM provider).

    Distinguished from a generic 500 so that retry/circuit-breaker logic and
    alerting can treat "our dependency is down" differently from "our code broke".
    """

    status_code = 502
    code = "EXTERNAL_SERVICE_ERROR"
    message = "An upstream service failed to respond correctly."


class ServiceUnavailableError(AppError):
    """We cannot serve the request right now (e.g. database not configured)."""

    status_code = 503
    code = "SERVICE_UNAVAILABLE"
    message = "The service is temporarily unavailable."
