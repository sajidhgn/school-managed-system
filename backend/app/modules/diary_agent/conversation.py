"""The diary agent's WhatsApp conversation with a teacher.

THE CONVERSATION
    teacher  [photo of today's diary page]
    agent    Got it -- reading the diary page...
    agent    Here is the diary for *Grade 5-B* ... Reply OK to post it.
    teacher  maths is ex 4.3 not 4.2
    agent    Here is the diary for *Grade 5-B* ... (corrected)
    teacher  ok
    agent    ✅ Posted to "5-B Parents".

    When the page does not say which class it is for (and the teacher has more
    than one), the agent lists the teacher's classes and asks for a number. A new
    photo replaces any unfinished one; a draft nobody answers lapses after
    `DIARY_DRAFT_TTL_MINUTES`.

WHO THE AGENT ANSWERS
    Only staff of THIS campus whose phone number on their account matches the
    sender. The school's number also receives parents' messages, and the agent
    must stay silent to every one of them -- an unknown number gets no reply at
    all, not even "I don't know you".

WHERE A DIARY MAY GO -- DECIDED HERE, NOT BY THE MODEL
    * the sender needs `whatsapp:diary`;
    * the group must be one of their TARGETS: an active class group in their
      teaching scope (every group, with `class:view_all`);
    * nothing is queued until the teacher answers OK to the exact text shown.
    The model proposes a class from that target list and the proposal is checked
    against it again before use.

TRANSACTIONS
    Model calls and WhatsApp calls take seconds, so they happen BETWEEN short
    transactions, never inside one. The draft row carries the state across them,
    and is re-locked and re-checked each time (a second OK finds it already POSTED).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditAction, record_audit
from app.common.whatsapp.sender import WahaSender, WhatsAppSender, build_whatsapp_sender
from app.common.whatsapp.waha import WahaClient, WahaError, session_name
from app.core.config import Settings
from app.core.context import (
    get_organization_id,
    get_school_id,
    set_organization_id,
    set_school_id,
)
from app.core.logging import get_logger
from app.db.session import session_scope
from app.modules.academics.teaching_scope import assigned_teacher
from app.modules.diary_agent.agent import (
    DiaryAgent,
    DiaryAgentError,
    DiaryLine,
    DiaryReading,
    ReadingContext,
)
from app.modules.diary_agent.models import (
    DEFAULT_DIARY_TEMPLATE,
    DEFAULT_ENTRY_TEMPLATE,
    OPEN_STATUSES,
    DiaryDraft,
    DiaryDraftStatus,
)
from app.modules.diary_agent.repository import (
    DiaryAgentSettingsRepository,
    DiaryDraftRepository,
    DiaryLookupRepository,
    DiaryTarget,
)
from app.modules.diary_agent.service import render_diary
from app.modules.tenancy.models import School
from app.modules.whatsapp.jobs import dispatch_outbox
from app.modules.whatsapp.service import WhatsAppService

logger = get_logger(__name__)

POST_PERMISSION = "whatsapp:diary"

_CONFIRM = frozenset(
    {
        "ok", "okay", "k", "yes", "y", "post", "send", "post it", "send it", "ok post",
        "yes post", "done", "haan", "han", "ji", "jee", "theek hai", "thik hai",
        "👍", "✅", "اوکے", "جی", "ہاں",
    }
)  # fmt: skip
_CANCEL = frozenset(
    {"cancel", "no", "n", "stop", "discard", "delete", "nahi", "nahin", "❌", "نہیں"}
)
_CLASS_COMMAND_RE = re.compile(r"^(?:class|grade|section)\b[\s:#-]*(.+)$", re.IGNORECASE)
_LABEL_NOISE_RE = re.compile(r"\b(?:class|grade|section)\b|[^0-9a-z؀-ۿ]+")

# A model read takes seconds; a draft still READING after this was abandoned.
_READING_STALE_MINUTES = 5

HELP_TEXT = (
    "Hi! Send me a photo of today's diary page and I'll write it up and post it to "
    "your class WhatsApp group. 📸"
)


# ---------------------------------------------------------------------------
# The webhook, parsed
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InboundMessage:
    """One incoming WhatsApp message for one campus, from a verified webhook."""

    organization_id: UUID
    school_id: UUID
    session: str
    message_id: str
    chat_id: str
    """The sender: `923001234567@c.us`, or `...@lid` behind WhatsApp's privacy id."""
    body: str
    has_media: bool
    media_url: str | None
    media_mimetype: str | None
    from_me: bool


def parse_webhook(raw: bytes) -> InboundMessage | None:
    """A WAHA `message` event -> `InboundMessage`; None for anything else.

    The tenant comes from the session's `metadata`, which WAHA signs along with
    the rest of the body -- and the session name must be that campus's, so a
    metadata/session mismatch (a hand-edited session) is dropped, not trusted.
    """
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict) or data.get("event") != "message":
        return None
    meta = data.get("metadata") or {}
    payload = data.get("payload") or {}
    try:
        organization_id = UUID(str(meta["organization_id"]))
        school_id = UUID(str(meta["school_id"]))
    except (KeyError, ValueError, TypeError):
        return None
    session = str(data.get("session") or "")
    if session != session_name(school_id):
        return None
    chat_id = str(payload.get("from") or "")
    message_id = str(payload.get("id") or "")
    if not chat_id or not message_id:
        return None
    media = payload.get("media") or {}
    return InboundMessage(
        organization_id=organization_id,
        school_id=school_id,
        session=session,
        message_id=message_id[:160],
        chat_id=chat_id,
        body=str(payload.get("body") or ""),
        has_media=bool(payload.get("hasMedia")),
        media_url=media.get("url"),
        media_mimetype=media.get("mimetype"),
        from_me=bool(payload.get("fromMe")),
    )


def normalize_phone(raw: str, default_country_code: str) -> str | None:
    """Any way a phone is typed -> international digits (`923001234567`).

    `+92 300 1234567`, `0092...`, `0300-1234567` and `3001234567` are one number.
    """
    digits = re.sub(r"\D", "", raw)
    if not digits:
        return None
    if raw.strip().startswith("+"):
        return digits
    if digits.startswith("00"):
        return digits[2:]
    if digits.startswith("0"):
        return default_country_code + digits[1:]
    if len(digits) <= 10:
        return default_country_code + digits
    return digits


def _norm_label(text: str) -> str:
    return _LABEL_NOISE_RE.sub("", text.lower())


def _word(text: str) -> str:
    return text.strip().lower().strip(" .!?،۔")  # noqa: RUF001 -- Urdu punctuation


# ---------------------------------------------------------------------------
# The conversation
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Teacher:
    user_id: UUID
    full_name: str
    permissions: frozenset[str]

    @property
    def bound_to(self) -> UUID | None:
        return assigned_teacher(self.user_id, self.permissions)


@dataclass(frozen=True, slots=True)
class _Format:
    template: str
    entry_template: str
    instructions: str | None
    school_name: str


class DiaryConversation:
    """Handles one inbound message end to end. Built per webhook."""

    def __init__(
        self,
        settings: Settings,
        *,
        waha: WahaClient,
        agent_factory: Callable[[], DiaryAgent],
    ) -> None:
        self.settings = settings
        self.waha = waha
        self.agent_factory = agent_factory

    async def handle(self, event: InboundMessage) -> None:
        """Never raises: a background task's exception would only reach the log."""
        if event.from_me:
            return
        previous_org, previous_school = get_organization_id(), get_school_id()
        set_organization_id(event.organization_id)
        set_school_id(event.school_id)
        try:
            await self._handle(event)
        except Exception:
            logger.exception("diary_agent_failed", message_id=event.message_id)
        finally:
            set_school_id(previous_school)
            set_organization_id(previous_org)

    async def _handle(self, event: InboundMessage) -> None:
        number = await self._sender_number(event)
        if number is None:
            return
        async with self._scope() as session:
            fmt = await self._format(session)
            teacher = await self._identify(session, event.school_id, number)
        if fmt is None:
            return  # switched off for this campus
        if teacher is None:
            logger.info("diary_agent_ignored_sender", school_id=str(event.school_id))
            return
        reply_to = f"{number}@c.us"
        if POST_PERMISSION not in teacher.permissions:
            await self._reply(
                event,
                reply_to,
                "Sorry, your account is not allowed to post the class diary. "
                "Please ask the school office.",
            )
            return
        if event.has_media:
            await self._photo(event, teacher, reply_to, fmt)
        else:
            await self._text(event, teacher, reply_to, fmt)

    # -- a photo ----------------------------------------------------------

    async def _photo(
        self, event: InboundMessage, teacher: _Teacher, reply_to: str, fmt: _Format
    ) -> None:
        mimetype = event.media_mimetype or ""
        if not mimetype.startswith("image/"):
            await self._reply(
                event, reply_to, "Please send the diary page as a photo (not a file or video)."
            )
            return
        if not event.media_url:
            await self._reply(event, reply_to, "I couldn't open that photo. Please send it again.")
            return

        async with self._scope() as session:
            drafts = DiaryDraftRepository(session)
            if await drafts.by_inbound_id(event.message_id) is not None:
                return  # the same webhook, delivered twice
            lookup = DiaryLookupRepository(session)
            targets = await lookup.targets(event.school_id, teacher.bound_to)
            started = (
                await self._start_draft(session, event, teacher, reply_to) if targets else None
            )
            context = await self._context(lookup, targets, fmt)
        if not targets:
            await self._reply(
                event,
                reply_to,
                "There is no class WhatsApp group linked for your classes yet. "
                "Please ask the school office to link it.",
            )
            return
        if started is None:
            return  # a concurrent delivery of the same photo won
        draft_id = started

        await self._reply(event, reply_to, "Got it - reading the diary page... 📖")
        try:
            image = await self.waha.download_media(
                event.media_url, max_bytes=self.settings.DIARY_MAX_IMAGE_MB * 1024 * 1024
            )
            reading = await self.agent_factory().read_page(image, mimetype, context)
        except (WahaError, DiaryAgentError) as exc:
            await self._fail(draft_id, str(exc))
            await self._reply(
                event,
                reply_to,
                f"Sorry, I couldn't read that photo right now ({exc}). Please try again "
                "in a few minutes.",
            )
            return
        await self._apply(event, draft_id, reading, teacher, reply_to, fmt)

    # -- a text reply -----------------------------------------------------

    async def _text(
        self, event: InboundMessage, teacher: _Teacher, reply_to: str, fmt: _Format
    ) -> None:
        text = event.body.strip()
        word = _word(text)
        revise: tuple[UUID, DiaryReading, ReadingContext] | None = None
        post: UUID | None = None

        async with self._scope() as session:
            drafts = DiaryDraftRepository(session)
            since = datetime.now(UTC) - timedelta(minutes=self.settings.DIARY_DRAFT_TTL_MINUTES)
            draft = await drafts.open_for(teacher.user_id, since=since)
            if draft is None:
                answer: str | None = HELP_TEXT
            elif draft.status is DiaryDraftStatus.READING and draft.updated_at >= datetime.now(
                UTC
            ) - timedelta(minutes=_READING_STALE_MINUTES):
                answer = "Still reading your last photo - one moment."
            elif draft.status is DiaryDraftStatus.READING:
                # The read never finished (a restart mid-call): say so, don't hang.
                draft.status = DiaryDraftStatus.FAILED
                draft.error = "The photo was never read."
                answer = "Sorry, I lost that photo. Please send it again."
            elif word in _CANCEL:
                draft.status = DiaryDraftStatus.CANCELLED
                draft.error = "Cancelled by the teacher."
                answer = "Cancelled. Nothing was posted."
            else:
                lookup = DiaryLookupRepository(session)
                targets = await lookup.targets(event.school_id, teacher.bound_to)
                command = _CLASS_COMMAND_RE.match(text)
                if draft.status is DiaryDraftStatus.NEEDS_CLASS or command or text.isdigit():
                    target = self._pick(command.group(1) if command else text, targets)
                    if target is None:
                        answer = self._ask_class(targets, draft.class_hint, again=True)
                    else:
                        self._set_target(draft, target, teacher, fmt)
                        answer = self._preview(draft, target)
                elif word in _CONFIRM:
                    post = draft.id
                    answer = None
                else:
                    current = self._reading_of(draft, targets)
                    revise = (draft.id, current, await self._context(lookup, targets, fmt))
                    answer = None

        if answer is not None:
            await self._reply(event, reply_to, answer)
        if post is not None:
            await self._post(event, post, teacher, reply_to)
        if revise is not None:
            draft_id, current, context = revise
            try:
                reading = await self.agent_factory().revise(current, text, context)
            except DiaryAgentError as exc:
                await self._reply(event, reply_to, f"Sorry, I couldn't apply that ({exc}).")
                return
            await self._apply(event, draft_id, reading, teacher, reply_to, fmt)

    # -- state changes ----------------------------------------------------

    async def _apply(
        self,
        event: InboundMessage,
        draft_id: UUID,
        reading: DiaryReading,
        teacher: _Teacher,
        reply_to: str,
        fmt: _Format,
    ) -> None:
        """Store a reading (first or corrected) and show the teacher the result."""
        async with self._scope() as session:
            drafts = DiaryDraftRepository(session)
            draft = await drafts.lock(draft_id)
            if draft is None or draft.status not in OPEN_STATUSES:
                return  # cancelled or replaced while the model was working
            # A correction is judged on its entries alone: a confused "not a diary"
            # from the revise call must not throw away a page already read.
            if not reading.entries or (not reading.is_diary and draft.content is None):
                draft.status = DiaryDraftStatus.FAILED
                draft.error = "Not a diary page."
                answer = (
                    "That doesn't look like a diary page. Please send a clear photo of "
                    "the whole page."
                )
            else:
                targets = await DiaryLookupRepository(session).targets(
                    event.school_id, teacher.bound_to
                )
                draft.content = {
                    "entries": [line.model_dump() for line in reading.entries],
                    "notes": reading.notes,
                }
                draft.class_hint = (reading.class_label or "")[:120] or draft.class_hint
                draft.diary_date = reading.parsed_date() or draft.diary_date or date.today()
                target = (
                    self._pick(reading.class_choice, targets)
                    or self._current(draft, targets)
                    or (targets[0] if len(targets) == 1 else None)
                )
                if target is None:
                    draft.status = DiaryDraftStatus.NEEDS_CLASS
                    answer = self._ask_class(targets, draft.class_hint)
                else:
                    self._set_target(draft, target, teacher, fmt)
                    answer = self._preview(draft, target)
        await self._reply(event, reply_to, answer)

    async def _post(
        self, event: InboundMessage, draft_id: UUID, teacher: _Teacher, reply_to: str
    ) -> None:
        """The teacher said OK: queue exactly the text they saw, then send it."""
        message_id: UUID | None = None
        async with self._scope() as session:
            draft = await DiaryDraftRepository(session).lock(draft_id)
            if draft is None or draft.status is not DiaryDraftStatus.AWAITING_CONFIRMATION:
                return  # a second OK, after the first posted it
            targets = await DiaryLookupRepository(session).targets(
                event.school_id, teacher.bound_to
            )
            target = self._current(draft, targets)
            if target is None or not draft.body:
                # Group unlinked, paused, or the teacher's assignment changed since.
                draft.status = DiaryDraftStatus.NEEDS_CLASS
                answer = self._ask_class(targets, draft.class_hint)
            else:
                message = await WhatsAppService(session, self.waha).queue_diary(
                    target.group, draft.body, actor_id=teacher.user_id
                )
                draft.status = DiaryDraftStatus.POSTED
                draft.message_id = message.id
                message_id = message.id
                await record_audit(
                    session,
                    organization_id=event.organization_id,
                    school_id=event.school_id,
                    actor_user_id=teacher.user_id,
                    action=AuditAction.DIARY_POSTED,
                    entity_type="diary_draft",
                    entity_id=draft.id,
                    after={"group_id": str(target.group.id), "class": draft.class_label},
                )
                answer = target.group.name
        if message_id is None:
            await self._reply(event, reply_to, answer)
            return

        sender = self._sender()
        if sender is None:
            await self._reply(event, reply_to, f'✅ Queued for "{answer}". It will go out shortly.')
            return
        sent, _ = await dispatch_outbox(event.organization_id, sender, limit=1, only=[message_id])
        if sent:
            await self._reply(event, reply_to, f'✅ Posted to "{answer}".')
        else:
            await self._reply(
                event,
                reply_to,
                f'⚠️ Saved, but WhatsApp did not accept it for "{answer}" yet. The school '
                "office can retry it from the WhatsApp page.",
            )

    async def _start_draft(
        self, session: AsyncSession, event: InboundMessage, teacher: _Teacher, reply_to: str
    ) -> UUID | None:
        """Open a READING draft for the photo; a newer photo replaces an open one."""
        drafts = DiaryDraftRepository(session)
        await drafts.cancel_open(teacher.user_id, reason="Replaced by a newer photo.")
        try:
            async with session.begin_nested():
                draft = await drafts.create(
                    teacher_user_id=teacher.user_id,
                    reply_chat_id=reply_to,
                    inbound_message_id=event.message_id,
                    status=DiaryDraftStatus.READING,
                    organization_id=event.organization_id,
                    school_id=event.school_id,
                )
        except IntegrityError:
            return None
        return draft.id

    async def _fail(self, draft_id: UUID, error: str) -> None:
        async with self._scope() as session:
            draft = await DiaryDraftRepository(session).lock(draft_id)
            if draft is not None and draft.status in OPEN_STATUSES:
                draft.status = DiaryDraftStatus.FAILED
                draft.error = error[:500]

    # -- helpers ----------------------------------------------------------

    def _set_target(
        self, draft: DiaryDraft, target: DiaryTarget, teacher: _Teacher, fmt: _Format
    ) -> None:
        content = draft.content or {}
        draft.group_id = target.group.id
        draft.class_label = target.label
        draft.status = DiaryDraftStatus.AWAITING_CONFIRMATION
        draft.body = render_diary(
            fmt.template,
            fmt.entry_template,
            school=fmt.school_name,
            class_label=target.label,
            diary_date=draft.diary_date or date.today(),
            entries=[(e["subject"], e["homework"]) for e in content.get("entries", [])],
            notes=content.get("notes"),
            teacher=teacher.full_name,
        )

    @staticmethod
    def _preview(draft: DiaryDraft, target: DiaryTarget) -> str:
        return (
            f'Here is the diary for *{target.label}*, ready for "{target.group.name}":\n\n'
            f"{draft.body}\n\n"
            "Reply *OK* to post it.\n"
            'To change something, just tell me (e.g. "Maths: Exercise 4.3").\n'
            "Wrong class? Reply *CLASS* and the class, e.g. *CLASS 5-A*. "
            "Reply *CANCEL* to discard."
        )

    @staticmethod
    def _ask_class(targets: list[DiaryTarget], hint: str | None, *, again: bool = False) -> str:
        if not targets:
            return (
                "There is no class WhatsApp group linked for your classes anymore. "
                "Please ask the school office."
            )
        lead = (
            "I couldn't match that to one of your classes."
            if again
            else "I read the diary"
            + (f' (it says "{hint}")' if hint else "")
            + " but couldn't tell which class it is for."
        )
        options = "\n".join(f"{i}. {t.label} ({t.group.name})" for i, t in enumerate(targets, 1))
        return f"{lead} Reply with the number:\n{options}"

    @staticmethod
    def _pick(text: str | None, targets: list[DiaryTarget]) -> DiaryTarget | None:
        """A number from the list, a class label, or a group name -> that target."""
        if not text:
            return None
        text = text.strip()
        if text.isdigit():
            index = int(text)
            return targets[index - 1] if 1 <= index <= len(targets) else None
        wanted = _norm_label(text)
        if not wanted:
            return None
        for target in targets:
            if wanted in (_norm_label(target.label), _norm_label(target.group.name)):
                return target
        return None

    @staticmethod
    def _current(draft: DiaryDraft, targets: list[DiaryTarget]) -> DiaryTarget | None:
        return next((t for t in targets if t.group.id == draft.group_id), None)

    def _reading_of(self, draft: DiaryDraft, targets: list[DiaryTarget]) -> DiaryReading:
        content = draft.content or {}
        current = self._current(draft, targets)
        return DiaryReading(
            is_diary=True,
            class_label=draft.class_hint,
            class_choice=current.label if current else None,
            diary_date=draft.diary_date.isoformat() if draft.diary_date else None,
            entries=[DiaryLine(**e) for e in content.get("entries", [])],
            notes=content.get("notes"),
        )

    async def _context(
        self, lookup: DiaryLookupRepository, targets: list[DiaryTarget], fmt: _Format
    ) -> ReadingContext:
        return ReadingContext(
            school_name=fmt.school_name,
            class_options=[t.label for t in targets],
            subjects=await lookup.subject_names([t.school_class.id for t in targets]),
            instructions=fmt.instructions,
            today=date.today(),
        )

    async def _format(self, session: AsyncSession) -> _Format | None:
        row = await DiaryAgentSettingsRepository(session).for_campus()
        if row is not None and not row.enabled:
            return None
        school = await session.get(School, get_school_id())
        return _Format(
            template=row.template if row else DEFAULT_DIARY_TEMPLATE,
            entry_template=row.entry_template if row else DEFAULT_ENTRY_TEMPLATE,
            instructions=row.instructions if row else None,
            school_name=school.name if school else "",
        )

    async def _identify(
        self, session: AsyncSession, school_id: UUID, number: str
    ) -> _Teacher | None:
        """The ONE staff member whose phone is this number, or None.

        Two accounts sharing a number is refused outright: the agent cannot know
        which of them is speaking, and guessing would post under the wrong name.
        """
        cc = self.settings.WHATSAPP_DEFAULT_COUNTRY_CODE
        matches = [
            c
            for c in await DiaryLookupRepository(session).staff_with_phones(school_id)
            if normalize_phone(c.phone, cc) == number
        ]
        if len({m.user_id for m in matches}) != 1:
            if matches:
                logger.warning("diary_agent_ambiguous_phone", school_id=str(school_id))
            return None
        permissions: frozenset[str] = frozenset().union(*(m.permissions for m in matches))
        return _Teacher(
            user_id=matches[0].user_id, full_name=matches[0].full_name, permissions=permissions
        )

    async def _sender_number(self, event: InboundMessage) -> str | None:
        """International digits of a PERSON's chat; None for groups, channels, status."""
        user, _, server = event.chat_id.partition("@")
        if server in ("c.us", "s.whatsapp.net"):
            return re.sub(r"\D", "", user) or None
        if server == "lid":
            try:
                phone = await self.waha.lid_to_phone(event.session, event.chat_id)
            except WahaError:
                return None
            return re.sub(r"\D", "", phone.partition("@")[0]) if phone else None
        return None

    def _sender(self) -> WhatsAppSender | None:
        """How to post right away; None where posting needs the desktop (pywhatkit)."""
        match self.settings.WHATSAPP_BACKEND:
            case "waha":
                return WahaSender(self.waha)
            case "pywhatkit":
                return None
            case _:
                return build_whatsapp_sender(self.settings)

    async def _reply(self, event: InboundMessage, chat_id: str, text: str) -> None:
        try:
            await self.waha.send_text(event.session, chat_id, text)
        except WahaError as exc:
            logger.warning("diary_agent_reply_failed", error=str(exc))

    def _scope(self) -> AbstractAsyncContextManager[AsyncSession]:
        return session_scope(get_organization_id(), school_id=get_school_id())
