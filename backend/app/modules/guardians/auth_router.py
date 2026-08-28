"""Parent-portal authentication endpoints -- unauthenticated by design.

WHY THIS ROUTER IS SEPARATE FROM `router.py`
    `router.py` is staff-only and every route on it carries a permission. These three
    routes carry NONE, because the caller is a parent who has not proved anything yet.
    Mixing the two postures in one file is how an endpoint ends up in the
    unauthenticated set by accident, which is the failure mode that matters most here.

THE FLOW, IN THE ORDER A PARENT WALKS IT
    1. POST /guardian/auth/request-code   -> an SMS, and a response that says nothing
                                             about whether the number is known.
    2. POST /guardian/auth/verify         -> either a full session, a picker, or
                                             `no_access`.
    3. POST /guardian/auth/context        -> only when step 2 returned a picker.
    4. POST /guardian/auth/refresh        -> rotation, with reuse detection.
    5. POST /guardian/auth/logout

WHY THESE ROUTES SET COOKIES DIRECTLY
    Tokens never reach a browser in a response body. The only way out is `Set-Cookie`,
    and FastAPI hands a handler the response object when it declares one -- which is
    what lets a handler both return a typed model and attach cookies.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response

from app.api.deps import (
    ClientIp,
    GuardianClaims,
    PublicDbSession,
    SettingsDep,
)
from app.common.sms import SmsSender, build_sms_sender
from app.core.config import Settings
from app.core.exceptions import AuthenticationError, NotFoundError
from app.db.session import bind_tenant
from app.modules.guardians.auth_service import GuardianAuthService, IssuedGuardianTokens
from app.modules.guardians.schemas import (
    GuardianContextRequest,
    GuardianLoginResponse,
    GuardianMessageResponse,
    GuardianTokenPair,
    OtpRequest,
    OtpRequestResponse,
    OtpVerifyRequest,
)

router = APIRouter()

# The single path permitted to receive the portal refresh cookie. Narrower than `/`
# for the reason `api/cookies.py` gives: the long-lived credential should not be
# attached to the hundreds of ordinary portal requests that have no use for it.
GUARDIAN_REFRESH_PATH = "/api/v1/guardian/auth"


def get_sms_dispatcher(settings: SettingsDep) -> SmsSender:
    """The outbound SMS transport, as a dependency.

    A dependency rather than a module-level singleton so the integration tests can
    override it with a capturing fake and read the code the service would have texted.
    Without that seam, testing this flow would need an SMS account.
    """
    return build_sms_sender(settings)


SmsDispatcher = Annotated[SmsSender, Depends(get_sms_dispatcher)]


def _wants_body_tokens(transport: str | None) -> bool:
    return (transport or "").lower() == "body"


def _set_guardian_cookies(
    response: Response,
    *,
    settings: Settings,
    access_token: str,
    refresh_token: str | None = None,
    access_max_age: int | None = None,
) -> None:
    """Attach the portal cookies.

    Distinct names from the staff cookies (see the settings that define them): a
    teacher who is also a parent holds both sessions in one browser, and sharing a
    name would make signing into the portal silently sign them out of their job.
    """
    response.set_cookie(
        key=settings.GUARDIAN_ACCESS_COOKIE_NAME,
        value=access_token,
        max_age=access_max_age or settings.GUARDIAN_ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite=settings.COOKIE_SAMESITE,
        domain=settings.COOKIE_DOMAIN or None,
        path="/",
    )
    if refresh_token is not None:
        response.set_cookie(
            key=settings.GUARDIAN_REFRESH_COOKIE_NAME,
            value=refresh_token,
            max_age=settings.GUARDIAN_SESSION_EXPIRE_DAYS * 24 * 60 * 60,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE,
            domain=settings.COOKIE_DOMAIN or None,
            path=GUARDIAN_REFRESH_PATH,
        )


def _clear_guardian_cookies(response: Response, *, settings: Settings) -> None:
    """Domain and path MUST match what set them, or the browser keeps the original."""
    response.delete_cookie(
        key=settings.GUARDIAN_ACCESS_COOKIE_NAME,
        domain=settings.COOKIE_DOMAIN or None,
        path="/",
    )
    response.delete_cookie(
        key=settings.GUARDIAN_REFRESH_COOKIE_NAME,
        domain=settings.COOKIE_DOMAIN or None,
        path=GUARDIAN_REFRESH_PATH,
    )


def _tokens_in_body(
    tokens: IssuedGuardianTokens, *, transport: str | None
) -> GuardianTokenPair | None:
    if not _wants_body_tokens(transport):
        return None
    return GuardianTokenPair(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


def _require_portal_enabled(settings: Settings) -> None:
    """The deployment-level kill switch.

    A 404, not a 403: when a group has not launched the portal, the honest answer is
    that this surface does not exist here. A 403 would advertise a feature the school
    has deliberately not turned on and generate support calls asking for access to it.
    """
    if not settings.GUARDIAN_PORTAL_ENABLED:
        raise NotFoundError("The parent portal is not enabled.", code="GUARDIAN_PORTAL_DISABLED")


# ---------------------------------------------------------------------------
# 1. Request a code
# ---------------------------------------------------------------------------


@router.post(
    "/request-code",
    response_model=OtpRequestResponse,
    summary="Send a one-time login code by SMS",
)
async def request_code(
    payload: OtpRequest,
    session: PublicDbSession,
    settings: SettingsDep,
    sms: SmsDispatcher,
    ip: ClientIp,
) -> OtpRequestResponse:
    """Text a code to the number, if it belongs to a registered guardian.

    THE RESPONSE IS IDENTICAL EITHER WAY. See the enumeration note in
    `auth_service.py`: an honest "no such guardian" would turn this endpoint into a
    way to ask whether a specific person has a child at a school on this platform.
    """
    _require_portal_enabled(settings)
    masked, ttl, retry_after = await GuardianAuthService(session, settings, sms).request_code(
        payload.phone, ip=ip
    )
    return OtpRequestResponse(
        message="If that number is registered, a code has been sent to it.",
        phone_masked=masked,
        expires_in_seconds=ttl,
        retry_after_seconds=retry_after,
    )


# ---------------------------------------------------------------------------
# 2. Verify it
# ---------------------------------------------------------------------------


@router.post(
    "/verify",
    response_model=GuardianLoginResponse,
    summary="Exchange a code for a portal session",
)
async def verify_code(
    payload: OtpVerifyRequest,
    request: Request,
    response: Response,
    session: PublicDbSession,
    settings: SettingsDep,
    ip: ClientIp,
    transport: Annotated[str | None, Header(alias="X-Token-Transport")] = None,
) -> GuardianLoginResponse:
    """Three outcomes -- see `GuardianLoginResponse`.

    The single-context path issues a full session immediately. Several contexts get a
    five-minute continuation token instead, which can do exactly one thing: choose.
    """
    _require_portal_enabled(settings)
    service = GuardianAuthService(session, settings)
    user_agent = request.headers.get("User-Agent", "")[:400]

    try:
        verified = await service.verify_code(payload.phone, payload.code)
    except AuthenticationError:
        # =====================================================================
        # COMMIT THE ATTEMPT COUNTER BEFORE RE-RAISING
        # =====================================================================
        #   `get_db` rolls the transaction back on any exception, which is exactly
        #   right for business writes -- a failed request must leave no trace.
        #
        #   The OTP attempt counter is the one write that MUST survive a failed
        #   request, and it is the whole security model of a 6-digit code. Rolled
        #   back, `attempts` and `failed_otp_count` reset to zero on every guess, the
        #   cap is never reached, and 10^6 codes fall to an attacker in minutes while
        #   the code that was supposed to stop them reads as correct.
        #
        #   The staff login endpoint commits its lockout counter for exactly this
        #   reason; see the note there. Safe for the same reason: the only writes
        #   performed so far are the counter increments and the code's consumption.
        await session.commit()
        raise

    if not verified.contexts:
        # The handset is genuinely registered, but no school currently exposes records
        # to it. Distinguished from a wrong code ON PURPOSE: this caller has already
        # proved control of the number, so there is nothing left to enumerate, and
        # making them retype a code that will never work is a support call.
        return GuardianLoginResponse(status="no_access")

    if len(verified.contexts) > 1:
        token, expires_in = await service.issue_context_selection(
            verified.identity, ip=ip, user_agent=user_agent
        )
        _set_guardian_cookies(
            response, settings=settings, access_token=token, access_max_age=expires_in
        )
        return GuardianLoginResponse(
            status="select_required",
            contexts=await service.describe_contexts(verified.contexts),
            tokens=GuardianTokenPair(access_token=token, expires_in=expires_in)
            if _wants_body_tokens(transport)
            else None,
        )

    guardian = verified.contexts[0]
    tokens = await service.issue_session(
        identity=verified.identity, guardian=guardian, ip=ip, user_agent=user_agent
    )
    _set_guardian_cookies(
        response,
        settings=settings,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
    )
    # The profile read needs the tenant bound: `organizations` is RLS-protected and
    # this request arrived with no organization in context.
    await bind_tenant(session, guardian.organization_id)
    return GuardianLoginResponse(
        status="authenticated",
        guardian=await service.profile(verified.identity, guardian),
        tokens=_tokens_in_body(tokens, transport=transport),
    )


# ---------------------------------------------------------------------------
# 3. Choose an organization
# ---------------------------------------------------------------------------


@router.post(
    "/context",
    response_model=GuardianLoginResponse,
    summary="Choose which school group to open",
)
async def select_context(
    payload: GuardianContextRequest,
    request: Request,
    response: Response,
    claims: GuardianClaims,
    session: PublicDbSession,
    settings: SettingsDep,
    ip: ClientIp,
    transport: Annotated[str | None, Header(alias="X-Token-Transport")] = None,
) -> GuardianLoginResponse:
    """Upgrade a continuation token into a full portal session.

    Accepts EITHER posture: the five-minute continuation from `/verify`, and an
    already-authenticated portal session switching between school groups. The second
    is the same "switch context" affordance staff have, and refusing it would make a
    parent with children in two groups sign out and back in to see the other one.
    """
    _require_portal_enabled(settings)
    service = GuardianAuthService(session, settings)
    user_agent = request.headers.get("User-Agent", "")[:400]

    identity, guardian = await service.select_context(
        identity_id=claims.user_id,
        guardian_id=payload.guardian_id,
        ip=ip,
        user_agent=user_agent,
    )

    # The continuation session dies here rather than lingering for its full five
    # minutes: it has done the one thing it exists for.
    await service.revoke_session(claims.session_id, reason="context_selected")

    tokens = await service.issue_session(
        identity=identity, guardian=guardian, ip=ip, user_agent=user_agent
    )
    _set_guardian_cookies(
        response,
        settings=settings,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
    )
    await bind_tenant(session, guardian.organization_id)
    return GuardianLoginResponse(
        status="authenticated",
        guardian=await service.profile(identity, guardian),
        tokens=_tokens_in_body(tokens, transport=transport),
    )


# ---------------------------------------------------------------------------
# 4. Refresh
# ---------------------------------------------------------------------------


@router.post(
    "/refresh",
    response_model=GuardianMessageResponse,
    summary="Rotate a portal session",
)
async def refresh(
    request: Request,
    response: Response,
    session: PublicDbSession,
    settings: SettingsDep,
    ip: ClientIp,
    transport: Annotated[str | None, Header(alias="X-Token-Transport")] = None,
    refresh_header: Annotated[str | None, Header(alias="X-Refresh-Token")] = None,
) -> GuardianMessageResponse:
    """Exchange a refresh token for a new pair, revoking the presented one.

    Reads the cookie first and the header second, mirroring the staff endpoint: a
    browser has no way to send the header, and a non-browser client has no cookie jar.
    """
    _require_portal_enabled(settings)
    raw = request.cookies.get(settings.GUARDIAN_REFRESH_COOKIE_NAME) or refresh_header
    if not raw:
        raise AuthenticationError("Missing refresh token.", code="TOKEN_MISSING")

    tokens = await GuardianAuthService(session, settings).refresh_session(
        raw, ip=ip, user_agent=request.headers.get("User-Agent", "")[:400]
    )
    _set_guardian_cookies(
        response,
        settings=settings,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
    )
    if _wants_body_tokens(transport):
        # Headers rather than a body, exactly as the staff endpoint does, so the
        # documented response model stays a plain message for every caller.
        response.headers["X-Access-Token"] = tokens.access_token
        response.headers["X-Refresh-Token"] = tokens.refresh_token
    return GuardianMessageResponse(message="Session refreshed.")


# ---------------------------------------------------------------------------
# 5. Logout
# ---------------------------------------------------------------------------


@router.post(
    "/logout",
    response_model=GuardianMessageResponse,
    summary="End the portal session",
)
async def logout(
    response: Response,
    claims: GuardianClaims,
    session: PublicDbSession,
    settings: SettingsDep,
    all_devices: bool = False,
) -> GuardianMessageResponse:
    """Revoke this session, or every session for this handset.

    `all_devices` matters more here than on the staff surface: a parent's phone is
    lent, lost and resold, and "sign out everywhere" is the only control they have
    over a session on a device they no longer hold.
    """
    service = GuardianAuthService(session, settings)
    if all_devices:
        await service.revoke_all(claims.user_id)
    else:
        await service.revoke_session(claims.session_id)
    _clear_guardian_cookies(response, settings=settings)
    return GuardianMessageResponse(message="Signed out.")
