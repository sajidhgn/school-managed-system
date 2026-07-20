"""Auth API contracts (Pydantic).

WHY THIS FILE EXISTS
    Defines exactly what each auth endpoint accepts and returns. Request schemas are
    the trust boundary: a client may send an email and a password, never a `role`, a
    `school_id` or a `status`. Those are set by the service.

INTERACTIONS
    * `router.py` declares these as request bodies / response models.
    * `service.py` builds the response schemas from ORM rows and issued tokens.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import EmailStr, Field

from app.common.schemas import BaseSchema
from app.modules.auth.models import UserRole, UserStatus

# A deliberately modest floor. OWASP's guidance is length-first; the real brute-force
# defences are Argon2id hashing (slow) plus account lockout, not composition rules.
PasswordStr = Field(min_length=8, max_length=128)


# ---------------------------------------------------------------------------
# Registration & verification
# ---------------------------------------------------------------------------


class RegisterRequest(BaseSchema):
    """Self-service signup: creates a pending school AND its first admin at once."""

    school_name: str = Field(min_length=2, max_length=200)
    school_email: EmailStr = Field(description="The school's contact address.")
    school_phone: str | None = Field(default=None, max_length=32)

    full_name: str = Field(min_length=1, max_length=200, description="The admin's name.")
    email: EmailStr = Field(description="The admin's login email.")
    password: str = PasswordStr


class RegisterResponse(BaseSchema):
    school_id: UUID
    user_id: UUID
    email: EmailStr
    detail: str = "Registration received. Check your email for a verification code."


class VerifyEmailRequest(BaseSchema):
    email: EmailStr
    code: str = Field(min_length=4, max_length=12)


class ResendVerificationRequest(BaseSchema):
    email: EmailStr


# ---------------------------------------------------------------------------
# Login, 2FA, tokens
# ---------------------------------------------------------------------------


class LoginRequest(BaseSchema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class TokenPair(BaseSchema):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access-token lifetime in seconds.")


class LoginResult(BaseSchema):
    """Login is two-shaped: either tokens, or a 2FA challenge.

    A single response model keeps the OpenAPI surface simple and lets the frontend
    branch on `requires_2fa` rather than on HTTP status.
    """

    requires_2fa: bool = False
    detail: str
    tokens: TokenPair | None = None


class Verify2FARequest(BaseSchema):
    email: EmailStr
    code: str = Field(min_length=4, max_length=12)


class RefreshRequest(BaseSchema):
    refresh_token: str


class LogoutRequest(BaseSchema):
    refresh_token: str


# ---------------------------------------------------------------------------
# Password reset
# ---------------------------------------------------------------------------


class ForgotPasswordRequest(BaseSchema):
    email: EmailStr


class ResetPasswordRequest(BaseSchema):
    email: EmailStr
    code: str = Field(min_length=4, max_length=12)
    new_password: str = PasswordStr


# ---------------------------------------------------------------------------
# Generic + profile
# ---------------------------------------------------------------------------


class MessageResponse(BaseSchema):
    detail: str


class UserRead(BaseSchema):
    """The authenticated user's own profile. Never exposes the password hash."""

    id: UUID
    school_id: UUID | None
    email: str
    full_name: str
    role: UserRole
    status: UserStatus
    email_verified: bool = Field(validation_alias="is_email_verified")
    two_factor_enabled: bool
    last_login_at: datetime | None
    created_at: datetime
