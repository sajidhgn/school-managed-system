"""PostgreSQL-backed tests for the exam module: exams, papers, marks, results.

Runs against real PostgreSQL as the restricted role for the same reasons the
academic foundation suite does: the guarantees under test -- the one-paper-per-
subject-per-class uniqueness, the absent-XOR-marks CHECK, RESTRICT on the
dimensions, and RLS -- live in the database, and a mocked suite would pass
without any of them.
"""

from __future__ import annotations

import pytest

from app.common.email.sender import EmailMessage
from tests.integration.conftest import API, Tenant
from tests.integration.test_academic_foundation import Campus, build_campus

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def campus(tenant: Tenant, mailbox: list[EmailMessage]) -> Campus:
    return await build_campus(tenant, mailbox)


async def _make_subject(campus: Campus, code: str = "MATH") -> str:
    created = await campus.post(
        f"{API}/subjects", json={"code": code, "name": f"Subject {code}"}
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def _make_exam(campus: Campus, name: str = "Mid-Term") -> str:
    created = await campus.post(f"{API}/exams", json={"name": name})
    assert created.status_code == 201, created.text
    return created.json()["id"]


async def _make_paper(campus: Campus, exam_id: str, subject_id: str, **extra) -> str:
    created = await campus.post(
        f"{API}/exams/{exam_id}/papers",
        json={"class_id": campus.class_id, "subject_id": subject_id, "max_marks": 100, **extra},
    )
    assert created.status_code == 201, created.text
    return created.json()["id"]


# ---------------------------------------------------------------------------
# The happy path: schedule, sit, mark, rank
# ---------------------------------------------------------------------------


async def test_exam_paper_marks_and_results_flow(campus: Campus) -> None:
    subject_id = await _make_subject(campus)
    exam_id = await _make_exam(campus)
    paper_id = await _make_paper(campus, exam_id, subject_id, pass_marks=40)

    # The sheet lists every enrolled student of the class, none entered yet.
    sheet = await campus.get(f"{API}/exams/papers/{paper_id}/marks")
    assert sheet.status_code == 200, sheet.text
    rows = sheet.json()["rows"]
    assert len(rows) == len(campus.student_ids)
    assert all(row["entered"] is False for row in rows)

    # Mark two, leave one absent.
    saved = await campus.put(
        f"{API}/exams/papers/{paper_id}/marks",
        json={
            "entries": [
                {"student_id": campus.student_ids[0], "marks_obtained": "91.5"},
                {"student_id": campus.student_ids[1], "marks_obtained": "76"},
                {"student_id": campus.student_ids[2], "is_absent": True},
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["saved"] == 3

    # Re-saving corrects rather than conflicts (upsert semantics).
    corrected = await campus.put(
        f"{API}/exams/papers/{paper_id}/marks",
        json={"entries": [{"student_id": campus.student_ids[1], "marks_obtained": "80"}]},
    )
    assert corrected.status_code == 200, corrected.text

    results = await campus.get(
        f"{API}/exams/{exam_id}/results", params={"class_id": campus.class_id}
    )
    assert results.status_code == 200, results.text
    body = results.json()
    by_rank = [(row["rank"], row["student_id"], row["percentage"]) for row in body["rows"]]
    assert by_rank[0][1] == campus.student_ids[0]  # 91.5%
    assert by_rank[0][0] == 1
    assert by_rank[1][1] == campus.student_ids[1]  # 80%
    # The absent student sat the paper (counts against them) and ranks last at 0%.
    assert by_rank[2][1] == campus.student_ids[2]
    assert float(by_rank[2][2]) == 0.0


async def test_students_directory_filters_by_exam_result(campus: Campus) -> None:
    """`GET /students?exam=...&result=...` -- the directory's results filter."""
    subject_id = await _make_subject(campus)
    exam_id = await _make_exam(campus)
    paper_id = await _make_paper(campus, exam_id, subject_id, pass_marks=40)

    await campus.put(
        f"{API}/exams/papers/{paper_id}/marks",
        json={
            "entries": [
                {"student_id": campus.student_ids[0], "marks_obtained": "85"},  # passed
                {"student_id": campus.student_ids[1], "marks_obtained": "20"},  # failed
                {"student_id": campus.student_ids[2], "is_absent": True},  # absent
            ]
        },
    )

    async def ids_for(result: str | None) -> set[str]:
        params: dict[str, str] = {"exam": exam_id}
        if result:
            params["result"] = result
        listed = await campus.get(f"{API}/students", params=params)
        assert listed.status_code == 200, listed.text
        return {row["id"] for row in listed.json()["items"]}

    assert await ids_for("passed") == {campus.student_ids[0]}
    assert await ids_for("failed") == {campus.student_ids[1]}
    assert await ids_for("absent") == {campus.student_ids[2]}
    assert await ids_for(None) == set(campus.student_ids)  # everyone marked

    # Each filtered row carries the totals the filter is relative to.
    listed = await campus.get(f"{API}/students", params={"exam": exam_id, "result": "failed"})
    row = listed.json()["items"][0]
    assert row["exam_result"]["failed_papers"] == 1
    assert float(row["exam_result"]["percentage"]) == 20.0

    # An unfiltered directory carries no marks at all.
    plain = await campus.get(f"{API}/students")
    assert all(row["exam_result"] is None for row in plain.json()["items"])

    # `result` without `exam` is refused, not ignored.
    dangling = await campus.get(f"{API}/students", params={"result": "failed"})
    assert dangling.status_code == 422, dangling.text


# ---------------------------------------------------------------------------
# Refusals: the invariants, each answered with a message rather than a 500
# ---------------------------------------------------------------------------


async def test_duplicate_paper_is_refused(campus: Campus) -> None:
    subject_id = await _make_subject(campus)
    exam_id = await _make_exam(campus)
    await _make_paper(campus, exam_id, subject_id)

    duplicate = await campus.post(
        f"{API}/exams/{exam_id}/papers",
        json={"class_id": campus.class_id, "subject_id": subject_id, "max_marks": 50},
    )
    assert duplicate.status_code == 409, duplicate.text


async def test_marks_above_maximum_are_refused(campus: Campus) -> None:
    subject_id = await _make_subject(campus)
    exam_id = await _make_exam(campus)
    paper_id = await _make_paper(campus, exam_id, subject_id)

    over = await campus.put(
        f"{API}/exams/papers/{paper_id}/marks",
        json={"entries": [{"student_id": campus.student_ids[0], "marks_obtained": "101"}]},
    )
    assert over.status_code == 422, over.text


async def test_stranger_to_the_class_cannot_be_marked(campus: Campus) -> None:
    subject_id = await _make_subject(campus)
    exam_id = await _make_exam(campus)
    paper_id = await _make_paper(campus, exam_id, subject_id)

    stray = await campus.put(
        f"{API}/exams/papers/{paper_id}/marks",
        json={
            "entries": [
                # A well-formed UUID that is not a student of this class.
                {"student_id": "00000000-0000-0000-0000-00000000dead", "marks_obtained": "50"}
            ]
        },
    )
    assert stray.status_code == 422, stray.text


async def test_marked_exam_and_paper_refuse_deletion(campus: Campus) -> None:
    subject_id = await _make_subject(campus)
    exam_id = await _make_exam(campus)
    paper_id = await _make_paper(campus, exam_id, subject_id)

    await campus.put(
        f"{API}/exams/papers/{paper_id}/marks",
        json={"entries": [{"student_id": campus.student_ids[0], "marks_obtained": "60"}]},
    )

    paper_delete = await campus.delete(f"{API}/exams/papers/{paper_id}")
    assert paper_delete.status_code == 409, paper_delete.text
    exam_delete = await campus.delete(f"{API}/exams/{exam_id}")
    assert exam_delete.status_code == 409, exam_delete.text

    # An unmarked exam deletes cleanly.
    empty_exam = await _make_exam(campus, name="Weekly Quiz")
    deleted = await campus.delete(f"{API}/exams/{empty_exam}")
    assert deleted.status_code == 204, deleted.text


async def test_absent_with_marks_is_refused(campus: Campus) -> None:
    subject_id = await _make_subject(campus)
    exam_id = await _make_exam(campus)
    paper_id = await _make_paper(campus, exam_id, subject_id)

    contradiction = await campus.put(
        f"{API}/exams/papers/{paper_id}/marks",
        json={
            "entries": [
                {"student_id": campus.student_ids[0], "marks_obtained": "50", "is_absent": True}
            ]
        },
    )
    assert contradiction.status_code == 422, contradiction.text
