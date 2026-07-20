"""Academics business rules -- class and section setup.

WHY THIS FILE EXISTS
    Everything that decides *what is allowed* when structuring a school: that a
    grade name is unique within the tenant, that a section cannot be deleted while
    students are still seated in it, and that a class teacher must actually be a
    teacher at this school.

INTERACTIONS
    * `router.py` translates HTTP; this layer never imports fastapi.
    * `students.service` calls `assert_section_capacity` before seating a student.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas import Page, PageParams, SortParams
from app.core.context import require_school_id
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.modules.academics.models import SchoolClass, Section
from app.modules.academics.repository import ClassRepository, SectionRepository
from app.modules.academics.schemas import (
    ClassCreate,
    ClassRead,
    ClassSummary,
    ClassUpdate,
    SectionCreate,
    SectionRead,
    SectionSummary,
    SectionUpdate,
)
from app.modules.auth.models import User, UserRole

logger = get_logger(__name__)


class AcademicsService:
    """Class and section lifecycle."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.classes = ClassRepository(session)
        self.sections = SectionRepository(session)

    # -- classes ------------------------------------------------------------

    async def create_class(self, payload: ClassCreate) -> ClassRead:
        if await self.classes.get_by_name(payload.name):
            raise ConflictError(f"A class named '{payload.name}' already exists.")
        if await self.classes.get_by_level(payload.level):
            raise ConflictError(f"A class at level {payload.level} already exists.")

        school_class = await self.classes.create(
            **payload.model_dump(),
            # From the verified JWT, never the request body. Omitting it does not
            # create an orphan row -- the RLS WITH CHECK rejects the INSERT outright.
            school_id=require_school_id(),
        )
        logger.info("class_created", class_id=str(school_class.id), level=school_class.level)
        return ClassRead.model_validate(school_class)

    async def get_class(self, class_id: UUID) -> SchoolClass:
        """Load a class or raise.

        Returns the ORM object, not a schema, because callers in this module need to
        pass it on. A cross-tenant id lands here as `None` -- RLS filtered the row
        out -- and becomes a 404, never a 403. A 403 would confirm the row exists,
        which is itself a cross-tenant information leak.
        """
        school_class = await self.classes.get(class_id)
        if school_class is None:
            raise NotFoundError("Class not found.")
        return school_class

    async def list_classes(self, params: PageParams, sort: SortParams) -> Page[ClassRead]:
        rows, total = await self.classes.list(params=params, sort=sort)
        return Page.create([ClassRead.model_validate(r) for r in rows], total, params)

    async def update_class(self, class_id: UUID, payload: ClassUpdate) -> ClassRead:
        school_class = await self.get_class(class_id)
        values = payload.model_dump(exclude_unset=True)

        # Re-check uniqueness only when the field actually changes, so a no-op PATCH
        # of an unrelated field does not fail against the row's own values.
        name = values.get("name")
        if name and name != school_class.name and await self.classes.get_by_name(name):
            raise ConflictError(f"A class named '{name}' already exists.")

        level = values.get("level")
        if (
            level is not None
            and level != school_class.level
            and await self.classes.get_by_level(level)
        ):
            raise ConflictError(f"A class at level {level} already exists.")

        updated = await self.classes.update(school_class, **values)
        return ClassRead.model_validate(updated)

    async def delete_class(self, class_id: UUID) -> None:
        school_class = await self.get_class(class_id)

        # Refuse rather than cascade. The FK would happily remove every section, and
        # every student in them would silently lose their placement. Deleting a whole
        # grade is a destructive administrative act that should be explicit.
        sections = await self.sections.list_for_class(class_id)
        if sections:
            raise ConflictError(
                f"This class still has {len(sections)} section(s). "
                "Delete or move them before deleting the class."
            )
        await self.classes.soft_delete(school_class)
        logger.info("class_deleted", class_id=str(class_id))

    # -- sections -----------------------------------------------------------

    async def create_section(self, class_id: UUID, payload: SectionCreate) -> SectionRead:
        school_class = await self.get_class(class_id)

        if await self.sections.get_by_name(class_id, payload.name):
            raise ConflictError(f"Section '{payload.name}' already exists in this class.")
        if payload.class_teacher_id is not None:
            await self._assert_is_teacher(payload.class_teacher_id)

        section = await self.sections.create(
            class_id=school_class.id,
            school_id=school_class.school_id,
            **payload.model_dump(),
        )
        logger.info("section_created", section_id=str(section.id), class_id=str(class_id))
        return SectionRead.model_validate(section)

    async def get_section(self, section_id: UUID) -> Section:
        section = await self.sections.get(section_id)
        if section is None:
            raise NotFoundError("Section not found.")
        return section

    async def list_sections(self, class_id: UUID) -> list[SectionRead]:
        await self.get_class(class_id)  # 404 for an unknown or cross-tenant class
        rows = await self.sections.list_for_class(class_id)
        return [SectionRead.model_validate(r) for r in rows]

    async def update_section(self, section_id: UUID, payload: SectionUpdate) -> SectionRead:
        section = await self.get_section(section_id)
        values = payload.model_dump(exclude_unset=True)

        name = values.get("name")
        if (
            name
            and name != section.name
            and await self.sections.get_by_name(section.class_id, name)
        ):
            raise ConflictError(f"Section '{name}' already exists in this class.")

        if "class_teacher_id" in values and values["class_teacher_id"] is not None:
            await self._assert_is_teacher(values["class_teacher_id"])

        # Shrinking capacity below the students already seated would leave the
        # section permanently over its own limit, and every later enrollment check
        # would read as broken rather than as a deliberate override.
        if (capacity := values.get("capacity")) is not None:
            seated = await self.sections.enrolled_count(section_id)
            if capacity < seated:
                raise ValidationError(
                    f"Capacity cannot be set below the {seated} student(s) already enrolled.",
                    code="CAPACITY_BELOW_ENROLLED",
                )

        updated = await self.sections.update(section, **values)
        return SectionRead.model_validate(updated)

    async def delete_section(self, section_id: UUID) -> None:
        section = await self.get_section(section_id)
        seated = await self.sections.enrolled_count(section_id)
        if seated:
            raise ConflictError(
                f"This section still has {seated} enrolled student(s). Move them first."
            )
        await self.sections.soft_delete(section)
        logger.info("section_deleted", section_id=str(section_id))

    # -- capacity, used by the students module ------------------------------

    async def assert_section_capacity(self, section_id: UUID) -> Section:
        """Confirm a section exists and has room for one more student."""
        section = await self.get_section(section_id)
        if section.capacity is None:
            return section
        seated = await self.sections.enrolled_count(section_id)
        if seated >= section.capacity:
            raise ConflictError(f"Section '{section.name}' is full ({seated}/{section.capacity}).")
        return section

    # -- summaries dashboard ------------------------------------------------

    async def summaries(self) -> list[ClassSummary]:
        """Classes -> sections -> headcounts (PDF: "Class & Section Summaries").

        Two queries total regardless of school size: one for the class/section
        structure, one grouped COUNT for every headcount. The alternative -- a count
        per section -- is an N+1 that degrades exactly as a school grows.
        """
        classes, _ = await self.classes.list(params=PageParams(page=1, size=100))
        counts = await self.sections.headcounts()

        summaries: list[ClassSummary] = []
        for school_class in sorted(classes, key=lambda c: c.level):
            sections = await self.sections.list_for_class(school_class.id)
            section_summaries = [
                SectionSummary(
                    id=s.id,
                    name=s.name,
                    capacity=s.capacity,
                    class_teacher_id=s.class_teacher_id,
                    student_count=counts.get(s.id, 0),
                )
                for s in sections
            ]
            summaries.append(
                ClassSummary(
                    id=school_class.id,
                    name=school_class.name,
                    level=school_class.level,
                    section_count=len(section_summaries),
                    student_count=sum(s.student_count for s in section_summaries),
                    sections=section_summaries,
                )
            )
        return summaries

    # -- internals ----------------------------------------------------------

    async def _assert_is_teacher(self, user_id: UUID) -> None:
        """A class teacher must be a real, active member of staff at this school.

        The lookup runs on the tenant-bound session, so a user id belonging to
        another school simply is not found -- the tenant check is implicit in RLS
        rather than an explicit school_id comparison that could be forgotten.
        """
        user = await self.session.get(User, user_id)
        if user is None or user.school_id is None:
            raise NotFoundError("Teacher not found.")
        if user.role not in (UserRole.TEACHER, UserRole.SCHOOL_ADMIN):
            raise ValidationError(
                "A class teacher must be a teacher or school admin.",
                code="INVALID_CLASS_TEACHER",
            )
