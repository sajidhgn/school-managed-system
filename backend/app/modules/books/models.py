"""Textbook library models -- books, their chapter list, uploads, pages and vectors.

WHY THIS FILE EXISTS
    Teachers upload the textbooks a class is taught from, one CHAPTER at a time: a
    chapter PDF, or a stack of phone photos of its pages. An agent then reads every
    page, puts the pages in printed-number order, checks the upload really is the
    chapter it was filed under, and indexes the text in pgvector so later features
    (question papers, search, a tutor) can retrieve it by meaning.

RESPONSIBILITY
    Six tables, outermost first:

        school_books        a campus's SHELF: which library books it uses, each
                            filed under one of its classes (+ optional subject)
        books               the shared LIBRARY: Title, Publisher, Version, Grade
        book_chapters       the book's CHAPTER LIST -- number + title -- and each
                            chapter's processing state and agent report
        book_chapter_files  the original uploads, in upload order
        book_pages          one row per physical page, in the order the agent chose
        book_chunks         retrieval units with a `vector(1536)` embedding

ONE LIBRARY, MANY SHELVES
    Every school on the platform reads from one library: a book uploaded once is
    added by any other school to its own class, never uploaded and indexed again
    (`catalog.py` decides when two books are the same one). So the five content
    tables are READABLE by every organization (`library_read` policy), while
    WRITES stay with the uploading organization (`tenant_isolation`). Which books a
    campus uses, and under which class and subject, is its own business and lives
    in `school_books`, an ordinary tenant table.

    The uploader's campus (`books.organization_id/school_id`) OWNS the content:
    only its people change chapters and uploads. Every other school's entry is a
    link to it; there are no copies to drift apart.

INTERACTIONS
    * `TenantMixin` -> RLS on `organization_id`; `RequiredSchoolMixin` -> campus.
      On the content tables that is the OWNER, and every child row copies both
      from its book on write, so a page can never be owned apart from its book.
    * `school_books.class_id` -> `classes.id` (CASCADE: a deleted class drops the
      shelf entry, not the book); `subject_id` -> `subjects.id` (SET NULL).
    * File bytes live in `common/storage.py`; rows hold only the storage key.
    * `jobs.py` (the worker) is the only writer of `book_pages` and `book_chunks`.

WHY THE CHAPTER LIST IS DECLARED BY THE TEACHER
    The agent is asked "which chapter of THIS list is this page from?", not "what
    chapter is this?". A closed list turns an open-ended guess into a decision with
    a measurable confidence, and a page that matches none of the chapters (the
    index, another book's page) is reported instead of silently indexed.

WHY NO SOFT DELETE
    Books are teaching material, not records anything is computed from. Removing
    a book removes the shelf entry; the content goes too once the uploader removes
    it and no other school uses it, and the audit trail keeps who did it.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, str_enum
from app.db.mixins import (
    RequiredSchoolMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

SEARCH_CONFIG = "english"
"""Text-search configuration for `book_chunks.search_vector`. English stemming
("laws" finds "law"); Urdu words carry no English suffixes and pass through
unchanged, so an Urdu chapter is still searchable word for word."""

EMBEDDING_DIMENSIONS = 1536
"""Fixed by the migration's `vector(1536)` column. `text-embedding-3-*` models are
asked for exactly this many dimensions, so either of them fits."""


class ChapterStatus(StrEnum):
    EMPTY = "empty"
    """No files uploaded yet."""
    UPLOADED = "uploaded"
    """Files present, not processed since they last changed."""
    QUEUED = "queued"
    READING = "reading"
    """Pages handed to OpenAI's Batch API (`BOOKS_BATCH_READS`); the worker picks the
    chapter up again when the batch finishes -- usually within hours, at most 24 h."""
    PROCESSING = "processing"
    READY = "ready"
    """Pages read, ordered, verified as the declared chapter, and indexed."""
    NEEDS_REVIEW = "needs_review"
    """Indexed, but the agent found something a teacher should look at: a page from
    another chapter, a missing page number, or an upload that does not look like
    the chapter it was filed under."""
    FAILED = "failed"


class FileKind(StrEnum):
    PDF = "pdf"
    IMAGE = "image"


class PageMethod(StrEnum):
    TEXT_LAYER = "text_layer"
    """The PDF's own text. Free and exact when the PDF was typeset digitally."""
    VISION = "vision"
    """Transcribed from the page image by the reading model."""


class PagePlacement(StrEnum):
    """How the agent decided where a page goes."""

    PRINTED_NUMBER = "printed_number"
    PDF_ORDER = "pdf_order"
    """Unnumbered, kept after the page before it in the same PDF."""
    AGENT = "agent"
    """Unnumbered loose image, placed by a Decisions API continuity question."""
    UPLOAD_ORDER = "upload_order"
    """No evidence either way; left where it was uploaded."""


class Book(Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin):
    """One textbook in the shared library, owned by the campus that uploaded it."""

    __tablename__ = "books"

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    publisher: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(60), nullable=False)
    """Edition or revision as printed: "2nd Edition", "2024", "Revised 2023"."""
    grade: Mapped[str] = mapped_column(String(80), nullable=False)
    """The class it is for, as the uploader names it ("Class 5") -- what other
    schools see in the library. Follows the uploader's class."""
    grade_key: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    """`catalog.grade_key(grade)`: "Grade 5" and "Class V" are both "5", so a school
    browsing the library for its own Class 5 finds them."""
    subject: Mapped[str | None] = mapped_column(String(120))
    """The uploader's subject name, for searching the library by subject."""
    catalog_key: Mapped[str | None] = mapped_column(String(600), unique=True)
    """`catalog.catalog_key` -- one book per key across the platform. NULL only on
    books that already duplicated an older one when the library became shared."""

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    """The uploader. `book:write` holders may edit only books they created."""


class SchoolBook(Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin):
    """A library book on one campus's shelf, filed under one of its classes."""

    __tablename__ = "school_books"

    book_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("books.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    class_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("classes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    subject_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("subjects.id", ondelete="SET NULL"),
        index=True,
    )
    added_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    """Who put it on the shelf -- the uploader, for the campus that owns the book.
    `book:write` holders may refile or remove only entries they added."""

    __table_args__ = (
        UniqueConstraint("school_id", "book_id", name="uq_school_books_school_id_book_id"),
    )


class BookChapter(Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin):
    """One entry in a book's chapter list, and the state of its upload."""

    __tablename__ = "book_chapters"

    book_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("books.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)

    status: Mapped[ChapterStatus] = mapped_column(
        str_enum(ChapterStatus, name="book_chapter_status"),
        nullable=False,
        default=ChapterStatus.EMPTY,
    )
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """The agent's last report -- see `schemas.ChapterReport` for the shape."""
    error: Mapped[str | None] = mapped_column(String(1000))

    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """Set when a worker claims the chapter. Doubles as the claim token: the worker
    writes its results only if the value is still the one it set."""
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    read_batch: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """The Batch API jobs reading this chapter's pages: `{"batch_ids": [...],
    "pages": n, "submitted_at": iso}`. Set while READING, kept through the
    PROCESSING that collects them (a re-claimed run collects again), cleared when
    the run is saved or fails."""
    embed_batch: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    """The Batch API jobs embedding this chapter's chunks (`BOOKS_BATCH_EMBEDDINGS`):
    `{"batch_ids": [...], "chunks": n, "submitted_at": iso}`. Set when a run is
    saved with chunks still to embed; independent of `status` -- the chapter is
    READY or NEEDS_REVIEW meanwhile, only its search entries wait. Cleared when the
    worker writes the vectors. SQL NULL (not JSON null): the worker scans for it."""

    __table_args__ = (
        UniqueConstraint("book_id", "number", name="uq_book_chapters_book_id_number"),
        CheckConstraint("number BETWEEN 1 AND 999", name="number_in_range"),
        # The worker's claim query: queued (or stale processing) chapters, oldest first;
        # also its scan for READING chapters whose batch may have finished.
        Index("ix_book_chapters_status_updated_at", "status", "updated_at"),
    )


class BookChapterFile(Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin):
    """One uploaded PDF or image."""

    __tablename__ = "book_chapter_files"

    chapter_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("book_chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[FileKind] = mapped_column(
        str_enum(FileKind, name="book_file_kind"), nullable=False
    )
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    page_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False)
    """Upload order. The agent's ordering overrides it; it is the fallback."""

    uploaded_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )

    __table_args__ = (
        # The same photo uploaded twice would become two copies of one page.
        UniqueConstraint("chapter_id", "sha256", name="uq_book_chapter_files_chapter_id_sha256"),
    )


class BookPage(Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin):
    """One physical page, in the order the agent put it."""

    __tablename__ = "book_pages"

    chapter_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("book_chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("book_chapter_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_index: Mapped[int] = mapped_column(Integer, nullable=False)
    """0-based page index inside its file (always 0 for an image)."""
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    """1-based reading order within the chapter."""
    printed_page_number: Mapped[int | None] = mapped_column(Integer)
    placement: Mapped[PagePlacement] = mapped_column(
        str_enum(PagePlacement, name="book_page_placement"), nullable=False
    )
    method: Mapped[PageMethod] = mapped_column(
        str_enum(PageMethod, name="book_page_method"), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    image_key: Mapped[str | None] = mapped_column(String(500))

    detected_chapter_number: Mapped[int | None] = mapped_column(Integer)
    """Which chapter of the book's list the Decisions API placed this page in;
    NULL for "none of them" (cover, index, a stray page)."""
    chapter_confidence: Mapped[float | None] = mapped_column(Float)
    opens_chapter: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (
        UniqueConstraint("chapter_id", "position", name="uq_book_pages_chapter_id_position"),
    )


class BookChunk(Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin):
    """A retrieval unit: a few paragraphs of a chapter with their embedding."""

    __tablename__ = "book_chunks"

    book_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("books.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chapter_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("book_chapters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_start: Mapped[int] = mapped_column(Integer, nullable=False)
    """`book_pages.position` of the first page the chunk draws from."""
    page_end: Mapped[int] = mapped_column(Integer, nullable=False)
    printed_start: Mapped[int | None] = mapped_column(Integer)
    printed_end: Mapped[int | None] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(EMBEDDING_DIMENSIONS))
    """NULL while the chunk waits for its embedding batch (`BookChapter.embed_batch`).
    Search skips it until then; HNSW does not index NULLs."""
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    search_vector: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed(f"to_tsvector('{SEARCH_CONFIG}', content)", persisted=True),
        deferred=True,
    )
    """Keyword index of `content`, maintained by PostgreSQL. Keyword search needs no
    embedding, so a chunk is findable by its words while its vector is pending."""

    __table_args__ = (
        UniqueConstraint("chapter_id", "chunk_index", name="uq_book_chunks_chapter_id_chunk_index"),
        Index("ix_book_chunks_search_vector", "search_vector", postgresql_using="gin"),
        # HNSW over cosine distance -- the `<=>` operator `repository.search` orders by.
        Index(
            "ix_book_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
