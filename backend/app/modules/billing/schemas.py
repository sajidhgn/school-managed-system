"""Billing request/response contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import Field

from app.common.schemas import BaseSchema
from app.modules.billing.models import BillingCycle


class PlanPublic(BaseSchema):
    """A plan as the marketing site sees it (spec §6.1).

    Served by an UNAUTHENTICATED endpoint, so it carries only what a pricing page
    needs. Internal fields -- `is_active`, timestamps, the row id's role in
    subscriptions -- are omitted rather than filtered client-side.

    NEVER HARDCODE THESE IN THE FRONTEND. A price duplicated into the marketing site
    is a price that will one day disagree with the one actually charged, and the
    customer will have a screenshot of the cheaper one.
    """

    id: UUID
    code: str
    name: str
    description: str | None
    marketing_tagline: str | None
    price_monthly: Decimal | None
    price_yearly: Decimal | None
    currency: str
    trial_days: int
    limits: dict[str, Any]
    features: dict[str, Any]
    sort_order: int


class SubscriptionRead(BaseSchema):
    id: UUID
    plan_code: str
    plan_name: str
    status: str
    billing_cycle: str
    trial_ends_at: datetime | None
    current_period_start: datetime | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    cancelled_at: datetime | None


class SubscribeRequest(BaseSchema):
    plan_code: str = Field(min_length=1, max_length=50)
    billing_cycle: BillingCycle = BillingCycle.MONTHLY


class CancelRequest(BaseSchema):
    at_period_end: bool = True
    """Defaults to True (spec §6.3). Immediate cancellation is a super-admin action;
    this flag is here so the shape stays stable when that endpoint reuses it."""


class UsageItem(BaseSchema):
    """One metered limit and its consumption. `allowed = -1` means unlimited."""

    key: str
    current: int
    allowed: int
    remaining: int | None
    is_unlimited: bool
    is_exhausted: bool


class UsageResponse(BaseSchema):
    """`GET /org/usage` -- live counters against plan limits."""

    plan_code: str
    organization_status: str
    items: list[UsageItem]


class InvoiceRead(BaseSchema):
    id: UUID
    number: str
    amount_subtotal: Decimal
    amount_tax: Decimal
    amount_total: Decimal
    currency: str
    status: str
    issued_at: datetime | None
    due_at: datetime | None
    paid_at: datetime | None
    pdf_url: str | None
    created_at: datetime
