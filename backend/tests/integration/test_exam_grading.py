"""PostgreSQL-backed tests for the campus grading scale.

What is under test:

  1. EVERY CAMPUS STARTS ON THE CUSTOM SCALE -- the one the result card always
     printed -- so introducing the setting changed nobody's grade.
  2. ONE SCALE GRADES EVERYTHING. The overall grade, each paper's grade, and the
     sheet's legend all come from the saved bands, compared exactly at the boundary.
  3. A SCALE IS COMPLETE OR REFUSED. Every percentage must land in one band.
  4. POLICY, NOT MARKING. Teachers hold `grade:manage` to enter marks; they must not
     be able to move the A boundary.
  5. ISOLATION. A scale belongs to one campus; RLS refuses a raw cross-tenant insert.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.common.email.sender import EmailMessage
from tests.integration.conftest import API, Tenant, make_campus_head
from tests.integration.staff import _teacher
from tests.integration.test_academic_foundation import Campus, build_campus

pytestmark = pytest.mark.asyncio

CUSTOM = [
    {"min_percent": "80", "grade": "A1", "remark": "Exceptional"},
    {"min_percent": "70", "grade": "A", "remark": "Excellent"},
    {"min_percent": "60", "grade": "B"},
    {"min_percent": "50", "grade": "C"},
    {"min_percent": "40", "grade": "D"},
    {"min_percent": "33", "grade": "E"},
    {"min_percent": "0", "grade": "F", "remark": "Needs improvement"},
]


@pytest.fixture
async def campus(tenant: Tenant, mailbox: list[EmailMessage]) -> Campus:
    return await build_campus(tenant, mailbox)


async def _marked_exam(campus: Campus, entries: list[dict[str, Any]]) -> str:
    subject = await campus.post(f"{API}/subjects", json={"code": "MATH", "name": "Mathematics"})
    assert subject.status_code == 201, subject.text
    exam = await campus.post(f"{API}/exams", json={"name": "Mid-Term"})
    assert exam.status_code == 201, exam.text
    exam_id = str(exam.json()["id"])
    paper = await campus.post(
        f"{API}/exams/{exam_id}/papers",
        json={"class_id": campus.class_id, "subject_id": subject.json()["id"], "max_marks": 100},
    )
    assert paper.status_code == 201, paper.text
    saved = await campus.put(
        f"{API}/exams/papers/{paper.json()['id']}/marks", json={"entries": entries}
    )
    assert saved.status_code == 200, saved.text
    return exam_id


async def _sheet(campus: Campus, exam_id: str) -> dict[str, Any]:
    results = await campus.get(
        f"{API}/exams/{exam_id}/results", params={"class_id": campus.class_id}
    )
    assert results.status_code == 200, results.text
    body: dict[str, Any] = results.json()
    return body


def _by_student(sheet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["student_id"]: row for row in sheet["rows"]}


# ---------------------------------------------------------------------------
# 1. The board scale until a campus saves its own
# ---------------------------------------------------------------------------


async def test_a_new_campus_grades_on_the_board_scale(campus: Campus) -> None:
    scale = (await campus.get(f"{API}/exams/grading-scale")).json()
    assert scale["is_default"] is True and scale["id"] is None
    assert [band["grade"] for band in scale["bands"]] == ["A+", "A", "B", "C", "D", "E", "F"]

    exam_id = await _marked_exam(
        campus,
        [
            {"student_id": campus.student_ids[0], "marks_obtained": "91"},
            {"student_id": campus.student_ids[1], "marks_obtained": "32.5"},
        ],
    )
    sheet = await _sheet(campus, exam_id)
    rows = _by_student(sheet)
    assert (rows[campus.student_ids[0]]["grade"], rows[campus.student_ids[0]]["remark"]) == (
        "A+",
        "Excellent",
    )
    # Under 33 is the board's fail band.
    assert rows[campus.student_ids[1]]["grade"] == "F"
    assert sheet["grading_scale"][-1]["grade"] == "F"
    # Nothing marked is not 0%: no grade at all.
    unmarked = rows[campus.student_ids[2]]
    assert unmarked["grade"] is None and unmarked["cells"][0]["grade"] is None


# ---------------------------------------------------------------------------
# 2. One scale grades everything
# ---------------------------------------------------------------------------


async def test_the_scale_grades_rows_papers_and_the_legend(campus: Campus) -> None:
    # Sent in a scrambled order: the server stores and returns highest first.
    saved = await campus.put(f"{API}/exams/grading-scale", json={"bands": list(reversed(CUSTOM))})
    assert saved.status_code == 200, saved.text
    assert saved.json()["is_default"] is False
    stored = saved.json()["bands"]
    assert [band["grade"] for band in stored] == [band["grade"] for band in CUSTOM]
    assert stored[0]["remark"] == "Exceptional"

    exam_id = await _marked_exam(
        campus,
        [
            # Exactly on the A1 boundary: 80 is an A1, not an A.
            {"student_id": campus.student_ids[0], "marks_obtained": "80"},
            # Just below it.
            {"student_id": campus.student_ids[1], "marks_obtained": "79.5"},
            {"student_id": campus.student_ids[2], "is_absent": True},
        ],
    )
    sheet = await _sheet(campus, exam_id)
    rows = _by_student(sheet)

    top = rows[campus.student_ids[0]]
    assert (top["grade"], top["remark"]) == ("A1", "Exceptional")
    assert top["cells"][0]["grade"] == "A1"

    second = rows[campus.student_ids[1]]
    assert second["grade"] == "A" and second["cells"][0]["grade"] == "A"

    # Absent sat the paper at 0% -- an F overall, but the paper itself is "absent",
    # which is not a grade.
    absent = rows[campus.student_ids[2]]
    assert Decimal(absent["percentage"]) == 0
    assert absent["grade"] == "F"
    assert absent["cells"][0]["grade"] is None and absent["cells"][0]["is_absent"] is True

    assert [band["grade"] for band in sheet["grading_scale"]] == [b["grade"] for b in CUSTOM]


async def test_changing_the_scale_regrades_without_touching_marks(campus: Campus) -> None:
    await campus.put(f"{API}/exams/grading-scale", json={"bands": CUSTOM})
    exam_id = await _marked_exam(
        campus, [{"student_id": campus.student_ids[0], "marks_obtained": "75"}]
    )
    assert _by_student(await _sheet(campus, exam_id))[campus.student_ids[0]]["grade"] == "A"

    stricter = [
        {"min_percent": "85", "grade": "A"},
        {"min_percent": "60", "grade": "B"},
        {"min_percent": "0", "grade": "C"},
    ]
    assert (
        await campus.put(f"{API}/exams/grading-scale", json={"bands": stricter})
    ).status_code == 200
    row = _by_student(await _sheet(campus, exam_id))[campus.student_ids[0]]
    assert row["grade"] == "B"
    assert Decimal(row["percentage"]) == Decimal("75.00")

    # Resetting goes back to the board scale (75% is an A there); the marks are untouched.
    assert (await campus.delete(f"{API}/exams/grading-scale")).status_code == 204
    row = _by_student(await _sheet(campus, exam_id))[campus.student_ids[0]]
    assert row["grade"] == "A" and Decimal(row["percentage"]) == Decimal("75.00")
    assert (await campus.get(f"{API}/exams/grading-scale")).json()["is_default"] is True
    # Resetting again is harmless.
    assert (await campus.delete(f"{API}/exams/grading-scale")).status_code == 204


async def test_saving_and_removing_the_scale_is_audited(campus: Campus) -> None:
    await campus.put(f"{API}/exams/grading-scale", json={"bands": CUSTOM})
    await campus.delete(f"{API}/exams/grading-scale")
    logs = await campus.get(
        f"{API}/schools/{campus.tenant.school_id}/audit-logs",
        params={"entity_type": "exam_grading_scale"},
    )
    assert logs.status_code == 200, logs.text
    actions = {entry["action"] for entry in logs.json()}
    assert {"exam.grading_scale_set", "exam.grading_scale_deleted"} <= actions


# ---------------------------------------------------------------------------
# 3. A scale is complete or refused
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bands",
    [
        # No band starts at 0: a 20% result would have no grade.
        [{"min_percent": "50", "grade": "P"}, {"min_percent": "80", "grade": "A"}],
        # Two bands start at 70.
        [
            {"min_percent": "70", "grade": "A"},
            {"min_percent": "70", "grade": "B"},
            {"min_percent": "0", "grade": "F"},
        ],
        # The same grade twice, whatever the case.
        [{"min_percent": "50", "grade": "a"}, {"min_percent": "0", "grade": "A"}],
        # A single band is not a scale.
        [{"min_percent": "0", "grade": "P"}],
        # Over 100%.
        [{"min_percent": "101", "grade": "A"}, {"min_percent": "0", "grade": "F"}],
        # A blank grade.
        [{"min_percent": "50", "grade": "  "}, {"min_percent": "0", "grade": "F"}],
    ],
)
async def test_an_incomplete_or_ambiguous_scale_is_refused(
    campus: Campus, bands: list[dict[str, str]]
) -> None:
    refused = await campus.put(f"{API}/exams/grading-scale", json={"bands": bands})
    assert refused.status_code == 422, refused.text
    assert (await campus.get(f"{API}/exams/grading-scale")).json()["is_default"] is True


# ---------------------------------------------------------------------------
# 4. Policy, not marking
# ---------------------------------------------------------------------------


async def test_a_teacher_reads_the_scale_but_cannot_change_it(campus: Campus) -> None:
    await campus.put(f"{API}/exams/grading-scale", json={"bands": CUSTOM})
    teacher = await _teacher(campus.tenant, "grades-teacher@test.example", "Grades Teacher")

    read = await teacher.get(f"{API}/exams/grading-scale")
    assert read.status_code == 200, read.text
    assert read.json()["bands"][0]["grade"] == "A1"

    changed = await teacher.put(
        f"{API}/exams/grading-scale",
        json={"bands": [{"min_percent": "0", "grade": "A"}, {"min_percent": "1", "grade": "B"}]},
    )
    assert changed.status_code == 403, changed.text
    removed = await campus.tenant.client.delete(
        f"{API}/exams/grading-scale", headers=teacher.headers
    )
    assert removed.status_code == 403, removed.text
    assert (await campus.get(f"{API}/exams/grading-scale")).json()["bands"][0]["grade"] == "A1"


# ---------------------------------------------------------------------------
# 5. Isolation
# ---------------------------------------------------------------------------


async def test_each_campus_has_its_own_scale(tenant: Tenant, mailbox: list[EmailMessage]) -> None:
    campus_one = await build_campus(tenant, mailbox, email="one@test.example", code="head_one")
    await campus_one.put(f"{API}/exams/grading-scale", json={"bands": CUSTOM})

    second = await tenant.post(f"{API}/schools", json={"name": "Second Campus", "code": "SECOND"})
    assert second.status_code == 201, second.text
    mailbox.clear()
    token_two = await make_campus_head(
        tenant, mailbox, "two@test.example", school_id=second.json()["id"], code="head_two"
    )
    headers_two = {"Authorization": f"Bearer {token_two}"}

    seen = await tenant.client.get(f"{API}/exams/grading-scale", headers=headers_two)
    assert seen.status_code == 200 and seen.json()["is_default"] is True

    # Campus two saving its own scale leaves campus one's alone.
    own = await tenant.client.put(
        f"{API}/exams/grading-scale",
        json={
            "bands": [{"min_percent": "50", "grade": "Pass"}, {"min_percent": "0", "grade": "Fail"}]
        },
        headers=headers_two,
    )
    assert own.status_code == 200, own.text
    assert (await campus_one.get(f"{API}/exams/grading-scale")).json()["bands"][0]["grade"] == "A1"


async def test_two_organizations_never_share_a_scale(
    make_tenant: Any, mailbox: list[EmailMessage]
) -> None:
    org_a = await make_tenant(name="Org A", email="a@test.example", school_code="A1")
    campus_a = await build_campus(org_a, mailbox, email="head-a@test.example", code="head_a")
    await campus_a.put(f"{API}/exams/grading-scale", json={"bands": CUSTOM})

    mailbox.clear()
    org_b = await make_tenant(name="Org B", email="b@test.example", school_code="B1")
    campus_b = await build_campus(org_b, mailbox, email="head-b@test.example", code="head_b")
    assert (await campus_b.get(f"{API}/exams/grading-scale")).json()["is_default"] is True


async def test_raw_cross_tenant_insert_is_rejected_by_rls(campus: Campus) -> None:
    """The WITH CHECK half of the policy, as the restricted `sms_app` role."""
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy.pool import NullPool

    from tests.integration.conftest import _TEST_DB_HOST, _TEST_DB_NAME, _TEST_DB_PORT

    engine = create_async_engine(
        f"postgresql+asyncpg://sms_app:sms_app_password@{_TEST_DB_HOST}:{_TEST_DB_PORT}/{_TEST_DB_NAME}",
        poolclass=NullPool,
    )
    try:
        async with engine.begin() as conn:
            await conn.execute(
                text("SELECT set_config('app.current_org_id', :org, true)"),
                {"org": "00000000-0000-0000-0000-0000000000ff"},
            )
            with pytest.raises(DBAPIError) as caught:
                await conn.execute(
                    text(
                        "INSERT INTO exam_grading_scales (organization_id, school_id, bands) "
                        "VALUES (:org, :school, '[]'::jsonb)"
                    ),
                    {"org": campus.tenant.organization_id, "school": campus.tenant.school_id},
                )
            assert "row-level security" in str(caught.value).lower()
    finally:
        await engine.dispose()
