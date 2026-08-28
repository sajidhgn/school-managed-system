"""Ids resolved to names on the screens that print them.

WHY THESE ARE WORTH TESTING AT ALL
    Every field here is "just for display", which is exactly why it breaks quietly. A
    name that silently becomes null does not raise, does not 500 and does not fail a
    type check -- it renders as an empty cell, and an empty cell reads as "nobody is
    assigned" rather than "the join stopped working". These tests are the difference
    between those two.

    Each one also pins the NULL case, because on all three screens "blank" is a real
    state with a real meaning -- an unassigned section, an applicant with no seat --
    and a change that made blank impossible would be just as wrong as one that made
    it universal.
"""

from __future__ import annotations

from typing import Any

from tests.integration.conftest import API, STRONG_PASSWORD, Tenant
from tests.integration.test_academic_foundation import Campus, build_campus


async def _a_teacher(campus: Campus, tenant: Tenant) -> dict[str, Any]:
    """One member of the campus who is teaching staff, created through the API."""
    roles = await campus.get(f"{API}/schools/{tenant.school_id}/roles")
    assert roles.status_code == 200, roles.text
    teacher_role = next(r for r in roles.json() if r["code"] == "teacher")

    created = await campus.post(
        f"{API}/schools/{tenant.school_id}/members",
        json={
            "email": "labelled.teacher@test.example",
            "full_name": "Labelled Teacher",
            "password": STRONG_PASSWORD,
            "role_id": teacher_role["id"],
        },
    )
    assert created.status_code == 201, created.text
    return dict(created.json())


# ---------------------------------------------------------------------------
# Classes screen: section -> class teacher
# ---------------------------------------------------------------------------


async def test_class_summary_names_the_class_teacher(tenant: Tenant, mailbox: list[Any]) -> None:
    campus = await build_campus(tenant, mailbox)
    teacher = await _a_teacher(campus, tenant)

    before = await campus.get(f"{API}/classes/summary")
    assert before.status_code == 200, before.text
    section = before.json()[0]["sections"][0]
    # Unassigned is null, not "" or "Unassigned" -- the UI decides how to print it.
    assert section["class_teacher_id"] is None
    assert section["class_teacher_name"] is None

    patched = await campus.patch(
        f"{API}/classes/sections/{campus.section_id}",
        json={"class_teacher_id": teacher["user_id"]},
    )
    assert patched.status_code == 200, patched.text

    after = await campus.get(f"{API}/classes/summary")
    assert after.status_code == 200, after.text
    section = after.json()[0]["sections"][0]
    assert section["class_teacher_id"] == teacher["user_id"]
    assert section["class_teacher_name"] == "Labelled Teacher"


# ---------------------------------------------------------------------------
# Attendance screen: the chase list names who to chase
# ---------------------------------------------------------------------------


async def test_daily_overview_names_the_class_teacher(tenant: Tenant, mailbox: list[Any]) -> None:
    """The name has to be there on a row with NO register.

    That is the whole point: the rows worth chasing are the ones where nothing has
    happened, so a label that only appeared once a register existed would be missing
    from every row that needs it.
    """
    campus = await build_campus(tenant, mailbox)
    teacher = await _a_teacher(campus, tenant)
    assigned = await campus.patch(
        f"{API}/classes/sections/{campus.section_id}",
        json={"class_teacher_id": teacher["user_id"]},
    )
    assert assigned.status_code == 200, assigned.text

    overview = await campus.get(f"{API}/attendance/today")
    assert overview.status_code == 200, overview.text
    row = next(r for r in overview.json()["sections"] if r["section_id"] == campus.section_id)

    assert row["session_id"] is None, "no register opened -- this is the chase case"
    assert row["class_teacher_name"] == "Labelled Teacher"


async def test_daily_overview_leaves_an_unassigned_section_null(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    campus = await build_campus(tenant, mailbox)

    overview = await campus.get(f"{API}/attendance/today")
    assert overview.status_code == 200, overview.text
    row = next(r for r in overview.json()["sections"] if r["section_id"] == campus.section_id)

    assert row["class_teacher_id"] is None
    assert row["class_teacher_name"] is None


# ---------------------------------------------------------------------------
# Students screen: where the child sits
# ---------------------------------------------------------------------------


async def test_student_list_names_class_and_section(tenant: Tenant, mailbox: list[Any]) -> None:
    campus = await build_campus(tenant, mailbox)

    listed = await campus.get(f"{API}/students")
    assert listed.status_code == 200, listed.text
    rows = listed.json()["items"]
    assert rows, "fixture enrolls students"

    for row in rows:
        assert row["class_name"] == "Grade 9"
        assert row["section_name"] == "A"


async def test_a_student_detail_names_class_and_section(tenant: Tenant, mailbox: list[Any]) -> None:
    """The single-record path resolves the same labels as the list path.

    Separate from the list test because they run through different code: the list
    resolves every section on the page at once, the detail resolves one. A refactor
    that fixed the N+1 by moving the lookup into the list would leave this one
    returning nulls, and nothing else would notice.
    """
    campus = await build_campus(tenant, mailbox)

    fetched = await campus.get(f"{API}/students/{campus.student_ids[0]}")
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["class_name"] == "Grade 9"
    assert fetched.json()["section_name"] == "A"


async def test_an_applicant_with_no_seat_has_no_class(tenant: Tenant, mailbox: list[Any]) -> None:
    """An admission is accepted before a section is chosen. That gap is a state to
    render, not a failure -- so both labels are null rather than absent or empty."""
    campus = await build_campus(tenant, mailbox)

    created = await campus.post(
        f"{API}/students",
        json={
            "admission_number": "2026-999",
            "first_name": "Unseated",
            "last_name": "Applicant",
            "guardian_name": "Parent Test",
            "guardian_phone": "03001119999",
        },
    )
    assert created.status_code == 201, created.text
    assert created.json()["section_id"] is None
    assert created.json()["class_name"] is None
    assert created.json()["section_name"] is None
