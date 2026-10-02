"""Diary HTTP endpoints -- one line of delegation each.

AUTHORISATION SHAPE
    diary:read     see any section's page
    diary:write    write rows on pages you are ASSIGNED to (class teacher: all
                   rows; subject teacher: your subjects' rows)
    diary:manage   write any row on any page, assigned or not

    The permission says what KIND of thing you may do; the assignment (who is
    whose class teacher) says WHERE. The service enforces the second half, so a
    teacher holding `diary:write` still cannot write another class's homework.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from app.api.deps import AuthContext, DbSession, require
from app.modules.diary.schemas import DiaryPage, DiaryPageWrite, DiarySectionOption
from app.modules.diary.service import DiaryService, default_diary_date

router = APIRouter()

ReadCtx = Annotated[AuthContext, Depends(require("diary:read"))]

DateQuery = Annotated[
    date | None, Query(alias="date", description="The diary's day. Defaults to today.")
]


@router.get(
    "/sections",
    response_model=list[DiarySectionOption],
    summary="Every section, with what the caller may write on its diary",
)
async def list_sections(
    db: DbSession, ctx: ReadCtx, entry_date: DateQuery = None
) -> list[DiarySectionOption]:
    """The caller's own classes come first: class teacher, then subject teacher."""
    return await DiaryService(db).sections(
        entry_date or default_diary_date(),
        user_id=ctx.user_id,
        may_write=ctx.has("diary:write"),
        may_manage=ctx.has("diary:manage"),
    )


@router.get(
    "/sections/{section_id}",
    response_model=DiaryPage,
    summary="One section's diary page for a date",
)
async def get_page(
    section_id: UUID, db: DbSession, ctx: ReadCtx, entry_date: DateQuery = None
) -> DiaryPage:
    return await DiaryService(db).page(
        section_id,
        entry_date or default_diary_date(),
        user_id=ctx.user_id,
        may_write=ctx.has("diary:write"),
        may_manage=ctx.has("diary:manage"),
    )


@router.put(
    "/sections/{section_id}",
    response_model=DiaryPage,
    summary="Write homework on a section's diary page",
)
async def write_page(
    section_id: UUID,
    payload: DiaryPageWrite,
    db: DbSession,
    ctx: ReadCtx,
    entry_date: DateQuery = None,
) -> DiaryPage:
    """Partial: subjects not named are untouched. A blank `content` clears that
    subject. 403 `DIARY_NOT_ASSIGNED` if any named row is not the caller's to write;
    nothing is saved in that case.

    Guarded on `diary:read` and then on `diary:write` OR `diary:manage` in the
    service: `require()` demands every code it is given, and a coordinator role may
    reasonably hold `manage` without `write`."""
    return await DiaryService(db).write(
        section_id,
        entry_date or default_diary_date(),
        payload,
        user_id=ctx.user_id,
        may_write=ctx.has("diary:write"),
        may_manage=ctx.has("diary:manage"),
    )
