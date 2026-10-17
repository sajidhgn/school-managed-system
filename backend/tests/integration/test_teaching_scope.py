"""PostgreSQL-backed tests for the teacher's view of classes and students.

The rule under test: a teacher sees the classes and students they are assigned to
-- their section as class teacher, every section of a class they teach a subject
in -- and nothing else, on every read that lists them. An administrator (here the
campus head who built the school) still sees everything.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.common.email.sender import EmailMessage
from tests.integration.conftest import API, Tenant
from tests.integration.staff import Staff, _subject, _teacher
from tests.integration.test_academic_foundation import Campus, build_campus

pytestmark = pytest.mark.asyncio


async def _student(campus: Campus, admission: str, first_name: str, section_id: str) -> str:
    created = await campus.post(
        f"{API}/students",
        json={
            "admission_number": admission,
            "first_name": first_name,
            "last_name": "Scoped",
            "section_id": section_id,
            "guardian_name": "Parent Scoped",
            "guardian_phone": "03001112233",
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def _section(campus: Campus, class_id: str, name: str) -> str:
    created = await campus.post(f"{API}/classes/{class_id}/sections", json={"name": name})
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


class School:
    """Grade 9 with sections A (campus's) and B, Grade 10 with section A."""

    def __init__(self, campus: Campus) -> None:
        self.campus = campus
        self.section_9b = ""
        self.class_10 = ""
        self.section_10a = ""
        self.student_9b = ""
        self.student_10a = ""


@pytest.fixture
async def school(tenant: Tenant, mailbox: list[EmailMessage]) -> School:
    campus = await build_campus(tenant, mailbox)
    built = School(campus)
    built.section_9b = await _section(campus, campus.class_id, "B")
    grade_10 = await campus.post(f"{API}/classes", json={"name": "Grade 10", "level": 10})
    assert grade_10.status_code == 201, grade_10.text
    built.class_10 = grade_10.json()["id"]
    built.section_10a = await _section(campus, built.class_10, "A")
    built.student_9b = await _student(campus, "S-9B", "Nineb", built.section_9b)
    built.student_10a = await _student(campus, "S-10A", "Tena", built.section_10a)
    return built


async def _class_teacher_of_9a(school: School) -> Staff:
    teacher = await _teacher(school.campus.tenant, "ct9a@test.example", "Class Teacher")
    assigned = await school.campus.patch(
        f"{API}/classes/sections/{school.campus.section_id}",
        json={"class_teacher_id": teacher.user_id},
    )
    assert assigned.status_code == 200, assigned.text
    return teacher


def _sections(summary: list[dict[str, Any]]) -> dict[str, list[str]]:
    return {c["name"]: [s["name"] for s in c["sections"]] for c in summary}


async def test_class_teacher_sees_only_their_section(school: School) -> None:
    campus = school.campus
    teacher = await _class_teacher_of_9a(school)

    summary = await teacher.get(f"{API}/classes/summary")
    assert summary.status_code == 200, summary.text
    assert _sections(summary.json()) == {"Grade 9": ["A"]}

    classes = await teacher.get(f"{API}/classes")
    assert [c["name"] for c in classes.json()["items"]] == ["Grade 9"]
    assert (await teacher.get(f"{API}/classes/{school.class_10}")).status_code == 404
    sections = await teacher.get(f"{API}/classes/{campus.class_id}/sections")
    assert [s["name"] for s in sections.json()] == ["A"]

    students = await teacher.get(f"{API}/students", params={"size": 100})
    assert students.status_code == 200, students.text
    assert {s["id"] for s in students.json()["items"]} == set(campus.student_ids)

    # Reaching around the list by id is refused the same way.
    assert (await teacher.get(f"{API}/students/{school.student_9b}")).status_code == 404
    assert (
        await teacher.get(f"{API}/students/{school.student_10a}/enrollments")
    ).status_code == 404
    assert (await teacher.get(f"{API}/students/{campus.student_ids[0]}")).status_code == 200
    assert (
        await teacher.get(f"{API}/classes/sections/{school.section_9b}/roster")
    ).status_code == 404
    roster = await teacher.get(f"{API}/classes/sections/{campus.section_id}/roster")
    assert roster.status_code == 200, roster.text


async def test_subject_teacher_sees_every_section_of_their_class(school: School) -> None:
    campus = school.campus
    teacher = await _teacher(campus.tenant, "maths@test.example", "Maths Teacher")
    await _subject(campus, "MATH", teacher_id=teacher.user_id)

    summary = await teacher.get(f"{API}/classes/summary")
    assert _sections(summary.json()) == {"Grade 9": ["A", "B"]}

    students = await teacher.get(f"{API}/students", params={"size": 100})
    ids = {s["id"] for s in students.json()["items"]}
    assert ids == {*campus.student_ids, school.student_9b}
    assert school.student_10a not in ids


async def test_unassigned_teacher_sees_nothing(school: School) -> None:
    teacher = await _teacher(school.campus.tenant, "new@test.example", "New Teacher")

    assert (await teacher.get(f"{API}/classes/summary")).json() == []
    assert (await teacher.get(f"{API}/students")).json()["items"] == []


async def test_administrator_still_sees_everything(school: School) -> None:
    await _class_teacher_of_9a(school)

    summary = await school.campus.get(f"{API}/classes/summary")
    assert _sections(summary.json()) == {"Grade 9": ["A", "B"], "Grade 10": ["A"]}


async def test_search_is_bounded_the_same_way(school: School) -> None:
    teacher = await _class_teacher_of_9a(school)

    found = await teacher.get(f"{API}/search", params={"q": "Scoped"})
    assert found.status_code == 200, found.text
    titles = [
        hit["title"] for g in found.json()["groups"] if g["type"] == "student" for hit in g["hits"]
    ]
    assert titles == []  # both "Scoped" students sit outside 9-A

    grades = await teacher.get(f"{API}/search", params={"q": "Grade"})
    class_titles = [
        hit["title"] for g in grades.json()["groups"] if g["type"] == "class" for hit in g["hits"]
    ]
    assert class_titles == ["Grade 9"]


async def test_teacher_cannot_read_the_staff_list(school: School) -> None:
    teacher = await _teacher(school.campus.tenant, "staff@test.example", "Any Teacher")
    tenant = school.campus.tenant

    members = await teacher.get(f"{API}/schools/{tenant.school_id}/members")
    assert members.status_code == 403, members.text


async def test_principal_can_lift_the_bound_from_the_teacher_role(school: School) -> None:
    """`class:view_all` is a role permission like any other: ticking it on the
    teacher role shows every class to every teacher on it."""
    tenant = school.campus.tenant
    roles = (await tenant.get(f"{API}/schools/{tenant.school_id}/roles")).json()
    role_id = next(r["id"] for r in roles if r["code"] == "teacher")
    url = f"{API}/schools/{tenant.school_id}/roles/{role_id}"
    codes = (await tenant.get(url)).json()["permissions"]
    assert "class:view_all" not in codes
    granted = await tenant.put(f"{url}/permissions", json={"codes": [*codes, "class:view_all"]})
    assert granted.status_code == 200, granted.text

    teacher = await _teacher(tenant, "senior@test.example", "Senior Teacher")

    summary = await teacher.get(f"{API}/classes/summary")
    assert _sections(summary.json()) == {"Grade 9": ["A", "B"], "Grade 10": ["A"]}
    assert (await teacher.get(f"{API}/students/{school.student_10a}")).status_code == 200
