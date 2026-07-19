"""Exception handlers -- the single translation point from domain errors to HTTP.

WHY THIS FILE EXISTS
    This is the *only* module allowed to know both the domain vocabulary
    (`AppError`) and the HTTP vocabulary (status codes, JSON bodies). Keeping that
    knowledge in one file is what lets services stay transport-agnostic.

RESPONSIBILITY
    Convert every exception that can reach the ASGI layer into a consistent
    RFC 9457 Problem Details response, and decide what is safe to disclose.

INTERACTIONS
    Registered on the app in `main.py::create_app`. Reads `core.context` for the
    request id so every error body carries a correlation handle.

THE SECURITY RULE ENCODED HERE
    Expected errors (AppError) return their message verbatim -- they were written
    for the client. Unexpected errors return a fixed generic message and log the
    stack trace server-side. An unhandled `IntegrityError` echoed to the client
    would disclose table names, column names and constraint definitions.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.common.schemas import FieldError, ProblemDetail
from app.core.config import get_settings
from app.core.context import get_request_id
from app.core.exceptions import AppError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Documentation anchors. Pointing `type` at a real docs page turns every error into
# a link a developer can follow, which is the entire point of RFC 9457.
ERROR_TYPE_BASE = "https://docs.example.com/errors"


def _problem_response(
    *,
    status_code: int,
    title: str,
    detail: str,
    code: str,
    errors: list[FieldError] | None = None,
    meta: dict[str, Any] | None = None,
) -> JSONResponse:
    problem = ProblemDetail(
        type=f"{ERROR_TYPE_BASE}/{code.lower().replace('_', '-')}",
        title=title,
        status=status_code,
        detail=detail,
        instance=get_request_id(),
        code=code,
        errors=errors,
        meta=meta,
    )
    return JSONResponse(
        status_code=status_code,
        # RFC 9457 mandates this content type. Clients and gateways use it to
        # distinguish an error body from a successful payload.
        media_type="application/problem+json",
        content=problem.model_dump(exclude_none=True),
    )


async def app_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Handle our own domain errors -- these are expected outcomes, not bugs."""
    assert isinstance(exc, AppError)

    # 4xx is the caller's problem (log at info); 5xx is ours (log at error).
    log = logger.error if exc.status_code >= 500 else logger.info
    log("app_error", code=exc.code, status=exc.status_code, detail=exc.message)

    return _problem_response(
        status_code=exc.status_code,
        title=exc.__class__.__name__.removesuffix("Error"),
        detail=exc.message,
        code=exc.code,
        meta=exc.details or None,
    )


async def validation_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Reshape FastAPI's 422 body into our Problem Details format.

    FastAPI's default validation body has its own bespoke shape. Passing it through
    would mean the frontend needs two error parsers. We flatten Pydantic's `loc`
    tuple into a dotted path (`body.address.city` -> `address.city`) because that is
    what maps onto a form field name.
    """
    assert isinstance(exc, RequestValidationError)

    field_errors = [
        FieldError(
            # Drop the leading "body"/"query"/"path" segment -- the client knows
            # where it sent the data.
            field=".".join(str(p) for p in error["loc"][1:]) or str(error["loc"][0]),
            message=error["msg"],
            type=error.get("type"),
        )
        for error in exc.errors()
    ]

    return _problem_response(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        title="Validation Failed",
        detail="One or more fields failed validation.",
        code="VALIDATION_ERROR",
        errors=field_errors,
    )


async def http_exception_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Catch HTTPExceptions raised by Starlette/FastAPI internals (404s, 405s).

    Without this, a request to an unknown path returns `{"detail": "Not Found"}`
    while every other error returns Problem Details -- an inconsistency the
    frontend would have to special-case.
    """
    assert isinstance(exc, StarletteHTTPException)
    return _problem_response(
        status_code=exc.status_code,
        title="HTTP Error",
        detail=str(exc.detail),
        code=f"HTTP_{exc.status_code}",
    )


async def integrity_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Turn a database constraint violation into a 409.

    A UNIQUE violation almost always means a genuine conflict (duplicate admission
    number, duplicate email). Services should pre-check and raise `ConflictError`
    with a helpful message; this handler is the safety net for the race where two
    concurrent requests both pass the pre-check.

    The driver's message is logged but never returned -- it contains the constraint
    name and often the offending values.
    """
    assert isinstance(exc, IntegrityError)
    logger.warning("integrity_error", error=str(exc.orig))
    return _problem_response(
        status_code=status.HTTP_409_CONFLICT,
        title="Conflict",
        detail="The operation conflicts with existing data.",
        code="INTEGRITY_ERROR",
    )


async def database_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, SQLAlchemyError)
    logger.exception("database_error")
    return _problem_response(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        title="Service Unavailable",
        detail="A database error occurred. Please retry shortly.",
        code="DATABASE_ERROR",
    )


async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    """Last resort. Anything reaching here is an unanticipated bug.

    `logger.exception` captures the full traceback for us. The client gets nothing
    but a generic message and the request id -- outside local development, where
    echoing the exception speeds up debugging considerably.
    """
    logger.exception("unhandled_exception", error_type=type(exc).__name__)
    settings = get_settings()
    detail = (
        f"{type(exc).__name__}: {exc}"
        if settings.DEBUG and not settings.is_production
        else "An unexpected error occurred. Please contact support with the request id."
    )
    return _problem_response(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        title="Internal Server Error",
        detail=detail,
        code="INTERNAL_ERROR",
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Wire all handlers. Order does not matter -- Starlette dispatches on the most
    specific registered exception class."""
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(IntegrityError, integrity_error_handler)
    app.add_exception_handler(SQLAlchemyError, database_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
