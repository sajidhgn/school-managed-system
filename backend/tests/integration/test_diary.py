"""PostgreSQL-backed tests for the class diary.

The rule under test is the assignment boundary: the class teacher writes every
row of their section's page, a subject teacher writes only their subject's row,
and `diary:write` without an assignment writes nothing. Those are the guarantees
a mocked suite would pass without, so they run against real PostgreSQL as the
restricted role, through the public API.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.common.email.sender import EmailMessage
from tests.integration.conftest import API, STRONG_PASSWORD, Tenant
from tests.integration.test_academic_foundation import Campus, build_campus

pytestmark = pytest.mark.asyncio


class Staff:
    """A teacher signed in through the real login path."""

    def __init__(self, tenant: Tenant, user_id: str, token: str) -> None:
        self.tenant = tenant
        self.user_id = user_id
        self.headers = {"Authorization": f"Bearer {token}"}

    async def get(self, url: str, **kw: Any) -> Any:
        return await self.tenant.client.get(url, headers=self.headers, **kw)

    async def put(self, url: str, **kw: Any) -> Any:
        return await self.tenant.client.put(url, headers=self.headers, **kw)


async def _teacher(tenant: Tenant, email: str, name: str) -> Staff:
    """A member on the SEEDED teacher role -- so the test also proves the role's
    default grants include the diary."""
    roles = await tenant.get(f"{API}/schools/{tenant.school_id}/roles")
    assert roles.status_code == 200, roles.text
    role_id = next(r["id"] for r in roles.json() if r["code"] == "teacher")

    created = await tenant.post(
        f"{API}/schools/{tenant.school_id}/members",
        json={"email": email, "full_name": name, "password": STRONG_PASSWORD, "role_id": role_id},
    )
    assert created.status_code == 201, created.text

    tenant.client.cookies.clear()
    login = await tenant.client.post(
        f"{API}/auth/login",
        json={"email": email, "password": STRONG_PASSWORD},
        headers={"X-Token-Transport": "body"},
    )
    assert login.status_code == 200, login.text
    tenant.client.cookies.clear()
    return Staff(tenant, created.json()["user_id"], str(login.headers["X-Access-Token"]))


async def _subject(campus: Campus, code: str, teacher_id: str | None = None) -> str:
    created = await campus.post(f"{API}/subjects", json={"code": code, "name": f"Subject {code}"})
    assert created.status_code == 201, created.text
    subject_id = created.json()["id"]
    linked = await campus.post(
        f"{API}/classes/{campus.class_id}/subjects",
        json={"subject_id": subject_id, "teacher_id": teacher_id},
    )
    assert linked.status_code == 201, linked.text
    return str(subject_id)


@pytest.fixture
async def setup(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> tuple[Campus, Staff, Staff, Staff, str, str]:
    campus = await build_campus(tenant, mailbox)
    class_teacher = await _teacher(tenant, "ct@test.example", "Class Teacher")
    maths_teacher = await _teacher(tenant, "mt@test.example", "Maths Teacher")
    outsider = await _teacher(tenant, "ot@test.example", "Other Teacher")

    assigned = await campus.patch(
        f"{API}/classes/sections/{campus.section_id}",
        json={"class_teacher_id": class_teacher.user_id},
    )
    assert assigned.status_code == 200, assigned.text

    urdu = await _subject(campus, "URDU")
    maths = await _subject(campus, "MATH", teacher_id=maths_teacher.user_id)
    return campus, class_teacher, maths_teacher, outsider, urdu, maths


def _page_url(campus: Campus) -> str:
    return f"{API}/diary/sections/{campus.section_id}"


async def test_class_teacher_writes_every_subject(setup) -> None:  # type: ignore[no-untyped-def]
    campus, class_teacher, _, _, urdu, maths = setup

    saved = await class_teacher.put(
        _page_url(campus),
        params={"date": "2026-09-28"},
        json={
            "entries": [
                {"subject_id": urdu, "content": "واش روم جانے کی دعا"},
                {"subject_id": maths, "content": "  Pg 5,6 Table of 2 L+w  "},
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    rows = {row["subject_id"]: row for row in saved.json()["rows"]}
    assert rows[urdu]["content"] == "واش روم جانے کی دعا"
    assert rows[maths]["content"] == "Pg 5,6 Table of 2 L+w"  # trimmed
    assert rows[maths]["written_by_name"] == "Class Teacher"
    assert all(row["can_edit"] for row in rows.values())

    # Curriculum order, not alphabetical: URDU was added first.
    assert [row["subject_code"] for row in saved.json()["rows"]] == ["URDU", "MATH"]

    # A different day is a different page.
    other_day = await class_teacher.get(_page_url(campus), params={"date": "2026-09-29"})
    assert other_day.status_code == 200, other_day.text
    assert all(row["content"] is None for row in other_day.json()["rows"])


async def test_subject_teacher_writes_only_their_subject(setup) -> None:  # type: ignore[no-untyped-def]
    campus, _, maths_teacher, _, urdu, maths = setup

    page = await maths_teacher.get(_page_url(campus), params={"date": "2026-09-28"})
    assert page.status_code == 200, page.text
    can_edit = {row["subject_id"]: row["can_edit"] for row in page.json()["rows"]}
    assert can_edit == {urdu: False, maths: True}

    ok = await maths_teacher.put(
        _page_url(campus),
        params={"date": "2026-09-28"},
        json={"entries": [{"subject_id": maths, "content": "Pg 34"}]},
    )
    assert ok.status_code == 200, ok.text

    # A save naming someone else's row is refused WHOLE -- the Maths line in the
    # same request must not land either.
    refused = await maths_teacher.put(
        _page_url(campus),
        params={"date": "2026-09-28"},
        json={
            "entries": [
                {"subject_id": maths, "content": "changed"},
                {"subject_id": urdu, "content": "not mine"},
            ]
        },
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "DIARY_NOT_ASSIGNED"

    page = await maths_teacher.get(_page_url(campus), params={"date": "2026-09-28"})
    contents = {row["subject_id"]: row["content"] for row in page.json()["rows"]}
    assert contents == {urdu: None, maths: "Pg 34"}


async def test_unassigned_teacher_reads_but_cannot_write(setup) -> None:  # type: ignore[no-untyped-def]
    campus, _, _, outsider, urdu, _ = setup

    sections = await outsider.get(f"{API}/diary/sections")
    assert sections.status_code == 200, sections.text
    assert sections.json()[0]["access"] == "read"

    page = await outsider.get(_page_url(campus))
    assert page.status_code == 200, page.text
    assert page.json()["can_edit"] is False

    refused = await outsider.put(
        _page_url(campus), json={"entries": [{"subject_id": urdu, "content": "x"}]}
    )
    assert refused.status_code == 403, refused.text


async def test_sections_list_puts_own_class_first(setup) -> None:  # type: ignore[no-untyped-def]
    campus, class_teacher, maths_teacher, _, urdu, _ = setup

    await class_teacher.put(
        _page_url(campus),
        params={"date": "2026-09-28"},
        json={"entries": [{"subject_id": urdu, "content": "Pg 85"}]},
    )
    mine = await class_teacher.get(f"{API}/diary/sections", params={"date": "2026-09-28"})
    assert mine.status_code == 200, mine.text
    first = mine.json()[0]
    assert first["section_id"] == campus.section_id
    assert first["access"] == "class_teacher"
    assert (first["filled_count"], first["subject_count"]) == (1, 2)

    theirs = await maths_teacher.get(f"{API}/diary/sections")
    assert theirs.json()[0]["access"] == "subject_teacher"


async def test_blank_content_clears_and_foreign_subject_is_refused(setup) -> None:  # type: ignore[no-untyped-def]
    campus, class_teacher, _, _, urdu, _ = setup

    await class_teacher.put(
        _page_url(campus), json={"entries": [{"subject_id": urdu, "content": "Pg 85"}]}
    )
    cleared = await class_teacher.put(
        _page_url(campus), json={"entries": [{"subject_id": urdu, "content": "   "}]}
    )
    assert cleared.status_code == 200, cleared.text
    assert next(r for r in cleared.json()["rows"] if r["subject_id"] == urdu)["content"] is None

    # A subject the school has, but this class does not study.
    stray = await campus.post(f"{API}/subjects", json={"code": "ART", "name": "Art"})
    assert stray.status_code == 201, stray.text
    refused = await class_teacher.put(
        _page_url(campus),
        json={"entries": [{"subject_id": stray.json()["id"], "content": "draw"}]},
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "SUBJECT_NOT_IN_CLASS"


async def test_manager_writes_any_row(setup) -> None:  # type: ignore[no-untyped-def]
    """The campus head holds `diary:manage` and is assigned to nothing."""
    campus, _, _, _, urdu, maths = setup

    saved = await campus.put(
        _page_url(campus),
        json={
            "entries": [
                {"subject_id": urdu, "content": "covering for the class teacher"},
                {"subject_id": maths, "content": "and maths"},
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["can_edit"] is True
