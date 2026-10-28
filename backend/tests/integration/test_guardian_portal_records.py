"""A parent's view of one child: attendance, fees, challan PDF and exam results.

Everything is built through the staff API and read through the portal, as a signed-in
parent. The data is real -- registers submitted, challans generated, marks entered --
so these test the portal against the same rows the office works with.

WHAT THESE GUARD

  1. ONLY THEIR OWN CHILD. Another child at the same school, and a child the parent
     may only collect, are 404 on every per-child endpoint.

  2. NOTHING PROVISIONAL. Draft and voided challans are not listed and cannot be
     downloaded; a draft exam's marks are not shown until the school publishes it.

  3. THE SAME NUMBERS AS THE OFFICE. Attendance rates, what is owed, overdue, the
     percentage and the rank match what the staff endpoints compute.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.common.email.sender import EmailMessage
from app.common.sms import SmsMessage
from tests.integration.conftest import API, Tenant
from tests.integration.test_academic_foundation import Campus, build_campus
from tests.integration.test_attendance_analytics import _register
from tests.integration.test_guardians import latest_code, sms_outbox

__all__ = ["sms_outbox"]  # a fixture, imported so pytest can find it here

FEE_YEAR = "2026-2027"
PARENT_PHONE = "0300-7654321"


class Portal:
    """A school, a parent signed in to the portal, and a way to read as either."""

    def __init__(self, campus: Campus) -> None:
        self.campus = campus
        self.token = ""

    @property
    def child(self) -> str:
        return self.campus.student_ids[0]

    @property
    def stranger(self) -> str:
        """A child at the same school this parent is not linked to."""
        return self.campus.student_ids[1]

    async def read(self, path: str) -> Any:
        return await self.campus.tenant.client.get(
            f"{API}/portal{path}", headers={"Authorization": f"Bearer {self.token}"}
        )

    async def ok(self, path: str) -> Any:
        response = await self.read(path)
        assert response.status_code == 200, response.text
        return response.json()


@pytest.fixture
async def portal(
    tenant: Tenant, mailbox: list[EmailMessage], sms_outbox: list[SmsMessage]
) -> Portal:
    campus = await build_campus(tenant, mailbox)
    granted = await campus.post(
        f"{API}/guardians/students/{campus.student_ids[0]}/portal-access",
        json={"phone": PARENT_PHONE, "full_name": "Parent One", "relationship_type": "mother"},
    )
    assert granted.status_code == 200, granted.text

    client = tenant.client
    requested = await client.post(f"{API}/guardian/auth/request-code", json={"phone": PARENT_PHONE})
    assert requested.status_code == 200, requested.text
    verified = await client.post(
        f"{API}/guardian/auth/verify",
        json={"phone": PARENT_PHONE, "code": latest_code(sms_outbox)},
        headers={"X-Token-Transport": "body"},
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["status"] == "authenticated"
    client.cookies.clear()

    p = Portal(campus)
    p.token = verified.json()["tokens"]["access_token"]
    return p


async def _price_the_class(campus: Campus, tuition: str = "4000.00") -> str:
    head = await campus.post(
        f"{API}/fees/heads", json={"code": "TUITION", "name": "Tuition", "recurrence": "monthly"}
    )
    assert head.status_code == 201, head.text
    structure = await campus.post(
        f"{API}/fees/structures",
        json={
            "class_id": campus.class_id,
            "academic_year": FEE_YEAR,
            "name": f"Grade 9 {FEE_YEAR}",
            "items": [{"head_id": head.json()["id"], "amount": tuition}],
        },
    )
    assert structure.status_code == 201, structure.text
    structure_id = structure.json()["id"]
    activated = await campus.post(f"{API}/fees/structures/{structure_id}/activate")
    assert activated.status_code == 200, activated.text
    return str(structure_id)


async def _bill(
    campus: Campus, structure_id: str, period: str, *, issue: bool = True, overdue: bool = False
) -> None:
    today = date.today()
    issued_on = today - timedelta(days=30) if overdue else today
    due_on = today - timedelta(days=10) if overdue else today + timedelta(days=14)
    generated = await campus.post(
        f"{API}/fees/vouchers/generate",
        json={
            "structure_id": structure_id,
            "period_label": period,
            "issue_date": issued_on.isoformat(),
            "due_date": due_on.isoformat(),
            "issue_immediately": issue,
        },
    )
    assert generated.status_code in (200, 201), generated.text


async def _vouchers_of(campus: Campus, student_id: str) -> list[dict[str, Any]]:
    listed = await campus.get(f"{API}/fees/vouchers", params={"student_id": student_id})
    assert listed.status_code == 200, listed.text
    return list(listed.json()["items"])


# ---------------------------------------------------------------------------
# Only their own child
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path",
    ["/attendance", "/fees", "/results"],
)
async def test_another_childs_records_are_not_found(portal: Portal, path: str) -> None:
    response = await portal.read(f"/children/{portal.stranger}{path}")
    assert response.status_code == 404, response.text
    assert (await portal.read(f"/children/not-a-uuid{path}")).status_code == 404


@pytest.mark.asyncio
async def test_a_pickup_only_child_shows_no_records(portal: Portal) -> None:
    """Linking the same parent to a second child for collection only shows nothing."""
    card = (await portal.campus.get(f"{API}/guardians/students/{portal.child}")).json()
    guardian_id = card[0]["guardian_id"]
    linked = await portal.campus.post(
        f"{API}/guardians/{guardian_id}/students",
        json={
            "student_id": portal.stranger,
            "relationship_type": "other",
            "relationship_label": "Neighbour",
            "can_pickup": True,
            "can_view_results": False,
        },
    )
    assert linked.status_code == 201, linked.text

    for path in ("/attendance", "/fees", "/results"):
        response = await portal.read(f"/children/{portal.stranger}{path}")
        assert response.status_code == 404, f"{path}: {response.text}"


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_attendance_matches_the_staff_calendar(portal: Portal) -> None:
    campus = portal.campus
    await _register(campus, campus.section_id, 2)
    await _register(campus, campus.section_id, 1, {portal.child: "absent"})
    # A draft register is nobody's assertion yet: it carries no status.
    await _register(campus, campus.section_id, 0, {portal.child: "absent"}, submit=False)

    mine = await portal.ok(f"/children/{portal.child}/attendance")
    staff = await campus.get(f"{API}/attendance/students/{portal.child}/calendar")
    assert staff.status_code == 200, staff.text

    assert mine["overall"] == staff.json()["overall"]
    assert mine["overall"]["counts"]["absent"] == 1
    assert mine["overall"]["counts"]["present"] == 1
    statuses = {d["session_date"]: d["status"] for d in mine["days"]}
    assert statuses[str(date.today())] is None


# ---------------------------------------------------------------------------
# Fees
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fees_list_issued_challans_and_what_is_owed(portal: Portal) -> None:
    campus = portal.campus
    structure_id = await _price_the_class(campus)
    await _bill(campus, structure_id, "2026-08", overdue=True)
    await _bill(campus, structure_id, "2026-09")
    await _bill(campus, structure_id, "2026-10", issue=False)  # draft: not shown

    statement = await portal.ok(f"/children/{portal.child}/fees")

    periods = [v["period_label"] for v in statement["vouchers"]]
    assert periods == ["2026-09", "2026-08"]  # newest due date first, no draft
    statuses = {v["period_label"]: v["status"] for v in statement["vouchers"]}
    assert statuses == {"2026-09": "issued", "2026-08": "overdue"}
    assert Decimal(statement["outstanding_total"]) == Decimal("8000.00")
    assert Decimal(statement["overdue_total"]) == Decimal("4000.00")
    # Only this child's challans, never a classmate's.
    mine = {v["id"] for v in await _vouchers_of(campus, portal.child)}
    assert {v["id"] for v in statement["vouchers"]} <= mine


@pytest.mark.asyncio
async def test_a_paid_challan_reads_as_paid_and_owes_nothing(portal: Portal) -> None:
    campus = portal.campus
    structure_id = await _price_the_class(campus)
    await _bill(campus, structure_id, "2026-08")
    voucher = (await _vouchers_of(campus, portal.child))[0]
    paid = await campus.post(
        f"{API}/fees/vouchers/{voucher['id']}/payments",
        json={"amount": voucher["total"], "method": "cash"},
    )
    assert paid.status_code in (200, 201), paid.text

    statement = await portal.ok(f"/children/{portal.child}/fees")
    assert statement["vouchers"][0]["status"] == "paid"
    assert Decimal(statement["outstanding_total"]) == Decimal("0")


@pytest.mark.asyncio
async def test_challan_pdf_downloads_only_for_the_childs_live_bills(portal: Portal) -> None:
    campus = portal.campus
    structure_id = await _price_the_class(campus)
    await _bill(campus, structure_id, "2026-08")
    await _bill(campus, structure_id, "2026-10", issue=False)
    by_period = {v["period_label"]: v for v in await _vouchers_of(campus, portal.child)}
    issued, draft = by_period["2026-08"], by_period["2026-10"]
    classmate = (await _vouchers_of(campus, portal.stranger))[0]

    pdf = await portal.read(f"/children/{portal.child}/fees/{issued['id']}/pdf")
    assert pdf.status_code == 200, pdf.text
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["cache-control"] == "private, no-store"
    assert pdf.content.startswith(b"%PDF")

    for voucher_id in (draft["id"], classmate["id"], "not-a-uuid"):
        refused = await portal.read(f"/children/{portal.child}/fees/{voucher_id}/pdf")
        assert refused.status_code == 404, refused.text
    # Nor through the classmate's own path: the parent is not linked to them.
    other = await portal.read(f"/children/{portal.stranger}/fees/{classmate['id']}/pdf")
    assert other.status_code == 404


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_results_appear_only_once_the_exam_is_published(portal: Portal) -> None:
    campus = portal.campus
    subject = await campus.post(f"{API}/subjects", json={"code": "MATH", "name": "Mathematics"})
    assert subject.status_code == 201, subject.text
    exam = await campus.post(f"{API}/exams", json={"name": "Mid-Term"})
    assert exam.status_code == 201, exam.text
    exam_id = exam.json()["id"]
    paper = await campus.post(
        f"{API}/exams/{exam_id}/papers",
        json={
            "class_id": campus.class_id,
            "subject_id": subject.json()["id"],
            "max_marks": 100,
            "pass_marks": 40,
        },
    )
    assert paper.status_code == 201, paper.text
    saved = await campus.put(
        f"{API}/exams/papers/{paper.json()['id']}/marks",
        json={
            "entries": [
                {"student_id": campus.student_ids[0], "marks_obtained": "76"},
                {"student_id": campus.student_ids[1], "marks_obtained": "91.5"},
                {"student_id": campus.student_ids[2], "is_absent": True},
            ]
        },
    )
    assert saved.status_code == 200, saved.text

    # Still a draft: the school is checking marks. Nothing for parents yet.
    assert await portal.ok(f"/children/{portal.child}/results") == []

    published = await campus.patch(f"{API}/exams/{exam_id}", json={"status": "published"})
    assert published.status_code == 200, published.text

    results = await portal.ok(f"/children/{portal.child}/results")
    assert len(results) == 1
    result = results[0]
    assert result["exam_name"] == "Mid-Term"
    assert result["class_name"] == "Grade 9"
    assert result["rank"] == 2 and result["class_size"] == 3
    assert Decimal(result["percentage"]) == Decimal("76.00")
    assert result["papers"] == [
        {
            "subject_name": "Mathematics",
            "max_marks": 100,
            "pass_marks": 40,
            "marks_obtained": "76.00",
            "is_absent": False,
            "marked": True,
        }
    ]
    # Nobody else's marks leave the server.
    assert "91.5" not in str(results)
