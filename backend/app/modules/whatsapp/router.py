"""WhatsApp HTTP endpoints -- one line of delegation each.

AUTHORISATION SHAPE
    whatsapp:read     see linked groups, settings, previews and the outbox
    whatsapp:send     queue a custom message or the fee notice now; retry/cancel
    whatsapp:manage   link groups and configure the monthly notice

    Sending is split from managing because the person who posts today's holiday
    notice is not necessarily the person who decides which groups exist.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import AuthContext, DbSession, Pagination, require
from app.common.schemas import Page
from app.modules.whatsapp.models import WhatsAppMessageStatus
from app.modules.whatsapp.schemas import (
    CustomMessageRequest,
    FeeNoticePreview,
    FeeNoticeQueueRequest,
    QueueResult,
    WhatsAppGroupRead,
    WhatsAppGroupWrite,
    WhatsAppMessageRead,
    WhatsAppSettingsRead,
    WhatsAppSettingsWrite,
)
from app.modules.whatsapp.service import WhatsAppService

router = APIRouter()

ReadCtx = Annotated[AuthContext, Depends(require("whatsapp:read"))]
SendCtx = Annotated[AuthContext, Depends(require("whatsapp:send"))]
ManageCtx = Annotated[AuthContext, Depends(require("whatsapp:manage"))]


@router.get("/groups", response_model=list[WhatsAppGroupRead], summary="Linked class groups")
async def list_groups(db: DbSession, _: ReadCtx) -> list[WhatsAppGroupRead]:
    return await WhatsAppService(db).list_groups()


@router.post(
    "/groups",
    response_model=WhatsAppGroupRead,
    status_code=status.HTTP_201_CREATED,
    summary="Link a WhatsApp group to a class",
)
async def create_group(
    payload: WhatsAppGroupWrite, db: DbSession, ctx: ManageCtx
) -> WhatsAppGroupRead:
    return await WhatsAppService(db).create_group(payload, actor_id=ctx.user_id)


@router.put("/groups/{group_id}", response_model=WhatsAppGroupRead, summary="Edit a linked group")
async def update_group(
    group_id: UUID, payload: WhatsAppGroupWrite, db: DbSession, ctx: ManageCtx
) -> WhatsAppGroupRead:
    return await WhatsAppService(db).update_group(group_id, payload, actor_id=ctx.user_id)


@router.delete(
    "/groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unlink a group; its queued messages are dropped",
)
async def delete_group(group_id: UUID, db: DbSession, ctx: ManageCtx) -> None:
    await WhatsAppService(db).delete_group(group_id, actor_id=ctx.user_id)


@router.get("/settings", response_model=WhatsAppSettingsRead, summary="Monthly fee notice settings")
async def get_settings(db: DbSession, _: ReadCtx) -> WhatsAppSettingsRead:
    return await WhatsAppService(db).get_settings()


@router.put("/settings", response_model=WhatsAppSettingsRead, summary="Configure the fee notice")
async def put_settings(
    payload: WhatsAppSettingsWrite, db: DbSession, ctx: ManageCtx
) -> WhatsAppSettingsRead:
    return await WhatsAppService(db).put_settings(payload, actor_id=ctx.user_id)


@router.get(
    "/fee-notices/preview",
    response_model=list[FeeNoticePreview],
    summary="What each group would receive for a month, without queuing",
)
async def preview_fee_notices(
    db: DbSession,
    _: ReadCtx,
    period_label: Annotated[str | None, Query(pattern=r"^\d{4}-\d{2}$")] = None,
) -> list[FeeNoticePreview]:
    return await WhatsAppService(db).preview_fee_notices(period_label)


@router.post(
    "/fee-notices",
    response_model=QueueResult,
    summary="Queue the month's fee notice now (once per group per month)",
)
async def queue_fee_notices(
    payload: FeeNoticeQueueRequest, db: DbSession, ctx: SendCtx
) -> QueueResult:
    return await WhatsAppService(db).queue_fee_notices(payload, actor_id=ctx.user_id)


@router.post(
    "/messages",
    response_model=QueueResult,
    status_code=status.HTTP_201_CREATED,
    summary="Queue a custom message to chosen groups",
)
async def queue_custom(payload: CustomMessageRequest, db: DbSession, ctx: SendCtx) -> QueueResult:
    return await WhatsAppService(db).queue_custom(payload, actor_id=ctx.user_id)


@router.get(
    "/messages", response_model=Page[WhatsAppMessageRead], summary="The outbox, newest first"
)
async def list_messages(
    db: DbSession,
    _: ReadCtx,
    params: Pagination,
    message_status: Annotated[WhatsAppMessageStatus | None, Query(alias="status")] = None,
) -> Page[WhatsAppMessageRead]:
    return await WhatsAppService(db).list_messages(params, message_status)


@router.post(
    "/messages/{message_id}/retry",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Put a failed message back in the queue",
)
async def retry_message(message_id: UUID, db: DbSession, _: SendCtx) -> None:
    await WhatsAppService(db).retry_message(message_id)


@router.delete(
    "/messages/{message_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Cancel a message that has not been sent",
)
async def cancel_message(message_id: UUID, db: DbSession, _: SendCtx) -> None:
    await WhatsAppService(db).cancel_message(message_id)
