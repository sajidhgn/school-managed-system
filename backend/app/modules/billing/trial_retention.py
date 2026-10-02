"""What happens to an organization whose trial ended without a plan being chosen.

=============================================================================
THE TIMELINE
=============================================================================
    day 0      trial ends -> `process_billing_lifecycle` expires the subscription and
               suspends the organization. Suspended means READ-ONLY: every module
               stays visible, every write is refused (`require()` in api/deps.py).
               The owner is emailed that the trial ended and when deletion happens.
    day G-N    second email: the account will be deleted in N days.
    day G      the organization and every row it owns are permanently deleted.

    G is `TRIAL_GRACE_DAYS` (7), N is `TRIAL_DELETION_NOTICE_DAYS` (2).

    Choosing a plan at any point before day G moves the subscription off EXPIRED
    and this module never touches the organization again.

=============================================================================
WHY THE DELETION WAITS FOR THE WARNING, NOT JUST FOR THE CALENDAR
=============================================================================
    The deletion date is `trial_ends_at + G`, but never earlier than N days after the
    warning email was actually SENT. If cron stopped for a week, or SMTP was down on
    the day the warning was due, a calendar-only rule would delete a school's records
    with no notice at all. Here a failed send records nothing, is retried on the next
    run, and the deletion moves back with it.

    The two emails are idempotent through `subscription_events` markers rather than
    a new column: the events table is already the subscription's history, and the
    markers are deleted along with it.

=============================================================================
WHY A HARD DELETE AND NOT `_anonymize_organization`
=============================================================================
    A cancelled PAYING customer gets the 30-day anonymization in `jobs.py`: their
    invoices are financial records we are obliged to keep. A trial that never paid
    has no such records, and keeping a stranger's student data "anonymized" forever
    is liability with no purpose. What survives is one `platform_audit_logs` row
    saying the account existed and when it was removed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import structlog
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import PlatformAuditAction, record_platform_audit
from app.common.email.sender import EmailSender
from app.common.email.templates import ActionPurpose, render_action_email
from app.core.config import Settings
from app.db.base import Base
from app.db.session import bind_tenant
from app.modules.auth.models import User
from app.modules.billing.models import Subscription, SubscriptionEvent, SubscriptionStatus
from app.modules.guardians.models import Guardian, GuardianIdentity
from app.modules.rbac.models import Membership
from app.modules.tenancy.models import Organization, OrganizationStatus

logger = structlog.get_logger(__name__)

EXPIRED_NOTICE_EVENT = "trial.expired_notice_sent"
DELETION_WARNING_EVENT = "trial.deletion_warning_sent"


async def _marker_sent_at(
    session: AsyncSession, subscription: Subscription, event_type: str
) -> datetime | None:
    """When this notice went out for the CURRENT trial expiry, or None.

    Bounded below by `trial_ends_at` so a marker left over from an earlier expiry
    (expired, upgraded, somehow expired again) cannot fast-forward a new deletion.
    """
    assert subscription.trial_ends_at is not None
    return (
        await session.execute(
            select(func.max(SubscriptionEvent.created_at)).where(
                SubscriptionEvent.subscription_id == subscription.id,
                SubscriptionEvent.event_type == event_type,
                SubscriptionEvent.created_at >= subscription.trial_ends_at,
            )
        )
    ).scalar_one_or_none()


def _deletion_date(
    subscription: Subscription, warning_sent_at: datetime | None, settings: Settings
) -> datetime:
    assert subscription.trial_ends_at is not None
    scheduled = subscription.trial_ends_at + timedelta(days=settings.TRIAL_GRACE_DAYS)
    if warning_sent_at is not None:
        scheduled = max(
            scheduled, warning_sent_at + timedelta(days=settings.TRIAL_DELETION_NOTICE_DAYS)
        )
    return scheduled


async def trial_deletion_date(
    session: AsyncSession,
    organization_id: UUID,
    settings: Settings,
    *,
    now: datetime | None = None,
) -> datetime | None:
    """When an expired-trial organization will be deleted, or None if it will not.

    For the in-app banner. Before the warning has gone out the date is a projection
    -- it can only move later, never earlier, so showing it is never a false promise.
    """
    subscription = (
        await session.execute(
            select(Subscription).where(Subscription.organization_id == organization_id)
        )
    ).scalar_one_or_none()
    if (
        subscription is None
        or subscription.status is not SubscriptionStatus.EXPIRED
        or subscription.trial_ends_at is None
    ):
        return None
    warning_sent_at = await _marker_sent_at(session, subscription, DELETION_WARNING_EVENT)
    scheduled = _deletion_date(subscription, warning_sent_at, settings)
    if warning_sent_at is None:
        # Not warned yet: the earliest it can now happen is N days from today.
        now = now or datetime.now(UTC)
        scheduled = max(scheduled, now + timedelta(days=settings.TRIAL_DELETION_NOTICE_DAYS))
    return scheduled


async def process_trial_retention(
    session: AsyncSession,
    organization_id: UUID,
    *,
    settings: Settings,
    email_sender: EmailSender | None,
    now: datetime | None = None,
) -> list[str]:
    """Send the expiry/warning emails and delete the organization when due.

    Idempotent: safe to run any number of times a day. Runs AFTER
    `process_billing_lifecycle` so a trial expiring on this pass is noticed on it.
    """
    now = now or datetime.now(UTC)
    organization = await session.get(Organization, organization_id)
    subscription = (
        await session.execute(
            select(Subscription).where(Subscription.organization_id == organization_id)
        )
    ).scalar_one_or_none()
    if (
        organization is None
        or organization.deleted_at is not None
        or subscription is None
        or subscription.status is not SubscriptionStatus.EXPIRED
        or subscription.trial_ends_at is None
        # A platform admin reactivated it by hand: their decision, not ours.
        or organization.status is not OrganizationStatus.SUSPENDED
    ):
        return []

    events: list[str] = []
    warning_sent_at = await _marker_sent_at(session, subscription, DELETION_WARNING_EVENT)
    warning_due_at = subscription.trial_ends_at + timedelta(
        days=settings.TRIAL_GRACE_DAYS - settings.TRIAL_DELETION_NOTICE_DAYS
    )

    if warning_sent_at is None:
        if now >= warning_due_at:
            # Sending the warning covers the expiry notice too when a late run finds
            # both due at once -- two emails in one minute reads as a malfunction.
            deletion_at = _deletion_date(subscription, now, settings)
            if await _notify(
                session,
                organization,
                subscription,
                purpose=ActionPurpose.TRIAL_DELETION_WARNING,
                event_type=DELETION_WARNING_EVENT,
                deletion_at=deletion_at,
                settings=settings,
                email_sender=email_sender,
            ):
                events.append(DELETION_WARNING_EVENT)
        elif await _marker_sent_at(session, subscription, EXPIRED_NOTICE_EVENT) is None:
            deletion_at = _deletion_date(subscription, None, settings)
            if await _notify(
                session,
                organization,
                subscription,
                purpose=ActionPurpose.TRIAL_EXPIRED,
                event_type=EXPIRED_NOTICE_EVENT,
                deletion_at=deletion_at,
                settings=settings,
                email_sender=email_sender,
            ):
                events.append(EXPIRED_NOTICE_EVENT)
        return events

    if now >= _deletion_date(subscription, warning_sent_at, settings):
        await purge_organization(session, organization, now=now)
        events.append("organization.purged")
    return events


async def _recipients(session: AsyncSession, organization: Organization) -> list[str]:
    owner_email = (
        await session.execute(select(User.email).where(User.id == organization.owner_user_id))
    ).scalar_one_or_none()
    addresses: list[str] = []
    for address in (owner_email, organization.billing_email):
        if address and address.lower() not in {a.lower() for a in addresses}:
            addresses.append(address)
    return addresses


async def _notify(
    session: AsyncSession,
    organization: Organization,
    subscription: Subscription,
    *,
    purpose: ActionPurpose,
    event_type: str,
    deletion_at: datetime,
    settings: Settings,
    email_sender: EmailSender | None,
) -> bool:
    """Email the owner (and billing contact), then record the marker.

    Returns False -- and records nothing -- when the send failed, so the next run
    retries it. The deletion is gated on the warning marker, so a send that never
    succeeds means a deletion that never happens; that is the safe failure.
    """
    if email_sender is None:
        return False
    owner_name = (
        await session.execute(select(User.full_name).where(User.id == organization.owner_user_id))
    ).scalar_one_or_none()
    details = [
        ("Organization", organization.name),
        ("Deletion date", deletion_at.strftime("%d %B %Y")),
    ]
    try:
        for address in await _recipients(session, organization):
            await email_sender.send(
                render_action_email(
                    to=address,
                    action_url=f"{settings.FRONTEND_URL.rstrip('/')}/billing",
                    purpose=purpose,
                    recipient_name=owner_name,
                    details=details,
                    expiry_text=None,
                    settings=settings,
                )
            )
    except Exception:  # any failure means "not notified", never "notified"
        logger.exception(
            "trial_notice_send_failed",
            organization_id=str(organization.id),
            notice=event_type,
        )
        return False

    session.add(
        SubscriptionEvent(
            organization_id=organization.id,
            subscription_id=subscription.id,
            event_type=event_type,
            from_plan_id=subscription.plan_id,
            to_plan_id=subscription.plan_id,
            payload={"source": "lifecycle_job", "deletion_at": deletion_at.isoformat()},
        )
    )
    await session.flush()
    return True


async def purge_organization(
    session: AsyncSession,
    organization: Organization,
    *,
    now: datetime,
) -> None:
    """Permanently delete an organization, every tenant row, and its exclusive users.

    The session must be bound to this organization. Tenant tables are emptied
    children-first in FK dependency order (SQLAlchemy's `sorted_tables`, reversed)
    rather than relying on `organizations` ON DELETE CASCADE: about thirty
    intra-tenant FKs are RESTRICT -- the fee ledger above all -- and a cascade that
    reaches `students` before `student_ledger_entries` aborts half way.
    """
    organization_id = organization.id

    # Collect the global rows tied to this org BEFORE the memberships and guardian
    # links that identify them are gone.
    await bind_tenant(session, None, platform_admin=True)
    try:
        exclusive_user_ids = list(
            (
                await session.execute(
                    select(Membership.user_id)
                    .group_by(Membership.user_id)
                    .having(func.bool_and(Membership.organization_id == organization_id))
                )
            ).scalars()
        )
        exclusive_user_ids = list({*exclusive_user_ids, organization.owner_user_id})
        identity_ids = set(
            (
                await session.execute(
                    select(Guardian.identity_id).where(Guardian.organization_id == organization_id)
                )
            ).scalars()
        )
        shared_identity_ids = (
            set(
                (
                    await session.execute(
                        select(Guardian.identity_id).where(
                            Guardian.identity_id.in_(identity_ids),
                            Guardian.organization_id != organization_id,
                        )
                    )
                ).scalars()
            )
            if identity_ids
            else set()
        )
        # The owner is only "exclusive" if they hold no membership elsewhere.
        owner_elsewhere = (
            await session.execute(
                select(func.count())
                .select_from(Membership)
                .where(
                    Membership.user_id == organization.owner_user_id,
                    Membership.organization_id != organization_id,
                )
            )
        ).scalar_one()
        if owner_elsewhere:
            exclusive_user_ids.remove(organization.owner_user_id)
    finally:
        await bind_tenant(session, organization_id)

    snapshot = {
        "organization_id": str(organization_id),
        "name": organization.name,
        "slug": organization.slug,
        "billing_email": organization.billing_email,
        "reason": "trial_expired_without_plan",
        "users_deleted": len(exclusive_user_ids),
    }
    session.expunge_all()

    for table in reversed(Base.metadata.sorted_tables):
        if "organization_id" in table.c:
            await session.execute(delete(table).where(table.c.organization_id == organization_id))
    await session.execute(delete(Organization).where(Organization.id == organization_id))

    for user_id in exclusive_user_ids:
        try:
            async with session.begin_nested():
                await session.execute(delete(User).where(User.id == user_id))
        except IntegrityError:
            # Still referenced by a row in some other organization (an audit actor,
            # say). Their data goes; the row itself stays as an inert tombstone.
            await session.execute(
                update(User)
                .where(User.id == user_id)
                .values(
                    email=f"deleted+{user_id.hex}@anonymized.invalid",
                    full_name="Deleted user",
                    phone=None,
                    avatar_url=None,
                    password_hash=None,
                    deleted_at=now,
                )
            )

    orphaned_identities = identity_ids - shared_identity_ids
    if orphaned_identities:
        await session.execute(
            delete(GuardianIdentity).where(GuardianIdentity.id.in_(orphaned_identities))
        )

    await record_platform_audit(
        session,
        action=PlatformAuditAction.ORGANIZATION_PURGED,
        entity_type="organization",
        entity_id=organization_id,
        metadata=snapshot,
    )
    await session.flush()
    logger.info("organization_purged", organization_id=str(organization_id))
