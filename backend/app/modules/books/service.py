"""Textbook library business rules -- who may change which book, and upload rules.

ONE LIBRARY, EVERY SCHOOL'S SHELF
    A book is uploaded once for the whole platform. The school that uploads it
    OWNS it -- only its people change the chapters, files and details -- and every
    school, the owner included, uses it through its own SHELF ENTRY (`SchoolBook`):
    the class and subject it is filed under on that campus. Reading a book, its
    pages or its passages needs an entry on the caller's campus; without one the
    book is a 404, exactly as before the library was shared.

    `library` lists the whole library to choose from; `add_from_library` files a
    book there under one of the caller's classes. A new book whose title,
    publisher, version and grade are already in the library is refused
    (`DUPLICATE_BOOK`, with the existing book's id to add instead) -- see
    `catalog.py` for what counts as the same.

    Removing a book takes it off the caller's shelf. The content goes too only
    when the OWNER removes it and no other campus, anywhere, still uses it.

AUTHORISATION SHAPE
    book:read     see the campus's books, their pages, and search them; browse
                  the library
    book:write    create books and add library books; change the books YOU
                  uploaded (chapters, uploads, processing) and the shelf entries
                  you added (class, subject, removal)
    book:manage   change or remove any of the campus's books -- the content only
                  of books the campus uploaded

    `router.py` resolves the permissions into flags; this service applies the
    ownership half, so it stays callable without HTTP.

WHAT A BOUND TEACHER SEES (`Caller.teacher_id`, see `academics/teaching_scope.py`)
    A book belongs to a class and optionally a subject, so it is bounded like the
    curriculum: a teacher sees the books of the subjects they answer for, plus the
    subject-less books of classes they are assigned to. Any other book -- its
    chapters, pages, files, search -- is a 404, and a book can only be filed under
    a class (and subject) the teacher could then see. None for an unbound caller.
    The filing is the campus's own (the shelf entry), so a library book is bounded
    by where THIS campus filed it, not by where its uploader did.

ASK THE LIBRARY (`search_library`, `ask`)
    Retrieval is hybrid: pgvector ranks chunks by MEANING, full-text search by
    WORDS, and reciprocal-rank fusion merges the two lists. Meaning alone misses
    exact terms ("Exercise 3.4", "F = ma"); words alone miss a question phrased
    unlike the book. A chunk whose vector is still in a batch is found by its
    words already. `ask` then hands the top passages to the answer model, which
    must answer from them or say the books do not cover it. Both run inside the
    caller's teaching scope, so a teacher can only be answered from books they see.

READING A NEW BOOK'S FRONT MATTER (`scan`)
    Photos or a PDF of the cover, title, imprint and contents pages go to the
    agent's front-matter reader, and its reading comes back as a draft for the
    "Add a book" form. Nothing is stored -- not the files, not the reading -- and
    the class and subject it may suggest are only those the caller could file the
    book under. Only the first `_SCAN_MAX_PAGES` pages are read.

UPLOAD RULES
    * The file type is decided from the bytes (`ingest.sniff_kind`), never from the
      filename or the browser's content type.
    * The same file cannot be uploaded to one chapter twice (sha256), and a chapter
      is capped at `BOOKS_MAX_PAGES_PER_CHAPTER` pages.
    * Any change to a chapter's files DROPS its pages and vectors at once. Indexed
      text therefore always describes the files currently uploaded -- never a
      mixture of an old upload and a new one.
    * Nothing changes while a worker holds the chapter (`processing`): the worker
      read the file list when it claimed it, and would overwrite the change.
"""

from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditAction, record_audit
from app.common.schemas import Page, PageParams
from app.common.storage import LocalFileStorage
from app.core.config import Settings
from app.core.exceptions import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.core.logging import get_logger
from app.modules.academics.models import SchoolClass, Subject
from app.modules.books.agent import (
    Answerer,
    FrontMatterChapter,
    FrontMatterReader,
    FrontPage,
    Passage,
)
from app.modules.books.catalog import catalog_key, grade_key
from app.modules.books.ingest import (
    UnsupportedFileError,
    count_pages,
    sniff_kind,
    split_file,
    text_layer_is_usable,
)
from app.modules.books.models import (
    Book,
    BookChapter,
    BookChapterFile,
    BookPage,
    ChapterStatus,
    FileKind,
    SchoolBook,
)
from app.modules.books.repository import (
    BookLookupRepository,
    BookRepository,
    ChapterFileRepository,
    ChapterRepository,
    ChunkRepository,
    LibraryScope,
    PageRepository,
    ShelfRepository,
)
from app.modules.books.schemas import (
    AskRequest,
    BookCreate,
    BookDetail,
    BookRead,
    BookScan,
    BookSearchHit,
    BookUpdate,
    ChapterFileRead,
    ChapterInput,
    ChapterRead,
    ChapterReport,
    ChapterUpdate,
    LibraryAnswer,
    LibraryBook,
    LibraryHit,
    PageRead,
    ShelfInput,
)

logger = get_logger(__name__)

_MAX_FILES_PER_UPLOAD = 60
_SCAN_MAX_FILES = 10
_SCAN_MAX_PAGES = 16
"""Pages one front-matter reading looks at. A textbook's cover, imprint and
contents are nearly always within its first sixteen; more only adds cost."""

Embedder = Callable[[str], Awaitable[list[float]]]

_RRF_K = 60
"""Reciprocal-rank fusion constant: a chunk scores 1/(k + rank) in each ranking.
60 is the value from the original paper and the usual default; it keeps one
ranking's top hit from drowning out a chunk both rankings agree on."""
_CANDIDATES = 30
"""Chunks taken from EACH ranking before fusion."""
_NOT_COVERED = "The uploaded books do not cover this question."


@dataclass(frozen=True, slots=True)
class Caller:
    user_id: UUID
    may_write: bool
    may_manage: bool
    teacher_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class IncomingFile:
    filename: str
    data: bytes


def book_prefix(book: Book) -> str:
    return f"{book.organization_id}/{book.school_id}/books/{book.id}"


def chapter_prefix(book: Book, chapter_id: UUID) -> str:
    return f"{book_prefix(book)}/chapters/{chapter_id}"


class BookService:
    def __init__(
        self, session: AsyncSession, storage: LocalFileStorage, settings: Settings
    ) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings
        self.books = BookRepository(session)
        self.shelf = ShelfRepository(session)
        self.chapters = ChapterRepository(session)
        self.files = ChapterFileRepository(session)
        self.pages = PageRepository(session)
        self.chunks = ChunkRepository(session)
        self.lookup = BookLookupRepository(session)

    # -- books --------------------------------------------------------------

    async def list_books(
        self,
        caller: Caller,
        *,
        params: PageParams,
        class_id: UUID | None,
        subject_id: UUID | None,
        search: str | None = None,
    ) -> Page[BookRead]:
        rows, total = await self.shelf.list_with_counts(
            params=params,
            class_id=class_id,
            subject_id=subject_id,
            teacher_id=caller.teacher_id,
            search=search,
        )
        names = await self._names([(e, b) for e, b, _, _ in rows])
        items = [
            self._book_read(entry, book, chapters, ready, caller, names)
            for entry, book, chapters, ready in rows
        ]
        return Page.create(items, total, params)

    async def detail(self, book_id: UUID, caller: Caller) -> BookDetail:
        entry, book = await self._shelved_or_404(book_id, teacher_id=caller.teacher_id)
        chapters = list(await self.chapters.for_book(book.id))
        files = await self.files.for_chapters(c.id for c in chapters)
        names = await self._names([(entry, book)])
        ready = sum(c.status is ChapterStatus.READY for c in chapters)
        base = self._book_read(entry, book, len(chapters), ready, caller, names)
        owned = _owns(entry, book)
        return BookDetail(
            **base.model_dump(),
            chapters=[self._chapter_read(c, files.get(c.id, []), owned=owned) for c in chapters],
        )

    async def library(
        self,
        *,
        params: PageParams,
        search: str | None,
        grade: str | None,
        subject: str | None,
    ) -> Page[LibraryBook]:
        """One page of the whole platform's library. `grade` is a class name as
        any school writes it ("Class 5", "Grade V"), matched by `catalog.grade_key`."""
        rows, total = await self.books.library_page(
            params=params,
            search=search,
            grade_key=grade_key(grade) if grade else None,
            subject=subject,
        )
        ids = [book.id for book, _, _ in rows]
        shelved = await self.shelf.shelved(ids)
        schools = await self.shelf.schools_using(ids)
        items = [
            LibraryBook(
                id=book.id,
                title=book.title,
                publisher=book.publisher,
                version=book.version,
                grade=book.grade,
                subject=book.subject,
                chapter_count=chapters,
                ready_chapter_count=ready,
                school_count=schools.get(book.id, 0),
                on_shelf=book.id in shelved,
            )
            for book, chapters, ready in rows
        ]
        return Page.create(items, total, params)

    async def library_subjects(self, grade: str | None) -> list[str]:
        return await self.books.library_subjects(grade_key(grade) if grade else None)

    async def add_from_library(
        self, book_id: UUID, payload: ShelfInput, caller: Caller
    ) -> BookDetail:
        """File a library book under one of the caller's classes."""
        self._assert_may_create(caller)
        book = await self.books.get(book_id)
        if book is None:
            raise NotFoundError("Book not found.")
        school_class = await self._class_or_422(payload.class_id)
        await self._subject_or_422(payload.subject_id)
        await self._assert_in_scope(caller, school_class.id, payload.subject_id)
        if await self.shelf.on_campus(school_class.school_id, book.id) is not None:
            raise ConflictError(
                "This book is already in your school's books.", code="ALREADY_ON_SHELF"
            )
        entry = SchoolBook(
            book_id=book.id,
            class_id=school_class.id,
            subject_id=payload.subject_id,
            added_by_user_id=caller.user_id,
            organization_id=school_class.organization_id,
            school_id=school_class.school_id,
        )
        self.session.add(entry)
        await self.session.flush()
        await self._audit(entry, caller, AuditAction.BOOK_SHELVED, after=_entry_snapshot(entry))
        logger.info("book_added_from_library", book_id=str(book.id))
        return await self.detail(book.id, caller)

    async def create(self, payload: BookCreate, caller: Caller) -> BookDetail:
        self._assert_may_create(caller)
        school_class = await self._class_or_422(payload.class_id)
        subject = await self._subject_or_422(payload.subject_id)
        await self._assert_in_scope(caller, school_class.id, payload.subject_id)
        key = catalog_key(payload.title, payload.publisher, payload.version, school_class.name)
        await self._assert_not_in_library(key, exclude=None)
        numbers = [c.number for c in payload.chapters]
        if len(numbers) != len(set(numbers)):
            raise ValidationError(
                "Two chapters in the list have the same number.", code="DUPLICATE_CHAPTER_NUMBER"
            )

        book = Book(
            title=payload.title,
            publisher=payload.publisher,
            version=payload.version,
            grade=school_class.name,
            grade_key=grade_key(school_class.name),
            subject=subject.name if subject else None,
            catalog_key=key,
            created_by_user_id=caller.user_id,
            organization_id=school_class.organization_id,
            school_id=school_class.school_id,
        )
        self.session.add(book)
        await self.session.flush()
        self.session.add(
            SchoolBook(
                book_id=book.id,
                class_id=school_class.id,
                subject_id=payload.subject_id,
                added_by_user_id=caller.user_id,
                organization_id=school_class.organization_id,
                school_id=school_class.school_id,
            )
        )
        for chapter in payload.chapters:
            self.session.add(self._new_chapter(book, chapter))
        await self.session.flush()
        await self._audit(
            book, caller, AuditAction.BOOK_CREATED, after=_book_snapshot(book, school_class.id)
        )
        logger.info("book_created", book_id=str(book.id), chapters=len(payload.chapters))
        return await self.detail(book.id, caller)

    async def scan(
        self, incoming: Sequence[IncomingFile], reader: FrontMatterReader, caller: Caller
    ) -> BookScan:
        """A new book's details read off its cover and contents pages -- a draft for
        the teacher to check, nothing saved."""
        self._assert_may_create(caller)
        if not incoming:
            raise ValidationError(
                "Choose photos or a PDF of the book's cover and contents pages.", code="NO_FILES"
            )
        if len(incoming) > _SCAN_MAX_FILES:
            raise ValidationError(
                f"Upload at most {_SCAN_MAX_FILES} files: the cover and the contents pages.",
                code="TOO_MANY_FILES",
            )
        max_bytes = self.settings.BOOKS_MAX_UPLOAD_MB * 1024 * 1024
        pages: list[FrontPage] = []
        skipped = False
        for item in incoming:
            if len(item.data) > max_bytes:
                raise ValidationError(
                    f"{item.filename} is larger than {self.settings.BOOKS_MAX_UPLOAD_MB} MB.",
                    code="FILE_TOO_LARGE",
                )
            room = _SCAN_MAX_PAGES - len(pages)
            try:
                kind, _ = sniff_kind(item.data)
                total = await asyncio.to_thread(count_pages, item.data, kind)
                raw = (
                    await asyncio.to_thread(split_file, item.data, kind, max_pages=room)
                    if room > 0
                    else []
                )
            except UnsupportedFileError as exc:
                raise ValidationError(f"{item.filename}: {exc}", code="UNSUPPORTED_FILE") from exc
            skipped = skipped or total > len(raw)
            pages.extend(
                FrontPage(
                    p.image,
                    p.image_type,
                    p.text_layer if text_layer_is_usable(p.text_layer) else "",
                )
                for p in raw
            )

        classes, curriculum = await self.lookup.filing_options(caller.teacher_id)
        class_ids = _ids_by_unique_name(classes)
        reading = await reader.read_front_matter(
            pages, list(class_ids), list(dict.fromkeys(name for _, _, name in curriculum))
        )
        class_id = class_ids.get(reading.class_choice)
        subject_id = next(
            (
                sid
                for cid, sid, name in curriculum
                if cid == class_id and name == reading.subject_choice
            ),
            None,
        )
        title = _scanned_text(reading.title, 200)
        chapters = _scanned_chapters(reading.chapters)
        if title is None and not chapters:
            raise ValidationError(
                "No title or chapter list could be read from these pages. Upload clear "
                "photos of the book's cover and its contents page.",
                code="NOTHING_READ",
            )
        notes = []
        if skipped:
            notes.append(
                f"Only the first {_SCAN_MAX_PAGES} pages were read. If the contents "
                "continue after them, add the missing chapters yourself."
            )
        logger.info(
            "book_scanned",
            pages=len(pages),
            chapters=len(chapters),
            input_tokens=reader.usage.input_tokens,
            output_tokens=reader.usage.output_tokens,
        )
        return BookScan(
            title=title,
            publisher=_scanned_text(reading.publisher, 200),
            version=_scanned_text(reading.version, 60),
            class_id=class_id,
            class_printed=_scanned_text(reading.class_printed, 80),
            subject_id=subject_id,
            subject_printed=_scanned_text(reading.subject_printed, 120),
            chapters=chapters,
            pages_read=len(pages),
            notes=notes,
        )

    async def update(self, book_id: UUID, payload: BookUpdate, caller: Caller) -> BookDetail:
        """The owner changes the book's details and its own filing; any other campus
        changes only where it files the book."""
        entry, book = await self._shelved_or_404(book_id, teacher_id=caller.teacher_id)
        owned = _owns(entry, book)
        if owned:
            self._assert_may_edit(book, caller)
        else:
            details = (payload.title, payload.publisher, payload.version)
            if any(
                new is not None and new != old
                for new, old in zip(details, _details(book), strict=True)
            ):
                raise AuthorizationError(
                    "Only the school that uploaded this book can change its title, "
                    "publisher or version.",
                    code="BOOK_NOT_OWNED",
                )
            self._assert_may_refile(entry, caller)

        before = {**_book_snapshot(book, entry.class_id), **_entry_snapshot(entry)}
        if payload.class_id is not None and payload.class_id != entry.class_id:
            school_class = await self.lookup.school_class(payload.class_id)
            if school_class is None or school_class.school_id != entry.school_id:
                raise ValidationError(
                    "That class does not exist on this campus.", code="CLASS_NOT_FOUND"
                )
            entry.class_id = school_class.id
        if payload.clear_subject:
            entry.subject_id = None
        elif payload.subject_id is not None:
            await self._subject_or_422(payload.subject_id)
            entry.subject_id = payload.subject_id
        # Re-filing must not move a book out of the teacher's own sight.
        await self._assert_in_scope(caller, entry.class_id, entry.subject_id)

        if owned:
            old_key = catalog_key(*_details(book), book.grade)
            classes = await self.lookup.class_names([entry.class_id])
            subjects = await self.lookup.subject_names([entry.subject_id])
            book.title = payload.title or book.title
            book.publisher = payload.publisher or book.publisher
            book.version = payload.version or book.version
            book.grade = classes.get(entry.class_id, book.grade)
            book.grade_key = grade_key(book.grade)
            book.subject = subjects.get(entry.subject_id) if entry.subject_id else None
            new_key = catalog_key(*_details(book), book.grade)
            # A book that already duplicated another when the library became shared
            # has no key; it keeps none until its details actually change.
            if new_key != old_key:
                await self._assert_not_in_library(new_key, exclude=book.id)
                book.catalog_key = new_key
        await self.session.flush()
        await self._audit(
            book if owned else entry,
            caller,
            AuditAction.BOOK_UPDATED,
            before=before,
            after={**_book_snapshot(book, entry.class_id), **_entry_snapshot(entry)},
        )
        return await self.detail(book.id, caller)

    async def delete(self, book_id: UUID, caller: Caller) -> None:
        """Take the book off the caller's campus. Its content goes too when the
        campus uploaded it and no campus anywhere still uses it."""
        entry, book = await self._shelved_or_404(book_id, teacher_id=caller.teacher_id)
        owned = _owns(entry, book)
        if owned:
            self._assert_may_edit(book, caller)
        else:
            self._assert_may_refile(entry, caller)
        await self.session.delete(entry)
        await self.session.flush()

        if owned:
            # Locked before counting: adding a book to a shelf takes a key-share
            # lock on it, so no campus can add it between the count and the delete.
            await self.books.lock(book.id)
            if not await self.shelf.schools_using([book.id]):
                snapshot = _book_snapshot(book, entry.class_id)
                prefix = book_prefix(book)
                await self._audit(book, caller, AuditAction.BOOK_DELETED, before=snapshot)
                await self.session.delete(book)
                await self.session.flush()
                await self.storage.delete_prefix(prefix)
                return
        await self._audit(entry, caller, AuditAction.BOOK_UNSHELVED, before=_entry_snapshot(entry))

    # -- chapters -----------------------------------------------------------

    async def add_chapter(
        self, book_id: UUID, payload: ChapterInput, caller: Caller
    ) -> ChapterRead:
        book = await self._editable_book(book_id, caller)
        if await self.chapters.by_number(book.id, payload.number) is not None:
            raise ConflictError(
                f"Chapter {payload.number} is already in the list.", code="DUPLICATE_CHAPTER_NUMBER"
            )
        chapter = self._new_chapter(book, payload)
        self.session.add(chapter)
        await self.session.flush()
        await self._audit(
            book,
            caller,
            AuditAction.BOOK_CHAPTER_CREATED,
            after={"chapter_id": str(chapter.id), "number": chapter.number, "title": chapter.title},
        )
        return await self._chapter_fresh(chapter)

    async def update_chapter(
        self, book_id: UUID, chapter_id: UUID, payload: ChapterUpdate, caller: Caller
    ) -> ChapterRead:
        book = await self._editable_book(book_id, caller)
        chapter = await self._chapter_or_404(book, chapter_id, lock=True)
        before = {"number": chapter.number, "title": chapter.title}
        if payload.number is not None and payload.number != chapter.number:
            if await self.chapters.by_number(book.id, payload.number) is not None:
                raise ConflictError(
                    f"Chapter {payload.number} is already in the list.",
                    code="DUPLICATE_CHAPTER_NUMBER",
                )
            chapter.number = payload.number
        if payload.title is not None:
            chapter.title = payload.title
        await self.session.flush()
        await self._audit(
            book,
            caller,
            AuditAction.BOOK_CHAPTER_UPDATED,
            before=before,
            after={"chapter_id": str(chapter.id), "number": chapter.number, "title": chapter.title},
        )
        return await self._chapter_fresh(chapter)

    async def delete_chapter(self, book_id: UUID, chapter_id: UUID, caller: Caller) -> None:
        book = await self._editable_book(book_id, caller)
        chapter = await self._chapter_or_404(book, chapter_id, lock=True)
        await self._audit(
            book,
            caller,
            AuditAction.BOOK_CHAPTER_DELETED,
            before={
                "chapter_id": str(chapter.id),
                "number": chapter.number,
                "title": chapter.title,
            },
        )
        await self.session.delete(chapter)
        await self.session.flush()
        await self.storage.delete_prefix(chapter_prefix(book, chapter.id))

    # -- uploads ------------------------------------------------------------

    async def upload(
        self,
        book_id: UUID,
        chapter_id: UUID,
        incoming: Sequence[IncomingFile],
        caller: Caller,
        *,
        process: bool,
    ) -> ChapterRead:
        if not incoming:
            raise ValidationError("Choose at least one file to upload.", code="NO_FILES")
        if len(incoming) > _MAX_FILES_PER_UPLOAD:
            raise ValidationError(
                f"Upload at most {_MAX_FILES_PER_UPLOAD} files at a time.", code="TOO_MANY_FILES"
            )
        book = await self._editable_book(book_id, caller)
        chapter = await self._chapter_or_404(book, chapter_id, lock=True)
        self._assert_not_processing(chapter)

        max_bytes = self.settings.BOOKS_MAX_UPLOAD_MB * 1024 * 1024
        seen = await self.files.existing_hashes(chapter.id)
        prepared: list[tuple[IncomingFile, FileKind, str, str, int]] = []
        for item in incoming:
            if len(item.data) > max_bytes:
                raise ValidationError(
                    f"{item.filename} is larger than {self.settings.BOOKS_MAX_UPLOAD_MB} MB.",
                    code="FILE_TOO_LARGE",
                )
            try:
                kind, content_type = sniff_kind(item.data)
                pages = await asyncio.to_thread(count_pages, item.data, kind)
            except UnsupportedFileError as exc:
                raise ValidationError(f"{item.filename}: {exc}", code="UNSUPPORTED_FILE") from exc
            digest = hashlib.sha256(item.data).hexdigest()
            if digest in seen:
                raise ConflictError(
                    f"{item.filename} has already been uploaded to this chapter.",
                    code="DUPLICATE_FILE",
                )
            seen.add(digest)
            prepared.append((item, kind, content_type, digest, pages))

        existing = await self.files.for_chapters([chapter.id])
        total_pages = sum(f.page_count for f in existing.get(chapter.id, [])) + sum(
            p[4] for p in prepared
        )
        if total_pages > self.settings.BOOKS_MAX_PAGES_PER_CHAPTER:
            raise ValidationError(
                f"A chapter can have at most {self.settings.BOOKS_MAX_PAGES_PER_CHAPTER} pages; "
                f"this upload would make {total_pages}.",
                code="TOO_MANY_PAGES",
            )

        order = await self.files.next_sort_order(chapter.id)
        names: list[str] = []
        for offset, (item, kind, content_type, digest, pages) in enumerate(prepared):
            file_id = uuid4()
            extension = {"application/pdf": "pdf", "image/jpeg": "jpg", "image/png": "png"}.get(
                content_type, "webp"
            )
            key = f"{chapter_prefix(book, chapter.id)}/files/{file_id}.{extension}"
            await self.storage.put(key, item.data)
            self.session.add(
                BookChapterFile(
                    id=file_id,
                    chapter_id=chapter.id,
                    kind=kind,
                    original_name=Path(item.filename).name[:255] or f"upload.{extension}",
                    content_type=content_type,
                    size_bytes=len(item.data),
                    sha256=digest,
                    storage_key=key,
                    page_count=pages,
                    sort_order=order + offset,
                    uploaded_by_user_id=caller.user_id,
                    organization_id=book.organization_id,
                    school_id=book.school_id,
                )
            )
            names.append(item.filename)

        await self._files_changed(book, chapter, queue=process)
        await self._audit(
            book,
            caller,
            AuditAction.BOOK_CHAPTER_FILES_UPLOADED,
            after={"chapter_id": str(chapter.id), "files": names, "pages": total_pages},
        )
        return await self._chapter_fresh(chapter)

    async def delete_file(
        self, book_id: UUID, chapter_id: UUID, file_id: UUID, caller: Caller
    ) -> ChapterRead:
        book = await self._editable_book(book_id, caller)
        chapter = await self._chapter_or_404(book, chapter_id, lock=True)
        self._assert_not_processing(chapter)
        file = await self.files.get(file_id)
        if file is None or file.chapter_id != chapter.id:
            raise NotFoundError("File not found.")
        key, name = file.storage_key, file.original_name
        await self.session.delete(file)
        await self.session.flush()
        await self._files_changed(book, chapter, queue=False)
        await self._audit(
            book,
            caller,
            AuditAction.BOOK_CHAPTER_FILE_DELETED,
            before={"chapter_id": str(chapter.id), "file": name},
        )
        await self.storage.delete(key)
        return await self._chapter_fresh(chapter)

    async def file_path(
        self, book_id: UUID, file_id: UUID, *, teacher_id: UUID | None = None
    ) -> tuple[Path, str, str]:
        book = await self._book_or_404(book_id, teacher_id=teacher_id)
        file = await self.files.get(file_id)
        if file is None:
            raise NotFoundError("File not found.")
        chapter = await self.chapters.get(file.chapter_id)
        if chapter is None or chapter.book_id != book.id:
            raise NotFoundError("File not found.")
        return self.storage.path(file.storage_key), file.content_type, file.original_name

    # -- processing ---------------------------------------------------------

    async def queue(self, book_id: UUID, chapter_id: UUID, caller: Caller) -> ChapterRead:
        book = await self._editable_book(book_id, caller)
        chapter = await self._chapter_or_404(book, chapter_id, lock=True)
        self._assert_not_processing(chapter)
        if chapter.status is ChapterStatus.EMPTY:
            raise ValidationError("Upload the chapter's pages first.", code="NO_FILES")
        chapter.status = ChapterStatus.QUEUED
        chapter.error = None
        await self.session.flush()
        await self._audit(
            book,
            caller,
            AuditAction.BOOK_CHAPTER_QUEUED,
            after={"chapter_id": str(chapter.id), "number": chapter.number},
        )
        return await self._chapter_fresh(chapter)

    async def accept(self, book_id: UUID, chapter_id: UUID, caller: Caller) -> ChapterRead:
        """A teacher confirms a NEEDS_REVIEW chapter is right as it is."""
        book = await self._editable_book(book_id, caller)
        chapter = await self._chapter_or_404(book, chapter_id, lock=True)
        if chapter.status is not ChapterStatus.NEEDS_REVIEW:
            raise ConflictError(
                "Only a chapter waiting for review can be accepted.", code="NOT_IN_REVIEW"
            )
        names = await self.lookup.user_names([caller.user_id])
        chapter.status = ChapterStatus.READY
        chapter.report = {**(chapter.report or {}), "accepted_by_name": names.get(caller.user_id)}
        await self.session.flush()
        await self._audit(
            book,
            caller,
            AuditAction.BOOK_CHAPTER_ACCEPTED,
            after={
                "chapter_id": str(chapter.id),
                "issues": [i.get("code") for i in (chapter.report or {}).get("issues", [])],
            },
        )
        return await self._chapter_fresh(chapter)

    # -- reading ------------------------------------------------------------

    async def chapter_pages(
        self, book_id: UUID, chapter_id: UUID, *, teacher_id: UUID | None = None
    ) -> list[PageRead]:
        book = await self._book_or_404(book_id, teacher_id=teacher_id)
        chapter = await self._chapter_or_404(book, chapter_id)
        return [
            PageRead(
                id=p.id,
                position=p.position,
                printed_page_number=p.printed_page_number,
                placement=p.placement,
                method=p.method,
                text=p.text,
                has_image=p.image_key is not None,
                file_id=p.file_id,
                source_index=p.source_index,
                detected_chapter_number=p.detected_chapter_number,
                chapter_confidence=p.chapter_confidence,
                opens_chapter=p.opens_chapter,
            )
            for p in await self.pages.for_chapter(chapter.id)
        ]

    async def page_image(
        self, book_id: UUID, page_id: UUID, *, teacher_id: UUID | None = None
    ) -> tuple[Path, str]:
        book = await self._book_or_404(book_id, teacher_id=teacher_id)
        page: BookPage | None = await self.pages.get(page_id)
        if page is None or page.image_key is None:
            raise NotFoundError("Page image not found.")
        chapter = await self.chapters.get(page.chapter_id)
        if chapter is None or chapter.book_id != book.id:
            raise NotFoundError("Page image not found.")
        media = "image/png" if page.image_key.endswith(".png") else "image/jpeg"
        return self.storage.path(page.image_key), media

    async def search(
        self,
        book_id: UUID,
        query: str,
        embed: Embedder,
        *,
        chapter_id: UUID | None,
        limit: int,
        teacher_id: UUID | None = None,
    ) -> list[BookSearchHit]:
        book = await self._book_or_404(book_id, teacher_id=teacher_id)
        vector = await embed(query)
        rows = await self.chunks.search(book.id, vector, chapter_id=chapter_id, limit=limit)
        return [
            BookSearchHit(
                chunk_id=chunk.id,
                chapter_id=chapter.id,
                chapter_number=chapter.number,
                chapter_title=chapter.title,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                printed_start=chunk.printed_start,
                printed_end=chunk.printed_end,
                content=chunk.content,
                score=round(max(0.0, 1.0 - distance), 4),
            )
            for chunk, chapter, distance in rows
        ]

    async def search_library(
        self, query: str, embed: Embedder, scope: LibraryScope, *, limit: int
    ) -> list[LibraryHit]:
        """The best passages for `query` across every book `scope` covers."""
        if scope.book_id is not None:
            await self._book_or_404(scope.book_id, teacher_id=scope.teacher_id)
        # The embedding is a network call: the keyword query runs meanwhile.
        vector, by_words = await asyncio.gather(
            embed(query), self.chunks.keyword_ids(query, scope, limit=_CANDIDATES)
        )
        by_meaning = await self.chunks.nearest_ids(vector, scope, limit=_CANDIDATES)

        scores: dict[UUID, float] = {}
        for ranking in (by_meaning, by_words):
            for rank, chunk_id in enumerate(ranking, start=1):
                scores[chunk_id] = scores.get(chunk_id, 0.0) + 1.0 / (_RRF_K + rank)
        top = sorted(scores, key=lambda c: scores[c], reverse=True)[:limit]
        rows = await self.chunks.with_sources(top)
        meaning, words = set(by_meaning), set(by_words)
        best = 2.0 / (_RRF_K + 1)  # first in both rankings

        hits: list[LibraryHit] = []
        for chunk_id in top:
            if chunk_id not in rows:
                continue  # deleted between the two queries
            chunk, chapter, book = rows[chunk_id]
            hits.append(
                LibraryHit(
                    chunk_id=chunk.id,
                    book_id=book.id,
                    book_title=book.title,
                    chapter_id=chapter.id,
                    chapter_number=chapter.number,
                    chapter_title=chapter.title,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    printed_start=chunk.printed_start,
                    printed_end=chunk.printed_end,
                    content=chunk.content,
                    score=round(scores[chunk_id] / best, 4),
                    matched_by=(
                        "both"
                        if chunk_id in meaning and chunk_id in words
                        else "meaning"
                        if chunk_id in meaning
                        else "keywords"
                    ),
                )
            )
        return hits

    async def ask(
        self, payload: AskRequest, embed: Embedder, answerer: Answerer, *, teacher_id: UUID | None
    ) -> LibraryAnswer:
        """An answer to `payload.question` written from the library's own passages."""
        scope = LibraryScope(
            class_id=payload.class_id,
            subject_id=payload.subject_id,
            book_id=payload.book_id,
            chapter_id=payload.chapter_id,
            teacher_id=teacher_id,
        )
        hits = await self.search_library(
            payload.question, embed, scope, limit=self.settings.BOOKS_ASK_PASSAGES
        )
        if not hits:
            return LibraryAnswer(found=False, answer=_NOT_COVERED, sources=[], cited=[])
        passages = [
            Passage(number=i, source=_source_label(hit), text=hit.content)
            for i, hit in enumerate(hits, start=1)
        ]
        result = await answerer.answer_question(payload.question, passages)
        logger.info(
            "book_question_answered",
            found=result.found,
            passages=len(passages),
            cited=len(result.citations),
            input_tokens=answerer.usage.input_tokens,
            output_tokens=answerer.usage.output_tokens,
        )
        # An answer that cites nothing is not grounded in the books. A "not
        # covered" reply keeps the model's sentence: it is in the question's language.
        found = result.found and bool(result.citations)
        ungrounded = result.found and not found
        return LibraryAnswer(
            found=found,
            answer=_NOT_COVERED if ungrounded or not result.answer else result.answer,
            sources=hits,
            cited=result.citations if found else [],
        )

    # -- internals ----------------------------------------------------------

    async def _files_changed(self, book: Book, chapter: BookChapter, *, queue: bool) -> None:
        await self.session.flush()
        await self.pages.clear_chapter(chapter.id)
        remaining = await self.files.for_chapters([chapter.id])
        has_files = bool(remaining.get(chapter.id))
        if not has_files:
            chapter.status = ChapterStatus.EMPTY
        else:
            chapter.status = ChapterStatus.QUEUED if queue else ChapterStatus.UPLOADED
        chapter.page_count = 0
        chapter.report = None
        chapter.error = None
        chapter.processed_at = None
        await self.session.flush()
        await self.storage.delete_prefix(f"{chapter_prefix(book, chapter.id)}/pages")

    async def _chapter_fresh(self, chapter: BookChapter) -> ChapterRead:
        """Re-read the row: `updated_at` and the other server-maintained columns are
        expired by the flush, and touching an expired attribute in async SQLAlchemy
        is an implicit blocking load."""
        await self.session.refresh(chapter)
        files = await self.files.for_chapters([chapter.id])
        return self._chapter_read(chapter, files.get(chapter.id, []))

    async def _book_or_404(self, book_id: UUID, *, teacher_id: UUID | None = None) -> Book:
        return (await self._shelved_or_404(book_id, teacher_id=teacher_id))[1]

    async def _shelved_or_404(
        self, book_id: UUID, *, teacher_id: UUID | None = None
    ) -> tuple[SchoolBook, Book]:
        """The caller's shelf entry for a book, and the book. A library book the
        campus has not added is not found -- for reading it, `library` is the way."""
        entry = await self.shelf.entry(book_id)
        if entry is None or (
            teacher_id is not None and not await self.shelf.visible(entry.id, teacher_id)
        ):
            raise NotFoundError("Book not found.")
        book = await self.books.get(book_id)
        if book is None:
            raise NotFoundError("Book not found.")
        return entry, book

    async def _class_or_422(self, class_id: UUID) -> SchoolClass:
        school_class = await self.lookup.school_class(class_id)
        if school_class is None:
            raise ValidationError(
                "That class does not exist on this campus.", code="CLASS_NOT_FOUND"
            )
        return school_class

    async def _subject_or_422(self, subject_id: UUID | None) -> Subject | None:
        if subject_id is None:
            return None
        subject = await self.lookup.subject(subject_id)
        if subject is None:
            raise ValidationError("That subject does not exist.", code="SUBJECT_NOT_FOUND")
        return subject

    async def _assert_in_scope(
        self, caller: Caller, class_id: UUID, subject_id: UUID | None
    ) -> None:
        """A bound teacher files books only where they could then see them.

        Refused with the same codes as a class or subject that does not exist:
        to this caller, an untaught one does not.
        """
        if caller.teacher_id is None:
            return
        if not await self.lookup.teaches_class(caller.teacher_id, class_id):
            raise ValidationError(
                "That class does not exist on this campus.", code="CLASS_NOT_FOUND"
            )
        if subject_id is not None and not await self.lookup.teaches_subject(
            caller.teacher_id, class_id, subject_id
        ):
            raise ValidationError("That subject does not exist.", code="SUBJECT_NOT_FOUND")

    async def _editable_book(self, book_id: UUID, caller: Caller) -> Book:
        entry, book = await self._shelved_or_404(book_id, teacher_id=caller.teacher_id)
        if not _owns(entry, book):
            raise AuthorizationError(
                "Only the school that uploaded this book can change its chapters and pages.",
                code="BOOK_NOT_OWNED",
            )
        self._assert_may_edit(book, caller)
        return book

    async def _chapter_or_404(
        self, book: Book, chapter_id: UUID, *, lock: bool = False
    ) -> BookChapter:
        if lock:
            chapter = await self.chapters.for_book_locked(book.id, chapter_id)
        else:
            chapter = await self.chapters.get(chapter_id)
            if chapter is not None and chapter.book_id != book.id:
                chapter = None
        if chapter is None:
            raise NotFoundError("Chapter not found.")
        return chapter

    async def _assert_not_in_library(self, key: str, *, exclude: UUID | None) -> None:
        """One copy of a book on the platform. The refusal names the copy there is,
        so the caller can add it instead (or open it, if the campus has it)."""
        existing = await self.books.find_duplicate(key, exclude=exclude)
        if existing is None:
            return
        on_shelf = bool(await self.shelf.shelved([existing.id]))
        raise ConflictError(
            f"{existing.title} ({existing.publisher}, {existing.version}, {existing.grade}) "
            + (
                "is already in your school's books."
                if on_shelf
                else "is already in the library, uploaded by another school. "
                "Add it to your class from the library instead of uploading it again."
            ),
            code="DUPLICATE_BOOK",
            details={"book_id": str(existing.id), "on_shelf": on_shelf},
        )

    @staticmethod
    def _assert_not_processing(chapter: BookChapter) -> None:
        if chapter.status is ChapterStatus.READING:
            raise ConflictError(
                "OpenAI is still reading this chapter's pages (this can take up to 24 hours). "
                "Try again when it finishes.",
                code="CHAPTER_PROCESSING",
            )
        if chapter.status is ChapterStatus.PROCESSING:
            raise ConflictError(
                "The agent is reading this chapter right now. Try again when it finishes.",
                code="CHAPTER_PROCESSING",
            )

    @staticmethod
    def _assert_may_create(caller: Caller) -> None:
        if not (caller.may_write or caller.may_manage):
            raise AuthorizationError(
                "You do not have permission to upload books.", code="FORBIDDEN"
            )

    @staticmethod
    def _may_edit(book: Book, caller: Caller) -> bool:
        """Content rights, for a book the caller's campus owns."""
        if caller.may_manage:
            return True
        return caller.may_write and book.created_by_user_id == caller.user_id

    @staticmethod
    def _may_refile(entry: SchoolBook, caller: Caller) -> bool:
        """Shelf rights: change the class a library book is filed under, or remove it."""
        if caller.may_manage:
            return True
        return caller.may_write and entry.added_by_user_id == caller.user_id

    def _assert_may_edit(self, book: Book, caller: Caller) -> None:
        if not self._may_edit(book, caller):
            raise AuthorizationError(
                "You can only change books you uploaded.", code="BOOK_NOT_OWNED"
            )

    def _assert_may_refile(self, entry: SchoolBook, caller: Caller) -> None:
        if not self._may_refile(entry, caller):
            raise AuthorizationError(
                "You can only change library books you added.", code="BOOK_NOT_OWNED"
            )

    @staticmethod
    def _new_chapter(book: Book, chapter: ChapterInput) -> BookChapter:
        return BookChapter(
            book_id=book.id,
            number=chapter.number,
            title=chapter.title,
            status=ChapterStatus.EMPTY,
            page_count=0,
            attempts=0,
            input_tokens=0,
            output_tokens=0,
            organization_id=book.organization_id,
            school_id=book.school_id,
        )

    async def _names(self, rows: Sequence[tuple[SchoolBook, Book]]) -> _Names:
        return _Names(
            classes=await self.lookup.class_names(e.class_id for e, _ in rows),
            subjects=await self.lookup.subject_names(e.subject_id for e, _ in rows),
            # Another school's uploader is not this campus's business.
            users=await self.lookup.user_names(
                b.created_by_user_id for e, b in rows if _owns(e, b)
            ),
            schools=await self.shelf.schools_using(b.id for _, b in rows),
        )

    def _book_read(
        self,
        entry: SchoolBook,
        book: Book,
        total: int,
        ready: int,
        caller: Caller,
        names: _Names,
    ) -> BookRead:
        owned = _owns(entry, book)
        return BookRead(
            id=book.id,
            title=book.title,
            publisher=book.publisher,
            version=book.version,
            grade=book.grade,
            class_id=entry.class_id,
            class_name=names.classes.get(entry.class_id, "?"),
            subject_id=entry.subject_id,
            subject_name=names.subjects.get(entry.subject_id) if entry.subject_id else None,
            chapter_count=total,
            ready_chapter_count=ready,
            created_by_name=(
                names.users.get(book.created_by_user_id)
                if owned and book.created_by_user_id
                else None
            ),
            created_at=entry.created_at,
            can_edit=owned and self._may_edit(book, caller),
            can_remove=self._may_edit(book, caller) if owned else self._may_refile(entry, caller),
            from_library=not owned,
            school_count=names.schools.get(book.id, 0),
        )

    @staticmethod
    def _chapter_read(
        chapter: BookChapter, files: list[BookChapterFile], *, owned: bool = True
    ) -> ChapterRead:
        report = ChapterReport.model_validate(chapter.report) if chapter.report else None
        if report is not None and not owned:
            # The name of the uploader's teacher who accepted it stays with them.
            report.accepted_by_name = None
        return ChapterRead(
            id=chapter.id,
            number=chapter.number,
            title=chapter.title,
            status=chapter.status,
            page_count=chapter.page_count,
            files=[ChapterFileRead.model_validate(f, from_attributes=True) for f in files],
            report=report,
            indexing=chapter.embed_batch is not None
            and chapter.status in (ChapterStatus.READY, ChapterStatus.NEEDS_REVIEW),
            error=chapter.error,
            processed_at=chapter.processed_at,
            updated_at=chapter.updated_at,
        )

    async def _audit(
        self,
        target: Book | SchoolBook,
        caller: Caller,
        action: str,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        """Recorded in the organization of `target`: the book's for a change to the
        content (its owner's), the shelf entry's for a change to a campus's shelf."""
        await record_audit(
            self.session,
            organization_id=target.organization_id,
            school_id=target.school_id,
            actor_user_id=caller.user_id,
            action=action,
            entity_type="book",
            entity_id=target.id if isinstance(target, Book) else target.book_id,
            before=before,
            after=after,
        )


def _ids_by_unique_name(rows: Sequence[tuple[UUID, str]]) -> dict[str, UUID]:
    """Name -> id, leaving out a name two rows share: picking it would be a guess.
    (Class names are unique per campus, but not across an organization's campuses.)"""
    ids: dict[str, UUID] = {}
    shared: set[str] = set()
    for row_id, name in rows:
        if name in ids:
            shared.add(name)
        ids[name] = row_id
    return {name: row_id for name, row_id in ids.items() if name not in shared}


def _scanned_text(value: str | None, limit: int) -> str | None:
    """A read value trimmed to what `BookCreate` accepts; None when blank."""
    flat = " ".join((value or "").split())[:limit].strip()
    return flat or None


def _scanned_chapters(chapters: Sequence[FrontMatterChapter]) -> list[ChapterInput]:
    """The read chapter list made valid for `BookCreate`: titled, at most 200, and
    numbered 1-999 without repeats. A list whose printed numbers repeat (two parts
    that each restart at 1) or fall outside that range is renumbered in order."""
    titled = [
        (c.number, title) for c in chapters if (title := _scanned_text(c.title, 200)) is not None
    ][:200]
    numbers = [number for number, _ in titled]
    if len(set(numbers)) != len(numbers) or any(not 1 <= n <= 999 for n in numbers):
        numbers = list(range(1, len(titled) + 1))
    return [
        ChapterInput(number=number, title=title)
        for number, (_, title) in zip(numbers, titled, strict=True)
    ]


@dataclass(frozen=True, slots=True)
class _Names:
    classes: dict[UUID, str]
    subjects: dict[UUID, str]
    users: dict[UUID, str]
    schools: dict[UUID, int]


def _owns(entry: SchoolBook, book: Book) -> bool:
    """Whether the entry's campus uploaded the book -- and so may change it."""
    return book.school_id == entry.school_id


def _details(book: Book) -> tuple[str, str, str]:
    return book.title, book.publisher, book.version


def _book_snapshot(book: Book, class_id: UUID) -> dict[str, Any]:
    return {
        "title": book.title,
        "publisher": book.publisher,
        "version": book.version,
        "grade": book.grade,
        "class_id": str(class_id),
    }


def _entry_snapshot(entry: SchoolBook) -> dict[str, Any]:
    return {
        "book_id": str(entry.book_id),
        "class_id": str(entry.class_id),
        "subject_id": str(entry.subject_id) if entry.subject_id else None,
    }


def _source_label(hit: LibraryHit) -> str:
    """ "New Countdown 5, Ch 2: Fractions, p. 21-23" -- what the answer model cites."""
    label = f"{hit.book_title}, Ch {hit.chapter_number}: {hit.chapter_title}"
    if hit.printed_start is None:
        return label
    if hit.printed_end is None or hit.printed_end == hit.printed_start:
        return f"{label}, p. {hit.printed_start}"
    return f"{label}, p. {hit.printed_start}-{hit.printed_end}"
