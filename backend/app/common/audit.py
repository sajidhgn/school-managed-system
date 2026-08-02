"""Audit trail writers.

WHY THIS FILE EXISTS
    Spec §4.4: "Every auth mutation writes an `audit_logs` row", and §7.1 requires
    one on every invitation action. Scattering hand-rolled `AuditLog(...)`
    constructions through six services guarantees drift -- different action names for
    the same event, forgotten actor ids, and eventually a mutation nobody recorded.

RESPONSIBILITY
    Provide one call for tenant audit rows and one for platform audit rows, plus the
    canonical action-name constants. No querying -- reading the trail is the audit
    module's job.

INTERACTIONS
    Called by every service that mutates state. Writes into the caller's existing
    session so the audit row commits in the SAME transaction as the change it
    describes.

=============================================================================
THE AUDIT ROW SHARES THE CALLER'S TRANSACTION. THAT IS THE WHOLE DESIGN.
=============================================================================
    It would be tempting to write audit rows on a separate connection, or to queue
    them, so that an audit failure cannot fail a user's request. Both are wrong here.

    Same transaction means the two facts -- "the member was suspended" and "we
    recorded that the member was suspended" -- are atomic. Either both happened or
    neither did. With a separate connection, a crash between them produces a change
    with no record, which is exactly the state an audit trail exists to make
    impossible.

    The cost is real: an audit write that fails rolls back the user's action. That is
    the correct trade for a system holding minors' records, where "we cannot tell you
    who changed this" is a worse outcome than "the change did not go through".
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.platform_admin.models import PlatformAuditLog
from app.modules.rbac.models import AuditLog


class AuditAction:
    """Canonical action names.

    Constants rather than free strings so that a typo is an AttributeError at import
    time, and so the set of auditable actions is enumerable -- which is what makes
    "alert when X happens" possible without grepping the codebase.

    Naming is `subject.verb_past_tense`, always past tense: an audit row records what
    HAPPENED, never what was attempted.
    """

    # --- Authentication -----------------------------------------------------
    USER_REGISTERED = "user.registered"
    USER_EMAIL_VERIFIED = "user.email_verified"
    USER_LOGGED_IN = "user.logged_in"
    USER_LOGIN_FAILED = "user.login_failed"
    USER_LOCKED_OUT = "user.locked_out"
    USER_LOGGED_OUT = "user.logged_out"
    USER_LOGGED_OUT_ALL = "user.logged_out_all"
    USER_PASSWORD_RESET_REQUESTED = "user.password_reset_requested"
    USER_PASSWORD_RESET = "user.password_reset"
    SESSION_CONTEXT_SWITCHED = "session.context_switched"
    SESSION_REUSE_DETECTED = "session.reuse_detected"

    # --- Organization & schools ---------------------------------------------
    ORGANIZATION_CREATED = "organization.created"
    ORGANIZATION_UPDATED = "organization.updated"
    OWNERSHIP_TRANSFERRED = "organization.ownership_transferred"
    SCHOOL_CREATED = "school.created"
    SCHOOL_UPDATED = "school.updated"
    SCHOOL_ARCHIVED = "school.archived"

    # --- Access control -----------------------------------------------------
    ROLE_CREATED = "role.created"
    ROLE_UPDATED = "role.updated"
    ROLE_DELETED = "role.deleted"
    ROLE_PERMISSIONS_CHANGED = "role.permissions_changed"
    MEMBER_ROLE_CHANGED = "member.role_changed"
    MEMBER_SUSPENDED = "member.suspended"
    MEMBER_REACTIVATED = "member.reactivated"
    MEMBER_REMOVED = "member.removed"

    # --- Invitations --------------------------------------------------------
    INVITATION_SENT = "invitation.sent"
    INVITATION_RESENT = "invitation.resent"
    INVITATION_REVOKED = "invitation.revoked"
    INVITATION_ACCEPTED = "invitation.accepted"

    # --- Billing ------------------------------------------------------------
    SUBSCRIPTION_CREATED = "subscription.created"
    SUBSCRIPTION_PLAN_CHANGED = "subscription.plan_changed"
    SUBSCRIPTION_CANCELLED = "subscription.cancelled"
    PAYMENT_RECEIVED = "payment.received"
    PAYMENT_FAILED = "payment.failed"
    PLAN_LIMIT_EXCEEDED = "entitlement.limit_exceeded"


class PlatformAuditAction:
    """Action names for platform-operator activity."""

    ADMIN_LOGGED_IN = "platform_admin.logged_in"
    ADMIN_LOGIN_FAILED = "platform_admin.login_failed"
    ORGANIZATION_SUSPENDED = "platform.organization_suspended"
    ORGANIZATION_REACTIVATED = "platform.organization_reactivated"
    ORGANIZATION_PLAN_OVERRIDDEN = "platform.organization_plan_overridden"
    IMPERSONATION_STARTED = "platform.impersonation_started"
    PLAN_CREATED = "platform.plan_created"
    PLAN_UPDATED = "platform.plan_updated"
    PLAN_DELETED = "platform.plan_deleted"


async def record_audit(
    session: AsyncSession,
    *,
    organization_id: UUID,
    action: str,
    school_id: UUID | None = None,
    actor_user_id: UUID | None = None,
    actor_membership_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> AuditLog:
    """Append a tenant audit row inside the caller's transaction.

    `actor_user_id` is nullable because some auditable events have no human actor --
    a failed login for an address that matches no account, or a subscription expiring
    on a schedule. Recording those with a null actor is more honest than attributing
    them to a system user that does not exist.

    No `flush()`: the row goes out with the rest of the unit of work. Flushing here
    would force a round-trip in the middle of every mutation for an id nobody reads.
    """
    entry = AuditLog(
        organization_id=organization_id,
        school_id=school_id,
        actor_user_id=actor_user_id,
        actor_membership_id=actor_membership_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        before=before,
        after=after,
        ip=ip,
        user_agent=user_agent,
    )
    session.add(entry)
    return entry


async def record_platform_audit(
    session: AsyncSession,
    *,
    action: str,
    actor_admin_id: UUID | None = None,
    entity_type: str | None = None,
    entity_id: UUID | None = None,
    target_organization_id: UUID | None = None,
    metadata: dict[str, Any] | None = None,
    ip: str | None = None,
    user_agent: str | None = None,
) -> PlatformAuditLog:
    """Append a platform audit row.

    Goes to a different table from `record_audit` because these actions cross
    organizations. See `PlatformAuditLog`'s docstring for why containment matters:
    a suspended organization must not be able to influence the visibility of the
    record describing its own suspension.
    """
    entry = PlatformAuditLog(
        actor_admin_id=actor_admin_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        target_organization_id=target_organization_id,
        audit_metadata=metadata or {},
        ip=ip,
        user_agent=user_agent,
    )
    session.add(entry)
    return entry
