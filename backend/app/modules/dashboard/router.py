"""Dashboard analytics HTTP endpoint.

`CurrentAuth`, not `require(...)`, for the same reason as `/search`: authorisation
is per section, decided in `DashboardService`, and any authenticated member gets the
subset of the board they could already have read module by module -- including the
teacher's boundary: without `class:view_all` the counts cover their own sections.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.api.deps import CurrentAuth, DbSession
from app.modules.academics.teaching_scope import assigned_teacher
from app.modules.dashboard.schemas import DashboardAnalytics
from app.modules.dashboard.service import DashboardService

router = APIRouter()


@router.get(
    "/analytics",
    response_model=DashboardAnalytics,
    summary="Students, attendance, fees and exams at a glance",
)
async def analytics(ctx: CurrentAuth, db: DbSession) -> DashboardAnalytics:
    """The landing screen's numbers, in one round trip.

    Sections the caller may not read come back as null. Scoped to the active campus,
    or the whole organization for a principal with no campus open.
    """
    return await DashboardService(
        db, ctx.permissions, teacher_id=assigned_teacher(ctx.user_id, ctx.permissions)
    ).analytics()
