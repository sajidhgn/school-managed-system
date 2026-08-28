"""PostgreSQL-backed tests for the academic calendar, curriculum, enrollment ledger
and attendance.

WHY THESE RUN AGAINST REAL POSTGRESQL AND AS THE RESTRICTED ROLE
    Four of the guarantees under test are enforced by the DATABASE, not by Python,
    and a SQLite or mocked suite would pass on a schema that has none of them:

      * the partial unique indexes (`uq_academic_years_one_current`,
        `uq_student_enrollments_one_open`, `uq_student_enrollments_roll`)
      * the CHECK constraints (`dates_ordered`, `whole_day_has_no_subject`)
      * the RESTRICT foreign keys that stop a subject or a year being deleted out
        from under the rows that depend on it
      * Row-Level Security, which is INERT for a superuser -- so the app connects as
        `sms_app` (NOBYPASSRLS) exactly as production does

    See `conftest.py` for the engine split.

ORGANISATION OF THIS FILE
    1. Calendar         years, the one-current invariant, terms and overlap
    2. Curriculum       subjects, class curricula, RESTRICT on delete
    3. Enrollment       seating, transfer, roster order, promotion, backfill
    4. Attendance       open/mark/submit/amend, the reports, separation of duties
    5. Isolation        two organizations, two campuses, and raw cross-tenant DML
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.email.sender import EmailMessage
from tests.integration.conftest import (
    API,
    STRONG_PASSWORD,
    Tenant,
    latest_token,
    make_campus_head,
)

pytestmark = pytest.mark.asyncio

TODAY = datetime.now(UTC).date()
YEAR_START = date(TODAY.year, 1, 1)
YEAR_END = date(TODAY.year, 12, 31)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class Campus:
    """A school with a calendar, a class, a section and students -- ready to mark.

    Built by driving the PUBLIC API rather than by inserting rows, for the reason
    `conftest.Tenant` gives: a hand-built fixture can construct a state the
    application itself could never produce, and then the tests pass against a system
    that does not exist.
    """

    def __init__(self, tenant: Tenant, token: str) -> None:
        self.tenant = tenant
        self.headers = {"Authorization": f"Bearer {token}"}
        self.year_id: str = ""
        self.class_id: str = ""
        self.section_id: str = ""
        self.student_ids: list[str] = []

    async def get(self, url: str, **kw: Any) -> Any:
        return await self.tenant.client.get(url, headers=self.headers, **kw)

    async def post(self, url: str, **kw: Any) -> Any:
        return await self.tenant.client.post(url, headers=self.headers, **kw)

    async def patch(self, url: str, **kw: Any) -> Any:
        return await self.tenant.client.patch(url, headers=self.headers, **kw)

    async def delete(self, url: str, **kw: Any) -> Any:
        return await self.tenant.client.delete(url, headers=self.headers, **kw)


async def build_campus(
    tenant: Tenant,
    mailbox: list[EmailMessage],
    *,
    email: str = "head@test.example",
    code: str = "campus_head",
    students: int = 3,
    capacity: int | None = None,
) -> Campus:
    token = await make_campus_head(tenant, mailbox, email, code=code)
    campus = Campus(tenant, token)

    year = await campus.post(
        f"{API}/academic-years",
        json={
            "name": f"{YEAR_START.year}-{YEAR_START.year + 1}",
            "start_date": str(YEAR_START),
            "end_date": str(YEAR_END),
            "is_current": True,
        },
    )
    assert year.status_code == 201, year.text
    campus.year_id = year.json()["id"]

    created_class = await campus.post(f"{API}/classes", json={"name": "Grade 9", "level": 9})
    assert created_class.status_code == 201, created_class.text
    campus.class_id = created_class.json()["id"]

    section_body: dict[str, Any] = {"name": "A"}
    if capacity is not None:
        section_body["capacity"] = capacity
    section = await campus.post(f"{API}/classes/{campus.class_id}/sections", json=section_body)
    assert section.status_code == 201, section.text
    campus.section_id = section.json()["id"]

    for index in range(students):
        student = await campus.post(
            f"{API}/students",
            json={
                "admission_number": f"{YEAR_START.year}-{index + 1:03d}",
                "first_name": f"Student{index + 1}",
                "last_name": "Test",
                "section_id": campus.section_id,
                "guardian_name": "Parent Test",
                "guardian_phone": f"0300000{index + 1:04d}",
            },
        )
        assert student.status_code == 201, student.text
        campus.student_ids.append(student.json()["id"])

    return campus


@pytest.fixture
async def campus(tenant: Tenant, mailbox: list[EmailMessage]) -> Campus:
    return await build_campus(tenant, mailbox)


async def make_actor(
    tenant: Tenant,
    mailbox: list[EmailMessage],
    email: str,
    permissions: list[str],
    *,
    code: str,
) -> dict[str, str]:
    """A school-scoped member holding EXACTLY `permissions`. Returns auth headers.

    `make_campus_head` grants every school-scoped code, which is the wrong subject
    for the separation-of-duties case: proving `attendance:mark` cannot rewrite a
    submitted register requires an actor who holds it and NOT `attendance:amend`.
    """
    role = await tenant.post(
        f"{API}/schools/{tenant.school_id}/roles",
        json={"code": code, "name": code.replace("_", " ").title(), "permissions": permissions},
    )
    assert role.status_code == 201, role.text

    invited = await tenant.post(
        f"{API}/schools/{tenant.school_id}/invitations",
        json={"email": email, "full_name": "Scoped Actor", "role_id": role.json()["id"]},
    )
    assert invited.status_code == 201, invited.text

    tenant.client.cookies.clear()
    accepted = await tenant.client.post(
        f"{API}/invitations/accept",
        json={
            "token": latest_token(mailbox),
            "full_name": "Scoped Actor",
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
    return {"Authorization": f"Bearer {login.headers['X-Access-Token']}"}


# ===========================================================================
# 1. The academic calendar
# ===========================================================================


async def test_only_one_year_can_be_current(campus: Campus) -> None:
    """Promoting a year demotes the incumbent.

    Guaranteed by `uq_academic_years_one_current`, a PARTIAL unique index. A plain
    unique index on `(school_id, is_current)` would instead permit exactly one
    NON-current year per school, which is the opposite of the rule.
    """
    second = await campus.post(
        f"{API}/academic-years",
        json={
            "name": "2099-2100",
            "start_date": "2099-04-01",
            "end_date": "2100-03-31",
            "is_current": True,
        },
    )
    assert second.status_code == 201, second.text

    listing = await campus.get(f"{API}/academic-years")
    assert listing.status_code == 200
    current = [y for y in listing.json()["items"] if y["is_current"]]
    assert len(current) == 1
    assert current[0]["name"] == "2099-2100"


async def test_set_current_is_its_own_transition(campus: Campus) -> None:
    other = await campus.post(
        f"{API}/academic-years",
        json={"name": "2098-2099", "start_date": "2098-04-01", "end_date": "2099-03-31"},
    )
    assert other.status_code == 201
    other_id = other.json()["id"]

    promoted = await campus.post(f"{API}/academic-years/{other_id}/set-current")
    assert promoted.status_code == 200
    assert promoted.json()["is_current"] is True

    still_current = await campus.get(f"{API}/academic-years/current")
    assert still_current.json()["id"] == other_id


async def test_year_must_end_after_it_starts(campus: Campus) -> None:
    bad = await campus.post(
        f"{API}/academic-years",
        json={"name": "Backwards", "start_date": "2030-06-01", "end_date": "2030-01-01"},
    )
    # Caught by the schema validator, which exists so the message names the field
    # rather than the CHECK constraint the database would otherwise report.
    assert bad.status_code == 422, bad.text


async def test_terms_may_not_overlap(campus: Campus) -> None:
    first = await campus.post(
        f"{API}/academic-years/{campus.year_id}/terms",
        json={
            "name": "Term 1",
            "sequence": 1,
            "start_date": str(YEAR_START),
            "end_date": str(YEAR_START + timedelta(days=100)),
        },
    )
    assert first.status_code == 201, first.text

    overlapping = await campus.post(
        f"{API}/academic-years/{campus.year_id}/terms",
        json={
            "name": "Term 2",
            "sequence": 2,
            "start_date": str(YEAR_START + timedelta(days=50)),
            "end_date": str(YEAR_START + timedelta(days=200)),
        },
    )
    assert overlapping.status_code == 409, overlapping.text
    assert "Term 1" in overlapping.json()["detail"]


async def test_a_term_must_fall_inside_its_year(campus: Campus) -> None:
    outside = await campus.post(
        f"{API}/academic-years/{campus.year_id}/terms",
        json={
            "name": "Stray term",
            "sequence": 1,
            "start_date": str(YEAR_END - timedelta(days=5)),
            "end_date": str(YEAR_END + timedelta(days=40)),
        },
    )
    assert outside.status_code == 422, outside.text
    assert outside.json()["code"] == "TERM_OUTSIDE_YEAR"


async def test_a_year_with_enrolled_students_cannot_be_deleted(campus: Campus) -> None:
    """The FK is RESTRICT, so the database would refuse anyway. The service refuses
    FIRST so the message names the cohort rather than a constraint."""
    deleted = await campus.delete(f"{API}/academic-years/{campus.year_id}")
    assert deleted.status_code == 409, deleted.text
    assert "history" in deleted.json()["detail"]


# ===========================================================================
# 2. Curriculum
# ===========================================================================


async def test_subject_codes_are_normalised_and_unique(campus: Campus) -> None:
    first = await campus.post(f"{API}/subjects", json={"code": "math", "name": "Mathematics"})
    assert first.status_code == 201, first.text
    assert first.json()["code"] == "MATH", "codes are upper-cased on the way in"

    duplicate = await campus.post(
        f"{API}/subjects", json={"code": "MATH", "name": "Further Mathematics"}
    )
    assert duplicate.status_code == 409, duplicate.text


async def test_a_subject_a_class_studies_cannot_be_deleted(campus: Campus) -> None:
    subject = await campus.post(f"{API}/subjects", json={"code": "PHY", "name": "Physics"})
    subject_id = subject.json()["id"]

    linked = await campus.post(
        f"{API}/classes/{campus.class_id}/subjects",
        json={"subject_id": subject_id, "weekly_periods": 5},
    )
    assert linked.status_code == 201, linked.text
    assert linked.json()["subject_code"] == "PHY", "the response inlines the subject"

    blocked = await campus.delete(f"{API}/subjects/{subject_id}")
    assert blocked.status_code == 409, blocked.text

    removed = await campus.delete(f"{API}/classes/curriculum/{linked.json()['id']}")
    assert removed.status_code == 204

    now_deletable = await campus.delete(f"{API}/subjects/{subject_id}")
    assert now_deletable.status_code == 204


async def test_a_subject_cannot_be_added_to_a_class_twice(campus: Campus) -> None:
    subject = await campus.post(f"{API}/subjects", json={"code": "CHEM", "name": "Chemistry"})
    body = {"subject_id": subject.json()["id"]}
    first = await campus.post(f"{API}/classes/{campus.class_id}/subjects", json=body)
    assert first.status_code == 201, first.text
    again = await campus.post(f"{API}/classes/{campus.class_id}/subjects", json=body)
    assert again.status_code == 409, again.text


# ===========================================================================
# 3. The enrollment ledger
# ===========================================================================


async def test_enrolling_a_student_opens_a_ledger_row(campus: Campus) -> None:
    history = await campus.get(f"{API}/students/{campus.student_ids[0]}/enrollments")
    assert history.status_code == 200, history.text
    rows = history.json()
    assert len(rows) == 1
    assert rows[0]["section_id"] == campus.section_id
    assert rows[0]["left_on"] is None, "the current placement is the open row"
    assert rows[0]["roll_number"] is not None


async def test_roster_is_ordered_by_roll_number_numerically(campus: Campus) -> None:
    """Roll 10 must not sort before roll 2 -- the same reason `SchoolClass.level`
    exists. A string sort is the default and is wrong on every printed register."""
    roster = await campus.get(f"{API}/classes/sections/{campus.section_id}/roster")
    assert roster.status_code == 200, roster.text
    rolls = [entry["roll_number"] for entry in roster.json()]
    assert rolls == ["1", "2", "3"]
    assert len(roster.json()) == len(campus.student_ids)


async def test_transfer_closes_the_previous_placement(campus: Campus) -> None:
    """`uq_student_enrollments_one_open` permits exactly one open row per student,
    so a transfer that failed to close the old one would be rejected by the database
    rather than silently leaving the child seated in two sections."""
    section_b = await campus.post(f"{API}/classes/{campus.class_id}/sections", json={"name": "B"})
    assert section_b.status_code == 201
    section_b_id = section_b.json()["id"]

    student_id = campus.student_ids[0]
    moved = await campus.post(
        f"{API}/students/{student_id}/enrollments",
        json={"section_id": section_b_id, "effective_date": str(TODAY)},
    )
    assert moved.status_code == 201, moved.text

    history = (await campus.get(f"{API}/students/{student_id}/enrollments")).json()
    assert len(history) == 2
    open_rows = [row for row in history if row["left_on"] is None]
    assert len(open_rows) == 1
    assert open_rows[0]["section_id"] == section_b_id

    # The student pointer is the HEAD of the ledger and must agree with it.
    student = (await campus.get(f"{API}/students/{student_id}")).json()
    assert student["section_id"] == section_b_id


async def test_promotion_moves_a_section_and_renumbers(
    campus: Campus, mailbox: list[EmailMessage]
) -> None:
    next_year = await campus.post(
        f"{API}/academic-years",
        json={
            "name": f"{YEAR_START.year + 1}-{YEAR_START.year + 2}",
            "start_date": str(YEAR_END + timedelta(days=1)),
            "end_date": str(YEAR_END + timedelta(days=365)),
        },
    )
    assert next_year.status_code == 201, next_year.text

    grade10 = await campus.post(f"{API}/classes", json={"name": "Grade 10", "level": 10})
    target = await campus.post(f"{API}/classes/{grade10.json()['id']}/sections", json={"name": "A"})

    promoted = await campus.post(
        f"{API}/students/promote",
        json={
            "from_section_id": campus.section_id,
            "to_section_id": target.json()["id"],
            "to_academic_year_id": next_year.json()["id"],
        },
    )
    assert promoted.status_code == 200, promoted.text
    body = promoted.json()
    assert body["promoted"] == len(campus.student_ids)
    assert body["skipped"] == []

    # The source section is now empty and the target holds everyone, renumbered 1..N.
    old_roster = (await campus.get(f"{API}/classes/sections/{campus.section_id}/roster")).json()
    assert old_roster == []
    new_roster = (await campus.get(f"{API}/classes/sections/{target.json()['id']}/roster")).json()
    assert [e["roll_number"] for e in new_roster] == ["1", "2", "3"]

    # And the ledger records where they were, which is the whole point of the table.
    history = (await campus.get(f"{API}/students/{campus.student_ids[0]}/enrollments")).json()
    assert len(history) == 2
    closed = [row for row in history if row["left_on"] is not None]
    assert closed[0]["section_id"] == campus.section_id


async def test_promotion_refuses_to_overfill_the_target(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Capacity is checked ONCE for the batch. Thirty per-student checks would each
    count the same section and pass thirty times against one free seat."""
    campus = await build_campus(tenant, mailbox, students=3)

    next_year = await campus.post(
        f"{API}/academic-years",
        json={
            "name": "2097-2098",
            "start_date": "2097-04-01",
            "end_date": "2098-03-31",
        },
    )
    grade10 = await campus.post(f"{API}/classes", json={"name": "Grade 10", "level": 10})
    small = await campus.post(
        f"{API}/classes/{grade10.json()['id']}/sections", json={"name": "A", "capacity": 2}
    )

    blocked = await campus.post(
        f"{API}/students/promote",
        json={
            "from_section_id": campus.section_id,
            "to_section_id": small.json()["id"],
            "to_academic_year_id": next_year.json()["id"],
        },
    )
    assert blocked.status_code == 409, blocked.text
    assert "room for" in blocked.json()["detail"]


async def test_backfill_is_idempotent(campus: Campus) -> None:
    """Students created through the API already have ledger rows, so the first run
    finds nothing to do. The second run must also find nothing -- a backfill that
    double-opens on retry would violate `uq_student_enrollments_one_open`, and the
    retry after a timeout is the case that matters."""
    first = await campus.post(f"{API}/academic-years/{campus.year_id}/enrollments/backfill")
    assert first.status_code == 200, first.text
    assert first.json()["opened"] == 0
    assert first.json()["already_enrolled"] == len(campus.student_ids)

    second = await campus.post(f"{API}/academic-years/{campus.year_id}/enrollments/backfill")
    assert second.status_code == 200
    assert second.json() == first.json()


async def test_withdrawing_a_student_closes_their_placement(campus: Campus) -> None:
    student_id = campus.student_ids[0]
    withdrawn = await campus.patch(f"{API}/students/{student_id}", json={"status": "transferred"})
    assert withdrawn.status_code == 200, withdrawn.text

    history = (await campus.get(f"{API}/students/{student_id}/enrollments")).json()
    assert all(row["left_on"] is not None for row in history)

    roster = (await campus.get(f"{API}/classes/sections/{campus.section_id}/roster")).json()
    assert student_id not in [entry["student_id"] for entry in roster]


# ===========================================================================
# 4. Attendance
# ===========================================================================


async def test_opening_a_register_prefills_the_roster_present(campus: Campus) -> None:
    """Rule 1 of the module: pre-filled present, teacher marks the exceptions.

    A pre-filled register is COMPLETE by construction, so a half-finished one is
    still unambiguous -- which is what makes `status` the only question left.
    """
    opened = await campus.post(
        f"{API}/attendance", json={"section_id": campus.section_id, "period": 0}
    )
    assert opened.status_code == 201, opened.text
    body = opened.json()
    assert body["status"] == "draft"
    assert body["total_count"] == len(campus.student_ids)
    assert body["present_count"] == len(campus.student_ids)
    assert {e["status"] for e in body["entries"]} == {"present"}


async def test_opening_the_same_register_twice_returns_the_first(campus: Campus) -> None:
    """IDEMPOTENT BY DESIGN. Two teachers tapping at once, or one tapping twice on a
    slow connection, must not produce two registers for one lesson -- and the 409 the
    unique constraint would raise is not something either of them can act on."""
    first = await campus.post(f"{API}/attendance", json={"section_id": campus.section_id})
    second = await campus.post(f"{API}/attendance", json={"section_id": campus.section_id})
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["id"] == second.json()["id"]


async def test_a_whole_day_register_cannot_name_a_subject(campus: Campus) -> None:
    subject = await campus.post(f"{API}/subjects", json={"code": "BIO", "name": "Biology"})
    bad = await campus.post(
        f"{API}/attendance",
        json={"section_id": campus.section_id, "period": 0, "subject_id": subject.json()["id"]},
    )
    # Rejected by the schema validator, mirroring
    # `ck_attendance_sessions_whole_day_has_no_subject` so the message names the field.
    assert bad.status_code == 422, bad.text


async def test_attendance_cannot_be_recorded_for_the_future(campus: Campus) -> None:
    future = await campus.post(
        f"{API}/attendance",
        json={
            "section_id": campus.section_id,
            "session_date": str(TODAY + timedelta(days=1)),
        },
    )
    assert future.status_code == 422, future.text
    assert future.json()["code"] == "FUTURE_DATE"


async def test_marking_is_partial_and_submission_freezes_the_register(campus: Campus) -> None:
    opened = await campus.post(f"{API}/attendance", json={"section_id": campus.section_id})
    session_id = opened.json()["id"]

    marked = await campus.patch(
        f"{API}/attendance/{session_id}/entries",
        json={"entries": [{"student_id": campus.student_ids[0], "status": "absent"}]},
    )
    assert marked.status_code == 200, marked.text
    body = marked.json()
    assert body["absent_count"] == 1
    # The two students NOT named keep the status they already had.
    assert body["present_count"] == len(campus.student_ids) - 1

    submitted = await campus.post(f"{API}/attendance/{session_id}/submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["submitted_at"] is not None

    again = await campus.post(f"{API}/attendance/{session_id}/submit")
    assert again.status_code == 409, "submitting twice is a conflict, not a no-op"


async def test_marking_cannot_reach_a_student_outside_the_register(campus: Campus) -> None:
    """The ROSTER decides who a register covers, not the request body. Otherwise a
    caller could create an attendance row for a child in another section."""
    other_section = await campus.post(
        f"{API}/classes/{campus.class_id}/sections", json={"name": "C"}
    )
    outsider = await campus.post(
        f"{API}/students",
        json={
            "admission_number": "OUTSIDER-1",
            "first_name": "Outside",
            "last_name": "Section",
            "section_id": other_section.json()["id"],
        },
    )
    opened = await campus.post(f"{API}/attendance", json={"section_id": campus.section_id})

    rejected = await campus.patch(
        f"{API}/attendance/{opened.json()['id']}/entries",
        json={"entries": [{"student_id": outsider.json()["id"], "status": "absent"}]},
    )
    assert rejected.status_code == 422, rejected.text
    assert rejected.json()["code"] == "STUDENT_NOT_ON_REGISTER"


async def test_mark_alone_cannot_rewrite_a_submitted_register(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """SEPARATION OF DUTIES, the module's whole integrity story.

    A system where the person who records absences can also erase them has no
    attendance record, only an attendance opinion. `attendance:mark` submits;
    `attendance:amend` -- a different, `dangerous`, non-default code -- rewrites.
    """
    campus = await build_campus(tenant, mailbox)
    opened = await campus.post(f"{API}/attendance", json={"section_id": campus.section_id})
    session_id = opened.json()["id"]
    await campus.post(f"{API}/attendance/{session_id}/submit")

    marker = await make_actor(
        tenant,
        mailbox,
        "marker@test.example",
        ["school:read", "student:read", "class:read", "attendance:read", "attendance:mark"],
        code="marker_only",
    )

    blocked = await tenant.client.patch(
        f"{API}/attendance/{session_id}/entries",
        headers=marker,
        json={
            "entries": [{"student_id": campus.student_ids[0], "status": "present"}],
            "reason": "Trying to change a submitted register",
        },
    )
    assert blocked.status_code == 409, blocked.text
    assert blocked.json()["code"] == "ATTENDANCE_SUBMITTED"

    reopen_blocked = await tenant.client.post(
        f"{API}/attendance/{session_id}/reopen",
        headers=marker,
        json={"reason": "Trying to reopen"},
    )
    assert reopen_blocked.status_code == 403, reopen_blocked.text


async def test_amending_requires_a_reason_and_is_audited(campus: Campus) -> None:
    opened = await campus.post(f"{API}/attendance", json={"section_id": campus.section_id})
    session_id = opened.json()["id"]
    await campus.post(f"{API}/attendance/{session_id}/submit")

    no_reason = await campus.patch(
        f"{API}/attendance/{session_id}/entries",
        json={"entries": [{"student_id": campus.student_ids[0], "status": "absent"}]},
    )
    assert no_reason.status_code == 422, no_reason.text
    assert no_reason.json()["code"] == "AMENDMENT_REASON_REQUIRED"

    amended = await campus.patch(
        f"{API}/attendance/{session_id}/entries",
        json={
            "entries": [{"student_id": campus.student_ids[0], "status": "absent"}],
            "reason": "Note from mother received after submission",
        },
    )
    assert amended.status_code == 200, amended.text
    assert amended.json()["absent_count"] == 1

    # ONE audit row per amended STUDENT, not one for the batch -- "who changed Ali's
    # absence, and why" is the question this trail is read with.
    audit = await campus.get(
        f"{API}/schools/{campus.tenant.school_id}/audit-logs",
        params={"action": "attendance_record.amended"},
    )
    assert audit.status_code == 200, audit.text
    # The audit log is a cursor-paginated LIST, not a `Page` envelope -- see ADR 0001.
    entries = audit.json()
    assert len(entries) == 1
    assert entries[0]["after"]["reason"] == "Note from mother received after submission"
    assert entries[0]["before"]["status"] == "present"


async def test_a_submitted_register_cannot_be_discarded(campus: Campus) -> None:
    opened = await campus.post(f"{API}/attendance", json={"section_id": campus.section_id})
    session_id = opened.json()["id"]

    discarded = await campus.delete(f"{API}/attendance/{session_id}")
    assert discarded.status_code == 204, "a draft may be thrown away"

    reopened = await campus.post(f"{API}/attendance", json={"section_id": campus.section_id})
    await campus.post(f"{API}/attendance/{reopened.json()['id']}/submit")
    blocked = await campus.delete(f"{API}/attendance/{reopened.json()['id']}")
    assert blocked.status_code == 409, blocked.text


async def test_daily_overview_distinguishes_unmarked_from_fully_present(
    campus: Campus,
) -> None:
    """The reason `attendance_sessions` is a table at all.

    In a flat attendance table "nobody marked Grade 10-B" and "Grade 10-B was fully
    present" are both an absence of rows.
    """
    section_b = await campus.post(f"{API}/classes/{campus.class_id}/sections", json={"name": "B"})
    before = (await campus.get(f"{API}/attendance/today")).json()
    assert before["sections_total"] == 2
    assert before["sections_not_started"] == 2

    opened = await campus.post(f"{API}/attendance", json={"section_id": campus.section_id})
    await campus.post(f"{API}/attendance/{opened.json()['id']}/submit")

    after = (await campus.get(f"{API}/attendance/today")).json()
    assert after["sections_submitted"] == 1
    assert after["sections_not_started"] == 1
    unmarked = [s for s in after["sections"] if s["section_id"] == section_b.json()["id"]]
    assert unmarked[0]["session_id"] is None
    assert unmarked[0]["total_count"] == 0


async def test_excused_absence_leaves_the_denominator(campus: Campus) -> None:
    """An authorised absence is neither attendance nor a failure to attend.

    Counting it either way misreports the child: as absent it fails them against a
    threshold they were excused from; as present it overstates their attendance.
    """
    opened = await campus.post(f"{API}/attendance", json={"section_id": campus.section_id})
    session_id = opened.json()["id"]
    await campus.patch(
        f"{API}/attendance/{session_id}/entries",
        json={"entries": [{"student_id": campus.student_ids[0], "status": "excused"}]},
    )
    await campus.post(f"{API}/attendance/{session_id}/submit")

    summary = await campus.get(
        f"{API}/attendance/students/{campus.student_ids[0]}/summary",
        params={"from_date": str(TODAY - timedelta(days=7)), "to_date": str(TODAY)},
    )
    assert summary.status_code == 200, summary.text
    body = summary.json()
    assert body["total_sessions"] == 1
    assert body["excused"] == 1
    assert body["counted_sessions"] == 0
    # None, not 0.0: a student with no countable registers has no attendance rate,
    # and 0% would put a disciplinary-looking figure against them.
    assert body["percentage"] is None


async def test_half_day_counts_as_half_and_late_counts_as_present(campus: Campus) -> None:
    for offset in (2, 1, 0):
        day = TODAY - timedelta(days=offset)
        opened = await campus.post(
            f"{API}/attendance",
            json={"section_id": campus.section_id, "session_date": str(day)},
        )
        session_id = opened.json()["id"]
        status = {2: "absent", 1: "half_day", 0: "late"}[offset]
        await campus.patch(
            f"{API}/attendance/{session_id}/entries",
            json={"entries": [{"student_id": campus.student_ids[0], "status": status}]},
        )
        await campus.post(f"{API}/attendance/{session_id}/submit")

    summary = (
        await campus.get(
            f"{API}/attendance/students/{campus.student_ids[0]}/summary",
            params={"from_date": str(TODAY - timedelta(days=7)), "to_date": str(TODAY)},
        )
    ).json()
    assert summary["counted_sessions"] == 3
    assert summary["absent"] == 1 and summary["half_day"] == 1 and summary["late"] == 1
    # late (1.0) + half_day (0.5) + absent (0.0) over three counted sessions.
    assert summary["percentage"] == pytest.approx(50.0)


async def test_draft_registers_do_not_reach_reports(campus: Campus) -> None:
    """A draft is a teacher's work in progress. Letting it into a percentage means
    the number a parent is shown changes during the school day for reasons nobody
    can explain."""
    opened = await campus.post(f"{API}/attendance", json={"section_id": campus.section_id})
    await campus.patch(
        f"{API}/attendance/{opened.json()['id']}/entries",
        json={"entries": [{"student_id": campus.student_ids[0], "status": "absent"}]},
    )

    summary = (
        await campus.get(
            f"{API}/attendance/students/{campus.student_ids[0]}/summary",
            params={"from_date": str(TODAY - timedelta(days=7)), "to_date": str(TODAY)},
        )
    ).json()
    assert summary["total_sessions"] == 0

    report = (
        await campus.get(
            f"{API}/attendance/sections/{campus.section_id}/report",
            params={"from_date": str(TODAY - timedelta(days=7)), "to_date": str(TODAY)},
        )
    ).json()
    assert report["days"] == []
    assert report["average_percentage"] is None


# ===========================================================================
# 5. Isolation -- two organizations, two campuses, and raw DML
# ===========================================================================


async def test_two_organizations_cannot_see_each_others_academic_data(
    make_tenant: Any, mailbox: list[EmailMessage]
) -> None:
    """RLS on `organization_id` is the HARD boundary. A known id from another
    organization must read as 404 -- never 403, which would confirm it exists."""
    org_a = await make_tenant(name="Org A", email="a@test.example", school_code="A1")
    campus_a = await build_campus(org_a, mailbox, email="head-a@test.example", code="head_a")

    mailbox.clear()
    org_b = await make_tenant(name="Org B", email="b@test.example", school_code="B1")
    campus_b = await build_campus(org_b, mailbox, email="head-b@test.example", code="head_b")

    session_a = await campus_a.post(f"{API}/attendance", json={"section_id": campus_a.section_id})
    assert session_a.status_code == 201

    for url in (
        f"{API}/academic-years/{campus_a.year_id}",
        f"{API}/attendance/{session_a.json()['id']}",
        f"{API}/classes/sections/{campus_a.section_id}/roster",
        f"{API}/students/{campus_a.student_ids[0]}/enrollments",
    ):
        leaked = await campus_b.get(url)
        assert leaked.status_code == 404, f"{url} leaked across organizations: {leaked.text}"

    # B's own listing sees only B's rows.
    years_b = (await campus_b.get(f"{API}/academic-years")).json()
    assert campus_a.year_id not in [y["id"] for y in years_b["items"]]


async def test_two_campuses_in_one_organization_are_scoped_apart(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """School scoping is the SOFT boundary -- enforced by the repository, not by a
    policy, because an org-level principal legitimately reads across campuses while a
    campus-scoped member must not."""
    campus_one = await build_campus(tenant, mailbox, email="one@test.example", code="head_one")

    second_school = await tenant.post(
        f"{API}/schools", json={"name": "Second Campus", "code": "SECOND"}
    )
    assert second_school.status_code == 201, second_school.text
    second_id = second_school.json()["id"]

    mailbox.clear()
    token_two = await make_campus_head(
        tenant, mailbox, "two@test.example", school_id=second_id, code="head_two"
    )
    headers_two = {"Authorization": f"Bearer {token_two}"}

    # Campus two cannot read campus one's calendar, roster or registers.
    for url in (
        f"{API}/academic-years/{campus_one.year_id}",
        f"{API}/classes/sections/{campus_one.section_id}/roster",
    ):
        blocked = await tenant.client.get(url, headers=headers_two)
        assert blocked.status_code == 404, f"{url} leaked across campuses: {blocked.text}"

    # And cannot mutate them.
    hijack = await tenant.client.post(
        f"{API}/attendance", headers=headers_two, json={"section_id": campus_one.section_id}
    )
    assert hijack.status_code == 404, hijack.text

    # The org-level principal still sees campus one, which is the whole reason
    # school scoping is not an RLS policy.
    tenant.active_school_id = tenant.school_id
    seen = await tenant.get(f"{API}/academic-years/{campus_one.year_id}")
    assert seen.status_code == 200, seen.text


@pytest.mark.parametrize(
    "table",
    [
        "academic_years",
        "terms",
        "subjects",
        "class_subjects",
        "student_enrollments",
        "attendance_sessions",
        "attendance_records",
    ],
)
async def test_raw_cross_tenant_insert_is_rejected_by_rls(
    campus: Campus,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    table: str,
) -> None:
    """The WITH CHECK half of every policy, exercised directly.

    Bypasses the application entirely: a connection bound to organization X must not
    be able to INSERT a row stamped with organization Y, even with a hand-written
    statement. A USING-only policy would let this through -- the writer could not
    read the row back, but they would have written into another tenant.

    Runs as `sms_app` (NOBYPASSRLS), because as a superuser every policy is inert and
    this test would pass against a schema with no policies at all.
    """
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from tests.integration.conftest import _TEST_DB_HOST, _TEST_DB_NAME, _TEST_DB_PORT

    engine = create_async_engine(
        f"postgresql+asyncpg://sms_app:sms_app_password@{_TEST_DB_HOST}:{_TEST_DB_PORT}/{_TEST_DB_NAME}",
        poolclass=NullPool,
    )
    try:
        async with engine.begin() as conn:
            # Bind a DIFFERENT organization than the row we are about to stamp.
            await conn.execute(
                text("SELECT set_config('app.current_org_id', :org, true)"),
                {"org": "00000000-0000-0000-0000-0000000000ff"},
            )
            with pytest.raises(DBAPIError) as caught:
                await conn.execute(
                    text(
                        f"INSERT INTO {table} (organization_id, school_id) VALUES (:org, :school)"
                    ),
                    {"org": campus.tenant.organization_id, "school": campus.tenant.school_id},
                )
            # `row-level security` for the policy, or a NOT NULL violation if the
            # policy were somehow satisfied -- either way the row does not land, and
            # the policy message is what we expect to see.
            assert "row-level security" in str(caught.value).lower()
    finally:
        await engine.dispose()
