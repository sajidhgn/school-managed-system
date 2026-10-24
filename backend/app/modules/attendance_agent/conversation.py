"""The attendance agent's WhatsApp conversation with a teacher.

THE CONVERSATION
    teacher  Nursery-A absent 12, 13, 15
    agent    📋 Attendance - Nursery-A ... Absent (3): 12 - Ali Khan, 13 - Sara
             Ahmed, 15 - Bilal Raza. Everyone else present (27 of 30).
             Reply OK to submit.
    teacher  13 was present actually
    agent    📋 Attendance - Nursery-A ... Absent (2) ...
    teacher  ok
    agent    ✅ Attendance submitted for Nursery-A: 28 present, 2 absent.

    When the message names no class and the teacher has several, the agent lists
    them and asks for a number. A new register replaces an unconfirmed one; one
    nobody answers lapses after `DIARY_DRAFT_TTL_MINUTES`.

HOW IT GETS THE MESSAGE
    The school's number has one webhook, received by the diary agent
    (`diary_agent/conversation.py`), which identifies the teacher and then offers
    every TEXT message here first. `handle` returns True when the message was about
    attendance, and False to let the diary agent carry on.

    A message is about attendance when it LOOKS like a register (a status word and
    roll numbers -- `parser.looks_like_attendance`), or when the teacher has a
    register waiting for an answer that is newer than any diary waiting for one.
    So "ok" confirms whichever of the two the teacher was shown last.

WHAT DECIDES -- CODE, NOT THE MODEL
    * the sender needs `attendance:mark`;
    * the class must be one they may mark (`markable_sections`), and the model's
      class is checked against that list again before use;
    * roll numbers are matched to children here, against the class roster, and
      the teacher confirms the NAMES before anything is written;
    * the OK makes the web register's own calls -- open, mark, submit -- so the
      teaching scope, the roster and "submitted needs `attendance:amend`" all
      still hold. WhatsApp is never a way around the register's rules.

TRANSACTIONS
    The model call takes seconds, so it happens BETWEEN short transactions, never
    inside one. The draft row carries the state across them, and is re-locked and
    re-checked each time (a second OK finds it already SUBMITTED).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.whatsapp.replies import (
    CANCEL_WORDS,
    CLASS_COMMAND_RE,
    CONFIRM_WORDS,
    norm_label,
    reply_word,
)
from app.core.config import Settings
from app.core.context import get_organization_id, get_school_id
from app.core.exceptions import AppError, ConflictError, ValidationError
from app.core.logging import get_logger
from app.db.session import session_scope
from app.modules.academics.teaching_scope import assigned_teacher
from app.modules.attendance.models import (
    WHOLE_DAY_PERIOD,
    AttendanceSessionStatus,
    AttendanceStatus,
)
from app.modules.attendance.repository import AttendanceSessionRepository
from app.modules.attendance.schemas import (
    AttendanceEntryInput,
    AttendanceMarkRequest,
    AttendanceSessionDetail,
    AttendanceSessionOpen,
)
from app.modules.attendance.service import AttendanceService
from app.modules.attendance_agent.agent import (
    AttendanceAgent,
    AttendanceAgentError,
    AttendanceMark,
    AttendanceReading,
    ReadingContext,
)
from app.modules.attendance_agent.models import (
    AttendanceChatDraft,
    AttendanceChatStatus,
)
from app.modules.attendance_agent.parser import (
    looks_like_attendance,
    parse_attendance,
    roll_key,
)
from app.modules.attendance_agent.repository import (
    AttendanceChatDraftRepository,
    markable_sections,
)
from app.modules.students.service import EnrollmentService

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, types only
    from app.modules.diary_agent.conversation import InboundMessage

logger = get_logger(__name__)

MARK_PERMISSION = "attendance:mark"

EXAMPLE = "Nursery-A absent 12, 13, 15"
HELP_LINE = f"To mark attendance, send the class and roll numbers, e.g. *{EXAMPLE}*. ✅"

# How each exception is shown, in the order a register is read out.
_SHOWN: tuple[tuple[AttendanceStatus, str, str], ...] = (
    (AttendanceStatus.ABSENT, "❌", "Absent"),
    (AttendanceStatus.LATE, "⏰", "Late"),
    (AttendanceStatus.EXCUSED, "📝", "Leave"),
    (AttendanceStatus.HALF_DAY, "🌓", "Half day"),
)
_COUNTED_AS = {
    AttendanceStatus.PRESENT: "present",
    AttendanceStatus.ABSENT: "absent",
    AttendanceStatus.LATE: "late",
    AttendanceStatus.EXCUSED: "on leave",
    AttendanceStatus.HALF_DAY: "half day",
}

Reply = Callable[[str], Awaitable[None]]


def _day(value: date) -> str:
    return f"{value:%A}, {value:%d %b %Y}"


@dataclass(frozen=True, slots=True)
class Speaker:
    """The staff member the diary agent identified from the sender's phone."""

    user_id: UUID
    full_name: str
    permissions: frozenset[str]

    @property
    def bound_to(self) -> UUID | None:
        return assigned_teacher(self.user_id, self.permissions)

    @property
    def may_mark(self) -> bool:
        return MARK_PERMISSION in self.permissions


@dataclass(frozen=True, slots=True)
class _Target:
    """A section the teacher may mark, as plain values that outlive the transaction."""

    section_id: UUID
    label: str
    class_name: str


@dataclass(frozen=True, slots=True)
class _Pending:
    """The teacher's unconfirmed register, as read at the start of this message."""

    id: UUID
    status: AttendanceChatStatus
    section_id: UUID | None
    class_label: str | None
    reading: AttendanceReading
    request_text: str
    updated_at: datetime


class AttendanceChat:
    """Handles one teacher text message about attendance. Built per message."""

    def __init__(
        self,
        settings: Settings,
        *,
        agent_factory: Callable[[], AttendanceAgent],
        reply: Reply,
    ) -> None:
        self.settings = settings
        self.agent_factory = agent_factory
        self.reply = reply

    async def handle(
        self,
        event: InboundMessage,
        speaker: Speaker,
        *,
        reply_to: str,
        diary_open_at: datetime | None,
    ) -> bool:
        """True when the message was about attendance and has been answered."""
        text = event.body.strip()
        if not text:
            return False
        is_register = looks_like_attendance(text)
        if not speaker.may_mark:
            if not is_register or diary_open_at is not None:
                return False  # with a diary open, more likely a correction to it
            await self.reply(
                "Sorry, your account is not allowed to mark attendance. "
                "Please ask the school office."
            )
            return True

        since = datetime.now(UTC) - timedelta(minutes=self.settings.DIARY_DRAFT_TTL_MINUTES)
        async with self._scope() as session:
            drafts = AttendanceChatDraftRepository(session)
            if await drafts.by_inbound_id(event.message_id) is not None:
                return True  # the same webhook, delivered twice
            pending = self._pending(await drafts.open_for(speaker.user_id, since=since))
            targets = [
                _Target(t.section.id, t.label, t.school_class.name)
                for t in await markable_sections(session, event.school_id, speaker.bound_to)
            ]

        answering = (
            pending
            if pending is not None
            and (diary_open_at is None or pending.updated_at >= diary_open_at)
            else None
        )
        if not is_register and answering is None:
            return False
        if not targets:
            await self.reply(
                "You have no classes to mark attendance for. Please ask the school office "
                "to assign your class."
            )
            return True
        if answering is not None and not is_register:
            await self._answer(event, speaker, text, answering, targets)
            return True
        return await self._register(event, speaker, text, pending, targets, reply_to)

    # -- a register ---------------------------------------------------------

    async def _register(
        self,
        event: InboundMessage,
        speaker: Speaker,
        text: str,
        pending: _Pending | None,
        targets: list[_Target],
        reply_to: str,
    ) -> bool:
        """A message with a status word and roll numbers: read it and show it back."""
        reading = parse_attendance(text)
        if reading is None or (reading.class_label and self._named(reading, targets) is None):
            # Not the usual shape, or a class the parser cannot place ("nur a") --
            # the model reads it, with any register on screen as context.
            try:
                reading = await self.agent_factory().read_message(
                    text, self._context(targets, pending)
                )
            except AttendanceAgentError:
                await self.reply(
                    f"Sorry, I couldn't understand that. Please send it like: *{EXAMPLE}*"
                )
                return True
            if not reading.is_attendance:
                return False
        if not reading.marks and not reading.all_present:
            await self.reply(
                f"I couldn't find any roll numbers in that. Please send it like: *{EXAMPLE}*"
            )
            return True

        # A list that names no class, sent while a register is on screen, is a new
        # list for THAT class -- the record keeps both messages.
        follows = pending is not None and not reading.class_label and not reading.class_choice
        request = f"{pending.request_text}\n{text}" if follows and pending else text
        target = self._target_for(reading, targets, pending)

        async with self._scope() as session:
            drafts = AttendanceChatDraftRepository(session)
            await drafts.cancel_open(speaker.user_id, reason="Replaced by a newer message.")
            try:
                async with session.begin_nested():
                    draft = await drafts.create(
                        teacher_user_id=speaker.user_id,
                        reply_chat_id=reply_to,
                        inbound_message_id=event.message_id,
                        status=AttendanceChatStatus.NEEDS_CLASS,
                        request_text=request[:4000],
                        session_date=datetime.now(UTC).date(),
                        class_hint=(reading.class_label or "")[:120] or None,
                        marks=self._marks_json(reading),
                        organization_id=event.organization_id,
                        school_id=event.school_id,
                    )
            except IntegrityError:
                return True  # a concurrent delivery of the same message won
            if target is None:
                answer = self._ask_class(targets, reading.class_label)
            else:
                answer = await self._resolve(session, draft, reading, target)
        await self.reply(answer)
        return True

    # -- a reply to a register on screen ------------------------------------

    async def _answer(
        self,
        event: InboundMessage,
        speaker: Speaker,
        text: str,
        pending: _Pending,
        targets: list[_Target],
    ) -> None:
        word = reply_word(text)
        command = CLASS_COMMAND_RE.match(text)
        submit = False
        revise = False

        async with self._scope() as session:
            draft = await AttendanceChatDraftRepository(session).lock(pending.id)
            if draft is None or draft.status not in (
                AttendanceChatStatus.NEEDS_CLASS,
                AttendanceChatStatus.AWAITING_CONFIRMATION,
            ):
                return  # settled by a message that arrived just before this one
            answer: str | None = None
            if word in CANCEL_WORDS:
                draft.status = AttendanceChatStatus.CANCELLED
                draft.error = "Cancelled by the teacher."
                answer = "Cancelled. The attendance was not submitted."
            elif draft.status is AttendanceChatStatus.NEEDS_CLASS or command:
                target = self._pick(command.group(1) if command else text, targets)
                if target is None:
                    answer = self._ask_class(targets, None, again=True)
                else:
                    answer = await self._resolve(session, draft, pending.reading, target)
            elif word in CONFIRM_WORDS:
                submit = True
            else:
                revise = True

        if answer is not None:
            await self.reply(answer)
        if submit:
            await self._submit(pending.id, speaker)
        if revise:
            await self._revise(event, text, pending, targets)

    async def _revise(
        self, event: InboundMessage, text: str, pending: _Pending, targets: list[_Target]
    ) -> None:
        """A change in the teacher's words ("13 was present") -> the whole new list."""
        label = pending.class_label or "this class"
        try:
            reading = await self.agent_factory().read_message(text, self._context(targets, pending))
        except AttendanceAgentError:
            await self.reply(
                "Sorry, I couldn't apply that. Reply *OK* to submit, *CANCEL* to discard, "
                f"or send the whole list again, e.g. *{EXAMPLE}*."
            )
            return
        if not reading.is_attendance or not (reading.marks or reading.all_present):
            await self.reply(
                f"Reply *OK* to submit the attendance for *{label}*, or *CANCEL* to discard it."
            )
            return
        target = self._target_for(reading, targets, pending)
        async with self._scope() as session:
            draft = await AttendanceChatDraftRepository(session).lock(pending.id)
            if draft is None or draft.status is not AttendanceChatStatus.AWAITING_CONFIRMATION:
                return
            draft.request_text = f"{draft.request_text}\n{text}"[:4000]
            draft.marks = self._marks_json(reading)
            answer = (
                await self._resolve(session, draft, reading, target)
                if target is not None
                else self._ask_class(targets, reading.class_label)
            )
            if target is None:
                draft.status = AttendanceChatStatus.NEEDS_CLASS
        await self.reply(answer)

    # -- the OK -------------------------------------------------------------

    async def _submit(self, draft_id: UUID, speaker: Speaker) -> None:
        """Open, mark and submit the register exactly as previewed -- or none of it."""
        async with self._scope() as session:
            draft = await AttendanceChatDraftRepository(session).lock(draft_id)
            if draft is None or draft.status is not AttendanceChatStatus.AWAITING_CONFIRMATION:
                return  # a second OK, after the first submitted it
            label = draft.class_label or "the class"
            wanted = {
                UUID(student_id): AttendanceStatus(status)
                for student_id, status in (draft.resolved or {}).get("students", {}).items()
            }
            try:
                # A savepoint, so a refusal part-way (submitted meanwhile, roster
                # changed) leaves the register exactly as it was -- and the draft
                # can still record why.
                async with session.begin_nested():
                    final = await self._write_register(session, draft, wanted, speaker)
            except AppError as exc:
                draft.status = AttendanceChatStatus.FAILED
                draft.error = exc.message[:500]
                answer = f"⚠️ Not submitted: {exc.message}"
            else:
                draft.status = AttendanceChatStatus.SUBMITTED
                draft.attendance_session_id = final.id
                answer = (
                    f"✅ Attendance submitted for *{label}* ({_day(draft.session_date)}): "
                    f"{self._counts(final)}."
                )
                logger.info(
                    "attendance_agent_submitted",
                    session_id=str(final.id),
                    draft_id=str(draft.id),
                )
        await self.reply(answer)

    async def _write_register(
        self,
        session: AsyncSession,
        draft: AttendanceChatDraft,
        wanted: dict[UUID, AttendanceStatus],
        speaker: Speaker,
    ) -> AttendanceSessionDetail:
        if draft.section_id is None:
            raise ValidationError("That class no longer exists.")
        service = AttendanceService(session)
        register = await service.open_session(
            AttendanceSessionOpen(section_id=draft.section_id, session_date=draft.session_date),
            actor_id=speaker.user_id,
            may_amend=False,
            teacher_id=speaker.bound_to,
        )
        if register.status is AttendanceSessionStatus.SUBMITTED:
            raise ConflictError(self._already_submitted(draft.class_label, draft.session_date))
        on_register = {entry.student_id for entry in register.entries}
        if not wanted.keys() <= on_register:
            raise ValidationError(
                f"the student list of {draft.class_label} has changed. "
                "Please send the attendance again."
            )
        # The message is the WHOLE register: anyone not named is present, including
        # a line someone set differently on the web draft.
        changes: list[AttendanceEntryInput] = []
        for entry in register.entries:
            status = wanted.get(entry.student_id, AttendanceStatus.PRESENT)
            if entry.status != status:
                changes.append(AttendanceEntryInput(student_id=entry.student_id, status=status))
        if changes:
            await service.mark(
                register.id,
                AttendanceMarkRequest(entries=changes),
                actor_id=speaker.user_id,
                may_amend=False,
                teacher_id=speaker.bound_to,
            )
        return await service.submit(
            register.id, actor_id=speaker.user_id, may_amend=False, teacher_id=speaker.bound_to
        )

    # -- matching and showing -----------------------------------------------

    async def _resolve(
        self,
        session: AsyncSession,
        draft: AttendanceChatDraft,
        reading: AttendanceReading,
        target: _Target,
    ) -> str:
        """Match the roll numbers to the class's children; return what to show the teacher."""
        draft.section_id = target.section_id
        draft.class_label = target.label

        existing = await AttendanceSessionRepository(session).find_register(
            target.section_id, draft.session_date, WHOLE_DAY_PERIOD
        )
        if existing is not None and existing.status is AttendanceSessionStatus.SUBMITTED:
            draft.status = AttendanceChatStatus.FAILED
            draft.error = "The register was already submitted."
            return self._already_submitted(target.label, draft.session_date)

        roster = await EnrollmentService(session).roster(target.section_id)
        if not roster:
            draft.status = AttendanceChatStatus.FAILED
            draft.error = "No students in the class."
            return f"*{target.label}* has no students enrolled yet, so there is nothing to mark."

        by_roll = {roll_key(e.roll_number): e for e in roster if e.roll_number}
        statuses: dict[UUID, AttendanceStatus] = {}
        unknown: list[str] = []
        for mark in reading.marks:
            entry = by_roll.get(roll_key(mark.roll_number))
            if entry is None:
                unknown.append(mark.roll_number)
            elif mark.status is AttendanceStatus.PRESENT:
                statuses.pop(entry.student_id, None)
            else:
                statuses[entry.student_id] = mark.status

        if unknown and not statuses and not reading.all_present:
            # Every number missed. Submitting would mark the whole class present --
            # the opposite of what the teacher sent.
            draft.status = AttendanceChatStatus.FAILED
            draft.error = "No roll number matched the class."
            return (
                f"None of these roll numbers are in *{target.label}*: {', '.join(unknown)}. "
                "Please check them and send the attendance again."
            )

        draft.status = AttendanceChatStatus.AWAITING_CONFIRMATION
        draft.resolved = {
            "students": {str(sid): status.value for sid, status in statuses.items()},
            "unknown": unknown,
            "roster": len(roster),
        }

        lines = [f"📋 *Attendance - {target.label}*", f"🗓️ {_day(draft.session_date)}", ""]
        for status, icon, title in _SHOWN:
            named = [e for e in roster if statuses.get(e.student_id) is status]
            if named:
                lines.append(f"{icon} *{title} ({len(named)})*")
                lines.extend(f"{e.roll_number} - {e.full_name}" for e in named)
                lines.append("")
        if statuses:
            rest = len(roster) - len(statuses)
            lines.append(f"✅ Everyone else present ({rest} of {len(roster)})")
        else:
            lines.append(f"✅ All {len(roster)} students present")
        if unknown:
            numbers = ", ".join(unknown)
            lines += ["", f"⚠️ Not in {target.label}, so left out: roll {numbers}"]
        lines += [
            "",
            "Reply *OK* to submit.",
            'To change something, just tell me (e.g. "13 was present", "also 17 absent").',
            "Reply *CANCEL* to discard.",
        ]
        return "\n".join(lines)

    def _target_for(
        self, reading: AttendanceReading, targets: list[_Target], pending: _Pending | None
    ) -> _Target | None:
        """The section a reading is for, or None to ask.

        A class the teacher NAMED but that is not one of theirs is never swapped for
        their only class: "9-B absent 4" from 9-A's teacher must not mark 9-A's roll 4.
        """
        if reading.class_label or reading.class_choice:
            return self._named(reading, targets)
        if pending is not None and pending.section_id is not None:
            current = next((t for t in targets if t.section_id == pending.section_id), None)
            if current is not None:
                return current
        return targets[0] if len(targets) == 1 else None

    def _named(self, reading: AttendanceReading, targets: list[_Target]) -> _Target | None:
        by_choice = next((t for t in targets if t.label == reading.class_choice), None)
        return by_choice or self._pick(reading.class_label, targets)

    @staticmethod
    def _pick(text: str | None, targets: list[_Target]) -> _Target | None:
        """A number from the list, a section label, or a class with one section."""
        if not text:
            return None
        text = text.strip()
        if text.isdigit():
            index = int(text)
            return targets[index - 1] if 1 <= index <= len(targets) else None
        wanted = norm_label(text)
        if not wanted:
            return None
        for target in targets:
            if wanted == norm_label(target.label):
                return target
        # "Nursery absent 4" when the teacher marks exactly one Nursery section.
        same_class = [t for t in targets if norm_label(t.class_name) == wanted]
        return same_class[0] if len(same_class) == 1 else None

    @staticmethod
    def _ask_class(targets: list[_Target], hint: str | None, *, again: bool = False) -> str:
        if again:
            lead = "I couldn't match that to one of your classes."
        elif hint:
            lead = f'I couldn\'t match "{hint}" to one of your classes.'
        else:
            lead = "Which class is this attendance for?"
        options = "\n".join(f"{i}. {t.label}" for i, t in enumerate(targets, 1))
        return f"{lead} Reply with the number:\n{options}"

    @staticmethod
    def _already_submitted(label: str | None, day: date) -> str:
        return (
            f"*{label}* attendance for {_day(day)} is already submitted. "
            "To change it, please ask the principal."
        )

    @staticmethod
    def _counts(register: AttendanceSessionDetail) -> str:
        tally = dict.fromkeys(_COUNTED_AS, 0)
        for entry in register.entries:
            tally[entry.status] += 1
        parts = [f"{n} {_COUNTED_AS[s]}" for s, n in tally.items() if n]
        return ", ".join(parts) or "no students"

    @staticmethod
    def _marks_json(reading: AttendanceReading) -> dict[str, Any]:
        return {
            "marks": [m.model_dump(mode="json") for m in reading.marks],
            "all_present": reading.all_present,
        }

    @staticmethod
    def _pending(draft: AttendanceChatDraft | None) -> _Pending | None:
        if draft is None:
            return None
        marks = draft.marks or {}
        return _Pending(
            id=draft.id,
            status=draft.status,
            section_id=draft.section_id,
            class_label=draft.class_label,
            reading=AttendanceReading(
                is_attendance=True,
                class_label=draft.class_hint,
                class_choice=draft.class_label,
                all_present=bool(marks.get("all_present")),
                marks=[AttendanceMark.model_validate(m) for m in marks.get("marks", [])],
            ),
            request_text=draft.request_text,
            updated_at=draft.updated_at,
        )

    @staticmethod
    def _context(targets: list[_Target], pending: _Pending | None) -> ReadingContext:
        return ReadingContext(
            class_options=[t.label for t in targets],
            today=datetime.now(UTC).date(),
            current_class=pending.class_label if pending else None,
            current_marks=list(pending.reading.marks) if pending else [],
        )

    def _scope(self) -> AbstractAsyncContextManager[AsyncSession]:
        return session_scope(get_organization_id(), school_id=get_school_id())
