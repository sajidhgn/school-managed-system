"""Scheduled WhatsApp work: queue the monthly fee notices, and drain the outbox.

TWO JOBS, RUN IN TWO DIFFERENT PLACES -- ON PURPOSE
    * `queue_fee_notices_for_organization` is part of the nightly `run-maintenance`
      pass, straight after challan generation, so a campus that bills and announces
      on the 1st does both in one pass. It only writes rows; it can run anywhere.
    * `dispatch_outbox` actually posts, and is run by `app.cli send-whatsapp` on the
      machine where the transport works. For pywhatkit that is a desktop with
      WhatsApp Web logged in -- see `common/whatsapp/sender.py`.

    Keeping them apart is what lets the server keep its nightly schedule while the
    posting happens wherever a logged-in browser exists.

CONTEXTVARS
    Same dance as `fees/jobs.py`, for the same reason: `session_scope` sets the RLS
    GUCs (organization boundary) but not the campus ContextVar the repositories read.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.whatsapp.sender import WhatsAppGroupMessage, WhatsAppSender
from app.core.context import (
    get_organization_id,
    get_school_id,
    set_organization_id,
    set_school_id,
)
from app.core.logging import get_logger
from app.db.session import session_scope
from app.modules.tenancy.models import School
from app.modules.whatsapp.models import WhatsAppMessageStatus, WhatsAppSettings
from app.modules.whatsapp.repository import WhatsAppMessageRepository
from app.modules.whatsapp.service import WhatsAppService

logger = get_logger(__name__)


async def queue_fee_notices_for_organization(
    session: AsyncSession, organization_id: UUID, *, today: date | None = None
) -> int:
    """Queue today's due fee notices for every campus that has them switched on.

    Idempotent: the partial unique index allows one fee notice per group per month,
    so a pass that runs twice -- or every night after the send day while drafts wait
    to be issued -- queues each group's notice exactly once.
    """
    today = today or date.today()
    school_ids = list(
        (
            await session.execute(
                select(WhatsAppSettings.school_id)
                .join(School, School.id == WhatsAppSettings.school_id)
                .where(
                    WhatsAppSettings.organization_id == organization_id,
                    WhatsAppSettings.fee_notice_enabled.is_(True),
                    School.deleted_at.is_(None),
                )
            )
        ).scalars()
    )

    queued = 0
    previous_org = get_organization_id()
    previous_school = get_school_id()
    set_organization_id(organization_id)
    try:
        for school_id in school_ids:
            set_school_id(school_id)
            queued += await WhatsAppService(session).queue_scheduled_fee_notices(today)
    finally:
        set_school_id(previous_school)
        set_organization_id(previous_org)
    return queued


async def dispatch_outbox(
    organization_id: UUID, sender: WhatsAppSender, *, limit: int
) -> tuple[int, int]:
    """Send up to `limit` queued messages for one organization. Returns (sent, failed).

    ONE TRANSACTION PER MESSAGE. A pywhatkit post takes half a minute; holding one
    transaction across fifty of them would keep every row locked for half an hour,
    and a crash at message 49 would roll back the record of 48 posts that really
    happened -- and the next run would post them all again.
    """
    async with session_scope(organization_id) as session:
        ids = await WhatsAppMessageRepository(session).queued_ids(limit)

    sent = failed = 0
    for message_id in ids:
        async with session_scope(organization_id) as session:
            message = await WhatsAppMessageRepository(session).claim(message_id)
            if message is None:
                continue  # another dispatcher took it, or it was cancelled
            message.attempts += 1
            try:
                await sender.send(
                    WhatsAppGroupMessage(
                        group_code=message.invite_code,
                        body=message.body,
                        purpose=message.kind.value,
                    )
                )
            except Exception as exc:  # any transport failure fails ONE message
                message.status = WhatsAppMessageStatus.FAILED
                message.last_error = f"{type(exc).__name__}: {exc}"[:500]
                failed += 1
                logger.warning(
                    "whatsapp_dispatch_failed", message_id=str(message.id), error=message.last_error
                )
            else:
                message.status = WhatsAppMessageStatus.SENT
                message.sent_at = datetime.now(UTC)
                message.last_error = None
                sent += 1
    return sent, failed
