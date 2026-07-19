"""Password hashing and JWT issuance/verification.

WHY THIS FILE EXISTS
    Cryptographic primitives are easy to get subtly wrong and must never be
    scattered. One module owns hashing and token handling; the rest of the app
    calls these four functions and nothing else.

RESPONSIBILITY
    * Hash and verify passwords.
    * Mint and decode signed JWTs.
    It does NOT know about users, sessions, or the database -- that is the auth
    service's job. This module is pure computation and therefore trivially testable.

INTERACTIONS
    * `modules/auth/service.py` calls it to log users in and issue token pairs.
    * `api/deps.py` calls `decode_token` to authenticate incoming requests.

DEVIATIONS FROM THE SKILL PLAYBOOK (both are security-relevant, not stylistic):
    1. `python-jose` -> `PyJWT`. python-jose is effectively unmaintained and has
       had algorithm-confusion CVEs. PyJWT is actively maintained.
    2. `passlib[bcrypt]` -> `pwdlib[argon2]`. Passlib's last release predates
       bcrypt 4.1 and crashes against it; Argon2id is the current OWASP
       recommendation for password storage.
    3. `datetime.utcnow()` -> `datetime.now(UTC)`. utcnow() returns a *naive*
       datetime and is deprecated in Python 3.12+.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings, get_settings
from app.core.exceptions import AuthenticationError

# Argon2id with library defaults (tuned to OWASP guidance).
_password_hasher = PasswordHash.recommended()


class TokenType(StrEnum):
    """Access vs refresh.

    Encoded in the `typ` claim and checked on decode, so a refresh token can never
    be replayed as an access token (a classic privilege-escalation bug).
    """

    ACCESS = "access"
    REFRESH = "refresh"


# ---------------------------------------------------------------------------
# Passwords
# ---------------------------------------------------------------------------


def hash_password(plain_password: str) -> str:
    """Return an Argon2id hash. Salt is generated internally and stored in the hash."""
    return _password_hasher.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Constant-time verification. Returns False on malformed hashes rather than raising."""
    try:
        return _password_hasher.verify(plain_password, hashed_password)
    except Exception:
        # A corrupt or legacy hash must read as "wrong password", never as a 500.
        return False


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


def _create_token(
    *,
    subject: UUID,
    token_type: TokenType,
    expires_delta: timedelta,
    claims: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> str:
    settings = settings or get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": str(subject),  # RFC 7519 requires `sub` to be a string
        "typ": token_type.value,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid4()),  # unique id -> enables future token revocation
        **(claims or {}),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(
    subject: UUID,
    *,
    school_id: UUID | None = None,
    role: str | None = None,
    is_super_admin: bool = False,
    settings: Settings | None = None,
) -> str:
    """Mint a short-lived access token.

    THE `school_id` CLAIM IS THE TENANT BOUNDARY. It is copied into the PostgreSQL
    session variable that Row-Level Security policies read. Because the token is
    signed, a client cannot alter it to read another school's data. This is why
    SECRET_KEY strength is enforced in `config.py`.
    """
    settings = settings or get_settings()
    claims: dict[str, Any] = {"sa": is_super_admin}
    if school_id is not None:
        claims["sid"] = str(school_id)
    if role is not None:
        claims["role"] = role

    return _create_token(
        subject=subject,
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        claims=claims,
        settings=settings,
    )


def create_refresh_token(subject: UUID, *, settings: Settings | None = None) -> str:
    """Mint a long-lived refresh token.

    Deliberately carries NO tenant or role claims: those must be re-read from the
    database on refresh, so that a revoked user or changed role takes effect within
    one access-token lifetime rather than one refresh-token lifetime.
    """
    settings = settings or get_settings()
    return _create_token(
        subject=subject,
        token_type=TokenType.REFRESH,
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        settings=settings,
    )


def decode_token(
    token: str,
    *,
    expected_type: TokenType = TokenType.ACCESS,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Verify signature + expiry and return the claims.

    Raises `AuthenticationError` (never a raw JWT exception) so callers depend only
    on our domain vocabulary.
    """
    settings = settings or get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],  # allowlist -> blocks `alg: none`
            options={"require": ["exp", "sub", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired.", code="TOKEN_EXPIRED") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Token is invalid.", code="TOKEN_INVALID") from exc

    if payload.get("typ") != expected_type.value:
        raise AuthenticationError(
            f"Expected a {expected_type.value} token.", code="TOKEN_WRONG_TYPE"
        )
    return payload
