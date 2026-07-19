"""Authentication models: User, OtpCode, RefreshToken.

WHY THIS FILE EXISTS
    Identity is its own module, separate from tenancy. A `User` belongs to a school,
    but the rules governing credentials, OTP challenges and session revocation are
    authentication concerns, not tenancy concerns.

RESPONSIBILITY
    Define the identity, challenge and session tables.

INTERACTIONS
    * `User.school_id` -> `schools.id`.
    * `modules/auth/service.py` orchestrates these via repositories.
    * `core/security.py` supplies hashing; `core/otp.py` supplies code digests.

=============================================================================
THESE THREE TABLES ARE DELIBERATELY *OUTSIDE* TENANT RLS. HERE IS WHY.
=============================================================================
    Every other table in this system is protected by a policy comparing `school_id`
    against `app.current_school_id`. These three cannot be, because of a
    chicken-and-egg problem:

        To set `app.current_school_id`, we need the tenant from the user's JWT.
        To issue a JWT, we must first look the user up by email.
        At that moment there is no JWT, so no tenant, so the GUC is unset --
        and an RLS policy comparing against an unset GUC matches ZERO rows.

    With RLS enabled on `users`, login would be structurally impossible: the query
    that finds the user would always return nothing. The same applies to
    `otp_codes` (forgot-password looks up by email, pre-authentication) and
    `refresh_tokens` (refresh runs with an expired access token).

    WHAT PROTECTS THEM INSTEAD:

      1. Every tenant-scoped read of `users` -- listing staff, fetching a teacher --
         goes through `UserRepository`, which applies an explicit `school_id`
         filter. This is the weaker application-layer guarantee that RLS exists to
         replace, so it is confined to exactly these three tables and nowhere else.

      2. The auth service never returns a `User` across a tenant boundary: every
         lookup that could is keyed by email + password, and issues a token scoped
         to that user's own school.

      3. `otp_codes` and `refresh_tokens` are only ever queried by their own
         primary key, by `user_id`, or by email + purpose -- never enumerated.

    THE UPGRADE PATH, if this trade stops being acceptable: give the login lookup
    its own database role (`sms_auth`) with SELECT on a narrow view exposing only
    (id, email, hashed_password, status, role, school_id), and keep full RLS on the
    base table. That costs a second connection pool, which is why it is not the
    starting design -- but it is the correct end state if the app ever handles
    genuinely adversarial multi-tenant load.

    THIS IS THE ONLY EXCEPTION IN THE SCHEMA. Every other table gets
    `setup_tenant_table()` in its migration, no exceptions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.core.otp import OtpPurpose
from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class UserRole(StrEnum):
    """RBAC roles.

    The PDF specifies School Admin (full access) and Teacher (limited to assigned
    classes); SUPER_ADMIN is the platform operator who onboards schools.

    Kept deliberately flat. A full permission matrix (roles -> permissions tables)
    is the right model once there are twelve roles, but at three it is indirection
    with no payoff -- and premature abstraction here would slow every module that
    follows.
    """

    SUPER_ADMIN = "super_admin"
    SCHOOL_ADMIN = "school_admin"
    TEACHER = "teacher"


class UserStatus(StrEnum):
    PENDING_VERIFICATION = "pending_verification"  # signed up, email not yet verified
    ACTIVE = "active"
    SUSPENDED = "suspended"


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A person who can authenticate."""

    __tablename__ = "users"

    # --- Tenancy -----------------------------------------------------------
    # NOT `TenantMixin`: that mixin declares school_id NOT NULL, and platform
    # super-admins genuinely belong to no school. Declared by hand so the column
    # can be nullable while keeping the same FK and index.
    # No `index=True`: the composite ix_users_school_id_role below already covers
    # school_id-only lookups via its leftmost prefix. A second index would be dead
    # weight -- never chosen by the planner, but still maintained on every write.
    school_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("schools.id", ondelete="CASCADE"),
        nullable=True,
    )

    # --- Credentials -------------------------------------------------------
    # No `index=True`: the partial unique index uq_users_email_active serves every
    # lookup we actually perform, since we always query live rows
    # (`WHERE email = ? AND deleted_at IS NULL`).
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    """320 chars = RFC 5321 maximum (64 local + @ + 255 domain).

    UNIQUENESS IS GLOBAL, NOT PER-SCHOOL -- see `__table_args__`. Login takes an
    email and a password with no school selector, so the email must identify
    exactly one account. The cost: one person cannot hold accounts at two schools
    under the same address. For a teacher working at two campuses that is a real
    limitation; the fix, if it ever bites, is a `user_school_memberships` join
    table rather than relaxing this constraint.

    Stored lowercase, normalised by the service on write.
    """

    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    """Argon2id digest. The column is named `hashed_password`, never `password`,
    so that a stray log of the model can never be mistaken for a plaintext leak."""

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)

    # --- Authorisation -----------------------------------------------------
    role: Mapped[UserRole] = mapped_column(String(32), nullable=False, index=True)
    status: Mapped[UserStatus] = mapped_column(
        String(32), nullable=False, default=UserStatus.PENDING_VERIFICATION, index=True
    )

    # --- Verification & 2FA ------------------------------------------------
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    two_factor_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """Per-user override on top of the role default.

    Policy (your decision): admins always 2FA, teachers never. `requires_two_factor`
    below combines the role default with this flag, so a security-conscious teacher
    can opt in without a schema change.
    """

    # --- Login protection --------------------------------------------------
    failed_login_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Lockout after repeated password failures.

    Distinct from the OTP attempt counter: this throttles password guessing,
    that one throttles code guessing. Both are needed -- an attacker who can
    brute-force the password never reaches the OTP step, and vice versa.
    """

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # Global uniqueness, but only across LIVE rows: the partial index means a
        # soft-deleted user's address is released for reuse. Without the WHERE
        # clause, deleting a teacher would permanently burn their email address.
        #
        # `text()` rather than the mapped attribute because __table_args__ is
        # evaluated during class construction, before `User.deleted_at` exists as a
        # resolvable InstrumentedAttribute.
        Index(
            "uq_users_email_active",
            "email",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_users_school_id_role", "school_id", "role"),
    )

    # --- Derived state -----------------------------------------------------

    @property
    def is_email_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def is_locked(self) -> bool:
        if self.locked_until is None:
            return False
        return self.locked_until > datetime.now(UTC)

    @property
    def can_authenticate(self) -> bool:
        """Whether this account may complete a login right now."""
        return self.status is UserStatus.ACTIVE and self.deleted_at is None and not self.is_locked

    @property
    def requires_two_factor(self) -> bool:
        """Role-based 2FA policy.

        Admins hold every student record, fee ledger and parent contact for their
        school, so they always get an email challenge. Teachers do not, because the
        PDF requires attendance in under 10 seconds and an inbox round-trip several
        times a day would make that target unreachable.
        """
        if self.role in (UserRole.SUPER_ADMIN, UserRole.SCHOOL_ADMIN):
            return True
        return self.two_factor_enabled


class OtpCode(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A one-time code challenge.

    Holds the STATE that `core/otp.py` deliberately does not: expiry, attempt count,
    and single-use consumption. Those three are what make a 6-digit code safe --
    the cryptography alone is not enough against 10^6 brute force.

    No soft delete: consumed and expired codes are purged by a scheduled job. They
    are transient security artefacts, not business records, and keeping them
    forever grows an index that is on the login hot path.
    """

    __tablename__ = "otp_codes"

    user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    """Nullable so a code can be issued before any user row exists -- and so
    forgot-password for an unknown address can follow an identical code path to a
    known one. Identical timing and identical writes are what prevent the endpoint
    from becoming a user-enumeration oracle."""

    email: Mapped[str] = mapped_column(String(320), nullable=False)
    """Denormalised from `users`.

    Forgot-password and signup-verify both arrive with only an email address, so
    the lookup must not require a join to a user that may not exist yet.
    """

    purpose: Mapped[OtpPurpose] = mapped_column(String(32), nullable=False)
    """Bound into `code_hash` cryptographically AND stored here.

    The digest binding makes cross-flow replay impossible; storing it as well lets
    the service reject a mismatch before doing any comparison, and makes the
    audit trail readable.
    """

    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    """HMAC-SHA256 hex digest -- exactly 64 chars. The plaintext code is NEVER
    persisted and never logged; it exists only in memory and in the sent email."""

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """Incremented on every wrong guess. At OTP_MAX_ATTEMPTS the code is burned.

    THIS COUNTER IS THE PRIMARY DEFENCE. Without it, 10^6 requests break any
    6-digit code with certainty.
    """

    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Set on successful use. Enforces single-use: a code observed in an inbox
    cannot be replayed after the legitimate user has already redeemed it."""

    __table_args__ = (
        # The exact lookup the service performs: "newest live code for this address
        # and flow". Covers verify, and the resend-cooldown check.
        Index("ix_otp_codes_email_purpose_created", "email", "purpose", "created_at"),
        Index("ix_otp_codes_expires_at", "expires_at"),  # for the purge job
    )

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= datetime.now(UTC)

    @property
    def is_consumed(self) -> bool:
        return self.consumed_at is not None

    def is_usable(self, max_attempts: int) -> bool:
        """Whether this code may still be presented.

        The service must check this BEFORE comparing digests. A cryptographic match
        on an expired, consumed or exhausted code is still a failed authentication.
        """
        return not self.is_expired and not self.is_consumed and self.attempts < max_attempts


class RefreshToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A persisted refresh-token handle, enabling revocation.

    WHY THIS TABLE EXISTS AT ALL
        JWTs are self-validating: the server needs no state to accept one, which is
        exactly why a stolen token cannot normally be revoked before it expires.
        Storing the `jti` lets us invalidate sessions on demand.

        Concretely, the flow you asked for requires it: password reset MUST kill
        every existing session. Otherwise an attacker who obtained a refresh token
        keeps their access even after the victim resets their password -- which
        defeats the entire point of the reset.

    Only REFRESH tokens are tracked, never access tokens. Access tokens live 30
    minutes and checking them against the database on every request would discard
    the performance benefit of stateless JWTs. The 30-minute window is the accepted
    trade; shortening ACCESS_TOKEN_EXPIRE_MINUTES narrows it.
    """

    __tablename__ = "refresh_tokens"

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    jti: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    """The token's unique id claim. We store the identifier, not the token itself --
    possessing this table must not let anyone mint or replay a session."""

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Captured for the "active sessions" screen and for security alerting on an
    # unfamiliar sign-in. Kept short: this is personal data under GDPR-style rules.
    user_agent: Mapped[str | None] = mapped_column(String(400))
    ip_address: Mapped[str | None] = mapped_column(String(45))  # 45 = max IPv6 length

    __table_args__ = (
        UniqueConstraint("jti", name="uq_refresh_tokens_jti"),
        Index("ix_refresh_tokens_user_id_revoked_at", "user_id", "revoked_at"),
    )

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > datetime.now(UTC)
