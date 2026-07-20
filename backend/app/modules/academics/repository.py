"""Academics data access. SQL only -- no business rules.

Note that no method filters on `school_id`. Tenant scoping is enforced by
PostgreSQL RLS on the connection (see db/session.py), so a query written here is
already tenant-safe. Re-filtering in Python would make a *missing* filter
survivable, which is precisely the complacency RLS exists to remove.
"""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, select

from app.common.repository import BaseRepository
from app.modules.academics.models import SchoolClass, Section
from app.modules.students.models import Student, StudentStatus


class ClassRepository(BaseRepository[SchoolClass]):
    model = SchoolClass
    sortable_fields = frozenset({"name", "level", "created_at"})

    async def get_by_name(self, name: str) -> SchoolClass | None:
        return await self.find_one(SchoolClass.name == name)

    async def get_by_level(self, level: int) -> SchoolClass | None:
        return await self.find_one(SchoolClass.level == level)


class SectionRepository(BaseRepository[Section]):
    model = Section
    sortable_fields = frozenset({"name", "created_at"})

    async def get_by_name(self, class_id: UUID, name: str) -> Section | None:
        return await self.find_one(Section.class_id == class_id, Section.name == name)

    async def list_for_class(self, class_id: UUID) -> Sequence[Section]:
        stmt = self._base_select().where(Section.class_id == class_id).order_by(Section.name)
        return (await self.session.execute(stmt)).scalars().all()

    async def enrolled_count(self, section_id: UUID) -> int:
        """Live headcount for one section, used to enforce `capacity`."""
        stmt = (
            select(func.count())
            .select_from(Student)
            .where(
                Student.section_id == section_id,
                Student.status == StudentStatus.ACTIVE,
                Student.deleted_at.is_(None),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    async def headcounts(self) -> dict[UUID, int]:
        """Enrolled students per section, for the whole (RLS-scoped) school.

        ONE grouped query, not one per section. The summaries dashboard renders
        every class and section on a single screen; doing this per section would be
        a textbook N+1 that grows with the size of the school.
        """
        stmt = (
            select(Student.section_id, func.count(Student.id))
            .where(
                Student.section_id.is_not(None),
                Student.status == StudentStatus.ACTIVE,
                Student.deleted_at.is_(None),
            )
            .group_by(Student.section_id)
        )
        rows = (await self.session.execute(stmt)).all()
        return {section_id: count for section_id, count in rows if section_id is not None}
