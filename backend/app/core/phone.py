"""Phone number normalisation to E.164.

WHY THIS FILE EXISTS
    A guardian's phone number is about to become a LOGIN IDENTIFIER, and an
    identifier that has several spellings is not an identifier at all. The same
    Pakistani mobile arrives from a school's front office as `0300-1234567`,
    `03001234567`, `+92 300 1234567`, `0092 300 1234567` and `92 300 1234567`.
    Stored verbatim, those are five guardians, five parent portal accounts, and a
    father who cannot log in because the office typed the dashes differently the day
    his second child enrolled.

    One canonical form -- E.164, `+` followed by country code and subscriber number,
    digits only -- collapses all five into one row and makes the unique index mean
    something.

RESPONSIBILITY
    Turn free text into E.164, or refuse. Pure computation: no database, no config
    lookup beyond the default calling code passed in by the caller.

INTERACTIONS
    * `modules/guardians/service.py` normalises before insert and before lookup.
    * `modules/guardians/auth_service.py` normalises the login identifier, so the
      OTP digest is bound to the canonical string and cannot be replayed against a
      differently-spelled version of the same number.

WHY NOT THE `phonenumbers` LIBRARY
    It is the correct answer for validating that a number is *dialable* -- it carries
    Google's per-country numbering plans and knows that `+92 300` is a mobile prefix
    and `+92 21` is a Karachi landline. It is deliberately not used here for two
    reasons: it is a multi-megabyte metadata dependency that would need updating on
    its own schedule, and its stricter validation rejects real numbers in edge cases
    (new prefixes, ported ranges) which would lock a genuine parent out of the
    portal.

    What we actually need is weaker and stable: a canonical FORM, not a proof of
    dialability. If a number is wrong, the OTP simply never arrives -- which is
    feedback the parent gets in ten seconds. Rejecting a valid number at the front
    desk is the more expensive failure, so this module errs toward accepting.
"""

from __future__ import annotations

import re

from app.core.exceptions import ValidationError

# Everything that is decoration rather than digits. Schools paste numbers out of
# spreadsheets, WhatsApp and printed admission forms, so all of these turn up.
_DECORATION = re.compile("[\\s\\-(). \u00a0\u200e\u200f]")

# E.164: `+`, a leading digit 1-9, then up to 14 more. The 15-digit ceiling is the
# ITU-T limit, and the "no leading zero" rule is what makes `+0...` -- a
# half-converted national number -- fail here rather than silently become a second
# identity for the same human.
_E164 = re.compile(r"^\+[1-9]\d{6,14}$")

# The shortest thing we will treat as a subscriber number at all. Seven digits is
# below every national mobile plan; anything shorter is a short code, an extension,
# or a typo, and none of those can receive an OTP.
MIN_SUBSCRIBER_DIGITS = 7


def normalise_phone(
    raw: str,
    *,
    default_calling_code: str = "",
    trunk_prefix: str = "0",
) -> str:
    """Return `raw` as E.164, or raise `ValidationError`.

    Args:
        raw: whatever the user typed.
        default_calling_code: digits only, no `+` (e.g. `"92"`). Used only for input
            that carries no international prefix of its own. Empty means "refuse
            national-format input", which is the right default for a deployment
            serving several countries -- guessing a country there would silently
            create a valid-looking number in the wrong one.
        trunk_prefix: the national dialling prefix stripped before the calling code
            is prepended (`0` almost everywhere; `1` in NANP countries, which do not
            need this path at all).

    THE ORDER OF THE BRANCHES IS THE WHOLE ALGORITHM, and each one exists because a
    real school types numbers that way:

      `+92300...`   already international -> accepted as-is.
      `0092300...`  the ISO/IEC dial-out prefix -> `00` becomes `+`.
      `0300...`     national format -> strip ONE trunk `0`, prepend the calling code.
      `92300...`    bare digits that already start with the calling code -> prepend
                    `+` only. Without this branch, a spreadsheet column exported
                    without its `+` would become `+9292300...`.
      `300...`      bare national significant number -> prepend the calling code.
    """
    cleaned = _DECORATION.sub("", raw or "")
    if not cleaned:
        raise ValidationError("A phone number is required.", code="PHONE_REQUIRED")

    if cleaned.startswith("00"):
        cleaned = "+" + cleaned[2:]

    if not cleaned.startswith("+"):
        code = _DECORATION.sub("", default_calling_code).lstrip("+")
        if not code:
            raise ValidationError(
                "Enter the phone number in international format, starting with '+'.",
                code="PHONE_NOT_INTERNATIONAL",
            )
        national = cleaned
        if trunk_prefix and national.startswith(trunk_prefix):
            # ONE prefix, not `lstrip`. `lstrip("0")` on `0300...` is fine but on a
            # hypothetical `00...`-style national number would eat both, and on a
            # subscriber number that legitimately begins `0` after the trunk digit it
            # would eat a digit that belongs to the person.
            national = national[len(trunk_prefix) :]
        if not national.startswith(code):
            national = code + national
        cleaned = "+" + national

    digits = cleaned[1:]
    if not digits.isdigit():
        raise ValidationError(
            "A phone number may contain only digits, spaces and + ( ) -.",
            code="PHONE_INVALID",
        )
    if len(digits) < MIN_SUBSCRIBER_DIGITS:
        raise ValidationError("That phone number is too short.", code="PHONE_TOO_SHORT")
    if not _E164.match(cleaned):
        raise ValidationError(
            "That phone number is not valid. Use international format, e.g. +923001234567.",
            code="PHONE_INVALID",
        )
    return cleaned


def mask_phone(e164: str) -> str:
    """Return a display-safe form: `+92300*****67`.

    Used in responses to an UNAUTHENTICATED caller -- "we sent a code to +92300*****67"
    -- so the parent can confirm which of their numbers the school holds without the
    endpoint becoming a way to read a number out of the database by guessing.
    """
    if len(e164) <= 6:
        return "*" * len(e164)
    return f"{e164[:6]}{'*' * (len(e164) - 8)}{e164[-2:]}"
