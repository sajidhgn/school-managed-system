"""Database engine, session factory, and the tenant-scoped session dependency.

WHY THIS FILE EXISTS
    Connection lifecycle is infrastructure, not business logic. This module owns the
    engine (one per process), the session factory, and -- most importantly -- the
    guarantee that every session is bound to exactly one tenant before it executes
    a single business query.

RESPONSIBILITY
    1. Lazily build the async engine so the app can boot with DB_ENABLED=false.
    2. Yield `AsyncSession` objects with correct transaction semantics.
    3. Stamp the PostgreSQL session variable that Row-Level Security policies read.

INTERACTIONS
    * `api/deps.py` re-exports the session dependency for routes.
    * Repositories receive the `AsyncSession` and never construct one themselves.
    * `main.py` lifespan disposes the engine on shutdown.

=============================================================================
HOW MULTI-TENANT ISOLATION ACTUALLY WORKS -- read this before writing any model
=============================================================================
Three independent layers, in order of trustworthiness:

  Layer 1 (application): repositories add `WHERE school_id = :tenant`.
           Convenient, but one forgotten filter in one query leaks data forever.

  Layer 2 (database, THE REAL BOUNDARY): every tenant table has RLS enabled with
           a policy of the form

               CREATE POLICY tenant_isolation ON students
               USING (school_id = current_setting('app.current_school_id')::uuid);

           PostgreSQL then appends that predicate to *every* statement, including
           ad-hoc SQL, ORM queries, and raw text(). A developer literally cannot
           write a query that returns another school's rows.

  Layer 3 (role): the application connects as a role WITHOUT the BYPASSRLS
           attribute and which does not own the tables. Table owners and
           superusers bypass RLS silently -- so if the app connected as `postgres`,
           layer 2 would be decorative. This is the single most commonly missed
           step in RLS deployments.

`_apply_tenant_guc` below is the bridge: it copies the tenant from the verified
JWT into the PostgreSQL session so the policy has something to compare against.
It uses `set_config(..., is_local => true)`, which scopes the value to the current
transaction. That is essential: connections are pooled and reused across requests,
so a session-scoped value would leak School A's tenant onto School B's next request.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import Settings, get_settings
from app.core.context import get_school_id, is_super_admin
from app.core.exceptions import ServiceUnavailableError
from app.core.logging import get_logger

logger = get_logger(__name__)

# Module-level singletons. Created lazily by `init_engine()` during startup so
# that importing this module never opens a socket -- which is what lets the test
# suite and the DB-less phase of development import the app freely.
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None

# PostgreSQL custom GUC names read by the RLS policies.
TENANT_GUC = "app.current_school_id"
SUPER_ADMIN_GUC = "app.is_super_admin"


def init_engine(settings: Settings | None = None) -> AsyncEngine:
    """Create the engine and session factory. Idempotent; called from lifespan."""
    global _engine, _session_factory

    if _engine is not None:
        return _engine

    settings = settings or get_settings()

    _engine = create_async_engine(
        settings.DATABASE_URL,
        echo=settings.DB_ECHO,
        pool_size=settings.DB_POOL_SIZE,
        max_overflow=settings.DB_MAX_OVERFLOW,
        # Verify a pooled connection is alive before handing it out. Without this,
        # connections killed by a proxy/idle-timeout surface as random 500s.
        pool_pre_ping=True,
        # Recycle below typical cloud idle timeouts (often 300-600s).
        pool_recycle=1800,
    )

    _session_factory = async_sessionmaker(
        bind=_engine,
        class_=AsyncSession,
        # expire_on_commit=False: after commit, SQLAlchemy would otherwise expire
        # every attribute, so touching `student.name` in the response serializer
        # triggers a fresh SELECT -- or raises MissingGreenlet in async code.
        expire_on_commit=False,
        autoflush=False,  # explicit flushes only; avoids surprise mid-transaction writes
    )

    logger.info("database_engine_initialised", host=settings.POSTGRES_HOST, db=settings.POSTGRES_DB)
    return _engine


async def dispose_engine() -> None:
    """Close all pooled connections. Called from lifespan shutdown."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        logger.info("database_engine_disposed")
    _engine = None
    _session_factory = None


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    if _session_factory is None:
        raise ServiceUnavailableError(
            "Database is not configured. Set DB_ENABLED=true and provide POSTGRES_* settings.",
            code="DATABASE_NOT_CONFIGURED",
        )
    return _session_factory


async def _apply_tenant_guc(
    session: AsyncSession,
    school_id: UUID | None,
    super_admin: bool,
) -> None:
    """Bind this transaction to a tenant so RLS policies can evaluate.

    `set_config(name, value, is_local)` is used instead of `SET LOCAL` because it
    is a *function* and therefore accepts bind parameters. `SET LOCAL` only takes
    literals, which would mean string-interpolating a value into SQL -- avoidable
    injection surface, even when the value comes from a signed token.

    is_local=true scopes the setting to the current transaction; it is discarded on
    COMMIT/ROLLBACK, so nothing leaks onto the next request that reuses this pooled
    connection.
    """
    await session.execute(
        text("SELECT set_config(:key, :value, true)"),
        {"key": TENANT_GUC, "value": str(school_id) if school_id else ""},
    )
    await session.execute(
        text("SELECT set_config(:key, :value, true)"),
        {"key": SUPER_ADMIN_GUC, "value": "on" if super_admin else "off"},
    )


async def bind_tenant(
    session: AsyncSession,
    school_id: UUID | None,
    *,
    super_admin: bool = False,
) -> None:
    """Re-bind the tenant GUC on an already-open session, mid-transaction.

    WHY THIS EXISTS
        A handful of PRE-authentication flows discover their tenant only *after* a
        lookup, so `get_db` cannot have bound it at session start:

          * self-service registration inserts a brand-new school and must set the
            GUC to that new id so the `schools` WITH CHECK policy accepts the row;
          * login reads the caller's own `School` row to check it is active, but the
            tenant is known only once the user has been found by email.

        Both run on a `PublicDbSession` whose GUC is empty. This helper lets the
        service bind the tenant it just resolved, using the same transaction-scoped
        `set_config` that `get_db` uses -- so nothing leaks past COMMIT onto the next
        request that reuses this pooled connection.

        This is a deliberately narrow, auditable escape hatch. It is NOT a way to
        widen a normal request's tenant: RLS still governs every row, and binding a
        tenant the caller has not proven they own would simply fail the policy.
    """
    await _apply_tenant_guc(session, school_id, super_admin)


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency yielding a tenant-scoped session (one per request).

    TRANSACTION SEMANTICS -- unit of work per request:
      * Commit on success: the handler either fully succeeds or writes nothing.
      * Rollback on any exception, including HTTP errors raised deep in a service.
      * The session is the transaction boundary, so a service that writes to three
        tables gets atomicity for free without any explicit transaction management.

    Services therefore must NOT call `session.commit()` themselves. They may call
    `session.flush()` when they need a generated id before the request ends.
    """
    factory = get_session_factory()

    async with factory() as session:
        await _apply_tenant_guc(session, get_school_id(), is_super_admin())
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def session_scope(
    school_id: UUID | None = None,
    *,
    super_admin: bool = False,
) -> AsyncIterator[AsyncSession]:
    """Session context manager for code running OUTSIDE a request.

    Background jobs, Alembic data migrations, seed scripts and CLI commands have no
    HTTP request and therefore no ambient context -- they must pass the tenant
    explicitly. Same transaction semantics as `get_db`.

        async with session_scope(school_id) as session:
            await StudentRepository(session).list_all()
    """
    factory = get_session_factory()
    async with factory() as session:
        await _apply_tenant_guc(session, school_id, super_admin)
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
