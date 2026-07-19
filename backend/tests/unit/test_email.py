"""Tests for email rendering and transport selection."""

from __future__ import annotations

import pytest

from app.common.email.sender import ConsoleEmailSender, EmailSender, build_email_sender
from app.common.email.templates import render_otp_email
from app.core.config import Environment, Settings
from app.core.otp import OtpPurpose


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        ENVIRONMENT=Environment.TEST,
        SECRET_KEY="unit-test-secret",
        APP_NAME="School Manage",
        EMAIL_FROM_ADDRESS="noreply@schoolmanage.test",
        EMAIL_FROM_NAME="School Manage",
    )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("purpose", list(OtpPurpose))
def test_every_purpose_renders_both_parts(purpose: OtpPurpose, settings: Settings) -> None:
    """Every flow must produce HTML *and* plaintext -- see the multipart rationale.

    Parametrised over the whole enum so adding a purpose without copy fails here
    rather than at 2am when a user cannot reset their password.
    """
    message = render_otp_email(
        to="parent@school.com", code="482913", purpose=purpose, settings=settings
    )

    assert message.html_body.strip()
    assert message.text_body.strip()
    assert "482913" in message.html_body
    assert "482913" in message.text_body


def test_code_appears_in_subject(settings: Settings) -> None:
    """Visible from the notification banner without opening the mail."""
    message = render_otp_email(
        to="a@b.com", code="482913", purpose=OtpPurpose.LOGIN_2FA, settings=settings
    )

    assert "482913" in message.subject


def test_recipient_name_is_used_when_given(settings: Settings) -> None:
    message = render_otp_email(
        to="a@b.com",
        code="111111",
        purpose=OtpPurpose.SIGNUP_VERIFY,
        recipient_name="Sajid",
        settings=settings,
    )

    assert "Sajid" in message.text_body


def test_missing_name_falls_back_to_neutral_greeting(settings: Settings) -> None:
    """Must never render "Hi ," or "Hi None,"."""
    message = render_otp_email(
        to="a@b.com", code="111111", purpose=OtpPurpose.SIGNUP_VERIFY, settings=settings
    )

    assert "Hi there," in message.text_body
    assert "None" not in message.text_body


def test_user_supplied_values_are_html_escaped() -> None:
    """A school or person named with markup must not become executable content.

    Autoescape is OFF by default in Jinja2, so this asserts we turned it on.
    """
    hostile_settings = Settings(
        _env_file=None,  # type: ignore[call-arg]
        ENVIRONMENT=Environment.TEST,
        SECRET_KEY="unit-test-secret",
        APP_NAME="<script>alert('xss')</script>",
    )

    message = render_otp_email(
        to="a@b.com",
        code="111111",
        purpose=OtpPurpose.LOGIN_2FA,
        recipient_name="<img src=x onerror=alert(1)>",
        settings=hostile_settings,
    )

    # The property that matters is that user input cannot introduce a TAG. Angle
    # brackets must come out escaped; the payload then renders as visible text and
    # cannot execute. Note that a substring like `onerror=` still appears in the
    # output -- that is fine and expected, because without a live `<` it is inert
    # text content, not an attribute. Asserting on `onerror=` alone would be
    # testing the wrong thing.
    assert "<script>" not in message.html_body
    assert "<img" not in message.html_body
    assert "&lt;script&gt;" in message.html_body
    assert "&lt;img src=x onerror=alert(1)&gt;" in message.html_body


def test_security_warning_only_on_sensitive_flows(settings: Settings) -> None:
    """Password reset and 2FA are the flows an attacker triggers against a victim,
    so only those carry the "didn't request this?" warning."""
    reset = render_otp_email(
        to="a@b.com", code="111111", purpose=OtpPurpose.PASSWORD_RESET, settings=settings
    )
    signup = render_otp_email(
        to="a@b.com", code="111111", purpose=OtpPurpose.SIGNUP_VERIFY, settings=settings
    )

    assert "did not request" in reset.text_body.lower()
    assert "did not request" not in signup.text_body.lower()


# ---------------------------------------------------------------------------
# Transport selection
# ---------------------------------------------------------------------------


def test_console_backend_is_the_default(settings: Settings) -> None:
    """The default must never deliver real mail -- a test run that emails real
    parents cannot be undone."""
    assert settings.EMAIL_BACKEND == "console"
    assert isinstance(build_email_sender(settings), ConsoleEmailSender)


def test_console_sender_satisfies_the_protocol() -> None:
    assert isinstance(ConsoleEmailSender(), EmailSender)


def test_from_header_is_rfc5322_formatted(settings: Settings) -> None:
    """`EMAIL_FROM=School Manage` (a bare display name, as in the Nodemailer
    config) is rejected by most receiving servers. A real mailbox is required."""
    assert settings.email_from == "School Manage <noreply@schoolmanage.test>"


def test_production_rejects_console_backend() -> None:
    """Booting production with the console backend would log OTPs in plaintext and
    silently send nothing. Fail at startup instead."""
    with pytest.raises(ValueError, match="cannot be used in production"):
        Settings(
            _env_file=None,  # type: ignore[call-arg]
            ENVIRONMENT=Environment.PRODUCTION,
            SECRET_KEY="a-real-production-secret-value-here",
            EMAIL_BACKEND="console",
        )
