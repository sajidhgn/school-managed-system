"""Global search release gate.

WHAT THESE PROVE
    Search is the one endpoint in the product that reads from every module at once.
    That makes it the easiest place for a scoping mistake to become a cross-campus
    or cross-tenant leak, and the easiest place for a permission to be forgotten --
    because a forgotten permission here does not 403, it just quietly returns rows.

    So the cases below are weighted towards the boundary rather than the behaviour:

      * a role sees exactly the entity kinds its permissions allow, and no others
      * a campus-scoped member cannot widen their own scope with `school:all`
      * another tenant's identically-named records never appear

    Everything runs through the app's own `sms_app` connection (NOBYPASSRLS), so
    the tenant boundary is PostgreSQL's policies rather than an application filter.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from app.common.email.sender import EmailMessage
from tests.integration.conftest import (
    API,
    STRONG_PASSWORD,
    Tenant,
    latest_token,
    make_campus_head,
)

SEARCH = f"{API}/search"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def make_actor(
    tenant: Tenant,
    mailbox: list[EmailMessage],
    email: str,
    permissions: list[str],
    *,
    code: str,
    school_id: str | None = None,
) -> str:
    """A school-scoped member holding EXACTLY `permissions`. Returns their token.

    Built through the public role editor and invitation flow rather than by
    inserting rows, so the actor these tests reason about is one a customer could
    actually create.
    """
    role = await tenant.post(
        f"{API}/schools/{school_id or tenant.school_id}/roles",
        json={"code": code, "name": code.replace("_", " ").title(), "permissions": permissions},
    )
    assert role.status_code == 201, role.text

    invited = await tenant.post(
        f"{API}/schools/{school_id or tenant.school_id}/invitations",
        json={"email": email, "full_name": "Search Actor", "role_id": role.json()["id"]},
    )
    assert invited.status_code == 201, invited.text

    tenant.client.cookies.clear()
    accepted = await tenant.client.post(
        f"{API}/invitations/accept",
        json={
            "token": latest_token(mailbox),
            "full_name": "Search Actor",
            "password": STRONG_PASSWORD,
        },
    )
    assert accepted.status_code == 200, accepted.text
    tenant.client.cookies.clear()

    login = await tenant.client.post(
        f"{API}/auth/login",
        json={"email": email, "password": STRONG_PASSWORD},
        headers={"X-Token-Transport": "body"},
    )
    assert login.status_code == 200, login.text
    tenant.client.cookies.clear()
    return str(login.headers["X-Access-Token"])


async def seed_directory(tenant: Tenant) -> dict[str, Any]:
    """A class, a section, and three students with deliberately overlapping names.

    The overlap is the point: "Muhammad Ali" and "Ali Hassan" both contain "ali",
    so a test asserting on ranking has something to rank, and a test asserting on
    exclusion has something to exclude.
    """
    created_class = await tenant.post(f"{API}/classes", json={"name": "Grade 10", "level": 10})
    assert created_class.status_code == 201, created_class.text
    class_id = created_class.json()["id"]

    section = await tenant.post(
        f"{API}/classes/{class_id}/sections", json={"name": "A", "capacity": 30}
    )
    assert section.status_code == 201, section.text
    section_id = section.json()["id"]

    students = {}
    for admission, first, last, status, guardian in (
        ("2026-001", "Muhammad", "Ali", "active", "Bilal Ali"),
        ("2026-002", "Ali", "Hassan", "active", "Nadia Hassan"),
        ("2026-003", "Zainab", "Khan", "pending", "Imran Khan"),
    ):
        response = await tenant.post(
            f"{API}/students",
            json={
                "admission_number": admission,
                "first_name": first,
                "last_name": last,
                "status": status,
                "section_id": section_id if status == "active" else None,
                "guardian_name": guardian,
                "guardian_phone": "+92300" + admission[-4:],
            },
        )
        assert response.status_code == 201, response.text
        students[admission] = response.json()["id"]

    return {"class_id": class_id, "section_id": section_id, "students": students}


def group(payload: dict[str, Any], entity: str) -> dict[str, Any] | None:
    return next((g for g in payload["groups"] if g["type"] == entity), None)


def titles(payload: dict[str, Any], entity: str) -> list[str]:
    found = group(payload, entity)
    return [hit["title"] for hit in found["hits"]] if found else []


# ---------------------------------------------------------------------------
# Role-scoped results -- the property the whole design rests on
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_returns_only_entity_kinds_the_role_may_read(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Two roles, one query, different sets of TYPES -- not just different rows.

    This is the difference between a search that filters results after the fact and
    one that never queries what the caller cannot see. A teacher-shaped role holds
    no `fee:read`, so `voucher` must be absent from `searched_types` entirely --
    proving the provider was skipped rather than queried and filtered.
    """
    tenant.active_school_id = tenant.school_id
    await seed_directory(tenant)

    principal = await tenant.get(SEARCH, params={"q": "ali"})
    assert principal.status_code == 200, principal.text
    principal_types = set(principal.json()["searched_types"])
    assert {"student", "member", "voucher", "role"} <= principal_types

    teacher_token = await make_actor(
        tenant,
        mailbox,
        "teacher@test.example",
        ["student:read", "class:read", "member:read", "school:read"],
        code="teacher_like",
    )
    teacher = await tenant.client.get(
        SEARCH, params={"q": "ali"}, headers={"Authorization": f"Bearer {teacher_token}"}
    )
    assert teacher.status_code == 200, teacher.text
    teacher_types = set(teacher.json()["searched_types"])

    assert "student" in teacher_types
    # The money, the access configuration and the audit trail are not part of a
    # teacher's product at all.
    assert teacher_types.isdisjoint({"voucher", "fee_head", "fee_structure", "role", "audit"})
    assert teacher_types < principal_types


@pytest.mark.asyncio
async def test_type_filter_naming_a_forbidden_type_finds_nothing(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """`type:role` from a role that cannot read roles returns no rows and a warning.

    And the warning says "unknown or unavailable" without distinguishing the two,
    so the search box cannot be used to enumerate which permissions the caller is
    missing.
    """
    tenant.active_school_id = tenant.school_id
    await seed_directory(tenant)

    token = await make_actor(
        tenant, mailbox, "narrow@test.example", ["student:read"], code="students_only"
    )
    response = await tenant.client.get(
        SEARCH,
        params={"q": "type:role principal"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["groups"] == []
    assert payload["searched_types"] == []
    assert any("Unknown or unavailable type" in warning for warning in payload["warnings"])


@pytest.mark.asyncio
async def test_config_describes_a_different_box_per_role(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """`/search/config` is what makes the UI role-aware without shipping the catalog.

    The principal's scope list leads with people and campuses; a fee-shaped role's
    leads with vouchers. Both come from the same endpoint and the same permission
    set -- the frontend holds no table of its own.
    """
    tenant.active_school_id = tenant.school_id

    principal = await tenant.get(f"{SEARCH}/config")
    assert principal.status_code == 200, principal.text
    principal_config = principal.json()
    assert principal_config["cross_school_available"] is True

    token = await make_actor(
        tenant,
        mailbox,
        "cashier@test.example",
        ["fee:read", "fee:collect", "student:read"],
        code="cashier",
    )
    cashier = await tenant.client.get(
        f"{SEARCH}/config", headers={"Authorization": f"Bearer {token}"}
    )
    assert cashier.status_code == 200, cashier.text
    cashier_config = cashier.json()

    cashier_scopes = [scope["type"] for scope in cashier_config["scopes"]]
    assert cashier_scopes[0] == "voucher", cashier_scopes
    assert "role" not in cashier_scopes
    # A campus-scoped member cannot widen their scope, so the UI must not offer it.
    assert cashier_config["cross_school_available"] is False
    assert any("type:voucher" in example for example in cashier_config["examples"])


# ---------------------------------------------------------------------------
# The query language
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_filter_and_exclusion_narrow_the_result_set(tenant: Tenant) -> None:
    tenant.active_school_id = tenant.school_id
    await seed_directory(tenant)

    pending = await tenant.get(SEARCH, params={"q": "type:student status:pending"})
    assert pending.status_code == 200, pending.text
    assert titles(pending.json(), "student") == ["Zainab Khan"]

    # "ali" matches both Muhammad Ali and Ali Hassan; `-hassan` drops the second.
    excluded = await tenant.get(SEARCH, params={"q": "type:student ali -hassan"})
    assert titles(excluded.json(), "student") == ["Muhammad Ali"]


@pytest.mark.asyncio
async def test_status_value_from_another_module_matches_nothing_here(tenant: Tenant) -> None:
    """`status:paid` is a voucher status; against students it must return zero rows.

    The alternative -- ignoring a filter a provider does not understand -- would
    dump the whole student directory into a search that plainly meant vouchers.
    """
    tenant.active_school_id = tenant.school_id
    await seed_directory(tenant)

    response = await tenant.get(SEARCH, params={"q": "type:student status:paid ali"})
    assert response.status_code == 200, response.text
    assert group(response.json(), "student") is None


@pytest.mark.asyncio
async def test_unknown_filter_is_searched_as_text_and_warned_about(tenant: Tenant) -> None:
    """A colon in a search term must never be a 400.

    Guardians' email addresses and note fields contain colons; erroring on them
    would make the box refuse perfectly reasonable input.
    """
    tenant.active_school_id = tenant.school_id
    await seed_directory(tenant)

    response = await tenant.get(SEARCH, params={"q": "nonsense:value"})
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["parsed"]["terms"] == ["nonsense:value"]
    assert any("Not a filter" in warning for warning in payload["warnings"])


@pytest.mark.asyncio
async def test_empty_query_is_an_empty_result_not_an_error(tenant: Tenant) -> None:
    """The omnibar calls this as the user clears the box."""
    tenant.active_school_id = tenant.school_id

    for params in ({}, {"q": ""}, {"q": "   "}):
        response = await tenant.get(SEARCH, params=params)
        assert response.status_code == 200, response.text
        assert response.json()["groups"] == []


@pytest.mark.asyncio
async def test_fuzzy_matching_survives_a_misspelling(tenant: Tenant) -> None:
    """`muhamad` finds `Muhammad` -- the reason pg_trgm is in the query at all.

    Transliterated names are spelled inconsistently by the people typing them, and
    a search that only does substrings is useless for exactly the names a school
    office looks up most.
    """
    tenant.active_school_id = tenant.school_id
    await seed_directory(tenant)

    response = await tenant.get(SEARCH, params={"q": "type:student muhamad"})
    assert response.status_code == 200, response.text
    assert "Muhammad Ali" in titles(response.json(), "student")


@pytest.mark.asyncio
async def test_exact_match_outranks_a_partial_one(tenant: Tenant) -> None:
    """Ranking, end to end: the student actually named "Ali" comes first."""
    tenant.active_school_id = tenant.school_id
    await seed_directory(tenant)

    response = await tenant.get(SEARCH, params={"q": "type:student ali"})
    assert response.status_code == 200, response.text
    found = titles(response.json(), "student")
    assert found[0] == "Ali Hassan", found


@pytest.mark.asyncio
async def test_hit_carries_a_deep_link_and_its_matched_field(tenant: Tenant) -> None:
    tenant.active_school_id = tenant.school_id
    seeded = await seed_directory(tenant)

    response = await tenant.get(SEARCH, params={"q": "type:student 2026-002"})
    assert response.status_code == 200, response.text
    hit = group(response.json(), "student")["hits"][0]

    assert hit["url"] == f"/students/{seeded['students']['2026-002']}"
    assert hit["subtitle"] == "2026-002"
    assert hit["matched_on"] == "subtitle"
    assert hit["context"] == "Grade 10 — A"


@pytest.mark.asyncio
async def test_a_match_on_a_hidden_field_reports_no_matched_field(tenant: Tenant) -> None:
    """Searching a guardian's phone finds the student, and says the match is elsewhere.

    `matched_on: null` is what lets the UI explain a result whose visible text does
    not contain the search term -- otherwise the row looks like a bug.
    """
    tenant.active_school_id = tenant.school_id
    await seed_directory(tenant)

    response = await tenant.get(SEARCH, params={"q": "type:student +923000002"})
    assert response.status_code == 200, response.text
    hits = group(response.json(), "student")["hits"]
    assert hits[0]["title"] == "Ali Hassan"
    assert hits[0]["matched_on"] is None


@pytest.mark.asyncio
async def test_suggest_ranks_the_same_way_as_search(tenant: Tenant) -> None:
    tenant.active_school_id = tenant.school_id
    await seed_directory(tenant)

    suggestions = await tenant.get(f"{SEARCH}/suggest", params={"q": "ali"})
    assert suggestions.status_code == 200, suggestions.text
    rows = suggestions.json()
    assert rows, rows

    full = await tenant.get(SEARCH, params={"q": "ali"})
    best = max(
        (hit for g in full.json()["groups"] for hit in g["hits"]),
        key=lambda hit: hit["score"],
    )
    assert rows[0]["id"] == best["id"]


# ---------------------------------------------------------------------------
# Scope -- campus and tenant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_campus_scoped_member_cannot_widen_scope_with_school_all(
    make_tenant: Callable[..., Any], mailbox: list[EmailMessage]
) -> None:
    """`school:all` from a campus-scoped member is acknowledged and NOT honoured.

    The single most important negative case in the module: the widening operator is
    ordinary text in the same box as the search term, so it must be impossible to
    reach a campus your membership does not cover by typing.
    """
    tenant = await make_tenant()

    second = await tenant.post(f"{API}/schools", json={"name": "North Campus", "code": "NORTH"})
    assert second.status_code == 201, second.text
    second_school_id = second.json()["id"]

    # A student on each campus, created by the org-level principal switching view.
    tenant.active_school_id = tenant.school_id
    await seed_directory(tenant)

    tenant.active_school_id = second_school_id
    north = await tenant.post(
        f"{API}/students",
        json={"admission_number": "N-001", "first_name": "Ali", "last_name": "Northman"},
    )
    assert north.status_code == 201, north.text

    # Now a member confined to the FIRST campus.
    token = await make_campus_head(tenant, mailbox, "head@test.example", school_id=tenant.school_id)

    response = await tenant.client.get(
        SEARCH,
        params={"q": "school:all type:student ali"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    payload = response.json()

    assert payload["cross_school"] is False
    assert "Ali Northman" not in titles(payload, "student")
    assert any("organization-level access" in warning for warning in payload["warnings"])


@pytest.mark.asyncio
async def test_org_level_member_searches_across_campuses_with_school_all(
    make_tenant: Callable[..., Any],
) -> None:
    """The principal's `school:all` sets aside the campus open in the UI.

    It grants nothing -- their membership already spans the organization -- it only
    stops the `X-Active-School` header from narrowing the view.
    """
    tenant = await make_tenant()
    second = await tenant.post(f"{API}/schools", json={"name": "North Campus", "code": "NORTH"})
    assert second.status_code == 201, second.text

    tenant.active_school_id = tenant.school_id
    await seed_directory(tenant)

    tenant.active_school_id = second.json()["id"]
    north = await tenant.post(
        f"{API}/students",
        json={"admission_number": "N-001", "first_name": "Ali", "last_name": "Northman"},
    )
    assert north.status_code == 201, north.text

    # Still pointed at North Campus: the active-school header alone hides the first.
    narrowed = await tenant.get(SEARCH, params={"q": "type:student ali"})
    assert narrowed.status_code == 200, narrowed.text
    assert narrowed.json()["cross_school"] is False
    assert "Ali Hassan" not in titles(narrowed.json(), "student")

    widened = await tenant.get(SEARCH, params={"q": "school:all type:student ali"})
    assert widened.status_code == 200, widened.text
    payload = widened.json()
    assert payload["cross_school"] is True
    found = titles(payload, "student")
    assert "Ali Hassan" in found and "Ali Northman" in found
    # Cross-campus results say which campus, or they are unreadable.
    assert all(hit["school_name"] for hit in group(payload, "student")["hits"])


@pytest.mark.asyncio
async def test_search_never_crosses_the_tenant_boundary(
    make_tenant: Callable[..., Any],
) -> None:
    """Two organizations, identical student names. RLS is what keeps them apart."""
    first = await make_tenant(name="First Trust", email="first@test.example", school_code="FIRST")
    first.active_school_id = first.school_id
    await seed_directory(first)

    second = await make_tenant(
        name="Second Trust", email="second@test.example", school_code="SECOND"
    )
    second.active_school_id = second.school_id
    await seed_directory(second)

    response = await second.get(SEARCH, params={"q": "school:all type:student ali"})
    assert response.status_code == 200, response.text
    payload = response.json()

    found = group(payload, "student")
    assert found is not None
    # Three students seeded per tenant, two of them matching "ali". Seeing four
    # would mean the other organization's rows came back.
    assert found["total"] == 2, found
    assert all(hit["school_id"] == second.school_id for hit in found["hits"])


@pytest.mark.asyncio
async def test_search_requires_authentication(tenant: Tenant) -> None:
    """No permission gates the route, but a session still does."""
    tenant.client.cookies.clear()
    response = await tenant.client.get(SEARCH, params={"q": "ali"})
    assert response.status_code == 401, response.text
