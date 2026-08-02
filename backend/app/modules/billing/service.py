"""Subscription lifecycle and webhook processing (spec §6).

WHY THIS FILE EXISTS
    Billing state changes arrive from two directions: the customer clicking in the
    app, and the gateway calling us asynchronously. Both mutate the same rows, and
    the second arrives unauthenticated, out of order, and more than once. Keeping
    that reconciliation in one place is the only way it stays comprehensible.

RESPONSIBILITY
    Create and change subscriptions, record plan-change history, and apply verified
    webhooks idempotently.

INTERACTIONS
    * `modules/auth/service.py::verify_email` -> `ensure_free_subscription`
    * `modules/billing/router.py` for the customer-facing endpoints.
    * `gateways/` through the `PaymentGateway` port, never a concrete adapter.

=============================================================================
WHY THE FREE PLAN IS A SUBSCRIPTION ROW AND NOT "NO SUBSCRIPTION"
=============================================================================
    It would be simpler to treat "no subscription row" as "on the free plan". It
    would also mean `EntitlementService` has to special-case a missing row on every
    single check, and the free plan's limits would live in code rather than in the
    `plans` table the super admin manages.

    Giving every organization a real subscription row means one code path, one place
    limits are defined, and an upgrade is an UPDATE rather than an INSERT with
    different semantics.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditAction, record_audit
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.modules.billing.entitlements import EntitlementService
from app.modules.billing.gateways.base import (
    GatewayEvent,
    GatewayEventType,
    PaymentGateway,
)
from app.modules.billing.models import (
    BillingCycle,
    OrganizationUsage,
    Payment,
    PaymentStatus,
    Subscription,
    SubscriptionEvent,
    SubscriptionStatus,
    WebhookEvent,
)
from app.modules.platform_admin.models import Plan, PlanCode
from app.modules.tenancy.models import Organization, OrganizationStatus

logger = get_logger(__name__)

# Grace period after a failed charge before access is restricted (spec §6.3).
PAST_DUE_GRACE = timedelta(days=7)


async def _plan_by_code(session: AsyncSession, code: str) -> Plan:
    plan = (
        await session.execute(select(Plan).where(Plan.code == code, Plan.is_active.is_(True)))
    ).scalar_one_or_none()
    if plan is None:
        raise NotFoundError(f"No active plan with code '{code}'.", code="PLAN_NOT_FOUND")
    return plan


async def ensure_free_subscription(session: AsyncSession, *, organization_id: UUID) -> Subscription:
    """Give a newly verified organization its free-plan subscription and usage row.

    IDEMPOTENT. Called from email verification, which a user can trigger twice by
    double-clicking the link or by a retried request. Returning the existing row
    rather than raising means the second call is harmless.
    """
    existing = (
        await session.execute(
            select(Subscription).where(Subscription.organization_id == organization_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    plan = await _plan_by_code(session, PlanCode.FREE.value)
    now = datetime.now(UTC)

    subscription = Subscription(
        organization_id=organization_id,
        plan_id=plan.id,
        # ACTIVE, not TRIALING: the free plan has nothing to trial. Marking it
        # trialing would start a clock that, on expiry, would suspend an
        # organization that never owed anything.
        status=SubscriptionStatus.ACTIVE,
        billing_cycle=BillingCycle.MONTHLY,
        current_period_start=now,
        current_period_end=None,  # free plans do not renew
    )
    session.add(subscription)

    usage = (
        await session.execute(
            select(OrganizationUsage).where(OrganizationUsage.organization_id == organization_id)
        )
    ).scalar_one_or_none()
    if usage is None:
        session.add(OrganizationUsage(organization_id=organization_id))

    await session.flush()

    session.add(
        SubscriptionEvent(
            organization_id=organization_id,
            subscription_id=subscription.id,
            event_type="subscription.created",
            to_plan_id=plan.id,
            payload={"reason": "email_verified", "plan_code": plan.code},
        )
    )
    return subscription


class BillingService:
    """Customer-facing subscription operations."""

    def __init__(self, session: AsyncSession, gateway: PaymentGateway) -> None:
        self.session = session
        self.gateway = gateway
        self.entitlements = EntitlementService(session)

    async def get_subscription(self, organization_id: UUID) -> tuple[Subscription, Plan]:
        row = (
            await self.session.execute(
                select(Subscription, Plan)
                .join(Plan, Plan.id == Subscription.plan_id)
                .where(Subscription.organization_id == organization_id)
            )
        ).first()
        if row is None:
            raise NotFoundError("No subscription for this organization.", code="NO_SUBSCRIPTION")
        return row[0], row[1]

    async def change_plan(
        self,
        *,
        organization_id: UUID,
        plan_code: str,
        billing_cycle: BillingCycle,
        actor_user_id: UUID | None = None,
    ) -> Subscription:
        """Move an organization to a different plan.

        =====================================================================
        DOWNGRADE NEVER DELETES DATA (spec §6.2)
        =====================================================================
            If the new plan's limits sit below current usage, the organization moves
            to `over_limit`: every existing record stays readable and exportable, and
            only NEW creates are refused until usage falls under the cap or they
            upgrade again.

            The alternative -- reclaiming the excess by deleting schools or students
            -- destroys a customer's records as a side effect of a billing change.
            For a system holding minors' academic records that is not a product
            decision, it is a liability.
        """
        subscription, current_plan = await self.get_subscription(organization_id)
        new_plan = await _plan_by_code(self.session, plan_code)

        if new_plan.id == subscription.plan_id and subscription.billing_cycle is billing_cycle:
            raise ConflictError("The organization is already on this plan.", code="PLAN_UNCHANGED")
        if not new_plan.is_public:
            # Hidden plans (enterprise) are assigned by the super admin after a
            # negotiated contract. Letting a customer self-select one would give away
            # unlimited limits to anyone who guessed the code.
            raise ValidationError(
                "This plan is not available for self-service.", code="PLAN_NOT_SELF_SERVICE"
            )

        organization = await self.session.get(Organization, organization_id)
        if organization is None:
            raise NotFoundError("Organization not found.")

        if subscription.gateway_subscription_ref:
            remote = await self.gateway.change_plan(
                subscription_ref=subscription.gateway_subscription_ref,
                plan_code=new_plan.code,
                billing_cycle=billing_cycle.value,
            )
            subscription.current_period_start = remote.current_period_start
            subscription.current_period_end = remote.current_period_end
        else:
            customer = await self.gateway.create_customer(
                organization_id=str(organization_id),
                email=organization.billing_email or "",
                name=organization.name,
            )
            remote = await self.gateway.create_subscription(
                customer_ref=customer.customer_ref,
                plan_code=new_plan.code,
                billing_cycle=billing_cycle.value,
                trial_days=new_plan.trial_days,
            )
            subscription.gateway = self.gateway.name
            subscription.gateway_customer_ref = customer.customer_ref
            subscription.gateway_subscription_ref = remote.subscription_ref
            subscription.current_period_start = remote.current_period_start
            subscription.current_period_end = remote.current_period_end
            if new_plan.trial_days:
                subscription.trial_ends_at = remote.current_period_end

        previous_plan_id = subscription.plan_id
        subscription.plan_id = new_plan.id
        subscription.billing_cycle = billing_cycle
        subscription.status = (
            SubscriptionStatus.TRIALING if new_plan.trial_days else SubscriptionStatus.ACTIVE
        )
        subscription.cancel_at_period_end = False
        subscription.cancelled_at = None
        await self.session.flush()

        # Evaluated AFTER the plan is applied, so the check runs against the new
        # limits. Doing it before would compare usage to the plan they are leaving.
        if await self.entitlements.is_over_limit(organization_id):
            organization.status = OrganizationStatus.OVER_LIMIT
            logger.info(
                "organization_over_limit_after_downgrade",
                organization_id=str(organization_id),
                plan=new_plan.code,
            )
        elif organization.status is OrganizationStatus.OVER_LIMIT:
            # An upgrade that resolves the overage returns them to normal.
            organization.status = OrganizationStatus.ACTIVE

        self.session.add(
            SubscriptionEvent(
                organization_id=organization_id,
                subscription_id=subscription.id,
                event_type="subscription.plan_changed",
                from_plan_id=previous_plan_id,
                to_plan_id=new_plan.id,
                payload={
                    "from": current_plan.code,
                    "to": new_plan.code,
                    "billing_cycle": billing_cycle.value,
                },
            )
        )
        await record_audit(
            self.session,
            organization_id=organization_id,
            action=AuditAction.SUBSCRIPTION_PLAN_CHANGED,
            actor_user_id=actor_user_id,
            entity_type="subscription",
            entity_id=subscription.id,
            before={"plan": current_plan.code},
            after={"plan": new_plan.code, "billing_cycle": billing_cycle.value},
        )
        return subscription

    async def cancel(
        self,
        *,
        organization_id: UUID,
        at_period_end: bool = True,
        actor_user_id: UUID | None = None,
    ) -> Subscription:
        """Cancel the subscription, at period end by default (spec §6.3).

        Immediate cancellation is reserved for the super admin: a customer who has
        paid through the end of the month keeps access until then, because cutting it
        the moment they click cancel bills them for time they cannot use.
        """
        subscription, plan = await self.get_subscription(organization_id)

        if subscription.gateway_subscription_ref:
            await self.gateway.cancel(
                subscription_ref=subscription.gateway_subscription_ref,
                at_period_end=at_period_end,
            )

        subscription.cancel_at_period_end = at_period_end
        subscription.cancelled_at = datetime.now(UTC)
        if not at_period_end:
            subscription.status = SubscriptionStatus.CANCELLED
            organization = await self.session.get(Organization, organization_id)
            if organization is not None:
                organization.status = OrganizationStatus.CANCELLED

        self.session.add(
            SubscriptionEvent(
                organization_id=organization_id,
                subscription_id=subscription.id,
                event_type="subscription.cancelled",
                from_plan_id=plan.id,
                payload={"at_period_end": at_period_end},
            )
        )
        await record_audit(
            self.session,
            organization_id=organization_id,
            action=AuditAction.SUBSCRIPTION_CANCELLED,
            actor_user_id=actor_user_id,
            entity_type="subscription",
            entity_id=subscription.id,
            after={"at_period_end": at_period_end},
        )
        return subscription


class WebhookService:
    """Applies verified gateway events exactly once (spec §6.4)."""

    def __init__(self, session: AsyncSession, gateway: PaymentGateway) -> None:
        self.session = session
        self.gateway = gateway

    async def handle(self, *, payload: bytes, headers: dict[str, str]) -> bool:
        """Verify, record, then process. Returns False if this is a redelivery.

        =====================================================================
        ORDER IS THE WHOLE DESIGN: RECORD BEFORE PROCESSING
        =====================================================================
            Gateways retry -- on timeout, on a 500, and sometimes for no visible
            reason. The same `event_id` WILL arrive twice, and processing it twice
            means double-crediting a payment or double-extending a period.

            The unique index on `(gateway, gateway_event_id)` is the guard, and
            inserting BEFORE processing is what makes it sound. If the handler
            crashes midway, the row is already committed, the retry is recognised as
            a duplicate, and the partial work is reconciled deliberately rather than
            blindly repeated.

            Storing it after processing would leave a window where a crash loses the
            record entirely, and the retry would re-run the whole thing.
        """
        event = self.gateway.verify_and_parse(payload=payload, headers=headers)

        # =====================================================================
        # `ON CONFLICT DO NOTHING` RATHER THAN CATCHING IntegrityError
        # =====================================================================
        #   The obvious implementation inserts and catches the unique violation.
        #   That does not work cleanly here: by the time the constraint fires, the
        #   transaction is already poisoned, and every later statement in the same
        #   request fails with PendingRollbackError. A SAVEPOINT can contain it, but
        #   the ORM object stays pending in the session and is re-flushed later,
        #   re-raising the same error somewhere far less obvious.
        #
        #   `ON CONFLICT DO NOTHING ... RETURNING id` asks the database the question
        #   directly: a returned id means we inserted it, None means someone already
        #   had it. One statement, no exception, no poisoned transaction -- and it is
        #   still perfectly atomic under concurrent redelivery, because the unique
        #   index is what arbitrates.
        insert = (
            pg_insert(WebhookEvent)
            .values(
                gateway=self.gateway.name,
                gateway_event_id=event.event_id,
                event_type=event.event_type.value,
                payload=event.raw,
            )
            .on_conflict_do_nothing(index_elements=["gateway", "gateway_event_id"])
            .returning(WebhookEvent.id)
        )
        inserted_id = (await self.session.execute(insert)).scalar_one_or_none()

        if inserted_id is None:
            logger.info(
                "webhook_duplicate_ignored",
                gateway=self.gateway.name,
                event_id=event.event_id,
            )
            return False

        record = await self.session.get(WebhookEvent, inserted_id)
        assert record is not None  # just inserted in this transaction

        await self._apply(event, record)
        record.processed_at = datetime.now(UTC)
        return True

    async def _apply(self, event: GatewayEvent, record: WebhookEvent) -> None:
        """Route a normalised event to its state change."""
        if event.subscription_ref is None:
            logger.info("webhook_without_subscription_ref", event_type=event.event_type.value)
            return

        subscription = (
            await self.session.execute(
                select(Subscription).where(
                    Subscription.gateway_subscription_ref == event.subscription_ref
                )
            )
        ).scalar_one_or_none()

        if subscription is None:
            # Recorded, not raised. An event for an unknown subscription is worth
            # investigating, but returning 500 makes the gateway retry forever.
            record.error = "no matching subscription"
            logger.warning("webhook_unknown_subscription", ref=event.subscription_ref)
            return

        record.organization_id = subscription.organization_id
        organization = await self.session.get(Organization, subscription.organization_id)

        match event.event_type:
            case GatewayEventType.SUBSCRIPTION_ACTIVATED | GatewayEventType.SUBSCRIPTION_RENEWED:
                subscription.status = SubscriptionStatus.ACTIVE
                if organization is not None and organization.status in (
                    OrganizationStatus.TRIALING,
                    OrganizationStatus.PAST_DUE,
                    OrganizationStatus.SUSPENDED,
                ):
                    organization.status = OrganizationStatus.ACTIVE

            case GatewayEventType.PAYMENT_SUCCEEDED:
                subscription.status = SubscriptionStatus.ACTIVE
                self.session.add(
                    Payment(
                        organization_id=subscription.organization_id,
                        amount=event.amount or Decimal("0"),
                        currency=event.currency or "USD",
                        status=PaymentStatus.SUCCEEDED,
                        gateway=self.gateway.name,
                        gateway_ref=event.event_id,
                        raw_payload=event.raw,
                    )
                )
                if organization is not None and organization.status is OrganizationStatus.PAST_DUE:
                    organization.status = OrganizationStatus.ACTIVE
                await record_audit(
                    self.session,
                    organization_id=subscription.organization_id,
                    action=AuditAction.PAYMENT_RECEIVED,
                    entity_type="subscription",
                    entity_id=subscription.id,
                    after={"amount": str(event.amount), "currency": event.currency},
                )

            case GatewayEventType.PAYMENT_FAILED:
                # PAST_DUE, not suspended. Spec §6.3 gives a 7-day grace with FULL
                # access and an in-app banner: a failed card should produce a nudge,
                # not an outage for a school in the middle of term.
                subscription.status = SubscriptionStatus.PAST_DUE
                if organization is not None:
                    organization.status = OrganizationStatus.PAST_DUE
                self.session.add(
                    Payment(
                        organization_id=subscription.organization_id,
                        amount=event.amount or Decimal("0"),
                        currency=event.currency or "USD",
                        status=PaymentStatus.FAILED,
                        gateway=self.gateway.name,
                        gateway_ref=event.event_id,
                        raw_payload=event.raw,
                    )
                )
                await record_audit(
                    self.session,
                    organization_id=subscription.organization_id,
                    action=AuditAction.PAYMENT_FAILED,
                    entity_type="subscription",
                    entity_id=subscription.id,
                    after={"grace_until": (datetime.now(UTC) + PAST_DUE_GRACE).isoformat()},
                )

            case GatewayEventType.SUBSCRIPTION_CANCELLED:
                subscription.status = SubscriptionStatus.CANCELLED
                subscription.cancelled_at = datetime.now(UTC)
                if organization is not None:
                    organization.status = OrganizationStatus.CANCELLED

            case GatewayEventType.UNKNOWN:
                # Deliberately inert. Acting on an event we do not understand is
                # worse than ignoring it; the raw payload is stored either way, so
                # nothing is lost if it turns out to matter.
                record.error = "unrecognised event type"

        self.session.add(
            SubscriptionEvent(
                organization_id=subscription.organization_id,
                subscription_id=subscription.id,
                event_type=f"webhook.{event.event_type.value}",
                payload=event.raw,
            )
        )
