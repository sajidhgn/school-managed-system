"""TOTP generation, verification, and encrypted secret storage for platform MFA."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings

TOTP_PERIOD_SECONDS = 30
TOTP_DIGITS = 6


def generate_totp_secret() -> str:
    """Return a 160-bit base32 secret, the interoperable TOTP default."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _fernet(settings: Settings) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(settings.SECRET_KEY.encode()).digest())
    return Fernet(key)


def encrypt_totp_secret(secret: str, settings: Settings) -> str:
    return _fernet(settings).encrypt(secret.encode()).decode()


def decrypt_totp_secret(ciphertext: str, settings: Settings) -> tuple[str, bool]:
    """Return `(secret, was_legacy_plaintext)` for transparent one-time migration."""
    try:
        return _fernet(settings).decrypt(ciphertext.encode()).decode(), False
    except InvalidToken:
        # Older local databases stored base32 directly. A successful MFA login
        # rewrites it encrypted; malformed values still fail TOTP verification.
        return ciphertext, True


def totp_code(secret: str, step: int) -> str:
    padded = secret.upper() + "=" * ((8 - len(secret) % 8) % 8)
    key = base64.b32decode(padded, casefold=True)
    digest = hmac.new(key, struct.pack(">Q", step), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (int.from_bytes(digest[offset : offset + 4], "big") & 0x7FFFFFFF) % (10**TOTP_DIGITS)
    return f"{value:0{TOTP_DIGITS}d}"


def verify_totp(
    secret: str,
    supplied: str,
    *,
    unix_time: int,
    last_used_step: int | None,
) -> int | None:
    """Verify ±1 time step and return the accepted, non-replayed counter."""
    if len(supplied) != TOTP_DIGITS or not supplied.isdigit():
        return None
    current = unix_time // TOTP_PERIOD_SECONDS
    for step in (current, current - 1, current + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        if hmac.compare_digest(totp_code(secret, step), supplied):
            return step
    return None


def provisioning_uri(*, secret: str, email: str, issuer: str = "EduCloud") -> str:
    label = quote(f"{issuer}:{email}")
    return (
        f"otpauth://totp/{label}?secret={quote(secret)}&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={TOTP_DIGITS}&period={TOTP_PERIOD_SECONDS}"
    )
