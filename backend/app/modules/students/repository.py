"""Student data access. SQL only."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, or_, select

from app.common.repository import BaseRepository
from app.core.context import get_school_id
from app.modules.students.models import Student, StudentEnrollment, StudentStatus


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

    async def next_admission_number(self, prefix: str, *, school_id: UUID | None = None) -> str:
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
        # Public admissions binds the database GUC directly and therefore passes
        # its verified school explicitly. Authenticated calls take the scope from
        # the access-token ContextVar, just like the generic repository paths.
        active_school_id = school_id or get_school_id()
        if active_school_id is not None:
            stmt = stmt.where(Student.school_id == active_school_id)
        used = int((await self.session.execute(stmt)).scalar_one() or 0)
        return f"{prefix}{used + 1:04d}"

    async def count_enrolled(self) -> int:
        """Active students in the current tenant -- checked against `max_students`."""
        return await self.count(Student.status == StudentStatus.ACTIVE)

    async def count_in_section(self, section_id: UUID) -> int:
        return await self.count(
            Student.section_id == section_id, Student.status == StudentStatus.ACTIVE
        )


class StudentEnrollmentRepository(BaseRepository[StudentEnrollment]):
    """Data access for the enrollment ledger.

    NOTE ON SOFT DELETE: `student_enrollments` has no `deleted_at`, so
    `BaseRepository`'s automatic `deleted_at IS NULL` filter is a no-op here (it is
    guarded on `hasattr`). Closing a row means setting `left_on`, and every query
    below that means "currently seated" says so explicitly rather than relying on
    the shared filter.
    """

    model = StudentEnrollment
    sortable_fields = frozenset({"enrolled_on", "left_on", "roll_number", "created_at"})

    async def get_open(self, student_id: UUID) -> StudentEnrollment | None:
        """The student's current placement, or None if they have never been seated.

        At most one exists -- `uq_student_enrollments_one_open` is what guarantees
        that, which is why this can return a single row rather than a list the
        caller has to disambiguate.
        """
        return await self.find_one(
            StudentEnrollment.student_id == student_id, StudentEnrollment.left_on.is_(None)
        )

    async def history(self, student_id: UUID) -> Sequence[StudentEnrollment]:
        stmt = (
            self._base_select()
            .where(StudentEnrollment.student_id == student_id)
            .order_by(StudentEnrollment.enrolled_on.desc(), StudentEnrollment.id)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def open_in_section(self, section_id: UUID) -> Sequence[StudentEnrollment]:
        """Every student currently seated in a section, in roll order.

        `NULLS LAST` so an unnumbered student sorts after the numbered ones rather
        than leading the register -- PostgreSQL's default for ASC puts NULLs last
        already, but stating it means a later switch to DESC does not silently
        reorder every printed register.
        """
        stmt = (
            self._base_select()
            .where(
                StudentEnrollment.section_id == section_id,
                StudentEnrollment.left_on.is_(None),
            )
            .order_by(StudentEnrollment.roll_number.asc().nullslast(), StudentEnrollment.id)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def roll_number_taken(
        self, section_id: UUID, academic_year_id: UUID, roll_number: str
    ) -> bool:
        return await self.exists(
            StudentEnrollment.section_id == section_id,
            StudentEnrollment.academic_year_id == academic_year_id,
            StudentEnrollment.roll_number == roll_number,
        )

    async def next_roll_number(self, section_id: UUID, academic_year_id: UUID) -> str:
        """The next free roll number in a section for a year.

        Takes MAX rather than COUNT: a section that has lost a student mid-year has
        a count of 29 and a highest roll of 30, and reusing 30 would collide with the
        partial unique index. Numeric-looking rolls are compared as integers; any
        non-numeric roll a school typed by hand is ignored for this purpose, since
        "next after A-7" has no defensible answer.

        Races under concurrent enrollment, exactly as `next_admission_number` does,
        and for the same reason: the partial unique index is the real guarantee, and
        a collision surfaces as a 409 rather than two students sharing a roll.
        """
        stmt = select(StudentEnrollment.roll_number).where(
            StudentEnrollment.section_id == section_id,
            StudentEnrollment.academic_year_id == academic_year_id,
            StudentEnrollment.roll_number.is_not(None),
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(StudentEnrollment.school_id == school_id)
        rolls = (await self.session.execute(stmt)).scalars().all()

        highest = 0
        for roll in rolls:
            if roll is not None and roll.isdigit():
                highest = max(highest, int(roll))
        return str(highest + 1)

    async def counts_by_section(self, academic_year_id: UUID) -> dict[UUID, int]:
        """Currently-seated students per section for one year.

        ONE grouped query, for the same reason `SectionRepository.headcounts` is one:
        the promotion preview screen renders every section of every class at once.
        """
        stmt = (
            select(StudentEnrollment.section_id, func.count(StudentEnrollment.id))
            .where(
                StudentEnrollment.academic_year_id == academic_year_id,
                StudentEnrollment.section_id.is_not(None),
                StudentEnrollment.left_on.is_(None),
            )
            .group_by(StudentEnrollment.section_id)
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(StudentEnrollment.school_id == school_id)
        rows = (await self.session.execute(stmt)).all()
        return {section_id: int(count) for section_id, count in rows if section_id is not None}

    async def roll_numbers(
        self, section_id: UUID, academic_year_id: UUID, student_ids: Sequence[UUID]
    ) -> dict[UUID, str]:
        """Roll numbers as they were for one section in one YEAR, closed rows included.

        =====================================================================
        WHY NOT JUST READ THE OPEN ENROLLMENT
        =====================================================================
            An attendance register printed for last March must show the roll numbers
            that were called out last March. Reading the student's CURRENT placement
            gives this year's number -- or none at all, once they have been promoted
            out of the section entirely -- so a historical register would silently
            renumber itself every time it was reopened.

            `left_on` is therefore not filtered here: the row that matters is the one
            that covered this section for this year, whether or not it is still open.
        """
        if not student_ids:
            return {}
        stmt = select(StudentEnrollment.student_id, StudentEnrollment.roll_number).where(
            StudentEnrollment.section_id == section_id,
            StudentEnrollment.academic_year_id == academic_year_id,
            StudentEnrollment.student_id.in_(student_ids),
            StudentEnrollment.roll_number.is_not(None),
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(StudentEnrollment.school_id == school_id)
        rows = (await self.session.execute(stmt)).all()
        return {student_id: roll for student_id, roll in rows if roll is not None}
