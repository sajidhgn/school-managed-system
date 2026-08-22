"""Scheduled billing lifecycle, retention, and post-cancellation privacy work."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditAction, record_audit
from app.db.session import bind_tenant
from app.modules.auth.models import User
from app.modules.billing.models import (
    Payment,
    PaymentStatus,
    Subscription,
    SubscriptionEvent,
    SubscriptionStatus,
)
from app.modules.platform_admin.models import Plan
from app.modules.rbac.models import AuditLog, Membership
from app.modules.students.models import Student
from app.modules.tenancy.models import Organization, OrganizationStatus

PAST_DUE_GRACE = timedelta(days=7)
CANCELLATION_RETENTION = timedelta(days=30)


async def process_billing_lifecycle(
    session: AsyncSession,
    organization_id: UUID,
    *,
    now: datetime | None = None,
) -> list[str]:
    """Advance one tenant through deterministic, idempotent billing transitions."""
    now = now or datetime.now(UTC)
    organization = await session.get(Organization, organization_id)
    subscription = (
        await session.execute(
            select(Subscription).where(Subscription.organization_id == organization_id)
        )
    ).scalar_one_or_none()
    if organization is None or subscription is None:
        return []

    events: list[str] = []
    if (
        subscription.cancel_at_period_end
        and subscription.current_period_end is not None
        and subscription.current_period_end <= now
        and subscription.status is not SubscriptionStatus.CANCELLED
    ):
        subscription.status = SubscriptionStatus.CANCELLED
        subscription.cancelled_at = now
        organization.status = OrganizationStatus.CANCELLED
        events.append("subscription.period_cancelled")
        await _record_transition(
            session,
            organization_id=organization_id,
            subscription=subscription,
            event_type="subscription.period_cancelled",
            action=AuditAction.SUBSCRIPTION_PERIOD_CANCELLED,
        )

    elif (
        subscription.status is SubscriptionStatus.TRIALING
        and subscription.trial_ends_at is not None
        and subscription.trial_ends_at <= now
    ):
        subscription.status = SubscriptionStatus.EXPIRED
        organization.status = OrganizationStatus.SUSPENDED
        events.append("subscription.trial_expired")
        await _record_transition(
            session,
            organization_id=organization_id,
            subscription=subscription,
            event_type="subscription.trial_expired",
            action=AuditAction.SUBSCRIPTION_TRIAL_EXPIRED,
        )

    elif subscription.status is SubscriptionStatus.PAST_DUE:
        failed_at = (
            await session.execute(
                select(func.max(Payment.created_at)).where(
                    Payment.organization_id == organization_id,
                    Payment.status == PaymentStatus.FAILED,
                )
            )
        ).scalar_one_or_none()
        grace_started = failed_at or subscription.current_period_end or subscription.updated_at
        if grace_started + PAST_DUE_GRACE <= now:
            subscription.status = SubscriptionStatus.SUSPENDED
            organization.status = OrganizationStatus.SUSPENDED
            events.append("subscription.suspended")
            await _record_transition(
                session,
                organization_id=organization_id,
                subscription=subscription,
                event_type="subscription.suspended",
                action=AuditAction.SUBSCRIPTION_SUSPENDED,
            )

    if (
        subscription.status is SubscriptionStatus.CANCELLED
        and subscription.cancelled_at is not None
        and subscription.cancelled_at + CANCELLATION_RETENTION <= now
        and organization.deleted_at is None
    ):
        await _anonymize_organization(session, organization, now=now)
        events.append("organization.anonymized")

    return events


async def purge_expired_audit_logs(
    session: AsyncSession,
    organization_id: UUID,
    *,
    now: datetime | None = None,
) -> int:
    """Delete tenant audit entries older than the current plan's retention."""
    now = now or datetime.now(UTC)
    retention_days = (
        await session.execute(
            select(Plan.limits["audit_retention_days"].as_integer())
            .join(Subscription, Subscription.plan_id == Plan.id)
            .where(Subscription.organization_id == organization_id)
        )
    ).scalar_one_or_none()
    if retention_days is None or retention_days < 0:
        return 0
    result = await session.execute(
        delete(AuditLog).where(
            AuditLog.organization_id == organization_id,
            AuditLog.created_at < now - timedelta(days=retention_days),
        )
    )
    return int(result.rowcount or 0)  # type: ignore[attr-defined]


async def _record_transition(
    session: AsyncSession,
    *,
    organization_id: UUID,
    subscription: Subscription,
    event_type: str,
    action: str,
) -> None:
    session.add(
        SubscriptionEvent(
            organization_id=organization_id,
            subscription_id=subscription.id,
            event_type=event_type,
            from_plan_id=subscription.plan_id,
            to_plan_id=subscription.plan_id,
            payload={"source": "lifecycle_job"},
        )
    )
    await record_audit(
        session,
        organization_id=organization_id,
        action=action,
        entity_type="subscription",
        entity_id=subscription.id,
        after={"status": subscription.status.value},
    )


async def _anonymize_organization(
    session: AsyncSession,
    organization: Organization,
    *,
    now: datetime,
) -> None:
    organization_id = organization.id
    marker = organization_id.hex
    await record_audit(
        session,
        organization_id=organization_id,
        action=AuditAction.ORGANIZATION_ANONYMIZED,
        entity_type="organization",
        entity_id=organization_id,
    )
    await session.flush()

    await session.execute(
        update(Student)
        .where(Student.organization_id == organization_id)
        .values(
            first_name="Anonymized",
            last_name="Student",
            address=None,
            photo_url=None,
            guardian_name=None,
            guardian_phone=None,
            guardian_email=None,
            emergency_contact_name=None,
            emergency_contact_phone=None,
        )
    )

    await bind_tenant(session, None, platform_admin=True)
    try:
        exclusive_user_ids = list(
            (
                await session.execute(
                    select(Membership.user_id)
                    .where(Membership.deleted_at.is_(None))
                    .group_by(Membership.user_id)
                    .having(func.bool_and(Membership.organization_id == organization_id))
                )
            ).scalars()
        )
    finally:
        await bind_tenant(session, organization_id)

    if exclusive_user_ids:
        for position, user_id in enumerate(exclusive_user_ids, start=1):
            await session.execute(
                update(User)
                .where(User.id == user_id)
                .values(
                    email=f"deleted+{marker}.{position}@anonymized.invalid",
                    full_name="Deleted user",
                    phone=None,
                    avatar_url=None,
                    password_hash=None,
                    deleted_at=now,
                )
            )

    organization.name = f"Anonymized organization {marker[:8]}"
    organization.slug = f"anonymized-{marker}"
    organization.billing_email = None
    organization.tax_id = None
    organization.deleted_at = now
