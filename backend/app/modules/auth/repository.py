"""Data access for the auth aggregate: users, OTP codes, refresh tokens.

WHY THIS FILE EXISTS
    All SQL touching the three auth tables lives here. These tables are OUTSIDE RLS
    (see the module docstring in models.py), so the repositories are the ONLY place
    the compensating `school_id` filter is applied -- confined here and nowhere else.

INTERACTIONS
    * Constructed by `AuthService` with the request-scoped session.
    * `UserRepository.get_by_email` is the pre-tenant login lookup; it intentionally
      does NOT filter by school (login has no school selector -- email is globally
      unique among live users).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, ClassVar, cast
from uuid import UUID

from sqlalchemy import CursorResult, func, update

from app.common.repository import BaseRepository
from app.core.otp import OtpPurpose
from app.modules.auth.models import OtpCode, RefreshToken, User


class UserRepository(BaseRepository[User]):
    """CRUD + credential/tenant-scoped finders for users."""

    model = User
    sortable_fields: ClassVar[frozenset[str]] = frozenset(
        {"full_name", "email", "role", "created_at", "last_login_at"}
    )

    async def get_by_email(self, email: str) -> User | None:
        """Find a live user by email, across all schools.

        Used by login / forgot-password, which run before any tenant is known. Safe
        because `email` is globally unique among non-deleted users.
        """
        return await self.find_one(User.email == email)

    async def get_in_school(self, user_id: UUID, school_id: UUID) -> User | None:
        """Fetch a user constrained to a school -- the compensating filter for the
        RLS these tables cannot have. Use for tenant-scoped staff reads."""
        return await self.find_one(User.id == user_id, User.school_id == school_id)

    async def email_taken(self, email: str) -> bool:
        return await self.exists(User.email == email)

    async def set_login_failure(
        self, user_id: UUID, *, attempts: int, locked_until: datetime | None
    ) -> None:
        """Persist the failed-login counter / lockout by id, without loading the row.

        Called from a SEPARATE transaction (see `AuthService._record_failed_login`),
        because the login request itself raises a 401 and would otherwise roll this
        write back -- leaving the counter forever at zero and lockout unreachable.
        """
        stmt = (
            update(User)
            .where(User.id == user_id)
            .values(failed_login_attempts=attempts, locked_until=locked_until)
        )
        await self.session.execute(stmt)


class OtpRepository(BaseRepository[OtpCode]):
    """CRUD + finders for one-time-code challenges.

    `otp_codes` has no soft-delete: consumed/expired codes are purged, not retained.
    """

    model = OtpCode

    async def latest_active(self, email: str, purpose: OtpPurpose) -> OtpCode | None:
        """The newest not-yet-consumed code for this address + flow.

        Matches the issuing index `ix_otp_codes_email_purpose_created`. Expiry and the
        attempt cap are checked by the service via `OtpCode.is_usable`; this only
        excludes already-consumed codes so a redeemed code is never reconsidered.
        """
        stmt = (
            self._base_select()
            .where(
                OtpCode.email == email,
                OtpCode.purpose == purpose,
                OtpCode.consumed_at.is_(None),
            )
            .order_by(OtpCode.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def latest_for_cooldown(self, email: str, purpose: OtpPurpose) -> OtpCode | None:
        """The newest code of any state, to enforce the resend cooldown."""
        stmt = (
            self._base_select()
            .where(OtpCode.email == email, OtpCode.purpose == purpose)
            .order_by(OtpCode.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    """CRUD + revocation for persisted refresh-token handles."""

    model = RefreshToken

    async def get_by_jti(self, jti: str) -> RefreshToken | None:
        return await self.find_one(RefreshToken.jti == jti)

    async def revoke(self, token: RefreshToken) -> None:
        if token.revoked_at is None:
            await self.update(token, revoked_at=datetime.now(UTC))

    async def revoke_all_for_user(self, user_id: UUID) -> int:
        """Revoke every live refresh token for a user (used on password reset).

        Returns the number of sessions killed. A bulk UPDATE, not a load-then-save
        loop: a user could have many active sessions and this must be one round trip.
        """
        stmt = (
            update(RefreshToken)
            .where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=func.now())
        )
        result = await self.session.execute(stmt)
        # rowcount lives on CursorResult (what UPDATE returns), not the generic
        # Result protocol that `execute` is typed as returning -- hence the cast.
        return cast("CursorResult[Any]", result).rowcount or 0
