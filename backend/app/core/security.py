"""Password hashing, JWT issuance/verification, and opaque token handling.

WHY THIS FILE EXISTS
    Cryptographic primitives are easy to get subtly wrong and must never be
    scattered. One module owns hashing and token handling; the rest of the app
    calls these functions and nothing else.

RESPONSIBILITY
    * Hash and verify passwords (Argon2id).
    * Mint and decode signed access JWTs carrying the tenant context.
    * Generate and digest the opaque tokens used for refresh, invitations,
      email verification and password reset.
    It does NOT know about users, sessions, or the database -- that is the auth
    service's job. This module is pure computation and therefore trivially testable.

INTERACTIONS
    * `modules/auth/service.py` calls it to log users in and issue token pairs.
    * `api/deps.py` calls `decode_access_token` to authenticate incoming requests.
    * `modules/invitations`, `modules/billing` use the opaque-token helpers.

=============================================================================
TWO KINDS OF TOKEN, AND WHY THEY ARE DIFFERENT SHAPES
=============================================================================
    ACCESS  -- a signed JWT, 15 minutes, stateless. Verifying it is a signature
               check with no database round-trip, which is what makes it cheap
               enough to put on every request. The cost of statelessness is that
               it cannot be revoked before it expires; 15 minutes is the accepted
               exposure window.

    REFRESH -- 256 bits of opaque randomness, 30 days, stored only as a SHA-256
               digest. Deliberately NOT a JWT: a refresh token's whole purpose is
               to be revocable, so it must be looked up in the database anyway,
               and making it self-describing would only leak claims to whoever
               steals it. Because it is checked against a row on every use, we can
               implement rotation with reuse detection (see the auth service).

    WHY SHA-256 AND NOT ARGON2 FOR THE OPAQUE TOKENS
        Argon2 is deliberately slow, which is correct for passwords -- they are
        low-entropy and must resist offline brute force. These tokens carry 256
        bits of entropy from `secrets`, so brute force is not a threat model and
        slowness would just be latency on the refresh hot path. What we need is a
        one-way digest so a database leak does not hand over live sessions, and
        SHA-256 provides exactly that.

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

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any, Self
from uuid import UUID, uuid4

import jwt
from pwdlib import PasswordHash

from app.core.config import Settings, get_settings
from app.core.exceptions import AuthenticationError

# Argon2id with library defaults (tuned to OWASP guidance).
_password_hasher = PasswordHash.recommended()

# Number of random bytes in an opaque token. 32 bytes = 256 bits, which is far
# beyond any feasible guessing attack and matches spec §7.1's `token_urlsafe(32)`.
_OPAQUE_TOKEN_BYTES = 32


class TokenType(StrEnum):
    """Access vs refresh, encoded in the `typ` claim... of the access token only.

    Refresh tokens are opaque and carry no claims at all, so there is nothing to
    confuse them with. This enum survives so `decode_access_token` can assert it is
    not being handed some other JWT the system might mint later.
    """

    ACCESS = "access"


class PrincipalType(StrEnum):
    """Which authentication surface a token belongs to -- the `typ` claim (spec §4.2).

    THIS SEPARATION IS LOAD-BEARING. A platform super admin and an organization user
    authenticate through different endpoints, are stored in different tables, and
    must never be interchangeable. Without an explicit claim, the only thing
    distinguishing them would be the presence of an `org` claim -- and "absent claim"
    is a terrible thing to hang a privilege boundary on, because a bug that drops the
    claim silently promotes a tenant user to platform scope.
    """

    TENANT = "tenant"
    PLATFORM = "platform"
    CONTEXT_SELECTION = "context_selection"

    # --- Guardian portal ---------------------------------------------------
    #
    # A THIRD SURFACE, for the same reason there is a second: guardians live in their
    # own identity table, hold no membership, and must never be interchangeable with
    # staff. A guardian token carries `org` -- so RLS binds correctly when the portal
    # reads that organization's students -- and it is EXACTLY that claim which makes
    # an explicit `typ` non-negotiable here. Without it, "has an org claim but no
    # membership claim" would be the only thing separating a parent from a member of
    # staff, and one dropped claim would promote the parent.
    GUARDIAN = "guardian"
    GUARDIAN_CONTEXT_SELECTION = "guardian_context_selection"


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


# A pre-computed hash of a value nobody can supply, used to burn the same CPU time
# on a missing account as on a real one. See `dummy_password_verify`.
_DUMMY_HASH = _password_hasher.hash(secrets.token_urlsafe(32))


def dummy_password_verify() -> None:
    """Burn one Argon2 verification's worth of time, deliberately.

    WHY THIS EXISTS (spec §4.4 + §12 "Auth")
        Argon2 is slow by design -- tens of milliseconds. If login skips it when the
        email is unknown, "unknown address" returns in 2ms and "known address, wrong
        password" in 60ms. That difference is trivially measurable over a network and
        turns the login endpoint into a user-enumeration oracle: an attacker learns
        which of a leaked address list are real customers of this platform, which for
        a school system means learning which schools are clients.

        Identical response bodies are not enough on their own. The timing must match
        too, which is what this call buys.
    """
    _password_hasher.verify("not-the-password", _DUMMY_HASH)


# ---------------------------------------------------------------------------
# Opaque tokens (refresh, invitation, verification, reset)
# ---------------------------------------------------------------------------


def generate_opaque_token() -> str:
    """Return a fresh 256-bit URL-safe token. The RAW value; never persist it."""
    return secrets.token_urlsafe(_OPAQUE_TOKEN_BYTES)


def hash_token(raw_token: str) -> str:
    """SHA-256 hex digest of an opaque token -- what actually goes in the database.

    Spec §4.4: "look up by hash, never by raw value". Storing the raw token would
    mean a read-only database leak hands the attacker every live session, every
    pending invitation and every password-reset link. Storing the digest means it
    hands them nothing usable.
    """
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def tokens_match(raw_token: str, stored_hash: str) -> bool:
    """Timing-safe comparison of a presented token against a stored digest.

    `compare_digest` rather than `==` because Python's string equality short-circuits
    on the first differing byte. An attacker who can measure that can recover a
    digest byte by byte. The lookup itself is by hash (an indexed equality search
    inside the database), and this guards the final confirmation.
    """
    return hmac.compare_digest(hash_token(raw_token), stored_hash)


# ---------------------------------------------------------------------------
# Access tokens
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AccessClaims:
    """The decoded, validated payload of an access token (spec §4.2).

    A typed object rather than a raw dict so that a typo in a claim name is a
    static error instead of a silent `None` that reads as "no organization" --
    which, in a system where the org claim IS the tenant boundary, would be a
    fail-open bug.
    """

    user_id: UUID
    principal_type: PrincipalType
    session_id: UUID
    membership_id: UUID | None = None
    organization_id: UUID | None = None
    school_id: UUID | None = None
    role_code: str | None = None
    permissions_version: int | None = None
    guardian_id: UUID | None = None
    """The tenant-scoped guardian record this portal session is acting as (`grd`).

    Present only on guardian tokens. Deliberately NOT reusing `mid`: a membership and
    a guardian record are different tables with different privileges, and a bug that
    read one as the other would hand a parent a staff permission set."""

    @property
    def is_platform(self) -> bool:
        return self.principal_type is PrincipalType.PLATFORM

    @property
    def is_context_selection(self) -> bool:
        return self.principal_type is PrincipalType.CONTEXT_SELECTION

    @property
    def is_guardian(self) -> bool:
        """Either guardian posture: a full portal session or the pre-context step."""
        return self.principal_type in (
            PrincipalType.GUARDIAN,
            PrincipalType.GUARDIAN_CONTEXT_SELECTION,
        )

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> Self:
        """Build from raw JWT claims, rejecting anything malformed.

        Every parse failure becomes `AuthenticationError`, never a `ValueError`
        escaping as a 500. A token we cannot understand is a token we do not trust.
        """

        def _uuid(key: str) -> UUID | None:
            raw = payload.get(key)
            return UUID(raw) if raw else None

        try:
            user_id = UUID(payload["sub"])
            session_id = UUID(payload["sid"])
            principal_type = PrincipalType(payload["typ"])
            return cls(
                user_id=user_id,
                principal_type=principal_type,
                session_id=session_id,
                membership_id=_uuid("mid"),
                organization_id=_uuid("org"),
                school_id=_uuid("sch"),
                role_code=payload.get("rol"),
                permissions_version=payload.get("pv"),
                guardian_id=_uuid("grd"),
            )
        except (KeyError, ValueError) as exc:
            raise AuthenticationError("Token claims are malformed.", code="TOKEN_INVALID") from exc


def create_access_token(
    *,
    user_id: UUID,
    session_id: UUID,
    principal_type: PrincipalType = PrincipalType.TENANT,
    membership_id: UUID | None = None,
    organization_id: UUID | None = None,
    school_id: UUID | None = None,
    role_code: str | None = None,
    permissions_version: int | None = None,
    guardian_id: UUID | None = None,
    expires_minutes: int | None = None,
    settings: Settings | None = None,
) -> str:
    """Mint a short-lived access token for exactly one membership.

    THE `org` CLAIM IS THE TENANT BOUNDARY. It is copied into the PostgreSQL session
    variable that every RLS policy reads. Because the token is signed, a client
    cannot alter it to read another organization's data -- which is why the key
    strength checks in `config.py` are not ceremony.

    ONE MEMBERSHIP AT A TIME (spec decision D4). A human may be a teacher at School A
    and an accountant at School B; the token names one of those, and switching costs
    a re-issue via `POST /auth/context`. The alternative -- a token listing every
    membership -- would mean every request carries ambient authority the user did not
    ask to exercise, and one confused-deputy bug would cross a school boundary.

    PERMISSIONS ARE NOT IN THE TOKEN. Only `pv` (the role's permissions_version) is.
    The permission set is resolved from Redis on each request, keyed by
    `(role_id, pv)`. Embedding the set would mean a principal who revokes a teacher's
    access waits a full token lifetime for it to take effect -- the classic
    "I removed their access 15 minutes ago and they can still delete records" bug.
    Bumping `pv` invalidates every existing token for that role instantly.
    """
    settings = settings or get_settings()
    now = datetime.now(UTC)

    payload: dict[str, Any] = {
        "sub": str(user_id),  # RFC 7519 requires `sub` to be a string
        "typ": principal_type.value,
        "sid": str(session_id),
        "iat": now,
        "exp": now
        + timedelta(
            minutes=expires_minutes
            if expires_minutes is not None
            else settings.ACCESS_TOKEN_EXPIRE_MINUTES
        ),
        "jti": str(uuid4()),
    }
    # Absent rather than null: a claim that is not there cannot be mistaken for a
    # claim whose value happens to be falsy.
    if membership_id is not None:
        payload["mid"] = str(membership_id)
    if organization_id is not None:
        payload["org"] = str(organization_id)
    if school_id is not None:
        payload["sch"] = str(school_id)
    if role_code is not None:
        payload["rol"] = role_code
    if permissions_version is not None:
        payload["pv"] = permissions_version
    if guardian_id is not None:
        payload["grd"] = str(guardian_id)

    return jwt.encode(payload, settings.jwt_signing_key, algorithm=settings.JWT_ALGORITHM)


def decode_access_token(token: str, *, settings: Settings | None = None) -> AccessClaims:
    """Verify signature + expiry and return typed claims.

    Raises `AuthenticationError` (never a raw JWT exception) so callers depend only
    on our domain vocabulary.
    """
    settings = settings or get_settings()
    try:
        payload: dict[str, Any] = jwt.decode(
            token,
            settings.jwt_verification_key,
            # An ALLOWLIST, not a preference. Without it PyJWT would honour the
            # token's own `alg` header, and an attacker could present `alg: none`
            # (no signature) or downgrade RS256 to HS256 using the public key as the
            # HMAC secret. Both are real, repeatedly-exploited JWT attacks.
            algorithms=[settings.JWT_ALGORITHM],
            options={"require": ["exp", "sub", "typ", "sid"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Token has expired.", code="TOKEN_EXPIRED") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError("Token is invalid.", code="TOKEN_INVALID") from exc

    return AccessClaims.from_payload(payload)
