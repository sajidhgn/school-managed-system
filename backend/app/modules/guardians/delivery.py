"""How a parent-portal login code reaches the parent: WhatsApp first, SMS behind it.

WHY THIS FILE EXISTS
    Parents in this market live on WhatsApp, and every campus already links its own
    number to WAHA for the diary and the fee notices. A code sent from the number
    that posts in their child's class group is one the parent recognises -- and it
    costs nothing, unlike an SMS.

    `auth_service` decides WHETHER a code is issued and WHAT it says. This file
    decides HOW it leaves, and is the only place that knows WhatsApp is involved.

WHICH NUMBER SENDS IT
    A campus where the parent has a child they may view, most recently linked first.
    The parent receives the code from their own child's school, never from a campus
    they have no business with. A campus whose session is not working (never linked,
    logged out, gateway down) is skipped for the next one.

"HAS WHATSAPP" IS CHECKED, NOT ASSUMED
    WAHA accepts a text to any number and reports nothing when it has no account, so
    the number is looked up first. One with no WhatsApp gets no WhatsApp message.

THE SMS SEAM STAYS UNDERNEATH
    When WhatsApp cannot deliver -- WAHA not configured, no campus connected, or the
    number has no WhatsApp -- the code goes to the SMS sender instead. In local
    development that is the console, which is how a developer reads the code; in
    production it is `null` until a real SMS provider exists, so the parent simply
    receives nothing. Either way the HTTP response was already identical.

RUNS AFTER THE RESPONSE
    The router schedules `deliver` as a background task. A WAHA round trip takes
    hundreds of milliseconds and only happens for a registered number, so doing it
    inside the request would let response timing answer "is this number a parent
    here?" -- the question the identical response body exists to refuse. It also
    keeps a slow gateway from freezing the parent's login screen. Nothing here
    touches the database: everything it needs is in `PendingCode`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from app.common.sms import SmsMessage, SmsSender
from app.common.whatsapp.waha import WahaClient, WahaError, session_name
from app.core.logging import get_logger
from app.core.phone import mask_phone

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class PendingCode:
    """A code issued and stored, waiting to be sent. Plain data, safe to outlive the request."""

    phone: str
    """E.164 -- the same string the code's digest is bound to."""
    body: str
    purpose: str
    school_ids: tuple[UUID, ...] = field(default_factory=tuple)
    """Campuses whose WhatsApp may send it, in preference order."""


class GuardianCodeDelivery:
    """Sends a `PendingCode`. Never raises: it runs where nobody could catch it."""

    def __init__(self, sms: SmsSender, waha: WahaClient | None = None) -> None:
        self.sms = sms
        self.waha = waha if waha is not None and waha.configured else None

    async def deliver(self, code: PendingCode) -> None:
        masked = mask_phone(code.phone)
        try:
            if await self._via_whatsapp(code, masked):
                return
            await self.sms.send(SmsMessage(to=code.phone, body=code.body, purpose=code.purpose))
        except Exception:  # background task: log, never propagate
            logger.exception("guardian_otp_delivery_failed", phone_masked=masked)

    async def _via_whatsapp(self, code: PendingCode, masked: str) -> bool:
        if self.waha is None or not code.school_ids:
            return False
        for school_id in code.school_ids:
            session = session_name(school_id)
            try:
                chat_id = await self.waha.check_number(session, code.phone)
                if chat_id is None:
                    # Whether a number has WhatsApp does not depend on which campus
                    # asks, so there is no point trying the next one.
                    logger.info("guardian_otp_not_on_whatsapp", phone_masked=masked)
                    return False
                await self.waha.send_text(session, chat_id, code.body)
            except WahaError as exc:
                logger.warning(
                    "guardian_otp_whatsapp_unavailable",
                    school_id=str(school_id),
                    phone_masked=masked,
                    error=str(exc),
                )
                continue
            logger.info("guardian_otp_sent_whatsapp", school_id=str(school_id), phone_masked=masked)
            return True
        return False
