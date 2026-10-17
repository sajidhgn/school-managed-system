"""Question bank and test paper business rules.

AUTHORISATION SHAPE (mirrors books)
    paper:read     see the papers and bank questions of classes you may see
    paper:write    generate papers; change the papers YOU created
    paper:manage   change or delete any paper

    A bound teacher (`Caller.teacher_id`) sees papers and questions of the
    subjects they answer for, plus the subject-less ones of their classes, and can
    only write a paper from a book they can see.

GENERATION IS A JOB
    `create` and `regenerate` only queue the paper; the worker (`jobs.py`) writes
    it. A queued or generating paper cannot be edited -- the worker would
    overwrite the edit. `replace_entry` is the one synchronous model call: one
    question, a few seconds, and the teacher is waiting for exactly that.

EDITING NEVER CHANGES ANOTHER PAPER
    A bank question may sit on several papers. Editing it on one paper edits it in
    place only when no other paper uses it; otherwise the edit is made to a copy
    that replaces it on this paper alone.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditAction, record_audit
from app.core.config import Settings
from app.core.exceptions import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.core.logging import get_logger
from app.modules.books.models import Book, BookChapter, ChapterStatus
from app.modules.books.repository import BookLookupRepository, BookRepository
from app.modules.papers.generator import (
    DEFAULT_MARKS,
    TRUE_FALSE_OPTIONS,
    TYPE_ORDER,
    Chosen,
    PaperAgent,
    Slot,
    Source,
    SourcePage,
    generate,
)
from app.modules.papers.models import (
    Difficulty,
    Paper,
    PaperDifficulty,
    PaperLanguage,
    PaperQuestion,
    PaperStatus,
    Question,
    QuestionOrigin,
    QuestionType,
)
from app.modules.papers.repository import (
    PaperQuestionRepository,
    PaperRepository,
    QuestionRepository,
    SourceRepository,
)
from app.modules.papers.schemas import (
    ChapterRef,
    PaperCreate,
    PaperDetail,
    PaperQuestionAdd,
    PaperQuestionRead,
    PaperRead,
    PaperUpdate,
    QuestionRead,
    QuestionUpdate,
    ReplaceRequest,
    SectionInput,
    SectionRead,
)

logger = get_logger(__name__)

USABLE_CHAPTERS = frozenset({ChapterStatus.READY, ChapterStatus.NEEDS_REVIEW})
"""Chapters with read, ordered text. NEEDS_REVIEW is usable: its text exists, the
review is about whether the agent filed it right."""
_BUSY = frozenset({PaperStatus.QUEUED, PaperStatus.GENERATING})


@dataclass(frozen=True, slots=True)
class Caller:
    user_id: UUID
    may_write: bool
    may_manage: bool
    teacher_id: UUID | None = None


class PaperService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.papers = PaperRepository(session)
        self.entries = PaperQuestionRepository(session)
        self.questions = QuestionRepository(session)
        self.sources = SourceRepository(session)
        self.books = BookRepository(session)
        self.lookup = BookLookupRepository(session)

    # -- papers -------------------------------------------------------------

    async def list_papers(
        self,
        caller: Caller,
        *,
        class_id: UUID | None,
        subject_id: UUID | None,
        status: PaperStatus | None,
        limit: int,
        offset: int,
    ) -> list[PaperRead]:
        rows = await self.papers.list_with_totals(
            class_id=class_id,
            subject_id=subject_id,
            status=status,
            teacher_id=caller.teacher_id,
            limit=limit,
            offset=offset,
        )
        names = await self._names([p for p, _, _ in rows])
        return [self._read(p, caller, count, marks, names) for p, count, marks in rows]

    async def create(self, payload: PaperCreate, caller: Caller) -> PaperDetail:
        if not (caller.may_write or caller.may_manage):
            raise AuthorizationError("You cannot create test papers.", code="PAPER_FORBIDDEN")
        book = await self._book_or_404(payload.book_id, caller)
        chapters = {c.id: c for c in await self.sources.chapters(book.id)}
        for chapter_id in payload.chapter_ids:
            chapter = chapters.get(chapter_id)
            if chapter is None:
                raise ValidationError(
                    "A chosen chapter is not in this book.", code="CHAPTER_NOT_FOUND"
                )
            if chapter.status not in USABLE_CHAPTERS or chapter.page_count == 0:
                raise ValidationError(
                    f"Chapter {chapter.number} ({chapter.title}) has not been read yet. "
                    "Upload and process it first.",
                    code="CHAPTER_NOT_READY",
                )
        ordered = sorted(payload.chapter_ids, key=lambda i: chapters[i].number)
        paper = Paper(
            organization_id=book.organization_id,
            school_id=book.school_id,
            class_id=book.class_id,
            subject_id=book.subject_id,
            book_id=book.id,
            title=payload.title,
            language=payload.language,
            difficulty=payload.difficulty,
            paper_type=payload.paper_type,
            duration_minutes=payload.duration_minutes,
            instructions=payload.instructions,
            settings={
                "chapter_ids": [str(i) for i in ordered],
                "sections": [
                    {
                        "type": s.type.value,
                        "count": s.count,
                        "marks": s.marks or DEFAULT_MARKS[s.type],
                    }
                    for s in sorted(payload.sections, key=lambda s: TYPE_ORDER.index(s.type))
                ],
            },
            status=PaperStatus.QUEUED,
            created_by_user_id=caller.user_id,
        )
        self.session.add(paper)
        await self.session.flush()
        await self._audit(paper, caller, AuditAction.PAPER_REQUESTED, after=_snapshot(paper))
        return await self.detail(paper.id, caller)

    async def detail(self, paper_id: UUID, caller: Caller) -> PaperDetail:
        paper = await self._paper_or_404(paper_id, caller)
        await self.session.refresh(paper)
        entries = await self.entries.for_paper(paper.id)
        names = await self._names([paper])
        chapter_rows = await self.sources.chapters(paper.book_id) if paper.book_id else []
        chapter_titles = {c.id: c for c in chapter_rows}
        wanted = [UUID(i) for i in paper.settings.get("chapter_ids", [])]

        sections: dict[QuestionType, list[PaperQuestionRead]] = {}
        for entry, question in entries:
            sections.setdefault(question.type, []).append(
                PaperQuestionRead(
                    id=entry.id,
                    position=entry.position,
                    marks=entry.marks,
                    requested_difficulty=entry.requested_difficulty,
                    question=_question_read(question, chapter_titles),
                )
            )
        base = self._read(
            paper,
            caller,
            len(entries),
            sum(e.marks for e, _ in entries),
            names,
        )
        return PaperDetail(
            **base.model_dump(),
            duration_minutes=paper.duration_minutes,
            instructions=paper.instructions,
            chapters=[
                ChapterRef(id=c.id, number=c.number, title=c.title)
                for i in wanted
                if (c := chapter_titles.get(i)) is not None
            ],
            requested=[SectionInput.model_validate(s) for s in paper.settings.get("sections", [])],
            report=paper.report,
            error=paper.error,
            sections=[
                SectionRead(
                    type=qtype,
                    marks=sum(q.marks for q in sections[qtype]),
                    questions=sections[qtype],
                )
                for qtype in TYPE_ORDER
                if qtype in sections
            ],
        )

    async def update(self, paper_id: UUID, payload: PaperUpdate, caller: Caller) -> PaperDetail:
        paper = await self._editable(paper_id, caller)
        before = _snapshot(paper)
        for field, value in payload.model_dump(exclude_unset=True).items():
            if field == "title" and value is None:
                continue
            setattr(paper, field, value)
        await self.session.flush()
        await self._audit(
            paper, caller, AuditAction.PAPER_UPDATED, before=before, after=_snapshot(paper)
        )
        return await self.detail(paper.id, caller)

    async def delete(self, paper_id: UUID, caller: Caller) -> None:
        paper = await self._editable(paper_id, caller, allow_busy=True)
        await self._audit(paper, caller, AuditAction.PAPER_DELETED, before=_snapshot(paper))
        await self.session.delete(paper)
        await self.session.flush()

    async def regenerate(self, paper_id: UUID, caller: Caller) -> PaperDetail:
        """Queue the paper to be written again from scratch. Its current questions
        leave the paper but stay in the bank."""
        paper = await self._editable(paper_id, caller)
        await self.entries.clear(paper.id)
        paper.status = PaperStatus.QUEUED
        paper.report = None
        paper.error = None
        paper.attempts = 0
        paper.locked_at = None
        await self.session.flush()
        await self._audit(paper, caller, AuditAction.PAPER_REGENERATED)
        return await self.detail(paper.id, caller)

    # -- the paper's questions ----------------------------------------------

    async def edit_entry(
        self, paper_id: UUID, entry_id: UUID, payload: QuestionUpdate, caller: Caller
    ) -> PaperQuestionRead:
        paper = await self._editable(paper_id, caller)
        entry = await self._entry_or_404(paper, entry_id)
        question = await self.questions.get(entry.question_id)
        if question is None:
            raise NotFoundError("Question not found.")
        changes = payload.model_dump(exclude_unset=True)
        marks = changes.pop("marks", None)
        if changes:
            merged = _merged(question, changes)
            if await self.entries.exists(
                PaperQuestion.question_id == question.id, PaperQuestion.paper_id != paper.id
            ):
                question = self._copy(question, caller)
                self.session.add(question)
                await self.session.flush()
                entry.question_id = question.id
            for field, value in merged.items():
                setattr(question, field, value)
            question.origin = QuestionOrigin.MANUAL
        if marks is not None:
            entry.marks = marks
        await self.session.flush()
        await self._audit(
            paper,
            caller,
            AuditAction.PAPER_QUESTION_EDITED,
            after={
                "entry_id": str(entry.id),
                "fields": sorted([*changes, *(["marks"] if marks else [])]),
            },
        )
        return await self._entry_read(entry, question, paper)

    async def remove_entry(self, paper_id: UUID, entry_id: UUID, caller: Caller) -> None:
        paper = await self._editable(paper_id, caller)
        entry = await self._entry_or_404(paper, entry_id)
        position = entry.position
        await self.session.delete(entry)
        await self.session.flush()
        await self.entries.close_gap(paper.id, position)
        await self._audit(
            paper,
            caller,
            AuditAction.PAPER_QUESTION_REMOVED,
            before={"entry_id": str(entry_id), "question_id": str(entry.question_id)},
        )

    async def add_entry(
        self, paper_id: UUID, payload: PaperQuestionAdd, caller: Caller
    ) -> PaperQuestionRead:
        """Put a bank question on the paper, at the end of its type's section."""
        paper = await self._editable(paper_id, caller)
        question = await self.questions.get(payload.question_id)
        if question is None or (
            caller.teacher_id is not None
            and not await self.questions.visible(question.id, caller.teacher_id)
        ):
            raise NotFoundError("Question not found.")
        if question.class_id != paper.class_id:
            raise ValidationError(
                "That question belongs to another class.", code="QUESTION_OTHER_CLASS"
            )
        entries = await self.entries.for_paper(paper.id)
        if any(q.id == question.id for _, q in entries):
            raise ConflictError("That question is already on the paper.", code="DUPLICATE_QUESTION")
        rank = TYPE_ORDER.index(question.type)
        position = 1 + max(
            (e.position for e, q in entries if TYPE_ORDER.index(q.type) <= rank), default=0
        )
        await self.entries.make_room(paper.id, position)
        entry = PaperQuestion(
            organization_id=paper.organization_id,
            school_id=paper.school_id,
            paper_id=paper.id,
            question_id=question.id,
            position=position,
            marks=payload.marks or question.marks,
            requested_difficulty=question.difficulty,
        )
        self.session.add(entry)
        await self.session.flush()
        await self._audit(
            paper,
            caller,
            AuditAction.PAPER_QUESTION_ADDED,
            after={"entry_id": str(entry.id), "question_id": str(question.id)},
        )
        return await self._entry_read(entry, question, paper)

    async def replace_entry(
        self,
        paper_id: UUID,
        entry_id: UUID,
        payload: ReplaceRequest,
        agent: PaperAgent,
        caller: Caller,
    ) -> PaperQuestionRead:
        """Have the agent write one new question for this place on the paper."""
        paper = await self._editable(paper_id, caller)
        entry = await self._entry_or_404(paper, entry_id)
        old = await self.questions.get(entry.question_id)
        if old is None:
            raise NotFoundError("Question not found.")
        source, chapter_ids = await build_source(
            self.sources, paper, self.lookup, self.settings.PAPERS_MAX_SOURCE_CHARS
        )
        level = payload.difficulty or entry.requested_difficulty or old.difficulty
        on_paper = [q.text for _, q in await self.entries.for_paper(paper.id)]
        result = await generate(
            source, [Slot(old.type, level, entry.marks)], paper.language, agent, avoid=on_paper
        )
        paper.input_tokens += agent.usage.input_tokens
        paper.output_tokens += agent.usage.output_tokens
        if not result.chosen:
            await self.session.flush()
            raise ValidationError(
                "No replacement passed the checks this time. Try again.",
                code="REPLACEMENT_FAILED",
            )
        question = new_question(paper, result.chosen[0], chapter_ids, caller.user_id)
        self.session.add(question)
        await self.session.flush()
        entry.question_id = question.id
        entry.requested_difficulty = level
        await self.session.flush()
        await self._audit(
            paper,
            caller,
            AuditAction.PAPER_QUESTION_REPLACED,
            before={"question_id": str(old.id)},
            after={"question_id": str(question.id)},
        )
        return await self._entry_read(entry, question, paper)

    # -- the bank -----------------------------------------------------------

    async def question_bank(
        self,
        caller: Caller,
        *,
        class_id: UUID | None,
        subject_id: UUID | None,
        book_id: UUID | None,
        chapter_id: UUID | None,
        qtype: QuestionType | None,
        difficulty: Difficulty | None,
        language: PaperLanguage | None,
        text: str | None,
        limit: int,
        offset: int,
    ) -> list[QuestionRead]:
        rows = await self.questions.bank(
            class_id=class_id,
            subject_id=subject_id,
            book_id=book_id,
            chapter_id=chapter_id,
            qtype=qtype,
            difficulty=difficulty,
            language=language,
            text=text,
            teacher_id=caller.teacher_id,
            limit=limit,
            offset=offset,
        )
        chapters: dict[UUID, BookChapter] = {}
        for book in {q.book_id for q in rows if q.book_id}:
            chapters.update({c.id: c for c in await self.sources.chapters(book)})
        return [_question_read(q, chapters) for q in rows]

    # -- internals ----------------------------------------------------------

    async def _book_or_404(self, book_id: UUID, caller: Caller) -> Book:
        book = await self.books.get(book_id)
        if book is None or (
            caller.teacher_id is not None
            and not await self.books.visible(book_id, caller.teacher_id)
        ):
            raise NotFoundError("Book not found.")
        return book

    async def _paper_or_404(self, paper_id: UUID, caller: Caller) -> Paper:
        paper = await self.papers.get(paper_id)
        if paper is None or (
            caller.teacher_id is not None
            and not await self.papers.visible(paper_id, caller.teacher_id)
        ):
            raise NotFoundError("Paper not found.")
        return paper

    async def _editable(self, paper_id: UUID, caller: Caller, *, allow_busy: bool = False) -> Paper:
        await self._paper_or_404(paper_id, caller)
        paper = await self.papers.for_update(paper_id)
        if paper is None:
            raise NotFoundError("Paper not found.")
        if not _may_edit(paper, caller):
            raise AuthorizationError(
                "You can only change papers you created.", code="PAPER_NOT_OWNED"
            )
        if not allow_busy and paper.status in _BUSY:
            raise ConflictError(
                "The paper is being generated. Wait for it to finish.", code="PAPER_BUSY"
            )
        return paper

    async def _entry_or_404(self, paper: Paper, entry_id: UUID) -> PaperQuestion:
        entry = await self.entries.on_paper(paper.id, entry_id)
        if entry is None:
            raise NotFoundError("That question is not on this paper.")
        return entry

    async def _entry_read(
        self, entry: PaperQuestion, question: Question, paper: Paper
    ) -> PaperQuestionRead:
        await self.session.refresh(question)
        chapters = (
            {c.id: c for c in await self.sources.chapters(paper.book_id)} if paper.book_id else {}
        )
        return PaperQuestionRead(
            id=entry.id,
            position=entry.position,
            marks=entry.marks,
            requested_difficulty=entry.requested_difficulty,
            question=_question_read(question, chapters),
        )

    async def _names(self, papers: Sequence[Paper]) -> dict[str, dict[UUID, str]]:
        books = {}
        for book_id in {p.book_id for p in papers if p.book_id}:
            book = await self.books.get(book_id)
            if book is not None:
                books[book.id] = book.title
        return {
            "classes": await self.lookup.class_names(p.class_id for p in papers),
            "subjects": await self.lookup.subject_names(p.subject_id for p in papers),
            "users": await self.lookup.user_names(p.created_by_user_id for p in papers),
            "books": books,
        }

    @staticmethod
    def _read(
        paper: Paper, caller: Caller, count: int, marks: int, names: dict[str, dict[UUID, str]]
    ) -> PaperRead:
        return PaperRead(
            id=paper.id,
            title=paper.title,
            class_id=paper.class_id,
            class_name=names["classes"].get(paper.class_id),
            subject_id=paper.subject_id,
            subject_name=names["subjects"].get(paper.subject_id) if paper.subject_id else None,
            book_id=paper.book_id,
            book_title=names["books"].get(paper.book_id) if paper.book_id else None,
            language=paper.language,
            difficulty=paper.difficulty,
            paper_type=paper.paper_type,
            status=paper.status,
            question_count=count,
            total_marks=marks,
            created_by_user_id=paper.created_by_user_id,
            created_by_name=(
                names["users"].get(paper.created_by_user_id) if paper.created_by_user_id else None
            ),
            can_edit=_may_edit(paper, caller),
            created_at=paper.created_at,
            generated_at=paper.generated_at,
        )

    @staticmethod
    def _copy(question: Question, caller: Caller) -> Question:
        return Question(
            organization_id=question.organization_id,
            school_id=question.school_id,
            class_id=question.class_id,
            subject_id=question.subject_id,
            book_id=question.book_id,
            chapter_id=question.chapter_id,
            type=question.type,
            difficulty=question.difficulty,
            language=question.language,
            text=question.text,
            options=list(question.options) if question.options is not None else None,
            correct_option=question.correct_option,
            answer=question.answer,
            marks=question.marks,
            printed_page=question.printed_page,
            origin=QuestionOrigin.MANUAL,
            checks=None,
            created_by_user_id=caller.user_id,
        )

    async def _audit(
        self,
        paper: Paper,
        caller: Caller,
        action: str,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        await record_audit(
            self.session,
            organization_id=paper.organization_id,
            school_id=paper.school_id,
            actor_user_id=caller.user_id,
            action=action,
            entity_type="paper",
            entity_id=paper.id,
            before=before,
            after=after,
        )


# ---------------------------------------------------------------------------
# Shared with the worker
# ---------------------------------------------------------------------------


async def build_source(
    sources: SourceRepository,
    paper: Paper,
    lookup: BookLookupRepository,
    max_chars: int,
) -> tuple[Source, dict[int, UUID]]:
    """The chapters' text as the models see it, and chapter number -> id.

    Longer than `max_chars`, each chapter keeps its first pages up to an equal
    share of the budget -- a paper over three chapters must not come only from
    the first.
    """
    if paper.book_id is None:
        raise ValidationError("The paper's book was deleted.", code="BOOK_NOT_FOUND")
    chapters = {c.id: c for c in await sources.chapters(paper.book_id)}
    wanted = [
        chapters[i]
        for i in (UUID(x) for x in paper.settings.get("chapter_ids", []))
        if i in chapters
    ]
    if not wanted:
        raise ValidationError("The paper's chapters were deleted.", code="CHAPTER_NOT_FOUND")
    rows = await sources.pages([c.id for c in wanted])
    by_chapter: dict[UUID, list[tuple[int | None, str]]] = {}
    for chapter_id, printed, text in rows:
        by_chapter.setdefault(chapter_id, []).append((printed, text))

    share = max_chars // len(wanted)
    pages: list[SourcePage] = []
    truncated = False
    for chapter in wanted:
        used = 0
        for printed, text in by_chapter.get(chapter.id, []):
            if not text.strip():
                continue
            if used + len(text) > share and used:
                truncated = True
                break
            if len(text) > share:
                truncated = True
            pages.append(SourcePage(chapter.number, printed, text[:share]))
            used += len(text)
    if not pages:
        raise ValidationError(
            "The chosen chapters have no readable text.", code="CHAPTER_NOT_READY"
        )

    book = await BookRepository(sources.session).get(paper.book_id)
    class_name = (await lookup.class_names([paper.class_id])).get(paper.class_id, "the class")
    subject_name = (
        (await lookup.subject_names([paper.subject_id])).get(paper.subject_id)
        if paper.subject_id
        else None
    )
    source = Source(
        book_title=book.title if book else "the textbook",
        class_name=class_name,
        subject_name=subject_name,
        chapters=tuple((c.number, c.title) for c in wanted),
        pages=tuple(pages),
        truncated=truncated,
    )
    return source, {c.number: c.id for c in wanted}


def new_question(
    paper: Paper, chosen: Chosen, chapter_ids: dict[int, UUID], user_id: UUID | None
) -> Question:
    draft = chosen.draft
    chapter_id = chapter_ids.get(draft.chapter_number) if draft.chapter_number else None
    if chapter_id is None and len(chapter_ids) == 1:
        chapter_id = next(iter(chapter_ids.values()))
    return Question(
        organization_id=paper.organization_id,
        school_id=paper.school_id,
        class_id=paper.class_id,
        subject_id=paper.subject_id,
        book_id=paper.book_id,
        chapter_id=chapter_id,
        type=draft.type,
        difficulty=chosen.difficulty,
        language=paper.language,
        text=draft.text,
        options=list(draft.options) or None,
        correct_option=draft.correct_option,
        answer=draft.answer,
        marks=chosen.slot.marks,
        printed_page=draft.printed_page,
        origin=QuestionOrigin.AI,
        checks=chosen.check.as_json(),
        created_by_user_id=user_id,
    )


def slots_for(paper: Paper) -> list[Slot]:
    from app.modules.papers.generator import Section, plan_slots

    sections = [
        Section(QuestionType(s["type"]), int(s["count"]), int(s["marks"]))
        for s in paper.settings.get("sections", [])
    ]
    return plan_slots(sections, PaperDifficulty(paper.difficulty))


def _may_edit(paper: Paper, caller: Caller) -> bool:
    if caller.may_manage:
        return True
    return caller.may_write and paper.created_by_user_id == caller.user_id


def _merged(question: Question, changes: dict[str, Any]) -> dict[str, Any]:
    """The edit, checked against the question's type. Raises on a bad combination."""
    text = changes.get("text", question.text)
    options = changes.get("options", question.options)
    correct = changes.get("correct_option", question.correct_option)
    answer = changes.get("answer", question.answer)
    if question.type is QuestionType.MCQ:
        cleaned = [o.strip() for o in options or []]
        if len(cleaned) != 4 or not all(cleaned) or len({o.casefold() for o in cleaned}) != 4:
            raise ValidationError(
                "A multiple-choice question needs four different options.",
                code="INVALID_OPTIONS",
            )
        if correct not in range(4):
            raise ValidationError("Choose the correct option.", code="INVALID_OPTIONS")
        options = cleaned
    elif question.type is QuestionType.TRUE_FALSE:
        options = list(TRUE_FALSE_OPTIONS[PaperLanguage(question.language)])
        if correct not in (0, 1):
            raise ValidationError("Choose true or false.", code="INVALID_OPTIONS")
    else:
        if changes.get("options") or changes.get("correct_option") is not None:
            raise ValidationError(
                "Only multiple-choice and true/false questions have options.",
                code="INVALID_OPTIONS",
            )
        options, correct = None, None
        if not (answer or "").strip():
            raise ValidationError("The answer key cannot be empty.", code="INVALID_ANSWER")
    merged: dict[str, Any] = {
        "text": text.strip(),
        "options": options,
        "correct_option": correct,
        "answer": (answer or "").strip(),
    }
    if "difficulty" in changes and changes["difficulty"] is not None:
        merged["difficulty"] = changes["difficulty"]
    return merged


def _question_read(question: Question, chapters: dict[UUID, BookChapter]) -> QuestionRead:
    chapter = chapters.get(question.chapter_id) if question.chapter_id else None
    return QuestionRead(
        id=question.id,
        type=question.type,
        difficulty=question.difficulty,
        language=question.language,
        text=question.text,
        options=question.options,
        correct_option=question.correct_option,
        answer=question.answer,
        marks=question.marks,
        printed_page=question.printed_page,
        book_id=question.book_id,
        chapter_id=question.chapter_id,
        chapter_number=chapter.number if chapter else None,
        chapter_title=chapter.title if chapter else None,
        origin=question.origin,
        checks=question.checks,
        created_at=question.created_at,
    )


def _snapshot(paper: Paper) -> dict[str, Any]:
    return {
        "title": paper.title,
        "language": paper.language.value,
        "difficulty": paper.difficulty.value,
        "paper_type": paper.paper_type.value,
        "duration_minutes": paper.duration_minutes,
        "settings": paper.settings,
    }
