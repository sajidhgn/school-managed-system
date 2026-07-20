"""Student data access. SQL only."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select

from app.common.repository import BaseRepository
from app.modules.students.models import Student, StudentStatus


class StudentRepository(BaseRepository[Student]):
    model = Student
    sortable_fields = frozenset(
        {"admission_number", "first_name", "last_name", "status", "enrolled_on", "created_at"}
    )

    async def get_by_admission_number(self, number: str) -> Student | None:
        return await self.find_one(Student.admission_number == number)

    async def admission_number_taken(self, number: str) -> bool:
        return await self.exists(Student.admission_number == number)

    def search_filter(self, term: str):  # type: ignore[no-untyped-def]
        """Case-insensitive match across name and admission number.

        ILIKE with a leading wildcard cannot use a btree index; `pg_trgm` (installed
        by init-db.sql) is what keeps this usable, and a GIN trigram index is the
        follow-up when the global-search omnibar lands. Parameterised, never
        interpolated -- the term is raw client input.
        """
        pattern = f"%{term}%"
        return or_(
            Student.first_name.ilike(pattern),
            Student.last_name.ilike(pattern),
            Student.admission_number.ilike(pattern),
        )

    async def next_admission_number(self, prefix: str) -> str:
        """Generate the next sequential number for a prefix, e.g. "2026-0007".

        Counts existing rows for the prefix and adds one. This races under
        concurrent submissions, which is why the caller relies on the
        `uq_students_school_id_admission_number` constraint as the real guarantee --
        a collision surfaces as a 409 from the IntegrityError handler rather than
        two students silently sharing a roll number.
        """
        stmt = (
            select(func.count())
            .select_from(Student)
            .where(Student.admission_number.startswith(prefix))
        )
        used = int((await self.session.execute(stmt)).scalar_one() or 0)
        return f"{prefix}{used + 1:04d}"

    async def count_enrolled(self) -> int:
        """Active students in the current tenant -- checked against `max_students`."""
        return await self.count(Student.status == StudentStatus.ACTIVE)

    async def count_in_section(self, section_id: UUID) -> int:
        return await self.count(
            Student.section_id == section_id, Student.status == StudentStatus.ACTIVE
        )
