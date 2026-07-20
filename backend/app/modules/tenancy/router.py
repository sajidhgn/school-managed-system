"""Tenancy HTTP endpoints -- the Super Admin school-management surface.

WHY THIS FILE EXISTS
    Maps HTTP to `TenancyService`. Handlers are thin: parse, delegate, return. No
    business rules and no SQL live here.

INTERACTIONS
    Mounted at `/api/v1/schools` by `api/v1/router.py`.

ACCESS MODEL
    * Everything except `/schools/current` is platform-level and requires a super
      admin (the PDF's "Super Admin Dashboard" that onboards and monitors schools).
    * `/schools/current` returns the caller's OWN school and is available to any
      school-scoped user; RLS guarantees they can only ever read their own row.

    Self-service *registration* is deliberately NOT here -- it creates a user as well
    as a school, so it lives in the auth module (`POST /auth/register`).
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import CurrentSchool, DbSession, Pagination, Sorting, require_super_admin
from app.common.schemas import Page
from app.modules.tenancy.models import SchoolStatus
from app.modules.tenancy.schemas import SchoolCreate, SchoolRead, SchoolUpdate
from app.modules.tenancy.service import TenancyService

router = APIRouter()

StatusFilter = Annotated[
    SchoolStatus | None,
    Query(description="Filter schools by lifecycle status (e.g. pending_approval)."),
]


@router.get(
    "",
    response_model=Page[SchoolRead],
    summary="List schools",
    dependencies=[Depends(require_super_admin)],
)
async def list_schools(
    db: DbSession,
    params: Pagination,
    sort: Sorting,
    status_filter: StatusFilter = None,
) -> Page[SchoolRead]:
    """Paginated directory of tenants for the Super Admin dashboard."""
    return await TenancyService(db).list_schools(status=status_filter, params=params, sort=sort)


@router.post(
    "",
    response_model=SchoolRead,
    status_code=status.HTTP_201_CREATED,
    summary="Onboard a school",
    dependencies=[Depends(require_super_admin)],
)
async def create_school(payload: SchoolCreate, db: DbSession) -> SchoolRead:
    """Super-admin onboarding: provisions an already-active tenant."""
    school = await TenancyService(db).create_school(payload)
    return SchoolRead.model_validate(school)


@router.get(
    "/current",
    response_model=SchoolRead,
    summary="Get the caller's own school",
)
async def get_current_school(db: DbSession, school_id: CurrentSchool) -> SchoolRead:
    """Return the school the authenticated caller belongs to. RLS-scoped."""
    school = await TenancyService(db).get_school(school_id)
    return SchoolRead.model_validate(school)


@router.get(
    "/{school_id}",
    response_model=SchoolRead,
    summary="Get a school",
    dependencies=[Depends(require_super_admin)],
)
async def get_school(school_id: UUID, db: DbSession) -> SchoolRead:
    school = await TenancyService(db).get_school(school_id)
    return SchoolRead.model_validate(school)


@router.patch(
    "/{school_id}",
    response_model=SchoolRead,
    summary="Update a school",
    dependencies=[Depends(require_super_admin)],
)
async def update_school(school_id: UUID, payload: SchoolUpdate, db: DbSession) -> SchoolRead:
    school = await TenancyService(db).update(school_id, payload)
    return SchoolRead.model_validate(school)


@router.post(
    "/{school_id}/approve",
    response_model=SchoolRead,
    summary="Approve a pending school",
    dependencies=[Depends(require_super_admin)],
)
async def approve_school(school_id: UUID, db: DbSession) -> SchoolRead:
    school = await TenancyService(db).approve(school_id)
    return SchoolRead.model_validate(school)


@router.post(
    "/{school_id}/suspend",
    response_model=SchoolRead,
    summary="Suspend a school",
    dependencies=[Depends(require_super_admin)],
)
async def suspend_school(school_id: UUID, db: DbSession) -> SchoolRead:
    school = await TenancyService(db).suspend(school_id)
    return SchoolRead.model_validate(school)
