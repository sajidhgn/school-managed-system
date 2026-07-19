"""Request context + access-log middleware.

WHY THIS FILE EXISTS
    Two things must happen at the very edge of every request, before any route code
    runs: assign a correlation id, and start the timer for the access log. A
    middleware is the correct place because it wraps *every* request including ones
    that never reach a route (404s, validation failures).

RESPONSIBILITY
    * Assign or propagate `X-Request-ID`.
    * Publish it into the ContextVar so logs and error bodies pick it up.
    * Emit one structured access-log line per request with its duration.
    * Reset the ContextVar afterwards so no state leaks between requests.

INTERACTIONS
    Registered in `main.py`. Writes to `core.context`; read by `core.logging` and
    `api/errors.py`.

WHY NOT A `@app.middleware("http")` DECORATOR
    A `BaseHTTPMiddleware` subclass is explicit, unit-testable, and avoids the
    decorator form's known interactions with streaming responses and background
    tasks.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from uuid import uuid4

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.context import reset_request_id, set_request_id
from app.core.logging import get_logger

logger = get_logger("api.access")

REQUEST_ID_HEADER = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Correlation id + access logging."""

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Honour an inbound id if a gateway or the Next.js frontend already
        # assigned one -- that is what makes a trace span multiple services.
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid4())
        token = set_request_id(request_id)

        # Also expose it on request.state for code that has a Request but not the
        # ContextVar (e.g. a third-party integration).
        request.state.request_id = request_id

        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Log the failed request here so the access log has an entry even when
            # the exception handler produces the response. Re-raise: turning an
            # exception into a response is the handler's job, not ours.
            logger.warning(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round((time.perf_counter() - start) * 1000, 2),
            )
            raise
        else:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            response.headers[REQUEST_ID_HEADER] = request_id
            # Server-Timing lets browser devtools chart backend latency alongside
            # network time -- free performance visibility for the frontend team.
            response.headers["Server-Timing"] = f"app;dur={duration_ms}"

            logger.info(
                "request_completed",
                method=request.method,
                path=request.url.path,
                status_code=response.status_code,
                duration_ms=duration_ms,
            )
            return response
        finally:
            # Always reset. ContextVars are per-task, but tasks are reused;
            # leaving a stale id set would mislabel a later log line.
            reset_request_id(token)
