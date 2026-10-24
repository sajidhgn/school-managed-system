"""Textbook library API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from app.common.schemas import BaseSchema
from app.modules.books.models import ChapterStatus, FileKind, PageMethod, PagePlacement


def _squash(value: str) -> str:
    """Trim and collapse internal whitespace, so "Oxford  " and "Oxford" are one
    publisher for the duplicate-book check."""
    return " ".join(value.split())


class ChapterInput(BaseSchema):
    number: int = Field(ge=1, le=999)
    title: str = Field(min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def _clean(cls, v: str) -> str:
        return _squash(v)


class BookCreate(BaseSchema):
    title: str = Field(min_length=1, max_length=200)
    class_id: UUID
    publisher: str = Field(min_length=1, max_length=200)
    version: str = Field(min_length=1, max_length=60)
    subject_id: UUID | None = None
    chapters: list[ChapterInput] = Field(default_factory=list, max_length=200)
    """The chapter list can be entered with the book, or added chapter by chapter."""

    @field_validator("title", "publisher", "version")
    @classmethod
    def _clean(cls, v: str) -> str:
        return _squash(v)


class BookScan(BaseSchema):
    """A book's details as the AI read them off its cover and contents pages.

    A draft for the "Add a book" form, never saved by itself: every field is
    what the teacher sees pre-filled and checks before adding the book.
    """

    title: str | None
    publisher: str | None
    version: str | None
    class_id: UUID | None
    """The campus class the book is for, when the pages name one the caller can
    file under."""
    class_printed: str | None
    """The class as printed ("Class V") -- shown when `class_id` is None."""
    subject_id: UUID | None
    """Only a subject on `class_id`'s curriculum the caller may file under."""
    subject_printed: str | None
    chapters: list[ChapterInput]
    pages_read: int
    notes: list[str] = Field(default_factory=list)
    """Things the teacher should know, e.g. that only a PDF's first pages were read."""


class ScanStatus(BaseSchema):
    """Whether "Add a book" can read pages with AI right now, and with what."""

    ready: bool
    provider: str
    """"kie.ai", "OpenRouter", ... -- from `BOOKS_SCAN_PROVIDER`."""
    model: str
    problem: str | None = None
    """Why not, when not ready: a missing or rejected key, an unknown model, an
    unreachable server."""


class BookUpdate(BaseSchema):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    class_id: UUID | None = None
    publisher: str | None = Field(default=None, min_length=1, max_length=200)
    version: str | None = Field(default=None, min_length=1, max_length=60)
    subject_id: UUID | None = None
    clear_subject: bool = False

    @field_validator("title", "publisher", "version")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return _squash(v) if v is not None else None


class ChapterUpdate(BaseSchema):
    number: int | None = Field(default=None, ge=1, le=999)
    title: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("title")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return _squash(v) if v is not None else None


class ReportIssue(BaseSchema):
    code: str
    message: str
    positions: list[int] = Field(default_factory=list)


class ChapterReport(BaseSchema):
    """What the agent found the last time it processed the chapter."""

    detected_chapter_number: int | None = None
    detected_confidence: float = 0.0
    matches_declared: bool = False
    chapter_probabilities: dict[str, float] = Field(default_factory=dict)
    issues: list[ReportIssue] = Field(default_factory=list)
    pages_total: int = 0
    vision_pages: int = 0
    text_layer_pages: int = 0
    batch_read_pages: int = 0
    """Vision pages read through the Batch API, at half price."""
    batch_fallback_pages: int = 0
    """Vision pages a batch did not answer (failed or expired), read live instead."""
    chunks: int = 0
    batch_embedded_chunks: int = 0
    """Chunks embedded through the Batch API, at half price. Filled in when the
    batch is collected, after the rest of the report."""
    batch_embed_fallback_chunks: int = 0
    """Chunks an embedding batch did not answer, embedded live instead."""
    models: dict[str, str] = Field(default_factory=dict)
    calls: dict[str, int] = Field(default_factory=dict)
    input_tokens: int = 0
    output_tokens: int = 0
    accepted_by_name: str | None = None
    """Set when a teacher accepted a NEEDS_REVIEW chapter as it is."""


class ChapterFileRead(BaseSchema):
    id: UUID
    kind: FileKind
    original_name: str
    content_type: str
    size_bytes: int
    page_count: int
    sort_order: int
    created_at: datetime


class ChapterRead(BaseSchema):
    id: UUID
    number: int
    title: str
    status: ChapterStatus
    page_count: int
    files: list[ChapterFileRead]
    report: ChapterReport | None
    indexing: bool = False
    """The chapter is processed, but its search entries wait for an OpenAI
    embedding batch (at most 24 h). Its pages can be read already."""
    error: str | None
    processed_at: datetime | None
    updated_at: datetime


class BookRead(BaseSchema):
    id: UUID
    title: str
    publisher: str
    version: str
    class_id: UUID
    class_name: str
    subject_id: UUID | None
    subject_name: str | None
    chapter_count: int
    ready_chapter_count: int
    created_by_name: str | None
    created_at: datetime
    can_edit: bool


class BookDetail(BookRead):
    chapters: list[ChapterRead]


class PageRead(BaseSchema):
    id: UUID
    position: int
    printed_page_number: int | None
    placement: PagePlacement
    method: PageMethod
    text: str
    has_image: bool
    file_id: UUID
    source_index: int
    detected_chapter_number: int | None
    chapter_confidence: float | None
    opens_chapter: bool


class BookSearchHit(BaseSchema):
    chunk_id: UUID
    chapter_id: UUID
    chapter_number: int
    chapter_title: str
    page_start: int
    page_end: int
    printed_start: int | None
    printed_end: int | None
    content: str
    score: float
    """Cosine similarity, 0-1. Higher is closer."""


class LibraryHit(BaseSchema):
    """A passage found by library-wide (hybrid) search."""

    chunk_id: UUID
    book_id: UUID
    book_title: str
    chapter_id: UUID
    chapter_number: int
    chapter_title: str
    page_start: int
    page_end: int
    printed_start: int | None
    printed_end: int | None
    content: str
    score: float
    """Reciprocal-rank fusion of the two rankings, scaled to 0-1. It orders the
    hits; it is not a probability."""
    matched_by: Literal["both", "meaning", "keywords"]
    """Which half of hybrid search found it: pgvector, full-text, or both."""


class AskRequest(BaseSchema):
    question: str = Field(min_length=3, max_length=500)
    class_id: UUID | None = None
    subject_id: UUID | None = None
    book_id: UUID | None = None
    chapter_id: UUID | None = None

    @field_validator("question")
    @classmethod
    def _clean(cls, v: str) -> str:
        return _squash(v)


class LibraryAnswer(BaseSchema):
    found: bool
    """False when the books do not cover the question; `answer` then says so."""
    answer: str
    """Markdown, citing `sources` as [1], [2], ..."""
    sources: list[LibraryHit]
    """Every passage the answer was written from, in order: [n] is `sources[n-1]`."""
    cited: list[int]
    """The [n] the answer actually uses -- the ones to show as its references."""
