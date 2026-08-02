"""Password strength policy (spec §4.4).

WHY THIS FILE EXISTS
    "Minimum 8 characters, one uppercase, one digit, one symbol" is the industry's
    most popular password rule and one of its least effective. It accepts `P@ssw0rd`
    and rejects `correct horse battery staple` -- exactly backwards. It also pushes
    users toward a small set of predictable mutations that every cracking dictionary
    already enumerates.

    Spec §4.4 therefore asks for three things instead: a length floor, an entropy
    estimate (zxcvbn score >= 3), and a check against known-breached passwords.
    Those three catch what composition rules miss.

RESPONSIBILITY
    Decide whether a candidate password is acceptable, and explain why not. No
    hashing (that is `core/security.py`), no storage, no HTTP.

INTERACTIONS
    Called by the auth service on register, password reset, and invitation accept --
    every path that sets a password. Raises `ValidationError`, which the API layer
    renders as 422 with field-level detail.

ON THE BREACHED-PASSWORD LIST
    The shipped list is a small local file of the most-reused passwords. It is
    deliberately NOT a network call to Have I Been Pwned's range API: signup would
    then depend on a third party being reachable, and an outage there would take
    down registration. The local list catches the overwhelming majority of real
    reuse; `BREACHED_PASSWORD_FILE` can point at a larger corpus in production.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from zxcvbn import zxcvbn

from app.core.config import Settings, get_settings
from app.core.exceptions import ValidationError

# Shipped alongside this module. One lowercase password per line, '#' comments.
_BREACHED_LIST_PATH = Path(__file__).parent / "data" / "breached_passwords.txt"


@lru_cache(maxsize=1)
def _breached_passwords() -> frozenset[str]:
    """Load the breached-password corpus once per process.

    Cached because this is called on every registration and reset. A missing file is
    tolerated rather than fatal: the length and entropy checks still apply, and
    refusing to boot because a supplementary wordlist is absent would be a
    self-inflicted outage.
    """
    if not _BREACHED_LIST_PATH.exists():
        return frozenset()
    lines = _BREACHED_LIST_PATH.read_text(encoding="utf-8").splitlines()
    return frozenset(
        line.strip().lower() for line in lines if line.strip() and not line.startswith("#")
    )


def validate_password(
    password: str,
    *,
    user_inputs: list[str] | None = None,
    settings: Settings | None = None,
) -> None:
    """Raise `ValidationError` unless `password` satisfies the policy.

    `user_inputs` should carry the person's own name, email and organization name.
    zxcvbn penalises passwords built from them, which is what catches the extremely
    common `Springfield High 2024!` chosen by an admin at Springfield High -- a
    password with fine surface entropy that the one attacker who matters can guess
    on the first try.

    Returns None on success rather than a bool: the caller cannot then forget to
    check a return value, which is the failure mode that makes validators useless.
    """
    settings = settings or get_settings()
    problems: list[str] = []

    if len(password) < settings.PASSWORD_MIN_LENGTH:
        problems.append(f"Must be at least {settings.PASSWORD_MIN_LENGTH} characters.")

    if password.lower() in _breached_passwords():
        problems.append("This password appears in known data breaches. Choose a different one.")

    # zxcvbn is the expensive check, so it runs only once the cheap ones pass --
    # there is no value in scoring the entropy of a password already rejected.
    if not problems:
        result = zxcvbn(password, user_inputs=[u for u in (user_inputs or []) if u])
        if result["score"] < settings.PASSWORD_MIN_ZXCVBN_SCORE:
            feedback = result.get("feedback", {})
            suggestion = feedback.get("warning") or " ".join(feedback.get("suggestions", []))
            problems.append(
                suggestion
                or "This password is too easy to guess. Try a longer phrase of unrelated words."
            )

    if problems:
        raise ValidationError(
            " ".join(problems),
            code="WEAK_PASSWORD",
            details={"field": "password", "problems": problems},
        )
