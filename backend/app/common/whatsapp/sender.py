"""WhatsApp group dispatch -- the transport class-group messages ride on.

WHY THIS FILE EXISTS
    Schools here run one WhatsApp group per class, and that group is where the fee
    reminder and every notice actually reaches parents. The `whatsapp` module decides
    WHAT to post and queues it; this file is the seam that decides HOW it leaves.

    Same shape as `common/sms/sender.py`: a Protocol the dispatcher depends on, and
    swappable transports behind `build_whatsapp_sender`. A hosted gateway is a new
    class and a config value -- nothing upstream moves. `WahaSender` is the one for
    a server: a self-hosted WAHA gateway, see `common/whatsapp/waha.py`.

=============================================================================
PYWHATKIT IS A DESKTOP AUTOMATION, NOT AN API -- AND THAT SHAPES EVERYTHING
=============================================================================
    `pywhatkit` opens web.whatsapp.com in the default browser, waits for the group
    to load, and TYPES the message with simulated keystrokes. So it needs:

      * a display, a browser, and WhatsApp Web already logged in as the school;
      * the screen left alone while it runs -- a click elsewhere sends the text
        to the wrong window;
      * one message at a time, ~30 seconds each.

    That is why the API never sends. It queues rows in `whatsapp_messages`, and
    `python -m app.cli send-whatsapp` -- run on that desktop -- drains them through
    this sender. `pywhatkit` is imported lazily inside the sender because merely
    importing it on a headless server fails (pyautogui wants a display).

    It also reports nothing back: a "sent" message is one handed to WhatsApp Web
    without an exception, not a delivery receipt.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from app.common.whatsapp.waha import WahaClient, WahaError, session_name
from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class WhatsAppGroupMessage:
    """One post into one group.

    `group_code` is the invite code -- the part after `chat.whatsapp.com/` in the
    group's invite link -- which is how WhatsApp Web addresses a group by URL.
    """

    group_code: str
    body: str
    purpose: str = "generic"
    chat_id: str | None = None
    """The group's `...@g.us` id when already resolved (WAHA addresses groups by it)."""
    school_id: UUID | None = None
    """Which campus's linked number posts it -- WAHA has one session per campus."""


class WhatsAppSender(Protocol):
    """What the dispatcher depends on. Raises on failure; returns on success."""

    async def send(self, message: WhatsAppGroupMessage) -> None: ...


class ConsoleWhatsAppSender:
    """Logs the message instead of posting it. The local-development default.

    Unlike an OTP, a group notice is not a secret, so logging the body is harmless.
    """

    async def send(self, message: WhatsAppGroupMessage) -> None:
        logger.info(
            "whatsapp_console_dispatch",
            group_code=message.group_code,
            purpose=message.purpose,
            body=message.body,
        )


class NullWhatsAppSender:
    """Accepts and discards. For a staging copy that must not post to real groups."""

    async def send(self, message: WhatsAppGroupMessage) -> None:
        logger.info("whatsapp_suppressed", group_code=message.group_code, purpose=message.purpose)


class PyWhatKitSender:
    """Posts through WhatsApp Web by browser automation. Desktop only -- see above."""

    def __init__(self, wait_seconds: int) -> None:
        self.wait_seconds = wait_seconds

    async def send(self, message: WhatsAppGroupMessage) -> None:
        # Blocking (it sleeps and types), so it runs on a worker thread rather than
        # stalling the event loop the database session lives on.
        await asyncio.to_thread(self._send_blocking, message)

    def _send_blocking(self, message: WhatsAppGroupMessage) -> None:
        # Lazy: importing pywhatkit without a display fails -- see module docstring.
        import pywhatkit  # type: ignore[import-not-found]

        pywhatkit.sendwhatmsg_to_group_instantly(
            message.group_code,
            message.body,
            wait_time=self.wait_seconds,
            # Closing the tab after each post keeps the next one from typing into a
            # stale chat when WhatsApp Web is slow to swap groups.
            tab_close=True,
            close_time=5,
        )
        logger.info(
            "whatsapp_pywhatkit_dispatch", group_code=message.group_code, purpose=message.purpose
        )


class WahaSender:
    """Posts through the campus's WAHA session. Headless; runs anywhere WAHA is reachable.

    A group linked before the campus connected WhatsApp has no chat id yet; it is
    resolved from the invite code here, at send time, rather than failing the post.
    """

    def __init__(self, client: WahaClient) -> None:
        self.client = client

    async def send(self, message: WhatsAppGroupMessage) -> None:
        if message.school_id is None:
            raise WahaError("No campus on the message; cannot pick a WhatsApp session.")
        session = session_name(message.school_id)
        chat_id = message.chat_id or await self.client.group_chat_id(session, message.group_code)
        await self.client.send_text(session, chat_id, message.body)
        logger.info("whatsapp_waha_dispatch", chat_id=chat_id, purpose=message.purpose)


def build_whatsapp_sender(settings: Settings | None = None) -> WhatsAppSender:
    """Pick the transport named by `WHATSAPP_BACKEND`. Unknown values drop, like SMS."""
    settings = settings or get_settings()
    match settings.WHATSAPP_BACKEND:
        case "console":
            return ConsoleWhatsAppSender()
        case "pywhatkit":
            return PyWhatKitSender(settings.WHATSAPP_PYWHATKIT_WAIT_SECONDS)
        case "waha":
            return WahaSender(WahaClient(settings))
        case _:
            return NullWhatsAppSender()
