"""The `PaymentGateway` port (spec §6.4).

WHY THIS FILE EXISTS
    The target market is Pakistan, so the real adapters are JazzCash and Easypaisa,
    with Stripe as an international fallback. Three providers with three different
    APIs, three different webhook formats and three different signature schemes.

    Coding directly against any one of them spreads that provider's vocabulary --
    its ids, its status strings, its error shapes -- through the subscription
    service, the webhook handler and the invoice logic. Adding the second provider
    then means finding and rewriting every one of those places, and the two
    implementations inevitably diverge in behaviour.

    A port fixes the vocabulary at OUR boundary. Adapters translate; nothing above
    them knows which provider is in use.

RESPONSIBILITY
    Define the contract and the provider-neutral result types. No I/O, no provider
    names beyond the registry.

INTERACTIONS
    * `gateways/mock.py` implements it for development and tests.
    * `modules/billing/service.py` depends on this Protocol, never on an adapter.

=============================================================================
WHY A `Protocol` AND NOT AN ABSTRACT BASE CLASS
=============================================================================
    Structural typing: an adapter satisfies the contract by having the right
    methods, with no import from this module and no inheritance. That keeps the
    dependency arrow pointing one way -- adapters may know about the port's types,
    but the port never needs to know an adapter exists -- and it means a test double
    is a plain class, not a subclass with five inherited methods it must stub out.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable


class GatewayEventType(StrEnum):
    """Provider-neutral webhook events.

    Every adapter maps its provider's event names onto these. The set is
    deliberately small: these are the only events that change state on our side, and
    an adapter receiving anything else reports `UNKNOWN` so it is recorded and
    ignored rather than triggering a guess.
    """

    SUBSCRIPTION_ACTIVATED = "subscription.activated"
    SUBSCRIPTION_RENEWED = "subscription.renewed"
    SUBSCRIPTION_CANCELLED = "subscription.cancelled"
    PAYMENT_SUCCEEDED = "payment.succeeded"
    PAYMENT_FAILED = "payment.failed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class GatewayCustomer:
    """A billing account at the provider."""

    customer_ref: str


@dataclass(frozen=True, slots=True)
class GatewaySubscription:
    """A recurring agreement at the provider."""

    subscription_ref: str
    status: str
    current_period_start: datetime | None = None
    current_period_end: datetime | None = None
    # Present when the provider needs the customer to complete payment in their own
    # UI -- which is the norm for JazzCash and Easypaisa, where the user is
    # redirected to a wallet confirmation screen rather than entering a card.
    checkout_url: str | None = None


@dataclass(frozen=True, slots=True)
class GatewayEvent:
    """A verified, normalised webhook.

    `event_id` is what makes idempotency possible (spec §6.4). Every provider
    supplies one; an adapter for a provider that does not must synthesise a stable
    one from the payload, never a random value -- a random id would make every
    retry look like a new event, which is the exact failure this field prevents.
    """

    event_id: str
    event_type: GatewayEventType
    subscription_ref: str | None = None
    customer_ref: str | None = None
    amount: Decimal | None = None
    currency: str | None = None
    occurred_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)


class GatewayError(Exception):
    """An adapter could not complete a call, or a webhook failed verification."""


@runtime_checkable
class PaymentGateway(Protocol):
    """What every payment provider adapter must offer."""

    name: str

    async def create_customer(
        self, *, organization_id: str, email: str, name: str
    ) -> GatewayCustomer:
        """Register the organization as a billing account with the provider."""
        ...

    async def create_subscription(
        self,
        *,
        customer_ref: str,
        plan_code: str,
        billing_cycle: str,
        trial_days: int = 0,
    ) -> GatewaySubscription:
        """Start a recurring agreement."""
        ...

    async def change_plan(
        self, *, subscription_ref: str, plan_code: str, billing_cycle: str
    ) -> GatewaySubscription:
        """Move an existing agreement to a different plan."""
        ...

    async def cancel(
        self, *, subscription_ref: str, at_period_end: bool = True
    ) -> GatewaySubscription:
        """End an agreement, at period end by default (spec §6.3)."""
        ...

    def verify_and_parse(self, *, payload: bytes, headers: dict[str, str]) -> GatewayEvent:
        """Verify the webhook signature and normalise it.

        VERIFICATION AND PARSING ARE ONE OPERATION ON PURPOSE. A separate
        `verify()` and `parse()` can be called in the wrong order, or the first can
        be forgotten entirely -- and an unverified webhook is an unauthenticated
        stranger telling us a payment succeeded. Fusing them makes it impossible to
        obtain a `GatewayEvent` that was not verified.

        Synchronous because signature checking is pure computation over bytes
        already in memory. Making it async would imply a network call that does not
        happen and invite a real one to be added later.

        Raises `GatewayError` when the signature does not match.
        """
        ...
