"""PostgreSQL-backed tests for the teacher's view of attendance and the dashboard.

The rule under test: a teacher without `class:view_all` reads and writes registers
only for the sections they are assigned to, and the dashboard counts only those
sections. Anything outside them is a 404 worded exactly like an unknown id. An
administrator (the campus head who built the school) still sees everything.

School shape (from `test_teaching_scope.school`): Grade 9-A with three students,
Grade 9-B with one, Grade 10-A with one.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any
from uuid import uuid4

import pytest

from tests.integration.conftest import API
from tests.integration.staff import Staff, _subject, _teacher
from tests.integration.test_academic_foundation import TODAY, Campus
from tests.integration.test_teaching_scope import School, _class_teacher_of_9a, school

pytestmark = pytest.mark.asyncio

__all__ = ["school"]  # the fixture, re-exported so pytest finds it here

ANALYTICS = f"{API}/dashboard/analytics"
RANGE = {"from_date": str(TODAY), "to_date": str(TODAY)}


async def _post(staff: Staff, url: str, **kw: Any) -> Any:
    return await staff.tenant.client.post(url, headers=staff.headers, **kw)


async def _patch(staff: Staff, url: str, **kw: Any) -> Any:
    return await staff.tenant.client.patch(url, headers=staff.headers, **kw)


async def _delete(staff: Staff, url: str) -> Any:
    return await staff.tenant.client.delete(url, headers=staff.headers)


async def _open(campus: Campus, section_id: str) -> str:
    opened = await campus.post(f"{API}/attendance", json={"section_id": section_id})
    assert opened.status_code == 201, opened.text
    return str(opened.json()["id"])


def _same_404(hidden: Any, unknown: Any) -> None:
    """Out of scope must be indistinguishable from never existed."""
    assert hidden.status_code == 404, hidden.text
    assert unknown.status_code == 404, unknown.text
    assert hidden.json().get("message") == unknown.json().get("message")
    assert hidden.json().get("code") == unknown.json().get("code")


async def test_class_teacher_marks_only_their_own_section(school: School) -> None:
    campus = school.campus
    teacher = await _class_teacher_of_9a(school)

    # Their own register: open, mark, submit.
    opened = await _post(teacher, f"{API}/attendance", json={"section_id": campus.section_id})
    assert opened.status_code == 201, opened.text
    own = opened.json()["id"]
    marked = await _patch(
        teacher,
        f"{API}/attendance/{own}/entries",
        json={"entries": [{"student_id": campus.student_ids[0], "status": "absent"}]},
    )
    assert marked.status_code == 200, marked.text
    assert (await _post(teacher, f"{API}/attendance/{own}/submit")).status_code == 200

    # Someone else's section cannot even be opened.
    _same_404(
        await _post(teacher, f"{API}/attendance", json={"section_id": school.section_10a}),
        await _post(teacher, f"{API}/attendance", json={"section_id": str(uuid4())}),
    )

    # Nor can a register the administrator opened there be reached by id.
    other = await _open(campus, school.section_10a)
    unknown = str(uuid4())
    _same_404(
        await teacher.get(f"{API}/attendance/{other}"),
        await teacher.get(f"{API}/attendance/{unknown}"),
    )
    entries = {"entries": [{"student_id": school.student_10a, "status": "absent"}]}
    assert (
        await _patch(teacher, f"{API}/attendance/{other}/entries", json=entries)
    ).status_code == 404
    assert (await _post(teacher, f"{API}/attendance/{other}/submit")).status_code == 404
    assert (await _delete(teacher, f"{API}/attendance/{other}")).status_code == 404

    # ...and it is untouched: still a draft, everyone still present.
    untouched = (await campus.get(f"{API}/attendance/{other}")).json()
    assert untouched["status"] == "draft"
    assert untouched["absent_count"] == 0


async def test_teacher_is_locked_out_once_the_day_after_has_passed(school: School) -> None:
    """Rule 3 of the service: `attendance:mark` reaches a register through the day
    after its date. After that it is locked, draft or not, and only an amender can
    change it."""
    campus = school.campus
    teacher = await _class_teacher_of_9a(school)
    yesterday = str(TODAY - timedelta(days=1))
    two_days_ago = str(TODAY - timedelta(days=2))

    # Yesterday is still inside the window.
    opened = await _post(
        teacher,
        f"{API}/attendance",
        json={"section_id": campus.section_id, "session_date": yesterday},
    )
    assert opened.status_code == 201, opened.text
    assert opened.json()["locked"] is False

    # The day before is not -- not even to open.
    refused = await _post(
        teacher,
        f"{API}/attendance",
        json={"section_id": campus.section_id, "session_date": two_days_ago},
    )
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "ATTENDANCE_LOCKED"

    # A draft the administrator left there is locked to the teacher as well.
    stale = await campus.post(
        f"{API}/attendance",
        json={"section_id": campus.section_id, "session_date": two_days_ago},
    )
    assert stale.status_code == 201, stale.text
    stale_id = stale.json()["id"]
    detail = await teacher.get(f"{API}/attendance/{stale_id}")
    assert detail.json()["locked"] is True
    entries = {"entries": [{"student_id": campus.student_ids[0], "status": "absent"}]}
    for response in (
        await _patch(teacher, f"{API}/attendance/{stale_id}/entries", json=entries),
        await _post(teacher, f"{API}/attendance/{stale_id}/submit"),
        await _delete(teacher, f"{API}/attendance/{stale_id}"),
    ):
        assert response.status_code == 409, response.text
        assert response.json()["code"] == "ATTENDANCE_LOCKED"

    board = await teacher.get(f"{API}/attendance/today", params={"date": two_days_ago})
    assert board.json()["locked"] is True
    assert (await teacher.get(f"{API}/attendance/today")).json()["locked"] is False

    # The amender is not locked out.
    marked = await campus.patch(f"{API}/attendance/{stale_id}/entries", json=entries)
    assert marked.status_code == 200, marked.text
    submitted = await campus.post(f"{API}/attendance/{stale_id}/submit")
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["absent_count"] == 1


async def test_class_teacher_reads_only_their_own_section(school: School) -> None:
    campus = school.campus
    teacher = await _class_teacher_of_9a(school)
    own = await _open(campus, campus.section_id)
    await _open(campus, school.section_10a)

    overview = await teacher.get(f"{API}/attendance/today")
    assert overview.status_code == 200, overview.text
    body = overview.json()
    assert [s["section_id"] for s in body["sections"]] == [campus.section_id]
    assert body["sections_total"] == 1
    assert body["sections"][0]["session_id"] == own

    listed = await teacher.get(f"{API}/attendance")
    assert listed.status_code == 200, listed.text
    assert [r["id"] for r in listed.json()["items"]] == [own]
    # Filtering by a section outside their classes narrows to nothing, not to it.
    filtered = await teacher.get(f"{API}/attendance", params={"section_id": school.section_10a})
    assert filtered.json()["items"] == []

    assert (await teacher.get(f"{API}/attendance/{own}")).status_code == 200

    summary = f"{API}/attendance/students/{{}}/summary"
    assert (
        await teacher.get(summary.format(campus.student_ids[0]), params=RANGE)
    ).status_code == 200
    _same_404(
        await teacher.get(summary.format(school.student_10a), params=RANGE),
        await teacher.get(summary.format(uuid4()), params=RANGE),
    )

    report = f"{API}/attendance/sections/{{}}/report"
    assert (await teacher.get(report.format(campus.section_id), params=RANGE)).status_code == 200
    _same_404(
        await teacher.get(report.format(school.section_9b), params=RANGE),
        await teacher.get(report.format(uuid4()), params=RANGE),
    )


async def test_subject_teacher_sees_every_section_of_their_class(school: School) -> None:
    campus = school.campus
    teacher = await _teacher(campus.tenant, "maths@test.example", "Maths Teacher")
    await _subject(campus, "MATH", teacher_id=teacher.user_id)

    overview = (await teacher.get(f"{API}/attendance/today")).json()
    assert {s["section_id"] for s in overview["sections"]} == {
        campus.section_id,
        school.section_9b,
    }
    opened = await _post(teacher, f"{API}/attendance", json={"section_id": school.section_9b})
    assert opened.status_code == 201, opened.text


async def test_unassigned_teacher_sees_nothing(school: School) -> None:
    await _open(school.campus, school.campus.section_id)
    teacher = await _teacher(school.campus.tenant, "new@test.example", "New Teacher")

    overview = (await teacher.get(f"{API}/attendance/today")).json()
    assert overview["sections"] == []
    assert overview["sections_total"] == 0
    assert (await teacher.get(f"{API}/attendance")).json()["items"] == []


async def test_administrator_still_sees_everything(school: School) -> None:
    campus = school.campus
    await _class_teacher_of_9a(school)
    await _open(campus, campus.section_id)
    await _open(campus, school.section_10a)

    overview = (await campus.get(f"{API}/attendance/today")).json()
    assert overview["sections_total"] == 3
    assert len((await campus.get(f"{API}/attendance")).json()["items"]) == 2
    report_url = f"{API}/attendance/sections/{school.section_10a}/report"
    report = await campus.get(report_url, params=RANGE)
    assert report.status_code == 200, report.text


async def test_dashboard_counts_only_the_teachers_sections(school: School) -> None:
    campus = school.campus
    teacher = await _class_teacher_of_9a(school)
    for section in (campus.section_id, school.section_10a):
        session_id = await _open(campus, section)
        assert (await campus.post(f"{API}/attendance/{session_id}/submit")).status_code == 200

    admin = (await campus.get(ANALYTICS)).json()
    assert admin["students"]["active"] == 5
    assert admin["attendance"]["today"]["sections_total"] == 3
    assert admin["attendance"]["today"]["sections_submitted"] == 2
    assert admin["attendance"]["today"]["mix"]["present"] == 4

    response = await teacher.get(ANALYTICS)
    assert response.status_code == 200, response.text
    mine = response.json()
    assert mine["students"]["active"] == 3
    assert mine["students"]["by_class"] == [{"class_name": "Grade 9", "level": 9, "count": 3}]
    assert sum(g["count"] for g in mine["students"]["gender"]) == 3
    assert mine["attendance"]["today"]["sections_total"] == 1
    assert mine["attendance"]["today"]["sections_submitted"] == 1
    assert mine["attendance"]["today"]["mix"]["present"] == 3


async def _paper(campus: Campus, exam_id: str, class_id: str, subject_id: str) -> str:
    created = await campus.post(
        f"{API}/exams/{exam_id}/papers",
        json={"class_id": class_id, "subject_id": subject_id, "max_marks": 50},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def _marks(campus: Campus, paper_id: str, student_ids: list[str], marks: str) -> None:
    saved = await campus.put(
        f"{API}/exams/papers/{paper_id}/marks",
        json={"entries": [{"student_id": s, "marks_obtained": marks} for s in student_ids]},
    )
    assert saved.status_code == 200, saved.text


async def test_dashboard_exams_are_bounded_by_pupil_and_subject(school: School) -> None:
    campus = school.campus
    class_teacher = await _class_teacher_of_9a(school)
    maths_teacher = await _teacher(campus.tenant, "maths@test.example", "Maths Teacher")
    maths = await _subject(campus, "MATH", teacher_id=maths_teacher.user_id)
    english = await _subject(campus, "ENG")
    art = await campus.post(f"{API}/subjects", json={"code": "ART", "name": "Subject ART"})
    assert art.status_code == 201, art.text

    exam = await campus.post(f"{API}/exams", json={"name": "Mid-Term"})
    assert exam.status_code == 201, exam.text
    exam_id = exam.json()["id"]
    grade_9 = [*campus.student_ids, school.student_9b]
    await _marks(campus, await _paper(campus, exam_id, campus.class_id, maths), grade_9, "40")
    await _marks(campus, await _paper(campus, exam_id, campus.class_id, english), grade_9, "30")
    art_paper = await _paper(campus, exam_id, school.class_10, art.json()["id"])
    await _marks(campus, art_paper, [school.student_10a], "20")

    def sat(body: dict[str, Any]) -> dict[str, int]:
        return {s["subject"]: s["sat"] for s in body["exams"]["subjects"]}

    admin = (await campus.get(ANALYTICS)).json()
    assert sat(admin) == {"Subject MATH": 4, "Subject ENG": 4, "Subject ART": 1}

    # Class teacher of 9-A: every Grade 9 subject, only 9-A's three pupils.
    assert sat((await class_teacher.get(ANALYTICS)).json()) == {
        "Subject MATH": 3,
        "Subject ENG": 3,
    }
    # Maths teacher of Grade 9: both sections, only maths.
    assert sat((await maths_teacher.get(ANALYTICS)).json()) == {"Subject MATH": 4}

    # Nobody's pupils, nobody's subjects: no exam to chart at all.
    outsider = await _teacher(campus.tenant, "new@test.example", "New Teacher")
    assert (await outsider.get(ANALYTICS)).json()["exams"] is None


async def test_global_search_finds_registers_only_inside_the_teachers_sections(
    school: School,
) -> None:
    """The omnibar's Attendance group draws the same boundary as `GET /attendance/{id}`:
    the administrator finds every register for the day, the class teacher of 9-A only
    their own -- and each hit links straight to the register it names."""
    campus = school.campus
    teacher = await _class_teacher_of_9a(school)
    own = await _open(campus, campus.section_id)
    other = await _open(campus, school.section_10a)
    query = {"q": f"type:attendance {TODAY}"}

    def registers(body: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            hit["id"]: hit
            for group in body["groups"]
            if group["type"] == "attendance"
            for hit in group["hits"]
        }

    admin = await campus.get(f"{API}/search", params=query)
    assert admin.status_code == 200, admin.text
    found = registers(admin.json())
    assert set(found) == {own, other}
    assert found[own]["title"] == "Grade 9 — A"
    assert found[own]["subtitle"] == f"{TODAY} · Whole day"
    assert found[own]["status"] == "draft"
    assert found[own]["url"] == f"/attendance?session={own}"

    # Neither is submitted yet, so the register's own lifecycle filter finds nothing.
    submitted = await campus.get(f"{API}/search", params={"q": "type:attendance status:submitted"})
    assert registers(submitted.json()) == {}

    taught = await teacher.get(f"{API}/search", params=query)
    assert taught.status_code == 200, taught.text
    assert set(registers(taught.json())) == {own}
