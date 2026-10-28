"""Textbook library data access. SQL only -- no business rules.

TWO KINDS OF ROW
    * `school_books` -- a campus's shelf. Tenant data like any other: RLS bounds it
      to the organization and every query here applies the campus filter
      explicitly (a joined `select(...)` never passes through `_base_select`).
    * the book content -- `books` and everything under it. The shared library:
      RLS lets every organization READ it, so these repositories carry no campus
      filter (`_Library`). Which content a caller may reach is decided by its
      shelf -- `ShelfRepository` here, `BookService` above.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    Select,
    Subquery,
    Text,
    and_,
    bindparam,
    cast,
    delete,
    func,
    literal,
    literal_column,
    or_,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, defer

from app.common.repository import BaseRepository, contains_pattern
from app.common.schemas import PageParams
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
    SchoolBook,
)


def _scoped[T: tuple[Any, ...]](stmt: Select[T], column: InstrumentedAttribute[UUID]) -> Select[T]:
    if (school_id := get_school_id()) is not None:
        stmt = stmt.where(column == school_id)
    return stmt


def taught_books(teacher_id: UUID) -> ColumnElement[bool]:
    """Shelf entries a bound teacher may see.

    A book filed under a subject follows that subject (`teaches_subject`: the class
    teacher sees every subject's book, a subject teacher only theirs). A book with
    no subject is the whole class's, so anyone assigned to the class sees it.
    """
    return or_(
        teaches_subject(teacher_id, SchoolBook.class_id, SchoolBook.subject_id),
        and_(
            SchoolBook.subject_id.is_(None),
            SchoolBook.class_id.in_(taught_class_ids(teacher_id)),
        ),
    )


def _chapter_counts() -> Subquery:
    """book id -> (chapters, ready chapters), to outer-join beside a book."""
    return (
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


def _title_or_publisher(search: str) -> ColumnElement[bool]:
    pattern = contains_pattern(search)
    return or_(
        Book.title.ilike(pattern, escape="\\"),
        Book.publisher.ilike(pattern, escape="\\"),
    )


class _Library:
    """Library content is shared by every campus: no campus filter on its rows.

    `BaseRepository` would scope every read to the caller's campus, which hides a
    book another school uploaded from the schools that added it. Reaching content
    is gated on the shelf instead, before any of these repositories is asked.
    """

    def _school_scope_condition(self) -> None:
        return None


class BookRepository(_Library, BaseRepository[Book]):
    model = Book

    async def find_duplicate(self, catalog_key: str, *, exclude: UUID | None) -> Book | None:
        """The library's book with this key, whoever uploaded it."""
        stmt = select(Book).where(Book.catalog_key == catalog_key)
        if exclude is not None:
            stmt = stmt.where(Book.id != exclude)
        return (await self.session.execute(stmt.limit(1))).scalar_one_or_none()

    async def lock(self, book_id: UUID) -> None:
        """Row-lock the book for the rest of the transaction. Only its owner's
        organization can: `FOR UPDATE` must pass the UPDATE policy too."""
        await self.session.execute(select(Book.id).where(Book.id == book_id).with_for_update())

    async def library_page(
        self,
        *,
        params: PageParams,
        search: str | None = None,
        grade_key: str | None = None,
        subject: str | None = None,
    ) -> tuple[list[tuple[Book, int, int]], int]:
        """One page of the whole library, by title, with (chapters, ready chapters).

        `search` matches the title or publisher anywhere; `grade_key` is exact (see
        `catalog.grade_key`); `subject` is the uploader's subject name, ignoring case.
        """
        conditions: list[ColumnElement[bool]] = []
        if search:
            conditions.append(_title_or_publisher(search))
        if grade_key:
            conditions.append(Book.grade_key == grade_key)
        if subject:
            conditions.append(func.lower(Book.subject) == subject.lower())

        total = await self.session.scalar(select(func.count(Book.id)).where(*conditions))
        chapters = _chapter_counts()
        stmt = (
            select(Book, func.coalesce(chapters.c.total, 0), func.coalesce(chapters.c.ready, 0))
            .outerjoin(chapters, chapters.c.book_id == Book.id)
            .where(*conditions)
            .order_by(func.lower(Book.title), Book.grade_key, Book.version, Book.id)
            .offset(params.offset)
            .limit(params.limit)
        )
        rows = [(b, int(t), int(r)) for b, t, r in (await self.session.execute(stmt)).all()]
        return rows, int(total or 0)

    async def library_subjects(self, grade_key: str | None) -> list[str]:
        """The subject names in the library, one spelling per name ignoring case."""
        stmt = select(func.min(Book.subject)).where(Book.subject.is_not(None))
        if grade_key:
            stmt = stmt.where(Book.grade_key == grade_key)
        stmt = stmt.group_by(func.lower(Book.subject)).order_by(func.lower(Book.subject))
        return [s for s in (await self.session.scalars(stmt)).all() if s]


class ShelfRepository(BaseRepository[SchoolBook]):
    """The campus's books: which library books it uses, under which class."""

    model = SchoolBook

    async def entry(self, book_id: UUID) -> SchoolBook | None:
        """The caller's entry for a book. An organization-level caller with no campus
        chosen may see the book on several campuses: the earliest entry stands."""
        stmt = (
            self._base_select()
            .where(SchoolBook.book_id == book_id)
            .order_by(SchoolBook.created_at, SchoolBook.id)
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def on_campus(self, school_id: UUID, book_id: UUID) -> SchoolBook | None:
        stmt = self._base_select().where(
            SchoolBook.school_id == school_id, SchoolBook.book_id == book_id
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def visible(self, entry_id: UUID, teacher_id: UUID) -> bool:
        stmt = select(SchoolBook.id).where(SchoolBook.id == entry_id, taught_books(teacher_id))
        return (await self.session.scalar(stmt)) is not None

    async def shelved(self, book_ids: Iterable[UUID]) -> set[UUID]:
        """Which of these books the caller's campus already has."""
        wanted = set(book_ids)
        if not wanted:
            return set()
        stmt = _scoped(
            select(SchoolBook.book_id).where(SchoolBook.book_id.in_(wanted)),
            SchoolBook.school_id,
        )
        return set((await self.session.scalars(stmt)).all())

    async def schools_using(self, book_ids: Iterable[UUID]) -> dict[UUID, int]:
        """How many campuses, in EVERY organization, have each book on their shelf.

        Shelves are tenant data, so the count comes from `library_book_schools`, a
        SECURITY DEFINER function that returns counts and nothing else -- never
        whose shelves they are.
        """
        wanted = list(set(book_ids))
        if not wanted:
            return {}
        stmt = text("SELECT book_id, schools FROM library_book_schools(:ids)").bindparams(
            bindparam("ids", value=wanted, type_=ARRAY(PgUUID(as_uuid=True)))
        )
        return {row[0]: int(row[1]) for row in await self.session.execute(stmt)}

    async def list_with_counts(
        self,
        *,
        params: PageParams,
        class_id: UUID | None = None,
        subject_id: UUID | None = None,
        teacher_id: UUID | None = None,
        search: str | None = None,
    ) -> tuple[list[tuple[SchoolBook, Book, int, int]], int]:
        """One page of the campus's books -- (entry, book, chapters, ready chapters),
        newest on the shelf first -- plus how many entries match in all.

        Filters, search and the page are all applied in SQL. `search` matches the
        title or the publisher anywhere, case-insensitively.
        """
        conditions: list[ColumnElement[bool]] = []
        if class_id is not None:
            conditions.append(SchoolBook.class_id == class_id)
        if subject_id is not None:
            conditions.append(SchoolBook.subject_id == subject_id)
        if teacher_id is not None:
            conditions.append(taught_books(teacher_id))
        if search:
            conditions.append(_title_or_publisher(search))

        total = await self.session.scalar(
            _scoped(
                select(func.count(SchoolBook.id))
                .join(Book, Book.id == SchoolBook.book_id)
                .where(*conditions),
                SchoolBook.school_id,
            )
        )

        chapters = _chapter_counts()
        stmt = (
            select(
                SchoolBook,
                Book,
                func.coalesce(chapters.c.total, 0),
                func.coalesce(chapters.c.ready, 0),
            )
            .join(Book, Book.id == SchoolBook.book_id)
            .outerjoin(chapters, chapters.c.book_id == Book.id)
            .where(*conditions)
            .order_by(SchoolBook.created_at.desc(), SchoolBook.id)
            .offset(params.offset)
            .limit(params.limit)
        )
        stmt = _scoped(stmt, SchoolBook.school_id)
        rows = [(e, b, int(t), int(r)) for e, b, t, r in (await self.session.execute(stmt)).all()]
        return rows, int(total or 0)


class ChapterRepository(_Library, BaseRepository[BookChapter]):
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


class ChapterFileRepository(_Library, BaseRepository[BookChapterFile]):
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


class PageRepository(_Library, BaseRepository[BookPage]):
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
    """Which books a search across the campus's books covers. Every field narrows
    it; with none set it is every book on the caller's shelf."""

    class_id: UUID | None = None
    subject_id: UUID | None = None
    book_id: UUID | None = None
    chapter_id: UUID | None = None
    teacher_id: UUID | None = None
    """A bound teacher: only the books `taught_books` lets them see."""


def _in_library_scope[T: tuple[Any, ...]](stmt: Select[T], scope: LibraryScope) -> Select[T]:
    """Chunks of the books on the caller's shelf. A subquery, not a join: an
    organization-level caller may have one book on two campuses, and a join would
    return its chunks twice."""
    shelf = _scoped(select(SchoolBook.book_id), SchoolBook.school_id)
    if scope.class_id is not None:
        shelf = shelf.where(SchoolBook.class_id == scope.class_id)
    if scope.subject_id is not None:
        shelf = shelf.where(SchoolBook.subject_id == scope.subject_id)
    if scope.teacher_id is not None:
        shelf = shelf.where(taught_books(scope.teacher_id))
    stmt = stmt.where(BookChunk.book_id.in_(shelf))
    if scope.book_id is not None:
        stmt = stmt.where(BookChunk.book_id == scope.book_id)
    if scope.chapter_id is not None:
        stmt = stmt.where(BookChunk.chapter_id == scope.chapter_id)
    return stmt


class ChunkRepository(_Library, BaseRepository[BookChunk]):
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
        if chapter_id is not None:
            stmt = stmt.where(BookChunk.chapter_id == chapter_id)
        return [(c, ch, float(d)) for c, ch, d in (await self.session.execute(stmt)).all()]

    async def nearest_ids(
        self, query_vector: list[float], scope: LibraryScope, *, limit: int
    ) -> list[UUID]:
        """Chunk ids by cosine distance (`<=>`), nearest first.

        A filtered HNSW scan collects `hnsw.ef_search` candidates BEFORE the shelf
        and book filters run; the index holds the whole platform's library, so most
        of those are books this campus does not use, and the search comes back short
        or empty. pgvector 0.8's
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
