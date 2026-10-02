"""Organization drilldown from the operator console.

The console's organizations table only ever showed a `schools_count` integer --
there was no way for an operator to see which campuses actually make up that count.
This covers the endpoint that backs the org-detail "Schools" list.
"""

from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.conftest import API, STRONG_PASSWORD, Tenant


async def _platform_session(
    db_client: AsyncClient, admin_sessionmaker: async_sessionmaker[AsyncSession]
) -> dict[str, str]:
    """Seed an operator and return a bearer header for them."""
    from app.core.security import hash_password

    async with admin_sessionmaker() as session:
        await session.execute(
            text(
                "INSERT INTO platform_admins (id, email, password_hash, full_name, is_active)"
                " VALUES (gen_random_uuid(), :email, :pw, 'Ops', true)"
            ),
            {"email": "ops@platform.example", "pw": hash_password(STRONG_PASSWORD)},
        )
        await session.commit()

    login = await db_client.post(
        f"{API}/platform/auth/login",
        json={"email": "ops@platform.example", "password": STRONG_PASSWORD},
        headers={"X-Token-Transport": "body"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.headers['X-Access-Token']}"}


async def test_list_schools_returns_the_organizations_schools(
    db_client: AsyncClient,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    tenant: Tenant,
) -> None:
    headers = await _platform_session(db_client, admin_sessionmaker)

    response = await db_client.get(
        f"{API}/platform/organizations/{tenant.organization_id}/schools", headers=headers
    )

    assert response.status_code == 200, response.text
    schools = response.json()
    assert [s["id"] for s in schools] == [tenant.school_id]
    assert schools[0]["code"] == "MAIN"


async def test_list_schools_404s_for_unknown_organization(
    db_client: AsyncClient,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    headers = await _platform_session(db_client, admin_sessionmaker)

    response = await db_client.get(
        f"{API}/platform/organizations/{uuid4()}/schools", headers=headers
    )

    assert response.status_code == 404, response.text


async def test_list_schools_refuses_a_tenant_token(tenant: Tenant) -> None:
    response = await tenant.get(f"{API}/platform/organizations/{tenant.organization_id}/schools")

    assert response.status_code == 403, response.text


async def test_analytics_reports_the_platform(
    db_client: AsyncClient,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    tenant: Tenant,
) -> None:
    headers = await _platform_session(db_client, admin_sessionmaker)

    response = await db_client.get(f"{API}/platform/analytics", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["organizations_total"] >= 1
    assert body["schools_total"] >= 1
    assert len(body["growth"]) == 12
    assert len(body["revenue"]) == 12
    # The tenant fixture signed up this month, so the newest bucket counts it.
    assert body["growth"][-1]["organizations"] >= 1
    assert any(p["subscribers"] >= 1 for p in body["plans"])
    assert tenant.organization_id in {o["organization_id"] for o in body["recent_organizations"]}


async def test_analytics_refuses_a_tenant_token(tenant: Tenant) -> None:
    response = await tenant.get(f"{API}/platform/analytics")

    assert response.status_code == 403, response.text


async def test_audit_log_names_the_actor_and_filters_by_action(
    db_client: AsyncClient,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    headers = await _platform_session(db_client, admin_sessionmaker)

    response = await db_client.get(
        f"{API}/platform/audit-logs?action=platform_admin.logged_in", headers=headers
    )

    assert response.status_code == 200, response.text
    entries = response.json()
    assert entries, "the login above writes an audit row"
    assert {e["action"] for e in entries} == {"platform_admin.logged_in"}
    assert entries[0]["actor_email"] == "ops@platform.example"


async def test_plan_override_converts_a_trialing_organization(
    db_client: AsyncClient,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    tenant: Tenant,
) -> None:
    """The subscription goes ACTIVE, so the organization must stop reading as a trial."""
    headers = await _platform_session(db_client, admin_sessionmaker)
    async with admin_sessionmaker() as session:
        await session.execute(
            text("UPDATE organizations SET status = 'trialing' WHERE id = :id"),
            {"id": tenant.organization_id},
        )
        await session.commit()

    response = await db_client.post(
        f"{API}/platform/organizations/{tenant.organization_id}/plan",
        json={"plan_code": "growth"},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "active"
    assert response.json()["subscription_status"] == "active"
