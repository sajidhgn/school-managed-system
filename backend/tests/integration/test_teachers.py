"""`GET /schools/{id}/teachers` -- the list behind the class-teacher picker.

WHAT THESE TESTS ARE REALLY DEFENDING
    The endpoint answers "who may I put in front of this class", and it answers it by
    asking what a role can DO, not what it is CALLED. That distinction is invisible in
    a fixture where the only teaching role is the seeded one named "teacher" -- it
    passes just as well under a `role.code == "teacher"` implementation. So the custom
    role test below deliberately builds a teaching role with an unrelated code and
    name, which is the case that separates the two implementations.
"""

from __future__ import annotations

from typing import Any

from tests.integration.conftest import API, STRONG_PASSWORD, Tenant


async def _role_id(tenant: Tenant, school_id: str, code: str) -> str:
    roles = await tenant.get(f"{API}/schools/{school_id}/roles")
    assert roles.status_code == 200, roles.text
    return str(next(r for r in roles.json() if r["code"] == code)["id"])


async def _add_member(
    tenant: Tenant, school_id: str, *, email: str, name: str, role_id: str
) -> dict[str, Any]:
    created = await tenant.post(
        f"{API}/schools/{school_id}/members",
        json={
            "email": email,
            "full_name": name,
            "password": STRONG_PASSWORD,
            "role_id": role_id,
        },
    )
    assert created.status_code == 201, created.text
    return dict(created.json())


async def test_lists_teachers_and_excludes_non_teaching_staff(tenant: Tenant) -> None:
    """A teacher appears; an accountant does not.

    The accountant is the control. They hold `student:read` and `class:read` -- plenty
    of academic access -- so any implementation that filtered on "can see the class"
    rather than "runs the classroom" would wrongly include them.
    """
    school = tenant.school_id
    teacher_role = await _role_id(tenant, school, "teacher")
    accountant_role = await _role_id(tenant, school, "accountant")

    await _add_member(
        tenant, school, email="t1@test.example", name="Real Teacher", role_id=teacher_role
    )
    await _add_member(
        tenant, school, email="a1@test.example", name="Book Keeper", role_id=accountant_role
    )

    response = await tenant.get(f"{API}/schools/{school}/teachers")
    assert response.status_code == 200, response.text
    emails = {row["email"] for row in response.json()}

    assert "t1@test.example" in emails
    assert "a1@test.example" not in emails


async def test_excludes_the_org_level_principal(tenant: Tenant) -> None:
    """The principal holds every permission, teaching ones included, and must still
    not show up in a list of teachers.

    Nothing filters them out by name. They are excluded structurally: their membership
    is org-level (`school_id IS NULL`) and the query asks for members OF THE BRANCH.
    This test exists because that is a load-bearing side effect of the scoping rather
    than an explicit rule, and a future rewrite that widened the query to
    `school_id IS NULL OR school_id = :id` would reintroduce them silently.
    """
    response = await tenant.get(f"{API}/schools/{tenant.school_id}/teachers")
    assert response.status_code == 200, response.text
    assert tenant.owner_email not in {row["email"] for row in response.json()}


async def test_includes_a_custom_teaching_role(tenant: Tenant) -> None:
    """THE TEST THAT PINS THE DESIGN.

    "Head of Curriculum" shares no substring with "teacher" in either its code or its
    name. It is in the list purely because its permissions say it runs a classroom.
    """
    school = tenant.school_id
    role = await tenant.post(
        f"{API}/schools/{school}/roles",
        json={
            "code": "head_of_curriculum",
            "name": "Head of Curriculum",
            "permissions": ["class:read", "student:read", "attendance:mark"],
        },
    )
    assert role.status_code == 201, role.text

    await _add_member(
        tenant,
        school,
        email="hoc@test.example",
        name="Curriculum Head",
        role_id=role.json()["id"],
    )

    response = await tenant.get(f"{API}/schools/{school}/teachers")
    assert response.status_code == 200, response.text
    row = next(r for r in response.json() if r["email"] == "hoc@test.example")
    # The role name rides along so the picker can tell two same-named people apart.
    assert row["role_name"] == "Head of Curriculum"


async def test_scoped_to_one_branch(tenant: Tenant) -> None:
    """A teacher at the second campus must not be offerable as class teacher at the
    first. Naming them would produce a section nobody on site can take a register for.
    """
    second = await tenant.post(f"{API}/schools", json={"name": "Second", "code": "SECOND"})
    assert second.status_code == 201, second.text
    second_id = second.json()["id"]

    await _add_member(
        tenant,
        second_id,
        email="branch2@test.example",
        name="Other Campus Teacher",
        role_id=await _role_id(tenant, second_id, "teacher"),
    )

    first = await tenant.get(f"{API}/schools/{tenant.school_id}/teachers")
    assert first.status_code == 200, first.text
    assert "branch2@test.example" not in {row["email"] for row in first.json()}

    other = await tenant.get(f"{API}/schools/{second_id}/teachers")
    assert other.status_code == 200, other.text
    assert "branch2@test.example" in {row["email"] for row in other.json()}


async def test_excludes_suspended_teachers(tenant: Tenant) -> None:
    """Suspending someone removes them from the picker.

    Only from the PICKER. A section that already names them keeps naming them -- see
    `list_teaching_staff`. Suspension stops new assignments; it does not silently
    strip the register from a class that still meets tomorrow.
    """
    school = tenant.school_id
    member = await _add_member(
        tenant,
        school,
        email="suspended@test.example",
        name="Suspended Teacher",
        role_id=await _role_id(tenant, school, "teacher"),
    )

    patched = await tenant.patch(
        f"{API}/schools/{school}/members/{member['membership_id']}",
        json={"suspended": True},
    )
    assert patched.status_code == 200, patched.text

    response = await tenant.get(f"{API}/schools/{school}/teachers")
    assert response.status_code == 200, response.text
    assert "suspended@test.example" not in {row["email"] for row in response.json()}


async def test_requires_authentication(tenant: Tenant) -> None:
    response = await tenant.client.get(f"{API}/schools/{tenant.school_id}/teachers")
    assert response.status_code == 401, response.text
