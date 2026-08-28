"""Academics data access. SQL only -- no business rules.

Organization isolation comes from PostgreSQL RLS.  Campus isolation is a separate
boundary: the shared repository injects the active school for ordinary CRUD, while
the custom aggregate queries below apply the same scope explicitly.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from uuid import UUID

from sqlalchemy import func, or_, select, update

from app.common.repository import BaseRepository
from app.core.context import get_school_id
from app.modules.academics.models import (
    AcademicYear,
    ClassSubject,
    SchoolClass,
    Section,
    Subject,
    Term,
)
from app.modules.auth.models import User
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

    async def labels(self, section_ids: set[UUID]) -> dict[UUID, tuple[str, str]]:
        """section id -> (class name, section name), in ONE query.

        Exists so that "which class is this child in" has a single answer shared by
        every screen that asks. The students table, the roster and the attendance
        views all need to turn a `section_id` into something printable, and three
        separate joins would eventually disagree about whether the class or the
        section comes first.

        Not school-filtered: the caller has already been scoped by RLS, and a section
        id in hand is a section the caller was allowed to read.
        """
        if not section_ids:
            return {}
        rows = await self.session.execute(
            select(Section.id, SchoolClass.name, Section.name)
            .join(SchoolClass, SchoolClass.id == Section.class_id)
            .where(Section.id.in_(section_ids))
        )
        return {row[0]: (row[1], row[2]) for row in rows}

    async def teacher_names(self, user_ids: set[UUID]) -> dict[UUID, str]:
        """Resolve class-teacher ids to display names, in ONE query.

        Same reasoning as `headcounts`: the summaries screen renders every section at
        once, so looking a teacher up per row would be an N+1 that grows with the
        school. Called with the ids already collected from the sections, so an empty
        set short-circuits without touching the database.

        NOT filtered by school or by whether the person still teaches. This resolves a
        name that a section already stores; hiding it when someone transfers campus
        would blank the column and make an assignment that still exists look absent.
        Who may be NEWLY assigned is a different question, answered by
        `GET /schools/{id}/teachers`.
        """
        if not user_ids:
            return {}
        rows = await self.session.execute(
            select(User.id, User.full_name).where(User.id.in_(user_ids))
        )
        return {row[0]: row[1] for row in rows}

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
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(Student.school_id == school_id)
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
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(Student.school_id == school_id)
        rows = (await self.session.execute(stmt)).all()
        return {section_id: count for section_id, count in rows if section_id is not None}


class AcademicYearRepository(BaseRepository[AcademicYear]):
    model = AcademicYear
    sortable_fields = frozenset({"name", "start_date", "end_date", "created_at"})

    async def get_by_name(self, name: str) -> AcademicYear | None:
        return await self.find_one(AcademicYear.name == name)

    async def get_current(self) -> AcademicYear | None:
        """The year new work defaults to, or None if the school has not set one."""
        return await self.find_one(AcademicYear.is_current.is_(True))

    async def find_containing(self, day: date) -> AcademicYear | None:
        """The year whose bounds contain `day`.

        Used to resolve an attendance date to a year when the caller did not name
        one. Distinct from `get_current`: a register being back-filled for last June
        belongs to last year even though this year holds the flag.
        """
        return await self.find_one(
            AcademicYear.start_date <= day,
            AcademicYear.end_date >= day,
        )

    async def clear_current(self, *, except_id: UUID | None = None) -> None:
        """Demote every current year for this school.

        Runs immediately BEFORE promoting the new one, inside the same transaction.
        The partial unique index (`uq_academic_years_one_current`) makes the ordering
        load-bearing: promoting first would collide with the incumbent, and the error
        would read as a duplicate-name conflict rather than as what it is.
        """
        stmt = (
            update(AcademicYear)
            .where(AcademicYear.is_current.is_(True), AcademicYear.deleted_at.is_(None))
            .values(is_current=False)
        )
        if except_id is not None:
            stmt = stmt.where(AcademicYear.id != except_id)
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(AcademicYear.school_id == school_id)
        await self.session.execute(stmt)

    async def term_counts(self) -> dict[UUID, int]:
        """Terms per year, for the whole (RLS-scoped) school.

        ONE grouped query. The calendar screen lists every year with its term count;
        counting per year would be an N+1 that grows with the age of the school.
        """
        stmt = (
            select(Term.academic_year_id, func.count(Term.id))
            .where(Term.deleted_at.is_(None))
            .group_by(Term.academic_year_id)
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(Term.school_id == school_id)
        rows = (await self.session.execute(stmt)).all()
        return {year_id: int(count) for year_id, count in rows}


class TermRepository(BaseRepository[Term]):
    model = Term
    sortable_fields = frozenset({"name", "sequence", "start_date", "created_at"})

    async def list_for_year(self, academic_year_id: UUID) -> Sequence[Term]:
        stmt = (
            self._base_select()
            .where(Term.academic_year_id == academic_year_id)
            .order_by(Term.sequence)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def find_overlapping(
        self, academic_year_id: UUID, start: date, end: date, *, exclude_id: UUID | None = None
    ) -> Term | None:
        """A term in this year whose dates intersect [start, end].

        THE OVERLAP TEST IS `existing.start <= new.end AND existing.end >= new.start`,
        which is the standard interval-intersection predicate and the one people
        habitually get wrong by testing containment instead. Containment would accept
        a term that straddles an existing one at both edges.

        Enforced here rather than by a PostgreSQL exclusion constraint: the constraint
        needs `btree_gist`, and its violation reaches the client as raw constraint
        text rather than as "Term 2 overlaps Term 1 (12 Jan - 30 Mar)".
        """
        conditions = [
            Term.academic_year_id == academic_year_id,
            Term.start_date <= end,
            Term.end_date >= start,
        ]
        if exclude_id is not None:
            conditions.append(Term.id != exclude_id)
        return await self.find_one(*conditions)


class SubjectRepository(BaseRepository[Subject]):
    model = Subject
    sortable_fields = frozenset({"code", "name", "kind", "created_at"})

    async def get_by_code(self, code: str) -> Subject | None:
        return await self.find_one(Subject.code == code)

    async def get_by_name(self, name: str) -> Subject | None:
        return await self.find_one(Subject.name == name)

    def search_filter(self, term: str):  # type: ignore[no-untyped-def]
        pattern = f"%{term}%"
        return or_(Subject.code.ilike(pattern), Subject.name.ilike(pattern))


class ClassSubjectRepository(BaseRepository[ClassSubject]):
    model = ClassSubject
    sortable_fields = frozenset({"created_at"})

    async def get_link(self, class_id: UUID, subject_id: UUID) -> ClassSubject | None:
        return await self.find_one(
            ClassSubject.class_id == class_id, ClassSubject.subject_id == subject_id
        )

    async def list_for_class(self, class_id: UUID) -> Sequence[tuple[ClassSubject, Subject]]:
        """Curriculum rows joined to their subject, ordered by subject code.

        Returns pairs rather than relying on the `subject` relationship so the join
        is explicit and single: lazy-loading `link.subject` per row is the N+1 this
        method exists to prevent, and `selectinload` would still be two queries for
        data one join already has.
        """
        stmt = (
            self._base_select()
            .join(Subject, Subject.id == ClassSubject.subject_id)
            .where(ClassSubject.class_id == class_id, Subject.deleted_at.is_(None))
            .order_by(Subject.code)
            .add_columns(Subject)
        )
        rows = (await self.session.execute(stmt)).all()
        return [(link, subject) for link, subject in rows]

    async def classes_using(self, subject_id: UUID) -> Sequence[ClassSubject]:
        """Every curriculum row referencing a subject.

        Read before deleting a subject: the FK is RESTRICT, so without this the
        delete surfaces as a raw integrity error instead of a message naming the
        grades that still study it.
        """
        stmt = self._base_select().where(ClassSubject.subject_id == subject_id)
        return (await self.session.execute(stmt)).scalars().all()
