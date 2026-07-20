"""Academics models -- the class/section hierarchy a school is organised by.

WHY THIS FILE EXISTS
    The PDF marks "Class & Section Setup" as Critical: a school creates grades
    (Grade 10) and sub-sections within them (Section A, B). Almost everything that
    follows hangs off this hierarchy -- students enroll into a section, attendance
    is taken per section, a timetable slots lessons into a section, and fee
    structures are defined per class. Getting the shape right here is load-bearing
    for every later module.

RESPONSIBILITY
    Define `SchoolClass` (a grade level) and `Section` (a sub-division of one), plus
    the constraints that keep them unique *within a tenant*.

INTERACTIONS
    * Both carry `TenantMixin`, so both get an RLS policy via `setup_tenant_table()`.
    * `Section.class_teacher_id` points at `users.id` -- the assignment that the
      PDF's "Teacher (limited to assigned classes)" RBAC rule will be read from.
    * `students.Student.section_id` points at `sections.id`.

WHY `SchoolClass` AND NOT `Class`
    `class` is a Python keyword. The table is still `classes`; only the Python
    identifier is prefixed, which is why `__tablename__` is set explicitly rather
    than left to the automatic convention in db/base.py.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.db.mixins import SoftDeleteMixin, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, types only
    from app.modules.students.models import Student


class SchoolClass(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    """A grade level within one school, e.g. "Grade 10"."""

    __tablename__ = "classes"

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    """Display name, e.g. "Grade 10" or "Year 6".

    Free text rather than a fixed ladder: naming differs per country and per school
    (Grade/Year/Form/Class), and forcing a canonical scheme would make the product
    unusable outside the region it was designed in.
    """

    level: Mapped[int] = mapped_column(Integer, nullable=False)
    """Numeric rank used for ordering, e.g. 10 for "Grade 10".

    Sorting on `name` alphabetically puts "Grade 10" before "Grade 2", which is
    wrong in every school report. An explicit integer keeps ordering correct and
    lets later modules express "promote everyone one level up" arithmetically.
    """

    sections: Mapped[list[Section]] = relationship(
        back_populates="school_class",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        # Scoped to the school, NOT global -- every school has its own "Grade 10".
        # This is the single most repeated multi-tenant modelling mistake: a global
        # unique index here would let the first school to create "Grade 10" block
        # every other tenant from doing the same.
        UniqueConstraint("school_id", "name", name="uq_classes_school_id_name"),
        UniqueConstraint("school_id", "level", name="uq_classes_school_id_level"),
        # Short name only -- the convention in db/base.py prefixes it to
        # `ck_classes_level_non_negative`. Passing the full name here would yield
        # `ck_classes_ck_classes_level_non_negative`.
        CheckConstraint("level >= 0", name="level_non_negative"),
        Index("ix_classes_school_id_level", "school_id", "level"),
    )


class Section(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    """A sub-division of a class, e.g. "A" within "Grade 10"."""

    __tablename__ = "sections"

    class_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("classes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    name: Mapped[str] = mapped_column(String(40), nullable=False)
    """Section label, e.g. "A", "Blue", "Morning"."""

    capacity: Mapped[int | None] = mapped_column(Integer)
    """Optional seat limit, enforced by the service on enrollment.

    Nullable because plenty of schools do not cap sections, and a sentinel value
    like 0 or 9999 would be indistinguishable from a real (if silly) limit.
    """

    class_teacher_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # SET NULL, not CASCADE: a teacher leaving must not delete the section and
        # every student record hanging off it. The section simply becomes unassigned.
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )

    school_class: Mapped[SchoolClass] = relationship(back_populates="sections")
    students: Mapped[list[Student]] = relationship(back_populates="section")

    __table_args__ = (
        # `class_id` alone would be enough for correctness, since a class belongs to
        # exactly one school. `school_id` is included so the constraint still holds
        # if a section is ever re-parented, and so the index is directly usable by
        # the RLS predicate, which always filters on school_id first.
        UniqueConstraint("school_id", "class_id", "name", name="uq_sections_school_class_name"),
        CheckConstraint("capacity IS NULL OR capacity > 0", name="capacity_positive"),
    )
