"""Academics API contracts.

WHY SEPARATE FROM models.py
    These describe what a client may SEND and what it WILL RECEIVE -- deliberately
    not the table shape. `school_id` appears in no Create schema: it is taken from
    the verified JWT, never from the request body. Accepting it would be a
    mass-assignment hole that lets a caller write into another tenant.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import Field

from app.common.schemas import BaseSchema

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
    student_count: int


# `ClassSummary` refers to `SectionSummary` before it is defined, which the
# `from __future__ import annotations` at the top turns into a forward reference.
# Pydantic needs this call to resolve it into the real class.
ClassSummary.model_rebuild()
