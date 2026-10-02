"""Dashboard analytics.

The endpoint reads from four modules under one route with no `require(...)`, so the
cases lean on the boundary as much as on the arithmetic: a section the caller may
not read must come back null rather than computed, and the attendance rate must
follow the same LATE / HALF_DAY / EXCUSED rules as the module's own reports.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.common.email.sender import EmailMessage
from tests.integration.conftest import API, Tenant
from tests.integration.test_academic_foundation import TODAY, Campus, build_campus, make_actor

pytestmark = pytest.mark.asyncio

ANALYTICS = f"{API}/dashboard/analytics"


@pytest.fixture
async def campus(tenant: Tenant, mailbox: list[EmailMessage]) -> Campus:
    return await build_campus(tenant, mailbox, students=4)


async def _submit(campus: Campus, offset: int, statuses: dict[int, str]) -> None:
    opened = await campus.post(
        f"{API}/attendance",
        json={"section_id": campus.section_id, "session_date": str(TODAY - timedelta(days=offset))},
    )
    assert opened.status_code in (200, 201), opened.text
    session_id = opened.json()["id"]
    marked = await campus.patch(
        f"{API}/attendance/{session_id}/entries",
        json={
            "entries": [
                {"student_id": campus.student_ids[i], "status": s} for i, s in statuses.items()
            ]
        },
    )
    assert marked.status_code == 200, marked.text
    submitted = await campus.post(f"{API}/attendance/{session_id}/submit")
    assert submitted.status_code == 200, submitted.text


async def test_students_and_attendance_add_up(campus: Campus) -> None:
    # Today: present, late, half_day, excused -> (1 + 1 + 0.5) / 3 counted.
    await _submit(campus, 0, {1: "late", 2: "half_day", 3: "excused"})
    # Two days ago: one absent out of four.
    await _submit(campus, 2, {0: "absent"})

    response = await campus.get(ANALYTICS)
    assert response.status_code == 200, response.text
    body = response.json()

    students = body["students"]
    assert students["active"] == 4
    assert students["unplaced"] == 0
    assert students["by_class"] == [{"class_name": "Grade 9", "level": 9, "count": 4}]
    assert sum(s["count"] for s in students["gender"]) == 4

    attendance = body["attendance"]
    assert attendance["today"]["sections_total"] == 1
    assert attendance["today"]["sections_submitted"] == 1
    assert attendance["today"]["rate"] == pytest.approx(2.5 / 3, abs=1e-4)
    assert attendance["today"]["mix"]["excused"] == 1

    days = attendance["days"]
    assert len(days) == 35
    assert days[-1]["day"] == str(TODAY)
    assert days[-3]["rate"] == pytest.approx(0.75)
    # A day nobody marked is unknown, not zero.
    assert days[-2]["rate"] is None and days[-2]["marked"] == 0

    # (2.5 + 3) / (3 + 4) over the window; nothing in the window before it.
    assert attendance["rate_30d"] == pytest.approx(5.5 / 7, abs=1e-4)
    assert attendance["rate_prev_30d"] is None
    assert attendance["mix_30d"]["absent"] == 1

    fees = body["fees"]
    assert len(fees["months"]) == 12
    assert fees["months"][-1]["month"] == TODAY.strftime("%Y-%m")
    assert fees["collection_rate"] is None  # nothing billed yet

    # No exam has any marks, so there is nothing to chart.
    assert body["exams"] is None


async def test_sections_without_permission_are_null(
    campus: Campus, tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    headers = await make_actor(
        tenant, mailbox, "register@test.example", ["attendance:read"], code="register_only"
    )
    response = await tenant.client.get(ANALYTICS, headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()

    assert body["attendance"] is not None
    assert body["students"] is None
    assert body["fees"] is None
    assert body["exams"] is None


async def test_exam_subjects_rank_by_average(campus: Campus) -> None:
    async def paper(exam_id: str, code: str, pass_marks: int | None) -> str:
        subject = await campus.post(f"{API}/subjects", json={"code": code, "name": code.title()})
        assert subject.status_code == 201, subject.text
        body = {"class_id": campus.class_id, "subject_id": subject.json()["id"], "max_marks": 50}
        if pass_marks is not None:
            body["pass_marks"] = pass_marks
        created = await campus.post(f"{API}/exams/{exam_id}/papers", json=body)
        assert created.status_code == 201, created.text
        return created.json()["id"]

    exam = await campus.post(f"{API}/exams", json={"name": "Mid-Term"})
    assert exam.status_code == 201, exam.text
    math = await paper(exam.json()["id"], "MATH", 20)
    art = await paper(exam.json()["id"], "ART", None)

    ids = campus.student_ids
    for paper_id, entries in (
        (math, [("10",), ("30",), ("40",), (None,)]),
        (art, [("45",), ("45",), (None,), (None,)]),
    ):
        saved = await campus.put(
            f"{API}/exams/papers/{paper_id}/marks",
            json={
                "entries": [
                    {"student_id": ids[i], "marks_obtained": m}
                    if m is not None
                    else {"student_id": ids[i], "is_absent": True}
                    for i, (m,) in enumerate(entries)
                ]
            },
        )
        assert saved.status_code == 200, saved.text

    exams = (await campus.get(ANALYTICS)).json()["exams"]
    assert exams["exam_name"] == "Mid-Term"
    # Absentees are not graded sittings: ART is 90% over two, MATH 53.3% over three.
    assert [s["subject"] for s in exams["subjects"]] == ["Art", "Math"]
    art_row, math_row = exams["subjects"]
    assert art_row == {"subject": "Art", "average_pct": 90.0, "pass_rate": None, "sat": 2}
    assert math_row["average_pct"] == pytest.approx(53.3)
    assert math_row["pass_rate"] == pytest.approx(2 / 3, abs=1e-4)
    assert math_row["sat"] == 3
