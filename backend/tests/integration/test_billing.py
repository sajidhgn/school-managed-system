"""Billing and entitlement gates (spec §12 "Billing", §6).

Covers the three the spec names as release gates -- free-plan school limit,
downgrade behaviour, and webhook idempotency -- plus the public plan catalog.
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.cli import reconcile_usage
from app.db.session import bind_tenant, get_session_factory
from app.modules.billing.entitlements import EntitlementService, PlanLimitExceededError
from app.modules.billing.gateways.mock import SIGNATURE_HEADER, MockGateway
from app.modules.billing.jobs import process_billing_lifecycle, purge_expired_audit_logs
from app.modules.billing.models import Invoice, InvoiceStatus
from app.modules.billing.service import WebhookService
from app.modules.rbac.models import AuditLog
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


async def test_known_webhook_binds_exactly_one_tenant(
    db_client: Any,
    make_tenant: Any,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """A verified provider reference resolves cross-tenant, then writes tenant-bound."""
    target: Tenant = await make_tenant(
        name="Webhook Target", email="webhook-target@test.example", plan="starter"
    )
    other: Tenant = await make_tenant(
        name="Webhook Other", email="webhook-other@test.example", plan="starter"
    )

    async with admin_sessionmaker() as session:
        subscription_ref = (
            await session.execute(
                text(
                    "SELECT gateway_subscription_ref FROM subscriptions "
                    "WHERE organization_id = :organization_id"
                ),
                {"organization_id": target.organization_id},
            )
        ).scalar_one()
        other_status_before = (
            await session.execute(
                text("SELECT status FROM organizations WHERE id = :organization_id"),
                {"organization_id": other.organization_id},
            )
        ).scalar_one()

    gateway = MockGateway("test-webhook-secret")
    payload = json.dumps(
        {
            "event_id": "evt_known_tenant_binding_001",
            "type": "payment.failed",
            "subscription_ref": subscription_ref,
            "amount": "29.00",
            "currency": "USD",
        }
    ).encode()
    response = await db_client.post(
        f"{API}/webhooks/payments/mock",
        content=payload,
        headers={SIGNATURE_HEADER: gateway.sign(payload), "Content-Type": "application/json"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "processed"

    async with admin_sessionmaker() as session:
        organizations = dict(
            (
                await session.execute(
                    text(
                        "SELECT id::text, status FROM organizations "
                        "WHERE id IN (:target_id, :other_id)"
                    ),
                    {"target_id": target.organization_id, "other_id": other.organization_id},
                )
            ).all()
        )
        assert organizations[target.organization_id] == "past_due"
        assert organizations[other.organization_id] == other_status_before

        payment_orgs = (
            (
                await session.execute(
                    text(
                        "SELECT organization_id::text FROM payments WHERE gateway_ref = :event_id"
                    ),
                    {"event_id": "evt_known_tenant_binding_001"},
                )
            )
            .scalars()
            .all()
        )
        assert payment_orgs == [target.organization_id]

        event_org = (
            await session.execute(
                text(
                    "SELECT organization_id::text FROM webhook_events "
                    "WHERE gateway_event_id = :event_id"
                ),
                {"event_id": "evt_known_tenant_binding_001"},
            )
        ).scalar_one()
        assert event_org == target.organization_id


async def test_unknown_webhook_reference_is_inert_and_clears_platform_read(
    db_client: Any,
) -> None:
    """Unknown references are retained without mutation or a leaked privileged GUC."""
    del db_client  # initializes the restricted application engine used below
    gateway = MockGateway("test-webhook-secret")
    payload = json.dumps(
        {
            "event_id": "evt_unknown_tenant_binding_001",
            "type": "payment.succeeded",
            "subscription_ref": "mock_sub_does_not_exist",
            "amount": "29.00",
            "currency": "USD",
        }
    ).encode()

    factory = get_session_factory()
    async with factory() as session:
        await bind_tenant(session, None)
        processed = await WebhookService(session, gateway).handle(
            payload=payload,
            headers={SIGNATURE_HEADER: gateway.sign(payload)},
        )
        assert processed is True

        platform_mode, organization_id = (
            await session.execute(
                text(
                    "SELECT current_setting('app.is_platform_admin', true), "
                    "current_setting('app.current_org_id', true)"
                )
            )
        ).one()
        assert platform_mode == "off"
        assert organization_id == ""

        payment_count = (
            await session.execute(
                text("SELECT count(*) FROM payments WHERE gateway_ref = :event_id"),
                {"event_id": "evt_unknown_tenant_binding_001"},
            )
        ).scalar_one()
        assert payment_count == 0


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


async def test_student_capacity_tracks_status_transitions_and_deletion(tenant: Tenant) -> None:
    """Only active students consume the plan; every transition releases/reserves once."""
    me = await tenant.get(f"{API}/auth/me")
    school_membership = next(
        item for item in me.json()["memberships"] if item["school_id"] == tenant.school_id
    )
    switched = await tenant.client.post(
        f"{API}/auth/context",
        json={"membership_id": school_membership["membership_id"]},
        headers={
            **tenant.headers(),
            "X-Token-Transport": "body",
        },
    )
    assert switched.status_code == 200, switched.text
    tenant.access_token = switched.headers["X-Access-Token"]

    created = await tenant.post(
        f"{API}/students",
        json={
            "admission_number": "CAP-001",
            "first_name": "Capacity",
            "last_name": "Student",
            "status": "active",
        },
    )
    assert created.status_code == 201, created.text
    student_id = created.json()["id"]

    async def count() -> int:
        usage = await tenant.get(f"{API}/org/usage")
        return next(i["current"] for i in usage.json()["items"] if i["key"] == "max_students")

    assert await count() == 1
    inactive = await tenant.patch(f"{API}/students/{student_id}", json={"status": "inactive"})
    assert inactive.status_code == 200, inactive.text
    assert await count() == 0

    active = await tenant.patch(f"{API}/students/{student_id}", json={"status": "active"})
    assert active.status_code == 200, active.text
    assert await count() == 1

    deleted = await tenant.delete(f"{API}/students/{student_id}")
    assert deleted.status_code == 204, deleted.text
    assert await count() == 0


async def test_concurrent_seat_reservations_cannot_exceed_plan(
    db_client: Any,
    make_tenant: Any,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """The counter UPDATE serializes contenders at the final free-plan staff seat."""
    del db_client
    tenant: Tenant = await make_tenant(plan=None)
    async with admin_sessionmaker() as session:
        await session.execute(
            text(
                "UPDATE organization_usage SET staff_count = 2 "
                "WHERE organization_id = :organization_id"
            ),
            {"organization_id": tenant.organization_id},
        )
        await session.commit()

    async def reserve() -> str:
        factory = get_session_factory()
        async with factory() as session:
            await bind_tenant(session, UUID(tenant.organization_id))
            try:
                await EntitlementService(session).check_and_consume(
                    UUID(tenant.organization_id), "max_staff"
                )
                await session.commit()
                return "reserved"
            except PlanLimitExceededError:
                await session.rollback()
                return "blocked"

    assert sorted(await asyncio.gather(reserve(), reserve())) == ["blocked", "reserved"]
    async with admin_sessionmaker() as session:
        count = (
            await session.execute(
                text(
                    "SELECT staff_count FROM organization_usage "
                    "WHERE organization_id = :organization_id"
                ),
                {"organization_id": tenant.organization_id},
            )
        ).scalar_one()
        assert count == 3


async def test_usage_reconciliation_is_idempotent(
    tenant: Tenant,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Reconciliation repairs drift and a second run makes no further changes."""
    async with admin_sessionmaker() as session:
        await session.execute(
            text(
                "UPDATE organization_usage SET schools_count = 99, students_count = 88, "
                "staff_count = 77, custom_roles_count = 66 "
                "WHERE organization_id = :organization_id"
            ),
            {"organization_id": tenant.organization_id},
        )
        await session.commit()

    factory = get_session_factory()
    snapshots: list[tuple[int, int, int, int]] = []
    for _ in range(2):
        async with factory() as session:
            await bind_tenant(session, UUID(tenant.organization_id))
            await reconcile_usage(session, UUID(tenant.organization_id))
            await session.commit()
        async with admin_sessionmaker() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT schools_count, students_count, staff_count, custom_roles_count "
                        "FROM organization_usage WHERE organization_id = :organization_id"
                    ),
                    {"organization_id": tenant.organization_id},
                )
            ).one()
            snapshots.append(tuple(row))

    assert snapshots[0] == snapshots[1]
    assert snapshots[0][0:3] == (1, 0, 0)


async def test_invoice_pdf_is_permission_checked_and_tenant_safe(
    make_tenant: Any,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """An invoice renders as a PDF, while another tenant's known id stays hidden."""
    target: Tenant = await make_tenant(name="Invoice Target", email="invoice-target@test.example")
    other: Tenant = await make_tenant(name="Invoice Other", email="invoice-other@test.example")
    now = datetime.now(UTC)
    async with admin_sessionmaker() as session:
        target_invoice = Invoice(
            organization_id=UUID(target.organization_id),
            number="INV-TARGET-001",
            amount_subtotal=Decimal("79.00"),
            amount_tax=Decimal("3.95"),
            amount_total=Decimal("82.95"),
            currency="USD",
            status=InvoiceStatus.OPEN,
            issued_at=now,
            due_at=now + timedelta(days=14),
        )
        other_invoice = Invoice(
            organization_id=UUID(other.organization_id),
            number="INV-OTHER-001",
            amount_subtotal=Decimal("29.00"),
            amount_tax=Decimal("0.00"),
            amount_total=Decimal("29.00"),
            currency="USD",
            status=InvoiceStatus.PAID,
            issued_at=now,
            due_at=now,
        )
        session.add_all([target_invoice, other_invoice])
        await session.commit()

    rendered = await target.get(f"{API}/billing/invoices/{target_invoice.id}/pdf")
    assert rendered.status_code == 200, rendered.text
    assert rendered.headers["content-type"] == "application/pdf"
    assert "INV-TARGET-001" in rendered.headers["content-disposition"]
    assert rendered.content.startswith(b"%PDF-")
    assert len(rendered.content) > 1_000

    hidden = await target.get(f"{API}/billing/invoices/{other_invoice.id}/pdf")
    assert hidden.status_code == 404, hidden.text


async def test_billing_mutations_replay_same_idempotency_key(
    tenant: Tenant,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Equal retries replay once; reusing the key for another payload is rejected."""
    headers = {**tenant.headers(), "Idempotency-Key": "upgrade-checkout-001"}
    payload = {"plan_code": "starter", "billing_cycle": "yearly"}
    first = await tenant.client.post(f"{API}/billing/change-plan", json=payload, headers=headers)
    assert first.status_code == 200, first.text

    replay = await tenant.client.post(f"{API}/billing/change-plan", json=payload, headers=headers)
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()

    conflict = await tenant.client.post(
        f"{API}/billing/change-plan",
        json={"plan_code": "free", "billing_cycle": "monthly"},
        headers=headers,
    )
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "IDEMPOTENCY_KEY_REUSED"

    async with admin_sessionmaker() as session:
        events = (
            await session.execute(
                text(
                    "SELECT count(*) FROM subscription_events "
                    "WHERE organization_id = :organization_id "
                    "AND event_type = 'subscription.plan_changed' "
                    "AND payload ->> 'to' = 'starter'"
                ),
                {"organization_id": tenant.organization_id},
            )
        ).scalar_one()
        assert events == 1


async def test_billing_lifecycle_grace_cancellation_and_anonymization(
    tenant: Tenant,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """The scheduled job advances overdue and cancelled tenants exactly on policy."""
    now = datetime.now(UTC)
    async with admin_sessionmaker() as session:
        await session.execute(
            text(
                "UPDATE subscriptions SET status = 'past_due', "
                "current_period_end = :grace_started WHERE organization_id = :organization_id"
            ),
            {
                "grace_started": now - timedelta(days=8),
                "organization_id": tenant.organization_id,
            },
        )
        await session.execute(
            text("UPDATE organizations SET status = 'past_due' WHERE id = :organization_id"),
            {"organization_id": tenant.organization_id},
        )
        await session.commit()

    factory = get_session_factory()
    async with factory() as session:
        await bind_tenant(session, UUID(tenant.organization_id))
        assert await process_billing_lifecycle(session, UUID(tenant.organization_id), now=now) == [
            "subscription.suspended"
        ]
        await session.commit()

    async with admin_sessionmaker() as session:
        await session.execute(
            text(
                "UPDATE subscriptions SET status = 'active', cancel_at_period_end = true, "
                "current_period_end = :period_end WHERE organization_id = :organization_id"
            ),
            {"period_end": now - timedelta(seconds=1), "organization_id": tenant.organization_id},
        )
        await session.execute(
            text("UPDATE organizations SET status = 'active' WHERE id = :organization_id"),
            {"organization_id": tenant.organization_id},
        )
        await session.commit()

    async with factory() as session:
        await bind_tenant(session, UUID(tenant.organization_id))
        assert await process_billing_lifecycle(session, UUID(tenant.organization_id), now=now) == [
            "subscription.period_cancelled"
        ]
        await session.commit()

    async with admin_sessionmaker() as session:
        await session.execute(
            text(
                "UPDATE subscriptions SET cancelled_at = :cancelled_at "
                "WHERE organization_id = :organization_id"
            ),
            {"cancelled_at": now - timedelta(days=31), "organization_id": tenant.organization_id},
        )
        await session.commit()

    async with factory() as session:
        await bind_tenant(session, UUID(tenant.organization_id))
        assert await process_billing_lifecycle(session, UUID(tenant.organization_id), now=now) == [
            "organization.anonymized"
        ]
        await session.commit()

    async with admin_sessionmaker() as session:
        organization = (
            await session.execute(
                text(
                    "SELECT name, billing_email, tax_id, deleted_at FROM organizations "
                    "WHERE id = :organization_id"
                ),
                {"organization_id": tenant.organization_id},
            )
        ).one()
        assert organization.name.startswith("Anonymized organization")
        assert organization.billing_email is None
        assert organization.tax_id is None
        assert organization.deleted_at is not None


async def test_plan_audit_retention_purges_only_expired_rows(
    tenant: Tenant,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Growth keeps 365 days: an older event is purged while a recent one remains."""
    now = datetime.now(UTC)
    async with admin_sessionmaker() as session:
        session.add_all(
            [
                AuditLog(
                    organization_id=UUID(tenant.organization_id),
                    action="retention.old",
                    created_at=now - timedelta(days=366),
                ),
                AuditLog(
                    organization_id=UUID(tenant.organization_id),
                    action="retention.current",
                    created_at=now - timedelta(days=364),
                ),
            ]
        )
        await session.commit()

    factory = get_session_factory()
    async with factory() as session:
        await bind_tenant(session, UUID(tenant.organization_id))
        assert await purge_expired_audit_logs(session, UUID(tenant.organization_id), now=now) == 1
        await session.commit()

    async with admin_sessionmaker() as session:
        actions = set(
            (
                await session.execute(
                    text(
                        "SELECT action FROM audit_logs WHERE organization_id = :organization_id "
                        "AND action LIKE 'retention.%'"
                    ),
                    {"organization_id": tenant.organization_id},
                )
            ).scalars()
        )
        assert actions == {"retention.current"}
