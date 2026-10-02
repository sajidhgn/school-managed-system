"""Authentication routes (spec §8 "Auth").

WHY THIS FILE EXISTS
    The HTTP boundary for identity. It translates requests into service calls and
    service results into responses + cookies, and does nothing else -- no business
    rules live here, so the same flows remain reachable from the CLI and tests.

RESPONSIBILITY
    Route definitions, cookie handling, and response assembly.

INTERACTIONS
    * `modules/auth/service.py` for every flow.
    * `api/cookies.py` for the httpOnly transport.
    * `api/deps.py` for the authenticated routes (`/me`, `/context`, `/logout`).

=============================================================================
WHY THESE ROUTES TAKE `Response` AND SET COOKIES DIRECTLY
=============================================================================
    Tokens never appear in a response body for a browser (spec §4.1), so the only
    way out is a `Set-Cookie` header. FastAPI gives a handler the response object
    when it declares one as a parameter, which is what lets a handler both return a
    typed model AND attach cookies.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.api.cookies import clear_auth_cookies, set_access_cookie, set_auth_cookies
from app.api.deps import (
    ClientIp,
    CurrentAuth,
    CurrentClaims,
    DbSession,
    PublicDbSession,
    SettingsDep,
)
from app.common.audit import AuditAction, record_audit
from app.common.email.sender import EmailSender, build_email_sender
from app.core.config import Settings
from app.core.context import set_organization_id, set_school_id
from app.core.exceptions import AuthenticationError
from app.core.rate_limit import enforce_rate_limit
from app.db.session import bind_tenant
from app.modules.auth.models import User
from app.modules.auth.schemas import (
    ContextSwitchRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LoginResponse,
    MembershipSummary,
    MeResponse,
    MessageResponse,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    ResetPasswordRequest,
    TokenPair,
    VerifyEmailRequest,
)
from app.modules.auth.service import AuthService, IssuedTokens
from app.modules.billing.trial_retention import trial_deletion_date
from app.modules.rbac.models import Membership
from app.modules.tenancy.models import Organization, School

router = APIRouter()


def get_email_dispatcher(settings: SettingsDep) -> EmailSender:
    """The outbound mail transport, as a dependency.

    A dependency rather than a module-level singleton so the integration tests can
    override it with a capturing fake and read the links the service would have
    emailed. Without that seam, testing the verification and invitation flows would
    require an SMTP server.
    """
    return build_email_sender(settings)


EmailDispatcher = Annotated[EmailSender, Depends(get_email_dispatcher)]


def _service(
    session: PublicDbSession, settings: Settings, sender: EmailSender | None = None
) -> AuthService:
    return AuthService(session, settings, sender)


def _wants_body_tokens(transport: str | None) -> bool:
    """Whether to return tokens in JSON instead of only as cookies.

    Opt-in via `X-Token-Transport: body`, for non-browser clients. See `TokenPair`'s
    docstring for why this is not a hole a malicious page can exploit.
    """
    return (transport or "").lower() == "body"


# ---------------------------------------------------------------------------
# Registration & verification
# ---------------------------------------------------------------------------


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(
    payload: RegisterRequest,
    session: PublicDbSession,
    settings: SettingsDep,
    sender: EmailDispatcher,
    ip: ClientIp,
    request: Request,
) -> RegisterResponse:
    """Create an account and its organization (spec §4.3B).

    Returns 201 with NO tokens: login is blocked until the emailed link is followed.
    """
    user, organization = await _service(session, settings, sender).register(
        full_name=payload.full_name,
        email=payload.email,
        password=payload.password,
        organization_name=payload.organization_name,
        country=payload.country,
        plan_code=payload.plan_code,
        billing_cycle=payload.billing_cycle,
        ip=ip,
        user_agent=request.headers.get("User-Agent"),
    )
    return RegisterResponse(
        user_id=user.id,
        organization_id=organization.id,
        email=user.email,
        verification_required=True,
        message="Account created. Check your email to verify your address.",
    )


@router.post("/verify-email", response_model=MessageResponse)
async def verify_email(
    payload: VerifyEmailRequest,
    session: PublicDbSession,
    settings: SettingsDep,
) -> MessageResponse:
    """Consume a verification link and activate the account."""
    await _service(session, settings).verify_email(payload.token)
    return MessageResponse(message="Email verified. You can now sign in.")


@router.post("/resend-verification", response_model=MessageResponse)
async def resend_verification(
    payload: ResendVerificationRequest,
    session: PublicDbSession,
    settings: SettingsDep,
    sender: EmailDispatcher,
    ip: ClientIp,
) -> MessageResponse:
    """Re-send the verification link.

    Always the same response, whether or not the address exists or is already
    verified -- otherwise this becomes a cheap way to test which addresses are
    registered.
    """
    await enforce_rate_limit(
        "verification_resend",
        f"{ip or 'unknown'}:{payload.email}",
        limit=settings.AUTH_RATE_LIMIT,
        window_seconds=settings.AUTH_RATE_WINDOW_SECONDS,
    )
    service = _service(session, settings, sender)
    user = await service._find_user_by_email(payload.email)
    if user is not None and not user.is_email_verified:
        await service._send_verification_email(user)
    return MessageResponse(message="If that address needs verification, we have sent a new link.")


# ---------------------------------------------------------------------------
# Login & context
# ---------------------------------------------------------------------------


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    response: Response,
    session: PublicDbSession,
    settings: SettingsDep,
    ip: ClientIp,
    request: Request,
    x_token_transport: Annotated[str | None, Header()] = None,
) -> LoginResponse:
    """Authenticate and, if the context is unambiguous, issue tokens (spec §4.3D).

    A user with several memberships gets `select_required: true` and NO access
    cookie; they must call `POST /auth/context` to choose. See `LoginResponse`.
    """
    service = _service(session, settings)
    user_agent = request.headers.get("User-Agent")
    await enforce_rate_limit(
        "tenant_login",
        f"{ip or 'unknown'}:{payload.email}",
        limit=settings.AUTH_RATE_LIMIT,
        window_seconds=settings.AUTH_RATE_WINDOW_SECONDS,
    )

    try:
        user = await service.authenticate(
            email=payload.email,
            password=payload.password,
            ip=ip,
            user_agent=user_agent,
        )
    except AuthenticationError:
        # =====================================================================
        # COMMIT THE FAILED-LOGIN COUNTER BEFORE RE-RAISING
        # =====================================================================
        #   `get_db` rolls the transaction back on any exception, which is exactly
        #   right for business writes -- a failed request must leave no trace.
        #
        #   But the lockout counter is the one write that MUST survive a failed
        #   request. Rolled back, `failed_login_count` resets to zero on every
        #   attempt, the threshold is never reached, and the account lockout in spec
        #   §4.4 silently does nothing at all. An attacker could guess forever while
        #   the code that was supposed to stop them looks correct in review.
        #
        #   Committing here is safe: the only writes performed so far are the counter
        #   increment and the audit row, both of which describe the failure itself.
        await session.commit()
        raise

    memberships = await service.list_memberships(user.id)
    selected = service.pick_default_membership(memberships)

    result = LoginResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        memberships=memberships,
        select_required=selected is None,
        active_membership_id=selected.membership_id if selected else None,
    )

    if selected is None:
        continuation = await service.issue_context_selection(
            user=user, ip=ip, user_agent=user_agent
        )
        set_access_cookie(
            response,
            access_token=continuation.access_token,
            settings=settings,
            max_age=continuation.expires_in,
        )
        if _wants_body_tokens(x_token_transport):
            response.headers["X-Access-Token"] = continuation.access_token
        return result

    membership = await service.resolve_membership(
        user_id=user.id, membership_id=selected.membership_id
    )
    tokens = await service.issue_session(
        user=user, membership=membership, ip=ip, user_agent=user_agent
    )
    set_auth_cookies(
        response,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        settings=settings,
    )

    # BIND BEFORE THE AUDIT WRITE. Login begins with no tenant -- discovering which
    # organizations this person belongs to is the point of the call -- and the
    # membership lookups above deliberately clear the GUCs again when they finish, so
    # a cross-tenant read cannot leak into the rest of the request. That leaves the
    # session unbound at exactly the moment the audit row needs an organization, and
    # the `WITH CHECK` policy on `audit_logs` refuses it.
    #
    # Now that the membership is resolved, the tenant is known and proven: the user
    # authenticated with a password and the membership was verified to be theirs.
    await bind_tenant(session, membership.organization_id, school_id=membership.school_id)
    set_organization_id(membership.organization_id)
    set_school_id(membership.school_id)

    await record_audit(
        session,
        organization_id=membership.organization_id,
        school_id=membership.school_id,
        action=AuditAction.USER_LOGGED_IN,
        actor_user_id=user.id,
        actor_membership_id=membership.id,
        ip=ip,
        user_agent=user_agent,
    )

    if _wants_body_tokens(x_token_transport):
        _attach_body_tokens(response, tokens, settings)
    return result


@router.post("/context", response_model=MembershipSummary)
async def switch_context(
    payload: ContextSwitchRequest,
    response: Response,
    claims: CurrentClaims,
    session: DbSession,
    settings: SettingsDep,
    ip: ClientIp,
    request: Request,
    x_token_transport: Annotated[str | None, Header()] = None,
) -> MembershipSummary:
    """Switch the active membership and re-issue tokens (spec §4.3E).

    Deliberately reachable with a token that has NO active membership -- that is the
    state a multi-membership user is in immediately after login, and it is the only
    endpoint that can move them out of it.
    """
    service = _service(session, settings)
    user_agent = request.headers.get("User-Agent")

    if claims.is_platform:
        raise AuthenticationError("Wrong token type.", code="WRONG_TOKEN_TYPE")

    membership = await service.resolve_membership(
        user_id=claims.user_id, membership_id=payload.membership_id
    )
    user = await session.get(User, claims.user_id)
    if user is None:
        raise AuthenticationError("Account no longer exists.", code="USER_NOT_FOUND")

    tokens = await service.switch_context(
        user=user,
        membership=membership,
        current_session_id=claims.session_id,
        ip=ip,
        user_agent=user_agent,
    )
    set_auth_cookies(
        response,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        settings=settings,
    )
    if _wants_body_tokens(x_token_transport):
        _attach_body_tokens(response, tokens, settings)

    school = await session.get(School, membership.school_id) if membership.school_id else None
    organization = await session.get(Organization, membership.organization_id)
    return MembershipSummary(
        membership_id=membership.id,
        organization_id=membership.organization_id,
        organization_name=organization.name if organization else "",
        school_id=membership.school_id,
        school_name=school.name if school else None,
        role_code=membership.role.code,
        role_name=membership.role.name,
        is_primary=membership.is_primary,
        is_org_level=membership.school_id is None,
    )


@router.post("/refresh", response_model=MessageResponse)
async def refresh(
    request: Request,
    response: Response,
    session: PublicDbSession,
    settings: SettingsDep,
    ip: ClientIp,
    x_token_transport: Annotated[str | None, Header()] = None,
) -> MessageResponse:
    """Rotate the refresh token, detecting reuse (spec §4.1).

    Reads the token from the cookie, or from `X-Refresh-Token` for non-browser
    clients that have no cookie jar.
    """
    # Header FIRST, then cookie -- the same precedence `_extract_token` uses for
    # access tokens. An explicit credential must always beat an ambient one:
    # otherwise a non-browser client that also happens to hold a cookie would
    # silently refresh the wrong session, and the token it actually sent would be
    # ignored without any error.
    raw = request.headers.get("X-Refresh-Token") or request.cookies.get(
        settings.REFRESH_COOKIE_NAME
    )
    if not raw:
        raise AuthenticationError("No refresh token supplied.", code="REFRESH_TOKEN_MISSING")

    try:
        tokens = await _service(session, settings).refresh_session(
            raw, ip=ip, user_agent=request.headers.get("User-Agent")
        )
    except AuthenticationError:
        # =====================================================================
        # COMMIT THE REVOCATIONS BEFORE RE-RAISING
        # =====================================================================
        #   Same reasoning as the login handler, and here the stakes are higher.
        #
        #   When reuse is detected the service revokes the ENTIRE token family --
        #   which is the whole defence against a stolen refresh token. But
        #   `get_db` rolls back on any exception, so raising immediately after would
        #   undo the revocation: the attacker's freshly rotated token would survive,
        #   the log line would claim the family was revoked, and the mechanism would
        #   be decorative.
        #
        #   The only writes on a failed refresh are revocations, so committing them
        #   is exactly right.
        await session.commit()
        raise
    set_auth_cookies(
        response,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        settings=settings,
    )
    if _wants_body_tokens(x_token_transport):
        _attach_body_tokens(response, tokens, settings)
    return MessageResponse(message="Session refreshed.")


@router.post("/logout", response_model=MessageResponse)
async def logout(
    response: Response,
    claims: CurrentClaims,
    session: DbSession,
    settings: SettingsDep,
    request: Request,
    ip: ClientIp,
) -> MessageResponse:
    """Revoke this session and clear the cookies."""
    await _service(session, settings).revoke_session(claims.session_id, reason="logout")
    if claims.organization_id is not None:
        await record_audit(
            session,
            organization_id=claims.organization_id,
            school_id=claims.school_id,
            action=AuditAction.USER_LOGGED_OUT,
            actor_user_id=claims.user_id,
            actor_membership_id=claims.membership_id,
            entity_type="session",
            entity_id=claims.session_id,
            ip=ip,
            user_agent=request.headers.get("User-Agent"),
        )
    clear_auth_cookies(response, settings=settings)
    return MessageResponse(message="Signed out.")


@router.post("/logout-all", response_model=MessageResponse)
async def logout_all(
    response: Response,
    claims: CurrentClaims,
    session: DbSession,
    settings: SettingsDep,
    request: Request,
    ip: ClientIp,
) -> MessageResponse:
    """Revoke every session for this user, on every device (spec §4.3F)."""
    if claims.is_context_selection:
        raise AuthenticationError(
            "Choose an organization or school before managing sessions.",
            code="CONTEXT_SELECTION_REQUIRED",
        )
    await _service(session, settings).revoke_all_sessions(claims.user_id, reason="logout_all")
    assert claims.organization_id is not None
    await record_audit(
        session,
        organization_id=claims.organization_id,
        school_id=claims.school_id,
        action=AuditAction.USER_LOGGED_OUT_ALL,
        actor_user_id=claims.user_id,
        actor_membership_id=claims.membership_id,
        ip=ip,
        user_agent=request.headers.get("User-Agent"),
    )
    clear_auth_cookies(response, settings=settings)
    return MessageResponse(message="Signed out on all devices.")


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(
    payload: ForgotPasswordRequest,
    session: PublicDbSession,
    settings: SettingsDep,
    sender: EmailDispatcher,
    ip: ClientIp,
) -> MessageResponse:
    """Send a reset link. Identical response for known and unknown addresses."""
    await enforce_rate_limit(
        "password_reset",
        f"{ip or 'unknown'}:{payload.email}",
        limit=settings.AUTH_RATE_LIMIT,
        window_seconds=settings.AUTH_RATE_WINDOW_SECONDS,
    )
    await _service(session, settings, sender).request_password_reset(payload.email)
    return MessageResponse(
        message="If an account exists for that address, we have sent a reset link."
    )


@router.post("/reset-password", response_model=MessageResponse)
async def reset_password(
    payload: ResetPasswordRequest,
    response: Response,
    session: PublicDbSession,
    settings: SettingsDep,
) -> MessageResponse:
    """Set a new password and revoke every existing session."""
    await _service(session, settings).reset_password(
        raw_token=payload.token, new_password=payload.password
    )
    # The caller may hold cookies for a session this reset just revoked. Clearing
    # them avoids a confusing state where the app appears logged in but every
    # request 401s.
    clear_auth_cookies(response, settings=settings)
    return MessageResponse(message="Password updated. Please sign in.")


# ---------------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------------


@router.get("/me", response_model=MeResponse)
async def me(ctx: CurrentAuth, session: DbSession, settings: SettingsDep) -> MeResponse:
    """The caller's identity, contexts and resolved permissions (spec §8).

    One call, because the app shell needs all of it before it can render anything:
    the nav depends on permissions, the header on the active school, the switcher on
    the membership list.
    """
    user = await session.get(User, ctx.user_id)
    if user is None:
        raise AuthenticationError("Account no longer exists.", code="USER_NOT_FOUND")

    memberships = await AuthService(session, settings).list_memberships(ctx.user_id)

    membership = (
        await session.execute(
            select(Membership)
            .options(joinedload(Membership.organization), joinedload(Membership.school))
            .where(Membership.id == ctx.membership_id)
        )
    ).scalar_one_or_none()

    permissions = sorted(ctx.permissions)
    read_only = ctx.organization_status == "suspended"
    scheduled_deletion_at = None
    if read_only:
        permissions = [code for code in permissions if _usable_while_read_only(code)]
        scheduled_deletion_at = await trial_deletion_date(session, ctx.organization_id, settings)

    return MeResponse(
        user_id=user.id,
        email=user.email,
        full_name=user.full_name,
        avatar_url=user.avatar_url,
        locale=user.locale,
        memberships=memberships,
        active_membership_id=ctx.membership_id,
        organization_id=ctx.organization_id,
        organization_name=membership.organization.name if membership else None,
        organization_status=ctx.organization_status,
        school_id=ctx.school_id,
        school_name=membership.school.name if membership and membership.school else None,
        role_code=ctx.role_code,
        permissions=permissions,
        read_only=read_only,
        trial_expired=scheduled_deletion_at is not None,
        scheduled_deletion_at=scheduled_deletion_at,
    )


# Writes a suspended organization may still make. `billing:manage` is the only one:
# choosing a plan is how a read-only account stops being read-only.
_READ_ONLY_WRITES = frozenset({"billing:manage", "invoice:download"})


def _usable_while_read_only(code: str) -> bool:
    """Whether a permission still does anything for a suspended organization.

    Narrowing `/auth/me` is what hides every create/edit/delete control in every
    module at once: the UI already gates each one on `can(user, "...")`. The server
    refuses the writes regardless (`require()` in api/deps.py); this only stops the
    interface offering buttons that would fail.
    """
    return code.endswith(":read") or code in _READ_ONLY_WRITES


def _attach_body_tokens(response: Response, tokens: IssuedTokens, settings: Settings) -> None:
    """Expose the token pair in headers for non-browser clients.

    Headers rather than the response body, because the body is a typed model shared
    with the browser path -- adding optional token fields to it would leave them one
    forgotten condition away from being serialised to a browser, which is exactly the
    mistake the httpOnly rule exists to prevent.

    `settings` is unused today and kept in the signature because the decision of
    which transport is permitted belongs with configuration, not with the caller;
    the check moves here the moment it becomes environment-dependent.
    """
    del settings  # see docstring
    response.headers["X-Access-Token"] = tokens.access_token
    response.headers["X-Refresh-Token"] = tokens.refresh_token
    response.headers["X-Expires-In"] = str(tokens.expires_in)


__all__ = ["TokenPair", "get_email_dispatcher", "router"]
