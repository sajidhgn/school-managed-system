"""Staff helpers shared by the teaching-scope suites.

A teacher signed in through the real login path, on the SEEDED teacher role, and a
subject linked to a campus's class -- the two pieces every assignment-boundary test
builds before it can assert anything.
"""

from __future__ import annotations

from typing import Any

from tests.integration.conftest import API, STRONG_PASSWORD, Tenant
from tests.integration.test_academic_foundation import Campus


class Staff:
    """A teacher signed in through the real login path."""

    def __init__(self, tenant: Tenant, user_id: str, token: str) -> None:
        self.tenant = tenant
        self.user_id = user_id
        self.headers = {"Authorization": f"Bearer {token}"}

    async def get(self, url: str, **kw: Any) -> Any:
        return await self.tenant.client.get(url, headers=self.headers, **kw)

    async def put(self, url: str, **kw: Any) -> Any:
        return await self.tenant.client.put(url, headers=self.headers, **kw)


async def _teacher(tenant: Tenant, email: str, name: str) -> Staff:
    """A member on the SEEDED teacher role -- so the test also proves the role's
    default grants are what a teacher really holds."""
    roles = await tenant.get(f"{API}/schools/{tenant.school_id}/roles")
    assert roles.status_code == 200, roles.text
    role_id = next(r["id"] for r in roles.json() if r["code"] == "teacher")

    created = await tenant.post(
        f"{API}/schools/{tenant.school_id}/members",
        json={"email": email, "full_name": name, "password": STRONG_PASSWORD, "role_id": role_id},
    )
    assert created.status_code == 201, created.text

    tenant.client.cookies.clear()
    login = await tenant.client.post(
        f"{API}/auth/login",
        json={"email": email, "password": STRONG_PASSWORD},
        headers={"X-Token-Transport": "body"},
    )
    assert login.status_code == 200, login.text
    tenant.client.cookies.clear()
    return Staff(tenant, created.json()["user_id"], str(login.headers["X-Access-Token"]))


async def _subject(campus: Campus, code: str, teacher_id: str | None = None) -> str:
    created = await campus.post(f"{API}/subjects", json={"code": code, "name": f"Subject {code}"})
    assert created.status_code == 201, created.text
    subject_id = created.json()["id"]
    linked = await campus.post(
        f"{API}/classes/{campus.class_id}/subjects",
        json={"subject_id": subject_id, "teacher_id": teacher_id},
    )
    assert linked.status_code == 201, linked.text
    return str(subject_id)
