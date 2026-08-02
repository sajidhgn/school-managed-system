"""Billing models: Subscription, SubscriptionEvent, Invoice, Payment,
OrganizationUsage, WebhookEvent.

WHY THIS FILE EXISTS
    Spec §6 makes the plan an enforcement mechanism, not a label. A free-plan
    organization must be blocked at school #2 with a 402, and that block has to be
    correct under concurrency, cheap enough to run before every resource-creating
    write, and reversible without deleting anyone's data.

RESPONSIBILITY
    Define the subscription lifecycle, the money records, the materialised usage
    counters entitlement checks read, and the webhook-idempotency ledger.

INTERACTIONS
    * `subscriptions.plan_id` -> `plans.id` (a platform table).
    * `modules/billing/entitlements.py` reads `OrganizationUsage` and the plan limits.
    * `modules/billing/gateways/` implement the `PaymentGateway` port.

=============================================================================
NEVER DELETE DATA ON DOWNGRADE -- spec §6.2
=============================================================================
    If an organization drops to a plan whose limits are below their current usage,
    the organization moves to `over_limit`: everything already there stays readable
    and exportable, and only NEW creates are refused until they are back under the
    cap or upgrade again.

    The tempting alternative -- reclaiming the excess by deleting schools or students
    -- destroys a customer's records because of a billing event. For a system holding
    minors' academic records that is not a product decision, it is a liability.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, ClassVar
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, str_enum
from app.db.mixins import CreatedAtMixin, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class SubscriptionStatus(StrEnum):
    """Spec §6.3: trialing -> active -> past_due -> suspended -> cancelled, + expired."""

    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class BillingCycle(StrEnum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


class InvoiceStatus(StrEnum):
    DRAFT = "draft"
    OPEN = "open"
    PAID = "paid"
    VOID = "void"
    UNCOLLECTIBLE = "uncollectible"


class PaymentStatus(StrEnum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    REFUNDED = "refunded"


class Subscription(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """One organization's plan. Exactly one row per organization."""

    __tablename__ = "subscriptions"

    plan_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("plans.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    """RESTRICT: a plan with live subscribers cannot be deleted. Retiring a plan is
    `is_active = false`, which stops new signups while leaving existing customers on
    the terms they agreed to."""

    status: Mapped[SubscriptionStatus] = mapped_column(
        str_enum(SubscriptionStatus, name="status"),
        nullable=False,
        default=SubscriptionStatus.TRIALING,
    )
    billing_cycle: Mapped[BillingCycle] = mapped_column(
        str_enum(BillingCycle, name="billing_cycle"),
        nullable=False,
        default=BillingCycle.MONTHLY,
    )

    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_start: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """The DEFAULT cancellation mode (spec §6.3). The customer has paid through the
    end of the period; cutting access the moment they click cancel bills them for
    time they cannot use. Immediate cancellation is a super-admin action."""

    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- Gateway linkage ---------------------------------------------------
    gateway: Mapped[str | None] = mapped_column(String(32))
    gateway_customer_ref: Mapped[str | None] = mapped_column(String(128))
    gateway_subscription_ref: Mapped[str | None] = mapped_column(String(128))
    """The provider's own ids. Stored rather than derived so that switching gateways
    -- JazzCash to Easypaisa, or either to Stripe -- does not orphan existing
    subscriptions: the old refs stay readable next to the new ones."""

    __table_args__ = (
        # ONE subscription per organization (spec D1). Unique rather than merely
        # indexed: two live subscriptions would make "what plan is this org on?"
        # ambiguous, and every entitlement check would silently pick one at random.
        Index("uq_subscriptions_organization_id", "organization_id", unique=True),
        Index("ix_subscriptions_status", "status"),
        Index("ix_subscriptions_current_period_end", "current_period_end"),
    )

    @property
    def is_in_trial(self) -> bool:
        return (
            self.status is SubscriptionStatus.TRIALING
            and self.trial_ends_at is not None
            and self.trial_ends_at > datetime.now(tz=self.trial_ends_at.tzinfo)
        )

    @property
    def grants_write_access(self) -> bool:
        """Whether this subscription currently permits writes.

        `past_due` grants access on purpose: spec §6.3 gives a 7-day grace with full
        access and an in-app banner. A failed card should produce a nudge, not an
        immediate outage for a school mid-term.
        """
        return self.status in (
            SubscriptionStatus.TRIALING,
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.PAST_DUE,
        )


class SubscriptionEvent(Base, UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin):
    """Append-only history of plan changes.

    Exists because `subscriptions` holds only current state, and "when did they
    upgrade, and from what?" is asked constantly -- by support, by revenue reporting,
    and by any billing dispute. Reconstructing it from invoices is guesswork.
    """

    __tablename__ = "subscription_events"

    subscription_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    from_plan_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("plans.id", ondelete="SET NULL")
    )
    to_plan_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("plans.id", ondelete="SET NULL")
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_subscription_events_org_created", "organization_id", text("created_at DESC")),
    )


class Invoice(Base, UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin):
    """A bill. Immutable once issued -- corrections are credit notes, not edits."""

    __tablename__ = "invoices"

    subscription_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("subscriptions.id", ondelete="SET NULL"),
        index=True,
    )

    number: Mapped[str] = mapped_column(String(40), nullable=False, unique=True)
    """Human-facing invoice number, globally unique across the platform.

    Global rather than per-organization because these appear in accounting exports
    and payment references where nobody carries the tenant alongside; two customers
    both holding "INV-0001" makes reconciliation ambiguous at exactly the moment it
    matters.
    """

    amount_subtotal: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    amount_tax: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False, default=0)
    amount_total: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    status: Mapped[InvoiceStatus] = mapped_column(
        str_enum(InvoiceStatus, name="status"),
        nullable=False,
        default=InvoiceStatus.DRAFT,
    )

    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    gateway_ref: Mapped[str | None] = mapped_column(String(128))
    pdf_url: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        Index("ix_invoices_organization_id_created", "organization_id", text("created_at DESC")),
        Index("ix_invoices_status", "status"),
        CheckConstraint("amount_total >= 0 AND amount_subtotal >= 0", name="amounts_non_negative"),
    )


class Payment(Base, UUIDPrimaryKeyMixin, TenantMixin, CreatedAtMixin):
    """A payment attempt against an invoice, successful or not."""

    __tablename__ = "payments"

    invoice_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("invoices.id", ondelete="SET NULL"),
        index=True,
    )

    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")

    status: Mapped[PaymentStatus] = mapped_column(
        str_enum(PaymentStatus, name="status"),
        nullable=False,
        default=PaymentStatus.PENDING,
    )

    gateway: Mapped[str] = mapped_column(String(32), nullable=False)
    gateway_ref: Mapped[str | None] = mapped_column(String(128), index=True)

    raw_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    """The gateway's response verbatim.

    Kept because when a payment dispute arrives six months later, the only defensible
    answer is what the provider actually said at the time -- not our interpretation of
    it, which may have been produced by code that has since been rewritten.
    """

    __table_args__ = (
        Index("ix_payments_organization_id_created", "organization_id", text("created_at DESC")),
    )


class OrganizationUsage(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Materialised usage counters -- what `EntitlementService` actually reads.

    =========================================================================
    WHY COUNTERS AND NOT `COUNT(*)` AT REQUEST TIME (spec §6.2)
    =========================================================================
        Two independent reasons, and the second is the one that bites.

        1. COST. The check runs before EVERY resource-creating write. Counting
           students across a large organization on each enrolment is a table scan on
           the hot path, and it gets slower exactly as the customer gets bigger.

        2. CORRECTNESS UNDER CONCURRENCY. `SELECT COUNT(*)` then `INSERT` is a
           read-modify-write with no lock between the halves. Two simultaneous
           requests both count 2 schools against a limit of 3, both proceed, and the
           organization ends up with 4. The limit is not enforced, it is merely
           usually observed.

           A counter row makes the check and the increment a single atomic
           `UPDATE ... SET schools_count = schools_count + 1 WHERE ... AND
           schools_count < :limit`, whose affected-row count IS the verdict. The
           database serialises the contending updates on the row lock, so the second
           request sees the first one's result and is refused.

        The cost of this design is that the counters can drift from reality if a
        write path forgets to maintain them. That is mitigated by keeping every
        increment in the same transaction as the row it counts, and by a periodic
        reconciliation job that recomputes from source.
    """

    __tablename__ = "organization_usage"

    schools_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    students_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    staff_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    custom_roles_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_used_mb: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    recomputed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """When the reconciliation job last rebuilt these from source tables. A stale
    timestamp on a busy organization is the signal that a write path is missing its
    counter update."""

    __table_args__ = (
        Index("uq_organization_usage_organization_id", "organization_id", unique=True),
        CheckConstraint(
            "schools_count >= 0 AND students_count >= 0 AND staff_count >= 0"
            " AND custom_roles_count >= 0 AND storage_used_mb >= 0",
            name="counts_non_negative",
        ),
    )

    # Maps a plan limit key to the counter column that tracks it. Declared here, next
    # to the columns, so adding a limit cannot silently go unmetered.
    LIMIT_TO_COUNTER: ClassVar[dict[str, str]] = {
        "max_schools": "schools_count",
        "max_students": "students_count",
        "max_staff": "staff_count",
        "max_custom_roles": "custom_roles_count",
        "storage_mb": "storage_used_mb",
    }


class WebhookEvent(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """Every webhook the platform has received, stored raw BEFORE processing.

    NO TENANT COLUMN AND NO RLS, deliberately. A webhook arrives unauthenticated
    from the gateway; which organization it concerns is only known after parsing it,
    and a malformed or hostile payload may name no organization at all. Requiring
    `organization_id` NOT NULL would make it impossible to record exactly the events
    most worth recording. `organization_id` is therefore a nullable, un-enforced
    reference filled in once resolution succeeds.

    =========================================================================
    IDEMPOTENCY IS THE ENTIRE POINT OF THIS TABLE (spec §6.4, §12)
    =========================================================================
        Payment gateways retry. They retry on timeout, on a 500, and sometimes for no
        visible reason -- so the same `gateway_event_id` WILL arrive more than once.
        Processing it twice means double-crediting a payment or double-extending a
        subscription period.

        The unique index on `(gateway, gateway_event_id)` makes the second delivery
        fail its INSERT, which is the check. Recording the row BEFORE processing (not
        after) is what makes it sound: if the handler crashes midway, the row is
        already committed, the retry is recognised as a duplicate, and the partial
        work is reconciled deliberately rather than blindly repeated.
    """

    __tablename__ = "webhook_events"

    gateway: Mapped[str] = mapped_column(String(32), nullable=False)
    gateway_event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(80))

    organization_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    """Resolved from the payload after the signature verifies. No ForeignKey: an
    event naming an organization we do not have must still be storable, so it can be
    investigated rather than discarded by a constraint."""

    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(500))

    __table_args__ = (
        Index("uq_webhook_events_gateway_event", "gateway", "gateway_event_id", unique=True),
        Index("ix_webhook_events_processed_at", "processed_at"),
    )
