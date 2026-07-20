"""Fixtures for database-backed integration tests.

WHY THESE EXIST (and are separate from the parent conftest)
    The skeleton's smoke tests run with DB_ENABLED=false. The tenancy/auth tests need
    a real PostgreSQL, and -- crucially -- the application under test must connect as
    the restricted `sms_app` role (NOBYPASSRLS), so Row-Level Security is genuinely
    exercised rather than silently bypassed by a superuser connection.

HOW IT WORKS
    * The schema is assumed already migrated (`make migrate`) on the target database.
    * A separate ADMIN engine (superuser) truncates tables between tests and seeds
      fixtures -- superusers bypass RLS, which is exactly what setup/teardown wants.
    * The APP engine connects as `sms_app`; every request the tests make is therefore
      subject to the same RLS the production app is.
    * A capturing email dispatcher records the messages the service would have sent,
      so a test can read the OTP code it needs to complete a flow.

    Each async engine is created and disposed within a single test's event loop
    (function scope), which sidesteps the "future attached to a different loop"
    problem asyncpg hits when an engine is shared across pytest-asyncio's per-function
    loops.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.common.email.sender import EmailMessage
from app.core.config import Environment, Settings, get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import dispose_engine, init_engine
from app.main import create_app
from app.modules.auth.models import User, UserRole, UserStatus
from app.modules.auth.router import get_email_dispatcher
from app.modules.tenancy.models import School, SchoolStatus, SubscriptionPlan

# Test infrastructure credentials. The app connects as the restricted role; the admin
# engine (superuser) is used only for setup/teardown and cross-tenant assertions.
_ADMIN_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/school_manage_db"
_APP_TABLES = ("refresh_tokens", "otp_codes", "users", "schools")

TEST_SECRET = "integration-test-secret-key-not-for-production-use"
DEFAULT_PASSWORD = "Password123!"

_SIX_DIGITS = re.compile(r"\b(\d{6})\b")


@pytest.fixture(scope="session")
def db_settings() -> Settings:
    """Settings for the app under test: connects as `sms_app`, DB enabled."""
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        ENVIRONMENT=Environment.TEST,
        DEBUG=True,
        DB_ENABLED=True,
        SECRET_KEY=TEST_SECRET,
        POSTGRES_HOST="localhost",
        POSTGRES_PORT=5432,
        POSTGRES_USER="sms_app",
        POSTGRES_PASSWORD="sms_app_password",
        POSTGRES_DB="school_manage_db",
        CORS_ORIGINS=["http://localhost:3000"],
        LOG_LEVEL="WARNING",
    )


class _CaptureDispatcher:
    """Records messages instead of sending them, so tests can read OTP codes."""

    def __init__(self, mailbox: list[EmailMessage]) -> None:
        self._mailbox = mailbox

    def dispatch(self, message: EmailMessage) -> None:
        self._mailbox.append(message)


@pytest.fixture
def mailbox() -> list[EmailMessage]:
    """Captured outbound emails for the current test."""
    return []


def latest_otp(mailbox: list[EmailMessage]) -> str:
    """Extract the 6-digit code from the most recently 'sent' email."""
    assert mailbox, "no email was dispatched"
    match = _SIX_DIGITS.search(mailbox[-1].subject) or _SIX_DIGITS.search(mailbox[-1].text_body)
    assert match, f"no OTP code found in email: {mailbox[-1].subject!r}"
    return match.group(1)


@pytest.fixture
async def admin_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A sessionmaker on a superuser engine (bypasses RLS) for setup/inspection."""
    engine = create_async_engine(_ADMIN_URL, poolclass=NullPool)
    # Clean slate before the test.
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(_APP_TABLES)} RESTART IDENTITY CASCADE"))
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def db_client(
    db_settings: Settings,
    mailbox: list[EmailMessage],
    admin_sessionmaker: async_sessionmaker[AsyncSession],  # ensures the DB is cleaned first
) -> AsyncIterator[AsyncClient]:
    """HTTP client wired to the app, connecting to PostgreSQL as `sms_app`."""
    await dispose_engine()
    init_engine(db_settings)

    app = create_app(db_settings)
    app.dependency_overrides[get_settings] = lambda: db_settings
    app.dependency_overrides[get_email_dispatcher] = lambda: _CaptureDispatcher(mailbox)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac

    await dispose_engine()


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SeededUser:
    user_id: str
    school_id: str | None
    email: str
    password: str
    role: UserRole


@pytest.fixture
def seed_school(
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> Callable[..., object]:
    """Return a coroutine factory that inserts a school (superuser, RLS bypassed)."""

    async def _make(
        *, name: str = "Test School", status: SchoolStatus = SchoolStatus.ACTIVE
    ) -> School:
        async with admin_sessionmaker() as session:
            school = School(
                name=name,
                slug=name.lower().replace(" ", "-") + "-" + _rand(),
                email="school@example.com",
                status=status,
                plan=SubscriptionPlan.TRIAL,
                max_students=100,
            )
            session.add(school)
            await session.commit()
            await session.refresh(school)
            return school

    return _make


@pytest.fixture
def seed_user(
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> Callable[..., object]:
    """Return a coroutine factory that inserts an active, verified user."""

    async def _make(
        *,
        school_id: str | None,
        email: str,
        role: UserRole = UserRole.TEACHER,
        password: str = DEFAULT_PASSWORD,
        two_factor: bool = False,
    ) -> SeededUser:
        from datetime import UTC, datetime

        async with admin_sessionmaker() as session:
            user = User(
                school_id=school_id,
                email=email.lower(),
                hashed_password=hash_password(password),
                full_name="Seeded User",
                role=role,
                status=UserStatus.ACTIVE,
                email_verified_at=datetime.now(UTC),
                two_factor_enabled=two_factor,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
            return SeededUser(
                user_id=str(user.id),
                school_id=str(user.school_id) if user.school_id else None,
                email=user.email,
                password=password,
                role=role,
            )

    return _make


def auth_header(
    *,
    user_id: str,
    school_id: str | None = None,
    role: str | None = None,
    super_admin: bool = False,
) -> dict[str, str]:
    """Mint a bearer header directly (no login round-trip) for a given principal."""
    from uuid import UUID

    token = create_access_token(
        UUID(user_id),
        school_id=UUID(school_id) if school_id else None,
        role=role,
        is_super_admin=super_admin,
        settings=Settings(_env_file=None, ENVIRONMENT=Environment.TEST, SECRET_KEY=TEST_SECRET),  # type: ignore[call-arg]
    )
    return {"Authorization": f"Bearer {token}"}


def _rand() -> str:
    import secrets

    return secrets.token_hex(3)
