"""The attendance agent: a teacher sends "Grade 9-A absent 1, 3", the register is submitted.

Driven end to end through the signed WAHA webhook, with WAHA replaced by an
`httpx.MockTransport` and the model by a scripted fake -- the same harness as the
diary agent's tests. The failure modes worth a test:

  * SUBMITTING WITHOUT AN OK. Nothing reaches the register until the teacher has
    seen the NAMES the roll numbers matched and confirmed them.
  * MARKING A CLASS THAT IS NOT THEIRS. Neither the parser, the model nor the
    teacher's reply can reach a section outside their teaching scope -- and a
    class they named is never silently swapped for one they teach.
  * REWRITING A SUBMITTED REGISTER. WhatsApp is not a way around
    `attendance:amend`, even when the web submit lands between preview and OK.
  * "EVERYONE PRESENT" BY ACCIDENT. A list whose numbers all miss is refused, not
    submitted as a full class.
  * THE MODEL SEEING A CHILD. It gets roll numbers and class labels, never names.
  * "OK" CONFIRMING THE WRONG THING. With a diary and a register both on screen,
    OK goes to the one shown last.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import pytest

from app.common.email.sender import EmailMessage
from app.common.whatsapp.waha import WahaClient
from app.core.config import Settings
from app.modules.attendance.models import AttendanceStatus
from app.modules.attendance_agent.agent import (
    AttendanceAgentError,
    AttendanceMark,
    AttendanceReading,
    ReadingContext,
)
from app.modules.whatsapp.router import (
    get_attendance_agent_factory,
    get_diary_agent_factory,
    get_waha_client,
)
from tests.integration.conftest import API, Tenant
from tests.integration.staff import _subject
from tests.integration.test_academic_foundation import build_campus
from tests.integration.test_diary_agent import (
    INVITE_A,
    SECRET,
    TEACHER_CHAT,
    TEACHER_PHONE,
    FakeAgent,
    FakeWaha,
    World,
    add_member,
    reading,
)

pytestmark = pytest.mark.asyncio


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


@dataclass
class FakeReader:
    """The model, scripted. With no `reading` set it behaves as unreachable."""

    reading: AttendanceReading | None = None
    texts: list[str] = field(default_factory=list)
    contexts: list[ReadingContext] = field(default_factory=list)

    async def read_message(self, text: str, context: ReadingContext) -> AttendanceReading:
        self.texts.append(text)
        self.contexts.append(context)
        if self.reading is None:
            raise AttendanceAgentError("The attendance reader is not responding.")
        return self.reading


def model_says(*marks: tuple[str, AttendanceStatus], **overrides: Any) -> AttendanceReading:
    values: dict[str, Any] = {
        "is_attendance": True,
        "class_label": None,
        "class_choice": None,
        "all_present": False,
        "marks": [AttendanceMark(roll_number=r, status=s) for r, s in marks],
        **overrides,
    }
    return AttendanceReading(**values)


@dataclass
class School:
    world: World
    reader: FakeReader
    roster: list[dict[str, Any]]
    """Grade 9-A's three students in roll order: `roll_number`, `full_name`, `student_id`."""

    @property
    def roll(self) -> list[str]:
        return [str(s["roll_number"]) for s in self.roster]

    def line(self, index: int) -> str:
        """How the preview names a student: "1 - Student1 Test"."""
        student = self.roster[index]
        return f"{student['roll_number']} - {student['full_name']}"

    async def say(self, body: str, message_id: str, sender: str = TEACHER_CHAT) -> str:
        await self.world.text(body, message_id, sender=sender)
        replies = self.world.waha.replies_to(sender)
        return replies[-1] if replies else ""

    async def today(self, section_id: str | None = None) -> dict[str, Any]:
        """Today's row for a section on the principal's daily board."""
        campus = self.world.campus
        listed = await campus.get(f"{API}/attendance/today")
        assert listed.status_code == 200, listed.text
        wanted = section_id or campus.section_id
        return next(r for r in listed.json()["sections"] if r["section_id"] == wanted)

    async def statuses(self) -> dict[str, str]:
        row = await self.today()
        assert row["session_id"], "no register was opened"
        detail = await self.world.campus.get(f"{API}/attendance/{row['session_id']}")
        assert detail.status_code == 200, detail.text
        return {e["student_id"]: e["status"] for e in detail.json()["entries"]}

    def ids(self, *statuses: str) -> dict[str, str]:
        return {s["student_id"]: status for s, status in zip(self.roster, statuses, strict=True)}


@pytest.fixture
async def school(tenant: Tenant, mailbox: list[EmailMessage], db_settings: Settings) -> School:
    campus = await build_campus(tenant, mailbox, students=3)
    waha = FakeWaha()
    diary = FakeAgent(reading=reading("Grade 9-A"))
    reader = FakeReader()

    app = tenant.client._transport.app  # type: ignore[attr-defined]
    transport = httpx.MockTransport(waha.handler)
    app.dependency_overrides[get_waha_client] = lambda: WahaClient(db_settings, transport=transport)
    app.dependency_overrides[get_diary_agent_factory] = lambda: lambda: diary
    app.dependency_overrides[get_attendance_agent_factory] = lambda: lambda: reader

    world = World(tenant=tenant, campus=campus, waha=waha, agent=diary)
    world.teacher_id = await add_member(
        tenant, "ayesha@test.example", "Ayesha Khan", role_code="teacher", phone=TEACHER_PHONE
    )
    assigned = await campus.patch(
        f"{API}/classes/sections/{campus.section_id}", json={"class_teacher_id": world.teacher_id}
    )
    assert assigned.status_code == 200, assigned.text
    roster = await campus.get(f"{API}/classes/sections/{campus.section_id}/roster")
    assert roster.status_code == 200, roster.text
    assert all(s["roll_number"] for s in roster.json()), "every student needs a roll number"
    return School(world=world, reader=reader, roster=roster.json())


# ---------------------------------------------------------------------------
# The happy path
# ---------------------------------------------------------------------------


async def test_roll_numbers_are_shown_by_name_and_submitted_only_after_ok(
    school: School,
) -> None:
    r1, _, r3 = school.roll
    preview = await school.say(f"Grade 9-A absent {r1}, {r3}", "att-1")

    assert "📋 *Attendance - Grade 9-A*" in preview
    assert "❌ *Absent (2)*" in preview
    assert school.line(0) in preview and school.line(2) in preview
    assert school.line(1) not in preview
    assert "✅ Everyone else present (1 of 3)" in preview
    assert school.reader.texts == []  # the usual shape is read without the model
    assert (await school.today())["session_id"] is None  # NOTHING before the OK

    done = await school.say("OK", "att-ok")
    assert done.startswith("✅ Attendance submitted for *Grade 9-A*")
    assert done.endswith(": 1 present, 2 absent.")
    assert (await school.today())["status"] == "submitted"
    assert await school.statuses() == school.ids("absent", "present", "absent")

    # A second OK (double tap, redelivery) changes nothing and errors nowhere.
    again = await school.say("ok", "att-ok-again")
    assert "To mark attendance" in again  # nothing open: the help text
    assert await school.statuses() == school.ids("absent", "present", "absent")


async def test_every_status_reaches_the_register(school: School) -> None:
    r1, r2, r3 = school.roll
    preview = await school.say(f"Grade 9-A absent {r1} late {r2} leave {r3}", "att-1")
    assert "⏰ *Late (1)*" in preview and "📝 *Leave (1)*" in preview
    assert "Everyone else present (0 of 3)" in preview

    await school.say("haan", "att-ok")
    assert await school.statuses() == school.ids("absent", "late", "excused")


async def test_all_present(school: School) -> None:
    preview = await school.say("Grade 9-A all present", "att-1")
    assert "✅ All 3 students present" in preview
    await school.say("ok", "att-ok")
    assert await school.statuses() == school.ids("present", "present", "present")


# ---------------------------------------------------------------------------
# The model: only for what the parser will not read, and never told a name
# ---------------------------------------------------------------------------


async def test_a_free_form_message_is_read_by_the_model_without_names(school: School) -> None:
    _, r2, _ = school.roll
    school.reader.reading = model_says(
        (r2, AttendanceStatus.ABSENT), class_label="9a", class_choice="Grade 9-A"
    )
    message = f"9a: {r2} absent"  # status after the number: not the parser's shape
    preview = await school.say(message, "att-1")

    assert school.reader.texts == [message]
    [context] = school.reader.contexts
    assert context.class_options == ["Grade 9-A"]
    assert context.current_marks == []
    assert all(s["full_name"] not in repr(context) for s in school.roster)
    assert school.line(1) in preview

    await school.say("ok", "att-ok")
    assert await school.statuses() == school.ids("present", "absent", "present")


async def test_a_change_applies_to_the_list_on_screen(school: School) -> None:
    r1, r2, r3 = school.roll
    await school.say(f"Grade 9-A absent {r1}, {r2}", "att-1")

    # A change without a status word ("remove 2") is a reply to the register...
    school.reader.reading = model_says((r1, AttendanceStatus.ABSENT))
    preview = await school.say(f"remove {r2}", "att-2")
    context = school.reader.contexts[-1]
    assert context.current_class == "Grade 9-A"
    assert [m.roll_number for m in context.current_marks] == [r1, r2]
    assert "❌ *Absent (1)*" in preview and school.line(1) not in preview

    # ...and one with a status word replaces it, for the same class.
    school.reader.reading = model_says((r1, AttendanceStatus.ABSENT), (r3, AttendanceStatus.LATE))
    preview = await school.say(f"also {r3} late", "att-3")
    assert "⏰ *Late (1)*" in preview

    await school.say("ok", "att-ok")
    assert await school.statuses() == school.ids("absent", "present", "late")


async def test_when_the_model_is_down_the_teacher_is_shown_the_usual_shape(
    school: School,
) -> None:
    reply = await school.say("9a: 2 absent", "att-1")
    assert "Please send it like: *Nursery-A absent 12, 13, 15*" in reply
    assert (await school.today())["session_id"] is None


# ---------------------------------------------------------------------------
# Which class -- decided in code, against the teacher's own classes
# ---------------------------------------------------------------------------


async def test_a_class_the_teacher_does_not_teach_is_never_marked(school: School) -> None:
    campus = school.world.campus
    other = await campus.post(f"{API}/classes/{campus.class_id}/sections", json={"name": "B"})
    assert other.status_code == 201, other.text
    # A model that ignores its instructions and names the other section anyway.
    school.reader.reading = model_says(
        ("1", AttendanceStatus.ABSENT), class_label="Grade 9-B", class_choice="Grade 9-B"
    )

    question = await school.say("Grade 9-B absent 1", "att-1")
    assert school.reader.contexts[0].class_options == ["Grade 9-A"]
    assert 'couldn\'t match "Grade 9-B"' in question
    assert "1. Grade 9-A" in question and "Grade 9-B\n" not in question
    assert (await school.today(other.json()["id"]))["session_id"] is None
    assert (await school.today())["session_id"] is None  # nor swapped for 9-A

    await school.say("ok", "att-ok")  # OK is not an answer to "which class?"
    assert (await school.today())["session_id"] is None


async def test_a_teacher_with_two_sections_is_asked_which(school: School) -> None:
    campus = school.world.campus
    other = await campus.post(f"{API}/classes/{campus.class_id}/sections", json={"name": "B"})
    assert other.status_code == 201, other.text
    await _subject(campus, "MATH", school.world.teacher_id)  # now every Grade 9 section

    question = await school.say(f"absent {school.roll[0]}", "att-1")
    assert "Which class is this attendance for?" in question
    assert "1. Grade 9-A" in question and "2. Grade 9-B" in question

    preview = await school.say("1", "att-2")
    assert "*Attendance - Grade 9-A*" in preview and school.line(0) in preview
    await school.say("ok", "att-ok")
    assert await school.statuses() == school.ids("absent", "present", "present")


# ---------------------------------------------------------------------------
# The register's own rules still hold
# ---------------------------------------------------------------------------


async def _web_submit(school: School) -> str:
    campus = school.world.campus
    opened = await campus.post(f"{API}/attendance", json={"section_id": campus.section_id})
    assert opened.status_code in (200, 201), opened.text
    submitted = await campus.post(f"{API}/attendance/{opened.json()['id']}/submit")
    assert submitted.status_code == 200, submitted.text
    return str(opened.json()["id"])


async def test_a_submitted_register_is_not_rewritten(school: School) -> None:
    await _web_submit(school)
    reply = await school.say(f"Grade 9-A absent {school.roll[0]}", "att-1")
    assert "already submitted" in reply and "ask the principal" in reply
    assert await school.statuses() == school.ids("present", "present", "present")


async def test_a_web_submit_between_preview_and_ok_wins(school: School) -> None:
    await school.say(f"Grade 9-A absent {school.roll[0]}", "att-1")
    await _web_submit(school)

    reply = await school.say("ok", "att-ok")
    assert reply.startswith("⚠️ Not submitted:") and "already submitted" in reply
    assert await school.statuses() == school.ids("present", "present", "present")


async def test_unknown_roll_numbers_are_flagged_and_none_matching_is_refused(
    school: School,
) -> None:
    preview = await school.say(f"Grade 9-A absent {school.roll[0]}, 45", "att-1")
    assert "⚠️ Not in Grade 9-A, so left out: roll 45" in preview

    refused = await school.say("Grade 9-A absent 45, 46", "att-2")
    assert refused.startswith("None of these roll numbers are in *Grade 9-A*: 45, 46")
    await school.say("ok", "att-ok")
    # NOT "everyone present": nothing was submitted at all.
    assert (await school.today())["session_id"] is None


async def test_cancel_and_a_redelivered_message(school: School) -> None:
    await school.say(f"Grade 9-A absent {school.roll[0]}", "att-1")
    await school.say(f"Grade 9-A absent {school.roll[0]}", "att-1")  # WAHA retrying
    previews = [t for t in school.world.waha.replies_to(TEACHER_CHAT) if "📋" in t]
    assert len(previews) == 1

    assert await school.say("cancel", "att-cancel") == (
        "Cancelled. The attendance was not submitted."
    )
    await school.say("ok", "att-ok")
    assert (await school.today())["session_id"] is None


# ---------------------------------------------------------------------------
# Who may speak
# ---------------------------------------------------------------------------


async def test_an_unknown_number_gets_no_reply_at_all(school: School) -> None:
    await school.say("Grade 9-A absent 1", "att-1", sender="923339999999@c.us")
    assert school.world.waha.sent == []


async def test_staff_without_the_permission_is_told_so(school: School) -> None:
    await add_member(
        school.world.tenant,
        "acc@test.example",
        "Accountant",
        role_code="accountant",
        phone="03011112222",
    )
    reply = await school.say("Grade 9-A absent 1", "att-1", sender="923011112222@c.us")
    assert "not allowed to mark attendance" in reply
    assert (await school.today())["session_id"] is None


# ---------------------------------------------------------------------------
# One number, two agents
# ---------------------------------------------------------------------------


async def test_ok_confirms_whichever_was_shown_last(school: School) -> None:
    world = school.world
    await world.link_group("9-A Parents", INVITE_A, section_id=world.campus.section_id)

    await school.say(f"Grade 9-A absent {school.roll[0]}", "att-1")
    await world.photo()  # the diary preview is now the newer one
    await school.say("ok", "ok-1")
    [diary] = await world.outbox()
    assert diary["kind"] == "diary"
    assert (await school.today())["session_id"] is None

    # The register is still waiting, and is now the newest thing on screen.
    await school.say("ok", "ok-2")
    assert await school.statuses() == school.ids("absent", "present", "present")


async def test_the_help_text_offers_both(school: School) -> None:
    reply = await school.say("hello", "hi-1")
    assert "Send me a photo" in reply
    assert "*Nursery-A absent 12, 13, 15*" in reply
