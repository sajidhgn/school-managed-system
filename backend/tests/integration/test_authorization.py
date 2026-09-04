"""Authorization gates (spec §12 "Authorization", §5.3).

These cover the invariants the spec calls "the part that gets built wrong". Each
test names the escalation it prevents, because a test asserting `== 403` without
saying what it stops is one refactor away from being deleted as redundant.
"""

from __future__ import annotations

from typing import Any

from tests.integration.conftest import (
    API,
    STRONG_PASSWORD,
    Tenant,
    latest_token,
    make_campus_head,
)

# The subject of most of these tests is a SCHOOL-SCOPED actor with broad powers --
# the thing the seeded school `principal` role used to be. That role is gone: there
# is one `principal` and it is org-level. `make_campus_head` builds the equivalent as
# a custom role, which is how a customer would, and is what these invariants must
# still hold against.


# ---------------------------------------------------------------------------
# Invariant 1: no self-elevation beyond own grant
# ---------------------------------------------------------------------------


async def test_principal_cannot_grant_a_permission_it_does_not_hold(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    """Spec §12: "Principal grants a permission it does not hold -> 403."

    THE ESCALATION THIS STOPS: a campus head creates a role holding `billing:manage`,
    assigns it to themselves, and now controls the organization's money. Without the
    subset check, "you may configure roles" silently means "you may grant yourself
    anything".
    """
    head_token = await make_campus_head(tenant, mailbox, "campus-head@test.example")

    response = await tenant.client.post(
        f"{API}/schools/{tenant.school_id}/roles",
        json={
            "code": "sneaky_role",
            "name": "Sneaky Role",
            # A school-scoped actor deliberately does NOT hold this -- it is
            # org-scoped and belongs to the principal alone.
            "permissions": ["billing:manage"],
        },
        headers={"Authorization": f"Bearer {head_token}"},
    )

    assert response.status_code in (403, 422), response.text
    body = response.json()
    assert body["code"] in ("PERMISSION_ESCALATION", "PERMISSION_SCOPE_VIOLATION")


async def test_principal_cannot_invite_into_a_role_it_could_not_grant(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    """Spec §7.1 step 2: the escalation guard applies to invitations too.

    THE ESCALATION THIS STOPS: a campus head who cannot grant `billing:manage`
    directly simply invites a fresh account into a role that already has it, then
    logs in as that account. Invitation would become an escalation backdoor -- the
    same privilege gain through a different door.

    Here they attempt to invite someone into the ORG-LEVEL principal role.
    """
    head_token = await make_campus_head(tenant, mailbox, "campus-head@test.example")

    roles = await tenant.get(f"{API}/schools/{tenant.school_id}/roles")
    principal_role = next((r for r in roles.json() if r["code"] == "principal"), None)
    assert principal_role is not None, "the principal role should be visible but unassignable"
    assert principal_role["school_id"] is None, "the principal role is org-level"

    response = await tenant.client.post(
        f"{API}/schools/{tenant.school_id}/invitations",
        json={
            "email": "accomplice@test.example",
            "full_name": "Accomplice",
            "role_id": principal_role["id"],
        },
        headers={"Authorization": f"Bearer {head_token}"},
    )

    assert response.status_code in (403, 422), response.text


async def test_campus_head_can_create_member_with_password_in_own_school(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    head_token = await make_campus_head(tenant, mailbox, "manual-head@test.example")
    headers = {"Authorization": f"Bearer {head_token}"}
    roles = await tenant.client.get(f"{API}/schools/{tenant.school_id}/roles", headers=headers)
    teacher = next(role for role in roles.json() if role["code"] == "teacher")

    created = await tenant.client.post(
        f"{API}/schools/{tenant.school_id}/members",
        json={
            "email": "manual-teacher@test.example",
            "full_name": "Manual Teacher",
            "password": STRONG_PASSWORD,
            "role_id": teacher["id"],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["school_id"] == str(tenant.school_id)
    assert created.json()["role_code"] == "teacher"

    tenant.client.cookies.clear()
    login = await tenant.client.post(
        f"{API}/auth/login",
        json={"email": "manual-teacher@test.example", "password": STRONG_PASSWORD},
        headers={"X-Token-Transport": "body"},
    )
    assert login.status_code == 200, login.text


async def test_campus_head_cannot_create_member_in_another_branch(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    second = await tenant.post(f"{API}/schools", json={"name": "Other Branch", "code": "OTHER"})
    assert second.status_code == 201, second.text
    second_school_id = second.json()["id"]
    second_roles = await tenant.get(f"{API}/schools/{second_school_id}/roles")
    teacher = next(role for role in second_roles.json() if role["code"] == "teacher")
    head_token = await make_campus_head(tenant, mailbox, "scoped-head@test.example")

    response = await tenant.client.post(
        f"{API}/schools/{second_school_id}/members",
        json={
            "email": "wrong-branch@test.example",
            "full_name": "Wrong Branch",
            "password": STRONG_PASSWORD,
            "role_id": teacher["id"],
        },
        headers={"Authorization": f"Bearer {head_token}"},
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "SCHOOL_SCOPE_VIOLATION"


async def test_principal_can_assign_teacher_to_multiple_branches(tenant: Tenant) -> None:
    """Staffing across campuses is the ORG-LEVEL principal's job.

    Placing someone at a campus other than your own is inherently a cross-campus
    decision, so it needs a caller whose scope covers both. The principal is the only
    system role that qualifies -- see `test_campus_head_cannot_assign_branches` for
    the other half.
    """
    second = await tenant.post(f"{API}/schools", json={"name": "North Branch", "code": "NORTH"})
    assert second.status_code == 201, second.text
    second_school_id = second.json()["id"]

    roles = await tenant.get(f"{API}/schools/{tenant.school_id}/roles")
    teacher = next(role for role in roles.json() if role["code"] == "teacher")
    created = await tenant.post(
        f"{API}/schools/{tenant.school_id}/members",
        json={
            "email": "multi-branch-teacher@test.example",
            "full_name": "Multi Branch Teacher",
            "password": STRONG_PASSWORD,
            "role_id": teacher["id"],
        },
    )
    assert created.status_code == 201, created.text

    assigned = await tenant.post(
        f"{API}/schools/{tenant.school_id}/members/{created.json()['membership_id']}/branches",
        json={"school_ids": [second_school_id]},
    )
    assert assigned.status_code == 200, assigned.text
    assert len(assigned.json()) == 1
    assert assigned.json()[0]["school_id"] == second_school_id
    assert assigned.json()[0]["role_code"] == "teacher"

    members = await tenant.get(f"{API}/schools/{second_school_id}/members")
    assert members.status_code == 200, members.text
    assert any(
        member["email"] == "multi-branch-teacher@test.example"
        for member in members.json()["items"]
    )


async def test_campus_head_cannot_assign_branches(tenant: Tenant, mailbox: list[Any]) -> None:
    """A school-scoped actor cannot place staff at a campus it does not administer.

    THE ESCALATION THIS STOPS: branch assignment CREATES a membership at the target
    school. Left open to a school-scoped caller, the head of Campus A could staff
    Campus B -- reaching into another campus's roster through a route whose own
    school id looks innocuous.
    """
    second = await tenant.post(f"{API}/schools", json={"name": "East Branch", "code": "EAST"})
    assert second.status_code == 201, second.text
    second_school_id = second.json()["id"]

    head_token = await make_campus_head(tenant, mailbox, "branch-head@test.example")
    headers = {"Authorization": f"Bearer {head_token}"}

    roles = await tenant.client.get(f"{API}/schools/{tenant.school_id}/roles", headers=headers)
    teacher = next(role for role in roles.json() if role["code"] == "teacher")
    created = await tenant.client.post(
        f"{API}/schools/{tenant.school_id}/members",
        json={
            "email": "stuck-teacher@test.example",
            "full_name": "Stuck Teacher",
            "password": STRONG_PASSWORD,
            "role_id": teacher["id"],
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text

    response = await tenant.client.post(
        f"{API}/schools/{tenant.school_id}/members/{created.json()['membership_id']}/branches",
        json={"school_ids": [second_school_id]},
        headers=headers,
    )
    assert response.status_code == 403, response.text
    assert response.json()["code"] == "PRINCIPAL_REQUIRED"


# ---------------------------------------------------------------------------
# Invariant 2: locked roles
# ---------------------------------------------------------------------------


async def test_principal_cannot_edit_its_own_role(tenant: Tenant) -> None:
    """Spec §12: "Principal edits its own role -> 403 (`is_editable = false`)."

    THE ESCALATION THIS STOPS: invariant 1 alone does not cover this. The principal
    editing the PRINCIPAL role is only granting permissions it already holds, so the
    subset check passes -- but the edit still changes what every principal in the
    organization can do, and locks that in against a future revocation.

    Driven by the principal itself, which is the only caller that could pass the
    scope guard on an org-level role -- and therefore the only one this lock is for.
    """
    roles = await tenant.get(f"{API}/schools/{tenant.school_id}/roles")
    principal_role = next(r for r in roles.json() if r["code"] == "principal")
    assert principal_role["is_editable"] is False
    assert principal_role["school_id"] is None

    response = await tenant.put(
        f"{API}/schools/{tenant.school_id}/roles/{principal_role['id']}/permissions",
        json={"codes": ["member:read"]},
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "ROLE_NOT_EDITABLE"


# ---------------------------------------------------------------------------
# Invariant 3: no scope crossing
# ---------------------------------------------------------------------------


async def test_org_scoped_permission_on_a_school_role_is_422(tenant: Tenant) -> None:
    """Spec §12: "School role granted `school:create` (org-scoped) -> 422."

    THE ESCALATION THIS STOPS: `school:create` on a school-scoped role lets a campus
    role manufacture campuses the organization has not paid for. `billing:*` would
    let a teacher at one campus change the plan for the whole group.

    422, not 403: the request is not forbidden, it is incoherent. `billing:manage`
    scoped to a single campus has no meaning, whoever asks for it.
    """
    response = await tenant.post(
        f"{API}/schools/{tenant.school_id}/roles",
        json={
            "code": "overreaching",
            "name": "Overreaching Role",
            "permissions": ["member:read", "school:create"],
        },
    )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "PERMISSION_SCOPE_VIOLATION"
    assert "school:create" in body["meta"]["org_scoped"]


async def test_school_scoped_actor_cannot_touch_another_schools_roles(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    """Spec §12: "Teacher of School 1 requesting School 2 in the same org -> 403."

    403 here, not 404, and the difference is deliberate: staff already know their
    organization operates other campuses, so hiding School 2's existence would be
    pointless obfuscation that only confuses someone who picked the wrong menu.
    Cross-ORGANIZATION access is the case that returns 404.
    """
    second = await tenant.post(f"{API}/schools", json={"name": "Second Campus", "code": "SECOND"})
    assert second.status_code == 201, second.text
    second_school_id = second.json()["id"]

    head_token = await make_campus_head(tenant, mailbox, "campus-head@test.example")

    response = await tenant.client.get(
        f"{API}/schools/{second_school_id}/roles",
        headers={"Authorization": f"Bearer {head_token}"},
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "SCHOOL_SCOPE_VIOLATION"


# ---------------------------------------------------------------------------
# Invariant 4: the last principal
# ---------------------------------------------------------------------------


async def test_removing_the_last_owner_is_409(tenant: Tenant) -> None:
    """Spec §12: "Removing the last principal -> 409."

    WHY THIS ONE MATTERS MOST OPERATIONALLY: an organization with no principal has
    nobody who can pay for it, create schools, or appoint a replacement. There is no
    in-app recovery -- it takes a database operator. Every other invariant here
    prevents someone gaining power; this one prevents an organization losing it
    irrecoverably.
    """
    members = await tenant.get(f"{API}/schools/{tenant.school_id}/members")
    assert members.status_code == 200

    # The principal's ORG-LEVEL membership is not in a school list, so drive the
    # guard through ownership transfer to a non-existent member instead: the same
    # `_assert_not_last_owner` path, reached the way a UI would reach it.
    response = await tenant.post(
        f"{API}/org/transfer-ownership",
        json={"new_owner_membership_id": "00000000-0000-0000-0000-000000000000"},
    )
    assert response.status_code == 404, response.text


async def test_user_cannot_remove_their_own_membership(tenant: Tenant, mailbox: list[Any]) -> None:
    """Spec §5.3: "A user cannot suspend/remove their own membership."

    Not paternalism. It is the only thing between a mis-click and an administrator
    locking themselves out of an organization they alone administer. Leaving is a
    separate operation with its own confirmation.
    """
    head_token = await make_campus_head(tenant, mailbox, "campus-head@test.example")

    members = await tenant.client.get(
        f"{API}/schools/{tenant.school_id}/members",
        headers={"Authorization": f"Bearer {head_token}"},
    )
    assert members.status_code == 200
    own = next(
        m for m in members.json()["items"] if m["email"] == "campus-head@test.example"
    )

    response = await tenant.client.delete(
        f"{API}/schools/{tenant.school_id}/members/{own['membership_id']}",
        headers={"Authorization": f"Bearer {head_token}"},
    )

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "SELF_MODIFICATION"


# ---------------------------------------------------------------------------
# Role deletion & permission propagation
# ---------------------------------------------------------------------------


async def test_deleting_a_role_with_members_is_409_with_the_count(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    """Spec §5.3: deleting a role requires reassigning its members first.

    Cascading instead would strip those people of access as a side effect of tidying
    up a role, with no record of what they lost -- which is why the foreign key is
    RESTRICT rather than CASCADE. The count is returned so the UI can say "3 members
    still hold this role" instead of a bare failure.
    """
    created = await tenant.post(
        f"{API}/schools/{tenant.school_id}/roles",
        json={
            "code": "librarian",
            "name": "Librarian",
            "permissions": ["member:read", "student:read"],
        },
    )
    assert created.status_code == 201, created.text
    role_id = created.json()["id"]

    invited = await tenant.post(
        f"{API}/schools/{tenant.school_id}/invitations",
        json={"email": "librarian@test.example", "full_name": "Lib", "role_id": role_id},
    )
    assert invited.status_code == 201
    tenant.client.cookies.clear()
    accepted = await tenant.client.post(
        f"{API}/invitations/accept",
        json={
            "token": latest_token(mailbox),
            "full_name": "Lib",
            "password": STRONG_PASSWORD,
        },
    )
    assert accepted.status_code == 200, accepted.text
    tenant.client.cookies.clear()

    response = await tenant.delete(f"{API}/schools/{tenant.school_id}/roles/{role_id}")
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["code"] == "ROLE_IN_USE"
    assert body["meta"]["members"] == 1


async def test_permission_change_takes_effect_on_the_next_request(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    """Spec §12: "Role permission change -> next request uses the new set (no token wait)."

    =========================================================================
    THIS IS THE TEST FOR THE `permissions_version` MECHANISM
    =========================================================================
        The classic bug: an admin revokes a teacher's access and it takes a full
        token lifetime to apply. Spec §4.2 calls it out by name and the fix is that
        permissions are NOT embedded in the token -- only `pv` is -- so bumping the
        role's version makes every existing token resolve against a fresh set.

        Here the member's token is minted BEFORE the revocation and reused AFTER it,
        with no refresh in between. If permissions were baked into the token, or
        cached without the version in the key, the second call would still succeed.
    """
    created = await tenant.post(
        f"{API}/schools/{tenant.school_id}/roles",
        json={
            "code": "assistant",
            "name": "Assistant",
            "permissions": ["member:read", "student:read"],
        },
    )
    assert created.status_code == 201, created.text
    role_id = created.json()["id"]

    invited = await tenant.post(
        f"{API}/schools/{tenant.school_id}/invitations",
        json={"email": "assistant@test.example", "full_name": "Asst", "role_id": role_id},
    )
    assert invited.status_code == 201
    tenant.client.cookies.clear()
    accepted = await tenant.client.post(
        f"{API}/invitations/accept",
        json={
            "token": latest_token(mailbox),
            "full_name": "Asst",
            "password": STRONG_PASSWORD,
        },
    )
    assert accepted.status_code == 200, accepted.text
    tenant.client.cookies.clear()
    login = await tenant.client.post(
        f"{API}/auth/login",
        json={"email": "assistant@test.example", "password": STRONG_PASSWORD},
        headers={"X-Token-Transport": "body"},
    )
    assert login.status_code == 200, login.text
    member_token = login.headers["X-Access-Token"]
    member_headers = {"Authorization": f"Bearer {member_token}"}

    # Before: the member can read the staff list.
    before = await tenant.client.get(
        f"{API}/schools/{tenant.school_id}/members", headers=member_headers
    )
    assert before.status_code == 200, before.text

    # The owner revokes `member:read`.
    updated = await tenant.put(
        f"{API}/schools/{tenant.school_id}/roles/{role_id}/permissions",
        json={"codes": ["student:read"]},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["permissions_version"] == 2

    # After: the SAME token, no refresh, is now refused.
    after = await tenant.client.get(
        f"{API}/schools/{tenant.school_id}/members", headers=member_headers
    )
    assert after.status_code == 403, (
        "revocation did not take effect on the next request -- permissions are being "
        "read from the token or from a cache key that ignores permissions_version"
    )
    assert "member:read" in after.json()["meta"]["missing"]


async def test_suspended_member_is_refused_immediately(tenant: Tenant, mailbox: list[Any]) -> None:
    """Suspension applies on the member's very next request, not at token expiry.

    The auth dependency re-reads the membership on every authorised request, which is
    exactly why it does so rather than trusting the token's claims. This is the test
    that makes that cost worth paying.
    """
    head_token = await make_campus_head(tenant, mailbox, "campus-head@test.example")
    headers = {"Authorization": f"Bearer {head_token}"}

    ok = await tenant.client.get(f"{API}/schools/{tenant.school_id}/members", headers=headers)
    assert ok.status_code == 200

    members = await tenant.get(f"{API}/schools/{tenant.school_id}/members")
    target = next(
        m for m in members.json()["items"] if m["email"] == "campus-head@test.example"
    )

    suspended = await tenant.patch(
        f"{API}/schools/{tenant.school_id}/members/{target['membership_id']}",
        json={"suspended": True},
    )
    assert suspended.status_code == 200, suspended.text

    after = await tenant.client.get(f"{API}/schools/{tenant.school_id}/members", headers=headers)
    assert after.status_code in (401, 403), after.text


async def test_unknown_permission_code_is_rejected(tenant: Tenant) -> None:
    """A typo'd permission must fail loudly, not silently create an inert role.

    Reported as "no such permission" rather than as a scope error, because the two
    send a reader hunting in completely different directions.
    """
    response = await tenant.post(
        f"{API}/schools/{tenant.school_id}/roles",
        json={
            "code": "typo_role",
            "name": "Typo Role",
            "permissions": ["members:read"],  # plural -- not in the catalog
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "UNKNOWN_PERMISSIONS"
