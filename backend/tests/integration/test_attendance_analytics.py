"""PostgreSQL-backed tests for attendance analytics: by class, and by child.

Three endpoints, one set of rules. The cases lean on the rules as hard as on the
arithmetic, because an analytics screen that quietly counts a draft, a lesson
register or an excused absence produces a number nobody can reconcile with the
register it came from:

  * only SUBMITTED whole-day registers count -- a draft or a lesson register is
    invisible to every figure;
  * EXCUSED leaves the denominator, HALF_DAY earns 0.5, LATE is present;
  * a rate is null, never 0, when nothing is countable;
  * a teacher without `class:view_all` sees their own sections and children, and
    anything else is a 404 worded exactly like an id that never existed;
  * another organization, or another campus, is invisible.

Registers are opened through the public API, which refuses a date more than 30 days
back for anyone -- so every date here sits inside that window.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from uuid import uuid4

import pytest

from app.common.email.sender import EmailMessage
from tests.integration.conftest import API, Tenant, make_campus_head
from tests.integration.staff import _teacher
from tests.integration.test_academic_foundation import (
    TODAY,
    YEAR_START,
    Campus,
    build_campus,
    make_actor,
)
from tests.integration.test_attendance_scope import _same_404
from tests.integration.test_teaching_scope import (
    School,
    _class_teacher_of_9a,
    _section,
    _student,
    school,
)

pytestmark = pytest.mark.asyncio

__all__ = ["school"]  # the fixture, re-exported so pytest finds it here

ANALYTICS = f"{API}/attendance/analytics"
STUDENTS = f"{API}/attendance/students"

# The last day of last month, and whether a test can use it: the API refuses to open
# a register more than 30 days back (so not on the 31st), and in January it falls
# before the test calendar's year, outside the "overall" window the test asserts on.
LAST_MONTH_END = TODAY.replace(day=1) - timedelta(days=1)
LAST_MONTH_REACHABLE = (TODAY - LAST_MONTH_END).days <= 30 and LAST_MONTH_END >= YEAR_START


def _day(offset: int) -> str:
    return str(TODAY - timedelta(days=offset))


def _span(first_offset: int, last_offset: int = 0) -> dict[str, str]:
    """`from_date`/`to_date` for `first_offset` days ago through `last_offset`."""
    return {"from_date": _day(first_offset), "to_date": _day(last_offset)}


async def _register(
    campus: Campus,
    section_id: str,
    on: int | date,
    statuses: dict[str, str] | None = None,
    *,
    submit: bool = True,
    period: int = 0,
) -> str:
    """Open a register `on` days ago (or on a date), mark the exceptions, submit.

    Everyone not named stays `present` -- the register is pre-filled (spec 5.2).
    """
    session_date = on if isinstance(on, date) else TODAY - timedelta(days=on)
    opened = await campus.post(
        f"{API}/attendance",
        json={"section_id": section_id, "session_date": str(session_date), "period": period},
    )
    assert opened.status_code == 201, opened.text
    session_id = str(opened.json()["id"])
    if statuses:
        marked = await campus.patch(
            f"{API}/attendance/{session_id}/entries",
            json={"entries": [{"student_id": s, "status": v} for s, v in statuses.items()]},
        )
        assert marked.status_code == 200, marked.text
    if submit:
        submitted = await campus.post(f"{API}/attendance/{session_id}/submit")
        assert submitted.status_code == 200, submitted.text
    return session_id


async def _ok(response: Any) -> Any:
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
async def four(tenant: Tenant, mailbox: list[EmailMessage]) -> Campus:
    """One section, Grade 9-A, with four students."""
    return await build_campus(tenant, mailbox, students=4)


# ===========================================================================
# 1. The class-by-class view
# ===========================================================================


async def test_rates_follow_the_module_rules(four: Campus) -> None:
    """Excused out, half day 0.5, late present; drafts and lesson registers invisible."""
    s = four.student_ids
    await _register(four, four.section_id, 0, {s[1]: "late", s[2]: "half_day", s[3]: "excused"})
    await _register(four, four.section_id, 1, {s[0]: "absent"}, submit=False)  # a draft
    await _register(four, four.section_id, 2, {s[0]: "absent"})
    # A LESSON register full of absences: a different question, not a school day.
    await _register(four, four.section_id, 3, dict.fromkeys(s, "absent"), period=1)
    # The previous period of a 7-day range is 7..13 days ago.
    await _register(four, four.section_id, 9, {s[0]: "absent", s[1]: "absent"})

    body = await _ok(await four.get(ANALYTICS, params=_span(6)))

    assert body["previous_from_date"] == _day(13)
    assert body["previous_to_date"] == _day(7)
    summary = body["summary"]
    # (1 + 1 + 0.5) / 3 today, plus 3 / 4 two days ago.
    assert summary["percentage"] == pytest.approx(round(5.5 / 7 * 100, 2))
    assert summary["previous_percentage"] == pytest.approx(50.0)
    assert summary["counted"] == 7
    assert summary["counts"] == {
        "present": 4,
        "absent": 1,
        "late": 1,
        "excused": 1,
        "half_day": 1,
    }
    assert summary["school_days"] == 2

    assert [(d["session_date"], d["percentage"], d["absent"]) for d in body["days"]] == [
        (_day(2), 75.0, 1),
        (_day(0), pytest.approx(83.33), 0),
    ]
    weekdays = {w["weekday"]: w for w in body["weekdays"]}
    assert list(weekdays) == [1, 2, 3, 4, 5, 6, 7]
    assert weekdays[TODAY.isoweekday()]["school_days"] == 1
    assert sum(w["school_days"] for w in body["weekdays"]) == 2

    (row,) = body["sections"]
    assert row["percentage"] == summary["percentage"]
    assert row["previous_percentage"] == pytest.approx(50.0)
    assert row["registers_submitted"] == 2
    assert row["registers_draft"] == 1
    assert row["coverage_percentage"] == pytest.approx(100.0)
    assert row["today_status"] == "submitted"
    assert row["students_on_roll"] == 4

    assert body["headline"]["today"]["percentage"] == pytest.approx(83.33)
    assert body["headline"]["today"]["counted"] == 3


async def test_section_rows_coverage_and_class_filter(school: School) -> None:
    campus = school.campus
    for offset in (2, 1, 0):
        await _register(campus, campus.section_id, offset)
    await _register(campus, school.section_9b, 2, {school.student_9b: "absent"})
    await _register(campus, school.section_9b, 0, submit=False)  # today's, still a draft

    body = await _ok(await campus.get(ANALYTICS, params=_span(2)))
    rows = body["sections"]
    # School order -- class level, then section -- not the order of the numbers.
    assert [(r["class_name"], r["section_name"]) for r in rows] == [
        ("Grade 9", "A"),
        ("Grade 9", "B"),
        ("Grade 10", "A"),
    ]
    nine_a, nine_b, ten_a = rows
    assert body["summary"]["school_days"] == 3

    assert nine_a["coverage_percentage"] == pytest.approx(100.0)
    assert nine_a["percentage"] == pytest.approx(100.0)
    assert nine_a["today_status"] == "submitted"

    assert nine_b["registers_submitted"] == 1
    assert nine_b["registers_draft"] == 1
    assert nine_b["coverage_percentage"] == pytest.approx(33.33)
    assert nine_b["percentage"] == pytest.approx(0.0)
    assert nine_b["today_status"] == "draft"

    # Never marked: no rate (not 0%), no coverage, and "not started" today.
    assert ten_a["percentage"] is None
    assert ten_a["previous_percentage"] is None
    assert ten_a["coverage_percentage"] == pytest.approx(0.0)
    assert ten_a["today_status"] == "not_started"

    # Three sections owe a register on each of three school days; four arrived.
    assert body["summary"]["registers_expected"] == 9
    assert body["summary"]["registers_submitted"] == 4
    assert body["summary"]["coverage_percentage"] == pytest.approx(44.44)
    assert [c["class_name"] for c in body["classes"]] == ["Grade 9", "Grade 10"]

    # The class filter narrows every figure, but the school was still open for three
    # days and the filter's options are still every class.
    tenth = await _ok(await campus.get(ANALYTICS, params={**_span(2), "class_id": school.class_10}))
    assert [r["section_id"] for r in tenth["sections"]] == [school.section_10a]
    assert tenth["summary"]["percentage"] is None
    assert tenth["summary"]["school_days"] == 3
    assert len(tenth["classes"]) == 2

    unknown = await campus.get(ANALYTICS, params={"class_id": str(uuid4())})
    assert unknown.status_code == 404, unknown.text


async def test_at_risk_threshold_minimum_and_streak(four: Campus) -> None:
    s = four.student_ids
    # Six school days, oldest first. s0 absent throughout; s1 absent for three days,
    # then back, then excused today; s2 absent only today; s3 always in.
    pattern = {
        5: {s[0]: "absent", s[1]: "absent"},
        4: {s[0]: "absent", s[1]: "absent"},
        3: {s[0]: "absent", s[1]: "absent"},
        2: {s[0]: "absent"},
        1: {s[0]: "absent"},
        0: {s[0]: "absent", s[1]: "excused", s[2]: "absent"},
    }
    for offset, statuses in pattern.items():
        await _register(four, four.section_id, offset, statuses)

    roster = await _ok(await four.get(f"{API}/classes/sections/{four.section_id}/roster"))
    rolls = {r["student_id"]: r["roll_number"] for r in roster}

    body = await _ok(await four.get(ANALYTICS, params=_span(5)))
    at_risk = body["at_risk"]
    assert [r["student_id"] for r in at_risk] == [s[0], s[1]]  # worst first
    worst, second = at_risk
    assert worst["percentage"] == 0.0
    assert worst["counted_sessions"] == 6
    assert worst["absent"] == 6
    assert worst["absence_streak"] == 6
    assert worst["full_name"] == "Student1 Test"
    assert worst["class_name"] == "Grade 9" and worst["section_name"] == "A"
    assert worst["roll_number"] == rolls[s[0]]
    # 2 of 5 counted (today's excused line is out of the denominator)...
    assert second["percentage"] == pytest.approx(40.0)
    assert second["counted_sessions"] == 5
    # ...and an excused day ends a streak: the school knows why they are out.
    assert second["absence_streak"] == 0
    assert body["summary"]["at_risk_students"] == 2
    assert body["sections"][0]["at_risk_students"] == 2

    # A stricter threshold catches s2 at 5/6.
    strict = await _ok(await four.get(ANALYTICS, params={**_span(5), "threshold": 90}))
    assert [r["student_id"] for r in strict["at_risk"]] == [s[0], s[1], s[2]]
    assert strict["at_risk"][2]["percentage"] == pytest.approx(83.33)
    assert strict["at_risk"][2]["absence_streak"] == 1

    # Three days of data is below the default minimum of five: nobody is flagged on
    # so little evidence...
    short = await _ok(await four.get(ANALYTICS, params=_span(2)))
    assert short["at_risk"] == []
    assert short["summary"]["at_risk_students"] == 0
    # ...until the caller lowers it. s1 has only two counted days, so stays off; and
    # s0's streak reaches back past the range, because a streak is about the child.
    relaxed = await _ok(await four.get(ANALYTICS, params={**_span(2), "min_sessions": 3}))
    assert [r["student_id"] for r in relaxed["at_risk"]] == [s[0], s[2]]
    assert relaxed["at_risk"][0]["absence_streak"] == 6


async def test_empty_range_is_null_not_zero(four: Campus) -> None:
    """Nothing marked: every rate is unknown, never a disciplinary-looking 0%."""
    body = await _ok(await four.get(ANALYTICS))
    assert body["to_date"] == str(TODAY)
    assert body["from_date"] == _day(29)  # the default 30 days

    summary = body["summary"]
    assert summary["percentage"] is None
    assert summary["previous_percentage"] is None
    assert summary["coverage_percentage"] is None
    assert summary["school_days"] == 0
    assert summary["counted"] == 0
    assert body["days"] == []
    assert all(w["percentage"] is None and w["school_days"] == 0 for w in body["weekdays"])
    assert body["at_risk"] == []

    (row,) = body["sections"]
    assert row["percentage"] is None
    assert row["coverage_percentage"] is None
    assert row["today_status"] == "not_started"
    assert set(row["counts"].values()) == {0}

    headline = body["headline"]
    assert headline["today"]["percentage"] is None
    assert headline["this_month"]["percentage"] is None
    assert headline["previous_month"]["percentage"] is None
    assert headline["year_to_date"]["from_date"] == str(YEAR_START)
    assert headline["year_to_date"]["percentage"] is None


# ===========================================================================
# 2. Every child
# ===========================================================================


async def test_student_table_windows_and_todays_state(four: Campus) -> None:
    """Today / this month / last month / overall, and "not marked" is not "present"."""
    if not LAST_MONTH_REACHABLE:
        pytest.skip("last month's final day is beyond the 30-day backdate window today")
    campus = four
    s = campus.student_ids
    unmarked_section = await _section(campus, campus.class_id, "B")
    unmarked = await _student(campus, "S-UNMARKED", "Unmarked", unmarked_section)
    draft_section = await _section(campus, campus.class_id, "C")
    drafted = await _student(campus, "S-DRAFTED", "Drafted", draft_section)

    await _register(campus, campus.section_id, 0, {s[0]: "absent", s[1]: "late"})
    await _register(campus, draft_section, 0, {drafted: "absent"}, submit=False)
    await _register(campus, campus.section_id, LAST_MONTH_END, {s[1]: "absent", s[2]: "excused"})

    page = await _ok(await campus.get(STUDENTS, params={"size": 50}))
    assert page["today"] == str(TODAY)
    assert page["this_month"] == {"from_date": str(TODAY.replace(day=1)), "to_date": str(TODAY)}
    assert page["previous_month"] == {
        "from_date": str(LAST_MONTH_END.replace(day=1)),
        "to_date": str(LAST_MONTH_END),
    }
    # "Overall" defaults to the academic year so far.
    assert page["overall"] == {"from_date": str(YEAR_START), "to_date": str(TODAY)}
    assert page["meta"]["total"] == 6
    rows = {r["student_id"]: r for r in page["items"]}

    absent_today = rows[s[0]]
    assert absent_today["today_register"] == "submitted"
    assert absent_today["today_status"] == "absent"
    assert absent_today["this_month"]["percentage"] == 0.0
    assert absent_today["previous_month"]["percentage"] == 100.0
    assert absent_today["overall"]["percentage"] == pytest.approx(50.0)
    assert absent_today["overall"]["counts"]["absent"] == 1

    late_today = rows[s[1]]
    assert late_today["today_status"] == "late"
    assert late_today["this_month"]["percentage"] == 100.0  # late is present
    assert late_today["previous_month"]["percentage"] == 0.0
    assert late_today["overall"]["percentage"] == pytest.approx(50.0)

    excused_last_month = rows[s[2]]
    assert excused_last_month["today_status"] == "present"
    # Only an excused line last month: nothing countable, so no rate -- not 0%.
    assert excused_last_month["previous_month"]["percentage"] is None
    assert excused_last_month["previous_month"]["counted"] == 0
    assert excused_last_month["previous_month"]["counts"]["excused"] == 1
    assert excused_last_month["overall"]["percentage"] == 100.0

    # Nobody opened a register for this child today: NOT the same as present.
    assert rows[unmarked]["today_register"] == "not_started"
    assert rows[unmarked]["today_status"] is None
    assert rows[unmarked]["overall"]["percentage"] is None
    # A register is open but not submitted: its pre-filled lines are not reported.
    assert rows[drafted]["today_register"] == "draft"
    assert rows[drafted]["today_status"] is None
    assert rows[drafted]["this_month"]["percentage"] is None

    # Worst first by default; children with no rate after everyone with one.
    order = [r["student_id"] for r in page["items"]]
    assert order[:2] == [s[0], s[1]]  # 50% each, then by name
    assert order[-2:] == [drafted, unmarked]

    by_name = await _ok(await campus.get(STUDENTS, params={"sort_by": "name", "size": 50}))
    assert by_name["items"][0]["full_name"] == "Drafted Scoped"

    paged = await _ok(await campus.get(STUDENTS, params={"size": 2, "page": 2}))
    assert len(paged["items"]) == 2
    assert paged["meta"] == {
        "page": 2,
        "size": 2,
        "total": 6,
        "pages": 3,
        "has_next": True,
        "has_prev": True,
    }

    searched = await _ok(await campus.get(STUDENTS, params={"q": "student2"}))
    assert [r["student_id"] for r in searched["items"]] == [s[1]]
    in_b = await _ok(await campus.get(STUDENTS, params={"section_id": unmarked_section}))
    assert [r["student_id"] for r in in_b["items"]] == [unmarked]

    bad_sort = await campus.get(STUDENTS, params={"sort_by": "guardian_phone"})
    assert bad_sort.status_code == 422, bad_sort.text
    assert bad_sort.json()["code"] == "INVALID_SORT_FIELD"


async def test_student_calendar_drilldown(four: Campus) -> None:
    s0 = four.student_ids[0]
    await _register(four, four.section_id, 2, {s0: "absent"})
    await _register(four, four.section_id, 1, {s0: "half_day"})
    await _register(four, four.section_id, 1, {s0: "absent"}, period=2)  # a lesson
    await _register(four, four.section_id, 0, {s0: "absent"}, submit=False)

    url = f"{STUDENTS}/{s0}/calendar"
    body = await _ok(await four.get(url, params=_span(2)))
    assert body["full_name"] == "Student1 Test"
    assert body["class_name"] == "Grade 9" and body["section_name"] == "A"
    assert [(d["session_date"], d["register_state"], d["status"]) for d in body["days"]] == [
        (_day(2), "submitted", "absent"),
        (_day(1), "submitted", "half_day"),
        # Today's register is a draft: the day is shown, its status is not.
        (_day(0), "draft", None),
    ]
    assert body["overall"]["counted"] == 2
    assert body["overall"]["percentage"] == pytest.approx(25.0)
    # The months add up to the whole, and every month the range touches is listed.
    assert sum(m["counted"] for m in body["months"]) == 2
    assert body["months"][-1]["month"] == TODAY.strftime("%Y-%m")

    # Defaults to the academic year so far.
    year = await _ok(await four.get(url))
    assert year["from_date"] == str(YEAR_START)
    assert year["to_date"] == str(TODAY)
    assert year["months"][0]["month"] == YEAR_START.strftime("%Y-%m")

    assert (await four.get(f"{STUDENTS}/{uuid4()}/calendar")).status_code == 404


# ===========================================================================
# 3. Boundaries -- the teacher, the campus, the organization
# ===========================================================================


async def test_teacher_sees_only_their_own_sections_and_children(school: School) -> None:
    campus = school.campus
    teacher = await _class_teacher_of_9a(school)
    mine = campus.student_ids[0]
    await _register(campus, campus.section_id, 0, {mine: "absent"})
    await _register(campus, school.section_10a, 0, {school.student_10a: "absent"})
    risky = {"min_sessions": 1}

    admin = await _ok(await campus.get(ANALYTICS, params=risky))
    assert len(admin["sections"]) == 3
    assert admin["summary"]["counts"]["absent"] == 2
    assert {r["student_id"] for r in admin["at_risk"]} == {mine, school.student_10a}

    body = await _ok(await teacher.get(ANALYTICS, params=risky))
    assert [r["section_id"] for r in body["sections"]] == [campus.section_id]
    assert [c["class_name"] for c in body["classes"]] == ["Grade 9"]
    assert body["summary"]["counts"]["absent"] == 1
    assert body["summary"]["counted"] == 3
    assert body["headline"]["today"]["counted"] == 3
    assert [r["student_id"] for r in body["at_risk"]] == [mine]

    # A class they do not teach is indistinguishable from one that does not exist.
    _same_404(
        await teacher.get(ANALYTICS, params={"class_id": school.class_10}),
        await teacher.get(ANALYTICS, params={"class_id": str(uuid4())}),
    )

    students = await _ok(await teacher.get(STUDENTS, params={"size": 50}))
    assert {r["student_id"] for r in students["items"]} == set(campus.student_ids)
    _same_404(
        await teacher.get(STUDENTS, params={"section_id": school.section_10a}),
        await teacher.get(STUDENTS, params={"section_id": str(uuid4())}),
    )
    assert (await teacher.get(f"{STUDENTS}/{mine}/calendar")).status_code == 200
    _same_404(
        await teacher.get(f"{STUDENTS}/{school.student_10a}/calendar"),
        await teacher.get(f"{STUDENTS}/{uuid4()}/calendar"),
    )

    everyone = await _ok(await campus.get(STUDENTS, params={"size": 50}))
    assert everyone["meta"]["total"] == 5

    # Assigned to nothing: an empty view, not an error and not the campus.
    outsider = await _teacher(campus.tenant, "new@test.example", "New Teacher")
    nothing = await _ok(await outsider.get(ANALYTICS))
    assert nothing["sections"] == []
    assert nothing["summary"]["percentage"] is None
    assert nothing["headline"]["today"]["percentage"] is None
    assert (await _ok(await outsider.get(STUDENTS)))["items"] == []


async def test_two_organizations_and_two_campuses_are_isolated(
    make_tenant: Any, mailbox: list[EmailMessage]
) -> None:
    org_a = await make_tenant(name="Org A", email="a@test.example", school_code="A1")
    campus_a = await build_campus(org_a, mailbox, email="head-a@test.example", code="head_a")
    await _register(campus_a, campus_a.section_id, 0, {campus_a.student_ids[0]: "absent"})

    mailbox.clear()
    org_b = await make_tenant(name="Org B", email="b@test.example", school_code="B1")
    campus_b = await build_campus(org_b, mailbox, email="head-b@test.example", code="head_b")

    seen = await _ok(await campus_b.get(ANALYTICS, params={"min_sessions": 1}))
    assert [r["section_id"] for r in seen["sections"]] == [campus_b.section_id]
    assert seen["summary"]["percentage"] is None
    assert seen["at_risk"] == []
    listed = await _ok(await campus_b.get(STUDENTS, params={"size": 50}))
    assert set(campus_a.student_ids).isdisjoint(r["student_id"] for r in listed["items"])

    for response in (
        await campus_b.get(ANALYTICS, params={"class_id": campus_a.class_id}),
        await campus_b.get(STUDENTS, params={"class_id": campus_a.class_id}),
        await campus_b.get(STUDENTS, params={"section_id": campus_a.section_id}),
        await campus_b.get(f"{STUDENTS}/{campus_a.student_ids[0]}/calendar"),
    ):
        assert response.status_code == 404, f"leaked across organizations: {response.text}"

    # A second campus of org A sees none of the first campus either.
    second = await org_a.post(f"{API}/schools", json={"name": "Second Campus", "code": "A2"})
    assert second.status_code == 201, second.text
    mailbox.clear()
    token = await make_campus_head(
        org_a, mailbox, "two@test.example", school_id=second.json()["id"], code="head_two"
    )
    headers = {"Authorization": f"Bearer {token}"}
    other = await _ok(await org_a.client.get(ANALYTICS, headers=headers))
    assert other["sections"] == []
    assert other["summary"]["counted"] == 0
    other_students = await _ok(await org_a.client.get(STUDENTS, headers=headers))
    assert other_students["items"] == []
    blocked = await org_a.client.get(
        f"{STUDENTS}/{campus_a.student_ids[0]}/calendar", headers=headers
    )
    assert blocked.status_code == 404, blocked.text


# ===========================================================================
# 4. Input and permission
# ===========================================================================


async def test_bad_ranges_and_parameters_are_refused(four: Campus) -> None:
    student = four.student_ids[0]
    for url in (ANALYTICS, STUDENTS, f"{STUDENTS}/{student}/calendar"):
        reversed_range = await four.get(url, params={"from_date": _day(0), "to_date": _day(1)})
        assert reversed_range.status_code == 422, reversed_range.text
        assert reversed_range.json()["code"] == "INVALID_DATE_RANGE"

        too_long = await four.get(url, params={"from_date": _day(400), "to_date": _day(0)})
        assert too_long.status_code == 422, too_long.text
        assert too_long.json()["code"] == "DATE_RANGE_TOO_LONG"

    for params in ({"threshold": 150}, {"threshold": -1}, {"min_sessions": 0}):
        rejected = await four.get(ANALYTICS, params=params)
        assert rejected.status_code == 422, rejected.text


async def test_attendance_read_is_required(
    four: Campus, tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    headers = await make_actor(
        tenant, mailbox, "noattendance@test.example", ["school:read"], code="no_attendance"
    )
    for url in (ANALYTICS, STUDENTS, f"{STUDENTS}/{four.student_ids[0]}/calendar"):
        response = await tenant.client.get(url, headers=headers)
        assert response.status_code == 403, f"{url}: {response.text}"
