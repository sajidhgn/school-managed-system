"""Exam API contracts.

Same discipline as the academics schemas: these describe what a client may SEND
and RECEIVE, never the table shape. `school_id` appears in no Create schema --
it comes from the verified JWT, and accepting it in a body would be a
mass-assignment hole into another campus's gradebook.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field, model_validator

from app.common.schemas import BaseSchema
from app.modules.exams.models import ExamStatus

# ---------------------------------------------------------------------------
# Exams
# ---------------------------------------------------------------------------


class ExamCreate(BaseSchema):
    name: str = Field(min_length=1, max_length=120, examples=["Mid-Term 2026-27"])
    term_id: UUID | None = None
    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def _dates_ordered(self) -> ExamCreate:
        """Checked here as well as by the CHECK constraint -- this is the error
        message, the constraint is the guarantee."""
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must not be before start_date.")
        return self


class ExamUpdate(BaseSchema):
    """PATCH semantics: omitted means unchanged; `status` moves the lifecycle."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    term_id: UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    status: ExamStatus | None = None


class ExamRead(BaseSchema):
    id: UUID
    name: str
    term_id: UUID | None
    start_date: date | None
    end_date: date | None
    status: ExamStatus
    paper_count: int = 0
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Papers
# ---------------------------------------------------------------------------


class ExamPaperCreate(BaseSchema):
    class_id: UUID
    subject_id: UUID
    scheduled_on: date | None = None
    max_marks: int = Field(default=100, gt=0, le=1000)
    pass_marks: int | None = Field(default=None, ge=0, le=1000)

    @model_validator(mode="after")
    def _pass_within_max(self) -> ExamPaperCreate:
        if self.pass_marks is not None and self.pass_marks > self.max_marks:
            raise ValueError("pass_marks cannot exceed max_marks.")
        return self


class ExamPaperUpdate(BaseSchema):
    scheduled_on: date | None = None
    max_marks: int | None = Field(default=None, gt=0, le=1000)
    pass_marks: int | None = Field(default=None, ge=0, le=1000)
    # `class_id` and `subject_id` are deliberately absent: re-pointing a paper
    # that already carries marks would silently reassign a whole class's results
    # to a different subject. Delete and recreate states that intent honestly.


class ExamPaperRead(BaseSchema):
    """A paper with its dimensions denormalised.

    Subject code/name and class name are inlined for the same reason
    `ClassSubjectRead` inlines them: the papers table renders every row's labels
    on first paint, and ids would guarantee an N+1 in the browser.
    """

    id: UUID
    exam_id: UUID
    class_id: UUID
    class_name: str
    subject_id: UUID
    subject_code: str
    subject_name: str
    scheduled_on: date | None
    max_marks: int
    pass_marks: int | None
    marks_entered: int = 0
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Marks
# ---------------------------------------------------------------------------


class MarkEntry(BaseSchema):
    """One student's result, as the marks screen submits it."""

    student_id: UUID
    marks_obtained: Decimal | None = Field(default=None, ge=0, decimal_places=2)
    is_absent: bool = False
    remarks: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def _absent_xor_marks(self) -> MarkEntry:
        """Mirrors the `absent_xor_marks` CHECK, as a message instead of a 409."""
        if self.is_absent and self.marks_obtained is not None:
            raise ValueError("An absent student cannot also have marks.")
        if not self.is_absent and self.marks_obtained is None:
            raise ValueError("Provide marks_obtained, or set is_absent.")
        return self


class MarksUpsert(BaseSchema):
    """The bulk write: the whole column of a paper's mark sheet in one request.

    An upsert rather than a create -- re-submitting the sheet after a correction
    must overwrite, not conflict. Students omitted from `entries` are left
    untouched, so a partial save (marking stops at roll 23) loses nothing.
    """

    entries: list[MarkEntry] = Field(min_length=1, max_length=500)


class StudentMarkRow(BaseSchema):
    """One line of the marks screen: the student, and their mark if entered.

    The roster and the marks arrive TOGETHER so the screen can render every
    enrolled student -- including the ones not yet marked -- in roll order.
    Returning only existing marks would hide exactly the rows the teacher still
    has to fill in.
    """

    student_id: UUID
    full_name: str
    admission_number: str
    marks_obtained: Decimal | None
    is_absent: bool
    remarks: str | None
    entered: bool
    """False when no mark row exists yet -- distinct from absent (see the model
    docstring: a missing row is "not yet entered", `is_absent` is "was away")."""


class PaperMarksRead(BaseSchema):
    paper: ExamPaperRead
    rows: list[StudentMarkRow]


class MarksUpsertResult(BaseSchema):
    saved: int


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


class ResultCell(BaseSchema):
    """One paper's contribution to one student's result line."""

    paper_id: UUID
    marks_obtained: Decimal | None
    is_absent: bool


class ExamResultRow(BaseSchema):
    student_id: UUID
    full_name: str
    admission_number: str
    cells: list[ResultCell]
    total_obtained: Decimal
    total_max: int
    percentage: Decimal
    """Of the papers actually MARKED for this student -- an unmarked paper does
    not count as zero, or a half-entered exam would rank everyone by data-entry
    order rather than performance."""
    rank: int
    """1-based within the class, ties sharing a rank (standard competition
    ranking: two students on 91% are both 1st and the next is 3rd)."""


class ExamClassResults(BaseSchema):
    """The class result sheet: papers as columns, students as rows."""

    exam_id: UUID
    class_id: UUID
    class_name: str
    papers: list[ExamPaperRead]
    rows: list[ExamResultRow]
