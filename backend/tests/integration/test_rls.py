"""Row-Level Security isolation -- the real tenant boundary.

These tests run queries through the APP's `sms_app` connection (NOBYPASSRLS), so they
exercise PostgreSQL's policy enforcement directly rather than the application-layer
filter. If RLS regressed, these fail even though every higher-level test still passes.
"""

from __future__ import annotations

import secrets

import pytest
from sqlalchemy.exc import DBAPIError

from app.common.schemas import PageParams
from app.core.config import Settings
from app.db.session import bind_tenant, dispose_engine, get_session_factory, init_engine
from app.modules.tenancy.models import School, SchoolStatus, SubscriptionPlan
from app.modules.tenancy.repository import SchoolRepository


async def test_reads_are_scoped_to_the_bound_tenant(db_settings: Settings, seed_school) -> None:
    school_a = await seed_school(name="Alpha Academy")
    school_b = await seed_school(name="Beta Institute")

    await dispose_engine()
    init_engine(db_settings)
    try:
        factory = get_session_factory()

        # Bound to A: only A is visible, even though B exists in the table.
        async with factory() as session:
            await bind_tenant(session, school_a.id)
            rows, _ = await SchoolRepository(session).list(params=PageParams(page=1, size=50))
            assert {str(r.id) for r in rows} == {str(school_a.id)}

        # Bound to B: only B.
        async with factory() as session:
            await bind_tenant(session, school_b.id)
            rows, _ = await SchoolRepository(session).list(params=PageParams(page=1, size=50))
            assert {str(r.id) for r in rows} == {str(school_b.id)}

        # Super admin: both are visible (the platform escape hatch).
        async with factory() as session:
            await bind_tenant(session, None, super_admin=True)
            rows, _ = await SchoolRepository(session).list(params=PageParams(page=1, size=50))
            visible = {str(r.id) for r in rows}
            assert {str(school_a.id), str(school_b.id)} <= visible
    finally:
        await dispose_engine()


async def test_unbound_session_sees_no_schools(db_settings: Settings, seed_school) -> None:
    """With no tenant bound (an unauthenticated session), RLS returns zero rows."""
    await seed_school(name="Invisible Academy")

    await dispose_engine()
    init_engine(db_settings)
    try:
        async with get_session_factory()() as session:
            # get_db would bind an empty GUC; emulate that unbound state.
            await bind_tenant(session, None)
            rows, total = await SchoolRepository(session).list(params=PageParams())
            assert total == 0
            assert rows == []
    finally:
        await dispose_engine()


async def test_writes_cannot_target_another_tenant(db_settings: Settings, seed_school) -> None:
    """A session bound to A cannot INSERT a row belonging to a different tenant.

    The schools WITH CHECK clause (`id = <current tenant>`) rejects it at the database,
    even though `sms_app` holds INSERT privilege on the table.
    """
    school_a = await seed_school(name="Gamma School")

    await dispose_engine()
    init_engine(db_settings)
    try:
        async with get_session_factory()() as session:
            await bind_tenant(session, school_a.id)
            # A brand-new school row has its own random id != school_a.id, so it falls
            # outside this tenant and the WITH CHECK policy must refuse the write.
            session.add(
                School(
                    name="Sneaky Annex",
                    slug=f"sneaky-{secrets.token_hex(3)}",
                    email="sneaky@example.com",
                    status=SchoolStatus.ACTIVE,
                    plan=SubscriptionPlan.TRIAL,
                    max_students=1,
                )
            )
            with pytest.raises(DBAPIError) as exc:
                await session.flush()
            assert "row-level security" in str(exc.value).lower()
    finally:
        await dispose_engine()
