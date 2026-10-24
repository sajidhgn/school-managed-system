"""Textbook library data access. SQL only -- no business rules.

Organization isolation comes from RLS. Every hand-built query applies the campus
filter explicitly: a joined `select(...)` never passes through `_base_select`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Select,
    Text,
    and_,
    cast,
    delete,
    func,
    literal,
    literal_column,
    or_,
    select,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, defer

from app.common.repository import BaseRepository
from app.core.context import get_school_id
from app.modules.academics.models import ClassSubject, SchoolClass, Subject
from app.modules.academics.teaching_scope import taught_class_ids, teaches_subject
from app.modules.auth.models import User
from app.modules.books.models import (
    SEARCH_CONFIG,
    Book,
    BookChapter,
    BookChapterFile,
    BookChunk,
    BookPage,
    ChapterStatus,
)


def _scoped[T: tuple[Any, ...]](stmt: Select[T], column: InstrumentedAttribute[UUID]) -> Select[T]:
    if (school_id := get_school_id()) is not None:
        stmt = stmt.where(column == school_id)
    return stmt


def taught_books(teacher_id: UUID) -> ColumnElement[bool]:
    """Books a bound teacher may see.

    A book filed under a subject follows that subject (`teaches_subject`: the class
    teacher sees every subject's book, a subject teacher only theirs). A book with
    no subject is the whole class's, so anyone assigned to the class sees it.
    """
    return or_(
        teaches_subject(teacher_id, Book.class_id, Book.subject_id),
        and_(Book.subject_id.is_(None), Book.class_id.in_(taught_class_ids(teacher_id))),
    )


class BookRepository(BaseRepository[Book]):
    model = Book

    async def visible(self, book_id: UUID, teacher_id: UUID) -> bool:
        stmt = select(Book.id).where(Book.id == book_id, taught_books(teacher_id))
        return (await self.session.scalar(stmt)) is not None

    async def list_with_counts(
        self,
        *,
        class_id: UUID | None = None,
        subject_id: UUID | None = None,
        teacher_id: UUID | None = None,
    ) -> Sequence[tuple[Book, int, int]]:
        """Books with (chapter count, ready chapter count), newest first."""
        chapters = (
            select(
                BookChapter.book_id,
                func.count(BookChapter.id).label("total"),
                func.count(BookChapter.id)
                .filter(BookChapter.status == ChapterStatus.READY)
                .label("ready"),
            )
            .group_by(BookChapter.book_id)
            .subquery()
        )
        stmt = (
            select(
                Book,
                func.coalesce(chapters.c.total, 0),
                func.coalesce(chapters.c.ready, 0),
            )
            .outerjoin(chapters, chapters.c.book_id == Book.id)
            .order_by(Book.created_at.desc(), Book.id)
        )
        stmt = _scoped(stmt, Book.school_id)
        if class_id is not None:
            stmt = stmt.where(Book.class_id == class_id)
        if subject_id is not None:
            stmt = stmt.where(Book.subject_id == subject_id)
        if teacher_id is not None:
            stmt = stmt.where(taught_books(teacher_id))
        return [(b, int(t), int(r)) for b, t, r in (await self.session.execute(stmt)).all()]

    async def find_duplicate(
        self, *, class_id: UUID, title: str, publisher: str, version: str, exclude: UUID | None
    ) -> Book | None:
        stmt = self._base_select().where(
            Book.class_id == class_id,
            func.lower(Book.title) == title.lower(),
            func.lower(Book.publisher) == publisher.lower(),
            func.lower(Book.version) == version.lower(),
        )
        if exclude is not None:
            stmt = stmt.where(Book.id != exclude)
        return (await self.session.execute(stmt.limit(1))).scalar_one_or_none()


class ChapterRepository(BaseRepository[BookChapter]):
    model = BookChapter

    async def for_book(self, book_id: UUID) -> Sequence[BookChapter]:
        stmt = (
            self._base_select().where(BookChapter.book_id == book_id).order_by(BookChapter.number)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def for_book_locked(self, book_id: UUID, chapter_id: UUID) -> BookChapter | None:
        stmt = (
            self._base_select()
            .where(BookChapter.id == chapter_id, BookChapter.book_id == book_id)
            .with_for_update()
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def by_number(self, book_id: UUID, number: int) -> BookChapter | None:
        stmt = self._base_select().where(
            BookChapter.book_id == book_id, BookChapter.number == number
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()


class ChapterFileRepository(BaseRepository[BookChapterFile]):
    model = BookChapterFile

    async def for_chapters(self, chapter_ids: Iterable[UUID]) -> dict[UUID, list[BookChapterFile]]:
        ids = set(chapter_ids)
        if not ids:
            return {}
        stmt = (
            self._base_select()
            .where(BookChapterFile.chapter_id.in_(ids))
            .order_by(BookChapterFile.sort_order)
        )
        result: dict[UUID, list[BookChapterFile]] = {}
        for f in (await self.session.execute(stmt)).scalars():
            result.setdefault(f.chapter_id, []).append(f)
        return result

    async def next_sort_order(self, chapter_id: UUID) -> int:
        stmt = select(func.coalesce(func.max(BookChapterFile.sort_order), 0)).where(
            BookChapterFile.chapter_id == chapter_id
        )
        return int((await self.session.execute(stmt)).scalar_one()) + 1

    async def existing_hashes(self, chapter_id: UUID) -> set[str]:
        stmt = select(BookChapterFile.sha256).where(BookChapterFile.chapter_id == chapter_id)
        return set((await self.session.execute(stmt)).scalars())


class PageRepository(BaseRepository[BookPage]):
    model = BookPage

    async def for_chapter(self, chapter_id: UUID) -> Sequence[BookPage]:
        stmt = (
            self._base_select().where(BookPage.chapter_id == chapter_id).order_by(BookPage.position)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def clear_chapter(self, chapter_id: UUID) -> None:
        """Drop a chapter's pages and chunks -- they describe files that changed."""
        await self.session.execute(delete(BookChunk).where(BookChunk.chapter_id == chapter_id))
        await self.session.execute(delete(BookPage).where(BookPage.chapter_id == chapter_id))


@dataclass(frozen=True, slots=True)
class LibraryScope:
    """Which books a library-wide search covers. Every field narrows it."""

    class_id: UUID | None = None
    subject_id: UUID | None = None
    book_id: UUID | None = None
    chapter_id: UUID | None = None
    teacher_id: UUID | None = None
    """A bound teacher: only the books `taught_books` lets them see."""


def _in_library_scope[T: tuple[Any, ...]](stmt: Select[T], scope: LibraryScope) -> Select[T]:
    stmt = _scoped(stmt.join(Book, Book.id == BookChunk.book_id), BookChunk.school_id)
    if scope.class_id is not None:
        stmt = stmt.where(Book.class_id == scope.class_id)
    if scope.subject_id is not None:
        stmt = stmt.where(Book.subject_id == scope.subject_id)
    if scope.book_id is not None:
        stmt = stmt.where(BookChunk.book_id == scope.book_id)
    if scope.chapter_id is not None:
        stmt = stmt.where(BookChunk.chapter_id == scope.chapter_id)
    if scope.teacher_id is not None:
        stmt = stmt.where(taught_books(scope.teacher_id))
    return stmt


class ChunkRepository(BaseRepository[BookChunk]):
    model = BookChunk

    async def search(
        self,
        book_id: UUID,
        query_vector: list[float],
        *,
        chapter_id: UUID | None,
        limit: int,
    ) -> Sequence[tuple[BookChunk, BookChapter, float]]:
        """Nearest chunks by cosine distance (`<=>`), served by the HNSW index.
        Chunks still waiting for an embedding batch have no vector and are skipped."""
        distance = BookChunk.embedding.cosine_distance(query_vector)
        stmt = (
            select(BookChunk, BookChapter, distance.label("distance"))
            # The 1536 floats are only needed inside PostgreSQL, for the distance.
            .options(defer(BookChunk.embedding))
            .join(BookChapter, BookChapter.id == BookChunk.chapter_id)
            .where(BookChunk.book_id == book_id, BookChunk.embedding.is_not(None))
            .order_by(distance)
            .limit(limit)
        )
        stmt = _scoped(stmt, BookChunk.school_id)
        if chapter_id is not None:
            stmt = stmt.where(BookChunk.chapter_id == chapter_id)
        return [(c, ch, float(d)) for c, ch, d in (await self.session.execute(stmt)).all()]

    async def nearest_ids(
        self, query_vector: list[float], scope: LibraryScope, *, limit: int
    ) -> list[UUID]:
        """Chunk ids by cosine distance (`<=>`), nearest first.

        A filtered HNSW scan collects `hnsw.ef_search` candidates BEFORE the campus
        and book filters run; once the index holds many campuses most of those are
        someone else's, and the search comes back short or empty. pgvector 0.8's
        iterative scan keeps walking the graph until enough rows pass the filters.
        """
        await self.session.execute(
            select(func.set_config("hnsw.iterative_scan", "relaxed_order", True))
        )
        stmt = (
            _in_library_scope(select(BookChunk.id), scope)
            .where(BookChunk.embedding.is_not(None))
            .order_by(BookChunk.embedding.cosine_distance(query_vector))
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def keyword_ids(self, query: str, scope: LibraryScope, *, limit: int) -> list[UUID]:
        """Chunk ids by full-text rank, best first.

        The question's words are OR-ed, not AND-ed: "what is newton's law" must
        find a passage that never says "what". Stop words are dropped by the
        English configuration, and `ts_rank_cd` puts passages matching more of the
        words, closer together, first.
        """
        words = func.plainto_tsquery(literal_column(f"'{SEARCH_CONFIG}'::regconfig"), query)
        any_word = func.to_tsquery(
            literal_column("'simple'::regconfig"), func.replace(cast(words, Text), "&", "|")
        )
        stmt = (
            _in_library_scope(select(BookChunk.id), scope)
            .where(BookChunk.search_vector.op("@@")(any_word))
            .order_by(func.ts_rank_cd(BookChunk.search_vector, any_word).desc(), BookChunk.id)
            .limit(limit)
        )
        return list((await self.session.scalars(stmt)).all())

    async def with_sources(
        self, chunk_ids: Sequence[UUID]
    ) -> dict[UUID, tuple[BookChunk, BookChapter, Book]]:
        if not chunk_ids:
            return {}
        stmt = (
            select(BookChunk, BookChapter, Book)
            .options(defer(BookChunk.embedding))
            .join(BookChapter, BookChapter.id == BookChunk.chapter_id)
            .join(Book, Book.id == BookChunk.book_id)
            .where(BookChunk.id.in_(chunk_ids))
        )
        stmt = _scoped(stmt, BookChunk.school_id)
        return {c.id: (c, ch, b) for c, ch, b in (await self.session.execute(stmt)).all()}


class BookLookupRepository:
    """Names for the class, subject and uploader beside a book."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def school_class(self, class_id: UUID) -> SchoolClass | None:
        stmt = select(SchoolClass).where(
            SchoolClass.id == class_id, SchoolClass.deleted_at.is_(None)
        )
        stmt = _scoped(stmt, SchoolClass.school_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def subject(self, subject_id: UUID) -> Subject | None:
        stmt = select(Subject).where(Subject.id == subject_id, Subject.deleted_at.is_(None))
        stmt = _scoped(stmt, Subject.school_id)
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def filing_options(
        self, teacher_id: UUID | None
    ) -> tuple[list[tuple[UUID, str]], list[tuple[UUID, UUID, str]]]:
        """Where a new book can be filed: `(class id, name)` and each class's
        curriculum as `(class id, subject id, subject name)`.

        A bound teacher gets only the classes and subjects `_assert_in_scope` would
        let them file under, so a reading never suggests one the create refuses.
        """
        classes = (
            select(SchoolClass.id, SchoolClass.name)
            .where(SchoolClass.deleted_at.is_(None))
            .order_by(SchoolClass.level)
        )
        classes = _scoped(classes, SchoolClass.school_id)
        links = (
            select(ClassSubject.class_id, Subject.id, Subject.name)
            .join(Subject, Subject.id == ClassSubject.subject_id)
            .where(ClassSubject.deleted_at.is_(None), Subject.deleted_at.is_(None))
            .order_by(Subject.name)
        )
        links = _scoped(links, ClassSubject.school_id)
        if teacher_id is not None:
            classes = classes.where(SchoolClass.id.in_(taught_class_ids(teacher_id)))
            links = links.where(
                teaches_subject(teacher_id, ClassSubject.class_id, ClassSubject.subject_id)
            )
        return (
            [(row[0], row[1]) for row in await self.session.execute(classes)],
            [(row[0], row[1], row[2]) for row in await self.session.execute(links)],
        )

    async def teaches_class(self, teacher_id: UUID, class_id: UUID) -> bool:
        stmt = select(SchoolClass.id).where(
            SchoolClass.id == class_id, SchoolClass.id.in_(taught_class_ids(teacher_id))
        )
        return (await self.session.scalar(stmt)) is not None

    async def teaches_subject(self, teacher_id: UUID, class_id: UUID, subject_id: UUID) -> bool:
        stmt = select(literal(True)).where(teaches_subject(teacher_id, class_id, subject_id))
        return bool(await self.session.scalar(stmt))

    async def class_names(self, ids: Iterable[UUID]) -> dict[UUID, str]:
        wanted = set(ids)
        if not wanted:
            return {}
        rows = await self.session.execute(
            select(SchoolClass.id, SchoolClass.name).where(SchoolClass.id.in_(wanted))
        )
        return {row[0]: row[1] for row in rows}

    async def subject_names(self, ids: Iterable[UUID | None]) -> dict[UUID, str]:
        wanted = {i for i in ids if i is not None}
        if not wanted:
            return {}
        rows = await self.session.execute(
            select(Subject.id, Subject.name).where(Subject.id.in_(wanted))
        )
        return {row[0]: row[1] for row in rows}

    async def user_names(self, ids: Iterable[UUID | None]) -> dict[UUID, str]:
        wanted = {i for i in ids if i is not None}
        if not wanted:
            return {}
        rows = await self.session.execute(
            select(User.id, User.full_name).where(User.id.in_(wanted))
        )
        return {row[0]: row[1] for row in rows}
