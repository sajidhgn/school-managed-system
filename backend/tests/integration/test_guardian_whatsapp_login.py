"""Parent-portal login codes on WhatsApp, and staff turning portal access on.

The WAHA gateway is replaced by an `httpx.MockTransport`, so these exercise the real
`WahaClient` requests -- the number check and the send -- without a gateway.

WHAT THESE GUARD

  1. THE CODE COMES FROM THE CHILD'S CAMPUS. It is sent from the WhatsApp session of
     a campus where the parent has a viewable child, to the chat WhatsApp names.

  2. "HAS WHATSAPP" IS CHECKED. A number with no WhatsApp gets no WhatsApp message;
     the code falls back to the SMS seam. So does a campus whose session is down.

  3. NOTHING LEAKS FOR AN UNKNOWN NUMBER. The gateway is not even asked about it.

  4. ACCESS IS TURNED ON BY STAFF, PER CHILD. The grant endpoint is idempotent,
     reuses an existing record, restores a removed link, and turning access off
     stops the campus sending codes.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest

from app.common.email.sender import EmailMessage
from app.common.sms import SmsMessage
from app.common.whatsapp.waha import WahaClient, session_name
from app.core.config import Settings
from app.modules.guardians.auth_router import get_code_dispatcher
from app.modules.guardians.delivery import GuardianCodeDelivery
from tests.integration.conftest import API, Tenant
from tests.integration.test_guardians import (
    _CODE_RE,
    OTHER_PHONE,
    PHONE,
    GuardianFixture,
    _CaptureSms,
    build_guardians,
)

PHONE_DIGITS = PHONE.lstrip("+")
PHONE_CHAT = f"{PHONE_DIGITS}@c.us"


class FakeWaha:
    """Answers the number check and the send, and records both."""

    def __init__(self) -> None:
        self.on_whatsapp: set[str] = {PHONE_DIGITS}
        self.down_sessions: set[str] = set()
        self.checked: list[tuple[str, str]] = []
        self.sent: list[tuple[str, str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/contacts/check-exists":
            session = request.url.params["session"]
            phone = request.url.params["phone"]
            self.checked.append((session, phone))
            if session in self.down_sessions:
                return httpx.Response(422, json={"message": "Session is not working"})
            exists = phone in self.on_whatsapp
            return httpx.Response(
                200, json={"numberExists": exists, "chatId": f"{phone}@c.us" if exists else None}
            )
        if request.url.path == "/api/sendText":
            body = json.loads(request.content)
            self.sent.append((body["session"], body["chatId"], body["text"]))
            return httpx.Response(201, json={"id": "sent"})
        return httpx.Response(404)


@pytest.fixture
def waha() -> FakeWaha:
    return FakeWaha()


@pytest.fixture
def sms_outbox(db_client: Any, db_settings: Settings, waha: FakeWaha) -> list[SmsMessage]:
    """Wire WAHA-backed delivery into the running app, with SMS captured behind it."""
    outbox: list[SmsMessage] = []
    settings = db_settings.model_copy(
        update={"WHATSAPP_BACKEND": "waha", "WAHA_BASE_URL": "http://waha.test"}
    )
    client = WahaClient(settings, transport=httpx.MockTransport(waha.handler))
    db_client._transport.app.dependency_overrides[get_code_dispatcher] = lambda: (
        GuardianCodeDelivery(sms=_CaptureSms(outbox), waha=client)
    )
    return outbox


@pytest.fixture
async def fx(tenant: Tenant, mailbox: list[EmailMessage]) -> GuardianFixture:
    return await build_guardians(tenant, mailbox)


async def grant(fx: GuardianFixture, student_id: str, phone: str = "0300-1234567") -> Any:
    return await fx.post(
        f"{API}/guardians/students/{student_id}/portal-access",
        json={"phone": phone, "full_name": "Muhammad Aslam", "relationship_type": "father"},
    )


async def request_code(fx: GuardianFixture, phone: str = PHONE) -> Any:
    response = await fx.tenant.client.post(
        f"{API}/guardian/auth/request-code", json={"phone": phone}
    )
    assert response.status_code == 200, response.text
    return response


def code_in(text: str) -> str:
    match = _CODE_RE.search(text)
    assert match, f"no code in {text!r}"
    return match.group(1)


# ---------------------------------------------------------------------------
# Delivery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_code_arrives_on_whatsapp_from_the_childs_campus(
    fx: GuardianFixture, sms_outbox: list[SmsMessage], waha: FakeWaha
) -> None:
    granted = await grant(fx, fx.student_ids[0])
    assert granted.status_code == 200, granted.text

    await request_code(fx)

    assert len(waha.sent) == 1
    session, chat_id, text = waha.sent[0]
    assert session == session_name(uuid.UUID(fx.tenant.school_id))
    assert chat_id == PHONE_CHAT
    assert sms_outbox == []

    verified = await fx.tenant.client.post(
        f"{API}/guardian/auth/verify",
        json={"phone": PHONE, "code": code_in(text)},
        headers={"X-Token-Transport": "body"},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "authenticated"
    token = verified.json()["tokens"]["access_token"]
    fx.tenant.client.cookies.clear()

    children = await fx.tenant.client.get(
        f"{API}/portal/children", headers={"Authorization": f"Bearer {token}"}
    )
    assert children.status_code == 200, children.text
    assert [c["student_id"] for c in children.json()] == [fx.student_ids[0]]


@pytest.mark.asyncio
async def test_a_number_without_whatsapp_gets_no_whatsapp_message(
    fx: GuardianFixture, sms_outbox: list[SmsMessage], waha: FakeWaha
) -> None:
    waha.on_whatsapp.clear()
    assert (await grant(fx, fx.student_ids[0])).status_code == 200

    await request_code(fx)

    assert waha.checked, "the number was never checked"
    assert waha.sent == []
    # Behind WhatsApp is the SMS seam -- the console in development, `null` in
    # production until an SMS provider exists.
    assert [m.to for m in sms_outbox] == [PHONE]


@pytest.mark.asyncio
async def test_a_disconnected_campus_falls_back_to_sms(
    fx: GuardianFixture, sms_outbox: list[SmsMessage], waha: FakeWaha
) -> None:
    waha.down_sessions.add(session_name(uuid.UUID(fx.tenant.school_id)))
    assert (await grant(fx, fx.student_ids[0])).status_code == 200

    await request_code(fx)

    assert waha.sent == []
    assert [m.to for m in sms_outbox] == [PHONE]


@pytest.mark.asyncio
async def test_an_unknown_number_never_reaches_the_gateway(
    fx: GuardianFixture, sms_outbox: list[SmsMessage], waha: FakeWaha
) -> None:
    assert (await grant(fx, fx.student_ids[0])).status_code == 200

    known = await request_code(fx)
    waha.checked.clear()
    waha.sent.clear()
    unknown = await request_code(fx, OTHER_PHONE)

    assert known.json()["message"] == unknown.json()["message"]
    assert set(known.json()) == set(unknown.json())
    assert waha.checked == []
    assert waha.sent == []
    assert sms_outbox == []


# ---------------------------------------------------------------------------
# Staff turning access on and off
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_granting_twice_keeps_one_parent_who_is_the_primary_contact(
    fx: GuardianFixture, sms_outbox: list[SmsMessage]
) -> None:
    first = await grant(fx, fx.student_ids[0])
    # Typed differently on purpose: it is still the same handset.
    second = await grant(fx, fx.student_ids[0], phone="+92 300 1234567")
    assert first.status_code == second.status_code == 200, second.text

    card = second.json()
    assert len(card) == 1
    assert card[0]["phone"] == PHONE
    assert card[0]["relationship_type"] == "father"
    assert card[0]["is_primary_contact"] is True
    assert card[0]["can_view_results"] is True
    assert card[0]["portal_enabled"] is True


@pytest.mark.asyncio
async def test_one_parent_granted_for_two_children_is_one_record(
    fx: GuardianFixture, sms_outbox: list[SmsMessage]
) -> None:
    a = await grant(fx, fx.student_ids[0])
    b = await grant(fx, fx.student_ids[1])
    assert a.status_code == b.status_code == 200, b.text
    assert a.json()[0]["guardian_id"] == b.json()[0]["guardian_id"]

    listed = await fx.get(f"{API}/guardians")
    assert listed.status_code == 200, listed.text
    assert listed.json()["meta"]["total"] == 1


@pytest.mark.asyncio
async def test_turning_access_off_stops_the_campus_sending_codes(
    fx: GuardianFixture, sms_outbox: list[SmsMessage], waha: FakeWaha
) -> None:
    granted = (await grant(fx, fx.student_ids[0])).json()[0]

    off = await fx.patch(
        f"{API}/guardians/{granted['guardian_id']}/students/{fx.student_ids[0]}",
        json={"can_view_results": False},
    )
    assert off.status_code == 200, off.text

    await request_code(fx)
    assert waha.sent == []

    verified = await fx.tenant.client.post(
        f"{API}/guardian/auth/verify",
        json={"phone": PHONE, "code": code_in(sms_outbox[-1].body)},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "no_access"

    # And granting again turns it back on.
    again = await grant(fx, fx.student_ids[0])
    assert again.status_code == 200, again.text
    assert again.json()[0]["can_view_results"] is True


@pytest.mark.asyncio
async def test_granting_restores_a_removed_link(
    fx: GuardianFixture, sms_outbox: list[SmsMessage]
) -> None:
    granted = (await grant(fx, fx.student_ids[0])).json()[0]
    removed = await fx.delete(
        f"{API}/guardians/{granted['guardian_id']}/students/{fx.student_ids[0]}"
    )
    assert removed.status_code == 204, removed.text
    assert (await fx.get(f"{API}/guardians/students/{fx.student_ids[0]}")).json() == []

    again = await grant(fx, fx.student_ids[0])
    assert again.status_code == 200, again.text
    assert [g["guardian_id"] for g in again.json()] == [granted["guardian_id"]]


@pytest.mark.asyncio
async def test_granting_needs_the_registry_permissions(
    fx: GuardianFixture, sms_outbox: list[SmsMessage]
) -> None:
    anonymous = await fx.tenant.client.post(
        f"{API}/guardians/students/{fx.student_ids[0]}/portal-access",
        json={"phone": PHONE, "full_name": "X", "relationship_type": "father"},
    )
    assert anonymous.status_code == 401, anonymous.text
