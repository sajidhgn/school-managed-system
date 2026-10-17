"""Question bank and test papers.

WHY THIS FILE EXISTS
    A teacher picks a book's chapters, a language, a difficulty and a paper type;
    the paper agent writes questions FROM THOSE CHAPTERS, checks them, and files
    them in the school's question bank. A paper is an ordered selection from that
    bank, so a question written once can be reused later without the AI.

TABLES
    questions          the bank: one question, its answer, where in the book it
                       comes from, and what the checks said about it
    papers             one test paper: what was asked for, and the generation
                       job's state (the worker claims it like a book chapter)
    paper_questions    the paper's questions, in order, by section, with marks

WHY A QUESTION REMEMBERS ITS PAGES AND ITS CHECKS
    `printed_page` lets a teacher open the book where the answer is. `checks` keeps
    the Decisions API's probabilities ("answerable 0.97, medium 0.81"), so a
    question is never trusted more than the evidence it passed.

LANGUAGE
    A paper is English, Urdu or Arabic (`PaperLanguage`). Questions carry the
    language they are written in; the print view sets direction and font from it
    (Urdu in Nastaliq, Arabic in Naskh, both right-to-left).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, str_enum
from app.db.mixins import (
    RequiredSchoolMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)


class QuestionType(StrEnum):
    MCQ = "mcq"
    TRUE_FALSE = "true_false"
    FILL_BLANK = "fill_blank"
    SHORT = "short"
    LONG = "long"

    @property
    def objective(self) -> bool:
        return self in OBJECTIVE_TYPES


OBJECTIVE_TYPES = frozenset({QuestionType.MCQ, QuestionType.TRUE_FALSE, QuestionType.FILL_BLANK})
SUBJECTIVE_TYPES = frozenset({QuestionType.SHORT, QuestionType.LONG})


class Difficulty(StrEnum):
    EASY = "easy"
    """Recall: a definition, a fact, a name."""
    MEDIUM = "medium"
    """Understand or apply in one step."""
    HARD = "hard"
    """Several steps, analyse, compare, explain why."""


class PaperDifficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    MIXED = "mixed"
    """30% easy, 50% medium, 20% hard -- see `generator.MIXED_SHARES`."""


class PaperType(StrEnum):
    OBJECTIVE = "objective"
    SUBJECTIVE = "subjective"
    MIX = "mix"


class PaperLanguage(StrEnum):
    ENGLISH = "en"
    URDU = "ur"
    ARABIC = "ar"


class QuestionOrigin(StrEnum):
    AI = "ai"
    MANUAL = "manual"


class PaperStatus(StrEnum):
    QUEUED = "queued"
    GENERATING = "generating"
    READY = "ready"
    """Every requested question was written and passed its checks."""
    NEEDS_REVIEW = "needs_review"
    """Generated, but fewer questions passed than were asked for, or some passed
    at another difficulty than requested -- `report.issues` says which."""
    FAILED = "failed"


class Question(Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin):
    """One question in the school's bank."""

    __tablename__ = "questions"

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
    book_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("books.id", ondelete="SET NULL"),
        index=True,
    )
    chapter_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("book_chapters.id", ondelete="SET NULL"),
        index=True,
    )
    type: Mapped[QuestionType] = mapped_column(
        str_enum(QuestionType, name="question_type"), nullable=False
    )
    difficulty: Mapped[Difficulty] = mapped_column(
        str_enum(Difficulty, name="question_difficulty"), nullable=False
    )
    language: Mapped[PaperLanguage] = mapped_column(
        str_enum(PaperLanguage, name="question_language", length=8), nullable=False
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[list[str] | None] = mapped_column(JSONB)
    """MCQ: four options. True/false: the two words in the paper's language."""
    correct_option: Mapped[int | None] = mapped_column(Integer)
    """0-based index into `options` (MCQ, true/false)."""
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    """The answer key: the word for a blank, a model answer or marking points."""
    marks: Mapped[int] = mapped_column(Integer, nullable=False)
    printed_page: Mapped[int | None] = mapped_column(Integer)
    """The book page the answer is on, as printed."""
    origin: Mapped[QuestionOrigin] = mapped_column(
        str_enum(QuestionOrigin, name="question_origin"),
        nullable=False,
        default=QuestionOrigin.AI,
    )
    checks: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """What the checker said: `{"answerable": 0.97, "difficulty": {"easy": 0.1, ...},
    "judged": "medium", "option_agrees": true}`."""
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )

    __table_args__ = (
        CheckConstraint("marks BETWEEN 1 AND 100", name="marks_in_range"),
        Index("ix_questions_school_id_class_id_type", "school_id", "class_id", "type"),
    )


class Paper(Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin):
    """One test paper and the job that generates it."""

    __tablename__ = "papers"

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
    book_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("books.id", ondelete="SET NULL"),
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    language: Mapped[PaperLanguage] = mapped_column(
        str_enum(PaperLanguage, name="paper_language", length=8), nullable=False
    )
    difficulty: Mapped[PaperDifficulty] = mapped_column(
        str_enum(PaperDifficulty, name="paper_difficulty"), nullable=False
    )
    paper_type: Mapped[PaperType] = mapped_column(
        str_enum(PaperType, name="paper_type"), nullable=False
    )
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    instructions: Mapped[str | None] = mapped_column(Text)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """What was asked for: `{"chapter_ids": [...], "sections": [{"type": "mcq",
    "count": 10, "marks": 1}, ...]}` -- the generator's whole input besides the text."""

    status: Mapped[PaperStatus] = mapped_column(
        str_enum(PaperStatus, name="paper_status"),
        nullable=False,
        default=PaperStatus.QUEUED,
    )
    report: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """`{"issues": [...], "written": n, "passed": n, "calls": {...}}`."""
    error: Mapped[str | None] = mapped_column(String(1000))
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    """The worker's claim token, as on `book_chapters`."""
    generated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    """`paper:write` holders may change only papers they created."""

    __table_args__ = (
        CheckConstraint(
            "duration_minutes IS NULL OR duration_minutes BETWEEN 5 AND 600",
            name="duration_in_range",
        ),
        Index("ix_papers_status_updated_at", "status", "updated_at"),
    )


class PaperQuestion(Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin):
    """A question's place on a paper."""

    __tablename__ = "paper_questions"

    paper_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("papers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    question_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    """1-based across the whole paper; objective sections come first."""
    marks: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_difficulty: Mapped[Difficulty | None] = mapped_column(
        str_enum(Difficulty, name="paper_question_difficulty")
    )
    """The slot's difficulty, which the question may not have matched."""

    __table_args__ = (
        UniqueConstraint("paper_id", "position", name="uq_paper_questions_paper_id_position"),
        UniqueConstraint("paper_id", "question_id", name="uq_paper_questions_paper_id_question_id"),
        CheckConstraint("marks BETWEEN 1 AND 100", name="marks_in_range"),
    )
