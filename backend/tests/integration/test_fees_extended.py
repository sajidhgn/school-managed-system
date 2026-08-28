"""Fees slice 2 -- the deferrals docs/modules/fees.md §2 recorded and this closes.

Five behaviours, and every one of them was deferred with a note saying it would need
no table rewrite. These tests are what makes that claim checkable rather than
asserted:

  * CONCESSIONS AND OVERRIDES -- a named scholarship, an ad-hoc remission, and a
    negotiated rate, all resolved by the one merge function the preview and the
    billing run share.
  * ONE-OFF CHARGES -- a fine or a breakage on a single draft challan, without
    touching the class structure every other student is billed from.
  * AUTOMATIC LATE FEES -- a policy, and a run that mints each fine as its OWN
    challan rather than rewriting the overdue one.
  * THE RUNNING LEDGER -- every money movement, and the arrears figure a new challan
    is printed with.
  * THE VOUCHER REGISTER EXPORT.

The cases that matter most are the ones about ORDER and DOUBLE COUNTING, because
those are the failures that produce a plausible-looking wrong number: a discount
computed against the class list price for a child on a negotiated rate, a fine that
compounds on itself, an arrears line billed twice.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.common.email.sender import EmailMessage
from app.db.session import bind_tenant, get_session_factory
from tests.integration.conftest import API, Tenant
from tests.integration.test_fees import (
    PERIOD,
    YEAR,
    FeeFixture,
    build_fees,
    generate,
    make_scoped_actor,
)

# NO `pytestmark = pytest.mark.anyio` here. `pyproject.toml` sets
# `asyncio_mode = "auto"`, so pytest-asyncio already runs every coroutine test on the
# session's single event loop. Adding the anyio marker hands these tests to a SECOND
# plugin and a second loop, while the database engine stays bound to the first --
# which surfaces as "attached to a different loop" and asyncpg protocol-state errors
# in fixtures that worked a moment earlier.


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def make_concession(fx: FeeFixture, **overrides: Any) -> str:
    payload: dict[str, Any] = {
        "code": "STAFF",
        "name": "Staff child remission",
        "kind": "percent",
        "value": "50.00",
    }
    payload.update(overrides)
    created = await fx.post(f"{API}/fees/concessions", json=payload)
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def assign(fx: FeeFixture, student_id: str, **payload: Any) -> Any:
    body = {"academic_year": YEAR, **payload}
    return await fx.put(f"{API}/fees/students/{student_id}/fee-assignments", json=body)


async def voucher_for(fx: FeeFixture, student_id: str) -> dict[str, Any]:
    listed = await fx.get(f"{API}/fees/vouchers", params={"student_id": student_id})
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert items, "expected a challan for this student"
    detail = await fx.get(f"{API}/fees/vouchers/{items[0]['id']}")
    assert detail.status_code == 200, detail.text
    return dict(detail.json())


async def generate_overdue(
    fx: FeeFixture, *, period: str, issued_days_ago: int, due_days_ago: int
) -> Any:
    """A challan whose due date is genuinely in the past.

    Real dates rather than a frozen clock, because the late-fee run is reached through
    HTTP and the route deliberately exposes no way to pretend it is a different day --
    a billing job that trusts a caller-supplied "today" is a job that can be made to
    fine a family early.
    """
    today = date.today()
    return await fx.post(
        f"{API}/fees/vouchers/generate",
        json={
            "structure_id": fx.structure_id,
            "period_label": period,
            "issue_date": (today - timedelta(days=issued_days_ago)).isoformat(),
            "due_date": (today - timedelta(days=due_days_ago)).isoformat(),
            "issue_immediately": True,
        },
    )


async def set_policy(fx: FeeFixture, **overrides: Any) -> Any:
    fine_head = await fx.post(
        f"{API}/fees/heads",
        json={"code": "LATE", "name": "Late fee", "recurrence": "one_time"},
    )
    head_id = (
        fine_head.json()["id"] if fine_head.status_code == 201 else fx.head_ids.get("LATE", "")
    )
    if fine_head.status_code == 201:
        fx.head_ids["LATE"] = head_id

    payload: dict[str, Any] = {
        "academic_year": YEAR,
        "name": "Standard late fee",
        "head_id": fx.head_ids["LATE"],
        "kind": "fixed",
        "value": "200.00",
        "grace_days": 0,
        "recurrence": "once",
    }
    payload.update(overrides)
    return await fx.put(f"{API}/fees/late-fee-policies", json=payload)


# ---------------------------------------------------------------------------
# 1-8. Concessions, overrides, and the order they apply in
# ---------------------------------------------------------------------------


async def test_a_percent_concession_reduces_the_line_and_shows_both_numbers(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """The gross stays on the challan beside the remission.

    A concession applied by quietly lowering the amount is indistinguishable on paper
    from a repricing, and the family cannot see they were awarded anything -- which
    is the one thing a scholarship has to make visible.
    """
    fx = await build_fees(tenant, mailbox)
    concession_id = await make_concession(fx)

    assigned = await assign(
        fx,
        fx.student_ids[0],
        head_id=fx.head_ids["TUITION"],
        mode="discount",
        concession_id=concession_id,
    )
    assert assigned.status_code == 200, assigned.text

    run = await generate(fx)
    assert run.status_code == 201, run.text

    discounted = await voucher_for(fx, fx.student_ids[0])
    # 5,000 tuition + 1,500 transport, half the tuition remitted.
    assert Decimal(discounted["subtotal"]) == Decimal("6500.00")
    assert Decimal(discounted["discount_total"]) == Decimal("2500.00")
    assert Decimal(discounted["total"]) == Decimal("4000.00")

    tuition_line = next(
        line for line in discounted["items"] if line["head_id"] == fx.head_ids["TUITION"]
    )
    assert Decimal(tuition_line["amount"]) == Decimal("5000.00"), "gross survives on the line"
    assert Decimal(tuition_line["discount_amount"]) == Decimal("2500.00")

    # The student with no arrangement is untouched -- a concession is not a repricing.
    plain = await voucher_for(fx, fx.student_ids[1])
    assert Decimal(plain["total"]) == Decimal("6500.00")
    assert Decimal(plain["discount_total"]) == Decimal("0.00")


async def test_the_preview_and_the_challan_agree_to_the_rupee(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """A preview showing 4,000 against a challan billing 6,500 is worse than no
    preview: the operator checked, and was told the wrong thing. Both go through
    `_effective_lines`, and this is what holds them to it."""
    fx = await build_fees(tenant, mailbox)
    concession_id = await make_concession(fx, value="30.00")
    await assign(
        fx,
        fx.student_ids[0],
        head_id=fx.head_ids["TUITION"],
        mode="discount",
        concession_id=concession_id,
    )

    profile = await fx.get(
        f"{API}/fees/students/{fx.student_ids[0]}/fee-profile", params={"academic_year": YEAR}
    )
    assert profile.status_code == 200, profile.text
    preview = profile.json()
    assert Decimal(preview["gross_total"]) == Decimal("6500.00")
    assert Decimal(preview["discount_total"]) == Decimal("1500.00")
    assert Decimal(preview["effective_total"]) == Decimal("5000.00")

    await generate(fx)
    billed = await voucher_for(fx, fx.student_ids[0])
    assert Decimal(billed["total"]) == Decimal(preview["effective_total"])
    assert Decimal(billed["discount_total"]) == Decimal(preview["discount_total"])


async def test_a_discount_applies_to_an_overridden_rate_not_the_class_price(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """THE ORDER TEST, and the one that actually costs money if it regresses.

    "Half of what this child pays" computed against the class list price bills the
    wrong number for every child on a negotiated rate -- and bills it invisibly,
    because the challan still shows a plausible-looking 50%.
    """
    fx = await build_fees(tenant, mailbox)
    concession_id = await make_concession(fx)  # 50%

    # Ali is on a legacy tuition of 4,000 rather than the class's 5,000...
    overridden = await assign(
        fx,
        fx.student_ids[0],
        head_id=fx.head_ids["TUITION"],
        mode="override",
        amount="4000.00",
    )
    assert overridden.status_code == 200, overridden.text
    # ...and is also a staff child. Only ONE arrangement per head per year is
    # allowed, so the discount must land on TRANSPORT to prove the ordering without
    # colliding with the override.
    await assign(
        fx,
        fx.student_ids[0],
        head_id=fx.head_ids["TRANSPORT"],
        mode="discount",
        concession_id=concession_id,
    )

    await generate(fx)
    billed = await voucher_for(fx, fx.student_ids[0])

    tuition = next(i for i in billed["items"] if i["head_id"] == fx.head_ids["TUITION"])
    transport = next(i for i in billed["items"] if i["head_id"] == fx.head_ids["TRANSPORT"])
    assert Decimal(tuition["amount"]) == Decimal("4000.00"), "override restates the class line"
    assert Decimal(transport["discount_amount"]) == Decimal("750.00"), "half of 1,500"
    assert Decimal(billed["subtotal"]) == Decimal("5500.00")
    assert Decimal(billed["total"]) == Decimal("4750.00")


async def test_an_override_never_invents_a_line_the_class_does_not_price(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """OVERRIDE replaces; it does not add. If it added, a mis-picked head would start
    billing a family for a service the child never took."""
    fx = await build_fees(tenant, mailbox)
    hostel = await fx.post(
        f"{API}/fees/heads", json={"code": "HOSTEL", "name": "Hostel", "recurrence": "monthly"}
    )
    assert hostel.status_code == 201, hostel.text

    await assign(
        fx,
        fx.student_ids[0],
        head_id=hostel.json()["id"],
        mode="override",
        amount="9000.00",
    )

    await generate(fx)
    billed = await voucher_for(fx, fx.student_ids[0])
    assert Decimal(billed["total"]) == Decimal("6500.00"), "unchanged -- nothing to replace"
    assert all(item["head_id"] != hostel.json()["id"] for item in billed["items"])


async def test_a_remission_larger_than_the_line_bills_zero_not_a_negative(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Clamped, because `ck_fee_voucher_items_amounts_valid` refuses a negative line
    -- and an unclamped generous scholarship would turn into a failed billing run for
    the whole class rather than a free student."""
    fx = await build_fees(tenant, mailbox)
    await assign(
        fx,
        fx.student_ids[0],
        head_id=fx.head_ids["TRANSPORT"],
        mode="discount",
        amount="99999.00",
    )

    run = await generate(fx)
    assert run.status_code == 201, run.text

    billed = await voucher_for(fx, fx.student_ids[0])
    transport = next(i for i in billed["items"] if i["head_id"] == fx.head_ids["TRANSPORT"])
    assert Decimal(transport["discount_amount"]) == Decimal("1500.00")
    assert Decimal(billed["total"]) == Decimal("5000.00"), "tuition only; transport free"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param({"mode": "discount"}, id="no_rate_at_all"),
        pytest.param({"mode": "discount", "amount": "100.00", "percent": "10.00"}, id="two_rates"),
        pytest.param({"mode": "override"}, id="override_without_amount"),
        pytest.param({"mode": "added", "percent": "10.00"}, id="percent_on_an_addition"),
    ],
)
async def test_an_arrangement_that_cannot_mean_one_thing_is_refused(
    tenant: Tenant, mailbox: list[EmailMessage], payload: dict[str, Any]
) -> None:
    """422 at the door rather than an opaque integrity error three screens later.

    A discount carrying both a scheme and its own percent has no single answer to
    "what rate is this child on", and the version that reaches production is the one
    where the two disagree.
    """
    fx = await build_fees(tenant, mailbox)
    response = await assign(fx, fx.student_ids[0], head_id=fx.head_ids["TUITION"], **payload)
    assert response.status_code == 422, response.text


async def test_revising_a_scheme_moves_every_student_on_it_but_not_issued_challans(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """The reason the rate lives on the scheme rather than on each child -- and the
    reason revising it does not restate February."""
    fx = await build_fees(tenant, mailbox)
    concession_id = await make_concession(fx, value="40.00")
    for student_id in fx.student_ids:
        await assign(
            fx,
            student_id,
            head_id=fx.head_ids["TUITION"],
            mode="discount",
            concession_id=concession_id,
        )

    await generate(fx, period="2026-08")
    august = await voucher_for(fx, fx.student_ids[0])
    assert Decimal(august["discount_total"]) == Decimal("2000.00")

    revised = await fx.patch(f"{API}/fees/concessions/{concession_id}", json={"value": "50.00"})
    assert revised.status_code == 200, revised.text

    # The issued challan is untouched...
    unchanged = await fx.get(f"{API}/fees/vouchers/{august['id']}")
    assert Decimal(unchanged.json()["discount_total"]) == Decimal("2000.00")

    # ...and BOTH students follow the scheme on the next run, with one edit.
    await generate(fx, period="2026-09")
    for student_id in fx.student_ids:
        listed = await fx.get(
            f"{API}/fees/vouchers",
            params={"student_id": student_id, "period_label": "2026-09"},
        )
        assert Decimal(listed.json()["items"][0]["discount_total"]) == Decimal("2500.00")


async def test_a_scheme_students_are_on_cannot_be_deleted_and_the_refusal_counts_them(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Deleting would silently restore those families to full fees, and nobody would
    find out until the challans printed. "37 students are on this scheme" is a message
    an operator acts on; "in use" is one they argue with."""
    fx = await build_fees(tenant, mailbox)
    concession_id = await make_concession(fx)
    await assign(
        fx,
        fx.student_ids[0],
        head_id=fx.head_ids["TUITION"],
        mode="discount",
        concession_id=concession_id,
    )

    refused = await fx.delete(f"{API}/fees/concessions/{concession_id}")
    assert refused.status_code == 409, refused.text
    assert "1 student arrangement" in refused.text

    listed = await fx.get(f"{API}/fees/concessions")
    assert listed.json()["items"][0]["student_count"] == 1

    # Taking the child off releases it.
    removed = await fx.delete(
        f"{API}/fees/students/{fx.student_ids[0]}/fee-assignments/{fx.head_ids['TUITION']}",
        params={"academic_year": YEAR},
    )
    assert removed.status_code == 200, removed.text
    assert (await fx.delete(f"{API}/fees/concessions/{concession_id}")).status_code == 204


# ---------------------------------------------------------------------------
# 9-11. One-off charges on a draft
# ---------------------------------------------------------------------------


async def test_a_one_off_charge_hits_one_student_not_the_whole_grade(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """The reason this route exists: without it, the only tool for "charge Ali 500 for
    the lab window" is the CLASS structure, which bills all forty."""
    fx = await build_fees(tenant, mailbox)
    breakage = await fx.post(
        f"{API}/fees/heads",
        json={"code": "BREAKAGE", "name": "Breakage", "recurrence": "one_time"},
    )
    assert breakage.status_code == 201, breakage.text

    await generate(fx, issue=False)
    draft = await voucher_for(fx, fx.student_ids[0])

    charged = await fx.put(
        f"{API}/fees/vouchers/{draft['id']}/charges",
        json={"head_id": breakage.json()["id"], "amount": "500.00", "note": "lab window"},
    )
    assert charged.status_code == 200, charged.text
    assert Decimal(charged.json()["total"]) == Decimal("7000.00")
    line = next(i for i in charged.json()["items"] if i["head_id"] == breakage.json()["id"])
    assert line["line_name"] == "Breakage — lab window"

    # Idempotent by head: a second charge SETS the line rather than adding another.
    again = await fx.put(
        f"{API}/fees/vouchers/{draft['id']}/charges",
        json={"head_id": breakage.json()["id"], "amount": "800.00"},
    )
    assert again.status_code == 200, again.text
    assert Decimal(again.json()["total"]) == Decimal("7300.00")
    assert len([i for i in again.json()["items"] if i["head_id"] == breakage.json()["id"]]) == 1

    # The classmate is untouched, which is the entire point.
    sibling = await voucher_for(fx, fx.student_ids[1])
    assert Decimal(sibling["total"]) == Decimal("6500.00")

    removed = await fx.delete(f"{API}/fees/vouchers/{draft['id']}/charges/{breakage.json()['id']}")
    assert removed.status_code == 200, removed.text
    assert Decimal(removed.json()["total"]) == Decimal("6500.00")


async def test_a_one_off_charge_is_refused_on_an_issued_challan(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Rule 1. A parent holding a challan for 6,500 must not discover at the counter
    that it now says 7,000."""
    fx = await build_fees(tenant, mailbox)
    fine = await fx.post(
        f"{API}/fees/heads", json={"code": "FINE", "name": "Fine", "recurrence": "one_time"}
    )
    await generate(fx, issue=True)
    issued = await voucher_for(fx, fx.student_ids[0])

    refused = await fx.put(
        f"{API}/fees/vouchers/{issued['id']}/charges",
        json={"head_id": fine.json()["id"], "amount": "300.00"},
    )
    assert refused.status_code == 409, refused.text

    unchanged = await fx.get(f"{API}/fees/vouchers/{issued['id']}")
    assert Decimal(unchanged.json()["total"]) == Decimal("6500.00")


# ---------------------------------------------------------------------------
# 12-18. Late fees
# ---------------------------------------------------------------------------


async def test_a_run_with_no_policy_fines_nobody(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Most schools operate no fine policy. A run that raised here would fill their
    logs every night."""
    fx = await build_fees(tenant, mailbox)
    await generate_overdue(fx, period=PERIOD, issued_days_ago=30, due_days_ago=20)

    run = await fx.post(f"{API}/fees/late-fee-policies/run", params={"academic_year": YEAR})
    assert run.status_code == 200, run.text
    assert run.json()["assessed"] == 0
    assert run.json()["considered"] == 0


async def test_a_fine_is_its_own_challan_pointing_back_at_the_late_one(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Rule 1 again, from the other side: the overdue challan is NOT rewritten.

    The fine is minted as its own voucher -- payable, printable and voidable through
    the machinery staff already use -- and `source_voucher_id` is what makes it
    explicable six months later.
    """
    fx = await build_fees(tenant, mailbox)
    await set_policy(fx)
    await generate_overdue(fx, period=PERIOD, issued_days_ago=30, due_days_ago=20)
    original = await voucher_for(fx, fx.student_ids[0])

    run = await fx.post(f"{API}/fees/late-fee-policies/run", params={"academic_year": YEAR})
    assert run.status_code == 200, run.text
    assert run.json()["assessed"] == 2, "both students are overdue"
    assert Decimal(run.json()["total_charged"]) == Decimal("400.00")

    fine = await fx.get(f"{API}/fees/vouchers/{run.json()['voucher_ids'][0]}")
    assert fine.status_code == 200, fine.text
    body = fine.json()
    assert body["origin"] == "late_fee"
    assert Decimal(body["total"]) == Decimal("200.00")
    assert body["status"] in {"issued", "overdue"}
    assert body["source_voucher_id"] is not None

    # The challan it punishes is byte-for-byte what the parent was given.
    untouched = await fx.get(f"{API}/fees/vouchers/{original['id']}")
    assert Decimal(untouched.json()["total"]) == Decimal(original["total"])
    assert len(untouched.json()["items"]) == len(original["items"])


async def test_re_running_the_fine_job_the_same_day_charges_nothing_further(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """It runs on a schedule, so it WILL be re-run -- retried, overlapped, or clicked
    twice. A job that double-fines is a job a school switches off after one Monday."""
    fx = await build_fees(tenant, mailbox)
    await set_policy(fx)
    await generate_overdue(fx, period=PERIOD, issued_days_ago=30, due_days_ago=20)

    first = await fx.post(f"{API}/fees/late-fee-policies/run", params={"academic_year": YEAR})
    assert first.json()["assessed"] == 2

    second = await fx.post(f"{API}/fees/late-fee-policies/run", params={"academic_year": YEAR})
    assert second.status_code == 200, second.text
    assert second.json()["assessed"] == 0
    assert second.json()["skipped_reasons"] == {"already_assessed": 2}


async def test_a_fine_is_never_itself_fined(tenant: Tenant, mailbox: list[EmailMessage]) -> None:
    """Without the `origin = regular` filter the policy compounds: the fine goes
    overdue, earns a fine, and a 200 rupee penalty reaches four figures unattended."""
    fx = await build_fees(tenant, mailbox)
    await set_policy(fx)
    await generate_overdue(fx, period=PERIOD, issued_days_ago=60, due_days_ago=50)
    await fx.post(f"{API}/fees/late-fee-policies/run", params={"academic_year": YEAR})

    listed = await fx.get(f"{API}/fees/vouchers", params={"size": 100})
    fines = [v for v in listed.json()["items"] if v["origin"] == "late_fee"]
    assert len(fines) == 2

    # A second pass sees the fines but must not consider them candidates.
    again = await fx.post(f"{API}/fees/late-fee-policies/run", params={"academic_year": YEAR})
    assert again.json()["considered"] == 2, "the two regular challans, never the fines"


async def test_grace_days_and_the_minimum_balance_both_hold_the_job_back(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """A parent whose bank posted their payment a day late has not been late, and a
    challan eleven rupees short is not worth a fine, a challan and a phone call."""
    fx = await build_fees(tenant, mailbox)
    await set_policy(fx, grace_days=30)
    await generate_overdue(fx, period=PERIOD, issued_days_ago=20, due_days_ago=10)

    inside_grace = await fx.post(
        f"{API}/fees/late-fee-policies/run", params={"academic_year": YEAR}
    )
    assert inside_grace.json()["assessed"] == 0
    assert inside_grace.json()["considered"] == 0, "the grace period is applied in SQL"

    await set_policy(fx, grace_days=0, min_outstanding="10000.00")
    below_minimum = await fx.post(
        f"{API}/fees/late-fee-policies/run", params={"academic_year": YEAR}
    )
    assert below_minimum.json()["assessed"] == 0
    assert below_minimum.json()["skipped_reasons"] == {"below_minimum": 2}


async def test_a_percentage_fine_is_charged_on_what_is_still_owed(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """A parent who paid four fifths late is fined on the fifth they still owe, not on
    the original total."""
    fx = await build_fees(tenant, mailbox)
    await set_policy(fx, kind="percent", value="10.00")
    await generate_overdue(fx, period=PERIOD, issued_days_ago=30, due_days_ago=20)

    late = await voucher_for(fx, fx.student_ids[0])
    paid = await fx.post(
        f"{API}/fees/vouchers/{late['id']}/payments",
        json={"amount": "5200.00", "method": "cash"},
    )
    assert paid.status_code == 201, paid.text

    run = await fx.post(f"{API}/fees/late-fee-policies/run", params={"academic_year": YEAR})
    assert run.json()["assessed"] == 2

    fines = {}
    listed = await fx.get(f"{API}/fees/vouchers", params={"size": 100})
    for row in listed.json()["items"]:
        if row["origin"] == "late_fee":
            fines[row["student_id"]] = Decimal(row["total"])

    # 10% of 1,300 still owed, versus 10% of the untouched 6,500.
    assert fines[fx.student_ids[0]] == Decimal("130.00")
    assert fines[fx.student_ids[1]] == Decimal("650.00")


async def test_a_settled_challan_is_never_fined(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Tested against `total > paid_total` rather than the stored status, because
    OVERDUE is derived on read here and a challan settled this morning still carries
    yesterday's status."""
    fx = await build_fees(tenant, mailbox)
    await set_policy(fx)
    await generate_overdue(fx, period=PERIOD, issued_days_ago=30, due_days_ago=20)

    settled = await voucher_for(fx, fx.student_ids[0])
    await fx.post(
        f"{API}/fees/vouchers/{settled['id']}/payments",
        json={"amount": settled["total"], "method": "cash"},
    )

    run = await fx.post(f"{API}/fees/late-fee-policies/run", params={"academic_year": YEAR})
    assert run.json()["assessed"] == 1, "only the student who still owes"


async def test_a_recurring_policy_must_declare_where_it_stops(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """An uncapped recurring fine keeps charging a family who has already stopped
    being able to pay, and converts a collection tool into the reason a child
    leaves."""
    fx = await build_fees(tenant, mailbox)
    uncapped = await set_policy(fx, recurrence="weekly")
    assert uncapped.status_code == 422, uncapped.text

    capped = await set_policy(fx, recurrence="weekly", max_amount="500.00")
    assert capped.status_code == 200, capped.text


async def test_a_recurring_fine_stops_at_its_cap(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """The cap is measured against everything already charged against that challan,
    not against one assessment."""
    fx = await build_fees(tenant, mailbox)
    await set_policy(fx, recurrence="weekly", value="200.00", max_amount="300.00")
    # Five weeks overdue: five assessments earned, but the cap allows 1.5.
    await generate_overdue(fx, period=PERIOD, issued_days_ago=45, due_days_ago=35)

    first = await fx.post(f"{API}/fees/late-fee-policies/run", params={"academic_year": YEAR})
    assert first.json()["assessed"] == 2
    assert Decimal(first.json()["total_charged"]) == Decimal("400.00")

    second = await fx.post(f"{API}/fees/late-fee-policies/run", params={"academic_year": YEAR})
    assert Decimal(second.json()["total_charged"]) == Decimal("200.00"), "100 each, to the cap"

    third = await fx.post(f"{API}/fees/late-fee-policies/run", params={"academic_year": YEAR})
    assert third.json()["assessed"] == 0
    assert third.json()["skipped_reasons"] == {"cap_reached": 2}


# ---------------------------------------------------------------------------
# 19-25. The running ledger
# ---------------------------------------------------------------------------


async def test_the_ledger_records_every_movement_and_a_draft_is_not_one(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """A draft is not a bill. A ledger that counted drafts would show families owing
    money nobody has asked them for."""
    fx = await build_fees(tenant, mailbox)
    await generate(fx, issue=False)

    empty = await fx.get(f"{API}/fees/students/{fx.student_ids[0]}/ledger")
    assert empty.status_code == 200, empty.text
    assert Decimal(empty.json()["balance"]) == Decimal("0.00")
    assert empty.json()["entries"] == []

    draft = await voucher_for(fx, fx.student_ids[0])
    issued = await fx.post(f"{API}/fees/vouchers/{draft['id']}/issue")
    assert issued.status_code == 200, issued.text

    charged = await fx.get(f"{API}/fees/students/{fx.student_ids[0]}/ledger")
    assert Decimal(charged.json()["balance"]) == Decimal("6500.00")
    assert charged.json()["entries"][0]["entry_type"] == "charge"
    assert Decimal(charged.json()["entries"][0]["amount"]) == Decimal("6500.00")

    await fx.post(
        f"{API}/fees/vouchers/{draft['id']}/payments",
        json={"amount": "4000.00", "method": "cash"},
    )
    part_paid = await fx.get(f"{API}/fees/students/{fx.student_ids[0]}/ledger")
    assert Decimal(part_paid.json()["balance"]) == Decimal("2500.00")
    assert Decimal(part_paid.json()["entries"][0]["amount"]) == Decimal("-4000.00")
    assert Decimal(part_paid.json()["entries"][0]["balance_after"]) == Decimal("2500.00")


async def test_reversing_a_payment_puts_the_debt_back_as_a_new_entry(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """A NEW entry rather than a correction to the old one. The statement must show
    that money arrived and was then reversed -- which is exactly the sequence a family
    disputing a balance needs to see."""
    fx = await build_fees(tenant, mailbox)
    await generate(fx)
    voucher = await voucher_for(fx, fx.student_ids[0])

    paid = await fx.post(
        f"{API}/fees/vouchers/{voucher['id']}/payments",
        json={"amount": "6500.00", "method": "cash"},
    )
    assert paid.status_code == 201, paid.text

    reversed_ = await fx.post(
        f"{API}/fees/payments/{paid.json()['id']}/reverse",
        json={"reason": "Cheque bounced"},
    )
    assert reversed_.status_code == 200, reversed_.text

    statement = await fx.get(f"{API}/fees/students/{fx.student_ids[0]}/ledger")
    body = statement.json()
    assert Decimal(body["balance"]) == Decimal("6500.00")
    assert [e["entry_type"] for e in body["entries"]] == [
        "payment_reversed",
        "payment",
        "charge",
    ]


async def test_voiding_an_issued_challan_credits_the_family_and_voiding_a_draft_does_not(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Voiding a draft cancels a bill that was never raised. Crediting for it would
    hand the family money the school never asked them for."""
    fx = await build_fees(tenant, mailbox)
    await generate(fx, issue=True)
    issued = await voucher_for(fx, fx.student_ids[0])
    await fx.post(f"{API}/fees/vouchers/{issued['id']}/void", json={"reason": "Withdrawn"})

    settled = await fx.get(f"{API}/fees/students/{fx.student_ids[0]}/ledger")
    assert Decimal(settled.json()["balance"]) == Decimal("0.00")
    assert settled.json()["entries"][0]["entry_type"] == "voucher_voided"

    # The classmate was billed in August too, so their ledger is not empty. What must
    # be true is narrower and more interesting: voiding their SEPTEMBER draft adds
    # nothing at all, because a draft never debited them in the first place.
    before = await fx.get(f"{API}/fees/students/{fx.student_ids[1]}/ledger")
    assert before.json()["total_entries"] == 1, "August only"

    await generate(fx, period="2026-09", issue=False)
    listed = await fx.get(
        f"{API}/fees/vouchers",
        params={"student_id": fx.student_ids[1], "period_label": "2026-09"},
    )
    draft_id = listed.json()["items"][0]["id"]
    await fx.post(f"{API}/fees/vouchers/{draft_id}/void", json={"reason": "Mis-generated"})

    after = await fx.get(f"{API}/fees/students/{fx.student_ids[1]}/ledger")
    assert after.json()["total_entries"] == 1, "voiding a draft credits nothing"
    assert Decimal(after.json()["balance"]) == Decimal(before.json()["balance"])
    assert all(e["entry_type"] != "voucher_voided" for e in after.json()["entries"])


async def test_arrears_are_printed_on_the_next_challan_and_never_billed_twice(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """THE DOUBLE-COUNTING TEST.

    Adding the carried balance into `total` would bill the same rupee twice -- once on
    the unpaid August challan that is still outstanding, and again on September. The
    school would find out at the counter, with the parent holding both.
    """
    fx = await build_fees(tenant, mailbox)
    await generate(fx, period="2026-08", issue=True)

    september = await generate(fx, period="2026-09", issue=True)
    assert september.status_code == 201, september.text

    listed = await fx.get(
        f"{API}/fees/vouchers",
        params={"student_id": fx.student_ids[0], "period_label": "2026-09"},
    )
    row = listed.json()["items"][0]
    assert Decimal(row["arrears_brought_forward"]) == Decimal("6500.00"), "August, unpaid"
    assert Decimal(row["total"]) == Decimal("6500.00"), "September only -- NOT 13,000"

    # And the ledger, which is where the 13,000 legitimately lives.
    statement = await fx.get(f"{API}/fees/students/{fx.student_ids[0]}/ledger")
    assert Decimal(statement.json()["balance"]) == Decimal("13000.00")


async def test_a_manual_adjustment_needs_fee_void_not_fee_collect(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """The one action here that moves money with no voucher and no receipt behind it,
    which makes it the one an accountant could use to cover a shortfall."""
    fx = await build_fees(tenant, mailbox)
    await generate(fx)

    collector_token = await make_scoped_actor(
        fx.tenant,
        mailbox,
        "collector-adjust@test.example",
        ["fee:read", "fee:collect"],
        code="collector_adjust",
    )
    refused = await fx.tenant.client.post(
        f"{API}/fees/students/{fx.student_ids[0]}/ledger/adjustments",
        headers={"Authorization": f"Bearer {collector_token}"},
        json={
            "amount": "-6500.00",
            "academic_year": YEAR,
            "description": "Written off",
        },
    )
    assert refused.status_code == 403, refused.text

    allowed = await fx.post(
        f"{API}/fees/students/{fx.student_ids[0]}/ledger/adjustments",
        json={
            "amount": "-6500.00",
            "academic_year": YEAR,
            "description": "Written off — hardship, approved by principal",
        },
    )
    assert allowed.status_code == 201, allowed.text
    assert Decimal(allowed.json()["balance"]) == Decimal("0.00")
    assert allowed.json()["entries"][0]["entry_type"] == "adjustment"


async def test_one_organizations_ledger_is_invisible_to_another(
    tenant: Tenant, make_tenant: Any, mailbox: list[EmailMessage]
) -> None:
    """Through the app's own NOBYPASSRLS connection, so this exercises the POLICY on
    `student_ledger_entries` rather than an application filter. A fee ledger without
    one exposes which families at every school in the system are in arrears."""
    org_a = tenant
    org_b = await make_tenant(
        name="Ledger B Trust", email="ledger-b@test.example", school_code="LEDGERB"
    )

    fx_a = await build_fees(org_a, mailbox, email="ledger-a-head@test.example")
    await generate(fx_a)

    factory = get_session_factory()
    async with factory() as app_session:
        await bind_tenant(app_session, UUID(org_b.organization_id))
        visible = (
            await app_session.execute(
                text("SELECT count(*) FROM student_ledger_entries WHERE organization_id = :org"),
                {"org": org_a.organization_id},
            )
        ).scalar_one()
        assert visible == 0, "B must not see A's ledger"

        # And WITH CHECK refuses B stamping a row into A.
        with pytest.raises(DBAPIError, match="row-level security"):
            await app_session.execute(
                text(
                    "INSERT INTO student_ledger_entries "
                    "(organization_id, school_id, student_id, entry_type, academic_year, "
                    " amount, balance_after, occurred_on, description) "
                    "VALUES (:org, :school, :student, 'adjustment', '2026-2027', "
                    " -1, -1, CURRENT_DATE, 'hijack')"
                ),
                {
                    "org": org_a.organization_id,
                    "school": org_a.school_id,
                    "student": fx_a.student_ids[0],
                },
            )
        await app_session.rollback()


async def test_the_voucher_register_exports_as_csv(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """The register a finance office reconciles against its bank statement.

    Declared before `/vouchers/{voucher_id}`, or Starlette parses "export" as a UUID.
    """
    fx = await build_fees(tenant, mailbox)
    await generate(fx)

    exported = await fx.get(f"{API}/fees/vouchers/export", params={"academic_year": YEAR})
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("text/csv")
    assert "attachment" in exported.headers["content-disposition"]

    lines = [line for line in exported.text.splitlines() if line.strip()]
    assert lines[0].startswith("voucher_number,admission_number,student_name")
    assert len(lines) == 3, "a header and both students"
    assert "6500.00" in exported.text
    assert "TRUNCATED" not in exported.text
