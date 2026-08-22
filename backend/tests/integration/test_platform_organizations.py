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
