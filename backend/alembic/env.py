"""Alembic migration environment.

WHY THIS FILE EXISTS
    Alembic needs to know two things: where the database is, and what the schema
    *should* look like. This file supplies both from the application itself, so
    there is exactly one definition of each and they cannot drift.

RESPONSIBILITY
    * Inject the DSN from `app.core.config` (never hard-code credentials).
    * Expose `Base.metadata` as the autogenerate target.
    * Run migrations over an async engine.

INTERACTIONS
    Imports `app.db.base.Base` and `app.db.registry`, which is the module that
    imports every model. If a model is not reachable from that import, autogenerate
    will not see it and will happily generate a migration that DROPs its table.

MIGRATIONS RUN AS THE OWNER, THE APP RUNS AS A RESTRICTED ROLE
    Alembic connects as the table owner (DDL rights, and implicitly bypasses RLS).
    The application connects as `sms_app`, which has DML rights only and NO
    BYPASSRLS. Using one role for both would silently disable every RLS policy --
    the most common way multi-tenant isolation fails in production.
"""

from __future__ import annotations

import asyncio
import os
from logging.config import fileConfig

import alembic
from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import app.db.registry  # noqa: F401  (import for side effect: populates Base.metadata)
from app.core.config import get_settings
from app.db.base import Base

# ---------------------------------------------------------------------------
# Make migration helpers importable as `alembic.rls`.
#
# WHY THIS IS NEEDED: this project ships helpers in `alembic/rls.py` and the
# convention (see PROJECT_STRUCTURE.md and rls.py's own docstring) is that
# migrations do `from alembic.rls import setup_tenant_table`. But the *installed*
# `alembic` distribution is a regular package that shadows this local directory,
# so `alembic.rls` would not resolve on its own. Extending the installed package's
# search path to include this directory makes the documented import work for every
# migration -- and env.py always runs before any migration, so this is in place in
# time. It is idempotent (append-once guarded).
_ALEMBIC_DIR = os.path.dirname(os.path.abspath(__file__))
if _ALEMBIC_DIR not in alembic.__path__:
    alembic.__path__.append(_ALEMBIC_DIR)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

settings = get_settings()
# MIGRATION_DATABASE_URL, not DATABASE_URL -- see the module docstring above. This
# connects as the schema owner; the application's restricted role cannot run DDL.
config.set_main_option("sqlalchemy.url", settings.MIGRATION_DATABASE_URL)

target_metadata = Base.metadata


def include_object(object_, name: str, type_: str, reflected: bool, compare_to) -> bool:  # type: ignore[no-untyped-def]
    """Filter what autogenerate considers.

    PostgreSQL extensions (pg_trgm, pgcrypto) create their own indexes and tables.
    Without this filter Alembic sees them as "unexpected" objects and generates
    DROP statements for them on every run.
    """
    return not (type_ == "table" and name.startswith(("pg_", "sql_")))


def process_revision_directives(context_, revision, directives) -> None:  # type: ignore[no-untyped-def]
    """Suppress empty migrations.

    Running `alembic revision --autogenerate` when nothing changed otherwise
    produces a no-op file that clutters history and confuses reviewers.
    """
    if getattr(config.cmd_opts, "autogenerate", False):
        script = directives[0]
        if script.upgrade_ops.is_empty():
            directives[:] = []
            print("No schema changes detected -- skipping empty migration.")


def _configure(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
        process_revision_directives=process_revision_directives,
        # Detect column type changes (VARCHAR(50) -> VARCHAR(100)). Off by default,
        # which means silent schema drift.
        compare_type=True,
        # Detect server_default changes.
        compare_server_default=True,
        # Wrap each migration in a transaction so a failure mid-migration rolls
        # back cleanly. PostgreSQL supports transactional DDL -- one of the main
        # reasons this project targets it.
        transaction_per_migration=True,
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    """Generate SQL to stdout without a database connection.

    `alembic upgrade head --sql` produces a script a DBA can review and apply
    manually -- required in environments where the deploy pipeline has no direct
    write access to production.
    """
    context.configure(
        url=settings.MIGRATION_DATABASE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Apply migrations against a live database using the async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # migrations are short-lived; pooling adds nothing
    )

    async with connectable.connect() as connection:
        await connection.run_sync(_configure)

    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
