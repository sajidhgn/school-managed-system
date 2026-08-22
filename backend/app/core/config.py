"""Application configuration.

WHY THIS FILE EXISTS
    12-factor principle: config lives in the environment, never in code. This module
    is the *single* place that reads the environment. Nothing else in the codebase may
    call `os.getenv` -- that keeps configuration typed, validated at startup, and
    discoverable in one place.

RESPONSIBILITY
    Parse + validate environment variables into an immutable, typed `Settings` object.
    Fail loudly at boot if a required value is missing or malformed, rather than
    failing at 3am on the first request that touches it.

INTERACTIONS
    Imported by nearly every subsystem (db.session, core.security, core.logging, main).
    Always consumed via `get_settings()` so it can be dependency-overridden in tests.
"""

from __future__ import annotations

from enum import StrEnum
from functools import lru_cache
from typing import Literal

from pydantic import Field, PostgresDsn, computed_field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Environment(StrEnum):
    """Deployment environment.

    Drives behaviour that must differ between local dev and production:
    docs exposure, error verbosity, log format.
    """

    LOCAL = "local"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"


class Settings(BaseSettings):
    """Typed, validated application settings.

    NOTE (deviation from the skill playbook): the playbook uses the Pydantic v1
    `class Config:` inner class. That is deprecated in Pydantic v2 -- the correct
    form is `model_config = SettingsConfigDict(...)`.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # tolerate unrelated vars in the shell environment
    )

    # --- Application -------------------------------------------------------
    APP_NAME: str = "School Management System"
    ENVIRONMENT: Environment = Environment.LOCAL
    DEBUG: bool = False
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    LOG_JSON: bool = False

    # --- API ---------------------------------------------------------------
    API_V1_PREFIX: str = "/api/v1"
    CORS_ORIGINS: list[str] = Field(default_factory=list)

    # --- Security ----------------------------------------------------------
    SECRET_KEY: str = "insecure-dev-key-change-me"
    JWT_ALGORITHM: Literal["HS256", "RS256"] = "HS256"
    """HS256 in dev, RS256 in production (spec §4.1).

    HS256 uses one shared secret for signing AND verification, so anything able to
    verify a token can also mint one. That is acceptable while a single process does
    both. RS256 splits them: the private key signs, the public key verifies, so a
    compromised verifier (an edge proxy, a sidecar) cannot forge an `org` claim --
    which in this system is the tenant boundary. `_require_rs256_in_prod` enforces
    the switch rather than trusting a deploy checklist.
    """
    JWT_PRIVATE_KEY: str = ""
    """PEM-encoded RSA private key, used only when JWT_ALGORITHM is RS256."""
    JWT_PUBLIC_KEY: str = ""
    """PEM-encoded RSA public key, used only when JWT_ALGORITHM is RS256."""

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 15  # spec §4.1
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30  # spec §4.1

    # --- Session cookies ---------------------------------------------------
    # Spec §4.1: tokens ride in httpOnly cookies, never localStorage. A token in
    # localStorage is readable by any XSS payload on the page; an httpOnly cookie
    # is not, which converts "one XSS bug" from "full account takeover" into
    # "requests forged while the tab is open".
    COOKIE_DOMAIN: str = ""  # empty = host-only cookie
    COOKIE_SECURE: bool = False  # MUST be true anywhere with TLS
    COOKIE_SAMESITE: Literal["lax", "strict", "none"] = "lax"
    """`none` is required only when the marketing site and the app sit on different
    registrable domains -- and `none` without `secure` is rejected by every modern
    browser, which `_reject_samesite_none_without_secure` enforces at boot."""
    ACCESS_COOKIE_NAME: str = "educloud_access"
    REFRESH_COOKIE_NAME: str = "educloud_refresh"

    # --- Password policy (spec §4.4) ---------------------------------------
    PASSWORD_MIN_LENGTH: int = 10
    PASSWORD_MIN_ZXCVBN_SCORE: int = 3  # 0-4; 3 = "safely unguessable"

    # --- Account lockout (spec §4.4) ---------------------------------------
    LOGIN_MAX_FAILURES: int = 5
    LOGIN_LOCKOUT_MINUTES: int = 15
    """First lockout duration. Doubles on each subsequent lockout (exponential),
    capped by LOGIN_LOCKOUT_MAX_MINUTES."""
    LOGIN_LOCKOUT_MAX_MINUTES: int = 24 * 60

    # --- Redis (permission cache, rate limits) -----------------------------
    REDIS_ENABLED: bool = False
    REDIS_URL: str = "redis://localhost:6379/0"
    PERMISSION_CACHE_TTL_SECONDS: int = 300
    """Upper bound only. Correctness comes from the `pv` (permissions_version) in the
    cache key, not from expiry: editing a role bumps `pv`, so every existing token
    misses the old key immediately. The TTL merely evicts abandoned versions."""
    TRUSTED_PROXY_IPS: list[str] = Field(default_factory=list)
    AUTH_RATE_LIMIT: int = 5
    AUTH_RATE_WINDOW_SECONDS: int = 60
    PUBLIC_MUTATION_RATE_LIMIT: int = 10
    PUBLIC_MUTATION_RATE_WINDOW_SECONDS: int = 60

    # --- Invitations (spec §7) ---------------------------------------------
    INVITATION_EXPIRE_DAYS: int = 7
    INVITATION_MAX_RESENDS: int = 5

    # --- Payments (spec §6.4) ----------------------------------------------
    # `mock` is an in-process adapter that approves everything -- correct for
    # development and tests, catastrophic in production, which
    # `_reject_mock_gateway_in_prod` enforces.
    PAYMENT_GATEWAY: str = "mock"
    PAYMENT_GATEWAY_SECRET: str = ""
    """Webhook signing secret. Falls back to SECRET_KEY when empty, which is fine
    for the mock and wrong for a real provider -- each supplies its own."""

    # --- Platform super admin (spec §11) -----------------------------------
    SUPERADMIN_EMAIL: str = ""
    SUPERADMIN_PASSWORD: str = ""

    # --- Database ----------------------------------------------------------
    # DB_ENABLED lets us build and run the whole application skeleton *before*
    # PostgreSQL is wired up. When false, the engine is never created and the
    # `get_db` dependency raises a clear 503 instead of a confusing connection error.
    DB_ENABLED: bool = False
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DB: str = "school_manage_db"
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 5

    # --- Migration credentials ---------------------------------------------
    # Alembic needs DDL rights and must connect as the schema OWNER. The
    # application connects as POSTGRES_USER -- a restricted, NOBYPASSRLS role that
    # owns nothing (see scripts/init-db.sql). The split is not cosmetic: PostgreSQL
    # exempts superusers and table owners from RLS, so running the app as the owner
    # would silently disable every tenant-isolation policy in the system.
    #
    # Left empty, these fall back to POSTGRES_USER/POSTGRES_PASSWORD -- correct only
    # for a throwaway database where the app role happens to own the schema, and
    # wrong everywhere else. Set them whenever the two roles genuinely differ.
    MIGRATION_USER: str = ""
    MIGRATION_PASSWORD: str = ""

    # --- Email / SMTP ------------------------------------------------------
    # EMAIL_BACKEND selects the transport:
    #   "console" -- render to the log, send nothing. The default, and what tests
    #                and local development use. A test suite that can accidentally
    #                email real people is a liability.
    #   "smtp"    -- actually deliver via SMTP_*.
    EMAIL_BACKEND: Literal["console", "smtp"] = "console"
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    # STARTTLS (port 587) vs implicit TLS (port 465). Nodemailer calls the latter
    # `secure: true`; aiosmtplib calls it `use_tls`. Same distinction, and the two
    # are NOT interchangeable -- using the wrong one for the port hangs the
    # connection rather than failing fast.
    SMTP_USE_TLS: bool = False  # True only for port 465
    SMTP_START_TLS: bool = True  # True for port 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_TIMEOUT_SECONDS: int = 15

    # RFC 5322 From header. Needs a real mailbox, not just a display name --
    # `"School Manage"` alone is rejected by most receiving servers.
    EMAIL_FROM_ADDRESS: str = "noreply@example.com"
    EMAIL_FROM_NAME: str = "School Manage"

    # Base URL of the Next.js frontend, used to build links in emails.
    FRONTEND_URL: str = "http://localhost:3000"
    EMAIL_LOGO_URL: str = ""

    @property
    def email_from(self) -> str:
        """Formatted From header: `School Manage <noreply@example.com>`."""
        return f"{self.EMAIL_FROM_NAME} <{self.EMAIL_FROM_ADDRESS}>"

    @field_validator("EMAIL_BACKEND")
    @classmethod
    def _reject_console_backend_in_prod(cls, v: str, info) -> str:  # type: ignore[no-untyped-def]
        """Refuse to boot production with the console email backend.

        The console backend writes OTP codes to the application log in plaintext.
        In production that is both a credential leak into log aggregation and a
        total outage of signup, password reset and 2FA -- since no mail is ever
        actually delivered. Failing at boot is far kinder than discovering it from
        support tickets.
        """
        if v == "console" and info.data.get("ENVIRONMENT") is Environment.PRODUCTION:
            raise ValueError(
                "EMAIL_BACKEND=console logs OTP codes in plaintext and sends no "
                "mail; it cannot be used in production. Set EMAIL_BACKEND=smtp."
            )
        return v

    @field_validator("SECRET_KEY")
    @classmethod
    def _reject_default_secret_in_prod(cls, v: str, info) -> str:  # type: ignore[no-untyped-def]
        """Refuse to boot production with the placeholder signing key.

        A weak SECRET_KEY means anyone can forge a JWT and therefore forge the
        `school_id` claim -- which in this system is the tenant boundary. This
        check is cheap insurance against a catastrophic misconfiguration.
        """
        env = info.data.get("ENVIRONMENT")
        if env in (Environment.PRODUCTION, Environment.STAGING) and "change" in v.lower():
            raise ValueError("SECRET_KEY must be set to a real secret outside local/test")
        return v

    @field_validator("COOKIE_SAMESITE")
    @classmethod
    def _reject_samesite_none_without_secure(cls, v: str, info) -> str:  # type: ignore[no-untyped-def]
        """`SameSite=None` without `Secure` is silently dropped by every browser.

        The failure mode is invisible and total: the cookie is never stored, so every
        request after login is unauthenticated and the app appears to "randomly log
        people out". Catching it at boot is far cheaper than debugging it from the
        browser console.
        """
        if v == "none" and not info.data.get("COOKIE_SECURE", False):
            raise ValueError("COOKIE_SAMESITE=none requires COOKIE_SECURE=true")
        return v

    @field_validator("JWT_PUBLIC_KEY")
    @classmethod
    def _require_rs256_keys(cls, v: str, info) -> str:  # type: ignore[no-untyped-def]
        """RS256 is unusable without both halves of the key pair.

        Validated on JWT_PUBLIC_KEY because field validators run in declaration
        order, so by this point JWT_ALGORITHM and JWT_PRIVATE_KEY are both in
        `info.data`.
        """
        if info.data.get("JWT_ALGORITHM") == "RS256" and not (
            v and info.data.get("JWT_PRIVATE_KEY")
        ):
            raise ValueError("JWT_ALGORITHM=RS256 requires both JWT_PRIVATE_KEY and JWT_PUBLIC_KEY")
        return v

    @field_validator("PAYMENT_GATEWAY")
    @classmethod
    def _reject_mock_gateway_in_prod(cls, v: str, info) -> str:  # type: ignore[no-untyped-def]
        """Refuse to boot production on the mock payment gateway.

        The mock approves every charge and signs its own webhooks with our own
        secret. In production that means subscriptions activate without anyone
        paying, and the revenue loss is silent -- nothing errors, invoices simply
        mark themselves paid.
        """
        if v == "mock" and info.data.get("ENVIRONMENT") is Environment.PRODUCTION:
            raise ValueError(
                "PAYMENT_GATEWAY=mock approves every charge and cannot be used in "
                "production. Configure a real gateway."
            )
        return v

    @field_validator("SUPERADMIN_PASSWORD")
    @classmethod
    def _require_strong_superadmin_password_in_prod(cls, v: str, info) -> str:  # type: ignore[no-untyped-def]
        """Spec §11.3: refuse production if the super-admin password is weak.

        This account can read every tenant's data and impersonate any organization.
        A short or placeholder password on it is not a configuration smell, it is a
        platform-wide breach waiting for someone to try `admin/admin`.
        """
        env = info.data.get("ENVIRONMENT")
        if env is Environment.PRODUCTION and v and len(v) < 16:
            raise ValueError("SUPERADMIN_PASSWORD must be at least 16 characters in production")
        return v

    @property
    def jwt_signing_key(self) -> str:
        """The key used to SIGN tokens. Private key under RS256, shared secret under HS256."""
        return self.JWT_PRIVATE_KEY if self.JWT_ALGORITHM == "RS256" else self.SECRET_KEY

    @property
    def jwt_verification_key(self) -> str:
        """The key used to VERIFY tokens. Public key under RS256, shared secret under HS256."""
        return self.JWT_PUBLIC_KEY if self.JWT_ALGORITHM == "RS256" else self.SECRET_KEY

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:
        """Async SQLAlchemy DSN (asyncpg driver) used by the application at runtime."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def MIGRATION_DATABASE_URL(self) -> str:
        """Async DSN used by Alembic only -- connects as the schema owner.

        Falls back to the application credentials when MIGRATION_USER is unset, so
        a disposable local database still works with no extra configuration. Note
        the password is taken from MIGRATION_PASSWORD verbatim once MIGRATION_USER
        is set: an owner authenticating by local trust/peer has no password, and
        silently substituting the app role's password would break that.
        """
        if self.MIGRATION_USER:
            username, password = self.MIGRATION_USER, self.MIGRATION_PASSWORD
        else:
            username, password = self.POSTGRES_USER, self.POSTGRES_PASSWORD
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=username,
                password=password or None,
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def SYNC_DATABASE_URL(self) -> str:
        """Sync DSN (psycopg) for tooling that cannot speak async.

        Alembic *can* run async, and ours does -- but having this available keeps
        the door open for sync-only tooling (e.g. schema diff utilities).
        """
        return str(
            PostgresDsn.build(
                scheme="postgresql+psycopg",
                username=self.POSTGRES_USER,
                password=self.POSTGRES_PASSWORD,
                host=self.POSTGRES_HOST,
                port=self.POSTGRES_PORT,
                path=self.POSTGRES_DB,
            )
        )

    @property
    def is_production(self) -> bool:
        return self.ENVIRONMENT is Environment.PRODUCTION

    @property
    def docs_url(self) -> str | None:
        """Swagger UI is disabled in production -- it leaks the full API surface."""
        return None if self.is_production else "/docs"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Cached because parsing + validating env vars on every request would be wasteful.
    Exposed as a *function* (not a module-level constant) so tests can clear the
    cache or override it via FastAPI's `dependency_overrides`.
    """
    return Settings()
