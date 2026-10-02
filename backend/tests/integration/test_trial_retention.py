"""An expired trial: read-only, warned, then permanently deleted (billing/trial_retention.py).

The order of these gates matters more than any one of them:

* read-only first -- every module still readable, every write refused;
* never deleted without the warning email having actually gone out;
* the deletion takes the organization's rows and nobody else's;
* choosing a plan at any point lifts read-only, and does not grant a second trial.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.email.sender import EmailMessage
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import bind_tenant, get_session_factory
from app.modules.billing.jobs import process_billing_lifecycle
from app.modules.billing.trial_retention import (
    DELETION_WARNING_EVENT,
    EXPIRED_NOTICE_EVENT,
    process_trial_retention,
)
from tests.integration.conftest import API, Tenant
from tests.integration.test_fees import build_fees, generate


class _Outbox:
    def __init__(self) -> None:
        self.sent: list[EmailMessage] = []

    async def send(self, message: EmailMessage) -> None:
        self.sent.append(message)


class _BrokenOutbox:
    async def send(self, message: EmailMessage) -> None:
        raise RuntimeError("smtp is down")


async def _end_trial(
    admin_sessionmaker: async_sessionmaker[AsyncSession], organization_id: str, ended_at: datetime
) -> None:
    async with admin_sessionmaker() as session:
        await session.execute(
            text(
                "UPDATE subscriptions SET trial_ends_at = :ended_at "
                "WHERE organization_id = :organization_id AND status = 'trialing'"
            ),
            {"ended_at": ended_at, "organization_id": organization_id},
        )
        await session.commit()


async def _run(
    organization_id: str,
    *,
    now: datetime,
    outbox: Any = None,
    lifecycle: bool = False,
) -> list[str]:
    """One maintenance pass for one tenant, exactly as `run-maintenance` does it."""
    events: list[str] = []
    async with get_session_factory()() as session:
        await bind_tenant(session, UUID(organization_id))
        if lifecycle:
            events += await process_billing_lifecycle(session, UUID(organization_id), now=now)
        events += await process_trial_retention(
            session,
            UUID(organization_id),
            settings=get_settings(),
            email_sender=outbox if outbox is not None else _Outbox(),
            now=now,
        )
        await session.commit()
    return events


async def _rows_for(
    admin_sessionmaker: async_sessionmaker[AsyncSession], organization_id: str
) -> dict[str, int]:
    counts: dict[str, int] = {}
    async with admin_sessionmaker() as session:
        for table in Base.metadata.sorted_tables:
            if "organization_id" in table.c:
                counts[table.name] = (
                    await session.execute(
                        text(f"SELECT count(*) FROM {table.name} WHERE organization_id = :o"),
                        {"o": organization_id},
                    )
                ).scalar_one()
    return {name: n for name, n in counts.items() if n}


async def test_expired_trial_is_read_only_then_warned_then_purged(
    make_tenant: Callable[..., Any],
    mailbox: list[EmailMessage],
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    doomed: Tenant = await make_tenant(name="Doomed Trust", email="d@test.example", school_code="D")
    keeper: Tenant = await make_tenant(name="Keeper Trust", email="k@test.example", school_code="K")

    # Real fee data -- vouchers, a payment, the ledger -- because that is where the
    # RESTRICT foreign keys a naive cascade would trip over live.
    fx = await build_fees(doomed, mailbox, email="d-fees@test.example")
    voucher_id = (await generate(fx)).json()["voucher_ids"][0]
    paid = await fx.post(
        f"{API}/fees/vouchers/{voucher_id}/payments", json={"amount": "100.00", "method": "cash"}
    )
    assert paid.status_code == 201, paid.text
    keeper_fx = await build_fees(keeper, mailbox, email="k-fees@test.example")
    assert (await generate(keeper_fx)).status_code == 201

    ended = datetime.now(UTC) - timedelta(minutes=1)
    await _end_trial(admin_sessionmaker, doomed.organization_id, ended)

    # Day 0: expired, suspended, told.
    outbox = _Outbox()
    events = await _run(
        doomed.organization_id, now=ended + timedelta(minutes=1), outbox=outbox, lifecycle=True
    )
    assert events == ["subscription.trial_expired", EXPIRED_NOTICE_EVENT]
    assert [m.to for m in outbox.sent] == [doomed.owner_email]
    assert "trial has ended" in outbox.sent[0].subject.lower()

    # Read-only: every module readable, every write refused, write controls hidden.
    me = (await doomed.get(f"{API}/auth/me")).json()
    assert me["read_only"] is True and me["trial_expired"] is True
    assert me["scheduled_deletion_at"] is not None
    assert "billing:manage" in me["permissions"]
    assert all(
        p.endswith(":read") or p in {"billing:manage", "invoice:download"}
        for p in me["permissions"]
    )
    assert (await fx.get(f"{API}/students")).status_code == 200
    refused = await fx.post(
        f"{API}/students",
        json={
            "admission_number": "X-1",
            "first_name": "No",
            "last_name": "Way",
            "section_id": fx.section_id,
        },
    )
    assert refused.status_code == 403
    assert refused.json()["code"] == "ORGANIZATION_READ_ONLY"

    # Idempotent: a second run the same day sends nothing.
    assert await _run(doomed.organization_id, now=ended + timedelta(hours=3)) == []

    # Day 5 (= 7 - 2): the deletion warning.
    outbox = _Outbox()
    assert await _run(doomed.organization_id, now=ended + timedelta(days=5), outbox=outbox) == [
        DELETION_WARNING_EVENT
    ]
    assert len(outbox.sent) == 1 and "deleted" in outbox.sent[0].subject.lower()
    assert await _run(doomed.organization_id, now=ended + timedelta(days=6)) == []

    # Day 7: gone.
    assert await _run(doomed.organization_id, now=ended + timedelta(days=7, minutes=1)) == [
        "organization.purged"
    ]

    assert await _rows_for(admin_sessionmaker, doomed.organization_id) == {}
    keeper_rows = await _rows_for(admin_sessionmaker, keeper.organization_id)
    assert keeper_rows.get("fee_vouchers") and keeper_rows.get("students")
    async with admin_sessionmaker() as session:
        assert (
            await session.execute(
                text("SELECT count(*) FROM organizations WHERE id = :o"),
                {"o": doomed.organization_id},
            )
        ).scalar_one() == 0
        remaining_users = set(
            (
                await session.execute(
                    text(
                        "SELECT email FROM users WHERE email IN "
                        "('d@test.example', 'd-fees@test.example', 'k@test.example')"
                    )
                )
            ).scalars()
        )
        assert remaining_users == {"k@test.example"}
        audit = (
            await session.execute(
                text(
                    "SELECT metadata->>'organization_id' FROM platform_audit_logs "
                    "WHERE action = 'platform.organization_purged'"
                )
            )
        ).scalar_one()
        assert audit == doomed.organization_id


async def test_deletion_never_happens_without_a_delivered_warning(
    tenant: Tenant,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Cron down for a month, then SMTP down: still no deletion without notice."""
    ended = datetime.now(UTC) - timedelta(days=30)
    await _end_trial(admin_sessionmaker, tenant.organization_id, ended)
    now = datetime.now(UTC)

    events = await _run(tenant.organization_id, now=now, outbox=_BrokenOutbox(), lifecycle=True)
    assert events == ["subscription.trial_expired"]
    assert await _run(tenant.organization_id, now=now, outbox=_BrokenOutbox()) == []

    # Mail works again: the warning goes out (covering the expiry notice too) ...
    outbox = _Outbox()
    assert await _run(tenant.organization_id, now=now, outbox=outbox) == [DELETION_WARNING_EVENT]
    assert len(outbox.sent) == 1
    # ... and the deletion waits the full notice period from THAT moment.
    assert await _run(tenant.organization_id, now=now + timedelta(days=1)) == []
    assert await _run(tenant.organization_id, now=now + timedelta(days=2, minutes=1)) == [
        "organization.purged"
    ]


async def test_choosing_a_plan_lifts_read_only_without_a_second_trial(
    tenant: Tenant,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    ended = datetime.now(UTC) - timedelta(minutes=1)
    await _end_trial(admin_sessionmaker, tenant.organization_id, ended)
    await _run(tenant.organization_id, now=datetime.now(UTC), lifecycle=True)

    # The upgrade is a POST from a read-only account; it must not be refused as a write.
    upgraded = await tenant.post(
        f"{API}/billing/change-plan", json={"plan_code": "growth", "billing_cycle": "monthly"}
    )
    assert upgraded.status_code == 200, upgraded.text
    assert upgraded.json()["status"] == "active", "an expired trial must not get a fresh one"

    me = (await tenant.get(f"{API}/auth/me")).json()
    assert me["read_only"] is False and me["organization_status"] == "active"
    assert "student:create" in me["permissions"]

    # And the retention job leaves it alone from now on.
    assert await _run(tenant.organization_id, now=ended + timedelta(days=30)) == []


async def test_plan_change_does_not_lift_an_admin_suspension(
    tenant: Tenant,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    async with admin_sessionmaker() as session:
        await session.execute(
            text("UPDATE organizations SET status = 'suspended' WHERE id = :o"),
            {"o": tenant.organization_id},
        )
        await session.commit()

    response = await tenant.post(
        f"{API}/billing/change-plan", json={"plan_code": "starter", "billing_cycle": "monthly"}
    )
    assert response.status_code == 403
    assert response.json()["code"] == "ORGANIZATION_READ_ONLY"
    me = (await tenant.get(f"{API}/auth/me")).json()
    assert me["read_only"] is True and me["trial_expired"] is False
