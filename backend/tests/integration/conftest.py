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

import os
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
from app.core.rate_limit import reset_memory_rate_limits
from app.db.session import dispose_engine, init_engine
from app.main import create_app
from app.modules.auth.router import get_email_dispatcher

# Test infrastructure credentials. The app connects as the restricted role; the admin
# engine (superuser) is used only for setup/teardown and cross-tenant assertions.
#
# =============================================================================
# THIS SUITE TRUNCATES EVERY TENANT TABLE IN THE DATABASE IT POINTS AT
# =============================================================================
#     So it points at its OWN database, not the one `make dev` serves. It used to
#     name `school_manage_db` -- the development database -- which meant a single
#     `make test` silently destroyed whatever the developer was working with, with
#     no warning and no way back.
#
#     `TEST_POSTGRES_DB` overrides it. Create the database once:
#
#         createdb -U postgres school_manage_test_db
#         psql -U postgres -d school_manage_test_db -f scripts/init-db.sql
#         TEST_POSTGRES_DB=school_manage_test_db uv run alembic upgrade head
#         TEST_POSTGRES_DB=school_manage_test_db uv run python -m app.cli seed
#
#     Pointing it back at a database with real data in it is a decision that now has
#     to be made deliberately, which is the whole point.
_TEST_DB_HOST = os.getenv("TEST_POSTGRES_HOST", "localhost")
_TEST_DB_PORT = int(os.getenv("TEST_POSTGRES_PORT", "5432"))
_TEST_DB_NAME = os.getenv("TEST_POSTGRES_DB", "school_manage_test_db")
_ADMIN_URL = (
    f"postgresql+asyncpg://postgres:postgres@{_TEST_DB_HOST}:{_TEST_DB_PORT}/{_TEST_DB_NAME}"
)

# Truncated between tests, children first for readability. `plans` and `permissions`
# are DELIBERATELY ABSENT: they are seeded reference data, not test fixtures, and
# wiping them would break every test that creates an organization (which needs the
# free plan to exist).
_APP_TABLES = (
    # Attendance first of all: `attendance_records.student_id` and
    # `attendance_sessions.section_id` are ON DELETE RESTRICT, so these must be
    # emptied before `students` and `sections` even though TRUNCATE ... CASCADE
    # would otherwise sort it out. Listing them explicitly keeps the dependency
    # order readable rather than relying on CASCADE to discover it.
    "attendance_records",
    "attendance_sessions",
    # Before `students`, `classes` and `academic_years` -- RESTRICT on the last two.
    "student_enrollments",
    # Before `subjects` (RESTRICT) and `classes` (CASCADE).
    "class_subjects",
    # WhatsApp: groups reference classes/sections, the outbox references groups.
    "whatsapp_messages",
    "whatsapp_groups",
    "whatsapp_settings",
    # Fees: `fee_vouchers.student_id` is ON DELETE RESTRICT, so these must go
    # before `students` even though TRUNCATE ... CASCADE would otherwise sort it out.
    #
    # THE LEDGER GOES FIRST OF ALL THE FEE TABLES. `student_ledger_entries` holds
    # ON DELETE RESTRICT foreign keys to students, vouchers AND payments -- it is
    # deliberately the most reference-heavy table in the module, because every row is
    # a financial record that must outlive any deletion path. Leaving it out of this
    # list does not merely leave stale rows behind: it makes the whole TRUNCATE fail,
    # and the next test then runs against a database nobody emptied. That failure
    # surfaces three tests later as an unrelated 401, which is a long way to walk back
    # from a missing line here.
    "student_ledger_entries",
    "fee_payments",
    "fee_voucher_items",
    "fee_vouchers",
    "fee_structure_items",
    "fee_structures",
    # Before `fee_heads` and `students`: references both ON DELETE RESTRICT/CASCADE.
    # `student_fee_assignments` also references `fee_concessions` ON DELETE RESTRICT,
    # so the scheme table follows it rather than preceding it.
    "student_fee_assignments",
    "fee_concessions",
    # Before `fee_heads`, which it references ON DELETE RESTRICT.
    "fee_late_fee_policies",
    "fee_heads",
    # After the line tables above: both reference it ON DELETE RESTRICT.
    "stationery_items",
    # Guardians: the link table references `students` and `guardians`, so it goes
    # before both. `guardians.identity_id` is ON DELETE RESTRICT, which is why
    # `guardian_identities` sits further down beside the other identity tables rather
    # than next to its children -- the same placement `users` gets, and for the same
    # reason.
    "guardian_students",
    "guardians",
    "students",
    "sections",
    "classes",
    # After `class_subjects` and `student_enrollments`, which reference them.
    "subjects",
    "terms",
    "academic_years",
    "audit_logs",
    "invitations",
    "memberships",
    "role_permissions",
    "roles",
    "billing_idempotency_keys",
    "payments",
    "invoices",
    "subscription_events",
    "subscriptions",
    "organization_usage",
    "webhook_events",
    "schools",
    "platform_audit_logs",
    # Before `guardian_identities` and `users`, both of which it references.
    "sessions",
    "password_reset_tokens",
    "email_verification_tokens",
    "guardian_otp_codes",
    # The guardian identity surface, alongside `users`: global, outside RLS, and
    # referenced by `sessions` and `guardians`, so it is emptied after both.
    "guardian_identities",
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
        POSTGRES_HOST=_TEST_DB_HOST,
        POSTGRES_PORT=_TEST_DB_PORT,
        POSTGRES_USER="sms_app",
        POSTGRES_PASSWORD="sms_app_password",
        POSTGRES_DB=_TEST_DB_NAME,
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


# The four plans the seeder creates. Everything else in `plans` was made by a test
# and must not survive it — otherwise a test that creates `custom_deal` makes the
# NEXT run of the same test fail with PLAN_CODE_TAKEN, and the suite stops being
# repeatable. Truncating the whole table instead would break every test that needs
# the free plan to exist.
_SEEDED_PLAN_CODES = ("free", "starter", "growth", "enterprise")


@pytest.fixture
async def admin_sessionmaker() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A sessionmaker on a superuser engine (bypasses RLS) for setup/inspection."""
    engine = create_async_engine(_ADMIN_URL, poolclass=NullPool)
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {', '.join(_APP_TABLES)} RESTART IDENTITY CASCADE"))
        # After the truncate, so no subscription can still reference them.
        await conn.execute(
            text("DELETE FROM plans WHERE code <> ALL(:keep)"),
            {"keep": list(_SEEDED_PLAN_CODES)},
        )
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def db_client(
    db_settings: Settings,
    mailbox: list[EmailMessage],
    admin_sessionmaker: async_sessionmaker[AsyncSession],  # ensures the DB is cleaned first
) -> AsyncIterator[AsyncClient]:
    """HTTP client wired to the app, connecting to PostgreSQL as `sms_app`."""
    await reset_memory_rate_limits()
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
    the application itself could never produce (an organization with no principal
    role, a school with no roles). Hand-built fixtures drift from reality; these
    cannot.
    """

    organization_id: str
    owner_user_id: str
    owner_email: str
    password: str
    school_id: str
    access_token: str
    refresh_token: str
    client: AsyncClient

    active_school_id: str | None = None
    """Which campus this org-level principal is looking at.

    The principal's token carries no school -- their one membership is org-level --
    so the school-scoped repositories would otherwise return every campus at once,
    and `require_school_id()` routes (create a student, create a class) would have no
    school to stamp. Setting this sends `X-Active-School`, which is exactly what the
    frontend does from its cookie. Authority is unchanged; only the view narrows.
    """

    def headers(self, token: str | None = None) -> dict[str, str]:
        headers = {"Authorization": f"Bearer {token or self.access_token}"}
        # Only alongside the tenant's OWN token. Attaching it to a borrowed token
        # would silently re-point somebody else's request at this tenant's campus.
        if token is None and self.active_school_id:
            headers["X-Active-School"] = self.active_school_id
        return headers

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


async def make_campus_head(
    tenant: Tenant,
    mailbox: list[EmailMessage],
    email: str,
    *,
    school_id: str | None = None,
    code: str = "campus_head",
    full_name: str = "Campus Head",
) -> str:
    """A SCHOOL-SCOPED actor holding every school permission. Returns their token.

    Stands in for the seeded school `principal` role, which no longer exists -- there
    is one `principal` now and it is org-level. The invariants that role used to
    exercise still need a subject: a school-scoped actor must not reach billing,
    another campus, or the definition of its own authority. A custom role is how a
    customer builds one, so building it through the public API is also a test that
    the role editor can express what the seeded role used to.

    `SCHOOL_SCOPED_CODES` is read from the catalog rather than listed here, so a new
    school permission joins this actor automatically instead of silently leaving a
    gap in the tests that use it.
    """
    from app.modules.rbac.catalog import SCHOOL_SCOPED_CODES

    target_school_id = school_id or tenant.school_id

    role = await tenant.post(
        f"{API}/schools/{target_school_id}/roles",
        json={
            "code": code,
            "name": full_name,
            "permissions": sorted(SCHOOL_SCOPED_CODES),
        },
    )
    assert role.status_code == 201, role.text

    invited = await tenant.post(
        f"{API}/schools/{target_school_id}/invitations",
        json={"email": email, "full_name": full_name, "role_id": role.json()["id"]},
    )
    assert invited.status_code == 201, invited.text

    # Accept as an ANONYMOUS caller. The accept endpoint checks any session it finds
    # against the invited address, so a lingering cookie from another account would
    # (correctly) be refused with INVITATION_EMAIL_MISMATCH.
    tenant.client.cookies.clear()
    accepted = await tenant.client.post(
        f"{API}/invitations/accept",
        json={
            "token": latest_token(mailbox),
            "full_name": full_name,
            "password": STRONG_PASSWORD,
        },
    )
    assert accepted.status_code == 200, accepted.text
    tenant.client.cookies.clear()

    login = await tenant.client.post(
        f"{API}/auth/login",
        json={"email": email, "password": STRONG_PASSWORD},
        headers={"X-Token-Transport": "body"},
    )
    assert login.status_code == 200, login.text
    tenant.client.cookies.clear()
    return str(login.headers["X-Access-Token"])


@pytest.fixture
def make_tenant(db_client: AsyncClient, mailbox: list[EmailMessage]) -> Callable[..., Any]:
    """Factory: register an organization, verify it, and create its first school.

    Returns a `Tenant` holding the principal's tokens. That token is ORG-LEVEL
    (`school_id` is null) and stays that way -- creating a school no longer mints a
    second, school-scoped membership -- which is what lets a test exercise the
    cross-school reads only the principal should have.
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
            school_id = created.json()["id"]

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
