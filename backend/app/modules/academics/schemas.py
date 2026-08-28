"""Academics API contracts.

WHY SEPARATE FROM models.py
    These describe what a client may SEND and what it WILL RECEIVE -- deliberately
    not the table shape. `school_id` appears in no Create schema: it is taken from
    the verified JWT, never from the request body. Accepting it would be a
    mass-assignment hole that lets a caller write into another tenant.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import Field, model_validator

from app.common.schemas import BaseSchema
from app.modules.academics.models import SubjectKind

# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------


class ClassCreate(BaseSchema):
    name: str = Field(min_length=1, max_length=80, examples=["Grade 10"])
    level: int = Field(ge=0, le=100, examples=[10], description="Numeric rank used for ordering.")


class ClassUpdate(BaseSchema):
    """All fields optional -- PATCH semantics.

    The service applies `model_dump(exclude_unset=True)`, so omitting a field leaves
    it untouched rather than nulling it.
    """

    name: str | None = Field(default=None, min_length=1, max_length=80)
    level: int | None = Field(default=None, ge=0, le=100)


class ClassRead(BaseSchema):
    id: UUID
    name: str
    level: int
    created_at: datetime
    updated_at: datetime


class ClassSummary(BaseSchema):
    """A class with its sections and headcounts.

    Serves the PDF's "Class & Section Summaries" dashboard: classes, their active
    sections, and total student headcount per section. Assembled by the service from
    one grouped COUNT query rather than N+1 per-section counts.
    """

    id: UUID
    name: str
    level: int
    section_count: int
    student_count: int
    sections: list[SectionSummary]


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------


class SectionCreate(BaseSchema):
    name: str = Field(min_length=1, max_length=40, examples=["A"])
    capacity: int | None = Field(default=None, gt=0, le=500)
    class_teacher_id: UUID | None = None


class SectionUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=1, max_length=40)
    capacity: int | None = Field(default=None, gt=0, le=500)
    class_teacher_id: UUID | None = None


class SectionRead(BaseSchema):
    id: UUID
    class_id: UUID
    name: str
    capacity: int | None
    class_teacher_id: UUID | None
    created_at: datetime
    updated_at: datetime


class SectionSummary(BaseSchema):
    """One section plus its live headcount, for the summaries dashboard."""

    id: UUID
    name: str
    capacity: int | None
    class_teacher_id: UUID | None
    class_teacher_name: str | None
    """Resolved server-side so the table can print a name.

    The id alone is useless to a reader, and making the browser resolve it would mean
    every viewer of the class list also needs permission to read the staff list --
    a strictly wider grant than `class:read`, demanded by a column that is only there
    to be legible.
    """
    student_count: int


# `ClassSummary` refers to `SectionSummary` before it is defined, which the
# `from __future__ import annotations` at the top turns into a forward reference.
# Pydantic needs this call to resolve it into the real class.
ClassSummary.model_rebuild()


# ---------------------------------------------------------------------------
# Academic years
# ---------------------------------------------------------------------------


class AcademicYearCreate(BaseSchema):
    name: str = Field(min_length=1, max_length=32, examples=["2026-2027"])
    start_date: date
    end_date: date
    is_current: bool = Field(
        default=False,
        description=(
            "Make this the year new work defaults to. Setting it demotes whichever "
            "year currently holds the flag -- there is at most one per school."
        ),
    )

    @model_validator(mode="after")
    def _dates_ordered(self) -> AcademicYearCreate:
        """Checked here as well as by the CHECK constraint.

        The constraint is the guarantee; this is the error message. A raw
        `ck_academic_years_dates_ordered` violation reaches the client as a 409 with
        a constraint name in it, which tells a registrar nothing about which of the
        two dates they should change.
        """
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date.")
        return self


class AcademicYearUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=1, max_length=32)
    start_date: date | None = None
    end_date: date | None = None
    # `is_current` is deliberately absent: promoting a year has to demote another
    # one, which is a transition rather than a field edit. It has its own endpoint.


class AcademicYearRead(BaseSchema):
    id: UUID
    name: str
    start_date: date
    end_date: date
    is_current: bool
    term_count: int = 0
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Terms
# ---------------------------------------------------------------------------


class TermCreate(BaseSchema):
    name: str = Field(min_length=1, max_length=60, examples=["Term 1"])
    sequence: int = Field(ge=1, le=12, description="1-based ordering within the year.")
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def _dates_ordered(self) -> TermCreate:
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date.")
        return self


class TermUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=1, max_length=60)
    sequence: int | None = Field(default=None, ge=1, le=12)
    start_date: date | None = None
    end_date: date | None = None


class TermRead(BaseSchema):
    id: UUID
    academic_year_id: UUID
    name: str
    sequence: int
    start_date: date
    end_date: date
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------


class SubjectCreate(BaseSchema):
    code: str = Field(min_length=1, max_length=24, examples=["MATH"])
    name: str = Field(min_length=1, max_length=120, examples=["Mathematics"])
    description: str | None = Field(default=None, max_length=2000)
    kind: SubjectKind = SubjectKind.CORE


class SubjectUpdate(BaseSchema):
    code: str | None = Field(default=None, min_length=1, max_length=24)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=2000)
    kind: SubjectKind | None = None


class SubjectRead(BaseSchema):
    id: UUID
    code: str
    name: str
    description: str | None
    kind: SubjectKind
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Curriculum -- which class studies which subject
# ---------------------------------------------------------------------------


class ClassSubjectCreate(BaseSchema):
    subject_id: UUID
    teacher_id: UUID | None = Field(
        default=None, description="Default teacher for this subject across the grade."
    )
    weekly_periods: int | None = Field(default=None, gt=0, le=40)


class ClassSubjectUpdate(BaseSchema):
    teacher_id: UUID | None = None
    weekly_periods: int | None = Field(default=None, gt=0, le=40)


class ClassSubjectRead(BaseSchema):
    """A curriculum row with the subject inlined.

    The subject's code and name are denormalised into the response rather than left
    as an id for the client to resolve. A curriculum screen renders every row's name
    on first paint, so returning ids would guarantee a second request per row -- an
    N+1 moved from the database into the browser.
    """

    id: UUID
    class_id: UUID
    subject_id: UUID
    subject_code: str
    subject_name: str
    subject_kind: SubjectKind
    teacher_id: UUID | None
    weekly_periods: int | None
    created_at: datetime
    updated_at: datetime
