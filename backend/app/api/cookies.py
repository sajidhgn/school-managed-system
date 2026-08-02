"""Auth cookie transport (spec §4.1).

WHY THIS FILE EXISTS
    Setting a cookie correctly means getting five flags right at once, and getting
    any of them wrong fails in a way that is either invisible or catastrophic:

      * missing `httponly`  -> any XSS payload on the page can read the token
      * missing `secure`    -> the token crosses the network in clear text
      * wrong `samesite`    -> either CSRF exposure, or a cookie the browser
                               silently refuses to store
      * wrong `path`        -> the refresh token is sent on every request instead of
                               only the one endpoint that needs it
      * wrong `max_age`     -> a session that dies early or outlives its token

    One module owns all five so a new endpoint cannot get them subtly different.

RESPONSIBILITY
    Attach and clear the access/refresh cookies. Nothing else.

INTERACTIONS
    Called by the auth router on login, context switch, refresh and logout.

=============================================================================
WHY THE REFRESH COOKIE IS PATH-SCOPED AND THE ACCESS COOKIE IS NOT
=============================================================================
    The access token is needed by every API call, so it is scoped to `/`.

    The refresh token is needed by exactly one endpoint. Scoping it to that path
    means the browser does not attach the long-lived credential to the hundreds of
    ordinary requests that have no use for it -- so it appears in far fewer logs,
    proxies and crash reports, and an endpoint that accidentally echoes its request
    headers cannot leak it.

    This is defence in depth, not a substitute for `httpOnly`. It narrows the blast
    radius of mistakes elsewhere.
"""

from __future__ import annotations

from fastapi import Response

from app.core.config import Settings

# The single endpoint permitted to receive the refresh cookie. Must match the route
# mounted in `modules/auth/router.py`; a mismatch means refresh silently 401s
# because the browser never sends the cookie.
REFRESH_COOKIE_PATH = "/api/v1/auth"


def set_auth_cookies(
    response: Response,
    *,
    access_token: str,
    refresh_token: str,
    settings: Settings,
) -> None:
    """Attach both auth cookies to `response`."""
    response.set_cookie(
        key=settings.ACCESS_COOKIE_NAME,
        value=access_token,
        max_age=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN or None,
        path="/",
    )
    response.set_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        value=refresh_token,
        max_age=settings.REFRESH_TOKEN_EXPIRE_DAYS * 24 * 60 * 60,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN or None,
        path=REFRESH_COOKIE_PATH,
    )


def clear_auth_cookies(response: Response, *, settings: Settings) -> None:
    """Remove both auth cookies.

    The `domain` and `path` MUST match what was used to set them. A browser treats
    (name, domain, path) as the identity of a cookie, so deleting with a different
    path leaves the original in place -- and the user stays logged in after clicking
    log out, which is the kind of bug that only shows up in production.
    """
    response.delete_cookie(
        key=settings.ACCESS_COOKIE_NAME,
        domain=settings.COOKIE_DOMAIN or None,
        path="/",
    )
    response.delete_cookie(
        key=settings.REFRESH_COOKIE_NAME,
        domain=settings.COOKIE_DOMAIN or None,
        path=REFRESH_COOKIE_PATH,
    )
