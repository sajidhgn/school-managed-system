"""Shared pytest fixtures.

WHY THIS FILE EXISTS
    Test setup that more than one test file needs belongs in exactly one place.
    conftest.py is auto-discovered by pytest, so fixtures defined here are available
    everywhere without imports.

RESPONSIBILITY
    Build an app configured for testing, and provide an HTTP client that talks to it
    in-process.

INTERACTIONS
    Overrides `get_settings` via `dependency_overrides` so tests never read the
    developer's real `.env`.

DEVIATIONS FROM THE SKILL PLAYBOOK
    1. `AsyncClient(app=app)` -- removed in httpx 0.28. The current form is
       `AsyncClient(transport=ASGITransport(app=app))`.
    2. The custom `event_loop` fixture -- deprecated and removed in pytest-asyncio 1.x.
       Loop scope is configured declaratively in pyproject.toml instead.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.config import Environment, Settings, get_settings
from app.main import create_app


@pytest.fixture(scope="session")
def settings() -> Settings:
    """Test settings, constructed explicitly rather than read from .env.

    `_env_file=None` stops pydantic-settings from loading the developer's local
    .env, which would make test outcomes depend on an untracked file.
    """
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        ENVIRONMENT=Environment.TEST,
        DEBUG=True,
        DB_ENABLED=False,
        SECRET_KEY="test-secret-key-not-used-in-any-real-environment",
        CORS_ORIGINS=["http://localhost:3000"],
        LOG_LEVEL="WARNING",  # keep test output readable
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    """A fresh application per test.

    Per-test (not per-session) so that a test which registers a dependency override
    cannot affect any other test.
    """
    application = create_app(settings)
    application.dependency_overrides[get_settings] = lambda: settings
    return application


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """HTTP client wired directly to the ASGI app -- no network, no port binding.

    Using `ASGITransport` rather than a live server keeps tests fast and
    deterministic, and exercises the real middleware and exception-handler stack.

    `async with LifespanManager`-style startup is not needed here because the
    fixture triggers lifespan via httpx's ASGI transport only if requested; the
    health route under test does not depend on startup state.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
