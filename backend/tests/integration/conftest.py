"""Fixtures for database-backed integration tests.

WHY THESE EXIST (and are separate from the parent conftest)
    The skeleton's smoke tests run with DB_ENABLED=false. These need a real
    PostgreSQL, and -- crucially -- the application under test must connect as the
    restricted `sms_app` role (NOBYPASSRLS), so Row-Level Security is genuinely
    exercised rather than silently bypassed by a superuser connection.

    A test suite that runs as `postgres` proves nothing about isolation: every
    policy is inert for a superuser, so the isolation tests would pass on a schema
    with no policies at all.

HOW IT WORKS
    * The schema is assumed already migrated (`make migrate`).
    * A separate ADMIN engine (superuser) truncates and inspects between tests --
      superusers bypass RLS, which is exactly what setup/teardown wants.
    * The APP engine connects as `sms_app`; every request the tests make is subject
      to the same policies production is.
    * A capturing email dispatcher records what would have been sent, so tests can
      read the verification and invitation links out of it.

    Each async engine is created and disposed within a single test's event loop
    (function scope), which sidesteps the "future attached to a different loop"
    problem asyncpg hits when an engine is shared across pytest-asyncio's
    per-function loops.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.common.email.sender import EmailMessage
from app.core.config import Environment, Settings, get_settings
from app.db.session import dispose_engine, init_engine
from app.main import create_app
from app.modules.auth.router import get_email_dispatcher

# Test infrastructure credentials. The app connects as the restricted role; the admin
# engine (superuser) is used only for setup/teardown and cross-tenant assertions.
_ADMIN_URL = "postgresql+asyncpg://postgres:postgres@localhost:5432/school_manage_db"

# Truncated between tests, children first for readability. `plans` and `permissions`
# are DELIBERATELY ABSENT: they are seeded reference data, not test fixtures, and
# wiping them would break every test that creates an organization (which needs the
# free plan to exist).
_APP_TABLES = (
    "students",
    "sections",
    "classes",
    "audit_logs",
    "invitations",
    "memberships",
    "role_permissions",
    "roles",
    "payments",
    "invoices",
    "subscription_events",
    "subscriptions",
    "organization_usage",
    "webhook_events",
    "schools",
    "platform_audit_logs",
    "sessions",
    "password_reset_tokens",
    "email_verification_tokens",
    "organizations",
    "users",
    "platform_admins",
)

TEST_SECRET = "integration-test-secret-key-not-for-production-use"
STRONG_PASSWORD = "correct-horse-battery-staple-72"
"""Passes the real policy: >= 10 chars, zxcvbn >= 3, not in the breached list.

Deliberately NOT `Password123!`, which the policy rejects -- using a password the
production policy would refuse would mean the tests exercise a code path real users
never reach.
"""

_TOKEN_RE = re.compile(r"[?&]token=([A-Za-z0-9_\-]+)")


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
        # Off, so the permission cache falls through to Postgres. Tests then assert
        # on the AUTHORITATIVE state rather than on whatever Redis happened to hold,
        # and a stale key from a previous test can never leak into the next one.
        REDIS_ENABLED=False,
        PAYMENT_GATEWAY="mock",
        PAYMENT_GATEWAY_SECRET="test-webhook-secret",
    )


class _CaptureDispatcher:
    """Records messages instead of sending them, so tests can read the links."""

    def __init__(self, mailbox: list[EmailMessage]) -> None:
        self._mailbox = mailbox

    async def send(self, message: EmailMessage) -> None:
        self._mailbox.append(message)


@pytest.fixture
def mailbox() -> list[EmailMessage]:
    """Captured outbound emails for the current test."""
    return []


def latest_token(mailbox: list[EmailMessage]) -> str:
    """Pull the raw token out of the most recent email's action link.

    This is the ONLY way a test can obtain a raw token, and that is the point: the
    database stores only the SHA-256 digest, so a test that could read the token from
    a row would be testing a system that leaks credentials.
    """
    assert mailbox, "no email was dispatched"
    body = mailbox[-1].text_body + mailbox[-1].html_body
    match = _TOKEN_RE.search(body)
    assert match, f"no token found in email: {mailbox[-1].subject!r}"
    return match.group(1)


@pytest.fixture
async def admin_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A sessionmaker on a superuser engine (bypasses RLS) for setup/inspection."""
    engine = create_async_engine(_ADMIN_URL, poolclass=NullPool)
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
# High-level fixtures: build organizations through the real API
# ---------------------------------------------------------------------------


@dataclass
class Tenant:
    """A fully provisioned organization, as a test would use it.

    Built by driving the PUBLIC API -- register, verify, create school -- rather than
    by inserting rows. That means every test implicitly re-verifies that signup and
    provisioning work, and it makes it impossible for a fixture to construct a state
    the application itself could never produce (an organization with no owner role, a
    school with no principal). Hand-built fixtures drift from reality; these cannot.
    """

    organization_id: str
    owner_user_id: str
    owner_email: str
    password: str
    school_id: str
    access_token: str
    refresh_token: str
    client: AsyncClient

    def headers(self, token: str | None = None) -> dict[str, str]:
        return {"Authorization": f"Bearer {token or self.access_token}"}

    async def get(self, url: str, **kw: Any) -> Any:
        return await self.client.get(url, headers=self.headers(), **kw)

    async def post(self, url: str, **kw: Any) -> Any:
        return await self.client.post(url, headers=self.headers(), **kw)

    async def patch(self, url: str, **kw: Any) -> Any:
        return await self.client.patch(url, headers=self.headers(), **kw)

    async def put(self, url: str, **kw: Any) -> Any:
        return await self.client.put(url, headers=self.headers(), **kw)

    async def delete(self, url: str, **kw: Any) -> Any:
        return await self.client.delete(url, headers=self.headers(), **kw)


API = "/api/v1"


@pytest.fixture
def make_tenant(db_client: AsyncClient, mailbox: list[EmailMessage]) -> Callable[..., Any]:
    """Factory: register an organization, verify it, and create its first school.

    Returns a `Tenant` holding the owner's tokens. The owner's token is ORG-LEVEL
    (`school_id` is null), which is what lets a test exercise the cross-school reads
    only an owner should have.
    """

    async def _make(
        *,
        name: str = "Test Trust",
        email: str = "owner@test.example",
        school_code: str = "MAIN",
        create_school: bool = True,
        plan: str | None = "growth",
    ) -> Tenant:
        """
        `plan` defaults to `growth` because the FREE plan allows 1 school, 3 staff
        and 0 custom roles -- so an authorization test that needs a second campus or
        a custom role would fail with 402 before reaching the thing it is testing.

        Pass `plan=None` to stay on free. The billing tests do exactly that: for them
        the limit IS the subject, not an obstacle.
        """
        register = await db_client.post(
            f"{API}/auth/register",
            json={
                "full_name": "Test Owner",
                "email": email,
                "password": STRONG_PASSWORD,
                "organization_name": name,
                "country": "PK",
            },
        )
        assert register.status_code == 201, register.text
        registered = register.json()

        verify = await db_client.post(
            f"{API}/auth/verify-email", json={"token": latest_token(mailbox)}
        )
        assert verify.status_code == 200, verify.text

        login = await db_client.post(
            f"{API}/auth/login",
            json={"email": email, "password": STRONG_PASSWORD},
            headers={"X-Token-Transport": "body"},
        )
        assert login.status_code == 200, login.text
        access = login.headers["X-Access-Token"]
        refresh = login.headers["X-Refresh-Token"]

        # Login set httpOnly cookies on the shared client. Clear them so a later
        # unauthenticated call -- accepting an invitation as a NEW person, verifying
        # a token -- is genuinely unauthenticated. Leaving them would make the
        # invitation flow see the owner's session and correctly refuse with
        # INVITATION_EMAIL_MISMATCH, which is the guard working but not what a test
        # of some other behaviour is trying to exercise.
        db_client.cookies.clear()

        if plan is not None:
            upgraded = await db_client.post(
                f"{API}/billing/change-plan",
                json={"plan_code": plan, "billing_cycle": "monthly"},
                headers={"Authorization": f"Bearer {access}"},
            )
            assert upgraded.status_code == 200, upgraded.text

        school_id = ""
        if create_school:
            created = await db_client.post(
                f"{API}/schools",
                json={"name": f"{name} Main", "code": school_code},
                headers={"Authorization": f"Bearer {access}"},
            )
            assert created.status_code == 201, created.text
            school_id = created.json()["school"]["id"]

        return Tenant(
            organization_id=registered["organization_id"],
            owner_user_id=registered["user_id"],
            owner_email=email,
            password=STRONG_PASSWORD,
            school_id=school_id,
            access_token=access,
            refresh_token=refresh,
            client=db_client,
        )

    return _make


@pytest.fixture
async def tenant(make_tenant: Callable[..., Any]) -> Tenant:
    """The common case: one organization with one school, owner signed in."""
    return await make_tenant()
