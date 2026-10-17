"""WhatsApp HTTP endpoints -- one line of delegation each.

AUTHORISATION SHAPE
    whatsapp:read     see linked groups, settings, previews and the outbox
    whatsapp:send     queue a custom message or the fee notice now; retry/cancel
    whatsapp:manage   link groups and configure the monthly notice

    Sending is split from managing because the person who posts today's holiday
    notice is not necessarily the person who decides which groups exist. Linking
    the campus's number (the WAHA connection) is `manage`: it decides who the
    school speaks as.

THE WEBHOOK IS ITS OWN ROUTER
    `webhook_router` is deliberately unauthenticated -- WAHA, not a user, calls it --
    and kept apart so a new endpoint cannot land in it by accident. Authenticity
    comes from the HMAC over the raw body (`WAHA_WEBHOOK_SECRET`). It answers at
    once and hands the message to the diary agent in the background: reading a
    photo takes seconds, and WAHA would otherwise time out and deliver it again.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Query, Request, status

from app.api.deps import AuthContext, DbSession, Pagination, SettingsDep, require
from app.common.schemas import Page
from app.common.whatsapp.waha import WahaClient, verify_webhook
from app.core.exceptions import AuthenticationError
from app.modules.diary_agent.agent import DiaryAgent, build_diary_agent
from app.modules.diary_agent.conversation import DiaryConversation, parse_webhook
from app.modules.whatsapp.models import WhatsAppMessageStatus
from app.modules.whatsapp.schemas import (
    CustomMessageRequest,
    FeeNoticePreview,
    FeeNoticeQueueRequest,
    QueueResult,
    WhatsAppConnectionRead,
    WhatsAppGroupRead,
    WhatsAppGroupWrite,
    WhatsAppMessageRead,
    WhatsAppQrRead,
    WhatsAppSettingsRead,
    WhatsAppSettingsWrite,
)
from app.modules.whatsapp.service import WhatsAppService

router = APIRouter()
webhook_router = APIRouter()


def get_waha_client(settings: SettingsDep) -> WahaClient:
    return WahaClient(settings)


AgentFactory = Callable[[], DiaryAgent]


def get_diary_agent_factory(settings: SettingsDep) -> AgentFactory:
    """A factory, not an agent: building one needs the API key, and a webhook that
    only says "OK" should not fail because the model is not configured."""
    return lambda: build_diary_agent(settings)


WahaDep = Annotated[WahaClient, Depends(get_waha_client)]
AgentFactoryDep = Annotated[AgentFactory, Depends(get_diary_agent_factory)]

ReadCtx = Annotated[AuthContext, Depends(require("whatsapp:read"))]
SendCtx = Annotated[AuthContext, Depends(require("whatsapp:send"))]
ManageCtx = Annotated[AuthContext, Depends(require("whatsapp:manage"))]


@router.get("/groups", response_model=list[WhatsAppGroupRead], summary="Linked class groups")
async def list_groups(db: DbSession, _: ReadCtx, waha: WahaDep) -> list[WhatsAppGroupRead]:
    return await WhatsAppService(db, waha).list_groups()


@router.post(
    "/groups",
    response_model=WhatsAppGroupRead,
    status_code=status.HTTP_201_CREATED,
    summary="Link a WhatsApp group to a class",
)
async def create_group(
    payload: WhatsAppGroupWrite, db: DbSession, ctx: ManageCtx, waha: WahaDep
) -> WhatsAppGroupRead:
    return await WhatsAppService(db, waha).create_group(payload, actor_id=ctx.user_id)


@router.put("/groups/{group_id}", response_model=WhatsAppGroupRead, summary="Edit a linked group")
async def update_group(
    group_id: UUID, payload: WhatsAppGroupWrite, db: DbSession, ctx: ManageCtx, waha: WahaDep
) -> WhatsAppGroupRead:
    return await WhatsAppService(db, waha).update_group(group_id, payload, actor_id=ctx.user_id)


@router.delete(
    "/groups/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Unlink a group; its queued messages are dropped",
)
async def delete_group(group_id: UUID, db: DbSession, ctx: ManageCtx) -> None:
    await WhatsAppService(db).delete_group(group_id, actor_id=ctx.user_id)


@router.get(
    "/connection",
    response_model=WhatsAppConnectionRead,
    summary="The campus's linked WhatsApp number (WAHA)",
)
async def get_connection(db: DbSession, _: ReadCtx, waha: WahaDep) -> WhatsAppConnectionRead:
    return await WhatsAppService(db, waha).connection()


@router.post(
    "/connection",
    response_model=WhatsAppConnectionRead,
    summary="Start linking the campus's number; then scan the QR code",
)
async def connect(db: DbSession, ctx: ManageCtx, waha: WahaDep) -> WhatsAppConnectionRead:
    return await WhatsAppService(db, waha).connect(actor_id=ctx.user_id)


@router.get(
    "/connection/qr",
    response_model=WhatsAppQrRead,
    summary="The QR code to scan with the school's phone",
)
async def connection_qr(db: DbSession, _: ManageCtx, waha: WahaDep) -> WhatsAppQrRead:
    return await WhatsAppService(db, waha).qr()


@router.delete(
    "/connection",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Log the campus's number out of the gateway",
)
async def disconnect(db: DbSession, ctx: ManageCtx, waha: WahaDep) -> None:
    await WhatsAppService(db, waha).disconnect(actor_id=ctx.user_id)


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


@webhook_router.post("/webhook", status_code=status.HTTP_200_OK, include_in_schema=False)
async def receive_webhook(
    request: Request,
    background: BackgroundTasks,
    settings: SettingsDep,
    waha: WahaDep,
    agent_factory: AgentFactoryDep,
) -> dict[str, str]:
    """An incoming WhatsApp message from WAHA -- verified, then handed to the diary
    agent after the response. Anything that is not a person's message is ignored."""
    raw = await request.body()
    if not verify_webhook(
        raw,
        request.headers.get("X-Webhook-Hmac"),
        request.headers.get("X-Webhook-Hmac-Algorithm"),
        settings.WAHA_WEBHOOK_SECRET,
    ):
        raise AuthenticationError("Invalid webhook signature.", code="INVALID_SIGNATURE")
    event = parse_webhook(raw)
    if event is not None:
        conversation = DiaryConversation(settings, waha=waha, agent_factory=agent_factory)
        background.add_task(conversation.handle, event)
    return {"status": "ok"}
