"""Identity models: User, Session, PasswordResetToken, EmailVerificationToken.

WHY THIS FILE EXISTS
    Identity is global; membership is scoped (spec decision D4). One `users` row per
    human, with a globally unique email. That human may hold several memberships --
    teacher at School A, accountant at School B, owner of a different organization
    entirely -- and each membership is a separate row in a different table.

RESPONSIBILITY
    Define the person, their sessions, and the short-lived tokens that let them
    prove control of an email address.

INTERACTIONS
    * `organizations.owner_user_id` -> `users.id`
    * `memberships.user_id` -> `users.id`
    * `sessions.membership_id` -> `memberships.id` (the active context of a session)
    * `core/security.py` supplies hashing and token digests.

=============================================================================
THESE TABLES CARRY NO `organization_id` AND ARE OUTSIDE TENANT RLS. HERE IS WHY.
=============================================================================
    Every tenant table is protected by a policy comparing `organization_id` against
    `app.current_org_id`. These four cannot be, for two independent reasons:

    1. A CHICKEN-AND-EGG PROBLEM AT LOGIN.
           To set `app.current_org_id` we need the org from the user's token.
           To issue a token we must first find the user by email.
           At that moment there is no token, so no org, so the GUC is empty --
           and a policy comparing against an empty GUC matches ZERO rows.
       With RLS on `users`, login would be structurally impossible: the query that
       finds the user would always return nothing. The same applies to
       `password_reset_tokens` (looked up pre-authentication) and `sessions`
       (refresh runs with an expired access token).

    2. A USER GENUINELY BELONGS TO NO SINGLE ORGANIZATION.
       This is the deeper reason, and it is why the design does not merely work
       around (1). A teacher employed by two client school groups is ONE person with
       ONE password. Stamping an `organization_id` on their `users` row would force
       either a duplicate account per employer -- two passwords, two reset flows, two
       places to revoke on termination -- or an arbitrary choice of which employer
       "owns" them. Spec decision D4 exists precisely to avoid that, and the target
       market (Pakistan/Gulf private-school groups) hits the case routinely.

    WHAT PROTECTS THEM INSTEAD:
      * `users` rows are never enumerated by a tenant-facing endpoint. Listing staff
        goes through `memberships`, which IS tenant-scoped and RLS-protected, and
        joins out to `users` for display fields only.
      * `sessions` and the token tables are queried only by primary key, by
        `user_id`, or by token HASH -- never listed.
      * Every lookup that could cross a boundary is keyed by a secret the caller
        already proved they hold: a password, a token digest, or a session id.

    THIS IS THE ONLY EXCEPTION IN THE SCHEMA. Every other table gets
    `setup_tenant_table()` in the migration, no exceptions.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, str_enum
from app.db.mixins import CreatedAtMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class UserStatus(StrEnum):
    PENDING = "pending"  # registered, email not yet verified -- login blocked
    ACTIVE = "active"
    SUSPENDED = "suspended"


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A person who can authenticate. Global -- no tenant column. See module docstring."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    """CITEXT: `Ayesha@school.pk` and `ayesha@school.pk` are the same human.

    Case-insensitivity lives in the COLUMN TYPE, not in a service-layer `.lower()`.
    A normalisation step only holds for the code paths that remember it; the type
    holds for raw SQL, seed scripts and every endpoint written later. It also makes
    the unique index case-insensitive, so the duplicate cannot be created at all.

    This matters more than usual here: spec §7.2 requires an invitation's email to
    match the accepting account's email EXACTLY. "Exactly" has to mean
    case-insensitively, or an invite to `Ayesha@` is unacceptable by `ayesha@`.

    UNIQUENESS IS GLOBAL, and that is the point of decision D4 -- one row per human,
    with memberships doing the scoping.
    """

    phone: Mapped[str | None] = mapped_column(String(32))

    password_hash: Mapped[str | None] = mapped_column(String(255))
    """NULLABLE until an invitation is accepted.

    An invited teacher has a `users` row the moment the invite is sent? No -- they do
    not. The row is created on ACCEPT. This column is nullable for the other case:
    accounts provisioned by an administrator or an import, which exist before their
    human has ever chosen a password. `can_authenticate` refuses login while it is
    NULL, so a password-less row is inert rather than an open door.
    """

    full_name: Mapped[str] = mapped_column(String(200), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(String(500))
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en")
    timezone: Mapped[str | None] = mapped_column(String(64))

    status: Mapped[UserStatus] = mapped_column(
        str_enum(UserStatus, name="status"),
        nullable=False,
        default=UserStatus.PENDING,
        index=True,
    )

    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- Login protection (spec §4.4) --------------------------------------
    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    """A SERVER default, not only a Python one -- so a row created by raw SQL (a seed
    script, an import, a support fix) does not fail on a not-null violation."""

    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    lockout_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    """How many times this account has been locked, ever.

    Drives the EXPONENTIAL backoff the spec asks for: 15 min, then 30, then 60...
    A flat 15-minute lock is only a speed bump -- an attacker with a candidate list
    simply paces themselves at 5 guesses per quarter hour and grinds indefinitely.
    Doubling makes sustained guessing cost more than it can possibly return, while a
    genuine user who fumbles their password twice in a year never notices.

    Reset to zero on a successful login, so a legitimate user who once got locked
    out is not punished for it months later.
    """

    # --- MFA ---------------------------------------------------------------
    mfa_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    mfa_secret: Mapped[str | None] = mapped_column(String(64))

    __table_args__ = (
        # Global uniqueness across LIVE rows only: a soft-deleted user's address is
        # released for reuse. Without the WHERE clause, removing a teacher would
        # permanently burn their email address -- and they may be re-hired.
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
    )

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
        """Whether this account may complete a login right now.

        Checks every gate at once so no call site can verify the password and then
        forget one of them. `password_hash is not None` is part of it: an
        invitation-provisioned account with no password must not be loginable.
        """
        return (
            self.status is UserStatus.ACTIVE
            and self.deleted_at is None
            and not self.is_locked
            and self.password_hash is not None
        )


class Session(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """A refresh-token family: one login, one device, one active context.

    WHY THIS TABLE EXISTS
        JWTs are self-validating -- the server needs no state to accept one, which is
        exactly why a stolen access token cannot be revoked before it expires. The
        refresh token is the long-lived credential and therefore the one that must be
        revocable, so it is stored (hashed) rather than signed.

    =========================================================================
    ROTATION WITH REUSE DETECTION -- the reason `family_id` exists
    =========================================================================
        Every refresh mints a new token and revokes the presented one. A token is
        therefore valid exactly once.

        Now suppose an attacker steals a refresh token. Either they use it before the
        legitimate user does, or after:

          * They use it first. Rotation succeeds for them; the real user's next
            refresh presents an ALREADY-ROTATED token.
          * The user uses it first. The attacker's later attempt presents an
            ALREADY-ROTATED token.

        Either way, one already-rotated token is presented -- which cannot happen in
        honest operation. That presentation is proof of compromise, and the response
        is to revoke the entire `family_id`, forcing both parties to re-authenticate.
        The attacker has a password they do not know; the user does not.

        Without the family, the best available response would be revoking the single
        replayed token -- leaving the attacker's freshly rotated one alive. The whole
        mechanism turns on being able to name the lineage, which is what `family_id`
        is for.

    NO SOFT DELETE: revocation is `revoked_at`, and expired rows are purged by a
    scheduled job. Sessions are transient security artefacts, not business records,
    and an unbounded table on the refresh hot path is a performance problem.
    """

    __tablename__ = "sessions"

    user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        index=True,
    )
    """The tenant user this session belongs to. NULL for a platform-admin session."""

    platform_admin_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("platform_admins.id", ondelete="CASCADE"),
        index=True,
    )
    """The platform operator this session belongs to. NULL for a tenant session.

    =========================================================================
    WHY BOTH PRINCIPAL TYPES SHARE ONE TABLE
    =========================================================================
        Platform admins live in their own table -- they belong to no organization and
        must never be confused with tenant users. But their SESSIONS need exactly the
        same machinery: opaque refresh tokens, rotation, family-based reuse detection,
        revocation.

        Duplicating that into a `platform_sessions` table would mean maintaining two
        copies of the most security-sensitive logic in the system, and the copy used
        by the most privileged accounts would be the one exercised least in testing.
        One table, one implementation, one CHECK constraint keeping the two
        identities from ever mixing.
    """

    membership_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="CASCADE"),
        index=True,
    )
    """The membership this session is currently acting as (spec §4.2 `mid`).

    NULLABLE for the window between `POST /auth/login` and `POST /auth/context` when
    a user holds several memberships and has not yet chosen one -- and for platform
    admin sessions, which have no membership at all.

    A context switch UPDATES this column rather than creating a new session, so
    "log out everywhere" stays meaningful: one login is one session regardless of how
    many times the user switched schools inside it.
    """

    refresh_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    """SHA-256 hex digest -- exactly 64 chars. The raw token is never persisted and
    never logged; it exists only in the response cookie."""

    family_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False, index=True)
    """Shared by every token descended from one login. See the class docstring."""

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_reason: Mapped[str | None] = mapped_column(String(64))
    """Why this row died: `rotated`, `logout`, `logout_all`, `reuse_detected`,
    `password_reset`, `membership_revoked`. Read during incident response -- a burst
    of `reuse_detected` across many users is a very different signal from one."""

    ip: Mapped[str | None] = mapped_column(String(45))  # 45 = max IPv6 length
    user_agent: Mapped[str | None] = mapped_column(String(400))

    __table_args__ = (
        # EXACTLY ONE principal per session. Without this, a row with both ids set
        # would be a session that is simultaneously a tenant user and a platform
        # operator -- and whichever branch of the refresh logic ran first would
        # decide which. A row with neither would be an orphan nobody can revoke.
        CheckConstraint(
            "(user_id IS NOT NULL) <> (platform_admin_id IS NOT NULL)",
            name="exactly_one_principal",
        ),
        # The refresh hot path: look the presented token up by digest. Unique because
        # two live sessions sharing a digest would make rotation ambiguous.
        Index("uq_sessions_refresh_token_hash", "refresh_token_hash", unique=True),
        # Revoking a whole family on reuse detection -- one indexed UPDATE.
        Index("ix_sessions_family_id_revoked_at", "family_id", "revoked_at"),
        # "Show me this user's active sessions" and `logout-all`.
        Index("ix_sessions_user_id_revoked_at", "user_id", "revoked_at"),
        Index("ix_sessions_expires_at", "expires_at"),  # purge job
    )

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > datetime.now(UTC)


class _SingleUseToken(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Shared shape for emailed, single-use, expiring tokens.

    Abstract: the two concrete subclasses below get their own tables. They are kept
    separate rather than unified behind a `purpose` column so that a bug in the
    password-reset flow cannot consume an email-verification token, and so each can
    be purged on its own retention schedule.
    """

    __abstract__ = True

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_usable(self) -> bool:
        """Single-use AND time-limited. Both must be checked before any comparison.

        A cryptographic match on an expired or already-consumed token is still a
        failed authentication -- and a reset link sitting in an old inbox is exactly
        the token an attacker with mailbox access would replay.
        """
        return self.used_at is None and self.expires_at > datetime.now(UTC)


class PasswordResetToken(_SingleUseToken):
    __tablename__ = "password_reset_tokens"

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index("uq_password_reset_tokens_token_hash", "token_hash", unique=True),
        Index("ix_password_reset_tokens_expires_at", "expires_at"),
    )


class EmailVerificationToken(_SingleUseToken):
    __tablename__ = "email_verification_tokens"

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    __table_args__ = (
        Index("uq_email_verification_tokens_token_hash", "token_hash", unique=True),
        Index("ix_email_verification_tokens_expires_at", "expires_at"),
    )
