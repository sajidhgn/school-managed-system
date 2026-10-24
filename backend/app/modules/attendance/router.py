"""Attendance HTTP endpoints -- registers, marking, and the reports read off them.

Handlers are one line of delegation each. Anything longer belongs in the service.

AUTHORISATION SHAPE
    Three codes, and the split between the second and the third is the module's
    whole integrity story:

        attendance:read    see registers and reports
        attendance:mark    open a register, set statuses, submit it -- until the
                           day after its date is over, when the register LOCKS
        attendance:amend   change or reopen a register that was already SUBMITTED,
                           or one that has locked

    A system where the person who records absences can also erase them has no
    attendance record, only an attendance opinion. `attendance:amend` is `dangerous`
    in the catalog, is absent from the default teacher role, and every action it
    unlocks writes before/after into `audit_logs` with the reason the caller gave.

    This is the same separation `fee:collect` and `fee:void` draw across a cash
    drawer, applied to the register a truancy referral is built from.

WHY MARKING IS A PATCH ON THE REGISTER AND NOT A POST PER STUDENT
    A teacher marks four absentees out of thirty in one interaction, on a phone, on
    a school's wifi. Thirty requests -- or four, each of which can fail
    independently and leave the register half-changed -- is the wrong unit. One
    request carrying the changed entries is atomic, retryable, and produces one
    audit batch.

TEACHERS SEE THEIR OWN SECTIONS
    A caller without `class:view_all` is bound to the sections they are assigned to
    (`academics/teaching_scope.py`). Every handler passes `teacher_id` -- None for
    an unbound caller -- and the service turns anything outside it into a 404.

ROUTE ORDER IS LOAD-BEARING
    Starlette matches in declaration order. Every literal segment (`/today`,
    `/analytics`, `/students...`, `/sections/...`) is declared BEFORE the
    `/{session_id}` pattern that would otherwise swallow it and fail with a 422 UUID
    error.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, status

from app.api.deps import AuthContext, DbSession, Pagination, SearchQuery, Sorting, require
from app.common.schemas import Page
from app.modules.academics.teaching_scope import assigned_teacher
from app.modules.attendance.analytics import (
    DEFAULT_MIN_SESSIONS,
    DEFAULT_THRESHOLD,
    AttendanceAnalyticsService,
)
from app.modules.attendance.models import AttendanceSessionStatus
from app.modules.attendance.schemas import (
    AttendanceAnalytics,
    AttendanceMarkRequest,
    AttendanceSessionDetail,
    AttendanceSessionOpen,
    AttendanceSessionRead,
    DailyOverview,
    SectionAttendanceReport,
    StudentAttendanceCalendar,
    StudentAttendancePage,
    StudentAttendanceSummary,
)
from app.modules.attendance.service import AttendanceService

router = APIRouter()

ReadCtx = Annotated[AuthContext, Depends(require("attendance:read"))]
MarkCtx = Annotated[AuthContext, Depends(require("attendance:mark"))]
AmendCtx = Annotated[AuthContext, Depends(require("attendance:amend"))]


def _teacher(ctx: AuthContext) -> UUID | None:
    return assigned_teacher(ctx.user_id, ctx.permissions)


# ---------------------------------------------------------------------------
# Registers
# ---------------------------------------------------------------------------


@router.get(
    "/today",
    response_model=DailyOverview,
    summary="Every section and whether its register has been taken",
)
async def daily_overview(
    db: DbSession,
    ctx: ReadCtx,
    session_date: date | None = Query(default=None, alias="date", description="Defaults to today."),
) -> DailyOverview:
    """The head teacher's morning chase list.

    `session_id: null` means nobody has opened that section's register -- a state a
    flat attendance table cannot distinguish from "everybody was present".
    """
    return await AttendanceService(db).daily_overview(session_date, teacher_id=_teacher(ctx))


# ---------------------------------------------------------------------------
# Analytics -- read-only, `attendance:read`, teacher-bounded like every read above
# ---------------------------------------------------------------------------
#
# All three count SUBMITTED WHOLE-DAY registers only, under the module's percentage
# rules; see `analytics.py` for why the whole-day register is the unit and why
# "school days" is a proxy. Literal paths, so declared above `/{session_id}`.


@router.get(
    "/analytics",
    response_model=AttendanceAnalytics,
    summary="Attendance by class and section over a date range, with at-risk students",
)
async def attendance_analytics(
    db: DbSession,
    ctx: ReadCtx,
    from_date: date | None = Query(
        default=None, description="Inclusive. Defaults to 29 days before `to_date`."
    ),
    to_date: date | None = Query(default=None, description="Inclusive. Defaults to today."),
    class_id: UUID | None = Query(default=None, description="Only this class's sections."),
    threshold: float = Query(
        default=DEFAULT_THRESHOLD,
        ge=0,
        le=100,
        description="A student below this percentage over the range is at risk.",
    ),
    min_sessions: int = Query(
        default=DEFAULT_MIN_SESSIONS,
        ge=1,
        le=366,
        description="Counted registers a student needs before they can be flagged.",
    ),
) -> AttendanceAnalytics:
    """The head teacher's class-by-class view.

    Per-section rates against the previous period of equal length, marking coverage
    against the days the school was marking, today's register state, a daily trend,
    a weekday pattern, the students under `threshold`, and the today / this month /
    last month / year-to-date headline. A teacher without `class:view_all` gets the
    same view of their own sections only. Ranges over 366 days are refused.
    """
    return await AttendanceAnalyticsService(db).analytics(
        from_date=from_date,
        to_date=to_date,
        class_id=class_id,
        threshold=threshold,
        min_sessions=min_sessions,
        teacher_id=_teacher(ctx),
    )


@router.get(
    "/students",
    response_model=StudentAttendancePage,
    summary="Every student's attendance: today, this month, last month and overall",
)
async def student_attendance_list(
    db: DbSession,
    params: Pagination,
    sort: Sorting,
    ctx: ReadCtx,
    search: SearchQuery = None,
    class_id: UUID | None = Query(default=None, description="Students seated in this class."),
    section_id: UUID | None = Query(default=None, description="Students seated in this section."),
    from_date: date | None = Query(
        default=None,
        description="Start of the `overall` window. Defaults to the academic year's start.",
    ),
    to_date: date | None = Query(
        default=None, description="End of the `overall` window. Defaults to today."
    ),
) -> StudentAttendancePage:
    """One row per active student the caller may see, worst overall rate first.

    `sort_by` is one of `overall` (default), `this_month`, `previous_month`, `name`,
    `admission_number`, `roll_number`, `class`. `q` matches a name or admission
    number anywhere, or a roll number exactly. `today_register` tells "not marked
    yet" apart from "present"; `today_status` is set only once the register is
    submitted.
    """
    return await AttendanceAnalyticsService(db).students(
        params,
        sort,
        from_date=from_date,
        to_date=to_date,
        class_id=class_id,
        section_id=section_id,
        search=search,
        teacher_id=_teacher(ctx),
    )


@router.get(
    "/students/{student_id}/calendar",
    response_model=StudentAttendanceCalendar,
    summary="One student's attendance day by day, with a rate per month",
)
async def student_attendance_calendar(
    student_id: UUID,
    db: DbSession,
    ctx: ReadCtx,
    from_date: date | None = Query(
        default=None, description="Inclusive. Defaults to the academic year's start."
    ),
    to_date: date | None = Query(default=None, description="Inclusive. Defaults to today."),
) -> StudentAttendanceCalendar:
    """The drill-down behind a student row: every whole-day register the child is
    on, the month-by-month rates, and the rate over the whole range. A draft day
    carries no status. 404 -- worded as for an unknown id -- for a student outside a
    teacher's sections."""
    return await AttendanceAnalyticsService(db).student_calendar(
        student_id, from_date=from_date, to_date=to_date, teacher_id=_teacher(ctx)
    )


@router.get(
    "",
    response_model=Page[AttendanceSessionRead],
    summary="List attendance registers",
)
async def list_sessions(
    db: DbSession,
    params: Pagination,
    sort: Sorting,
    ctx: ReadCtx,
    section_id: UUID | None = Query(default=None, description="Filter by section."),
    from_date: date | None = Query(default=None, description="Inclusive lower bound."),
    to_date: date | None = Query(default=None, description="Inclusive upper bound."),
    session_status: AttendanceSessionStatus | None = Query(
        default=None,
        alias="status",
        description="Filter by register state, e.g. `draft` for what is still open.",
    ),
) -> Page[AttendanceSessionRead]:
    return await AttendanceService(db).list_sessions(
        params,
        sort,
        section_id=section_id,
        from_date=from_date,
        to_date=to_date,
        session_status=session_status,
        teacher_id=_teacher(ctx),
    )


@router.post(
    "",
    response_model=AttendanceSessionDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Open a register for a section, pre-filled from its roster",
)
async def open_session(
    payload: AttendanceSessionOpen, db: DbSession, ctx: MarkCtx
) -> AttendanceSessionDetail:
    """IDEMPOTENT: opening a register that already exists returns it.

    Two teachers tapping "take attendance" at once, or one tapping twice on a slow
    connection, must not produce two registers for one lesson -- and a 409 from the
    unique constraint is not something either of them can act on.

    Every student on the roster is written in as `present`; the teacher then flips
    the exceptions. See `AttendanceService` for why the register is pre-filled.
    """
    return await AttendanceService(db).open_session(
        payload,
        actor_id=ctx.user_id,
        may_amend=ctx.has("attendance:amend"),
        teacher_id=_teacher(ctx),
    )


@router.get(
    "/{session_id}",
    response_model=AttendanceSessionDetail,
    summary="One register with every line, in roll order",
)
async def get_session(session_id: UUID, db: DbSession, ctx: ReadCtx) -> AttendanceSessionDetail:
    return await AttendanceService(db).detail(session_id, teacher_id=_teacher(ctx))


@router.patch(
    "/{session_id}/entries",
    response_model=AttendanceSessionDetail,
    summary="Set statuses for some of the students on a register",
)
async def mark_attendance(
    session_id: UUID, payload: AttendanceMarkRequest, db: DbSession, ctx: MarkCtx
) -> AttendanceSessionDetail:
    """Partial: students not named keep the status they already have.

    On a SUBMITTED register this becomes an AMENDMENT -- it requires
    `attendance:amend` as well, requires a `reason`, and writes one audit row per
    changed student. A LOCKED register (past the day after its date) refuses
    `attendance:mark` alone with `ATTENDANCE_LOCKED`. The permission is resolved here
    and passed to the service as a flag, so the service stays callable from a CLI or a
    worker.
    """
    return await AttendanceService(db).mark(
        session_id,
        payload,
        actor_id=ctx.user_id,
        may_amend=ctx.has("attendance:amend"),
        teacher_id=_teacher(ctx),
    )


@router.post(
    "/{session_id}/submit",
    response_model=AttendanceSessionDetail,
    summary="Assert that a register is complete and correct",
)
async def submit_session(session_id: UUID, db: DbSession, ctx: MarkCtx) -> AttendanceSessionDetail:
    """From here the register feeds reports and absence alerts, and further changes
    need `attendance:amend`."""
    return await AttendanceService(db).submit(
        session_id,
        actor_id=ctx.user_id,
        may_amend=ctx.has("attendance:amend"),
        teacher_id=_teacher(ctx),
    )


@router.post(
    "/{session_id}/reopen",
    response_model=AttendanceSessionDetail,
    summary="Reopen a submitted register for correction",
)
async def reopen_session(
    session_id: UUID,
    db: DbSession,
    ctx: AmendCtx,
    reason: Annotated[str, Body(embed=True, min_length=3, max_length=300)],
) -> AttendanceSessionDetail:
    """`attendance:amend`, not `attendance:mark`.

    The reason is required, not optional: an audit row saying only that a register
    was reopened answers none of the questions asked of it later.
    """
    return await AttendanceService(db).reopen(
        session_id, reason=reason, actor_id=ctx.user_id, teacher_id=_teacher(ctx)
    )


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Discard a draft register",
)
async def discard_session(session_id: UUID, db: DbSession, ctx: MarkCtx) -> None:
    """Only a DRAFT. A submitted register is corrected by amendment, which leaves a
    trail; deleting one would not."""
    await AttendanceService(db).discard(
        session_id,
        actor_id=ctx.user_id,
        may_amend=ctx.has("attendance:amend"),
        teacher_id=_teacher(ctx),
    )


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
#
# Both take an explicit date range rather than a term id. A term is one range a
# caller might want; "since the parents' evening" and "the last 30 days" are others,
# and a term-only API cannot express them. The frontend resolves a term to its dates
# and passes those.


@router.get(
    "/students/{student_id}/summary",
    response_model=StudentAttendanceSummary,
    summary="One student's attendance rate over a date range",
)
async def student_summary(
    student_id: UUID,
    db: DbSession,
    ctx: ReadCtx,
    from_date: Annotated[date, Query(description="Inclusive lower bound.")],
    to_date: Annotated[date, Query(description="Inclusive upper bound.")],
) -> StudentAttendanceSummary:
    """Counts only SUBMITTED registers, and excludes EXCUSED absences from the
    denominator. `percentage` is null -- not 0 -- when nothing countable exists."""
    return await AttendanceService(db).student_summary(
        student_id, from_date, to_date, teacher_id=_teacher(ctx)
    )


@router.get(
    "/sections/{section_id}/report",
    response_model=SectionAttendanceReport,
    summary="One section's attendance, day by day",
)
async def section_report(
    section_id: UUID,
    db: DbSession,
    ctx: ReadCtx,
    from_date: Annotated[date, Query(description="Inclusive lower bound.")],
    to_date: Annotated[date, Query(description="Inclusive upper bound.")],
) -> SectionAttendanceReport:
    return await AttendanceService(db).section_report(
        section_id, from_date, to_date, teacher_id=_teacher(ctx)
    )
