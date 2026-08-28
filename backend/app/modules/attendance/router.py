"""Attendance HTTP endpoints -- registers, marking, and the reports read off them.

Handlers are one line of delegation each. Anything longer belongs in the service.

AUTHORISATION SHAPE
    Three codes, and the split between the second and the third is the module's
    whole integrity story:

        attendance:read    see registers and reports
        attendance:mark    open a register, set statuses, submit it
        attendance:amend   change or reopen a register that was already SUBMITTED

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

ROUTE ORDER IS LOAD-BEARING
    Starlette matches in declaration order. Every literal segment (`/today`,
    `/students/...`, `/sections/...`) is declared BEFORE the `/{session_id}` pattern
    that would otherwise swallow it and fail with a 422 UUID error.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Body, Depends, Query, status

from app.api.deps import AuthContext, DbSession, Pagination, Sorting, require
from app.common.schemas import Page
from app.modules.attendance.models import AttendanceSessionStatus
from app.modules.attendance.schemas import (
    AttendanceMarkRequest,
    AttendanceSessionDetail,
    AttendanceSessionOpen,
    AttendanceSessionRead,
    DailyOverview,
    SectionAttendanceReport,
    StudentAttendanceSummary,
)
from app.modules.attendance.service import AttendanceService

router = APIRouter()

ReadCtx = Annotated[AuthContext, Depends(require("attendance:read"))]
MarkCtx = Annotated[AuthContext, Depends(require("attendance:mark"))]
AmendCtx = Annotated[AuthContext, Depends(require("attendance:amend"))]


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
    _ctx: ReadCtx,
    session_date: date | None = Query(default=None, alias="date", description="Defaults to today."),
) -> DailyOverview:
    """The head teacher's morning chase list.

    `session_id: null` means nobody has opened that section's register -- a state a
    flat attendance table cannot distinguish from "everybody was present".
    """
    return await AttendanceService(db).daily_overview(session_date)


@router.get(
    "",
    response_model=Page[AttendanceSessionRead],
    summary="List attendance registers",
)
async def list_sessions(
    db: DbSession,
    params: Pagination,
    sort: Sorting,
    _ctx: ReadCtx,
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
    return await AttendanceService(db).open_session(payload, actor_id=ctx.user_id)


@router.get(
    "/{session_id}",
    response_model=AttendanceSessionDetail,
    summary="One register with every line, in roll order",
)
async def get_session(session_id: UUID, db: DbSession, _ctx: ReadCtx) -> AttendanceSessionDetail:
    return await AttendanceService(db).detail(session_id)


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
    changed student. The permission is resolved here and passed to the service as a
    flag, so the service stays callable from a CLI or a worker.
    """
    return await AttendanceService(db).mark(
        session_id,
        payload,
        actor_id=ctx.user_id,
        may_amend=ctx.has("attendance:amend"),
    )


@router.post(
    "/{session_id}/submit",
    response_model=AttendanceSessionDetail,
    summary="Assert that a register is complete and correct",
)
async def submit_session(session_id: UUID, db: DbSession, ctx: MarkCtx) -> AttendanceSessionDetail:
    """From here the register feeds reports and absence alerts, and further changes
    need `attendance:amend`."""
    return await AttendanceService(db).submit(session_id, actor_id=ctx.user_id)


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
    return await AttendanceService(db).reopen(session_id, reason=reason, actor_id=ctx.user_id)


@router.delete(
    "/{session_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Discard a draft register",
)
async def discard_session(session_id: UUID, db: DbSession, ctx: MarkCtx) -> None:
    """Only a DRAFT. A submitted register is corrected by amendment, which leaves a
    trail; deleting one would not."""
    await AttendanceService(db).discard(session_id, actor_id=ctx.user_id)


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
    _ctx: ReadCtx,
    from_date: Annotated[date, Query(description="Inclusive lower bound.")],
    to_date: Annotated[date, Query(description="Inclusive upper bound.")],
) -> StudentAttendanceSummary:
    """Counts only SUBMITTED registers, and excludes EXCUSED absences from the
    denominator. `percentage` is null -- not 0 -- when nothing countable exists."""
    return await AttendanceService(db).student_summary(student_id, from_date, to_date)


@router.get(
    "/sections/{section_id}/report",
    response_model=SectionAttendanceReport,
    summary="One section's attendance, day by day",
)
async def section_report(
    section_id: UUID,
    db: DbSession,
    _ctx: ReadCtx,
    from_date: Annotated[date, Query(description="Inclusive lower bound.")],
    to_date: Annotated[date, Query(description="Inclusive upper bound.")],
) -> SectionAttendanceReport:
    return await AttendanceService(db).section_report(section_id, from_date, to_date)
