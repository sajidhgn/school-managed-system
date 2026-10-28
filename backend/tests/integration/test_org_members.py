"""The Members module's org-wide list: `GET /org/members`.

The principal opens Members without first choosing a campus, so the list spans every
branch and a branch is a filter, not a precondition. A school-scoped administrator
reaching the same route still sees only their own branch.
"""

from __future__ import annotations

from app.common.email.sender import EmailMessage
from tests.integration.conftest import API, STRONG_PASSWORD, Tenant, make_campus_head


async def _add_member(
    tenant: Tenant,
    school_id: str,
    email: str,
    full_name: str = "Branch Teacher",
    role_code: str = "teacher",
) -> dict[str, str]:
    roles = await tenant.get(f"{API}/schools/{school_id}/roles")
    role_id = next(r["id"] for r in roles.json() if r["code"] == role_code)
    created = await tenant.post(
        f"{API}/schools/{school_id}/members",
        json={
            "email": email,
            "full_name": full_name,
            "password": STRONG_PASSWORD,
            "role_id": role_id,
        },
    )
    assert created.status_code == 201, created.text
    return dict(created.json())


async def _second_school(tenant: Tenant) -> str:
    second = await tenant.post(f"{API}/schools", json={"name": "Second", "code": "SECOND"})
    assert second.status_code == 201, second.text
    return str(second.json()["id"])


async def test_principal_lists_every_branch_and_can_filter_to_one(tenant: Tenant) -> None:
    second_id = await _second_school(tenant)
    first = await _add_member(tenant, tenant.school_id, "first@test.example")
    second = await _add_member(tenant, second_id, "second@test.example")

    everyone = await tenant.get(f"{API}/org/members?size=100")
    assert everyone.status_code == 200, everyone.text
    rows = {m["email"]: m for m in everyone.json()["items"]}
    assert rows["first@test.example"]["school_id"] == tenant.school_id
    assert rows["second@test.example"]["school_id"] == second_id
    # The principal's own org-level membership is part of the organization's staff.
    assert rows[tenant.owner_email]["school_id"] is None
    assert rows[tenant.owner_email]["role_code"] == "principal"

    narrowed = await tenant.get(f"{API}/org/members?school_id={second_id}&size=100")
    assert narrowed.status_code == 200, narrowed.text
    assert [m["membership_id"] for m in narrowed.json()["items"]] == [second["membership_id"]]
    assert first["membership_id"] not in {m["membership_id"] for m in narrowed.json()["items"]}


async def test_open_campus_does_not_narrow_the_org_list(tenant: Tenant) -> None:
    """The campus picker narrows the campus modules, not Members: that is what makes
    the module usable straight after sign-in, before -- or regardless of -- a pick."""
    second_id = await _second_school(tenant)
    await _add_member(tenant, second_id, "elsewhere@test.example")

    tenant.active_school_id = tenant.school_id
    response = await tenant.get(f"{API}/org/members?size=100")
    assert response.status_code == 200, response.text
    assert "elsewhere@test.example" in {m["email"] for m in response.json()["items"]}


async def test_school_scoped_caller_sees_only_own_branch(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    second_id = await _second_school(tenant)
    await _add_member(tenant, second_id, "other.branch@test.example")
    token = await make_campus_head(tenant, mailbox, "head@test.example")
    headers = {"Authorization": f"Bearer {token}"}

    own = await tenant.client.get(f"{API}/org/members?size=100", headers=headers)
    assert own.status_code == 200, own.text
    assert {m["school_id"] for m in own.json()["items"]} == {tenant.school_id}

    other = await tenant.client.get(f"{API}/org/members?school_id={second_id}", headers=headers)
    assert other.status_code == 403, other.text
    assert other.json()["code"] == "SCHOOL_SCOPE_VIOLATION"


async def test_filters_by_name_role_and_branch(tenant: Tenant) -> None:
    second_id = await _second_school(tenant)
    await _add_member(tenant, tenant.school_id, "fatima.noor@test.example", "Fatima Noor")
    await _add_member(tenant, second_id, "bilal.shah@test.example", "Bilal Shah")
    await _add_member(
        tenant, tenant.school_id, "accounts@test.example", "Fatima Accounts", "accountant"
    )

    async def emails(query: str) -> set[str]:
        response = await tenant.get(f"{API}/org/members?size=100&{query}")
        assert response.status_code == 200, response.text
        return {m["email"] for m in response.json()["items"]}

    # Name, case-insensitively and anywhere in it; and email.
    assert await emails("q=FATIMA") == {"fatima.noor@test.example", "accounts@test.example"}
    assert await emails("q=accounts%40") == {"accounts@test.example"}
    # By role CODE: every branch has its own `teacher` row, and both are teachers.
    assert await emails("role=teacher") == {"fatima.noor@test.example", "bilal.shah@test.example"}
    # Filters combine.
    assert await emails("role=teacher&q=fatima") == {"fatima.noor@test.example"}
    assert await emails(f"role=teacher&school_id={second_id}") == {"bilal.shah@test.example"}
    # LIKE wildcards in the term are literal, not "match everything".
    assert await emails("q=%25") == set()
    assert await emails("q=_") == set()

    total = await tenant.get(f"{API}/org/members?role=teacher&size=1")
    assert total.json()["meta"]["total"] == 2


async def test_org_invitations_are_filtered_and_paged_in_the_database(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    second_id = await _second_school(tenant)

    async def invite(school_id: str, email: str) -> dict[str, str]:
        roles = await tenant.get(f"{API}/schools/{school_id}/roles")
        role_id = next(r["id"] for r in roles.json() if r["code"] == "teacher")
        sent = await tenant.post(
            f"{API}/schools/{school_id}/invitations", json={"email": email, "role_id": role_id}
        )
        assert sent.status_code == 201, sent.text
        return dict(sent.json())

    first = await invite(tenant.school_id, "one@test.example")
    await invite(second_id, "two@test.example")
    await invite(second_id, "three@test.example")
    revoked = await tenant.delete(f"{API}/schools/{tenant.school_id}/invitations/{first['id']}")
    assert revoked.status_code == 200, revoked.text

    async def emails(query: str = "") -> set[str]:
        response = await tenant.get(f"{API}/org/invitations?size=100&{query}")
        assert response.status_code == 200, response.text
        return {i["email"] for i in response.json()["items"]}

    assert await emails() == {"one@test.example", "two@test.example", "three@test.example"}
    assert await emails(f"school_id={second_id}") == {"two@test.example", "three@test.example"}
    assert await emails("status=pending") == {"two@test.example", "three@test.example"}
    assert await emails("status=revoked") == {"one@test.example"}

    page = (await tenant.get(f"{API}/org/invitations?size=2&page=2")).json()
    assert len(page["items"]) == 1
    assert page["meta"]["total"] == 3
