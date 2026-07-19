"""Structured logging configuration.

WHY THIS FILE EXISTS
    Plain `print` and unstructured `logging` produce output you cannot query. In a
    multi-tenant SaaS the first question during an incident is always "which school,
    which request?" -- so every log line must carry `request_id` and `school_id`
    automatically, without the caller remembering to pass them.

RESPONSIBILITY
    Configure structlog once at startup, and install a processor that injects the
    ambient request context into every event.

INTERACTIONS
    * Called once from `main.py` during lifespan startup.
    * Reads `core.context` for the request id / tenant.
    * Every module obtains a logger via `get_logger(__name__)`.

DESIGN NOTE
    Console renderer locally (readable), JSON in staging/production (ingestible by
    CloudWatch / Loki / Datadog). One switch: `LOG_JSON`.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog

from app.core.config import Settings
from app.core.context import get_context


def _inject_request_context(
    _logger: Any, _method: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """structlog processor: stamp every event with the ambient request context.

    This is why `core/context.py` exists. Without it, correlating a stack trace
    to a tenant means grepping by timestamp and hoping.
    """
    ctx = get_context()
    if ctx.request_id:
        event_dict["request_id"] = ctx.request_id
    if ctx.school_id:
        event_dict["school_id"] = str(ctx.school_id)
    if ctx.user_id:
        event_dict["user_id"] = str(ctx.user_id)
    return event_dict


def configure_logging(settings: Settings) -> None:
    """Install the logging configuration. Idempotent; call once at startup."""
    # Route stdlib logging (uvicorn, sqlalchemy) through the same handler so the
    # output format is uniform regardless of who emitted the line.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=getattr(logging, settings.LOG_LEVEL),
        force=True,
    )

    shared_processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        _inject_request_context,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    renderer: Any = (
        structlog.processors.JSONRenderer()
        if settings.LOG_JSON
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.LOG_LEVEL)),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # SQLAlchemy's engine logger is extremely chatty at INFO; DB_ECHO controls it.
    logging.getLogger("sqlalchemy.engine").setLevel(
        logging.INFO if settings.DB_ECHO else logging.WARNING
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Standard accessor. Use `logger = get_logger(__name__)` at module scope."""
    return structlog.get_logger(name)  # type: ignore[no-any-return]
