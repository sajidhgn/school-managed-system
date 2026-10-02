"""Diary API contracts.

A diary PAGE is assembled, not stored: the section's curriculum supplies the rows,
`diary_entries` supplies the text beside them. The response is shaped as the page
a teacher fills and a parent reads -- every subject, in order, homework or not.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from pydantic import Field

from app.common.schemas import BaseSchema

# Long enough for a dense day ("Pg 26 complete Alphabet Aa to Zz, Days of week ...")
# several times over; short enough that a pasted chapter is refused rather than
# rendered as an unreadable diary sheet.
MAX_ENTRY_LENGTH = 1000


class DiaryAccess(StrEnum):
    """Why the caller sees a section in their diary list, strongest first."""

    CLASS_TEACHER = "class_teacher"
    """Writes every subject on the page."""

    SUBJECT_TEACHER = "subject_teacher"
    """Writes only the rows for subjects they teach this class."""

    MANAGE = "manage"
    """Holds `diary:manage`: writes any row, assigned or not."""

    READ = "read"
    """Sees the page, writes nothing on it."""


class DiarySectionOption(BaseSchema):
    """One section in the diary picker."""

    section_id: UUID
    section_name: str
    class_id: UUID
    class_name: str
    class_level: int
    class_teacher_name: str | None
    access: DiaryAccess
    filled_count: int = 0
    """Subjects with homework written for the requested date -- lets the picker
    show at a glance which classes still have an empty diary."""
    subject_count: int = 0


class DiaryRow(BaseSchema):
    subject_id: UUID
    subject_code: str
    subject_name: str
    teacher_id: UUID | None
    teacher_name: str | None
    content: str | None
    written_by_name: str | None
    updated_at: datetime | None
    can_edit: bool


class DiaryPage(BaseSchema):
    section_id: UUID
    section_name: str
    class_id: UUID
    class_name: str
    class_teacher_name: str | None
    entry_date: date
    rows: list[DiaryRow]
    can_edit: bool
    """True when the caller may write at least one row -- drives the Save button."""


class DiaryEntryInput(BaseSchema):
    subject_id: UUID
    content: str = Field(max_length=MAX_ENTRY_LENGTH)
    """Blank (after trimming) clears the subject's homework for the day."""


class DiaryPageWrite(BaseSchema):
    """The rows the caller changed. Subjects not named are left as they are, so two
    subject teachers saving the same page at once never overwrite each other."""

    entries: list[DiaryEntryInput] = Field(min_length=1, max_length=50)
