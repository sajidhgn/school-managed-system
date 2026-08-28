"""Unattended monthly generation, and challans that absorb what is still owed.

Two features that share one failure mode: BILLING THE SAME RUPEE TWICE, and both
reach it by a different road.

  * The SCHEDULE bills a whole campus with nobody watching. A run that fires twice,
    or that a retried container repeats, must not produce two challans for one month.
  * CONSOLIDATION cancels the challans it absorbs. If the cancellation and the new
    charge are not the same moment, the family's balance is briefly and visibly
    wrong; if a part-paid challan is absorbed, its receipt is orphaned and the family
    is charged again for money the school already banked.

So the cases here are mostly about ORDER and ARITHMETIC rather than about routes:
what the balance reads at each step, and what happens when a parent pays in the gap
between generating a draft and issuing it.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from app.common.email.sender import EmailMessage
from tests.integration.conftest import API, Tenant
from tests.integration.test_fees import (
    YEAR,
    FeeFixture,
    build_fees,
    generate,
    make_scoped_actor,
)

# See the note in `test_fees_extended.py`: `asyncio_mode = "auto"` already runs these,
# and adding the anyio marker hands them to a second plugin on a second event loop.


async def make_arrears_head(fx: FeeFixture) -> str:
    created = await fx.post(
        f"{API}/fees/heads",
        json={"code": "ARREARS", "name": "Previous dues", "recurrence": "monthly"},
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def set_schedule(fx: FeeFixture, **overrides: Any) -> Any:
    body: dict[str, Any] = {
        "academic_year": YEAR,
        "is_active": True,
        "generate_day": 1,
        "due_day_offset": 10,
        "issue_immediately": False,
        "include_stationery": False,
        "carry_forward_dues": False,
        **overrides,
    }
    return await fx.put(f"{API}/fees/billing-schedule", json=body)


async def balance_of(fx: FeeFixture, student_id: str) -> Decimal:
    statement = await fx.get(f"{API}/fees/students/{student_id}/ledger")
    assert statement.status_code == 200, statement.text
    return Decimal(statement.json()["balance"])


# ---------------------------------------------------------------------------
# The schedule
# ---------------------------------------------------------------------------


async def test_a_campus_with_no_schedule_reads_as_null_rather_than_missing(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """ "Not set up" is a normal state, not an error.

    A 404 here would make the settings screen of a school that has never configured
    automation look broken, and "broken" is what stops somebody configuring it.
    """
    fx = await build_fees(tenant, mailbox)
    read = await fx.get(f"{API}/fees/billing-schedule", params={"academic_year": YEAR})
    assert read.status_code == 200, read.text
    assert read.json() is None


async def test_the_schedule_is_upserted_by_year_and_reports_its_next_run(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """PUT twice revises; it does not create a second schedule.

    Two live schedules would mean the day a family is billed depends on which row the
    job happened to read first -- and the partial unique index would reject the second
    anyway, as a 409 on a request that looked perfectly ordinary.
    """
    fx = await build_fees(tenant, mailbox)

    first = await set_schedule(fx, generate_day=5)
    assert first.status_code == 200, first.text
    assert first.json()["generate_day"] == 5

    second = await set_schedule(fx, generate_day=25, due_day_offset=7)
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["id"] == first.json()["id"], "revised, not duplicated"
    assert body["generate_day"] == 25
    assert body["due_day_offset"] == 7

    # The next run is computed server-side: it depends on which period has already
    # been billed and on the campus's own calendar, neither of which a browser knows.
    assert body["next_run_on"] is not None
    assert date.fromisoformat(body["next_run_on"]).day == 25
    assert date.fromisoformat(body["next_run_on"]) >= date.today()


async def test_a_paused_schedule_keeps_its_settings_and_has_no_next_run(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Pausing is not deleting. An owner who stops automation for a term expects
    their billing day back when they resume, not an empty form."""
    fx = await build_fees(tenant, mailbox)
    await set_schedule(fx, generate_day=12)

    paused = await set_schedule(fx, generate_day=12, is_active=False)
    assert paused.status_code == 200, paused.text
    assert paused.json()["generate_day"] == 12
    assert paused.json()["next_run_on"] is None

    read = await fx.get(f"{API}/fees/billing-schedule", params={"academic_year": YEAR})
    assert read.json()["generate_day"] == 12, "settings survive the pause"


async def test_a_schedule_carrying_dues_forward_must_name_a_head(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Half-configured consolidation is the dangerous state: the run would absorb a
    family's arrears and have nowhere to bill them, so the money would vanish from
    both the old challan and the new one."""
    fx = await build_fees(tenant, mailbox)
    refused = await set_schedule(fx, carry_forward_dues=True)
    assert refused.status_code == 422, refused.text


async def test_running_now_bills_every_active_structure_and_only_once(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """THE IDEMPOTENCE TEST, and it is the one that makes a nightly job safe at all.

    The second run is not an error -- "already generated" is an answer -- and even if
    the bookmark were lost, the partial unique index behind it would skip every
    student rather than bill them twice.
    """
    fx = await build_fees(tenant, mailbox, students=2)
    await set_schedule(fx, issue_immediately=True)

    first = await fx.post(f"{API}/fees/billing-schedule/run", params={"academic_year": YEAR})
    assert first.status_code == 200, first.text
    body = first.json()
    assert body["ran"] is True
    assert body["structures"] == 1
    assert body["created"] == 2
    assert body["period_label"] == f"{date.today():%Y-%m}"

    second = await fx.post(f"{API}/fees/billing-schedule/run", params={"academic_year": YEAR})
    assert second.status_code == 200, second.text
    assert second.json()["ran"] is False
    assert "already been generated" in (second.json()["reason"] or "")

    listed = await fx.get(f"{API}/fees/vouchers", params={"period_label": f"{date.today():%Y-%m}"})
    assert listed.json()["meta"]["total"] == 2, "two students, two challans, not four"


async def test_the_run_records_a_receipt_of_itself(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """A run that created 0 and skipped 400 is a WORKING run; one that never happened
    is a different fact. The screen must be able to tell them apart."""
    fx = await build_fees(tenant, mailbox, students=2)
    await set_schedule(fx)

    before = await fx.get(f"{API}/fees/billing-schedule", params={"academic_year": YEAR})
    assert before.json()["last_run_at"] is None

    await fx.post(f"{API}/fees/billing-schedule/run", params={"academic_year": YEAR})

    after = await fx.get(f"{API}/fees/billing-schedule", params={"academic_year": YEAR})
    body = after.json()
    assert body["last_run_at"] is not None
    assert body["last_run_created"] == 2
    assert body["last_run_period"] == f"{date.today():%Y-%m}"
    # Already billed for this period, so the next run is next month rather than today.
    assert date.fromisoformat(body["next_run_on"]) > date.today()


async def test_configuring_needs_manage_and_running_needs_issue(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Deciding that this campus bills on the 25th, into issued challans, carrying
    arrears forward, is a standing pricing decision. Pressing "run now" bills four
    hundred families today. They are not the same trust."""
    # Built for its side effect: the campus, class and structure the two scoped
    # actors below are answered against have to exist before either can be refused
    # for the right reason rather than for having nothing to act on.
    await build_fees(tenant, mailbox)

    issuer = await make_scoped_actor(
        tenant,
        mailbox,
        "issuer-only@test.example",
        ["fee:read", "fee:issue"],
        code="fee_issuer",
    )
    issue_headers = {"Authorization": f"Bearer {issuer}"}

    refused = await tenant.client.put(
        f"{API}/fees/billing-schedule",
        headers=issue_headers,
        json={"academic_year": YEAR, "generate_day": 3},
    )
    assert refused.status_code == 403, refused.text

    manager = await make_scoped_actor(
        tenant,
        mailbox,
        "manager-only@test.example",
        ["fee:read", "fee:manage"],
        code="fee_manager",
    )
    manage_headers = {"Authorization": f"Bearer {manager}"}

    allowed = await tenant.client.put(
        f"{API}/fees/billing-schedule",
        headers=manage_headers,
        json={"academic_year": YEAR, "generate_day": 3},
    )
    assert allowed.status_code == 200, allowed.text

    cannot_run = await tenant.client.post(
        f"{API}/fees/billing-schedule/run",
        headers=manage_headers,
        params={"academic_year": YEAR},
    )
    assert cannot_run.status_code == 403, cannot_run.text


# ---------------------------------------------------------------------------
# Consolidation -- the new challan absorbs what is still owed
# ---------------------------------------------------------------------------


async def test_carrying_dues_forward_bills_them_once_and_cancels_the_old_challan(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """THE OTHER DOUBLE-COUNTING TEST.

    September bills 13,000 -- its own 6,500 plus August's 6,500 -- and August is
    VOIDED as it is absorbed. The family's balance stays 13,000: if the cancellation
    were skipped it would read 19,500, and the school would be chasing money nobody
    owes.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    student = fx.student_ids[0]
    arrears_head = await make_arrears_head(fx)

    august = await generate(fx, period="2026-08", issue=True)
    assert august.status_code == 201, august.text
    august_id = august.json()["voucher_ids"][0]
    assert await balance_of(fx, student) == Decimal("6500.00")

    september = await generate(
        fx,
        period="2026-09",
        issue=True,
        carry_forward_dues=True,
        carry_forward_head_id=arrears_head,
    )
    assert september.status_code == 201, september.text
    assert september.json()["absorbed_vouchers"] == 1
    assert Decimal(september.json()["absorbed_total"]) == Decimal("6500.00")

    detail = await fx.get(f"{API}/fees/vouchers/{september.json()['voucher_ids'][0]}")
    body = detail.json()
    assert Decimal(body["total"]) == Decimal("13000.00"), "its own month plus the arrears"
    # The line names the periods it came from, so a parent can check it against the
    # challans they were holding rather than argue with a bare number.
    carried = [item for item in body["items"] if item["head_id"] == arrears_head]
    assert len(carried) == 1
    assert Decimal(carried[0]["amount"]) == Decimal("6500.00")
    assert "2026-08" in carried[0]["line_name"]
    # NOT printed as a separate balance as well -- that would show the family a figure
    # they have just been charged for, on the same piece of paper.
    assert Decimal(body["arrears_brought_forward"]) == Decimal("0.00")

    voided = await fx.get(f"{API}/fees/vouchers/{august_id}")
    assert voided.json()["status"] == "void"
    assert "Superseded by" in (voided.json()["void_reason"] or "")
    assert voided.json()["superseded_by_voucher_number"] == body["voucher_number"]

    assert await balance_of(fx, student) == Decimal("13000.00"), "not 19,500"


async def test_a_consolidating_draft_leaves_the_old_challan_payable_until_it_is_issued(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """A draft is not a bill.

    Cancelling August against an unissued September would tell the school the family
    owes nothing while the only document covering that money sits in a drafts list.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    student = fx.student_ids[0]
    arrears_head = await make_arrears_head(fx)

    august_id = (await generate(fx, period="2026-08", issue=True)).json()["voucher_ids"][0]

    september = await generate(
        fx,
        period="2026-09",
        issue=False,
        carry_forward_dues=True,
        carry_forward_head_id=arrears_head,
    )
    september_id = september.json()["voucher_ids"][0]

    still_live = await fx.get(f"{API}/fees/vouchers/{august_id}")
    assert still_live.json()["status"] in {"issued", "overdue"}, "reserved, not cancelled"
    assert still_live.json()["superseded_by_voucher_id"] == september_id
    assert await balance_of(fx, student) == Decimal("6500.00"), "the draft charges nothing"

    issued = await fx.post(f"{API}/fees/vouchers/{september_id}/issue")
    assert issued.status_code == 200, issued.text

    now_void = await fx.get(f"{API}/fees/vouchers/{august_id}")
    assert now_void.json()["status"] == "void"
    assert await balance_of(fx, student) == Decimal("13000.00")


async def test_a_part_paid_challan_is_never_absorbed(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Cancelling a challan money was received against would orphan the receipt --
    which `void_voucher` refuses outright -- and billing for it anyway would charge a
    family twice for what they had already paid.

    Its remaining balance keeps its own document, and prints beside the new total the
    way it always did.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    student = fx.student_ids[0]
    arrears_head = await make_arrears_head(fx)

    august_id = (await generate(fx, period="2026-08", issue=True)).json()["voucher_ids"][0]
    paid = await fx.post(
        f"{API}/fees/vouchers/{august_id}/payments", json={"amount": "2000.00", "method": "cash"}
    )
    assert paid.status_code == 201, paid.text

    september = await generate(
        fx,
        period="2026-09",
        issue=True,
        carry_forward_dues=True,
        carry_forward_head_id=arrears_head,
    )
    assert september.json()["absorbed_vouchers"] == 0, "part paid -- left alone"

    august = await fx.get(f"{API}/fees/vouchers/{august_id}")
    assert august.json()["status"] == "partly_paid"

    detail = await fx.get(f"{API}/fees/vouchers/{september.json()['voucher_ids'][0]}")
    assert Decimal(detail.json()["total"]) == Decimal("6500.00"), "September only"
    # Printed beside the total rather than inside it -- August is still payable.
    assert Decimal(detail.json()["arrears_brought_forward"]) == Decimal("4500.00")
    assert await balance_of(fx, student) == Decimal("11000.00")


async def test_paying_a_reserved_challan_shrinks_the_arrears_line_at_issue(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """THE RACE THIS DESIGN EXISTS TO SURVIVE.

    A parent pays August at the counter while September sits in drafts. Voiding August
    then is impossible and billing for it would be theft, so the reservation is
    released and the line comes off -- which is legal only because the voucher is
    still a draft at that moment.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    student = fx.student_ids[0]
    arrears_head = await make_arrears_head(fx)

    august_id = (await generate(fx, period="2026-08", issue=True)).json()["voucher_ids"][0]
    september_id = (
        await generate(
            fx,
            period="2026-09",
            issue=False,
            carry_forward_dues=True,
            carry_forward_head_id=arrears_head,
        )
    ).json()["voucher_ids"][0]

    drafted = await fx.get(f"{API}/fees/vouchers/{september_id}")
    assert Decimal(drafted.json()["total"]) == Decimal("13000.00"), "reserved August included"

    settled = await fx.post(
        f"{API}/fees/vouchers/{august_id}/payments", json={"amount": "6500.00", "method": "cash"}
    )
    assert settled.status_code == 201, settled.text

    issued = await fx.post(f"{API}/fees/vouchers/{september_id}/issue")
    assert issued.status_code == 200, issued.text
    body = issued.json()
    assert Decimal(body["total"]) == Decimal("6500.00"), "the arrears line came off"
    # Removed rather than zeroed: a "Previous dues 0" line is a question a parent
    # phones about, and the answer is not one the paper can give.
    assert [item for item in body["items"] if item["head_id"] == arrears_head] == []

    august = await fx.get(f"{API}/fees/vouchers/{august_id}")
    assert august.json()["status"] == "paid", "never voided"
    assert august.json()["superseded_by_voucher_id"] is None, "released"
    assert await balance_of(fx, student) == Decimal("6500.00")


async def test_voiding_a_consolidating_draft_releases_what_it_reserved(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Otherwise the reserved challans are stranded: never absorbed, never offered to
    the next run, and still sitting on the family's balance."""
    fx = await build_fees(tenant, mailbox, students=1)
    arrears_head = await make_arrears_head(fx)

    august_id = (await generate(fx, period="2026-08", issue=True)).json()["voucher_ids"][0]
    september_id = (
        await generate(
            fx,
            period="2026-09",
            issue=False,
            carry_forward_dues=True,
            carry_forward_head_id=arrears_head,
        )
    ).json()["voucher_ids"][0]

    voided = await fx.post(
        f"{API}/fees/vouchers/{september_id}/void", json={"reason": "Wrong period"}
    )
    assert voided.status_code == 200, voided.text

    august = await fx.get(f"{API}/fees/vouchers/{august_id}")
    assert august.json()["superseded_by_voucher_id"] is None
    assert august.json()["status"] in {"issued", "overdue"}

    # And it is offered to the next consolidating run rather than stranded.
    october = await generate(
        fx,
        period="2026-10",
        issue=True,
        carry_forward_dues=True,
        carry_forward_head_id=arrears_head,
    )
    assert october.json()["absorbed_vouchers"] == 1


async def test_generating_with_carry_forward_and_no_head_is_refused(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Named at the boundary so the error reaches the form that produced it, rather
    than surfacing as an integrity error from the CHECK behind it."""
    fx = await build_fees(tenant, mailbox)
    refused = await generate(fx, period="2026-09", carry_forward_dues=True)
    assert refused.status_code == 422, refused.text
