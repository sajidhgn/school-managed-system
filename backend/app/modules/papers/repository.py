"""Question bank and test paper data access. SQL only -- no business rules.

Organization isolation comes from RLS. Every hand-built query applies the campus
filter explicitly, for the reason `diary/repository.py` gives.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Select, and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute

from app.common.repository import BaseRepository
from app.core.context import get_school_id
from app.modules.academics.teaching_scope import taught_class_ids, teaches_subject
from app.modules.books.models import BookChapter, BookPage
from app.modules.papers.models import (
    Difficulty,
    Paper,
    PaperLanguage,
    PaperQuestion,
    PaperStatus,
    Question,
    QuestionType,
)


def _scoped[T: tuple[Any, ...]](stmt: Select[T], column: InstrumentedAttribute[UUID]) -> Select[T]:
    if (school_id := get_school_id()) is not None:
        stmt = stmt.where(column == school_id)
    return stmt


def taught(
    teacher_id: UUID,
    class_column: InstrumentedAttribute[UUID],
    subject_column: InstrumentedAttribute[UUID | None],
) -> ColumnElement[bool]:
    """Rows a bound teacher may see -- the same rule as `books.repository.taught_books`:
    a subject's rows follow the subject, a subject-less row the whole class."""
    return or_(
        teaches_subject(teacher_id, class_column, subject_column),
        and_(subject_column.is_(None), class_column.in_(taught_class_ids(teacher_id))),
    )


class PaperRepository(BaseRepository[Paper]):
    model = Paper

    async def visible(self, paper_id: UUID, teacher_id: UUID) -> bool:
        stmt = select(Paper.id).where(
            Paper.id == paper_id, taught(teacher_id, Paper.class_id, Paper.subject_id)
        )
        return (await self.session.scalar(stmt)) is not None

    async def list_with_totals(
        self,
        *,
        class_id: UUID | None,
        subject_id: UUID | None,
        status: PaperStatus | None,
        teacher_id: UUID | None,
        limit: int,
        offset: int,
    ) -> Sequence[tuple[Paper, int, int]]:
        """Papers with (question count, total marks), newest first."""
        totals = (
            select(
                PaperQuestion.paper_id,
                func.count(PaperQuestion.id).label("count"),
                func.sum(PaperQuestion.marks).label("marks"),
            )
            .group_by(PaperQuestion.paper_id)
            .subquery()
        )
        stmt = (
            select(Paper, func.coalesce(totals.c.count, 0), func.coalesce(totals.c.marks, 0))
            .outerjoin(totals, totals.c.paper_id == Paper.id)
            .order_by(Paper.created_at.desc(), Paper.id)
            .limit(limit)
            .offset(offset)
        )
        stmt = _scoped(stmt, Paper.school_id)
        if class_id is not None:
            stmt = stmt.where(Paper.class_id == class_id)
        if subject_id is not None:
            stmt = stmt.where(Paper.subject_id == subject_id)
        if status is not None:
            stmt = stmt.where(Paper.status == status)
        if teacher_id is not None:
            stmt = stmt.where(taught(teacher_id, Paper.class_id, Paper.subject_id))
        return [(p, int(c), int(m)) for p, c, m in (await self.session.execute(stmt)).all()]

    async def for_update(self, paper_id: UUID) -> Paper | None:
        stmt = _scoped(select(Paper).where(Paper.id == paper_id).with_for_update(), Paper.school_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()


class PaperQuestionRepository(BaseRepository[PaperQuestion]):
    model = PaperQuestion

    async def for_paper(self, paper_id: UUID) -> Sequence[tuple[PaperQuestion, Question]]:
        stmt = (
            select(PaperQuestion, Question)
            .join(Question, Question.id == PaperQuestion.question_id)
            .where(PaperQuestion.paper_id == paper_id)
            .order_by(PaperQuestion.position)
        )
        stmt = _scoped(stmt, PaperQuestion.school_id)
        return [(pq, q) for pq, q in (await self.session.execute(stmt)).all()]

    async def on_paper(self, paper_id: UUID, entry_id: UUID) -> PaperQuestion | None:
        stmt = _scoped(
            select(PaperQuestion).where(
                PaperQuestion.id == entry_id, PaperQuestion.paper_id == paper_id
            ),
            PaperQuestion.school_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def clear(self, paper_id: UUID) -> None:
        """Remove every question from a paper (the questions stay in the bank)."""
        entries = await self.for_paper(paper_id)
        for entry, _ in entries:
            await self.session.delete(entry)
        await self.session.flush()

    async def close_gap(self, paper_id: UUID, after: int) -> None:
        """Shift every entry after `after` up one place, in ascending order so each
        move lands on a position the previous one freed."""
        rows = (
            await self.session.execute(
                select(PaperQuestion.id, PaperQuestion.position)
                .where(PaperQuestion.paper_id == paper_id, PaperQuestion.position > after)
                .order_by(PaperQuestion.position)
            )
        ).all()
        for entry_id, position in rows:
            await self.session.execute(
                update(PaperQuestion)
                .where(PaperQuestion.id == entry_id)
                .values(position=position - 1)
            )

    async def make_room(self, paper_id: UUID, at: int) -> None:
        """Shift every entry from `at` down one place, last first."""
        rows = (
            await self.session.execute(
                select(PaperQuestion.id, PaperQuestion.position)
                .where(PaperQuestion.paper_id == paper_id, PaperQuestion.position >= at)
                .order_by(PaperQuestion.position.desc())
            )
        ).all()
        for entry_id, position in rows:
            await self.session.execute(
                update(PaperQuestion)
                .where(PaperQuestion.id == entry_id)
                .values(position=position + 1)
            )


class QuestionRepository(BaseRepository[Question]):
    model = Question

    async def bank(
        self,
        *,
        class_id: UUID | None,
        subject_id: UUID | None,
        book_id: UUID | None,
        chapter_id: UUID | None,
        qtype: QuestionType | None,
        difficulty: Difficulty | None,
        language: PaperLanguage | None,
        text: str | None,
        teacher_id: UUID | None,
        limit: int,
        offset: int,
    ) -> Sequence[Question]:
        stmt = _scoped(select(Question), Question.school_id).order_by(
            Question.created_at.desc(), Question.id
        )
        for column, value in (
            (Question.class_id, class_id),
            (Question.subject_id, subject_id),
            (Question.book_id, book_id),
            (Question.chapter_id, chapter_id),
            (Question.type, qtype),
            (Question.difficulty, difficulty),
            (Question.language, language),
        ):
            if value is not None:
                stmt = stmt.where(column == value)
        if text:
            escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            stmt = stmt.where(Question.text.ilike(f"%{escaped}%", escape="\\"))
        if teacher_id is not None:
            stmt = stmt.where(taught(teacher_id, Question.class_id, Question.subject_id))
        stmt = stmt.limit(limit).offset(offset)
        return (await self.session.execute(stmt)).scalars().all()

    async def visible(self, question_id: UUID, teacher_id: UUID) -> bool:
        stmt = select(Question.id).where(
            Question.id == question_id,
            taught(teacher_id, Question.class_id, Question.subject_id),
        )
        return (await self.session.scalar(stmt)) is not None


class SourceRepository:
    """The book text a paper is written from."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def chapters(self, book_id: UUID) -> Sequence[BookChapter]:
        stmt = _scoped(
            select(BookChapter).where(BookChapter.book_id == book_id).order_by(BookChapter.number),
            BookChapter.school_id,
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def pages(self, chapter_ids: Sequence[UUID]) -> Sequence[tuple[UUID, int | None, str]]:
        """(chapter id, printed page number, text) in reading order per chapter."""
        stmt = _scoped(
            select(BookPage.chapter_id, BookPage.printed_page_number, BookPage.text)
            .where(BookPage.chapter_id.in_(chapter_ids))
            .order_by(BookPage.chapter_id, BookPage.position),
            BookPage.school_id,
        )
        return [(c, n, t) for c, n, t in (await self.session.execute(stmt)).all()]
