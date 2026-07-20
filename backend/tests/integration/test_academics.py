"""Integration tests for the academics module (classes + sections).

These run against real PostgreSQL with the app connected as the restricted
`sms_app` role, so every assertion here is also an assertion that RLS did not get
in the way of legitimate access -- and, in the isolation test, that it did get in
the way of illegitimate access.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from httpx import AsyncClient

from app.modules.auth.models import UserRole
from tests.integration.conftest import auth_header


async def _admin_ctx(
    seed_school: Callable[..., Any], seed_user: Callable[..., Any]
) -> tuple[dict[str, str], str]:
    """Seed an active school with a school_admin, returning (headers, school_id)."""
    school = await seed_school(name="Academics High")
    admin = await seed_user(
        school_id=str(school.id), email="admin@academics.test", role=UserRole.SCHOOL_ADMIN
    )
    headers = auth_header(
        user_id=admin.user_id, school_id=str(school.id), role=UserRole.SCHOOL_ADMIN.value
    )
    return headers, str(school.id)


class TestClassSetup:
    async def test_create_and_list_class(
        self, db_client: AsyncClient, seed_school: Any, seed_user: Any
    ) -> None:
        headers, _ = await _admin_ctx(seed_school, seed_user)

        created = await db_client.post(
            "/api/v1/classes", json={"name": "Grade 10", "level": 10}, headers=headers
        )
        assert created.status_code == 201, created.text
        assert created.json()["name"] == "Grade 10"

        listed = await db_client.get("/api/v1/classes", headers=headers)
        assert listed.status_code == 200
        assert listed.json()["meta"]["total"] == 1

    async def test_duplicate_class_name_is_rejected(
        self, db_client: AsyncClient, seed_school: Any, seed_user: Any
    ) -> None:
        headers, _ = await _admin_ctx(seed_school, seed_user)
        payload = {"name": "Grade 10", "level": 10}

        assert (
            await db_client.post("/api/v1/classes", json=payload, headers=headers)
        ).status_code == 201

        duplicate = await db_client.post(
            "/api/v1/classes", json={"name": "Grade 10", "level": 11}, headers=headers
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "CONFLICT"

    async def test_teacher_cannot_create_a_class(
        self, db_client: AsyncClient, seed_school: Any, seed_user: Any
    ) -> None:
        """RBAC: the PDF limits teachers to their assigned classes, not school setup."""
        school = await seed_school(name="RBAC High")
        teacher = await seed_user(
            school_id=str(school.id), email="teacher@rbac.test", role=UserRole.TEACHER
        )
        headers = auth_header(
            user_id=teacher.user_id, school_id=str(school.id), role=UserRole.TEACHER.value
        )

        response = await db_client.post(
            "/api/v1/classes", json={"name": "Grade 9", "level": 9}, headers=headers
        )
        assert response.status_code == 403
        assert response.json()["code"] == "INSUFFICIENT_ROLE"

    async def test_class_with_sections_cannot_be_deleted(
        self, db_client: AsyncClient, seed_school: Any, seed_user: Any
    ) -> None:
        headers, _ = await _admin_ctx(seed_school, seed_user)
        class_id = (
            await db_client.post(
                "/api/v1/classes", json={"name": "Grade 8", "level": 8}, headers=headers
            )
        ).json()["id"]
        await db_client.post(
            f"/api/v1/classes/{class_id}/sections", json={"name": "A"}, headers=headers
        )

        response = await db_client.delete(f"/api/v1/classes/{class_id}", headers=headers)
        assert response.status_code == 409
        assert "section" in response.json()["detail"].lower()


class TestSectionSetup:
    async def test_create_section_and_reject_duplicate(
        self, db_client: AsyncClient, seed_school: Any, seed_user: Any
    ) -> None:
        headers, _ = await _admin_ctx(seed_school, seed_user)
        class_id = (
            await db_client.post(
                "/api/v1/classes", json={"name": "Grade 7", "level": 7}, headers=headers
            )
        ).json()["id"]

        created = await db_client.post(
            f"/api/v1/classes/{class_id}/sections",
            json={"name": "A", "capacity": 30},
            headers=headers,
        )
        assert created.status_code == 201, created.text
        assert created.json()["capacity"] == 30

        duplicate = await db_client.post(
            f"/api/v1/classes/{class_id}/sections", json={"name": "A"}, headers=headers
        )
        assert duplicate.status_code == 409

    async def test_capacity_must_be_positive(
        self, db_client: AsyncClient, seed_school: Any, seed_user: Any
    ) -> None:
        headers, _ = await _admin_ctx(seed_school, seed_user)
        class_id = (
            await db_client.post(
                "/api/v1/classes", json={"name": "Grade 6", "level": 6}, headers=headers
            )
        ).json()["id"]

        response = await db_client.post(
            f"/api/v1/classes/{class_id}/sections",
            json={"name": "A", "capacity": 0},
            headers=headers,
        )
        assert response.status_code == 422

    async def test_sections_of_unknown_class_are_404(
        self, db_client: AsyncClient, seed_school: Any, seed_user: Any
    ) -> None:
        headers, _ = await _admin_ctx(seed_school, seed_user)
        unknown = "00000000-0000-0000-0000-0000000000ff"
        response = await db_client.get(f"/api/v1/classes/{unknown}/sections", headers=headers)
        assert response.status_code == 404


class TestSummaries:
    async def test_summary_reports_headcount_per_section(
        self, db_client: AsyncClient, seed_school: Any, seed_user: Any
    ) -> None:
        headers, _ = await _admin_ctx(seed_school, seed_user)
        class_id = (
            await db_client.post(
                "/api/v1/classes", json={"name": "Grade 5", "level": 5}, headers=headers
            )
        ).json()["id"]
        section_id = (
            await db_client.post(
                f"/api/v1/classes/{class_id}/sections", json={"name": "A"}, headers=headers
            )
        ).json()["id"]

        for i in range(3):
            response = await db_client.post(
                "/api/v1/students",
                json={
                    "admission_number": f"S-{i}",
                    "first_name": "Pupil",
                    "last_name": str(i),
                    "section_id": section_id,
                },
                headers=headers,
            )
            assert response.status_code == 201, response.text

        summary = await db_client.get("/api/v1/classes/summary", headers=headers)
        assert summary.status_code == 200, summary.text
        body = summary.json()
        assert len(body) == 1
        assert body[0]["student_count"] == 3
        assert body[0]["section_count"] == 1
        assert body[0]["sections"][0]["student_count"] == 3


class TestCrossTenantIsolation:
    async def test_a_school_cannot_read_another_schools_class(
        self, db_client: AsyncClient, seed_school: Any, seed_user: Any
    ) -> None:
        """The RLS guarantee, exercised over real HTTP.

        School B asks for School A's class by its real id. RLS filters the row out,
        the service sees None, and the caller gets 404 -- NOT 403, which would
        confirm the record exists and is itself a cross-tenant leak.
        """
        headers_a, _ = await _admin_ctx(seed_school, seed_user)
        class_id = (
            await db_client.post(
                "/api/v1/classes", json={"name": "Grade 12", "level": 12}, headers=headers_a
            )
        ).json()["id"]

        school_b = await seed_school(name="Rival High")
        admin_b = await seed_user(
            school_id=str(school_b.id), email="admin@rival.test", role=UserRole.SCHOOL_ADMIN
        )
        headers_b = auth_header(
            user_id=admin_b.user_id,
            school_id=str(school_b.id),
            role=UserRole.SCHOOL_ADMIN.value,
        )

        response = await db_client.get(f"/api/v1/classes/{class_id}", headers=headers_b)
        assert response.status_code == 404

        listed = await db_client.get("/api/v1/classes", headers=headers_b)
        assert listed.json()["meta"]["total"] == 0
