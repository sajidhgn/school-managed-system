"""Invitation model (spec §7).

WHY THIS FILE EXISTS
    Requirement #7: a principal invites teachers and accountants by email. The
    invitation is the only path by which a new human enters an existing organization,
    which makes it the organization's entire attack surface for unwanted members.
    It gets its own module because the guards matter more than the CRUD.

RESPONSIBILITY
    Define the invitation row and its lifecycle. The flow logic -- escalation checks,
    entitlement checks, the two accept branches -- lives in the service.

INTERACTIONS
    * `modules/invitations/service.py` creates, verifies, accepts, resends, revokes.
    * On accept, creates a `memberships` row and (for new users) a `users` row.

=============================================================================
WHY THE TOKEN IS STORED AS A DIGEST, AND WHAT THAT COSTS
=============================================================================
    `token_hash` holds SHA-256 of a 256-bit random token. The raw value exists in
    exactly one place: the email that was sent. Not in the database, not in the logs.

    The consequence to be aware of: nobody -- not support, not the principal who sent
    it -- can retrieve the link after the fact. "Resend" therefore generates a NEW
    token and invalidates the old one; it cannot re-send the original. That is a
    deliberate trade. The alternative, storing the raw token so it can be re-read,
    means a read-only database leak hands the attacker a working membership in every
    organization with a pending invite.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, str_enum
from app.db.mixins import (
    CreatedAtMixin,
    SchoolScopedMixin,
    TenantMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, types only
    from app.modules.rbac.models import Role
    from app.modules.tenancy.models import School


class InvitationStatus(StrEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class Invitation(Base, UUIDPrimaryKeyMixin, TenantMixin, SchoolScopedMixin, CreatedAtMixin):
    """A pending offer of membership in one scope of one organization."""

    __tablename__ = "invitations"

    role_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    """The role the invitee will hold. CASCADE: deleting a role kills its pending
    invitations, which is correct -- accepting an invite to a role that no longer
    exists could not produce a valid membership anyway."""

    email: Mapped[str] = mapped_column(CITEXT, nullable=False)
    """CITEXT so the exact-match guard in §7.2 is case-insensitive. An invitation
    addressed to `Ayesha@school.pk` must be acceptable by the account
    `ayesha@school.pk` -- they are the same mailbox, and rejecting it would be an
    incomprehensible failure for the user."""

    full_name: Mapped[str | None] = mapped_column(String(200))

    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    """SHA-256 hex of the raw token. See the module docstring."""

    status: Mapped[InvitationStatus] = mapped_column(
        str_enum(InvitationStatus, name="status"),
        nullable=False,
        default=InvitationStatus.PENDING,
    )

    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    invited_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )

    accepted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    accepted_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )

    resent_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Eager-loaded by the list endpoint, which shows the invited role's name next to
    # each pending invitation. Without it, a page of 50 invitations is 51 queries.
    role: Mapped[Role] = relationship(lazy="select")
    school: Mapped[School | None] = relationship(lazy="select")

    __table_args__ = (
        # Lookup by digest is the accept hot path. Unique because two live invitations
        # sharing a digest would make acceptance ambiguous.
        Index("uq_invitations_token_hash", "token_hash", unique=True),
        # At most ONE pending invitation per (org, school, email). Partial on
        # `status = 'pending'` so that a previously accepted or revoked invite does
        # not block a fresh one -- a teacher who left and is re-hired must be
        # invitable again.
        #
        # NULLS NOT DISTINCT so the constraint also covers org-level invitations,
        # where `school_id IS NULL`; without it, an organization could accumulate
        # unlimited pending org-level invites for the same address.
        Index(
            "uq_invitations_pending_email",
            "organization_id",
            "school_id",
            "email",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("status = 'pending'"),
        ),
        Index("ix_invitations_organization_id_status", "organization_id", "status"),
        Index("ix_invitations_expires_at", "expires_at"),
    )

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= datetime.now(UTC)

    @property
    def is_acceptable(self) -> bool:
        """Whether this invitation may still be redeemed.

        Status and expiry are checked together, and BOTH before any token comparison.
        A valid digest on an expired or already-accepted invitation is still a failed
        acceptance -- and an invite link sitting in an old inbox is exactly what an
        attacker with mailbox access would replay.
        """
        return self.status is InvitationStatus.PENDING and not self.is_expired
