"""PostgreSQL-backed tests for the teacher's view of exams, papers, marks, results.

The rule under test is the teaching scope (`academics/teaching_scope.py`) carried
into the gradebook: a paper is visible when its (class, subject) is one the
teacher answers for, and a mark row when its student sits in a section they
teach. So the maths teacher of Grade 9 sees only maths, in every section; the
class teacher of 9-A sees every subject of Grade 9, but only 9-A's students. The
campus head who built the school still sees everything.
"""

from __future__ import annotations

from typing import Any

import pytest

from app.common.email.sender import EmailMessage
from tests.integration.conftest import API, Tenant
from tests.integration.staff import Staff, _subject, _teacher
from tests.integration.test_academic_foundation import Campus, build_campus
from tests.integration.test_teaching_scope import _section, _student

pytestmark = pytest.mark.asyncio


async def _send(staff: Staff, method: str, url: str, **kw: Any) -> Any:
    """`Staff` carries only GET/PUT; the write endpoints need the rest."""
    return await staff.tenant.client.request(method, url, headers=staff.headers, **kw)


async def _paper(campus: Campus, exam_id: str, class_id: str, subject_id: str) -> str:
    created = await campus.post(
        f"{API}/exams/{exam_id}/papers",
        json={"class_id": class_id, "subject_id": subject_id, "max_marks": 100},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def _exam(campus: Campus, name: str) -> str:
    created = await campus.post(f"{API}/exams", json={"name": name})
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


class Gradebook:
    """Grade 9 (A, B) and Grade 10 (A); "Mid-Term" sits Grade 9 maths and Urdu and
    Grade 10 Urdu; "G10 Test" sits Grade 10 alone."""

    def __init__(self, campus: Campus) -> None:
        self.campus = campus
        self.class_10 = ""
        self.student_9b = ""
        self.student_10a = ""
        self.exam_id = ""
        self.g10_exam_id = ""
        self.maths_9 = ""
        self.urdu_9 = ""
        self.urdu_10 = ""
        self.maths_subject = ""
        self.urdu_subject = ""
        self.class_teacher: Staff
        self.maths_teacher: Staff
        self.outsider: Staff


@pytest.fixture
async def book(tenant: Tenant, mailbox: list[EmailMessage]) -> Gradebook:
    campus = await build_campus(tenant, mailbox)
    built = Gradebook(campus)

    section_9b = await _section(campus, campus.class_id, "B")
    grade_10 = await campus.post(f"{API}/classes", json={"name": "Grade 10", "level": 10})
    assert grade_10.status_code == 201, grade_10.text
    built.class_10 = grade_10.json()["id"]
    section_10a = await _section(campus, built.class_10, "A")
    built.student_9b = await _student(campus, "S-9B", "Nineb", section_9b)
    built.student_10a = await _student(campus, "S-10A", "Tena", section_10a)

    built.class_teacher = await _teacher(tenant, "ct9a@test.example", "Class Teacher")
    built.maths_teacher = await _teacher(tenant, "maths@test.example", "Maths Teacher")
    built.outsider = await _teacher(tenant, "other@test.example", "Other Teacher")
    assigned = await campus.patch(
        f"{API}/classes/sections/{campus.section_id}",
        json={"class_teacher_id": built.class_teacher.user_id},
    )
    assert assigned.status_code == 200, assigned.text

    built.urdu_subject = await _subject(campus, "URDU")
    built.maths_subject = await _subject(campus, "MATH", teacher_id=built.maths_teacher.user_id)

    built.exam_id = await _exam(campus, "Mid-Term")
    built.maths_9 = await _paper(campus, built.exam_id, campus.class_id, built.maths_subject)
    built.urdu_9 = await _paper(campus, built.exam_id, campus.class_id, built.urdu_subject)
    built.urdu_10 = await _paper(campus, built.exam_id, built.class_10, built.urdu_subject)
    built.g10_exam_id = await _exam(campus, "G10 Test")
    await _paper(campus, built.g10_exam_id, built.class_10, built.urdu_subject)

    # Marks across both Grade 9 sections, entered by the administrator.
    saved = await campus.put(
        f"{API}/exams/papers/{built.maths_9}/marks",
        json={
            "entries": [
                {"student_id": campus.student_ids[0], "marks_obtained": "70"},
                {"student_id": built.student_9b, "marks_obtained": "90"},
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    return built


def _row_ids(sheet: Any) -> set[str]:
    assert sheet.status_code == 200, sheet.text
    return {row["student_id"] for row in sheet.json()["rows"]}


async def test_subject_teacher_sees_only_their_subject(book: Gradebook) -> None:
    campus, teacher = book.campus, book.maths_teacher

    exams = await teacher.get(f"{API}/exams")
    assert exams.status_code == 200, exams.text
    listed = {e["name"]: e["paper_count"] for e in exams.json()["items"]}
    assert listed == {"Mid-Term": 1}  # their one paper; G10 Test is not theirs
    assert (await teacher.get(f"{API}/exams/{book.g10_exam_id}")).status_code == 404

    papers = await teacher.get(f"{API}/exams/{book.exam_id}/papers")
    assert [p["id"] for p in papers.json()] == [book.maths_9]
    assert papers.json()[0]["marks_entered"] == 2

    # Every section of Grade 9 on the maths sheet; the Urdu sheet does not exist.
    sheet = await teacher.get(f"{API}/exams/papers/{book.maths_9}/marks")
    assert _row_ids(sheet) == {*campus.student_ids, book.student_9b}
    assert (await teacher.get(f"{API}/exams/papers/{book.urdu_9}/marks")).status_code == 404

    results = await teacher.get(
        f"{API}/exams/{book.exam_id}/results", params={"class_id": campus.class_id}
    )
    assert results.status_code == 200, results.text
    assert [p["id"] for p in results.json()["papers"]] == [book.maths_9]
    assert _row_ids(results) == {*campus.student_ids, book.student_9b}
    other_class = await teacher.get(
        f"{API}/exams/{book.exam_id}/results", params={"class_id": book.class_10}
    )
    assert other_class.status_code == 404, other_class.text


async def test_class_teacher_sees_every_subject_but_only_their_section(
    book: Gradebook,
) -> None:
    campus, teacher = book.campus, book.class_teacher

    papers = await teacher.get(f"{API}/exams/{book.exam_id}/papers")
    assert {p["id"] for p in papers.json()} == {book.maths_9, book.urdu_9}
    # Only 9-A's mark counts -- the count matches the sheet they open.
    assert {p["id"]: p["marks_entered"] for p in papers.json()}[book.maths_9] == 1

    sheet = await teacher.get(f"{API}/exams/papers/{book.maths_9}/marks")
    assert _row_ids(sheet) == set(campus.student_ids)  # 9-B's student is not there
    assert (await teacher.get(f"{API}/exams/papers/{book.urdu_10}/marks")).status_code == 404

    results = await teacher.get(
        f"{API}/exams/{book.exam_id}/results", params={"class_id": campus.class_id}
    )
    assert {p["id"] for p in results.json()["papers"]} == {book.maths_9, book.urdu_9}
    assert _row_ids(results) == set(campus.student_ids)


async def test_marks_outside_scope_are_refused(book: Gradebook) -> None:
    campus, teacher = book.campus, book.class_teacher
    url = f"{API}/exams/papers/{book.maths_9}/marks"

    # A student of 9-B on the Grade 9 maths sheet: in the class, not in their section.
    stray = await teacher.put(
        url, json={"entries": [{"student_id": book.student_9b, "marks_obtained": "10"}]}
    )
    assert stray.status_code == 422, stray.text
    mine = await teacher.put(
        url, json={"entries": [{"student_id": campus.student_ids[1], "marks_obtained": "55"}]}
    )
    assert mine.status_code == 200, mine.text

    # The 9-B mark the refusal protected is untouched.
    sheet = await campus.get(url)
    marks = {r["student_id"]: r["marks_obtained"] for r in sheet.json()["rows"]}
    assert float(marks[book.student_9b]) == 90.0

    # A paper they cannot see is a 404 for writes too.
    hidden = await teacher.put(
        f"{API}/exams/papers/{book.urdu_10}/marks",
        json={"entries": [{"student_id": book.student_10a, "marks_obtained": "10"}]},
    )
    assert hidden.status_code == 404, hidden.text


async def test_papers_are_set_and_changed_only_within_scope(book: Gradebook) -> None:
    campus, teacher = book.campus, book.maths_teacher

    urdu = await _send(
        teacher,
        "POST",
        f"{API}/exams/{book.exam_id}/papers",
        json={"class_id": campus.class_id, "subject_id": book.urdu_subject},
    )
    assert urdu.status_code == 404, urdu.text  # Grade 9 Urdu is not theirs
    edit = await _send(
        teacher, "PATCH", f"{API}/exams/papers/{book.urdu_9}", json={"max_marks": 50}
    )
    assert edit.status_code == 404, edit.text
    removed = await _send(teacher, "DELETE", f"{API}/exams/papers/{book.urdu_9}")
    assert removed.status_code == 404, removed.text

    # Mid-Term is shared with papers they cannot see: they may not rename it.
    renamed = await _send(teacher, "PATCH", f"{API}/exams/{book.exam_id}", json={"name": "Renamed"})
    assert renamed.status_code == 403, renamed.text

    # Their own exam, with their own paper, is theirs to run.
    own = await _send(teacher, "POST", f"{API}/exams", json={"name": "Maths Quiz"})
    assert own.status_code == 201, own.text
    quiz = own.json()["id"]
    added = await _send(
        teacher,
        "POST",
        f"{API}/exams/{quiz}/papers",
        json={"class_id": campus.class_id, "subject_id": book.maths_subject},
    )
    assert added.status_code == 201, added.text
    status = await _send(teacher, "PATCH", f"{API}/exams/{quiz}", json={"status": "completed"})
    assert status.status_code == 200, status.text


async def test_unassigned_teacher_sees_nothing(book: Gradebook) -> None:
    teacher = book.outsider

    assert (await teacher.get(f"{API}/exams")).json()["items"] == []
    assert (await teacher.get(f"{API}/exams/{book.exam_id}")).status_code == 404
    assert (await teacher.get(f"{API}/exams/{book.exam_id}/papers")).status_code == 404
    assert (await teacher.get(f"{API}/exams/papers/{book.maths_9}/marks")).status_code == 404
    results = await teacher.get(
        f"{API}/exams/{book.exam_id}/results", params={"class_id": book.campus.class_id}
    )
    assert results.status_code == 404, results.text
    write = await teacher.put(
        f"{API}/exams/papers/{book.maths_9}/marks",
        json={"entries": [{"student_id": book.campus.student_ids[0], "marks_obtained": "1"}]},
    )
    assert write.status_code == 404, write.text


async def test_administrator_still_sees_everything(book: Gradebook) -> None:
    campus = book.campus

    exams = await campus.get(f"{API}/exams")
    listed = {e["name"]: e["paper_count"] for e in exams.json()["items"]}
    assert listed == {"Mid-Term": 3, "G10 Test": 1}

    papers = await campus.get(f"{API}/exams/{book.exam_id}/papers")
    assert {p["id"] for p in papers.json()} == {book.maths_9, book.urdu_9, book.urdu_10}

    sheet = await campus.get(f"{API}/exams/papers/{book.maths_9}/marks")
    assert _row_ids(sheet) == {*campus.student_ids, book.student_9b}
