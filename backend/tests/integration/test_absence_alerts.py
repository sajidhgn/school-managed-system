"""Absence alerts: a WhatsApp message to a parent when their child is marked absent.

Registers are opened, marked and submitted through the staff API; the alerts are
read from the WhatsApp outbox and dispatched through a capturing sender, and through
the real `WahaSender` against a mocked gateway.

WHAT THESE GUARD

  1. OFF UNTIL A CAMPUS TURNS IT ON, and a settings save that does not mention the
     switch does not turn it off.
  2. ONLY TODAY'S WHOLE-DAY REGISTER. A lesson register, or a day back-filled later,
     messages nobody.
  3. ONLY THE RIGHT PEOPLE. A guardian who opted out for this child, or who may only
     collect them, is not told. The message names the child and the school, in the
     guardian's language.
  4. NEVER TWICE. Reopening and resubmitting a register queues no second alert.
  5. A NUMBER WITHOUT WHATSAPP FAILS VISIBLY in the outbox rather than reading as sent.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any
from uuid import UUID

import httpx
import pytest

from app.common.email.sender import EmailMessage
from app.common.whatsapp.sender import WahaSender, WhatsAppDirectMessage, WhatsAppGroupMessage
from app.common.whatsapp.waha import WahaClient
from app.core.config import Settings
from app.modules.whatsapp.jobs import dispatch_outbox
from tests.integration.conftest import API, Tenant
from tests.integration.test_academic_foundation import Campus, build_campus
from tests.integration.test_attendance_analytics import _register

MOTHER = "0300-7654321"
MOTHER_E164 = "+923007654321"


class _Capture:
    def __init__(self) -> None:
        self.groups: list[WhatsAppGroupMessage] = []
        self.direct: list[WhatsAppDirectMessage] = []

    async def send(self, message: WhatsAppGroupMessage) -> None:
        self.groups.append(message)

    async def send_direct(self, message: WhatsAppDirectMessage) -> None:
        self.direct.append(message)


async def _set_alerts(campus: Campus, enabled: bool | None) -> Any:
    current = (await campus.get(f"{API}/whatsapp/settings")).json()
    body: dict[str, Any] = {
        "fee_notice_enabled": current["fee_notice_enabled"],
        "send_day": current["send_day"],
        "fee_template": current["fee_template"],
        "monthly_note": current["monthly_note"],
    }
    if enabled is not None:
        body["absence_alerts_enabled"] = enabled
    saved = await campus.put(f"{API}/whatsapp/settings", json=body)
    assert saved.status_code == 200, saved.text
    return saved.json()


async def _grant(campus: Campus, student_id: str, phone: str = MOTHER, name: str = "Ayesha") -> str:
    granted = await campus.post(
        f"{API}/guardians/students/{student_id}/portal-access",
        json={"phone": phone, "full_name": name, "relationship_type": "mother"},
    )
    assert granted.status_code == 200, granted.text
    return str(granted.json()[0]["guardian_id"])


async def _alerts(campus: Campus) -> list[dict[str, Any]]:
    listed = await campus.get(f"{API}/whatsapp/messages")
    assert listed.status_code == 200, listed.text
    return [m for m in listed.json()["items"] if m["kind"] == "absence_alert"]


@pytest.fixture
async def campus(tenant: Tenant, mailbox: list[EmailMessage]) -> Campus:
    campus = await build_campus(tenant, mailbox)
    await _grant(campus, campus.student_ids[0])
    return campus


# ---------------------------------------------------------------------------
# The switch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_alerts_are_off_until_the_campus_turns_them_on(campus: Campus) -> None:
    assert (await campus.get(f"{API}/whatsapp/settings")).json()["absence_alerts_enabled"] is False
    await _register(campus, campus.section_id, 0, {campus.student_ids[0]: "absent"})
    assert await _alerts(campus) == []


@pytest.mark.asyncio
async def test_saving_the_fee_settings_does_not_switch_alerts_off(campus: Campus) -> None:
    assert (await _set_alerts(campus, True))["absence_alerts_enabled"] is True
    assert (await _set_alerts(campus, None))["absence_alerts_enabled"] is True
    assert (await _set_alerts(campus, False))["absence_alerts_enabled"] is False


# ---------------------------------------------------------------------------
# Which registers
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_todays_register_alerts_the_absent_childs_guardian(campus: Campus) -> None:
    await _set_alerts(campus, True)
    await _register(campus, campus.section_id, 0, {campus.student_ids[0]: "absent"})

    alerts = await _alerts(campus)
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["group_name"] == "Ayesha · parent of Student1 Test"
    assert alert["status"] == "queued"
    assert alert["period_label"] == str(date.today())
    assert "Student1 Test was marked absent" in alert["body"]
    assert "Assalam-o-Alaikum Ayesha" in alert["body"]


@pytest.mark.asyncio
async def test_late_is_not_absent(campus: Campus) -> None:
    """Late counts as present under the module's rules, so it alerts nobody."""
    await _set_alerts(campus, True)
    await _register(campus, campus.section_id, 0, {campus.student_ids[0]: "late"})
    assert await _alerts(campus) == []


@pytest.mark.asyncio
async def test_lesson_and_back_filled_registers_alert_nobody(campus: Campus) -> None:
    await _set_alerts(campus, True)
    await _register(campus, campus.section_id, 1, {campus.student_ids[0]: "absent"})
    await _register(campus, campus.section_id, 0, {campus.student_ids[0]: "absent"}, period=3)
    assert await _alerts(campus) == []


@pytest.mark.asyncio
async def test_reopening_and_resubmitting_does_not_alert_twice(campus: Campus) -> None:
    await _set_alerts(campus, True)
    session_id = await _register(campus, campus.section_id, 0, {campus.student_ids[0]: "absent"})

    reopened = await campus.post(
        f"{API}/attendance/{session_id}/reopen", json={"reason": "Corrected a mark"}
    )
    assert reopened.status_code == 200, reopened.text
    resubmitted = await campus.post(f"{API}/attendance/{session_id}/submit")
    assert resubmitted.status_code == 200, resubmitted.text

    assert len(await _alerts(campus)) == 1


# ---------------------------------------------------------------------------
# Who is told
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_opted_out_and_pickup_only_guardians_are_not_told(campus: Campus) -> None:
    await _set_alerts(campus, True)
    child = campus.student_ids[0]

    father = await campus.post(
        f"{API}/guardians", json={"phone": "0300-1112223", "full_name": "Opted Out"}
    )
    assert father.status_code == 201, father.text
    linked = await campus.post(
        f"{API}/guardians/{father.json()['id']}/students",
        json={"student_id": child, "relationship_type": "father", "receives_notifications": False},
    )
    assert linked.status_code == 201, linked.text

    neighbour = await campus.post(
        f"{API}/guardians", json={"phone": "0300-4445556", "full_name": "Neighbour"}
    )
    assert neighbour.status_code == 201, neighbour.text
    linked = await campus.post(
        f"{API}/guardians/{neighbour.json()['id']}/students",
        json={
            "student_id": child,
            "relationship_type": "other",
            "relationship_label": "Neighbour",
            "can_pickup": True,
            "can_view_results": False,
        },
    )
    assert linked.status_code == 201, linked.text

    await _register(campus, campus.section_id, 0, {child: "absent"})
    assert [a["group_name"] for a in await _alerts(campus)] == ["Ayesha · parent of Student1 Test"]


@pytest.mark.asyncio
async def test_an_urdu_reading_guardian_gets_the_alert_in_urdu(campus: Campus) -> None:
    await _set_alerts(campus, True)
    child = campus.student_ids[1]
    created = await campus.post(
        f"{API}/guardians",
        json={"phone": "0321-9998887", "full_name": "Bilal", "preferred_locale": "ur"},
    )
    assert created.status_code == 201, created.text
    linked = await campus.post(
        f"{API}/guardians/{created.json()['id']}/students",
        json={"student_id": child, "relationship_type": "father"},
    )
    assert linked.status_code == 201, linked.text

    await _register(campus, campus.section_id, 0, {child: "absent"})
    (alert,) = await _alerts(campus)
    assert "Student2 Test کی غیر حاضری لگی ہے" in alert["body"]


# ---------------------------------------------------------------------------
# Sending
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_alert_is_sent_to_the_guardian_not_a_group(
    tenant: Tenant, campus: Campus
) -> None:
    await _set_alerts(campus, True)
    await _register(campus, campus.section_id, 0, {campus.student_ids[0]: "absent"})

    capture = _Capture()
    assert await dispatch_outbox(UUID(tenant.organization_id), capture, limit=10) == (1, 0)
    assert capture.groups == []
    (sent,) = capture.direct
    assert sent.phone == MOTHER_E164
    assert sent.purpose == "absence_alert"
    assert str(sent.school_id) == tenant.school_id
    assert (await _alerts(campus))[0]["status"] == "sent"


@pytest.mark.asyncio
async def test_a_number_without_whatsapp_fails_visibly(
    tenant: Tenant, campus: Campus, db_settings: Settings
) -> None:
    await _set_alerts(campus, True)
    await _register(campus, campus.section_id, 0, {campus.student_ids[0]: "absent"})

    sent: list[str] = []

    def gateway(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/contacts/check-exists":
            return httpx.Response(200, json={"numberExists": False})
        if request.url.path == "/api/sendText":
            sent.append(json.loads(request.content)["chatId"])
            return httpx.Response(201, json={})
        return httpx.Response(404)

    settings = db_settings.model_copy(
        update={"WHATSAPP_BACKEND": "waha", "WAHA_BASE_URL": "http://waha.test"}
    )
    sender = WahaSender(WahaClient(settings, transport=httpx.MockTransport(gateway)))
    assert await dispatch_outbox(UUID(tenant.organization_id), sender, limit=10) == (0, 1)
    assert sent == []

    (alert,) = await _alerts(campus)
    assert alert["status"] == "failed"
    assert "not on WhatsApp" in (alert["last_error"] or "")
