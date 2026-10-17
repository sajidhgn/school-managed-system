"""Diary agent HTTP endpoints -- the office's side: format, preview, history.

AUTHORISATION SHAPE
    whatsapp:read     see the diary format and what teachers have sent
    whatsapp:manage   change the format and the model's standing instructions

    Teachers never use these: they talk to the agent on WhatsApp, and that side is
    the signed webhook in `whatsapp/router.py`, gated on `whatsapp:diary`.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import AuthContext, DbSession, Pagination, require
from app.common.schemas import Page
from app.modules.diary_agent.schemas import (
    DiaryAgentSettingsRead,
    DiaryAgentSettingsWrite,
    DiaryDraftRead,
    DiaryPreviewRead,
)
from app.modules.diary_agent.service import DiaryAgentService

router = APIRouter()

ReadCtx = Annotated[AuthContext, Depends(require("whatsapp:read"))]
ManageCtx = Annotated[AuthContext, Depends(require("whatsapp:manage"))]


@router.get("/settings", response_model=DiaryAgentSettingsRead, summary="The campus's diary format")
async def get_settings(db: DbSession, _: ReadCtx) -> DiaryAgentSettingsRead:
    return await DiaryAgentService(db).get_settings()


@router.put("/settings", response_model=DiaryAgentSettingsRead, summary="Change the diary format")
async def put_settings(
    payload: DiaryAgentSettingsWrite, db: DbSession, ctx: ManageCtx
) -> DiaryAgentSettingsRead:
    return await DiaryAgentService(db).put_settings(payload, actor_id=ctx.user_id)


@router.post(
    "/preview",
    response_model=DiaryPreviewRead,
    summary="A sample diary in a format, without saving it",
)
async def preview(payload: DiaryAgentSettingsWrite, db: DbSession, _: ReadCtx) -> DiaryPreviewRead:
    return await DiaryAgentService(db).preview(payload)


@router.get(
    "/drafts",
    response_model=Page[DiaryDraftRead],
    summary="Diaries teachers have sent, newest first",
)
async def list_drafts(db: DbSession, _: ReadCtx, params: Pagination) -> Page[DiaryDraftRead]:
    return await DiaryAgentService(db).list_drafts(params)
