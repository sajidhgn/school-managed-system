"""Editing a staff member from the members table: rename, and the classes they teach."""

from __future__ import annotations

from app.common.email.sender import EmailMessage
from tests.integration.conftest import API, STRONG_PASSWORD, Tenant
from tests.integration.test_academic_foundation import Campus, build_campus


async def _add_teacher(campus: Campus, school_id: str) -> dict[str, str]:
    roles = await campus.get(f"{API}/schools/{school_id}/roles")
    role_id = next(r["id"] for r in roles.json() if r["code"] == "teacher")
    created = await campus.post(
        f"{API}/schools/{school_id}/members",
        json={
            "email": "edit.me@test.example",
            "full_name": "Edit Me",
            "password": STRONG_PASSWORD,
            "role_id": role_id,
        },
    )
    assert created.status_code == 201, created.text
    return dict(created.json())


async def _row(campus: Campus, school_id: str, membership_id: str) -> dict:
    page = await campus.get(f"{API}/schools/{school_id}/members?size=100")
    assert page.status_code == 200, page.text
    return next(m for m in page.json()["items"] if m["membership_id"] == membership_id)


async def test_members_list_shows_and_removes_class_assignments(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    campus = await build_campus(tenant, mailbox, students=0)
    school = tenant.school_id
    teacher = await _add_teacher(campus, school)

    assigned = await campus.patch(
        f"{API}/classes/sections/{campus.section_id}",
        json={"class_teacher_id": teacher["user_id"]},
    )
    assert assigned.status_code == 200, assigned.text
    subject = await campus.post(f"{API}/subjects", json={"code": "PHY", "name": "Physics"})
    link = await campus.post(
        f"{API}/classes/{campus.class_id}/subjects",
        json={"subject_id": subject.json()["id"], "teacher_id": teacher["user_id"]},
    )
    assert link.status_code == 201, link.text

    row = await _row(campus, school, teacher["membership_id"])
    assert row["assigned_classes"] == [
        {
            "class_name": "Grade 9",
            "section_id": campus.section_id,
            "section_name": "A",
            "class_subject_id": None,
            "subject_name": None,
        },
        {
            "class_name": "Grade 9",
            "section_id": None,
            "section_name": None,
            "class_subject_id": link.json()["id"],
            "subject_name": "Physics",
        },
    ]

    # "Remove from class" clears the teacher on the section / curriculum row.
    await campus.patch(
        f"{API}/classes/sections/{campus.section_id}", json={"class_teacher_id": None}
    )
    await campus.patch(f"{API}/classes/curriculum/{link.json()['id']}", json={"teacher_id": None})
    row = await _row(campus, school, teacher["membership_id"])
    assert row["assigned_classes"] == []


async def test_rename_member(tenant: Tenant, mailbox: list[EmailMessage]) -> None:
    campus = await build_campus(tenant, mailbox, students=0)
    school = tenant.school_id
    teacher = await _add_teacher(campus, school)

    renamed = await campus.patch(
        f"{API}/schools/{school}/members/{teacher['membership_id']}",
        json={"full_name": "  Edited Name "},
    )
    assert renamed.status_code == 200, renamed.text
    assert renamed.json()["full_name"] == "Edited Name"

    blank = await campus.patch(
        f"{API}/schools/{school}/members/{teacher['membership_id']}",
        json={"full_name": "   "},
    )
    assert blank.status_code == 422, blank.text
