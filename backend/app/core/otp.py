"""One-time password generation and verification.

WHY THIS FILE EXISTS
    OTPs guard three separate doors in this system -- signup verification, password
    reset, and login 2FA. Each has the same cryptographic requirements, and each is
    easy to get wrong in a way that is invisible until exploited. One module owns
    the primitives; the auth service owns the workflow.

RESPONSIBILITY
    Generate codes, derive verification digests, compare them safely. Pure
    computation -- no database, no email, no I/O -- which is what makes every
    property below directly unit-testable.

INTERACTIONS
    * `modules/auth/service.py` calls these when issuing and checking codes.
    * The digest is what gets persisted; the plaintext code exists only in memory
      and in the email that is sent.

=============================================================================
THE FOUR DESIGN DECISIONS, AND WHY
=============================================================================

1. `secrets`, NEVER `random`
   `random` is a Mersenne Twister seeded from the clock. Observing a handful of
   outputs lets an attacker predict every subsequent code. `secrets` draws from the
   OS CSPRNG. This is a one-word difference with a total difference in security.

2. HMAC-SHA256 with a server-side pepper, NOT Argon2 and NOT a bare hash
   A 6-digit code has only 10^6 possible values. If the database leaks and codes
   were stored under a plain SHA-256, an attacker enumerates the entire keyspace in
   under a second. Argon2 would resist that, but costs ~100ms per verification --
   and OTPs are verified on a hot path.

   HMAC with a secret the database does not contain is the right trade: verification
   is microseconds, and an attacker holding only a database dump cannot brute-force
   anything, because they lack the key. The defence rests on SECRET_KEY secrecy
   rather than on computational cost -- appropriate for a credential that dies in
   ten minutes.

3. THE PURPOSE IS BOUND INTO THE DIGEST (domain separation)
   The digest covers `purpose|identifier|code`, not just `code`. Without this, an
   OTP mailed for "verify your email" could be replayed against the password-reset
   endpoint -- an attacker who can trigger the benign flow gets a code that opens
   the dangerous one. Binding the purpose makes a code cryptographically useless
   outside the flow it was issued for.

   The identifier (user id or email) is bound for the same reason: it stops a code
   issued to attacker@evil.com being submitted for victim@school.com.

4. CONSTANT-TIME COMPARISON
   `==` on bytes short-circuits at the first differing byte. Timing that comparison
   across many attempts leaks the digest one byte at a time. `hmac.compare_digest`
   takes the same time regardless of where the mismatch is.

WHAT THIS MODULE DELIBERATELY DOES NOT DO
    Expiry, attempt-counting and single-use enforcement are STATE, and state lives
    in the database. A correct implementation needs all three -- see the notes on
    `OtpPurpose` -- but they belong to the auth service and its `otp_codes` table,
    not here.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from enum import StrEnum

from app.core.config import Settings, get_settings

# Six digits is the usability/security balance users expect from SMS and email
# codes. The security does NOT come from the code's entropy -- 10^6 is trivially
# brute-forceable -- it comes from the auth service enforcing a short expiry and a
# hard attempt limit. Without those two controls a 6-digit code is worthless, and
# with them a longer code buys very little.
OTP_LENGTH = 6

# Ten minutes: long enough to survive slow email delivery and a user switching
# apps, short enough that a code intercepted from an inbox is usually already dead.
OTP_TTL_MINUTES = 10

# After this many wrong guesses the code is burned and must be re-requested.
# THIS IS THE PRIMARY DEFENCE. At 5 attempts against 10^6 codes, an attacker's
# chance is 1 in 200,000 per issued code. Without the cap, 10^6 requests breaks it
# every time.
OTP_MAX_ATTEMPTS = 5

# Minimum gap between sends to the same address. Stops an attacker using our SMTP
# server to flood someone's inbox, and stops a stuck frontend burning the Gmail
# daily quota.
OTP_RESEND_COOLDOWN_SECONDS = 60


class OtpPurpose(StrEnum):
    """What a given code is allowed to authorise.

    Bound into the digest, so codes are not interchangeable between flows.
    Persisted alongside the digest so the service can also reject a mismatched
    purpose before it even reaches the comparison.
    """

    SIGNUP_VERIFY = "signup_verify"
    PASSWORD_RESET = "password_reset"
    LOGIN_2FA = "login_2fa"
    EMAIL_CHANGE = "email_change"


def generate_otp(length: int = OTP_LENGTH) -> str:
    """Return a cryptographically random numeric code, zero-padded.

    Zero-padding matters: without it, `secrets.randbelow(10**6)` returns 42 as
    "42" rather than "000042", so ~10% of codes are shorter than advertised. That
    both looks broken to users and measurably shrinks the keyspace.
    """
    upper_bound = 10**length
    return str(secrets.randbelow(upper_bound)).zfill(length)


def hash_otp(
    code: str,
    *,
    purpose: OtpPurpose,
    identifier: str,
    settings: Settings | None = None,
) -> str:
    """Derive the digest to persist. Never store `code` itself.

    Args:
        code: the plaintext code that was emailed.
        purpose: the flow this code authorises -- bound in, see module docstring.
        identifier: user id or email address, normalised by the caller.

    Returns:
        Hex-encoded HMAC-SHA256 digest.
    """
    settings = settings or get_settings()

    # The separator must be a character that cannot appear in any component,
    # otherwise ("ab", "c") and ("a", "bc") produce identical messages -- a
    # canonicalisation ambiguity that would let one flow's code match another's.
    # Email addresses and UUIDs cannot contain a null byte.
    message = f"{purpose.value}\x00{identifier}\x00{code}".encode()

    return hmac.new(
        key=settings.SECRET_KEY.encode(),
        msg=message,
        digestmod=hashlib.sha256,
    ).hexdigest()


def verify_otp(
    code: str,
    stored_hash: str,
    *,
    purpose: OtpPurpose,
    identifier: str,
    settings: Settings | None = None,
) -> bool:
    """Constant-time check of a submitted code against the stored digest.

    Returns a plain bool. The CALLER is still responsible for checking expiry,
    the attempt counter, and whether the code was already consumed -- a `True`
    here means only "this code matches", never "this code is usable".
    """
    expected = hash_otp(code, purpose=purpose, identifier=identifier, settings=settings)
    return hmac.compare_digest(expected, stored_hash)


def normalise_identifier(value: str) -> str:
    """Canonicalise an email/identifier before it is bound into a digest.

    Email addresses are case-insensitive in practice. Without normalisation,
    requesting a code as `User@x.com` and submitting it as `user@x.com` produces a
    different digest and the code silently fails -- a support ticket, not an attack,
    but a guaranteed one.
    """
    return value.strip().lower()
