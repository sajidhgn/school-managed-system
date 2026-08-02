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

from uuid import UUID

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, Pagination, Sorting, require
from app.common.schemas import Page
from app.modules.academics.schemas import (
    ClassCreate,
    ClassRead,
    ClassSummary,
    ClassUpdate,
    SectionCreate,
    SectionRead,
    SectionUpdate,
)
from app.modules.academics.service import AcademicsService

router = APIRouter()


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
