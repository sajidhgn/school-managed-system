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
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

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
