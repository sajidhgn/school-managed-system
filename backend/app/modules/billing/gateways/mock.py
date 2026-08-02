"""`MockGateway` -- the in-process payment provider (spec §6.4).

WHY THIS FILE EXISTS
    Spec §6.4: "Ship a MockGateway first so the whole flow is testable without
    credentials." Every other adapter needs a merchant account, a sandbox, and a
    publicly reachable webhook URL. Blocking the billing test suite on all three
    means the subscription lifecycle goes untested until the day it goes live.

    This adapter makes the entire flow -- subscribe, change plan, cancel, webhook,
    idempotent redelivery -- exercisable in a unit test with no network at all.

RESPONSIBILITY
    Behave like a payment provider, deterministically. It is NOT a stub that returns
    empty values: it models the parts whose behaviour the rest of the system depends
    on, including HMAC signature verification, because a mock that skips signature
    checking would let the webhook handler ship with that step untested.

INTERACTIONS
    Selected by `get_payment_gateway` when `PAYMENT_GATEWAY=mock` (the default
    outside production).

=============================================================================
WHY THIS MOCK SIGNS ITS WEBHOOKS FOR REAL
=============================================================================
    The tempting shortcut is `verify_and_parse` that just parses. Then the test
    suite never executes a signature check, and the first real verification anyone
    runs is against a live provider in production.

    Here, `sign()` and `verify_and_parse()` use HMAC-SHA256 over the raw body with
    `compare_digest`, which is the same shape every real adapter needs. A test that
    posts an unsigned or tampered payload gets a 400, exactly as it would from
    JazzCash -- so the handler's rejection path is covered before it matters.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from app.modules.billing.gateways.base import (
    GatewayCustomer,
    GatewayError,
    GatewayEvent,
    GatewayEventType,
    GatewaySubscription,
)

SIGNATURE_HEADER = "X-Mock-Signature"

# Maps the mock's own event names onto the provider-neutral vocabulary. A real
# adapter has exactly this shape, just with the provider's strings on the left.
_EVENT_MAP: dict[str, GatewayEventType] = {
    "subscription.activated": GatewayEventType.SUBSCRIPTION_ACTIVATED,
    "subscription.renewed": GatewayEventType.SUBSCRIPTION_RENEWED,
    "subscription.cancelled": GatewayEventType.SUBSCRIPTION_CANCELLED,
    "payment.succeeded": GatewayEventType.PAYMENT_SUCCEEDED,
    "payment.failed": GatewayEventType.PAYMENT_FAILED,
}


class MockGateway:
    """A deterministic, in-process payment provider."""

    name = "mock"

    def __init__(self, secret: str) -> None:
        self._secret = secret.encode("utf-8")

    # -- Outbound calls ------------------------------------------------------

    async def create_customer(
        self, *, organization_id: str, email: str, name: str
    ) -> GatewayCustomer:
        del email, name  # a real provider stores these; the mock only needs the ref
        # DERIVED FROM `organization_id`, not random: calling this twice for the same
        # organization returns the same ref, so a retried signup does not create a
        # duplicate billing account. Real providers offer an idempotency key for
        # this; deriving the ref is the mock's equivalent.
        return GatewayCustomer(customer_ref=f"mock_cus_{organization_id.replace('-', '')[:24]}")

    async def create_subscription(
        self,
        *,
        customer_ref: str,
        plan_code: str,
        billing_cycle: str,
        trial_days: int = 0,
    ) -> GatewaySubscription:
        now = datetime.now(UTC)
        period_end = now + (
            timedelta(days=365) if billing_cycle == "yearly" else timedelta(days=30)
        )
        return GatewaySubscription(
            subscription_ref=(
                "mock_sub_" + uuid.uuid5(uuid.NAMESPACE_OID, customer_ref + plan_code).hex[:24]
            ),
            status="trialing" if trial_days > 0 else "active",
            current_period_start=now,
            current_period_end=now + timedelta(days=trial_days) if trial_days else period_end,
            checkout_url=None,  # the mock needs no customer-facing confirmation step
        )

    async def change_plan(
        self, *, subscription_ref: str, plan_code: str, billing_cycle: str
    ) -> GatewaySubscription:
        del plan_code
        now = datetime.now(UTC)
        return GatewaySubscription(
            subscription_ref=subscription_ref,
            status="active",
            current_period_start=now,
            current_period_end=now
            + (timedelta(days=365) if billing_cycle == "yearly" else timedelta(days=30)),
        )

    async def cancel(
        self, *, subscription_ref: str, at_period_end: bool = True
    ) -> GatewaySubscription:
        return GatewaySubscription(
            subscription_ref=subscription_ref,
            # `cancel_at_period_end` keeps the agreement ACTIVE until the period
            # ends -- the customer paid for that time. Only an immediate cancel
            # flips the status now.
            status="active" if at_period_end else "cancelled",
            current_period_end=None if at_period_end else datetime.now(UTC),
        )

    # -- Webhooks ------------------------------------------------------------

    def sign(self, payload: bytes) -> str:
        """Produce the signature a real provider would send. Used by tests and seeds."""
        return hmac.new(self._secret, payload, hashlib.sha256).hexdigest()

    def verify_and_parse(self, *, payload: bytes, headers: dict[str, str]) -> GatewayEvent:
        """Verify the HMAC and normalise the event.

        Header lookup is case-insensitive because HTTP header names are, and a real
        provider posting `x-mock-signature` must not fail against a handler that
        checked for `X-Mock-Signature`.
        """
        lowered = {k.lower(): v for k, v in headers.items()}
        supplied = lowered.get(SIGNATURE_HEADER.lower())
        if not supplied:
            raise GatewayError("Webhook signature header is missing.")

        # `compare_digest`, never `==`: string equality short-circuits on the first
        # differing byte, and an attacker who can measure that recovers the signature
        # one byte at a time.
        if not hmac.compare_digest(supplied, self.sign(payload)):
            raise GatewayError("Webhook signature does not match.")

        try:
            body: dict[str, Any] = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise GatewayError("Webhook payload is not valid JSON.") from exc

        raw_amount = body.get("amount")
        return GatewayEvent(
            # Falls back to a digest of the payload rather than a random uuid: a
            # random id would make every redelivery look new, defeating the
            # idempotency check that `webhook_events` exists to provide.
            event_id=str(body.get("event_id") or hashlib.sha256(payload).hexdigest()),
            event_type=_EVENT_MAP.get(str(body.get("type")), GatewayEventType.UNKNOWN),
            subscription_ref=body.get("subscription_ref"),
            customer_ref=body.get("customer_ref"),
            # Decimal from `str`, never from `float`: `Decimal(29.99)` inherits the
            # binary representation error, `Decimal("29.99")` does not.
            amount=Decimal(str(raw_amount)) if raw_amount is not None else None,
            currency=body.get("currency"),
            occurred_at=datetime.now(UTC),
            raw=body,
        )
