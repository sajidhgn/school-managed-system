"""Keep every API response out of search engines.

WHY THIS FILE EXISTS
    The API is reached through the Next.js BFF and is never meant to be public, but
    a misconfigured proxy, a leaked link to a challan PDF or an exposed port is
    enough for a crawler to find it. `X-Robots-Tag` is the only noindex signal that
    works for JSON, PDFs and images alike, so it goes on every response,
    unconditionally: there is no environment in which an API should be indexed.

WHY A PURE ASGI MIDDLEWARE
    It only has to touch the response headers, so it wraps `send` instead of
    buffering the response the way `BaseHTTPMiddleware` does. That keeps streamed
    downloads streaming, and it tags error responses produced further in too.
"""

from __future__ import annotations

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

ROBOTS_HEADER = "X-Robots-Tag"
ROBOTS_VALUE = "noindex, nofollow"


class NoIndexMiddleware:
    """Add `X-Robots-Tag: noindex, nofollow` to every HTTP response."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_robots_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)[ROBOTS_HEADER] = ROBOTS_VALUE
            await send(message)

        await self.app(scope, receive, send_with_robots_header)
