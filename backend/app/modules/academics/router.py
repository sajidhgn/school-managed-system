"""Academics HTTP endpoints -- class and section setup.

Handlers are one line of delegation each. Anything longer belongs in the service.

AUTHORISATION SHAPE
    Every route names the permission it needs, resolved through `require()` against
    the shared catalog. Reads need `class:read`, writes need `class:create`,
    `class:update` or `class:delete`.

    This replaced a `require_roles("school_admin")` guard. A role-name check cannot
    express the custom roles customers create -- a school that defines "Head of
    Curriculum" and expects them to manage classes would have to be given the full
    admin role instead, which is how least-privilege quietly stops being practised.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import AuthContext, DbSession, Pagination, SearchQuery, Sorting, require
from app.common.schemas import Page
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
    SectionUpdate,
    SubjectCreate,
    SubjectRead,
    SubjectUpdate,
    TermCreate,
    TermRead,
    TermUpdate,
)
from app.modules.academics.service import (
    AcademicCalendarService,
    AcademicsService,
    CurriculumService,
)
from app.modules.students.schemas import EnrollmentBackfillResult, SectionRosterEntry
from app.modules.students.service import EnrollmentService

router = APIRouter()

# The calendar and the curriculum are gated on their OWN permission codes rather
# than on `class:*`. A registrar who defines terms is not necessarily the person who
# renames a section, and -- more to the point -- `calendar:read` is granted to the
# teacher role while `class:create` is not, so sharing a code would either hand
# every teacher the ability to restructure the school or hide the term list from
# the people who teach in it.
CalendarReadCtx = Annotated[AuthContext, Depends(require("calendar:read"))]
CalendarManageCtx = Annotated[AuthContext, Depends(require("calendar:manage"))]
SubjectReadCtx = Annotated[AuthContext, Depends(require("subject:read"))]
SubjectManageCtx = Annotated[AuthContext, Depends(require("subject:manage"))]
StudentReadCtx = Annotated[AuthContext, Depends(require("student:read"))]
PromoteCtx = Annotated[AuthContext, Depends(require("student:promote"))]


# ---------------------------------------------------------------------------
# Summaries
# ---------------------------------------------------------------------------


@router.get(
    "/summary",
    response_model=list[ClassSummary],
    summary="Class and section summaries with headcounts",
    dependencies=[Depends(require("class:read"))],
)
async def class_summaries(db: DbSession) -> list[ClassSummary]:
    """Dashboard view: every class, its sections, and students per section."""
    return await AcademicsService(db).summaries()


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------
#
# NOTE ON ROUTE ORDER: `/summary` is declared BEFORE `/{class_id}`. Starlette
# matches in declaration order, so the reverse would make `/summary` parse as a
# class_id and fail with a 422 UUID error.


@router.get(
    "",
    response_model=Page[ClassRead],
    summary="List classes",
    dependencies=[Depends(require("class:read"))],
)
async def list_classes(db: DbSession, params: Pagination, sort: Sorting) -> Page[ClassRead]:
    return await AcademicsService(db).list_classes(params, sort)


@router.post(
    "",
    response_model=ClassRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a class",
    dependencies=[Depends(require("class:create"))],
)
async def create_class(payload: ClassCreate, db: DbSession) -> ClassRead:
    return await AcademicsService(db).create_class(payload)


@router.get(
    "/{class_id}",
    response_model=ClassRead,
    summary="Get a class",
    dependencies=[Depends(require("class:read"))],
)
async def get_class(class_id: UUID, db: DbSession) -> ClassRead:
    return ClassRead.model_validate(await AcademicsService(db).get_class(class_id))


@router.patch(
    "/{class_id}",
    response_model=ClassRead,
    summary="Update a class",
    dependencies=[Depends(require("class:update"))],
)
async def update_class(class_id: UUID, payload: ClassUpdate, db: DbSession) -> ClassRead:
    return await AcademicsService(db).update_class(class_id, payload)


@router.delete(
    "/{class_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an empty class",
    dependencies=[Depends(require("class:delete"))],
)
async def delete_class(class_id: UUID, db: DbSession) -> None:
    await AcademicsService(db).delete_class(class_id)


# ---------------------------------------------------------------------------
# Sections (nested under their class)
# ---------------------------------------------------------------------------


@router.get(
    "/{class_id}/sections",
    response_model=list[SectionRead],
    summary="List the sections of a class",
    dependencies=[Depends(require("class:read"))],
)
async def list_sections(class_id: UUID, db: DbSession) -> list[SectionRead]:
    return await AcademicsService(db).list_sections(class_id)


@router.post(
    "/{class_id}/sections",
    response_model=SectionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a section to a class",
    dependencies=[Depends(require("class:create"))],
)
async def create_section(class_id: UUID, payload: SectionCreate, db: DbSession) -> SectionRead:
    return await AcademicsService(db).create_section(class_id, payload)


@router.patch(
    "/sections/{section_id}",
    response_model=SectionRead,
    summary="Update a section",
    dependencies=[Depends(require("class:update"))],
)
async def update_section(section_id: UUID, payload: SectionUpdate, db: DbSession) -> SectionRead:
    return await AcademicsService(db).update_section(section_id, payload)


@router.delete(
    "/sections/{section_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an empty section",
    dependencies=[Depends(require("class:delete"))],
)
async def delete_section(section_id: UUID, db: DbSession) -> None:
    await AcademicsService(db).delete_section(section_id)


# ---------------------------------------------------------------------------
# Curriculum, nested under the class it belongs to
# ---------------------------------------------------------------------------
#
# `/classes/curriculum/{id}` is declared BEFORE `/classes/{class_id}/subjects` for
# the same reason `/summary` leads the class routes: Starlette matches in
# declaration order, and the reverse would let a two-segment curriculum path be
# parsed as a class id.


@router.patch(
    "/curriculum/{link_id}",
    response_model=ClassSubjectRead,
    summary="Change a curriculum entry's teacher or period count",
)
async def update_curriculum_entry(
    link_id: UUID, payload: ClassSubjectUpdate, db: DbSession, ctx: SubjectManageCtx
) -> ClassSubjectRead:
    return await CurriculumService(db).update_curriculum_entry(
        link_id, payload, actor_id=ctx.user_id
    )


@router.delete(
    "/curriculum/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove a subject from a class's curriculum",
)
async def remove_from_curriculum(link_id: UUID, db: DbSession, ctx: SubjectManageCtx) -> None:
    await CurriculumService(db).remove_from_curriculum(link_id, actor_id=ctx.user_id)


@router.get(
    "/{class_id}/subjects",
    response_model=list[ClassSubjectRead],
    summary="The subjects this class studies",
)
async def list_curriculum(
    class_id: UUID, db: DbSession, _ctx: SubjectReadCtx
) -> list[ClassSubjectRead]:
    return await CurriculumService(db).list_curriculum(class_id)


@router.post(
    "/{class_id}/subjects",
    response_model=ClassSubjectRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a subject to a class's curriculum",
)
async def add_to_curriculum(
    class_id: UUID, payload: ClassSubjectCreate, db: DbSession, ctx: SubjectManageCtx
) -> ClassSubjectRead:
    return await CurriculumService(db).add_to_curriculum(class_id, payload, actor_id=ctx.user_id)


# ===========================================================================
# The academic calendar -- mounted at /academic-years
# ===========================================================================
#
# A SEPARATE ROUTER RATHER THAN MORE PATHS UNDER `/classes`. A year is not a
# property of a class -- classes are recreated every year and the year outlives
# them -- and `/classes/academic-years/{id}/terms` would say the opposite in the
# one place clients read the domain model from.

calendar_router = APIRouter()


@calendar_router.get(
    "",
    response_model=Page[AcademicYearRead],
    summary="List academic years",
)
async def list_academic_years(
    db: DbSession, params: Pagination, sort: Sorting, _ctx: CalendarReadCtx
) -> Page[AcademicYearRead]:
    return await AcademicCalendarService(db).list_years(params, sort)


@calendar_router.post(
    "",
    response_model=AcademicYearRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an academic year",
)
async def create_academic_year(
    payload: AcademicYearCreate, db: DbSession, ctx: CalendarManageCtx
) -> AcademicYearRead:
    return await AcademicCalendarService(db).create_year(payload, actor_id=ctx.user_id)


@calendar_router.get(
    "/current",
    response_model=AcademicYearRead,
    summary="The year new work defaults to",
)
async def current_academic_year(db: DbSession, _ctx: CalendarReadCtx) -> AcademicYearRead:
    """422 with `NO_CURRENT_ACADEMIC_YEAR` when the school has not set one.

    Declared before `/{year_id}` so "current" is never parsed as a year id.
    """
    service = AcademicCalendarService(db)
    return await service.read_year((await service.require_current()).id)


@calendar_router.get(
    "/{year_id}",
    response_model=AcademicYearRead,
    summary="Get an academic year",
)
async def get_academic_year(
    year_id: UUID, db: DbSession, _ctx: CalendarReadCtx
) -> AcademicYearRead:
    return await AcademicCalendarService(db).read_year(year_id)


@calendar_router.patch(
    "/{year_id}",
    response_model=AcademicYearRead,
    summary="Edit an academic year's name or dates",
)
async def update_academic_year(
    year_id: UUID, payload: AcademicYearUpdate, db: DbSession, ctx: CalendarManageCtx
) -> AcademicYearRead:
    return await AcademicCalendarService(db).update_year(year_id, payload, actor_id=ctx.user_id)


@calendar_router.post(
    "/{year_id}/set-current",
    response_model=AcademicYearRead,
    summary="Make this the year new work defaults to",
)
async def set_current_academic_year(
    year_id: UUID, db: DbSession, ctx: CalendarManageCtx
) -> AcademicYearRead:
    """Its own endpoint because promoting one year DEMOTES another.

    A PATCH setting `is_current: true` would look like a single-record edit while
    silently rewriting the row every default in the app reads from.
    """
    return await AcademicCalendarService(db).set_current_year(year_id, actor_id=ctx.user_id)


@calendar_router.delete(
    "/{year_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an academic year nothing depends on",
)
async def delete_academic_year(year_id: UUID, db: DbSession, ctx: CalendarManageCtx) -> None:
    await AcademicCalendarService(db).delete_year(year_id, actor_id=ctx.user_id)


@calendar_router.get(
    "/{year_id}/terms",
    response_model=list[TermRead],
    summary="List the terms of an academic year",
)
async def list_terms(year_id: UUID, db: DbSession, _ctx: CalendarReadCtx) -> list[TermRead]:
    return await AcademicCalendarService(db).list_terms(year_id)


@calendar_router.post(
    "/{year_id}/terms",
    response_model=TermRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a term to an academic year",
)
async def create_term(
    year_id: UUID, payload: TermCreate, db: DbSession, ctx: CalendarManageCtx
) -> TermRead:
    return await AcademicCalendarService(db).create_term(year_id, payload, actor_id=ctx.user_id)


@calendar_router.patch(
    "/terms/{term_id}",
    response_model=TermRead,
    summary="Edit a term",
)
async def update_term(
    term_id: UUID, payload: TermUpdate, db: DbSession, ctx: CalendarManageCtx
) -> TermRead:
    return await AcademicCalendarService(db).update_term(term_id, payload, actor_id=ctx.user_id)


@calendar_router.delete(
    "/terms/{term_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a term",
)
async def delete_term(term_id: UUID, db: DbSession, ctx: CalendarManageCtx) -> None:
    await AcademicCalendarService(db).delete_term(term_id, actor_id=ctx.user_id)


# ===========================================================================
# Subjects -- mounted at /subjects
# ===========================================================================

subjects_router = APIRouter()


@subjects_router.get(
    "",
    response_model=Page[SubjectRead],
    summary="List and search subjects",
)
async def list_subjects(
    db: DbSession,
    params: Pagination,
    sort: Sorting,
    _ctx: SubjectReadCtx,
    search: SearchQuery = None,
) -> Page[SubjectRead]:
    return await CurriculumService(db).list_subjects(params, sort, search=search)


@subjects_router.post(
    "",
    response_model=SubjectRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a subject",
)
async def create_subject(
    payload: SubjectCreate, db: DbSession, ctx: SubjectManageCtx
) -> SubjectRead:
    return await CurriculumService(db).create_subject(payload, actor_id=ctx.user_id)


@subjects_router.get(
    "/{subject_id}",
    response_model=SubjectRead,
    summary="Get a subject",
)
async def get_subject(subject_id: UUID, db: DbSession, _ctx: SubjectReadCtx) -> SubjectRead:
    return SubjectRead.model_validate(await CurriculumService(db).get_subject(subject_id))


@subjects_router.patch(
    "/{subject_id}",
    response_model=SubjectRead,
    summary="Edit a subject",
)
async def update_subject(
    subject_id: UUID, payload: SubjectUpdate, db: DbSession, ctx: SubjectManageCtx
) -> SubjectRead:
    return await CurriculumService(db).update_subject(subject_id, payload, actor_id=ctx.user_id)


@subjects_router.delete(
    "/{subject_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a subject no class studies",
)
async def delete_subject(subject_id: UUID, db: DbSession, ctx: SubjectManageCtx) -> None:
    await CurriculumService(db).delete_subject(subject_id, actor_id=ctx.user_id)


# ---------------------------------------------------------------------------
# The class register, read from the enrollment ledger
# ---------------------------------------------------------------------------


@router.get(
    "/sections/{section_id}/roster",
    response_model=list[SectionRosterEntry],
    summary="The class register for a section, in roll order",
)
async def section_roster(
    section_id: UUID, db: DbSession, _ctx: StudentReadCtx
) -> list[SectionRosterEntry]:
    """Gated on `student:read`, not `class:read`.

    The response is a list of children with their guardian's phone number on it.
    That is student data that happens to be reached through a section, and letting
    `class:read` -- which exists so staff can see the school's structure -- return it
    would make the structure permission a back door into the directory.
    """
    return await EnrollmentService(db).roster(section_id)


@calendar_router.post(
    "/{year_id}/enrollments/backfill",
    response_model=EnrollmentBackfillResult,
    summary="Open enrollment history for students who predate the calendar",
)
async def backfill_enrollments(
    year_id: UUID, db: DbSession, ctx: PromoteCtx
) -> EnrollmentBackfillResult:
    """One-off catch-up for installations that had students before they had a year.

    The migration that created `student_enrollments` deliberately populated nothing:
    an enrollment needs an academic year, and no school had one until it created one.
    This is that population, run against an explicit year rather than a guessed one.

    Idempotent -- students who already have an open enrollment are counted and left
    alone -- so a retry after a timeout is safe.

    Gated on `student:promote` rather than `calendar:manage`: it writes a row per
    student, which is the same bulk, whole-school blast radius promotion has.
    """
    return await EnrollmentService(db).backfill(year_id, actor_id=ctx.user_id)
