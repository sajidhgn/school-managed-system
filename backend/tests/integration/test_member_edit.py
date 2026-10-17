"""Editing a staff member from the members table: details, password, classes taught."""

from __future__ import annotations

from typing import Any

from app.common.email.sender import EmailMessage
from tests.integration.conftest import API, STRONG_PASSWORD, Tenant, latest_token
from tests.integration.test_academic_foundation import Campus, build_campus


async def _add_teacher(
    campus: Campus | Tenant,
    school_id: str,
    email: str = "edit.me@test.example",
    role_code: str = "teacher",
) -> dict[str, str]:
    roles = await campus.get(f"{API}/schools/{school_id}/roles")
    role_id = next(r["id"] for r in roles.json() if r["code"] == role_code)
    created = await campus.post(
        f"{API}/schools/{school_id}/members",
        json={
            "email": email,
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


NEW_PASSWORD = "fresh-lantern-orchard-519"


async def _login(tenant: Tenant, email: str, password: str) -> Any:
    tenant.client.cookies.clear()
    response = await tenant.client.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
        headers={"X-Token-Transport": "body"},
    )
    tenant.client.cookies.clear()
    return response


async def test_edit_member_email_and_phone(tenant: Tenant) -> None:
    school = tenant.school_id
    teacher = await _add_teacher(tenant, school)
    url = f"{API}/schools/{school}/members/{teacher['membership_id']}"

    edited = await tenant.patch(
        url, json={"email": "renamed@test.example", "phone": " 0300 1234567 "}
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["email"] == "renamed@test.example"
    assert edited.json()["phone"] == "0300 1234567"

    # The email is the sign-in name: the new one works, the old one is gone.
    assert (await _login(tenant, "renamed@test.example", STRONG_PASSWORD)).status_code == 200
    assert (await _login(tenant, "edit.me@test.example", STRONG_PASSWORD)).status_code == 401

    cleared = await tenant.patch(url, json={"phone": ""})
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["phone"] is None

    taken = await tenant.patch(url, json={"email": tenant.owner_email})
    assert taken.status_code == 409, taken.text
    assert taken.json()["code"] == "EMAIL_TAKEN"


async def test_reset_member_password_signs_them_out(tenant: Tenant) -> None:
    school = tenant.school_id
    teacher = await _add_teacher(tenant, school)
    url = f"{API}/schools/{school}/members/{teacher['membership_id']}"

    before = await _login(tenant, "edit.me@test.example", STRONG_PASSWORD)
    assert before.status_code == 200, before.text
    old_refresh = before.headers["X-Refresh-Token"]

    weak = await tenant.patch(url, json={"password": "short"})
    assert weak.status_code == 422, weak.text

    reset = await tenant.patch(url, json={"password": NEW_PASSWORD})
    assert reset.status_code == 200, reset.text

    assert (await _login(tenant, "edit.me@test.example", STRONG_PASSWORD)).status_code == 401
    assert (await _login(tenant, "edit.me@test.example", NEW_PASSWORD)).status_code == 200

    # The session that existed before the reset is dead.
    stale = await tenant.client.post(
        f"{API}/auth/refresh",
        headers={"X-Refresh-Token": old_refresh, "X-Token-Transport": "body"},
    )
    assert stale.status_code == 401, stale.text


async def test_cannot_reset_password_of_someone_with_more_access(tenant: Tenant) -> None:
    """Setting a password is signing in as that person -- bounded like granting a role."""
    school = tenant.school_id
    teacher_role = next(
        r
        for r in (await tenant.get(f"{API}/schools/{school}/roles")).json()
        if r["code"] == "teacher"
    )
    teacher_codes = (await tenant.get(f"{API}/schools/{school}/roles/{teacher_role['id']}")).json()
    limited = await tenant.post(
        f"{API}/schools/{school}/roles",
        json={
            "code": "staff_desk",
            "name": "Staff Desk",
            "permissions": sorted(
                {*teacher_codes["permissions"], "member:update", "member:reset_password"}
            ),
        },
    )
    assert limited.status_code == 201, limited.text

    await _add_teacher(tenant, school, email="desk@test.example", role_code="staff_desk")
    teacher = await _add_teacher(tenant, school, email="plain.teacher@test.example")
    accountant = await _add_teacher(
        tenant, school, email="money@test.example", role_code="accountant"
    )

    login = await _login(tenant, "desk@test.example", STRONG_PASSWORD)
    assert login.status_code == 200, login.text
    desk = {"Authorization": f"Bearer {login.headers['X-Access-Token']}"}
    members = f"{API}/schools/{school}/members"

    ok = await tenant.client.patch(
        f"{members}/{teacher['membership_id']}", json={"password": NEW_PASSWORD}, headers=desk
    )
    assert ok.status_code == 200, ok.text

    # The accountant holds fee permissions the desk role does not.
    refused = await tenant.client.patch(
        f"{members}/{accountant['membership_id']}", json={"password": NEW_PASSWORD}, headers=desk
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "PERMISSION_ESCALATION"

    no_email = await tenant.client.patch(
        f"{members}/{accountant['membership_id']}",
        json={"email": "hijack@test.example"},
        headers=desk,
    )
    assert no_email.status_code == 403, no_email.text


async def test_password_reset_needs_its_own_permission(tenant: Tenant) -> None:
    school = tenant.school_id
    editor = await tenant.post(
        f"{API}/schools/{school}/roles",
        json={"code": "editor", "name": "Editor", "permissions": ["member:read", "member:update"]},
    )
    assert editor.status_code == 201, editor.text
    await _add_teacher(tenant, school, email="editor@test.example", role_code="editor")
    target = await _add_teacher(tenant, school, email="target@test.example", role_code="editor")

    login = await _login(tenant, "editor@test.example", STRONG_PASSWORD)
    headers = {"Authorization": f"Bearer {login.headers['X-Access-Token']}"}
    response = await tenant.client.patch(
        f"{API}/schools/{school}/members/{target['membership_id']}",
        json={"password": NEW_PASSWORD},
        headers=headers,
    )
    assert response.status_code == 403, response.text
    assert "password" in response.json()["detail"]


async def test_cannot_reset_an_account_shared_with_another_organization(
    tenant: Tenant, make_tenant: Any, mailbox: list[EmailMessage]
) -> None:
    """The user row is global: resetting it here would open a login into another tenant."""
    school = tenant.school_id
    teacher = await _add_teacher(tenant, school, email="shared@test.example")

    other: Tenant = await make_tenant(
        name="Other Trust", email="other@test.example", school_code="OTHER"
    )
    roles = (await other.get(f"{API}/schools/{other.school_id}/roles")).json()
    invited = await other.post(
        f"{API}/schools/{other.school_id}/invitations",
        json={
            "email": "shared@test.example",
            "full_name": "Shared Person",
            "role_id": next(r["id"] for r in roles if r["code"] == "teacher"),
        },
    )
    assert invited.status_code == 201, invited.text
    token = latest_token(mailbox)
    login = await _login(tenant, "shared@test.example", STRONG_PASSWORD)
    accepted = await tenant.client.post(
        f"{API}/invitations/accept",
        json={"token": token},
        headers={"Authorization": f"Bearer {login.headers['X-Access-Token']}"},
    )
    assert accepted.status_code == 200, accepted.text
    tenant.client.cookies.clear()

    url = f"{API}/schools/{school}/members/{teacher['membership_id']}"
    for body in ({"password": NEW_PASSWORD}, {"email": "taken-over@test.example"}):
        response = await tenant.patch(url, json=body)
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "ACCOUNT_SHARED"

    # Contact details that are not sign-in details stay editable.
    phone = await tenant.patch(url, json={"phone": "0300 7654321"})
    assert phone.status_code == 200, phone.text
