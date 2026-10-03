"""Class WhatsApp groups: the monthly fee notice, custom messages, and the outbox.

The failure modes worth a test:

  * POSTING TWICE. A nightly pass that retries or overlaps must not put October's
    reminder into 5-A two times -- parents notice, and stop reading the group.
  * ANNOUNCING WHAT IS NOT A BILL. Draft challans have not been sent to anyone;
    a "please pay by the 10th" for them is a message the office must then retract.
  * ONE FAMILY'S DUES IN A SHARED GROUP. The notice carries the class's standard
    fee, never an individual's balance.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from uuid import UUID

from app.common.email.sender import EmailMessage
from app.common.whatsapp.sender import WhatsAppGroupMessage
from app.db.session import session_scope
from app.modules.whatsapp.jobs import dispatch_outbox, queue_fee_notices_for_organization
from app.modules.whatsapp.service import current_period
from tests.integration.conftest import API, Tenant
from tests.integration.test_fees import PERIOD, FeeFixture, build_fees, generate, make_scoped_actor

INVITE = "https://chat.whatsapp.com/AbCdEfGhIjKlMnOpQrStUv"


async def link_group(fx: FeeFixture, **overrides: Any) -> Any:
    body: dict[str, Any] = {
        "class_id": fx.class_id,
        "name": "Grade 10 Parents",
        "invite_link": INVITE,
        **overrides,
    }
    return await fx.post(f"{API}/whatsapp/groups", json=body)


async def enable_notice(fx: FeeFixture, **overrides: Any) -> Any:
    settings = await fx.get(f"{API}/whatsapp/settings")
    assert settings.status_code == 200, settings.text
    body = {
        "fee_notice_enabled": True,
        "send_day": 1,
        "fee_template": settings.json()["fee_template"],
        "monthly_note": None,
        **overrides,
    }
    return await fx.put(f"{API}/whatsapp/settings", json=body)


class _Capture:
    def __init__(self) -> None:
        self.sent: list[WhatsAppGroupMessage] = []

    async def send(self, message: WhatsAppGroupMessage) -> None:
        self.sent.append(message)


class _Broken:
    async def send(self, message: WhatsAppGroupMessage) -> None:
        raise RuntimeError("WhatsApp Web did not load")


# ---------------------------------------------------------------------------
# Groups
# ---------------------------------------------------------------------------


async def test_a_group_is_linked_by_its_invite_link_and_stored_as_the_code(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    fx = await build_fees(tenant, mailbox)
    created = await link_group(fx, section_id=fx.section_id)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["invite_code"] == "AbCdEfGhIjKlMnOpQrStUv"
    assert body["class_name"] == "Grade 10"
    assert body["section_name"] == "A"

    listed = await fx.get(f"{API}/whatsapp/groups")
    assert [g["id"] for g in listed.json()] == [body["id"]]


async def test_the_same_invite_link_cannot_be_linked_twice(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    fx = await build_fees(tenant, mailbox)
    assert (await link_group(fx)).status_code == 201
    again = await link_group(fx, name="Duplicate")
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "DUPLICATE_INVITE_LINK"


async def test_something_that_is_not_an_invite_link_is_refused(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    fx = await build_fees(tenant, mailbox)
    refused = await link_group(fx, invite_link="https://example.com/not-whatsapp")
    assert refused.status_code == 422, refused.text


# ---------------------------------------------------------------------------
# The fee notice
# ---------------------------------------------------------------------------


async def test_the_fee_notice_states_the_class_fee_and_due_date_once_per_month(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """THE IDEMPOTENCE TEST: queuing the same month twice queues it once."""
    fx = await build_fees(tenant, mailbox)
    await link_group(fx)
    await enable_notice(fx, monthly_note="School closed on Friday for the holiday.")
    assert (await generate(fx, issue=True)).status_code in (200, 201)

    first = await fx.post(f"{API}/whatsapp/fee-notices", json={"period_label": PERIOD})
    assert first.status_code == 200, first.text
    assert first.json()["queued"] == 1

    second = await fx.post(f"{API}/whatsapp/fee-notices", json={"period_label": PERIOD})
    assert second.json()["queued"] == 0
    assert "already" in second.json()["skipped"][0]["reason"]

    outbox = (await fx.get(f"{API}/whatsapp/messages")).json()["items"]
    assert len(outbox) == 1
    body = outbox[0]["body"]
    assert "Grade 10" in body
    assert "August 2026" in body
    assert "Rs 6,500" in body  # tuition 5000 + transport 1500, the class standard
    assert body.endswith("School closed on Friday for the holiday.")
    assert outbox[0]["status"] == "queued"


async def test_draft_challans_are_not_announced(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    fx = await build_fees(tenant, mailbox)
    await link_group(fx)
    assert (await generate(fx, issue=False)).status_code in (200, 201)

    result = await fx.post(f"{API}/whatsapp/fee-notices", json={"period_label": PERIOD})
    assert result.json()["queued"] == 0
    assert "No issued challans" in result.json()["skipped"][0]["reason"]


async def test_the_nightly_pass_queues_on_the_send_day_and_not_before(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    today = date.today()
    fx = await build_fees(tenant, mailbox)
    await link_group(fx)
    assert (await generate(fx, period=current_period(today), issue=True)).status_code in (200, 201)
    org = UUID(tenant.organization_id)

    if today.day < 28:
        await enable_notice(fx, send_day=today.day + 1)
        async with session_scope(org) as session:
            assert await queue_fee_notices_for_organization(session, org, today=today) == 0

    await enable_notice(fx, send_day=min(today.day, 28))
    async with session_scope(org) as session:
        assert await queue_fee_notices_for_organization(session, org, today=today) == 1
    async with session_scope(org) as session:
        assert await queue_fee_notices_for_organization(session, org, today=today) == 0


async def test_a_notice_switched_off_queues_nothing_at_night(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    today = date.today()
    fx = await build_fees(tenant, mailbox)
    await link_group(fx)
    assert (await generate(fx, period=current_period(today), issue=True)).status_code in (200, 201)
    await enable_notice(fx, fee_notice_enabled=False, send_day=1)
    org = UUID(tenant.organization_id)
    async with session_scope(org) as session:
        assert await queue_fee_notices_for_organization(session, org, today=today) == 0


# ---------------------------------------------------------------------------
# Custom messages and the outbox
# ---------------------------------------------------------------------------


async def test_a_custom_message_is_queued_then_dispatched_and_marked_sent(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    fx = await build_fees(tenant, mailbox)
    group = (await link_group(fx)).json()
    queued = await fx.post(
        f"{API}/whatsapp/messages", json={"body": "PTM on Saturday at 10am.", "group_ids": None}
    )
    assert queued.status_code == 201, queued.text
    assert queued.json()["queued"] == 1

    capture = _Capture()
    sent, failed = await dispatch_outbox(UUID(tenant.organization_id), capture, limit=10)
    assert (sent, failed) == (1, 0)
    assert capture.sent[0].group_code == group["invite_code"]
    assert capture.sent[0].body == "PTM on Saturday at 10am."

    outbox = (await fx.get(f"{API}/whatsapp/messages")).json()["items"]
    assert outbox[0]["status"] == "sent"
    assert outbox[0]["sent_at"] is not None

    # Drained: a second pass sends nothing again.
    assert await dispatch_outbox(UUID(tenant.organization_id), capture, limit=10) == (0, 0)


async def test_a_failed_send_is_kept_with_its_error_and_can_be_retried(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    fx = await build_fees(tenant, mailbox)
    await link_group(fx)
    await fx.post(f"{API}/whatsapp/messages", json={"body": "Hello"})

    assert await dispatch_outbox(UUID(tenant.organization_id), _Broken(), limit=10) == (0, 1)
    message = (await fx.get(f"{API}/whatsapp/messages")).json()["items"][0]
    assert message["status"] == "failed"
    assert "did not load" in message["last_error"]

    retried = await fx.post(f"{API}/whatsapp/messages/{message['id']}/retry")
    assert retried.status_code == 204, retried.text
    assert await dispatch_outbox(UUID(tenant.organization_id), _Capture(), limit=10) == (1, 0)


async def test_sending_needs_send_and_linking_needs_manage(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    fx = await build_fees(tenant, mailbox)
    await link_group(fx)
    sender = await make_scoped_actor(
        tenant,
        mailbox,
        "wa-sender@test.example",
        ["whatsapp:read", "whatsapp:send"],
        code="wa_sender",
    )
    headers = {"Authorization": f"Bearer {sender}"}

    may_send = await tenant.client.post(
        f"{API}/whatsapp/messages", headers=headers, json={"body": "Hi"}
    )
    assert may_send.status_code == 201, may_send.text

    may_not_link = await tenant.client.post(
        f"{API}/whatsapp/groups",
        headers=headers,
        json={
            "class_id": fx.class_id,
            "name": "X",
            "invite_link": "https://chat.whatsapp.com/ZzYyXxWwVvUuTtSsRrQqPp",
        },
    )
    assert may_not_link.status_code == 403, may_not_link.text
