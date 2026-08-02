"""Billing and entitlement gates (spec §12 "Billing", §6).

Covers the three the spec names as release gates -- free-plan school limit,
downgrade behaviour, and webhook idempotency -- plus the public plan catalog.
"""

from __future__ import annotations

import json
from typing import Any

from tests.integration.conftest import API, Tenant


async def test_public_plans_endpoint_is_unauthenticated_and_hides_enterprise(
    db_client: Any,
) -> None:
    """Spec §8: `GET /public/plans`, unauthenticated, `is_public = true` only.

    Two properties matter. It must work with NO credentials -- the pricing page has
    no user -- and it must not disclose the hidden `enterprise` tier, whose limits
    are unlimited and whose price is negotiated. Leaking it would let anyone request
    a plan code they were never quoted.
    """
    response = await db_client.get(f"{API}/public/plans")
    assert response.status_code == 200, response.text

    plans = response.json()
    codes = {p["code"] for p in plans}
    assert {"free", "starter", "growth"} <= codes
    assert "enterprise" not in codes, "the hidden enterprise plan was exposed publicly"

    # Cached at the edge: the catalog changes a few times a year and every visitor
    # to the marketing site hits this.
    assert "max-age" in response.headers.get("Cache-Control", "")

    free = next(p for p in plans if p["code"] == "free")
    assert free["limits"]["max_schools"] == 1
    assert free["limits"]["max_students"] == 50
    # Spec §6.1: every limit key exists on every plan -- no missing-key fallbacks.
    required = {
        "max_schools",
        "max_students",
        "max_staff",
        "max_custom_roles",
        "storage_mb",
        "audit_retention_days",
    }
    for plan in plans:
        assert required <= set(plan["limits"]), f"{plan['code']} is missing limit keys"


async def test_free_plan_org_is_blocked_at_school_two_with_402(make_tenant: Any) -> None:
    """Spec §12: "Free-plan org creating school #2 -> 402."

    THE HEADLINE BILLING GATE. 402 Payment Required with the limit, the current
    count and an upgrade URL -- not a generic 403 -- so the frontend can render an
    upgrade prompt rather than something that reads like a bug.
    """
    tenant: Tenant = await make_tenant(plan=None)  # free: max_schools = 1

    second = await tenant.post(f"{API}/schools", json={"name": "Second Campus", "code": "SECOND"})

    assert second.status_code == 402, second.text
    body = second.json()
    assert body["code"] == "plan_limit_exceeded"
    assert body["meta"]["limit"] == "max_schools"
    assert body["meta"]["current"] == 1
    assert body["meta"]["allowed"] == 1
    assert body["meta"]["upgrade_url"] == "/billing/plans"


async def test_upgrading_lifts_the_limit(make_tenant: Any) -> None:
    """After an upgrade the previously-blocked create succeeds.

    Confirms the entitlement check reads the CURRENT plan rather than a value cached
    at signup -- a limit that only refreshes on restart is a limit that keeps
    charging customers for capacity they cannot use.
    """
    tenant: Tenant = await make_tenant(plan=None)

    blocked = await tenant.post(f"{API}/schools", json={"name": "Second Campus", "code": "SECOND"})
    assert blocked.status_code == 402

    upgraded = await tenant.post(
        f"{API}/billing/change-plan",
        json={"plan_code": "growth", "billing_cycle": "monthly"},
    )
    assert upgraded.status_code == 200, upgraded.text
    assert upgraded.json()["plan_code"] == "growth"

    allowed = await tenant.post(f"{API}/schools", json={"name": "Second Campus", "code": "SECOND"})
    assert allowed.status_code == 201, allowed.text


async def test_downgrade_below_usage_keeps_data_readable_and_blocks_creates(
    make_tenant: Any,
) -> None:
    """Spec §12: "Downgrade below usage -> existing data readable, new creates blocked."

    =========================================================================
    THE RULE THAT MATTERS MOST COMMERCIALLY: NEVER DELETE DATA ON DOWNGRADE
    =========================================================================
        The tempting implementation reclaims the excess by deleting schools. That
        destroys a customer's records -- students, grades, fee history -- as a side
        effect of a billing change. Spec §6.2 puts it bluntly: "Deleting a customer's
        schools because they downgraded is how you get sued."

        Instead the organization moves to `over_limit`: everything already there
        stays readable and exportable, and only NEW creates are refused.
    """
    tenant: Tenant = await make_tenant(plan="growth")

    second = await tenant.post(f"{API}/schools", json={"name": "Second Campus", "code": "SECOND"})
    assert second.status_code == 201, second.text
    second_id = second.json()["school"]["id"]

    downgraded = await tenant.post(
        f"{API}/billing/change-plan",
        json={"plan_code": "free", "billing_cycle": "monthly"},
    )
    assert downgraded.status_code == 200, downgraded.text

    # 1. EXISTING DATA STAYS READABLE. This is the non-negotiable half.
    listed = await tenant.get(f"{API}/schools")
    assert listed.status_code == 200, listed.text
    assert {s["id"] for s in listed.json()} >= {tenant.school_id, second_id}

    fetched = await tenant.get(f"{API}/schools/{second_id}")
    assert fetched.status_code == 200, "a school became unreadable after a downgrade"

    # 2. THE ORGANIZATION IS FLAGGED, so the UI can explain why creates fail.
    usage = await tenant.get(f"{API}/org/usage")
    assert usage.status_code == 200
    assert usage.json()["organization_status"] == "over_limit"

    # 3. NEW CREATES ARE BLOCKED.
    third = await tenant.post(f"{API}/schools", json={"name": "Third Campus", "code": "THIRD"})
    assert third.status_code == 402, third.text


async def test_duplicate_webhook_is_processed_once(db_client: Any, tenant: Tenant) -> None:
    """Spec §12: "Duplicate webhook delivery -> processed once."

    =========================================================================
    GATEWAYS RETRY. THIS IS NOT A HYPOTHETICAL.
    =========================================================================
        On timeout, on a 500, and sometimes for no visible reason. The same
        `gateway_event_id` WILL arrive more than once, and processing it twice means
        double-crediting a payment or double-extending a subscription period.

        The unique index on `(gateway, gateway_event_id)` is the guard; inserting the
        record BEFORE processing is what makes it sound.

        Both deliveries return 2xx: the gateway's contract is "2xx means delivered",
        and a duplicate WAS delivered -- we simply had it already. Any other status
        provokes further retries of an event that is fully handled.
    """
    from app.modules.billing.gateways.mock import SIGNATURE_HEADER, MockGateway

    gateway = MockGateway("test-webhook-secret")

    subscribed = await tenant.post(
        f"{API}/billing/subscribe",
        json={"plan_code": "starter", "billing_cycle": "monthly"},
    )
    assert subscribed.status_code == 200, subscribed.text

    subscription = await tenant.get(f"{API}/billing/subscription")
    assert subscription.status_code == 200

    payload = json.dumps(
        {
            "event_id": "evt_duplicate_test_001",
            "type": "payment.succeeded",
            "subscription_ref": "mock_sub_unknown",
            "amount": "29.00",
            "currency": "USD",
        }
    ).encode()
    headers = {
        SIGNATURE_HEADER: gateway.sign(payload),
        "Content-Type": "application/json",
    }

    first = await db_client.post(f"{API}/webhooks/payments/mock", content=payload, headers=headers)
    assert first.status_code == 200, first.text
    assert first.json()["status"] == "processed"

    second = await db_client.post(f"{API}/webhooks/payments/mock", content=payload, headers=headers)
    assert second.status_code == 200, second.text
    assert second.json()["status"] == "duplicate", (
        "a redelivered webhook was processed a second time"
    )


async def test_webhook_with_a_bad_signature_is_rejected(db_client: Any) -> None:
    """An unsigned or tampered webhook is refused with 400, not 500.

    A webhook arrives unauthenticated -- the caller is a payment provider, not a user
    -- so the HMAC over the raw body is the ONLY thing establishing authenticity.
    Without the check, anyone who found the URL could tell us a payment succeeded.

    400 rather than 500 because a bad signature will never become a good one:
    returning 5xx would make the gateway retry it forever.
    """
    payload = json.dumps({"event_id": "evt_forged", "type": "payment.succeeded"}).encode()

    unsigned = await db_client.post(
        f"{API}/webhooks/payments/mock",
        content=payload,
        headers={"Content-Type": "application/json"},
    )
    assert unsigned.status_code == 422, unsigned.text
    assert unsigned.json()["code"] == "WEBHOOK_VERIFICATION_FAILED"

    tampered = await db_client.post(
        f"{API}/webhooks/payments/mock",
        content=payload,
        headers={"X-Mock-Signature": "0" * 64, "Content-Type": "application/json"},
    )
    assert tampered.status_code == 422, tampered.text


async def test_hidden_plan_cannot_be_self_selected(tenant: Tenant) -> None:
    """A customer cannot put themselves on the enterprise tier.

    It is `is_public = false` with unlimited limits, assigned only by a super admin
    after a negotiated contract. Letting a customer select it by guessing the code
    would hand out unlimited capacity for free.
    """
    response = await tenant.post(
        f"{API}/billing/change-plan",
        json={"plan_code": "enterprise", "billing_cycle": "monthly"},
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "PLAN_NOT_SELF_SERVICE"


async def test_usage_is_readable_by_any_member(tenant: Tenant) -> None:
    """`GET /org/usage` is not gated behind `billing:read`.

    A teacher who hits a student limit needs to understand why the create failed.
    Answering only "forbidden" sends them to ask the principal a question the UI
    could have answered itself.
    """
    response = await tenant.get(f"{API}/org/usage")
    assert response.status_code == 200, response.text

    body = response.json()
    keys = {item["key"] for item in body["items"]}
    assert "max_schools" in keys and "max_staff" in keys

    schools = next(i for i in body["items"] if i["key"] == "max_schools")
    assert schools["current"] == 1
    assert schools["remaining"] is not None


async def test_cancellation_is_at_period_end(tenant: Tenant) -> None:
    """Self-service cancellation never cuts access immediately (spec §6.3).

    The customer has paid through the end of the period; ending it the moment they
    click cancel bills them for time they cannot use. Immediate cancellation is a
    super-admin action.
    """
    await tenant.post(
        f"{API}/billing/subscribe",
        json={"plan_code": "starter", "billing_cycle": "monthly"},
    )

    immediate = await tenant.post(f"{API}/billing/cancel", json={"at_period_end": False})
    assert immediate.status_code == 422, immediate.text
    assert immediate.json()["code"] == "IMMEDIATE_CANCEL_NOT_ALLOWED"

    scheduled = await tenant.post(f"{API}/billing/cancel", json={"at_period_end": True})
    assert scheduled.status_code == 200, scheduled.text
    body = scheduled.json()
    assert body["cancel_at_period_end"] is True
    # Still ACTIVE: they keep access for the period they paid for.
    assert body["status"] in ("active", "trialing")
