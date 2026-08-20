"""Tenant isolation -- the release gate (spec §12 "Isolation", §2.2).

WHY THESE TESTS ARE THE MOST IMPORTANT IN THE SUITE
    Every other failure in this system is a bug. A failure here is a breach: one
    school's staff reading another school's minors' records.

    Spec §2.2 makes it explicit -- "Add a test that runs the full CRUD suite as
    Org A while Org B data exists, asserting zero rows of B ever appear. This test is
    a release gate."

    They run through the app's own `sms_app` connection (NOBYPASSRLS), so they
    exercise PostgreSQL's policy enforcement rather than an application filter. If
    the policies regressed -- or were never created on a new table -- these fail even
    though every higher-level test still passes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings
from app.db.session import bind_tenant, dispose_engine, get_session_factory, init_engine
from app.modules.academics.models import SchoolClass, Section
from app.modules.students.models import Student, StudentStatus
from tests.integration.conftest import API, Tenant


async def test_organization_cannot_see_another_organizations_schools(
    make_tenant: Callable[..., Any],
) -> None:
    """The headline gate: Org A must never see a single row belonging to Org B."""
    org_a: Tenant = await make_tenant(
        name="Alpha Trust", email="a@test.example", school_code="ALPHA"
    )
    org_b: Tenant = await make_tenant(name="Beta Trust", email="b@test.example", school_code="BETA")

    a_schools = await org_a.get(f"{API}/schools")
    assert a_schools.status_code == 200
    a_ids = {s["id"] for s in a_schools.json()}

    b_schools = await org_b.get(f"{API}/schools")
    b_ids = {s["id"] for s in b_schools.json()}

    assert a_ids and b_ids
    assert a_ids.isdisjoint(b_ids), "an organization saw another organization's schools"
    assert org_b.school_id not in a_ids


async def test_cross_organization_read_returns_404_not_403(
    make_tenant: Callable[..., Any],
) -> None:
    """Spec §12: cross-tenant access returns 404, NOT 403.

    A 403 would confirm the resource exists. Over a school platform that discloses
    which schools are customers of this product -- and, worse, lets an attacker
    enumerate valid ids by watching which ones return 403 instead of 404.

    This is not merely convention: RLS filters the row out of the query entirely, so
    the service genuinely cannot distinguish "another tenant's school" from "no such
    school". The 404 is a consequence of the architecture, not a policy applied on
    top of it.
    """
    org_a: Tenant = await make_tenant(
        name="Alpha Trust", email="a@test.example", school_code="ALPHA"
    )
    org_b: Tenant = await make_tenant(name="Beta Trust", email="b@test.example", school_code="BETA")

    response = await org_a.get(f"{API}/schools/{org_b.school_id}")
    assert response.status_code == 404, (
        f"expected 404 (existence hidden), got {response.status_code}: {response.text}"
    )


async def test_cross_organization_write_is_rejected(
    make_tenant: Callable[..., Any],
) -> None:
    """Org A must not be able to modify Org B's school, even knowing its id."""
    org_a: Tenant = await make_tenant(
        name="Alpha Trust", email="a@test.example", school_code="ALPHA"
    )
    org_b: Tenant = await make_tenant(name="Beta Trust", email="b@test.example", school_code="BETA")

    response = await org_a.patch(f"{API}/schools/{org_b.school_id}", json={"name": "Hijacked"})
    assert response.status_code == 404

    # And B's school is untouched.
    check = await org_b.get(f"{API}/schools/{org_b.school_id}")
    assert check.json()["name"] != "Hijacked"


async def test_school_scoped_context_cannot_read_or_mutate_another_school_academic_data(
    tenant: Tenant,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """The soft boundary: a School A token cannot reach School B rows.

    Organization RLS cannot enforce this boundary because an organization owner is
    intentionally allowed to read across all of its campuses.  School-scoped
    memberships therefore rely on the repository base query injecting the active
    ``school_id``.  This exercises every generic CRUD path plus the custom academic
    aggregate queries, because omitting the filter from even one of them exposes
    minors' records to staff at another campus in the same organization.
    """
    second_school = await tenant.post(
        f"{API}/schools",
        json={"name": "Test Trust North", "code": "NORTH"},
    )
    assert second_school.status_code == 201, second_school.text
    second_school_id = second_school.json()["school"]["id"]

    # Seed valid School B domain rows through the administrative test connection.
    # The public fixtures intentionally create state through the API, but School B
    # has no principal yet and the subject of this test is visibility, not staffing.
    async with admin_sessionmaker() as session:
        foreign_class = SchoolClass(
            organization_id=tenant.organization_id,
            school_id=second_school_id,
            name="Foreign Grade",
            level=91,
        )
        session.add(foreign_class)
        await session.flush()

        foreign_section = Section(
            organization_id=tenant.organization_id,
            school_id=second_school_id,
            class_id=foreign_class.id,
            name="Foreign Section",
            capacity=20,
        )
        foreign_student = Student(
            organization_id=tenant.organization_id,
            school_id=second_school_id,
            admission_number="NORTH-001",
            first_name="School B",
            last_name="Student",
            status=StudentStatus.ACTIVE,
        )
        session.add_all((foreign_section, foreign_student))
        await session.commit()
        foreign_class_id = str(foreign_class.id)
        foreign_section_id = str(foreign_section.id)
        foreign_student_id = str(foreign_student.id)

    # Switch from the owner's org-wide context into the first school's principal
    # membership.  The resulting token must be narrowed to School A.
    me = await tenant.get(f"{API}/auth/me")
    assert me.status_code == 200, me.text
    principal = next(
        membership
        for membership in me.json()["memberships"]
        if membership["school_id"] == tenant.school_id
    )
    switched = await tenant.client.post(
        f"{API}/auth/context",
        json={"membership_id": principal["membership_id"]},
        headers={
            **tenant.headers(),
            "X-Token-Transport": "body",
        },
    )
    assert switched.status_code == 200, switched.text
    school_a_headers = {"Authorization": f"Bearer {switched.headers['X-Access-Token']}"}

    # CREATE is stamped from the verified token, never from request input.
    own_class = await tenant.client.post(
        f"{API}/classes",
        json={"name": "School A Grade", "level": 1},
        headers=school_a_headers,
    )
    assert own_class.status_code == 201, own_class.text
    own_student = await tenant.client.post(
        f"{API}/students",
        json={
            "admission_number": "MAIN-001",
            "first_name": "School A",
            "last_name": "Student",
        },
        headers=school_a_headers,
    )
    assert own_student.status_code == 201, own_student.text

    classes = await tenant.client.get(f"{API}/classes", headers=school_a_headers)
    students = await tenant.client.get(f"{API}/students", headers=school_a_headers)
    summaries = await tenant.client.get(f"{API}/classes/summary", headers=school_a_headers)
    assert classes.status_code == students.status_code == summaries.status_code == 200
    assert {row["id"] for row in classes.json()["items"]} == {own_class.json()["id"]}
    assert {row["id"] for row in students.json()["items"]} == {own_student.json()["id"]}
    assert {row["id"] for row in summaries.json()} == {own_class.json()["id"]}

    # READ/UPDATE/DELETE by a known School B id all fail closed as not found.  A
    # 404 also avoids confirming to School A that the foreign record exists.
    attempts = (
        await tenant.client.get(f"{API}/classes/{foreign_class_id}", headers=school_a_headers),
        await tenant.client.patch(
            f"{API}/classes/{foreign_class_id}",
            json={"name": "Hijacked Class"},
            headers=school_a_headers,
        ),
        await tenant.client.delete(f"{API}/classes/{foreign_class_id}", headers=school_a_headers),
        await tenant.client.patch(
            f"{API}/classes/sections/{foreign_section_id}",
            json={"name": "Hijacked Section"},
            headers=school_a_headers,
        ),
        await tenant.client.delete(
            f"{API}/classes/sections/{foreign_section_id}", headers=school_a_headers
        ),
        await tenant.client.get(f"{API}/students/{foreign_student_id}", headers=school_a_headers),
        await tenant.client.patch(
            f"{API}/students/{foreign_student_id}",
            json={"first_name": "Hijacked"},
            headers=school_a_headers,
        ),
        await tenant.client.delete(
            f"{API}/students/{foreign_student_id}", headers=school_a_headers
        ),
    )
    assert all(response.status_code == 404 for response in attempts), [
        (response.status_code, response.text) for response in attempts
    ]

    # The filter is membership-sensitive, not a blanket school predicate. Switching
    # back to the organization-owner membership intentionally restores cross-campus
    # visibility while organization RLS still contains the query to this tenant.
    owner = next(
        membership for membership in me.json()["memberships"] if membership["is_org_level"]
    )
    switched_back = await tenant.client.post(
        f"{API}/auth/context",
        json={"membership_id": owner["membership_id"]},
        headers={
            **school_a_headers,
            "X-Token-Transport": "body",
        },
    )
    assert switched_back.status_code == 200, switched_back.text
    owner_headers = {"Authorization": f"Bearer {switched_back.headers['X-Access-Token']}"}
    owner_classes = await tenant.client.get(f"{API}/classes", headers=owner_headers)
    owner_students = await tenant.client.get(f"{API}/students", headers=owner_headers)
    assert foreign_class_id in {row["id"] for row in owner_classes.json()["items"]}
    assert foreign_student_id in {row["id"] for row in owner_students.json()["items"]}

    # Verify the failed mutations did not merely hide their response after writing.
    async with admin_sessionmaker() as session:
        saved_class = await session.get(SchoolClass, foreign_class.id)
        saved_section = await session.get(Section, foreign_section.id)
        saved_student = await session.get(Student, foreign_student.id)
        assert saved_class is not None and saved_class.name == "Foreign Grade"
        assert saved_class.deleted_at is None
        assert saved_section is not None and saved_section.name == "Foreign Section"
        assert saved_section.deleted_at is None
        assert saved_student is not None and saved_student.first_name == "School B"
        assert saved_student.deleted_at is None


async def test_unbound_session_sees_zero_rows(db_settings: Settings, tenant: Tenant) -> None:
    """Spec §12: "Direct SQL as the app role without GUCs set -> zero rows."

    This is the property everything else rests on. If a connection with no tenant
    bound could read rows, then any code path that forgot to set the GUC -- a
    background job, a new endpoint, a debugging script -- would silently read the
    whole platform.

    `NULLIF(current_setting(...), '')::uuid` yields NULL when unset, and
    `organization_id = NULL` is NULL rather than true, so the policy matches nothing.
    Fails closed, which is the only acceptable direction.
    """
    await dispose_engine()
    init_engine(db_settings)
    try:
        factory = get_session_factory()
        async with factory() as session:
            await bind_tenant(session, None)  # explicitly no tenant

            for table in ("organizations", "schools", "memberships", "roles"):
                count = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
                assert count == 0, f"{table} leaked {count} rows to an unbound session"
    finally:
        await dispose_engine()


async def test_bound_session_sees_only_its_own_organization(
    db_settings: Settings,
    make_tenant: Callable[..., Any],
) -> None:
    """Binding Org A shows A's rows and none of B's, at the SQL level."""
    org_a: Tenant = await make_tenant(
        name="Alpha Trust", email="a@test.example", school_code="ALPHA"
    )
    org_b: Tenant = await make_tenant(name="Beta Trust", email="b@test.example", school_code="BETA")

    await dispose_engine()
    init_engine(db_settings)
    try:
        factory = get_session_factory()

        async with factory() as session:
            await bind_tenant(session, org_a.organization_id)
            rows = (
                (await session.execute(text("SELECT organization_id::text FROM schools")))
                .scalars()
                .all()
            )
            assert set(rows) == {org_a.organization_id}

        async with factory() as session:
            await bind_tenant(session, org_b.organization_id)
            rows = (
                (await session.execute(text("SELECT organization_id::text FROM schools")))
                .scalars()
                .all()
            )
            assert set(rows) == {org_b.organization_id}
    finally:
        await dispose_engine()


async def test_insert_into_another_tenant_is_refused_by_with_check(
    db_settings: Settings,
    make_tenant: Callable[..., Any],
) -> None:
    """The `WITH CHECK` half: bound to A, you cannot write a row stamped B.

    A `USING`-only policy would let a user of Org A INSERT a row carrying Org B's id.
    They could not read it back -- but they would have written into another tenant's
    data, and B would see it. `WITH CHECK` closes that, and this asserts it is
    actually present rather than assumed.
    """
    org_a: Tenant = await make_tenant(
        name="Alpha Trust", email="a@test.example", school_code="ALPHA"
    )
    org_b: Tenant = await make_tenant(name="Beta Trust", email="b@test.example", school_code="BETA")

    await dispose_engine()
    init_engine(db_settings)
    try:
        factory = get_session_factory()
        async with factory() as session:
            await bind_tenant(session, org_a.organization_id)

            with pytest.raises(DBAPIError) as exc:
                await session.execute(
                    text(
                        "INSERT INTO schools "
                        "(id, organization_id, name, code, slug, academic_year_start_month,"
                        " timezone, locale, status) "
                        "VALUES (gen_random_uuid(), :org, 'Smuggled', 'SMUG', 'smuggled',"
                        " 4, 'UTC', 'en', 'active')"
                    ),
                    {"org": org_b.organization_id},
                )
            assert "row-level security" in str(exc.value).lower()
    finally:
        await dispose_engine()


async def test_platform_admin_guc_grants_reads_but_not_writes(
    db_settings: Settings, tenant: Tenant
) -> None:
    """Spec §2.2: the admin escape is on `USING` only, never on `WITH CHECK`.

    A platform operator may read across tenants for support and billing. They may not
    write into one -- otherwise a single buggy admin endpoint could stamp rows into an
    arbitrary organization with nothing in the database objecting, and the affected
    customer would have no audit trail explaining where the row came from.
    """
    await dispose_engine()
    init_engine(db_settings)
    try:
        factory = get_session_factory()

        # READ: permitted.
        async with factory() as session:
            await bind_tenant(session, None, platform_admin=True)
            count = (await session.execute(text("SELECT count(*) FROM organizations"))).scalar_one()
            assert count >= 1, "platform admin could not read across tenants"

        # WRITE: refused, even with the admin GUC armed.
        async with factory() as session:
            await bind_tenant(session, None, platform_admin=True)
            with pytest.raises(DBAPIError) as exc:
                await session.execute(
                    text(
                        "INSERT INTO schools "
                        "(id, organization_id, name, code, slug, academic_year_start_month,"
                        " timezone, locale, status) "
                        "VALUES (gen_random_uuid(), :org, 'AdminWrite', 'ADMW', 'adminwrite',"
                        " 4, 'UTC', 'en', 'active')"
                    ),
                    {"org": tenant.organization_id},
                )
            assert "row-level security" in str(exc.value).lower()
    finally:
        await dispose_engine()


async def test_every_tenant_table_has_forced_rls(
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """A structural guard: no tenant table may ship without a forced policy.

    WHY ASSERT ON THE SCHEMA RATHER THAN ON BEHAVIOUR
        The behavioural tests above cover the tables they touch. This one catches the
        table nobody wrote a test for -- which is precisely the one that will leak.
        A new module adding `organization_id NOT NULL` and forgetting
        `setup_tenant_table()` fails here, at the point the omission is cheap to fix.

        `FORCE` matters as much as `ENABLE`: without it the table owner bypasses
        every policy silently, so a schema showing `relrowsecurity = true` can still
        be completely unprotected.

    WHY THE RULE IS "NOT NULL organization_id", NOT MERELY "HAS organization_id"
        A NULLABLE `organization_id` is, by definition, not a tenant key -- a NULL
        can never satisfy `organization_id = current_setting(...)`, so RLS on such a
        column would hide exactly the rows that most need to be recorded.

        `webhook_events` is the case in point: a payment webhook arrives
        unauthenticated, and which organization it concerns is only known after
        parsing it. A hostile or malformed payload may name none at all. Requiring
        NOT NULL there would make it impossible to store the events most worth
        investigating.

        Stating the rule this way is deliberate. A hardcoded exclusion list would
        also make this test pass, but the next table someone adds to that list to
        silence a failure would be a real leak.
    """
    async with admin_sessionmaker() as session:
        rows = (
            await session.execute(
                text(
                    """
                    SELECT c.relname,
                           c.relrowsecurity,
                           c.relforcerowsecurity,
                           (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid)
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    JOIN information_schema.columns col
                      ON col.table_name = c.relname
                     AND col.table_schema = 'public'
                     AND col.column_name = 'organization_id'
                     AND col.is_nullable = 'NO'
                    WHERE n.nspname = 'public' AND c.relkind = 'r'
                    """
                )
            )
        ).all()

        assert rows, "no tenant tables found -- has the migration been applied?"

        unprotected = [
            name
            for name, enabled, forced, policies in rows
            if not (enabled and forced and policies)
        ]
        assert not unprotected, (
            f"tables carry a NOT NULL organization_id but lack forced RLS + a policy: {unprotected}"
        )

        # `organizations` keys its policy on `id`, so the join above misses it.
        # Asserting separately keeps the most important table in the schema from
        # being the one the structural guard forgets.
        enabled, forced, policies = (
            await session.execute(
                text(
                    """
                    SELECT c.relrowsecurity, c.relforcerowsecurity,
                           (SELECT count(*) FROM pg_policy p WHERE p.polrelid = c.oid)
                    FROM pg_class c
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public' AND c.relname = 'organizations'
                    """
                )
            )
        ).one()
        assert enabled and forced and policies, "organizations lacks forced RLS"
