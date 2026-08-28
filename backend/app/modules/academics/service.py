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

from datetime import date
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditAction, record_audit
from app.common.schemas import Page, PageParams, SortParams
from app.core.context import require_organization_id, require_school_id
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.modules.academics.models import (
    AcademicYear,
    ClassSubject,
    SchoolClass,
    Section,
    Subject,
    Term,
)
from app.modules.academics.repository import (
    AcademicYearRepository,
    ClassRepository,
    ClassSubjectRepository,
    SectionRepository,
    SubjectRepository,
    TermRepository,
)
from app.modules.academics.schemas import (
    AcademicYearCreate,
    AcademicYearRead,
    AcademicYearUpdate,
    ClassCreate,
    ClassRead,
    ClassSubjectCreate,
    ClassSubjectRead,
    ClassSubjectUpdate,
    ClassSummary,
    ClassUpdate,
    SectionCreate,
    SectionRead,
    SectionSummary,
    SectionUpdate,
    SubjectCreate,
    SubjectRead,
    SubjectUpdate,
    TermCreate,
    TermRead,
    TermUpdate,
)
from app.modules.rbac.models import Membership, MembershipStatus
from app.modules.students.models import StudentEnrollment

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
            # Both from the verified JWT, never the request body.
            #
            # `organization_id` is the RLS key: omitting it does not create an orphan
            # row, because the WITH CHECK policy rejects the INSERT outright.
            # `school_id` is the campus scope, which the policy does NOT enforce --
            # it is enforced by the permission dependency having put the caller's
            # school in the context in the first place.
            organization_id=require_organization_id(),
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
            # Inherited from the parent class rather than re-read from context, so a
            # section can never end up scoped differently from the class it belongs to.
            organization_id=school_class.organization_id,
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
        """Classes -> sections -> headcounts -> class teachers (PDF: "Class & Section
        Summaries").

        THE COST MODEL: one query for the classes, one per class for its sections, and
        then exactly TWO more no matter how big the school gets -- a grouped COUNT for
        every headcount, and one lookup resolving every class-teacher id on the screen
        to a name.

        Those last two are the ones worth guarding. Both are naturally per-section, and
        writing either inside the render loop turns this into an N+1 that degrades
        precisely as a school grows -- which is why the counts are grouped and the
        teacher names are gathered up front rather than fetched per row.
        """
        classes, _ = await self.classes.list(params=PageParams(page=1, size=100))
        counts = await self.sections.headcounts()

        ordered = sorted(classes, key=lambda c: c.level)
        sections_by_class = {c.id: await self.sections.list_for_class(c.id) for c in ordered}

        # Every class-teacher on the screen resolved in one query, before the render
        # loop. Doing it inside the loop would be the N+1 this method already avoids
        # for headcounts.
        teacher_names = await self.sections.teacher_names(
            {
                s.class_teacher_id
                for sections in sections_by_class.values()
                for s in sections
                if s.class_teacher_id is not None
            }
        )

        summaries: list[ClassSummary] = []
        for school_class in ordered:
            sections = sections_by_class[school_class.id]
            section_summaries = [
                SectionSummary(
                    id=s.id,
                    name=s.name,
                    capacity=s.capacity,
                    class_teacher_id=s.class_teacher_id,
                    class_teacher_name=(
                        teacher_names.get(s.class_teacher_id)
                        if s.class_teacher_id is not None
                        else None
                    ),
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
        """A class teacher must hold an active membership at this school.

        =====================================================================
        CHECKED THROUGH `memberships`, NOT THROUGH A ROLE COLUMN ON `users`
        =====================================================================
            `users` is global and carries no role -- a person can be a teacher at one
            school and an accountant at another (spec decision D4). "Is this user a
            teacher?" is therefore not a question about the user at all; it is a
            question about a membership in a specific school.

            The lookup runs on the tenant-bound session, so a membership from another
            organization is filtered out by RLS and reads as absent. The explicit
            `school_id` comparison narrows it further to this campus -- the soft
            boundary RLS deliberately does not police.

        Any active membership qualifies, rather than a hardcoded list of role codes.
        Customers create custom roles ("Head of Year", "Senior Tutor"), and a check
        against `role.code in ('teacher', 'principal')` would reject exactly the
        staff those roles were created for.
        """
        membership = (
            await self.session.execute(
                select(Membership).where(
                    Membership.user_id == user_id,
                    Membership.school_id == require_school_id(),
                    Membership.status == MembershipStatus.ACTIVE,
                    Membership.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

        if membership is None:
            # 404 rather than 422: from the caller's perspective there is no such
            # person at this school, and confirming the user exists elsewhere on the
            # platform would leak across the tenant boundary.
            raise NotFoundError("Teacher not found at this school.")


class AcademicCalendarService:
    """Academic years and the terms inside them.

    WHY THIS IS A SEPARATE CLASS FROM `AcademicsService`
        They share a module because they are one setup screen, but they share no
        state and no rules. `AcademicsService` decides what a class may be named;
        this decides when a year runs. Folding them together would produce a
        900-line service whose two halves are read by different people, and would
        make `AcademicsService(session)` construct four repositories to answer a
        question about a section name.

    INTERACTIONS
        * `students.service` resolves the current year here when opening an
          enrollment.
        * `attendance.service` resolves the year a register's DATE falls in --
          which is not necessarily the current one; see `resolve_for_date`.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.years = AcademicYearRepository(session)
        self.terms = TermRepository(session)

    # -- years --------------------------------------------------------------

    async def create_year(self, payload: AcademicYearCreate, *, actor_id: UUID) -> AcademicYearRead:
        if await self.years.get_by_name(payload.name):
            raise ConflictError(f"An academic year named '{payload.name}' already exists.")

        values = payload.model_dump()
        make_current = values.pop("is_current")

        # Demote BEFORE inserting. The partial unique index permits one current year
        # per school, so promoting first collides with the incumbent -- and the error
        # would surface as a duplicate-key conflict that names an index, not the
        # year the registrar actually has to think about.
        if make_current:
            await self.years.clear_current()

        year = await self.years.create(
            **values,
            is_current=make_current,
            organization_id=require_organization_id(),
            school_id=require_school_id(),
        )
        await self._audit(
            AuditAction.ACADEMIC_YEAR_CREATED,
            entity_id=year.id,
            actor_id=actor_id,
            after={"name": year.name, "is_current": year.is_current},
        )
        logger.info("academic_year_created", academic_year_id=str(year.id), name=year.name)
        return self._to_read(year, term_count=0)

    async def list_years(self, params: PageParams, sort: SortParams) -> Page[AcademicYearRead]:
        rows, total = await self.years.list(params=params, sort=sort)
        counts = await self.years.term_counts()
        items = [self._to_read(y, term_count=counts.get(y.id, 0)) for y in rows]
        return Page.create(items, total, params)

    async def get_year(self, year_id: UUID) -> AcademicYear:
        """Load a year or raise. Returns the ORM object -- other services need it."""
        year = await self.years.get(year_id)
        if year is None:
            raise NotFoundError("Academic year not found.")
        return year

    async def read_year(self, year_id: UUID) -> AcademicYearRead:
        year = await self.get_year(year_id)
        counts = await self.years.term_counts()
        return self._to_read(year, term_count=counts.get(year.id, 0))

    async def update_year(
        self, year_id: UUID, payload: AcademicYearUpdate, *, actor_id: UUID
    ) -> AcademicYearRead:
        year = await self.get_year(year_id)
        values = payload.model_dump(exclude_unset=True)

        name = values.get("name")
        if name and name != year.name and await self.years.get_by_name(name):
            raise ConflictError(f"An academic year named '{name}' already exists.")

        # The bounds are validated against their FINAL values, not against whichever
        # half the PATCH happened to include. Moving only `start_date` past a
        # `end_date` the request never mentioned is the exact case a per-field check
        # lets through, and the CHECK constraint would then reject it with a
        # constraint name instead of a sentence.
        start = values.get("start_date", year.start_date)
        end = values.get("end_date", year.end_date)
        if end <= start:
            raise ValidationError(
                "The academic year must end after it starts.", code="INVALID_DATE_RANGE"
            )

        # Narrowing a year past its own terms would leave terms sitting outside the
        # year that contains them, and every report scoped by year would then quietly
        # omit part of itself.
        if "start_date" in values or "end_date" in values:
            for term in await self.terms.list_for_year(year_id):
                if term.start_date < start or term.end_date > end:
                    raise ValidationError(
                        f"'{term.name}' ({term.start_date} to {term.end_date}) would fall "
                        "outside the new year dates. Move the term first.",
                        code="TERM_OUTSIDE_YEAR",
                    )

        before = {
            "name": year.name,
            "start_date": str(year.start_date),
            "end_date": str(year.end_date),
        }
        updated = await self.years.update(year, **values)
        await self._audit(
            AuditAction.ACADEMIC_YEAR_UPDATED,
            entity_id=year_id,
            actor_id=actor_id,
            before=before,
            after={k: str(v) for k, v in values.items()},
        )
        counts = await self.years.term_counts()
        return self._to_read(updated, term_count=counts.get(year_id, 0))

    async def set_current_year(self, year_id: UUID, *, actor_id: UUID) -> AcademicYearRead:
        """Promote one year to current, demoting whichever held the flag.

        Its own endpoint rather than a field on PATCH because it is a transition
        with a side effect on a DIFFERENT row. A client PATCHing `is_current: true`
        would reasonably expect to have changed one record; it has changed two, and
        the one it did not name is the one every default in the app reads from.
        """
        year = await self.get_year(year_id)
        if year.is_current:
            return await self.read_year(year_id)

        await self.years.clear_current(except_id=year_id)
        updated = await self.years.update(year, is_current=True)
        await self._audit(
            AuditAction.ACADEMIC_YEAR_ACTIVATED,
            entity_id=year_id,
            actor_id=actor_id,
            after={"name": year.name},
        )
        logger.info("academic_year_activated", academic_year_id=str(year_id))
        counts = await self.years.term_counts()
        return self._to_read(updated, term_count=counts.get(year_id, 0))

    async def delete_year(self, year_id: UUID, *, actor_id: UUID) -> None:
        """Soft-delete a year that nothing depends on yet.

        Refused rather than cascaded when terms, enrollments or registers exist. The
        foreign keys are RESTRICT, so the database would refuse anyway -- but it
        would refuse with an integrity error naming a constraint, and the person
        deleting a year needs to be told which cohort's history they were about to
        take with it.
        """
        year = await self.get_year(year_id)

        terms = await self.terms.list_for_year(year_id)
        if terms:
            raise ConflictError(
                f"This year still has {len(terms)} term(s). Delete them before deleting the year."
            )

        enrolled = await self.session.execute(
            select(func.count())
            .select_from(StudentEnrollment)
            .where(StudentEnrollment.academic_year_id == year_id)
        )
        if int(enrolled.scalar_one() or 0):
            raise ConflictError(
                "Students were enrolled in this academic year. It cannot be deleted; "
                "its records are part of their history."
            )

        if year.is_current:
            raise ConflictError(
                "The current academic year cannot be deleted. Make another year current first."
            )

        await self.years.soft_delete(year)
        await self._audit(
            AuditAction.ACADEMIC_YEAR_DELETED,
            entity_id=year_id,
            actor_id=actor_id,
            before={"name": year.name},
        )
        logger.info("academic_year_deleted", academic_year_id=str(year_id))

    # -- resolution, used by other modules ----------------------------------

    async def require_current(self) -> AcademicYear:
        """The current year, or a 422 telling the caller to set one.

        A 422 and not a 404: the year is not missing from a URL the caller supplied,
        it is missing from the school's setup, and the fix is an administrative
        action rather than a corrected request.
        """
        year = await self.years.get_current()
        if year is None:
            raise ValidationError(
                "This school has no current academic year. Create one and mark it current "
                "before enrolling students or taking attendance.",
                code="NO_CURRENT_ACADEMIC_YEAR",
            )
        return year

    async def resolve_for_date(self, day: date) -> AcademicYear:
        """The year that CONTAINS `day`, falling back to the current one.

        Deliberately not just `require_current()`. A register being back-filled for
        last June belongs to last year, and filing it under the current year would
        make last year's attendance percentage rise months after it was published.

        The fallback matters for the summer gap, when no year contains today: a
        school opening a register on an in-service day in August should get the year
        it is preparing for, not a 422.
        """
        year = await self.years.find_containing(day)
        if year is not None:
            return year
        return await self.require_current()

    # -- terms --------------------------------------------------------------

    async def create_term(self, year_id: UUID, payload: TermCreate, *, actor_id: UUID) -> TermRead:
        year = await self.get_year(year_id)
        self._assert_inside_year(year, payload.start_date, payload.end_date)

        overlapping = await self.terms.find_overlapping(
            year_id, payload.start_date, payload.end_date
        )
        if overlapping is not None:
            raise ConflictError(
                f"These dates overlap '{overlapping.name}' "
                f"({overlapping.start_date} to {overlapping.end_date})."
            )

        term = await self.terms.create(
            **payload.model_dump(),
            academic_year_id=year.id,
            # Inherited from the parent year rather than re-read from context, so a
            # term can never end up scoped differently from the year it belongs to.
            organization_id=year.organization_id,
            school_id=year.school_id,
        )
        await self._audit(
            AuditAction.TERM_CREATED,
            entity_id=term.id,
            actor_id=actor_id,
            after={"name": term.name, "academic_year_id": str(year_id)},
        )
        return TermRead.model_validate(term)

    async def list_terms(self, year_id: UUID) -> list[TermRead]:
        await self.get_year(year_id)  # 404 for an unknown or cross-tenant year
        return [TermRead.model_validate(t) for t in await self.terms.list_for_year(year_id)]

    async def get_term(self, term_id: UUID) -> Term:
        term = await self.terms.get(term_id)
        if term is None:
            raise NotFoundError("Term not found.")
        return term

    async def update_term(self, term_id: UUID, payload: TermUpdate, *, actor_id: UUID) -> TermRead:
        term = await self.get_term(term_id)
        values = payload.model_dump(exclude_unset=True)

        start = values.get("start_date", term.start_date)
        end = values.get("end_date", term.end_date)
        if end <= start:
            raise ValidationError("A term must end after it starts.", code="INVALID_DATE_RANGE")

        year = await self.get_year(term.academic_year_id)
        self._assert_inside_year(year, start, end)

        overlapping = await self.terms.find_overlapping(
            term.academic_year_id, start, end, exclude_id=term_id
        )
        if overlapping is not None:
            raise ConflictError(
                f"These dates overlap '{overlapping.name}' "
                f"({overlapping.start_date} to {overlapping.end_date})."
            )

        before = {
            "name": term.name,
            "start_date": str(term.start_date),
            "end_date": str(term.end_date),
        }
        updated = await self.terms.update(term, **values)
        await self._audit(
            AuditAction.TERM_UPDATED,
            entity_id=term_id,
            actor_id=actor_id,
            before=before,
            after={k: str(v) for k, v in values.items()},
        )
        return TermRead.model_validate(updated)

    async def delete_term(self, term_id: UUID, *, actor_id: UUID) -> None:
        term = await self.get_term(term_id)
        await self.terms.soft_delete(term)
        await self._audit(
            AuditAction.TERM_DELETED,
            entity_id=term_id,
            actor_id=actor_id,
            before={"name": term.name},
        )

    # -- internals ----------------------------------------------------------

    @staticmethod
    def _assert_inside_year(year: AcademicYear, start: date, end: date) -> None:
        """A term must sit inside its year.

        Not merely tidy: every "this term" report is computed as a date range inside
        a year-scoped query, so a term that pokes out of its year silently returns
        fewer rows than its own dates describe.
        """
        if start < year.start_date or end > year.end_date:
            raise ValidationError(
                f"A term must fall inside {year.name} ({year.start_date} to {year.end_date}).",
                code="TERM_OUTSIDE_YEAR",
            )

    @staticmethod
    def _to_read(year: AcademicYear, *, term_count: int) -> AcademicYearRead:
        return AcademicYearRead(
            id=year.id,
            name=year.name,
            start_date=year.start_date,
            end_date=year.end_date,
            is_current=year.is_current,
            term_count=term_count,
            created_at=year.created_at,
            updated_at=year.updated_at,
        )

    async def _audit(
        self,
        action: str,
        *,
        entity_id: UUID,
        actor_id: UUID,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        await record_audit(
            self.session,
            organization_id=require_organization_id(),
            school_id=require_school_id(),
            actor_user_id=actor_id,
            action=action,
            entity_type="academic_year" if "academic_year" in action else "term",
            entity_id=entity_id,
            before=before,
            after=after,
        )


class CurriculumService:
    """Subjects, and which class studies which of them."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.subjects = SubjectRepository(session)
        self.links = ClassSubjectRepository(session)
        self.classes = ClassRepository(session)

    # -- subjects -----------------------------------------------------------

    async def create_subject(self, payload: SubjectCreate, *, actor_id: UUID) -> SubjectRead:
        code = payload.code.upper()
        # Normalised on the way in rather than compared case-insensitively on the way
        # out. "math" and "MATH" are the same subject to every human who will read a
        # report card, and a school that ends up with both has a curriculum screen
        # showing a subject twice with no way to tell them apart.
        if await self.subjects.get_by_code(code):
            raise ConflictError(f"A subject with code '{code}' already exists.")
        if await self.subjects.get_by_name(payload.name):
            raise ConflictError(f"A subject named '{payload.name}' already exists.")

        subject = await self.subjects.create(
            **{**payload.model_dump(), "code": code},
            organization_id=require_organization_id(),
            school_id=require_school_id(),
        )
        await self._audit(
            AuditAction.SUBJECT_CREATED,
            entity_type="subject",
            entity_id=subject.id,
            actor_id=actor_id,
            after={"code": subject.code, "name": subject.name},
        )
        return SubjectRead.model_validate(subject)

    async def list_subjects(
        self, params: PageParams, sort: SortParams, *, search: str | None = None
    ) -> Page[SubjectRead]:
        conditions = [self.subjects.search_filter(search)] if search else []
        rows, total = await self.subjects.list(*conditions, params=params, sort=sort)
        return Page.create([SubjectRead.model_validate(r) for r in rows], total, params)

    async def get_subject(self, subject_id: UUID) -> Subject:
        subject = await self.subjects.get(subject_id)
        if subject is None:
            raise NotFoundError("Subject not found.")
        return subject

    async def update_subject(
        self, subject_id: UUID, payload: SubjectUpdate, *, actor_id: UUID
    ) -> SubjectRead:
        subject = await self.get_subject(subject_id)
        values = payload.model_dump(exclude_unset=True)
        if "code" in values and values["code"] is not None:
            values["code"] = values["code"].upper()

        code = values.get("code")
        if code and code != subject.code and await self.subjects.get_by_code(code):
            raise ConflictError(f"A subject with code '{code}' already exists.")
        name = values.get("name")
        if name and name != subject.name and await self.subjects.get_by_name(name):
            raise ConflictError(f"A subject named '{name}' already exists.")

        before = {"code": subject.code, "name": subject.name, "kind": subject.kind.value}
        updated = await self.subjects.update(subject, **values)
        await self._audit(
            AuditAction.SUBJECT_UPDATED,
            entity_type="subject",
            entity_id=subject_id,
            actor_id=actor_id,
            before=before,
            after={k: str(v) for k, v in values.items()},
        )
        return SubjectRead.model_validate(updated)

    async def delete_subject(self, subject_id: UUID, *, actor_id: UUID) -> None:
        """Soft-delete a subject no class studies.

        The FK from `class_subjects` is RESTRICT, so the database would refuse this
        anyway -- but it would refuse with an integrity error naming a constraint.
        Reading the dependents first lets the refusal name the grades, which is the
        information the person deleting it actually needs.
        """
        subject = await self.get_subject(subject_id)
        used_by = await self.links.classes_using(subject_id)
        if used_by:
            raise ConflictError(
                f"{len(used_by)} class(es) still study '{subject.name}'. "
                "Remove it from their curriculum first."
            )
        await self.subjects.soft_delete(subject)
        await self._audit(
            AuditAction.SUBJECT_DELETED,
            entity_type="subject",
            entity_id=subject_id,
            actor_id=actor_id,
            before={"code": subject.code, "name": subject.name},
        )

    # -- curriculum ---------------------------------------------------------

    async def list_curriculum(self, class_id: UUID) -> list[ClassSubjectRead]:
        await self._get_class(class_id)  # 404 for an unknown or cross-tenant class
        return [
            self._to_read(link, subject)
            for link, subject in await self.links.list_for_class(class_id)
        ]

    async def add_to_curriculum(
        self, class_id: UUID, payload: ClassSubjectCreate, *, actor_id: UUID
    ) -> ClassSubjectRead:
        school_class = await self._get_class(class_id)
        subject = await self.get_subject(payload.subject_id)

        if await self.links.get_link(class_id, subject.id):
            raise ConflictError(f"'{subject.name}' is already on this class's curriculum.")
        if payload.teacher_id is not None:
            await AcademicsService(self.session)._assert_is_teacher(payload.teacher_id)

        link = await self.links.create(
            **payload.model_dump(),
            class_id=school_class.id,
            organization_id=school_class.organization_id,
            school_id=school_class.school_id,
        )
        await self._audit(
            AuditAction.CLASS_SUBJECT_ADDED,
            entity_type="class_subject",
            entity_id=link.id,
            actor_id=actor_id,
            after={"class_id": str(class_id), "subject": subject.code},
        )
        return self._to_read(link, subject)

    async def update_curriculum_entry(
        self, link_id: UUID, payload: ClassSubjectUpdate, *, actor_id: UUID
    ) -> ClassSubjectRead:
        link = await self._get_link(link_id)
        values = payload.model_dump(exclude_unset=True)
        if values.get("teacher_id") is not None:
            await AcademicsService(self.session)._assert_is_teacher(values["teacher_id"])

        before = {
            "teacher_id": str(link.teacher_id) if link.teacher_id else None,
            "weekly_periods": link.weekly_periods,
        }
        updated = await self.links.update(link, **values)
        await self._audit(
            AuditAction.CLASS_SUBJECT_UPDATED,
            entity_type="class_subject",
            entity_id=link_id,
            actor_id=actor_id,
            before=before,
            after={k: str(v) for k, v in values.items()},
        )
        return self._to_read(updated, await self.get_subject(updated.subject_id))

    async def remove_from_curriculum(self, link_id: UUID, *, actor_id: UUID) -> None:
        link = await self._get_link(link_id)
        await self.links.soft_delete(link)
        await self._audit(
            AuditAction.CLASS_SUBJECT_REMOVED,
            entity_type="class_subject",
            entity_id=link_id,
            actor_id=actor_id,
            before={"class_id": str(link.class_id), "subject_id": str(link.subject_id)},
        )

    # -- internals ----------------------------------------------------------

    async def _get_class(self, class_id: UUID) -> SchoolClass:
        school_class = await self.classes.get(class_id)
        if school_class is None:
            raise NotFoundError("Class not found.")
        return school_class

    async def _get_link(self, link_id: UUID) -> ClassSubject:
        link = await self.links.get(link_id)
        if link is None:
            raise NotFoundError("Curriculum entry not found.")
        return link

    @staticmethod
    def _to_read(link: ClassSubject, subject: Subject) -> ClassSubjectRead:
        return ClassSubjectRead(
            id=link.id,
            class_id=link.class_id,
            subject_id=subject.id,
            subject_code=subject.code,
            subject_name=subject.name,
            subject_kind=subject.kind,
            teacher_id=link.teacher_id,
            weekly_periods=link.weekly_periods,
            created_at=link.created_at,
            updated_at=link.updated_at,
        )

    async def _audit(
        self,
        action: str,
        *,
        entity_type: str,
        entity_id: UUID,
        actor_id: UUID,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        await record_audit(
            self.session,
            organization_id=require_organization_id(),
            school_id=require_school_id(),
            actor_user_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before=before,
            after=after,
        )
