"""Payment gateway adapters and the registry that selects one.

WHY THIS FILE EXISTS
    One place that maps a configuration string to an adapter instance. Without it,
    every call site that needs a gateway grows its own `if settings.PAYMENT_GATEWAY
    == ...` chain, and adding JazzCash means finding all of them.

INTERACTIONS
    `get_payment_gateway` is used as a FastAPI dependency, so a test can override it
    through `dependency_overrides` rather than by patching a module global.
"""

from __future__ import annotations

from app.core.config import Settings, get_settings
from app.modules.billing.gateways.base import (
    GatewayCustomer,
    GatewayError,
    GatewayEvent,
    GatewayEventType,
    GatewaySubscription,
    PaymentGateway,
)
from app.modules.billing.gateways.mock import MockGateway

# Registered adapters. JazzCash, Easypaisa and Stripe slot in here as they are
# built; nothing above this module changes when they do.
_ADAPTERS: dict[str, type[MockGateway]] = {
    "mock": MockGateway,
}


def build_gateway(settings: Settings | None = None) -> PaymentGateway:
    """Construct the configured adapter.

    An unknown name raises rather than falling back to the mock. A production
    deployment misconfigured to `jazzcash` before that adapter exists must fail
    loudly, not silently accept payments through a mock that approves everything.
    """
    settings = settings or get_settings()
    adapter = _ADAPTERS.get(settings.PAYMENT_GATEWAY)
    if adapter is None:
        raise GatewayError(
            f"Unknown payment gateway '{settings.PAYMENT_GATEWAY}'. Available: {sorted(_ADAPTERS)}"
        )
    return adapter(settings.PAYMENT_GATEWAY_SECRET or settings.SECRET_KEY)


def get_payment_gateway(settings: Settings | None = None) -> PaymentGateway:
    """Dependency wrapper around `build_gateway`."""
    return build_gateway(settings)


__all__ = [
    "GatewayCustomer",
    "GatewayError",
    "GatewayEvent",
    "GatewayEventType",
    "GatewaySubscription",
    "MockGateway",
    "PaymentGateway",
    "build_gateway",
    "get_payment_gateway",
]
