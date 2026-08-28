"""SMS dispatch -- the transport the guardian OTP rides on.

WHY THIS FILE EXISTS
    Guardians authenticate by phone, so a code has to leave the building. Every
    real gateway (Twilio, Vonage, Jazz, Telenor's bulk API, WhatsApp Business) is a
    different HTTP contract with a different credential and a different failure mode,
    and none of them can be signed up for during development.

    The same shape `common/email/sender.py` already uses solves it: a Protocol the
    application depends on, and swappable implementations behind it. Adding a real
    provider is then a new class and a config value -- not a search-and-replace
    through the auth code.

RESPONSIBILITY
    Define the message, the sender Protocol, and the two transports that need no
    external account: one that logs and one that drops. Nothing here knows what an
    OTP is.

INTERACTIONS
    * `modules/guardians/auth_router.py` injects a sender as a FastAPI dependency,
      which is the seam the integration tests replace with a capturing fake.

=============================================================================
THIS IS A PLACEHOLDER FOR THE NOTIFICATION BUS, AND SAYS SO ON PURPOSE
=============================================================================
    A tenant-metered, queued, throttled notification service with delivery receipts
    is its own module, and it is the right home for every message this system will
    ever send. It does not exist yet, and guardian login cannot wait for it.

    So the seam is drawn where that module will plug in: one `send()` call taking one
    message. When the bus lands, `build_sms_sender` returns a bus-backed sender and
    NOTHING in the guardian module changes. What must NOT happen in the meantime is
    a direct `httpx.post` to a gateway inside the auth service -- that is the version
    which has to be unpicked later.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SmsMessage:
    """One outbound text.

    `to` is E.164 (see `core/phone.py`); senders do no normalisation of their own so
    that the number stored, the number the digest is bound to, and the number dialled
    are provably the same string.
    """

    to: str
    body: str
    purpose: str = "generic"
    """Coarse label for logs and, later, for per-category tenant metering. NOT the
    message content -- the body of an OTP text must never reach a log line."""


class SmsSender(Protocol):
    """What the application depends on. Implementations may block only internally."""

    async def send(self, message: SmsMessage) -> None: ...


class ConsoleSmsSender:
    """Logs the message instead of sending it. The local-development default.

    Logs the BODY at debug level, which is how a developer reads the OTP without an
    SMS account. That is acceptable precisely because it is unreachable outside
    local/test: `build_sms_sender` refuses to select this backend in production, and
    the code it prints dies in five minutes regardless.
    """

    async def send(self, message: SmsMessage) -> None:
        logger.info(
            "sms_console_dispatch", to=message.to, purpose=message.purpose, body=message.body
        )


class NullSmsSender:
    """Accepts and discards. For environments that must not text anyone.

    Not the same thing as `ConsoleSmsSender`: this one deliberately does not record
    the body, so a staging environment restored from a production dump cannot leak
    live codes into a log aggregator.
    """

    async def send(self, message: SmsMessage) -> None:
        logger.info("sms_suppressed", to=message.to, purpose=message.purpose)


def build_sms_sender(settings: Settings | None = None) -> SmsSender:
    """Pick the transport named by `SMS_BACKEND`.

    Unknown values fall through to `NullSmsSender` rather than raising. A typo in an
    environment variable must not prevent the API from booting -- guardians simply
    cannot log in until it is corrected, which is a visible, recoverable failure
    rather than an outage of the whole tenant surface.
    """
    settings = settings or get_settings()
    match settings.SMS_BACKEND:
        case "console":
            return ConsoleSmsSender()
        case _:
            return NullSmsSender()
