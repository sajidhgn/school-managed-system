"""Email template rendering.

WHY THIS FILE EXISTS
    Email copy is content, not logic. Keeping it in template files rather than
    f-strings inside the auth service means a non-developer can adjust wording, and
    a change to the signup email cannot break the login flow.

RESPONSIBILITY
    Turn (template name, context) into a rendered `EmailMessage`. It does not decide
    *when* to send or *what* the OTP is -- the auth service does that.

INTERACTIONS
    * `modules/auth/service.py` calls `render_otp_email` and passes the result to
      an `EmailSender`.
    * Templates live in `templates/`, loaded once at import.

WHY AUTOESCAPE IS ON
    Template context includes user-controlled values -- a school's name, a person's
    name. A school named `<script>alert(1)</script>` must not become executable
    markup in an email client that renders it. Autoescaping is off by default in
    Jinja2, which is the wrong default for anything HTML.

WHY EACH EMAIL SHIPS BOTH .html AND .txt
    See the multipart rationale in `sender.py`. Practically: an OTP that renders as
    raw HTML tags in a text-only client is an OTP the user cannot read.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.common.email.sender import EmailMessage
from app.core.config import Settings, get_settings
from app.core.otp import OTP_TTL_MINUTES, OtpPurpose

TEMPLATE_DIR = Path(__file__).parent / "templates"


@lru_cache(maxsize=1)
def _environment() -> Environment:
    """Jinja environment, built once.

    `StrictUndefined` turns a typo'd variable into a loud error at render time
    instead of silently rendering an empty string. An OTP email that renders
    "Your code is:" with no code is worse than one that fails to send -- the user
    is stuck with no signal that anything went wrong.
    """
    return Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html", "xml"]),
        undefined=StrictUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )


# Subject lines and the action sentence for each flow. Centralised so the three
# OTP emails stay consistent in tone and structure, and so adding a flow is one
# entry rather than a new template pair.
_OTP_COPY: dict[OtpPurpose, tuple[str, str]] = {
    OtpPurpose.SIGNUP_VERIFY: (
        "Verify your email address",
        "Use this code to verify your email address and finish creating your account.",
    ),
    OtpPurpose.PASSWORD_RESET: (
        "Reset your password",
        "Use this code to reset your password.",
    ),
    OtpPurpose.LOGIN_2FA: (
        "Your sign-in code",
        "Use this code to finish signing in.",
    ),
    OtpPurpose.EMAIL_CHANGE: (
        "Confirm your new email address",
        "Use this code to confirm your new email address.",
    ),
}


def render_otp_email(
    *,
    to: str,
    code: str,
    purpose: OtpPurpose,
    recipient_name: str | None = None,
    settings: Settings | None = None,
) -> EmailMessage:
    """Render the OTP email for a given flow.

    Args:
        to: recipient address.
        code: the plaintext OTP. This is the ONLY place it legitimately appears
            outside memory -- it is never logged and never persisted.
        purpose: selects subject and body copy.
        recipient_name: personalisation; falls back to a neutral greeting.
    """
    settings = settings or get_settings()
    subject, action_text = _OTP_COPY[purpose]

    context = {
        "code": code,
        "subject": subject,
        "action_text": action_text,
        "greeting_name": recipient_name or "there",
        "ttl_minutes": OTP_TTL_MINUTES,
        "app_name": settings.APP_NAME,
        "logo_url": settings.EMAIL_LOGO_URL or None,
        "frontend_url": settings.FRONTEND_URL,
        # Password reset is the flow attackers trigger against victims, so it gets
        # an explicit "someone may be trying to access your account" warning that
        # the benign flows do not need.
        "show_security_warning": purpose in (OtpPurpose.PASSWORD_RESET, OtpPurpose.LOGIN_2FA),
    }

    env = _environment()
    return EmailMessage(
        to=to,
        subject=f"{code} — {subject}",  # code in the subject: visible from the
        # notification banner without opening the mail
        html_body=env.get_template("otp.html").render(**context),
        text_body=env.get_template("otp.txt").render(**context),
        tags={"purpose": purpose.value},
    )


# ---------------------------------------------------------------------------
# Link-action emails (spec §4.3, §7)
# ---------------------------------------------------------------------------


class ActionPurpose(StrEnum):
    """The link-based flows. Distinct from `OtpPurpose`: these carry a URL, not a code.

    WHY LINKS AND NOT CODES FOR THESE THREE
        A 6-digit code is right when the user is already sitting in the flow and just
        needs to prove inbox access -- they type it into a form they can see.

        These three arrive cold. An invitation reaches someone who has never used the
        product and has no page open to type a code into; email verification and
        password reset land the same way. A link takes them to the right screen with
        the right context already loaded, which is the difference between a completed
        signup and an abandoned one.
    """

    VERIFY_EMAIL = "verify_email"
    RESET_PASSWORD = "reset_password"
    INVITATION = "invitation"


# Subject, greeting sentence, button label, and the closing security note per flow.
#
# The security notes differ on purpose. Verification is benign -- a stray one means
# someone mistyped their address. Reset and invitation are the two an attacker
# triggers AT a victim, so each says plainly what to do if it was unexpected.
_ACTION_COPY: dict[ActionPurpose, tuple[str, str, str, str]] = {
    ActionPurpose.VERIFY_EMAIL: (
        "Verify your email address",
        "Confirm this address to finish setting up your account.",
        "Verify email address",
        "If you did not create an account, you can safely ignore this message.",
    ),
    ActionPurpose.RESET_PASSWORD: (
        "Reset your password",
        "We received a request to reset the password on your account.",
        "Reset password",
        "If you did not request this, ignore this email — your password is unchanged. "
        "If you receive these repeatedly, someone may be trying to access your account.",
    ),
    ActionPurpose.INVITATION: (
        "You have been invited",
        "You have been invited to join a school on {app_name}.",
        "Accept invitation",
        "If you were not expecting this invitation, you can safely ignore it. "
        "Nothing is shared with you until you accept.",
    ),
}


def render_action_email(
    *,
    to: str,
    action_url: str,
    purpose: ActionPurpose,
    recipient_name: str | None = None,
    details: list[tuple[str, str]] | None = None,
    expiry_text: str = "24 hours",
    settings: Settings | None = None,
) -> EmailMessage:
    """Render a link-action email.

    Args:
        to: recipient address.
        action_url: the full URL including the RAW token. This is the ONLY place the
            raw token legitimately appears outside memory -- the database holds only
            its SHA-256 digest, and it is never logged.
        purpose: selects subject, copy and button label.
        recipient_name: personalisation; falls back to a neutral greeting.
        details: label/value rows shown in a summary box. Used by invitations to show
            the school and role, so the recipient can tell a legitimate invite from a
            phishing attempt WITHOUT having to click the link to find out.
        expiry_text: human phrasing of the validity window, e.g. "7 days".
    """
    settings = settings or get_settings()
    subject, action_text, button_label, security_note = _ACTION_COPY[purpose]
    action_text = action_text.format(app_name=settings.APP_NAME)

    context = {
        "subject": subject,
        "action_text": action_text,
        "button_label": button_label,
        "security_note": security_note,
        "action_url": action_url,
        "details": details or [],
        "expiry_text": expiry_text,
        "greeting_name": recipient_name or "there",
        "app_name": settings.APP_NAME,
        "logo_url": settings.EMAIL_LOGO_URL or None,
        "preheader": f"{action_text} This link expires in {expiry_text}.",
    }

    env = _environment()
    return EmailMessage(
        to=to,
        subject=subject,
        html_body=env.get_template("action.html").render(**context),
        text_body=env.get_template("action.txt").render(**context),
        tags={"purpose": purpose.value},
    )
