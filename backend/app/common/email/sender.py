"""Email transport.

WHY THIS FILE EXISTS
    Sending email touches a network service that is slow, flaky, and -- in this
    project's case -- destined to be replaced. Gmail SMTP will not carry a
    multi-tenant SaaS that broadcasts fee reminders to every parent. Isolating the
    transport behind an interface means swapping Gmail for Resend/SES/Postmark is a
    new class and a config value, not a search-and-replace across the auth module.

RESPONSIBILITY
    Deliver a rendered message. Nothing about OTPs, users, or business rules --
    those live in the auth service, which hands this module a finished message.

INTERACTIONS
    * `modules/auth/service.py` builds an `EmailMessage` and calls `send`.
    * `api/deps.py` injects the configured sender, so routes and tests can
      substitute a fake.

=============================================================================
TWO DECISIONS WORTH DEFENDING
=============================================================================

1. `console` IS THE DEFAULT BACKEND, NOT `smtp`
   A misconfigured test run that emails real parents is unrecoverable -- you cannot
   unsend it. Defaulting to console means delivery must be switched on deliberately,
   per environment. The failure mode of the default is "no email sent", which is
   always recoverable.

2. EVERY MESSAGE IS multipart/alternative (HTML + PLAINTEXT)
   An HTML-only email scores badly with spam filters and renders as gibberish in
   text-only clients. For an OTP -- where the entire payload is six digits the user
   must be able to read -- a plaintext part is not optional. Gmail in particular
   weighs its absence when scoring deliverability, and OTP mail landing in spam
   means users cannot log in at all.

WHY SENDING IS NEVER AWAITED ON THE REQUEST PATH
   SMTP handshake + TLS + send against Gmail is commonly 500ms-3s, and can hang to
   the timeout. Blocking an HTTP response on that makes login feel broken. The auth
   service dispatches sends via FastAPI's `BackgroundTasks`, so the response returns
   immediately and delivery happens after. The consequence -- the user is told "code
   sent" before it provably was -- is the correct trade: the alternative reveals
   whether an address exists (see the enumeration note in the auth service).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from email.message import EmailMessage as MIMEMessage
from typing import Protocol, runtime_checkable

import aiosmtplib

from app.core.config import Settings, get_settings
from app.core.exceptions import ExternalServiceError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class EmailMessage:
    """A rendered, ready-to-send message.

    Frozen because a message that has been handed to a background task must not be
    mutated by the code that queued it.
    """

    to: str
    subject: str
    html_body: str
    text_body: str
    reply_to: str | None = None
    tags: dict[str, str] = field(default_factory=dict)  # for provider analytics


@runtime_checkable
class EmailSender(Protocol):
    """The transport contract.

    A `Protocol` rather than an ABC: any object with a matching `send` satisfies it,
    so a test fake needs no import from this module and no inheritance. Structural
    typing keeps the dependency arrow pointing one way.
    """

    async def send(self, message: EmailMessage) -> None: ...


def _build_mime(message: EmailMessage, settings: Settings) -> MIMEMessage:
    """Assemble a multipart/alternative MIME message.

    Order is load-bearing: RFC 2046 says the LAST alternative is the preferred one,
    so plaintext must be set first and HTML added after it. Reversing these makes
    every client display the raw plaintext.
    """
    mime = MIMEMessage()
    mime["From"] = settings.email_from
    mime["To"] = message.to
    mime["Subject"] = message.subject
    if message.reply_to:
        mime["Reply-To"] = message.reply_to

    # Tells Gmail and others not to send auto-replies or out-of-office bounces to
    # a noreply address, and marks the mail as transactional rather than bulk.
    mime["Auto-Submitted"] = "auto-generated"

    mime.set_content(message.text_body)
    mime.add_alternative(message.html_body, subtype="html")
    return mime


class ConsoleEmailSender:
    """Logs the message instead of delivering it. Default for local dev and tests.

    Logs the full body deliberately: during development the OTP has to be readable
    somewhere, and the alternative -- a developer wiring real SMTP just to see a
    code -- is how live credentials end up in test configs.

    NOTE: because this prints OTP codes in plaintext, `config.py` must never allow
    it as the backend in production. Enforced by the validator below.
    """

    async def send(self, message: EmailMessage) -> None:
        logger.info(
            "email_not_sent_console_backend",
            to=message.to,
            subject=message.subject,
            body=message.text_body,
        )


class SmtpEmailSender:
    """Delivers over SMTP via aiosmtplib.

    aiosmtplib rather than stdlib `smtplib` because the latter is blocking: a single
    slow send would stall the entire event loop, freezing every concurrent request
    in the process -- not just the one sending mail.
    """

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def send(self, message: EmailMessage) -> None:
        settings = self._settings
        mime = _build_mime(message, settings)

        try:
            await aiosmtplib.send(
                mime,
                hostname=settings.SMTP_HOST,
                port=settings.SMTP_PORT,
                username=settings.SMTP_USER or None,
                password=settings.SMTP_PASSWORD or None,
                # Mutually exclusive. use_tls = implicit TLS from the first byte
                # (port 465); start_tls = plaintext connect then STARTTLS upgrade
                # (port 587). Setting both raises; setting neither sends
                # credentials in the clear.
                use_tls=settings.SMTP_USE_TLS,
                start_tls=settings.SMTP_START_TLS,
                timeout=settings.SMTP_TIMEOUT_SECONDS,
            )
        except aiosmtplib.SMTPException as exc:
            # Logged with the address but NEVER with the body -- bodies contain
            # OTP codes, and logs are far more widely readable than inboxes.
            logger.error("email_send_failed", to=message.to, error=str(exc))
            raise ExternalServiceError(
                "Unable to send email at this time.", code="EMAIL_SEND_FAILED"
            ) from exc

        logger.info("email_sent", to=message.to, subject=message.subject)


def build_email_sender(settings: Settings | None = None) -> EmailSender:
    """Factory selecting the transport from configuration.

    Called once per request via the DI layer rather than at import time, so tests
    can override `get_settings` and get a different backend without reimporting.
    """
    settings = settings or get_settings()
    if settings.EMAIL_BACKEND == "smtp":
        return SmtpEmailSender(settings)
    return ConsoleEmailSender()
