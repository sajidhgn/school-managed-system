"""Question bank and test paper API contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.common.schemas import BaseSchema
from app.modules.papers.models import (
    OBJECTIVE_TYPES,
    SUBJECTIVE_TYPES,
    Difficulty,
    PaperDifficulty,
    PaperLanguage,
    PaperStatus,
    PaperType,
    QuestionOrigin,
    QuestionType,
)

MAX_QUESTIONS_PER_PAPER = 100


def _squash(value: str) -> str:
    return " ".join(value.split())


class SectionInput(BaseSchema):
    type: QuestionType
    count: int = Field(ge=1, le=50)
    marks: int | None = Field(default=None, ge=1, le=100)
    """Marks per question; the type's usual marks when omitted."""


class PaperCreate(BaseSchema):
    title: str = Field(min_length=1, max_length=200)
    book_id: UUID
    chapter_ids: list[UUID] = Field(min_length=1, max_length=20)
    language: PaperLanguage = PaperLanguage.ENGLISH
    difficulty: PaperDifficulty = PaperDifficulty.MIXED
    paper_type: PaperType
    sections: list[SectionInput] = Field(min_length=1, max_length=5)
    duration_minutes: int | None = Field(default=None, ge=5, le=600)
    instructions: str | None = Field(default=None, max_length=2000)

    @field_validator("title")
    @classmethod
    def _clean_title(cls, v: str) -> str:
        return _squash(v)

    @model_validator(mode="after")
    def _consistent(self) -> PaperCreate:
        types = [s.type for s in self.sections]
        if len(set(types)) != len(types):
            raise ValueError("Each question type may appear in one section only.")
        if len(set(self.chapter_ids)) != len(self.chapter_ids):
            raise ValueError("A chapter is listed twice.")
        if sum(s.count for s in self.sections) > MAX_QUESTIONS_PER_PAPER:
            raise ValueError(f"A paper holds at most {MAX_QUESTIONS_PER_PAPER} questions.")
        chosen = set(types)
        if self.paper_type is PaperType.OBJECTIVE and not chosen <= OBJECTIVE_TYPES:
            raise ValueError("An objective paper has only MCQ, true/false and fill-in sections.")
        if self.paper_type is PaperType.SUBJECTIVE and not chosen <= SUBJECTIVE_TYPES:
            raise ValueError("A subjective paper has only short and long question sections.")
        if self.paper_type is PaperType.MIX and not (
            chosen & OBJECTIVE_TYPES and chosen & SUBJECTIVE_TYPES
        ):
            raise ValueError("A mixed paper needs an objective and a subjective section.")
        return self


class PaperUpdate(BaseSchema):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    duration_minutes: int | None = Field(default=None, ge=5, le=600)
    instructions: str | None = Field(default=None, max_length=2000)

    @field_validator("title")
    @classmethod
    def _clean_title(cls, v: str | None) -> str | None:
        return None if v is None else _squash(v)


class QuestionRead(BaseSchema):
    id: UUID
    type: QuestionType
    difficulty: Difficulty
    language: PaperLanguage
    text: str
    options: list[str] | None
    correct_option: int | None
    answer: str
    marks: int
    printed_page: int | None
    book_id: UUID | None
    chapter_id: UUID | None
    chapter_number: int | None
    chapter_title: str | None
    origin: QuestionOrigin
    checks: dict[str, Any] | None
    created_at: datetime


class QuestionUpdate(BaseSchema):
    """Edit a question in place. Options and key are checked against its type."""

    text: str | None = Field(default=None, min_length=1, max_length=4000)
    options: list[str] | None = Field(default=None, min_length=2, max_length=4)
    correct_option: int | None = Field(default=None, ge=0, le=3)
    answer: str | None = Field(default=None, max_length=8000)
    difficulty: Difficulty | None = None
    marks: int | None = Field(default=None, ge=1, le=100)
    """Marks on THIS paper. The bank keeps the question's own marks."""


class PaperQuestionRead(BaseSchema):
    id: UUID
    """The question's place on this paper -- what edit/replace/remove address."""
    position: int
    marks: int
    requested_difficulty: Difficulty | None
    question: QuestionRead


class SectionRead(BaseSchema):
    type: QuestionType
    marks: int
    """The section's total."""
    questions: list[PaperQuestionRead]


class ChapterRef(BaseSchema):
    id: UUID
    number: int
    title: str


class PaperRead(BaseSchema):
    id: UUID
    title: str
    class_id: UUID
    class_name: str | None
    subject_id: UUID | None
    subject_name: str | None
    book_id: UUID | None
    book_title: str | None
    language: PaperLanguage
    difficulty: PaperDifficulty
    paper_type: PaperType
    status: PaperStatus
    question_count: int
    total_marks: int
    created_by_user_id: UUID | None
    created_by_name: str | None
    can_edit: bool
    created_at: datetime
    generated_at: datetime | None


class PaperDetail(PaperRead):
    duration_minutes: int | None
    instructions: str | None
    chapters: list[ChapterRef]
    requested: list[SectionInput]
    report: dict[str, Any] | None
    error: str | None
    sections: list[SectionRead]


class PaperQuestionAdd(BaseSchema):
    question_id: UUID
    marks: int | None = Field(default=None, ge=1, le=100)


class ReplaceRequest(BaseSchema):
    difficulty: Difficulty | None = None
    """The new question's difficulty; the slot's when omitted."""
