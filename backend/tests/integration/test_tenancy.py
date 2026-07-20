"""Tenancy endpoints: super-admin management and the access boundary around it."""

from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient

from tests.integration.conftest import SeededUser, auth_header


def _super_admin_header() -> dict[str, str]:
    return auth_header(user_id=str(uuid4()), role="super_admin", super_admin=True)


async def test_super_admin_can_onboard_and_list_schools(db_client: AsyncClient) -> None:
    headers = _super_admin_header()

    created = await db_client.post(
        "/api/v1/schools",
        headers=headers,
        json={"name": "Riverdale Academy", "email": "office@riverdale.edu", "plan": "standard"},
    )
    assert created.status_code == 201, created.text
    school = created.json()
    assert school["status"] == "active"  # super-admin onboarding goes live immediately
    assert school["slug"].startswith("riverdale-academy")

    listing = await db_client.get("/api/v1/schools", headers=headers)
    assert listing.status_code == 200
    body = listing.json()
    assert body["meta"]["total"] >= 1
    assert any(s["id"] == school["id"] for s in body["items"])


async def test_approve_then_suspend_transitions(db_client: AsyncClient, seed_school) -> None:
    from app.modules.tenancy.models import SchoolStatus

    pending = await seed_school(name="Pending School", status=SchoolStatus.PENDING_APPROVAL)
    headers = _super_admin_header()

    approved = await db_client.post(f"/api/v1/schools/{pending.id}/approve", headers=headers)
    assert approved.status_code == 200
    assert approved.json()["status"] == "active"
    assert approved.json()["approved_at"] is not None

    suspended = await db_client.post(f"/api/v1/schools/{pending.id}/suspend", headers=headers)
    assert suspended.status_code == 200
    assert suspended.json()["status"] == "suspended"


async def test_list_can_filter_by_status(db_client: AsyncClient, seed_school) -> None:
    from app.modules.tenancy.models import SchoolStatus

    await seed_school(name="Active One", status=SchoolStatus.ACTIVE)
    await seed_school(name="Pending One", status=SchoolStatus.PENDING_APPROVAL)
    headers = _super_admin_header()

    resp = await db_client.get(
        "/api/v1/schools", headers=headers, params={"status_filter": "pending_approval"}
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert items and all(s["status"] == "pending_approval" for s in items)


async def test_school_admin_cannot_reach_platform_endpoints(
    db_client: AsyncClient, seed_school, seed_user
) -> None:
    from app.modules.auth.models import UserRole

    school = await seed_school()
    admin: SeededUser = await seed_user(
        school_id=str(school.id), email="admin@riverdale.edu", role=UserRole.SCHOOL_ADMIN
    )
    headers = auth_header(user_id=admin.user_id, school_id=admin.school_id, role="school_admin")

    resp = await db_client.get("/api/v1/schools", headers=headers)
    assert resp.status_code == 403


async def test_school_admin_reads_own_school_via_current(
    db_client: AsyncClient, seed_school, seed_user
) -> None:
    from app.modules.auth.models import UserRole

    school = await seed_school(name="Own School")
    admin: SeededUser = await seed_user(
        school_id=str(school.id), email="admin2@riverdale.edu", role=UserRole.SCHOOL_ADMIN
    )
    headers = auth_header(user_id=admin.user_id, school_id=admin.school_id, role="school_admin")

    resp = await db_client.get("/api/v1/schools/current", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["id"] == str(school.id)


async def test_missing_school_is_404(db_client: AsyncClient) -> None:
    resp = await db_client.get(f"/api/v1/schools/{uuid4()}", headers=_super_admin_header())
    assert resp.status_code == 404
    assert resp.json()["code"] == "NOT_FOUND"
