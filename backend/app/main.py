"""Application entry point and composition root.

WHY THIS FILE EXISTS
    Every application needs one place where all the independent pieces -- settings,
    logging, middleware, routers, error handlers, database -- are wired together.
    This is the Composition Root pattern: dependencies are assembled here and
    nowhere else, so no module has to reach out and construct its own collaborators.

RESPONSIBILITY
    Build and configure the `FastAPI` instance. It contains no business logic and
    no route handlers -- if you find yourself adding an endpoint here, it belongs
    in a module router instead.

INTERACTIONS
    Imports from every layer, and is imported by nobody except the ASGI server
    (`uvicorn app.main:app`) and the test suite.

WHY A FACTORY FUNCTION (`create_app`) RATHER THAN A MODULE-LEVEL `app`
    A factory lets tests build a fresh, independently-configured app per test
    session (different settings, overridden dependencies) without import-time side
    effects leaking between tests. The module-level `app` at the bottom exists only
    because ASGI servers need an importable attribute.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.errors import register_exception_handlers
from app.api.v1.router import api_router
from app.api.v1.routes.health import router as health_router
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine, init_engine
from app.middleware.request_context import RequestContextMiddleware

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup and shutdown hooks.

    WHY LIFESPAN AND NOT @app.on_event: the on_event decorators are deprecated. More
    importantly, lifespan is a single context manager, so setup and its matching
    teardown sit adjacent in the code -- you cannot add a resource and forget to
    release it.

    Connection pools are created here, not at import time, so that importing
    `app.main` (as the test suite and Alembic do) never opens a socket.
    """
    settings: Settings = app.state.settings

    configure_logging(settings)
    logger.info(
        "application_starting",
        app=settings.APP_NAME,
        environment=settings.ENVIRONMENT.value,
        db_enabled=settings.DB_ENABLED,
    )

    if settings.DB_ENABLED:
        init_engine(settings)
    else:
        # Explicit and loud: this is a legitimate development state, but nobody
        # should ever wonder why writes are failing.
        logger.warning(
            "database_disabled",
            hint="Set DB_ENABLED=true once PostgreSQL is provisioned.",
        )

    yield  # ---- application serves requests here ----

    logger.info("application_shutting_down")
    if settings.DB_ENABLED:
        await dispose_engine()


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build a configured FastAPI application."""
    settings = settings or get_settings()

    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        summary="Multi-tenant school management platform",
        description=(
            "Backend API for the School Management System.\n\n"
            "**Tenant isolation** is enforced by PostgreSQL Row-Level Security: the "
            "`school_id` claim in your JWT scopes every query. Cross-tenant reads "
            "return 404, never 403, so resource existence is never disclosed."
        ),
        lifespan=lifespan,
        docs_url=settings.docs_url,
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        # Errors are RFC 9457 Problem Details; declare it once so every operation
        # in the generated OpenAPI spec documents the shape.
        responses={
            400: {"description": "Bad Request"},
            401: {"description": "Unauthenticated"},
            403: {"description": "Forbidden"},
            422: {"description": "Validation Error"},
        },
    )

    # Stash settings on app.state so lifespan and tests can reach the *same*
    # instance that was injected, rather than calling get_settings() again.
    app.state.settings = settings

    _register_middleware(app, settings)
    register_exception_handlers(app)
    _register_routers(app, settings)

    return app


def _register_middleware(app: FastAPI, settings: Settings) -> None:
    """Install middleware.

    ORDER IS SIGNIFICANT AND COUNTER-INTUITIVE: Starlette applies middleware in
    reverse registration order, so the LAST one added is the OUTERMOST wrapper --
    it sees the request first and the response last.

    Desired outer-to-inner chain:
        TrustedHost -> CORS -> GZip -> RequestContext -> router

    RequestContext must be innermost of these so that its timing measurement covers
    route execution rather than compression, and so its log line is emitted with the
    final status code.
    """
    app.add_middleware(RequestContextMiddleware)

    # Compress responses over 1 KB. Class lists and fee reports are large, repetitive
    # JSON -- typically 70-80% smaller gzipped, which matters on mobile networks
    # where teachers will be marking attendance.
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    if settings.CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
            # Without this the browser hides X-Request-ID from frontend JS, so the
            # UI cannot show a correlation id on its error screens.
            expose_headers=["X-Request-ID", "Server-Timing"],
            max_age=600,
        )

    if settings.is_production:
        # Blocks Host-header injection, which otherwise enables cache poisoning and
        # password-reset link hijacking. Replace with real hostnames at deploy time.
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*.example.com"])


def _register_routers(app: FastAPI, settings: Settings) -> None:
    """Mount routers.

    Health checks live at the root (unversioned) because orchestrator probe URLs
    must remain stable across API versions. Everything else is versioned.
    """
    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.API_V1_PREFIX)


# ASGI entry point: `uvicorn app.main:app --reload`
app = create_app()
