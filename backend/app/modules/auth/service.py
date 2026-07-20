"""Authentication business rules.

WHY THIS FILE EXISTS
    Every credential decision the system makes is here: signup, email verification,
    login (with lockout and role-based 2FA), token issuance and rotation, logout, and
    password reset. The router only speaks HTTP; the repositories only run SQL; the
    security/otp primitives only do maths. This layer is the workflow that ties them
    together, and it imports no `fastapi`.

INTERACTIONS
    * `router.py` calls these methods and supplies an `EmailDispatcher` that schedules
      the actual (slow, network-bound) SMTP send off the request path.
    * `TenancyService` is called during registration so a school and its first admin
      are created in ONE transaction -- either both land or neither does.

SECURITY NOTES worth keeping in view
    * OTP verification always fails with the SAME message regardless of whether the
      code was wrong, expired, exhausted or never issued -- so the endpoint is not an
      oracle.
    * Login on an unknown email still runs a password verification against a dummy
      hash, so "no such user" and "wrong password" take similar time and return the
      same error -- no user enumeration by response or timing.
    * Password reset revokes every refresh token, closing the window where a stolen
      session survives the reset it was meant to defeat.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol, runtime_checkable
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.email.sender import EmailMessage
from app.common.email.templates import render_otp_email
from app.core.config import Settings, get_settings
from app.core.exceptions import AuthenticationError, ConflictError, NotFoundError
from app.core.logging import get_logger
from app.core.otp import (
    OTP_MAX_ATTEMPTS,
    OTP_RESEND_COOLDOWN_SECONDS,
    OTP_TTL_MINUTES,
    OtpPurpose,
    generate_otp,
    hash_otp,
    normalise_identifier,
    verify_otp,
)
from app.core.security import (
    TokenType,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.db.session import bind_tenant, session_scope
from app.modules.auth.models import User, UserRole, UserStatus
from app.modules.auth.repository import OtpRepository, RefreshTokenRepository, UserRepository
from app.modules.auth.schemas import (
    ForgotPasswordRequest,
    LoginRequest,
    LoginResult,
    MessageResponse,
    RegisterRequest,
    RegisterResponse,
    ResetPasswordRequest,
    TokenPair,
    UserRead,
    Verify2FARequest,
    VerifyEmailRequest,
)
from app.modules.tenancy.repository import SchoolRepository
from app.modules.tenancy.service import TenancyService

logger = get_logger(__name__)

# Password-guessing throttle (distinct from the OTP attempt cap, which throttles code
# guessing). After this many consecutive failures the account locks for a cool-off.
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 15

# A precomputed Argon2id hash of a random value. Verified against when the email is
# unknown, so an unknown-user login costs the same ~real hash time as a wrong password
# and the two are indistinguishable to an attacker.
_DUMMY_PASSWORD_HASH = hash_password("dummy-password-for-constant-time-login-path")

# Uniform failure message for every OTP problem -- wrong, expired, exhausted, absent.
_OTP_FAILURE = "The code is invalid or has expired. Please request a new one."


@runtime_checkable
class EmailDispatcher(Protocol):
    """Schedules delivery of a rendered message without blocking the request.

    A Protocol (not a concrete class) so the service depends only on the shape: the
    router wires a real implementation backed by `BackgroundTasks`; tests pass a fake
    that simply records what would have been sent.
    """

    def dispatch(self, message: EmailMessage) -> None: ...


class AuthService:
    """Signup, login, 2FA, token lifecycle and password reset."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        dispatcher: EmailDispatcher,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.dispatcher = dispatcher
        self.users = UserRepository(session)
        self.otps = OtpRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)

    # ======================================================== registration

    async def register(self, payload: RegisterRequest) -> RegisterResponse:
        """Create a pending school and its first admin, then send a verify code.

        Both writes share this request's transaction, so a failure anywhere leaves
        neither a stray school nor a stray user behind.
        """
        admin_email = normalise_identifier(payload.email)

        # Pre-tenant lookup (users are outside RLS): email is globally unique.
        if await self.users.email_taken(admin_email):
            raise ConflictError("An account with this email already exists.", code="EMAIL_TAKEN")

        # Creates the school AND binds this session's tenant to it, so the users
        # insert below is stamped with a real, policy-consistent school_id.
        school = await TenancyService(self.session).register_school(
            name=payload.school_name,
            email=payload.school_email,
            phone=payload.school_phone,
        )

        user = await self.users.create(
            school_id=school.id,
            email=admin_email,
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name.strip(),
            role=UserRole.SCHOOL_ADMIN,
            status=UserStatus.PENDING_VERIFICATION,
        )

        await self._send_otp(
            email=admin_email,
            purpose=OtpPurpose.SIGNUP_VERIFY,
            user_id=user.id,
            recipient_name=user.full_name,
        )
        logger.info("user_registered", user_id=str(user.id), school_id=str(school.id))
        return RegisterResponse(school_id=school.id, user_id=user.id, email=admin_email)

    async def verify_email(self, payload: VerifyEmailRequest) -> MessageResponse:
        """Consume a SIGNUP_VERIFY code and activate the user account."""
        email = normalise_identifier(payload.email)
        await self._consume_otp(email, OtpPurpose.SIGNUP_VERIFY, payload.code)

        user = await self.users.get_by_email(email)
        if user is None:  # pragma: no cover - a consumed code implies the user exists
            raise AuthenticationError(_OTP_FAILURE, code="OTP_INVALID")
        if user.is_email_verified:
            return MessageResponse(detail="Email already verified.")

        await self.users.update(user, email_verified_at=datetime.now(UTC), status=UserStatus.ACTIVE)
        logger.info("email_verified", user_id=str(user.id))
        return MessageResponse(
            detail="Email verified. Your school is pending approval before you can sign in."
        )

    async def resend_verification(self, email: str) -> MessageResponse:
        """Re-send a signup code, silently rate-limited to avoid enumeration."""
        normalised = normalise_identifier(email)
        user = await self.users.get_by_email(normalised)
        if (
            user is not None
            and user.status is UserStatus.PENDING_VERIFICATION
            and not await self._within_cooldown(normalised, OtpPurpose.SIGNUP_VERIFY)
        ):
            await self._send_otp(
                email=normalised,
                purpose=OtpPurpose.SIGNUP_VERIFY,
                user_id=user.id,
                recipient_name=user.full_name,
            )
        return MessageResponse(
            detail="If the account needs verification, a new code has been sent."
        )

    # ================================================================ login

    async def login(
        self, payload: LoginRequest, *, user_agent: str | None = None, ip: str | None = None
    ) -> LoginResult:
        """Authenticate credentials, then either issue tokens or a 2FA challenge."""
        email = normalise_identifier(payload.email)
        user = await self.users.get_by_email(email)

        if user is None:
            # Constant-time-ish: still pay for a hash so timing does not reveal
            # whether the address exists.
            verify_password(payload.password, _DUMMY_PASSWORD_HASH)
            raise AuthenticationError("Invalid email or password.", code="INVALID_CREDENTIALS")

        if user.is_locked:
            raise AuthenticationError(
                "Account temporarily locked after repeated failures. Try again later.",
                code="ACCOUNT_LOCKED",
            )

        if not verify_password(payload.password, user.hashed_password):
            await self._record_failed_login(user)
            raise AuthenticationError("Invalid email or password.", code="INVALID_CREDENTIALS")

        if user.status is UserStatus.PENDING_VERIFICATION:
            raise AuthenticationError(
                "Please verify your email before signing in.", code="EMAIL_NOT_VERIFIED"
            )
        if user.status is UserStatus.SUSPENDED:
            raise AuthenticationError("This account has been suspended.", code="ACCOUNT_SUSPENDED")

        await self._require_active_school(user)

        # Password was correct: clear the failure counter (but do not stamp
        # last_login until a token is actually issued -- 2FA may still be pending).
        if user.failed_login_attempts or user.locked_until is not None:
            await self.users.update(user, failed_login_attempts=0, locked_until=None)

        if user.requires_two_factor:
            await self._send_otp(
                email=email,
                purpose=OtpPurpose.LOGIN_2FA,
                user_id=user.id,
                recipient_name=user.full_name,
            )
            return LoginResult(
                requires_2fa=True,
                detail="A sign-in code was sent to your email.",
            )

        tokens = await self._issue_tokens(user, user_agent=user_agent, ip=ip)
        return LoginResult(requires_2fa=False, detail="Signed in.", tokens=tokens)

    async def verify_2fa(
        self, payload: Verify2FARequest, *, user_agent: str | None = None, ip: str | None = None
    ) -> TokenPair:
        """Consume a LOGIN_2FA code and complete the sign-in."""
        email = normalise_identifier(payload.email)
        await self._consume_otp(email, OtpPurpose.LOGIN_2FA, payload.code)

        user = await self.users.get_by_email(email)
        if user is None or not user.can_authenticate:
            raise AuthenticationError("Invalid email or password.", code="INVALID_CREDENTIALS")
        await self._require_active_school(user)
        return await self._issue_tokens(user, user_agent=user_agent, ip=ip)

    # ================================================= token lifecycle

    async def refresh(
        self, refresh_token: str, *, user_agent: str | None = None, ip: str | None = None
    ) -> TokenPair:
        """Rotate a refresh token: verify it, revoke it, and issue a fresh pair.

        Rotation (revoke-on-use) means a leaked refresh token is usable at most once
        before the legitimate client's next refresh invalidates it. Role and tenant
        are re-read from the database here, so a changed role or suspended school
        takes effect within one access-token lifetime.
        """
        payload = decode_token(
            refresh_token, expected_type=TokenType.REFRESH, settings=self.settings
        )
        jti = str(payload["jti"])
        stored = await self.refresh_tokens.get_by_jti(jti)
        if stored is None or not stored.is_active:
            raise AuthenticationError(
                "Session is invalid or has expired. Please sign in again.",
                code="REFRESH_INVALID",
            )

        user = await self.users.get(UUID(str(payload["sub"])))
        if user is None or not user.can_authenticate:
            raise AuthenticationError("Session is no longer valid.", code="REFRESH_INVALID")
        await self._require_active_school(user)

        await self.refresh_tokens.revoke(stored)
        return await self._issue_tokens(user, user_agent=user_agent, ip=ip)

    async def logout(self, refresh_token: str) -> MessageResponse:
        """Revoke a refresh token. Idempotent: an unknown/expired token is a no-op."""
        try:
            payload = decode_token(
                refresh_token, expected_type=TokenType.REFRESH, settings=self.settings
            )
        except AuthenticationError:
            return MessageResponse(detail="Signed out.")

        stored = await self.refresh_tokens.get_by_jti(str(payload["jti"]))
        if stored is not None:
            await self.refresh_tokens.revoke(stored)
        return MessageResponse(detail="Signed out.")

    # ============================================================ password

    async def forgot_password(self, payload: ForgotPasswordRequest) -> MessageResponse:
        """Issue a reset code. Always returns the same message (no enumeration)."""
        email = normalise_identifier(payload.email)
        user = await self.users.get_by_email(email)
        if user is not None and not await self._within_cooldown(email, OtpPurpose.PASSWORD_RESET):
            await self._send_otp(
                email=email,
                purpose=OtpPurpose.PASSWORD_RESET,
                user_id=user.id,
                recipient_name=user.full_name,
            )
        return MessageResponse(
            detail="If an account exists for that address, a reset code has been sent."
        )

    async def reset_password(self, payload: ResetPasswordRequest) -> MessageResponse:
        """Consume a reset code, set the new password, and kill every session."""
        email = normalise_identifier(payload.email)
        await self._consume_otp(email, OtpPurpose.PASSWORD_RESET, payload.code)

        user = await self.users.get_by_email(email)
        if user is None:  # pragma: no cover - a consumed code implies the user exists
            raise AuthenticationError(_OTP_FAILURE, code="OTP_INVALID")

        await self.users.update(
            user,
            hashed_password=hash_password(payload.new_password),
            failed_login_attempts=0,
            locked_until=None,
        )
        killed = await self.refresh_tokens.revoke_all_for_user(user.id)
        logger.info("password_reset", user_id=str(user.id), sessions_revoked=killed)
        return MessageResponse(detail="Password updated. Please sign in with your new password.")

    # ============================================================= profile

    async def get_profile(self, user_id: UUID) -> UserRead:
        user = await self.users.get(user_id)
        if user is None:
            raise NotFoundError("User not found.")
        return UserRead.model_validate(user)

    # ============================================================= helpers

    async def _issue_tokens(
        self, user: User, *, user_agent: str | None, ip: str | None
    ) -> TokenPair:
        """Mint an access+refresh pair, persist the refresh handle, stamp last_login."""
        is_sa = user.role is UserRole.SUPER_ADMIN
        access = create_access_token(
            user.id,
            school_id=user.school_id,
            role=user.role.value,
            is_super_admin=is_sa,
            settings=self.settings,
        )
        refresh = create_refresh_token(user.id, settings=self.settings)

        # Read jti/exp back from the signed token rather than re-generating them, so
        # the stored handle and the issued token can never disagree.
        claims = decode_token(refresh, expected_type=TokenType.REFRESH, settings=self.settings)
        await self.refresh_tokens.create(
            user_id=user.id,
            jti=str(claims["jti"]),
            expires_at=datetime.fromtimestamp(int(claims["exp"]), tz=UTC),
            user_agent=(user_agent or None) and user_agent[:400],
            ip_address=ip,
        )
        await self.users.update(user, last_login_at=datetime.now(UTC))

        return TokenPair(
            access_token=access,
            refresh_token=refresh,
            expires_in=self.settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def _require_active_school(self, user: User) -> None:
        """Reject sign-in when the user's school is not live.

        Super admins carry no school and skip this. For everyone else, the school is
        read under a session freshly bound to that tenant (login is a pre-tenant,
        public flow), so RLS permits exactly this one school row.
        """
        if user.school_id is None:
            return
        await bind_tenant(self.session, user.school_id)
        school = await SchoolRepository(self.session).get(user.school_id)
        if school is None or not school.is_active:
            raise AuthenticationError(
                "Your school is not active yet. Please contact your administrator.",
                code="SCHOOL_INACTIVE",
            )

    async def _record_failed_login(self, user: User) -> None:
        """Bump the failure counter (and lock if the cap is reached) in ITS OWN
        transaction, so the 401 this login is about to raise cannot roll it back.

        The request's own session only performed SELECTs at this point; the counter
        genuinely needs to be a separate, committed unit of work to survive rejection.
        """
        attempts = user.failed_login_attempts + 1
        locked_until = None
        if attempts >= MAX_FAILED_LOGINS:
            locked_until = datetime.now(UTC) + timedelta(minutes=LOCKOUT_MINUTES)
            logger.warning("account_locked", user_id=str(user.id), attempts=attempts)

        async with session_scope() as session:
            await UserRepository(session).set_login_failure(
                user.id, attempts=attempts, locked_until=locked_until
            )

    async def _send_otp(
        self, *, email: str, purpose: OtpPurpose, user_id: UUID, recipient_name: str | None
    ) -> None:
        """Generate a code, persist only its digest, and dispatch the email."""
        code = generate_otp()
        await self.otps.create(
            user_id=user_id,
            email=email,
            purpose=purpose,
            code_hash=hash_otp(code, purpose=purpose, identifier=email, settings=self.settings),
            expires_at=datetime.now(UTC) + timedelta(minutes=OTP_TTL_MINUTES),
            attempts=0,
        )
        message = render_otp_email(
            to=email,
            code=code,
            purpose=purpose,
            recipient_name=recipient_name,
            settings=self.settings,
        )
        self.dispatcher.dispatch(message)

    async def _consume_otp(self, email: str, purpose: OtpPurpose, code: str) -> None:
        """Verify a submitted code and burn it, or raise a uniform failure.

        Order matters: usability (expiry/consumption/attempt cap) is checked BEFORE
        the cryptographic compare, because a match on an unusable code is still a
        failed authentication.
        """
        otp = await self.otps.latest_active(email, purpose)
        if otp is None or not otp.is_usable(OTP_MAX_ATTEMPTS):
            raise AuthenticationError(_OTP_FAILURE, code="OTP_INVALID")

        if not verify_otp(
            code, otp.code_hash, purpose=purpose, identifier=email, settings=self.settings
        ):
            await self.otps.update(otp, attempts=otp.attempts + 1)
            raise AuthenticationError(_OTP_FAILURE, code="OTP_INVALID")

        await self.otps.update(otp, consumed_at=datetime.now(UTC))

    async def _within_cooldown(self, email: str, purpose: OtpPurpose) -> bool:
        """True if a code for this address+flow was sent within the resend cooldown."""
        latest = await self.otps.latest_for_cooldown(email, purpose)
        if latest is None:
            return False
        age = datetime.now(UTC) - latest.created_at
        return age.total_seconds() < OTP_RESEND_COOLDOWN_SECONDS
