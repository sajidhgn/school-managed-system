"""Auth request/response contracts.

WHY THIS FILE EXISTS
    The API surface is a contract with the Next.js frontend, which generates its
    TypeScript types from this schema. Defining the shapes here -- rather than
    returning ORM objects or dicts -- means a field rename is a compile error in the
    frontend rather than a runtime `undefined`.

RESPONSIBILITY
    Shape and validate what crosses the wire. Format-level validation only; business
    rules (does this email already exist, is this password strong enough) belong to
    the service, which can express them with the database and the policy module.

INTERACTIONS
    Consumed by `modules/auth/router.py`; produced by `modules/auth/service.py`.

=============================================================================
WHAT IS DELIBERATELY ABSENT FROM EVERY RESPONSE HERE
=============================================================================
    No access token, and no refresh token. Both travel exclusively in httpOnly
    cookies (spec §4.1), so putting them in a response body would defeat the point
    entirely -- a token in JSON is a token JavaScript can read, and therefore a token
    any XSS payload can steal.

    The one exception is documented at `TokenPair`, which exists only for
    non-browser clients and is never returned to a browser.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import EmailStr, Field

from app.common.schemas import BaseSchema

# ---------------------------------------------------------------------------
# Registration & verification
# ---------------------------------------------------------------------------


class RegisterRequest(BaseSchema):
    """Self-service signup: creates the person AND their organization (spec §4.3B)."""

    full_name: str = Field(min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)
    """Length is checked properly by `core/passwords.py`, which applies the real
    policy -- minimum length, zxcvbn score, breached-password list. The bound here
    is only a denial-of-service guard: Argon2's cost grows with input size, so an
    unbounded password field is a free way to burn server CPU."""

    organization_name: str = Field(min_length=2, max_length=200)
    country: str | None = Field(default=None, min_length=2, max_length=2)


class RegisterResponse(BaseSchema):
    """Signup result. Carries no token: login is blocked until email is verified."""

    user_id: UUID
    organization_id: UUID
    email: EmailStr
    verification_required: bool = True
    message: str


class VerifyEmailRequest(BaseSchema):
    token: str = Field(min_length=16, max_length=512)


class ResendVerificationRequest(BaseSchema):
    email: EmailStr


# ---------------------------------------------------------------------------
# Login & context
# ---------------------------------------------------------------------------


class LoginRequest(BaseSchema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class MembershipSummary(BaseSchema):
    """One context the user may act in. Rendered by the context switcher."""

    membership_id: UUID
    organization_id: UUID
    organization_name: str
    school_id: UUID | None
    school_name: str | None
    role_code: str
    role_name: str
    is_primary: bool
    is_org_level: bool


class LoginResponse(BaseSchema):
    """Login result.

    TWO SHAPES IN ONE RESPONSE, driven by `select_required` (spec §4.3D):

      * exactly one membership -> auto-selected, cookies are set, the caller is
        logged in and can proceed.
      * several memberships    -> `select_required = true`, NO access cookie is set,
        and the caller must call `POST /auth/context` to pick one.

    The second case is not an error, so it is still a 200. A user who teaches at two
    schools has not done anything wrong; they simply have not said which hat they
    are wearing, and the system must not guess. Guessing would drop a teacher into
    the wrong school's data.
    """

    user_id: UUID
    email: EmailStr
    full_name: str
    memberships: list[MembershipSummary]
    select_required: bool
    active_membership_id: UUID | None = None


class ContextSwitchRequest(BaseSchema):
    membership_id: UUID


class MeResponse(BaseSchema):
    """`GET /auth/me` -- everything the app shell needs on boot.

    Returns the resolved permission set so the frontend can hide actions the user
    cannot perform. That hiding is COSMETIC ONLY (spec §9): every action is
    re-checked server-side by `require()`. A frontend treating this list as the
    security boundary is one `curl` away from being bypassed.
    """

    user_id: UUID
    email: EmailStr
    full_name: str
    avatar_url: str | None
    locale: str
    memberships: list[MembershipSummary]
    active_membership_id: UUID | None
    organization_id: UUID | None
    organization_name: str | None
    organization_status: str | None
    school_id: UUID | None
    school_name: str | None
    role_code: str | None
    permissions: list[str]


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


class ForgotPasswordRequest(BaseSchema):
    email: EmailStr


class ResetPasswordRequest(BaseSchema):
    token: str = Field(min_length=16, max_length=512)
    password: str = Field(min_length=1, max_length=200)


class MessageResponse(BaseSchema):
    """Generic acknowledgement.

    Used by the endpoints that must NOT reveal whether an account exists --
    forgot-password and resend-verification return this identical body whether or not
    the address is registered. A response that differs turns the endpoint into a
    user-enumeration oracle, which for a school platform means learning which schools
    are customers.
    """

    message: str


class TokenPair(BaseSchema):
    """Tokens in the response body, for NON-BROWSER clients only.

    Returned exclusively when the caller opts in with `X-Token-Transport: body`.
    Browsers never send that header, so they never receive tokens in JSON.

    This exists because the test suite, CI and future server-to-server integrations
    have no cookie jar. It is a deliberate, narrow exception to the httpOnly rule,
    and it is safe precisely because a page running in a victim's browser cannot
    trigger it: setting a custom header cross-origin requires a CORS preflight this
    API does not grant to arbitrary origins.
    """

    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class SessionSummary(BaseSchema):
    """One active session, for the security screen."""

    session_id: UUID
    created_at: datetime
    expires_at: datetime
    ip: str | None
    user_agent: str | None
    is_current: bool
