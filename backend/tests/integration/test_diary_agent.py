"""The diary agent: a teacher photographs the diary, the agent posts it to the class group.

Driven end to end through the signed WAHA webhook, with WAHA itself replaced by an
`httpx.MockTransport` and the model by a scripted fake. The failure modes worth a
test:

  * POSTING WITHOUT AN OK. Nothing reaches parents until the teacher confirms the
    exact text they were shown.
  * ANSWERING A STRANGER. The school's number also receives parents' messages;
    an unknown number must get no reply at all.
  * POSTING OUTSIDE THE TEACHER'S CLASSES. The model's class guess is only ever
    accepted from the teacher's own groups.
  * A FORGED WEBHOOK. Without the HMAC, nobody can speak as a teacher.
  * POSTING TWICE. A redelivered webhook or a double OK posts once.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

import httpx
import pytest
from httpx import AsyncClient
from PIL import Image

from app.common.email.sender import EmailMessage
from app.common.whatsapp.waha import WahaClient, session_name, sign_webhook
from app.core.config import Settings
from app.modules.diary_agent.agent import DiaryLine, DiaryReading, ReadingContext
from app.modules.whatsapp.router import get_diary_agent_factory, get_waha_client
from tests.integration.conftest import API, STRONG_PASSWORD, Tenant
from tests.integration.staff import _subject
from tests.integration.test_academic_foundation import Campus, build_campus

pytestmark = pytest.mark.asyncio

SECRET = "waha-test-secret"
TEACHER_PHONE = "0300-1234567"
TEACHER_CHAT = "923001234567@c.us"
INVITE_A = "https://chat.whatsapp.com/SectionAaaaaaaaaaaaaaaa"
INVITE_B = "https://chat.whatsapp.com/SectionBbbbbbbbbbbbbbbb"
INVITE_OTHER = "https://chat.whatsapp.com/OtherClassccccccccccccc"


@pytest.fixture(scope="module")
def db_settings(db_settings: Settings) -> Settings:
    return db_settings.model_copy(
        update={
            "WHATSAPP_BACKEND": "waha",
            "WAHA_BASE_URL": "http://waha.test",
            "WAHA_WEBHOOK_SECRET": SECRET,
            "WAHA_WEBHOOK_URL": "http://api.test/api/v1/whatsapp/webhook",
        }
    )


# ---------------------------------------------------------------------------
# Fakes: the WAHA gateway and the model
# ---------------------------------------------------------------------------


def _photo() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (60, 80), "white").save(out, format="PNG")
    return out.getvalue()


class FakeWaha:
    """Answers the WAHA calls the app makes, and records what it was asked to send."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.session_status = "WORKING"
        self.lids: dict[str, str] = {}
        self.sessions_created: list[dict[str, Any]] = []

    def replies_to(self, chat_id: str) -> list[str]:
        return [text for chat, text in self.sent if chat == chat_id]

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/sendText":
            body = json.loads(request.content)
            self.sent.append((body["chatId"], body["text"]))
            return httpx.Response(201, json={"id": "sent"})
        if path.startswith("/api/files/"):
            return httpx.Response(200, content=_photo())
        if path.endswith("/groups/join-info"):
            code = request.url.params["code"]
            return httpx.Response(200, json={"id": f"{code}@g.us"})
        if "/lids/" in path:
            lid = path.rsplit("/", 1)[-1].replace("%40", "@")
            return httpx.Response(200, json={"lid": lid, "pn": self.lids.get(lid)})
        if path.endswith("/auth/qr"):
            return httpx.Response(200, json={"mimetype": "image/png", "data": "UVI="})
        if path == "/api/sessions" and request.method == "POST":
            self.sessions_created.append(json.loads(request.content))
            self.session_status = "STARTING"
            return httpx.Response(201, json={})
        if path.startswith("/api/sessions/"):
            if request.method == "GET":
                if self.session_status == "MISSING":
                    return httpx.Response(404)
                return httpx.Response(
                    200,
                    json={
                        "status": self.session_status,
                        "me": {"id": "923000000000@c.us", "pushName": "School"},
                    },
                )
            return httpx.Response(200, json={})
        return httpx.Response(404)


@dataclass
class FakeAgent:
    reading: DiaryReading
    revision: DiaryReading | None = None
    contexts: list[ReadingContext] = field(default_factory=list)
    requests: list[str] = field(default_factory=list)

    async def read_page(self, image: bytes, mimetype: str, context: ReadingContext) -> DiaryReading:
        assert image  # the photo was downloaded
        self.contexts.append(context)
        return self.reading

    async def revise(
        self, reading: DiaryReading, request: str, context: ReadingContext
    ) -> DiaryReading:
        self.requests.append(request)
        return self.revision or reading


def reading(class_choice: str | None, **overrides: Any) -> DiaryReading:
    values: dict[str, Any] = {
        "is_diary": True,
        "class_label": "IX-A",
        "class_choice": class_choice,
        "diary_date": "2026-10-16",
        "entries": [
            DiaryLine(subject="English", homework="Learn the poem on page 12."),
            DiaryLine(subject="Maths", homework="Exercise 4.2, Q1-Q5."),
        ],
        "notes": "Bring your art copy tomorrow.",
        **overrides,
    }
    return DiaryReading(**values)


# ---------------------------------------------------------------------------
# Fixture: a campus, a teacher with a phone, a linked group, the fakes wired in
# ---------------------------------------------------------------------------


@dataclass
class World:
    tenant: Tenant
    campus: Campus
    waha: FakeWaha
    agent: FakeAgent
    teacher_id: str = ""
    groups: dict[str, str] = field(default_factory=dict)

    @property
    def client(self) -> AsyncClient:
        return self.tenant.client

    async def webhook(self, payload: dict[str, Any], *, secret: str = SECRET) -> httpx.Response:
        school_id = UUID(self.tenant.school_id)
        envelope = {
            "id": "evt_1",
            "event": "message",
            "session": session_name(school_id),
            "metadata": {
                "organization_id": self.tenant.organization_id,
                "school_id": self.tenant.school_id,
            },
            "payload": payload,
        }
        raw = json.dumps(envelope).encode()
        return await self.client.post(
            f"{API}/whatsapp/webhook",
            content=raw,
            headers={
                "Content-Type": "application/json",
                "X-Webhook-Hmac": sign_webhook(raw, secret),
                "X-Webhook-Hmac-Algorithm": "sha512",
            },
        )

    async def photo(self, message_id: str = "photo-1", sender: str = TEACHER_CHAT) -> None:
        response = await self.webhook(
            {
                "id": message_id,
                "from": sender,
                "fromMe": False,
                "body": "",
                "hasMedia": True,
                "media": {
                    "url": f"http://localhost:3000/api/files/{message_id}.jpeg",
                    "mimetype": "image/jpeg",
                },
            }
        )
        assert response.status_code == 200, response.text

    async def text(self, body: str, message_id: str, sender: str = TEACHER_CHAT) -> None:
        response = await self.webhook(
            {"id": message_id, "from": sender, "fromMe": False, "body": body, "hasMedia": False}
        )
        assert response.status_code == 200, response.text

    async def outbox(self) -> list[dict[str, Any]]:
        listed = await self.campus.get(f"{API}/whatsapp/messages")
        assert listed.status_code == 200, listed.text
        return list(listed.json()["items"])

    async def drafts(self) -> list[dict[str, Any]]:
        listed = await self.campus.get(f"{API}/diary-agent/drafts")
        assert listed.status_code == 200, listed.text
        return list(listed.json()["items"])

    async def link_group(self, name: str, invite: str, **body: Any) -> str:
        created = await self.campus.post(
            f"{API}/whatsapp/groups",
            json={"class_id": self.campus.class_id, "name": name, "invite_link": invite, **body},
        )
        assert created.status_code == 201, created.text
        self.groups[name] = created.json()["id"]
        return str(created.json()["id"])


async def add_member(
    tenant: Tenant, email: str, name: str, *, role_code: str, phone: str | None
) -> str:
    roles = await tenant.get(f"{API}/schools/{tenant.school_id}/roles")
    role_id = next(r["id"] for r in roles.json() if r["code"] == role_code)
    created = await tenant.post(
        f"{API}/schools/{tenant.school_id}/members",
        json={"email": email, "full_name": name, "password": STRONG_PASSWORD, "role_id": role_id},
    )
    assert created.status_code == 201, created.text
    if phone is not None:
        patched = await tenant.patch(
            f"{API}/schools/{tenant.school_id}/members/{created.json()['membership_id']}",
            json={"phone": phone},
        )
        assert patched.status_code == 200, patched.text
    return str(created.json()["user_id"])


@pytest.fixture
async def world(tenant: Tenant, mailbox: list[EmailMessage], db_settings: Settings) -> World:
    campus = await build_campus(tenant, mailbox, students=0)
    waha = FakeWaha()
    agent = FakeAgent(reading=reading("Grade 9-A"))

    app = tenant.client._transport.app  # type: ignore[attr-defined]
    transport = httpx.MockTransport(waha.handler)
    app.dependency_overrides[get_waha_client] = lambda: WahaClient(db_settings, transport=transport)
    app.dependency_overrides[get_diary_agent_factory] = lambda: (lambda: agent)

    w = World(tenant=tenant, campus=campus, waha=waha, agent=agent)
    w.teacher_id = await add_member(
        tenant, "ayesha@test.example", "Ayesha Khan", role_code="teacher", phone=TEACHER_PHONE
    )
    # Class teacher of 9-A: the 9-A group is hers.
    assigned = await campus.patch(
        f"{API}/classes/sections/{campus.section_id}", json={"class_teacher_id": w.teacher_id}
    )
    assert assigned.status_code == 200, assigned.text
    await w.link_group("9-A Parents", INVITE_A, section_id=campus.section_id)
    return w


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


async def test_a_photo_is_previewed_and_posted_only_after_ok(world: World) -> None:
    await world.photo()

    replies = world.waha.replies_to(TEACHER_CHAT)
    assert replies[0].startswith("Got it")
    preview = replies[-1]
    assert "*Grade 9-A*" in preview and '"9-A Parents"' in preview
    assert "▪️ *English:* Learn the poem on page 12." in preview
    assert "Bring your art copy tomorrow." in preview
    assert "Friday, 16 Oct 2026" in preview
    # The model was offered only this teacher's class, and the curriculum's subjects.
    assert world.agent.contexts[0].class_options == ["Grade 9-A"]

    assert await world.outbox() == []  # NOTHING before the OK
    [draft] = await world.drafts()
    assert draft["status"] == "awaiting_confirmation"
    assert draft["teacher_name"] == "Ayesha Khan"

    await world.text("OK", "msg-ok")

    [message] = await world.outbox()
    assert message["kind"] == "diary"
    assert message["status"] == "sent"
    assert message["created_by_name"] == "Ayesha Khan"
    assert message["body"] == draft["body"]  # exactly the text she approved
    group_posts = [(c, t) for c, t in world.waha.sent if c.endswith("@g.us")]
    assert group_posts == [("SectionAaaaaaaaaaaaaaaa@g.us", draft["body"])]
    assert world.waha.replies_to(TEACHER_CHAT)[-1] == '✅ Posted to "9-A Parents".'

    # A second OK (double tap, or a redelivered webhook) posts nothing more.
    await world.text("ok", "msg-ok-again")
    assert len(await world.outbox()) == 1


async def test_a_correction_revises_the_draft_before_posting(world: World) -> None:
    world.agent.revision = reading(
        "Grade 9-A",
        entries=[
            DiaryLine(subject="English", homework="Learn the poem on page 12."),
            DiaryLine(subject="Maths", homework="Exercise 4.3, Q1-Q5."),
        ],
    )
    await world.photo()
    await world.text("Maths is exercise 4.3 not 4.2", "msg-fix")

    assert world.agent.requests == ["Maths is exercise 4.3 not 4.2"]
    assert "Exercise 4.3" in world.waha.replies_to(TEACHER_CHAT)[-1]
    assert await world.outbox() == []

    await world.text("yes", "msg-ok")
    [message] = await world.outbox()
    assert "Exercise 4.3" in message["body"] and "Exercise 4.2" not in message["body"]


async def test_cancel_discards_and_a_redelivered_photo_is_read_once(world: World) -> None:
    await world.photo("photo-1")
    await world.photo("photo-1")  # WAHA retrying the same message
    assert len(world.agent.contexts) == 1
    assert len(await world.drafts()) == 1

    await world.text("cancel", "msg-cancel")
    [draft] = await world.drafts()
    assert draft["status"] == "cancelled"
    assert world.waha.replies_to(TEACHER_CHAT)[-1] == "Cancelled. Nothing was posted."

    await world.text("ok", "msg-ok")  # nothing open any more: just the help text
    assert await world.outbox() == []
    assert "Send me a photo" in world.waha.replies_to(TEACHER_CHAT)[-1]


async def test_the_campus_format_is_what_parents_receive(world: World) -> None:
    fmt = {
        "enabled": True,
        "template": "{school} | {class} | {date}\n{entries}\n-- {teacher}",
        "entry_template": "{subject} => {homework}",
        "instructions": "Keep Urdu homework in Urdu.",
    }
    previewed = await world.campus.post(f"{API}/diary-agent/preview", json=fmt)
    assert previewed.status_code == 200, previewed.text
    assert "Grade 5-B" in previewed.json()["body"]
    assert "English => " in previewed.json()["body"]

    saved = await world.campus.put(f"{API}/diary-agent/settings", json=fmt)
    assert saved.status_code == 200, saved.text

    await world.photo()
    await world.text("ok", "msg-ok")
    [message] = await world.outbox()
    assert message["body"].splitlines()[1:] == [
        "English => Learn the poem on page 12.",
        "Maths => Exercise 4.2, Q1-Q5.",
        "-- Ayesha Khan",
    ]
    assert world.agent.contexts[0].instructions == "Keep Urdu homework in Urdu."


# ---------------------------------------------------------------------------
# Who may speak, and where it may go
# ---------------------------------------------------------------------------


async def test_a_forged_webhook_is_refused(world: World) -> None:
    response = await world.webhook(
        {"id": "x", "from": TEACHER_CHAT, "body": "ok", "hasMedia": False}, secret="wrong"
    )
    assert response.status_code == 401
    assert world.waha.sent == []


async def test_an_unknown_number_gets_no_reply_at_all(world: World) -> None:
    await world.photo(sender="923339999999@c.us")
    await world.text("hello?", "msg-parent", sender="923339999999@c.us")
    assert world.waha.sent == []
    assert await world.drafts() == []


async def test_staff_without_the_permission_is_told_so(world: World) -> None:
    await add_member(
        world.tenant, "acc@test.example", "Accountant", role_code="accountant", phone="03011112222"
    )
    await world.photo(sender="923011112222@c.us")
    assert "not allowed" in world.waha.replies_to("923011112222@c.us")[-1]
    assert await world.drafts() == []


async def test_a_privacy_id_sender_is_resolved_to_their_phone(world: World) -> None:
    world.waha.lids["555111@lid"] = TEACHER_CHAT
    await world.photo(sender="555111@lid")
    assert "*Grade 9-A*" in world.waha.replies_to(TEACHER_CHAT)[-1]


async def test_the_class_is_asked_for_when_the_page_does_not_say(world: World) -> None:
    section_b = await world.campus.post(
        f"{API}/classes/{world.campus.class_id}/sections", json={"name": "B"}
    )
    assert section_b.status_code == 201, section_b.text
    # Maths teacher of Grade 9: every section of the class is hers now.
    await _subject(world.campus, "MATH", world.teacher_id)
    await world.link_group("9-B Parents", INVITE_B, section_id=section_b.json()["id"])
    world.agent.reading = reading(None, class_label=None)

    await world.photo()
    question = world.waha.replies_to(TEACHER_CHAT)[-1]
    assert "1. Grade 9-A (9-A Parents)" in question
    assert "2. Grade 9-B (9-B Parents)" in question
    assert world.agent.contexts[0].subjects == ["Subject MATH"]

    await world.text("2", "msg-pick")
    assert "*Grade 9-B*" in world.waha.replies_to(TEACHER_CHAT)[-1]
    await world.text("ok", "msg-ok")
    [message] = await world.outbox()
    assert message["group_id"] == world.groups["9-B Parents"]


async def test_the_model_cannot_send_it_to_a_class_the_teacher_does_not_teach(
    world: World,
) -> None:
    other = await world.campus.post(f"{API}/classes", json={"name": "Grade 10", "level": 10})
    assert other.status_code == 201, other.text
    linked = await world.campus.post(
        f"{API}/whatsapp/groups",
        json={"class_id": other.json()["id"], "name": "10 Parents", "invite_link": INVITE_OTHER},
    )
    assert linked.status_code == 201, linked.text
    world.agent.reading = reading("Grade 10")  # a page that claims another class

    await world.photo()
    assert world.agent.contexts[0].class_options == ["Grade 9-A"]
    await world.text("CLASS Grade 10", "msg-class")  # nor can the teacher pick it
    assert "couldn't match" in world.waha.replies_to(TEACHER_CHAT)[-1]
    await world.text("ok", "msg-ok")
    [message] = await world.outbox()
    assert message["group_id"] == world.groups["9-A Parents"]


async def test_switching_the_agent_off_silences_it(world: World) -> None:
    settings = (await world.campus.get(f"{API}/diary-agent/settings")).json()
    off = {k: settings[k] for k in ("template", "entry_template", "instructions")}
    saved = await world.campus.put(f"{API}/diary-agent/settings", json={**off, "enabled": False})
    assert saved.status_code == 200, saved.text
    await world.photo()
    assert world.waha.sent == []


# ---------------------------------------------------------------------------
# The connection
# ---------------------------------------------------------------------------


async def test_linking_a_group_resolves_its_whatsapp_id(world: World) -> None:
    groups = (await world.campus.get(f"{API}/whatsapp/groups")).json()
    assert groups[0]["chat_id"] == "SectionAaaaaaaaaaaaaaaa@g.us"
    status = await world.campus.get(f"{API}/whatsapp/connection")
    assert status.status_code == 200, status.text
    assert status.json() | {"phone": None} == {
        "backend": "waha",
        "configured": True,
        "status": "WORKING",
        "phone": None,
        "push_name": "School",
        "unresolved_groups": 0,
    }


async def test_connecting_creates_the_campus_session_and_shows_its_qr(world: World) -> None:
    world.waha.session_status = "MISSING"
    started = await world.campus.post(f"{API}/whatsapp/connection")
    assert started.status_code == 200, started.text
    assert started.json()["status"] == "STARTING"
    [created] = world.waha.sessions_created
    assert created["name"] == session_name(UUID(world.tenant.school_id))
    hook = created["config"]["webhooks"][0]
    assert hook["hmac"] == {"key": SECRET}
    assert created["config"]["metadata"]["school_id"] == world.tenant.school_id

    world.waha.session_status = "SCAN_QR_CODE"
    qr = await world.campus.get(f"{API}/whatsapp/connection/qr")
    assert qr.status_code == 200, qr.text
    assert qr.json() == {"mimetype": "image/png", "data": "UVI="}
