"""`GET /students?fees=...` -- the defaulters filter on the students list.

WHAT THESE TESTS ARE DEFENDING
    The filter crosses a module boundary: a students query whose WHERE clause is
    answered by the fees ledger. That makes two failure modes possible that neither
    module's own tests would catch.

    The first is a JOIN that multiplies. A student with three unpaid challans is one
    defaulter; if the implementation ever becomes a join rather than a subquery, the
    rows duplicate and -- worse than the visible duplication -- the PAGE COUNT
    silently inflates. `test_a_student_with_several_unpaid_challans_appears_once`
    exists solely to fail when that happens.

    The second is the definition drifting. "Owes money" has three exclusions that are
    each individually defensible to get wrong (draft, void, already-paid), and each
    one puts a family on a defaulters list who does not belong there.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from tests.integration.conftest import API, STRONG_PASSWORD, Tenant
from tests.integration.test_fees import PERIOD, FeeFixture, build_fees, generate


async def _generate_late(fx: FeeFixture, *, period: str = PERIOD) -> Any:
    """A challan whose due date has already passed.

    Both dates are moved back, not just the due date: `ck_fee_vouchers_due_after_issue`
    refuses a bill due before it was issued, which is the database refusing to model a
    debt that was late the moment it existed.
    """
    today = date.today()
    return await generate(
        fx,
        period=period,
        issue_date=(today - timedelta(days=30)).isoformat(),
        due_date=(today - timedelta(days=3)).isoformat(),
    )


async def _ids(fx: FeeFixture, fees: str | None = None) -> set[str]:
    """Student ids the list returns under one fee filter."""
    params: dict[str, Any] = {"size": 100}
    if fees is not None:
        params["fees"] = fees
    listed = await fx.get(f"{API}/students", params=params)
    assert listed.status_code == 200, listed.text
    return {row["id"] for row in listed.json()["items"]}


async def test_pending_lists_only_students_who_owe(tenant: Tenant, mailbox: list[Any]) -> None:
    """One student pays in full, the other does not. Only the debtor is pending."""
    fx = await build_fees(tenant, mailbox)
    run = await generate(fx)
    assert run.status_code == 201, run.text

    vouchers = await fx.get(f"{API}/fees/vouchers", params={"size": 100})
    assert vouchers.status_code == 200, vouchers.text
    rows = vouchers.json()["items"]

    settled = next(v for v in rows if v["student_id"] == fx.student_ids[0])
    paid = await fx.post(
        f"{API}/fees/vouchers/{settled['id']}/payments",
        json={"amount": settled["total"], "method": "cash"},
    )
    assert paid.status_code == 201, paid.text

    pending = await _ids(fx, "pending")
    assert fx.student_ids[1] in pending
    assert fx.student_ids[0] not in pending, "paid in full -- must not be a defaulter"

    # The two sets partition the roll: everyone is either owing or clear.
    clear = await _ids(fx, "clear")
    assert fx.student_ids[0] in clear
    assert pending | clear == await _ids(fx)
    assert not (pending & clear)


async def test_a_partly_paid_challan_still_counts_as_owing(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    """Part of the money is not the money. A family who paid half still owes half."""
    fx = await build_fees(tenant, mailbox)
    assert (await generate(fx)).status_code == 201

    vouchers = await fx.get(f"{API}/fees/vouchers", params={"size": 100})
    voucher = next(v for v in vouchers.json()["items"] if v["student_id"] == fx.student_ids[0])
    part = await fx.post(
        f"{API}/fees/vouchers/{voucher['id']}/payments",
        json={"amount": "100.00", "method": "cash"},
    )
    assert part.status_code == 201, part.text

    assert fx.student_ids[0] in await _ids(fx, "pending")


async def test_a_draft_challan_is_not_a_debt(tenant: Tenant, mailbox: list[Any]) -> None:
    """THE EXCLUSION MOST WORTH PINNING.

    A draft has never left the office. Listing that family as owing money is a
    conversation the school cannot win at the counter -- they were never asked to pay.
    """
    fx = await build_fees(tenant, mailbox)
    drafted = await generate(fx, issue=False)
    assert drafted.status_code == 201, drafted.text

    pending = await _ids(fx, "pending")
    assert not pending & set(fx.student_ids), "nothing was issued -- nobody owes anything"

    # ...and issuing the very same challan turns them into debtors.
    for voucher_id in drafted.json()["voucher_ids"]:
        issued = await fx.post(f"{API}/fees/vouchers/{voucher_id}/issue")
        assert issued.status_code == 200, issued.text

    assert set(fx.student_ids) <= await _ids(fx, "pending")


async def test_a_voided_challan_is_not_a_debt(tenant: Tenant, mailbox: list[Any]) -> None:
    fx = await build_fees(tenant, mailbox)
    run = await generate(fx)
    assert run.status_code == 201, run.text

    for voucher_id in run.json()["voucher_ids"]:
        voided = await fx.post(
            f"{API}/fees/vouchers/{voucher_id}/void", json={"reason": "Issued in error"}
        )
        assert voided.status_code == 200, voided.text

    assert not await _ids(fx, "pending") & set(fx.student_ids)


async def test_overdue_is_the_late_subset_of_pending(tenant: Tenant, mailbox: list[Any]) -> None:
    """A challan due next week is pending but NOT overdue.

    The distinction is the whole reason the filter has three states instead of two:
    a bill that has not fallen due yet is not a delinquency, and putting those
    families on the chase list buries the ones who are genuinely late.
    """
    fx = await build_fees(tenant, mailbox)
    assert (await generate(fx, due_in_days=14)).status_code == 201

    assert set(fx.student_ids) <= await _ids(fx, "pending")
    assert not await _ids(fx, "overdue") & set(fx.student_ids)


async def test_a_past_due_challan_is_overdue(tenant: Tenant, mailbox: list[Any]) -> None:
    fx = await build_fees(tenant, mailbox)
    late = await _generate_late(fx)
    assert late.status_code == 201, late.text

    overdue = await _ids(fx, "overdue")
    pending = await _ids(fx, "pending")
    assert set(fx.student_ids) <= overdue
    assert overdue <= pending, "late money is also money owed"


async def test_a_student_with_several_unpaid_challans_appears_once(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    """Three debts, one defaulter.

    Guards the subquery against becoming a join. Duplicated rows would be visible,
    but the inflated page TOTAL would not be -- and that is the number the pagination
    controls are drawn from.
    """
    fx = await build_fees(tenant, mailbox)
    for index, period in enumerate((PERIOD, "2026-09", "2026-10")):
        run = await generate(fx, period=period, due_in_days=14 - index)
        assert run.status_code == 201, run.text

    listed = await fx.get(f"{API}/students", params={"size": 100, "fees": "pending"})
    assert listed.status_code == 200, listed.text
    body = listed.json()

    ids = [row["id"] for row in body["items"]]
    assert len(ids) == len(set(ids)), "a student with three unpaid challans is ONE row"
    assert body["meta"]["total"] == len(ids), "the page total must match the rows on it"


async def test_clear_includes_a_student_who_was_never_billed(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    """A child enrolled after the billing run owes nothing, and must be findable.

    `clear` means "does not owe the school anything", not "has paid". A student with
    no challan at all is the case that separates those two readings.
    """
    fx = await build_fees(tenant, mailbox)
    assert (await generate(fx)).status_code == 201

    newcomer = await fx.post(
        f"{API}/students",
        json={
            "admission_number": f"{date.today().year}-NEW",
            "first_name": "Late",
            "last_name": "Joiner",
            "section_id": fx.section_id,
            "guardian_name": "Parent Test",
            "guardian_phone": "03007654321",
        },
    )
    assert newcomer.status_code == 201, newcomer.text
    newcomer_id = newcomer.json()["id"]

    assert newcomer_id in await _ids(fx, "clear")
    assert newcomer_id not in await _ids(fx, "pending")


async def test_the_filter_composes_with_the_other_filters(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    """`fees` narrows alongside `section_id`, rather than replacing it.

    Filters that quietly override one another are the classic listing bug, and it
    only shows up when two are set at once.
    """
    fx = await build_fees(tenant, mailbox)
    late = await _generate_late(fx)
    assert late.status_code == 201, late.text

    combined = await fx.get(
        f"{API}/students",
        params={"size": 100, "fees": "overdue", "section_id": fx.section_id},
    )
    assert combined.status_code == 200, combined.text
    assert {row["id"] for row in combined.json()["items"]} == set(fx.student_ids)

    # A section nobody in the overdue set belongs to yields nothing, rather than
    # falling back to "all overdue students".
    other_class = await fx.post(f"{API}/classes", json={"name": "Grade 11", "level": 11})
    assert other_class.status_code == 201, other_class.text
    other_section = await fx.post(
        f"{API}/classes/{other_class.json()['id']}/sections", json={"name": "Z"}
    )
    assert other_section.status_code == 201, other_section.text

    empty = await fx.get(
        f"{API}/students",
        params={"size": 100, "fees": "overdue", "section_id": other_section.json()["id"]},
    )
    assert empty.status_code == 200, empty.text
    assert empty.json()["items"] == []


async def test_an_unknown_fee_filter_is_rejected(tenant: Tenant, mailbox: list[Any]) -> None:
    """422, not a silently ignored parameter. A typo'd filter that returns the whole
    roll looks exactly like a school with no defaulters."""
    fx = await build_fees(tenant, mailbox)
    response = await fx.get(f"{API}/students", params={"fees": "unpaid"})
    assert response.status_code == 422, response.text


async def test_the_filter_requires_permission_to_view_fees(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    """A teacher can read the roll but must not be able to enumerate who owes money.

    `?fees=overdue` is a list of the families behind on their payments. The seeded
    teacher role holds `student:read` and NOT `fee:read`, and that gap is the whole
    point of this test: the filter has to be refused rather than quietly ignored,
    because an unfiltered roll reads as "this school has no defaulters".
    """
    fx = await build_fees(tenant, mailbox)
    assert (await generate(fx)).status_code == 201

    roles = await fx.get(f"{API}/schools/{tenant.school_id}/roles")
    assert roles.status_code == 200, roles.text
    teacher_role = next(r for r in roles.json() if r["code"] == "teacher")
    created = await fx.post(
        f"{API}/schools/{tenant.school_id}/members",
        json={
            "email": "nosy.teacher@test.example",
            "full_name": "Nosy Teacher",
            "password": STRONG_PASSWORD,
            "role_id": teacher_role["id"],
        },
    )
    assert created.status_code == 201, created.text

    tenant.client.cookies.clear()
    login = await tenant.client.post(
        f"{API}/auth/login",
        json={"email": "nosy.teacher@test.example", "password": STRONG_PASSWORD},
        headers={"X-Token-Transport": "body"},
    )
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.headers['X-Access-Token']}"}
    tenant.client.cookies.clear()

    # The roll itself is readable...
    roll = await tenant.client.get(f"{API}/students", headers=headers)
    assert roll.status_code == 200, roll.text

    # ...but not sliced by who owes money.
    refused = await tenant.client.get(
        f"{API}/students", params={"fees": "overdue"}, headers=headers
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "FEE_READ_REQUIRED"


# ---------------------------------------------------------------------------
# The amount shown beside each row
# ---------------------------------------------------------------------------


async def _row(fx: FeeFixture, student_id: str, fees: str) -> dict[str, Any]:
    listed = await fx.get(f"{API}/students", params={"size": 100, "fees": fees})
    assert listed.status_code == 200, listed.text
    return next(r for r in listed.json()["items"] if r["id"] == student_id)


async def test_dues_carry_the_amount_and_the_period(tenant: Tenant, mailbox: list[Any]) -> None:
    """The number on the row is what the family owes, labelled with the period.

    The period is half the point: "8,800" starts no conversation at the counter,
    "8,800 for Term 1" tells the clerk which challan to open.
    """
    fx = await build_fees(tenant, mailbox)
    assert (await generate(fx)).status_code == 201

    vouchers = await fx.get(f"{API}/fees/vouchers", params={"size": 100})
    voucher = next(v for v in vouchers.json()["items"] if v["student_id"] == fx.student_ids[0])

    row = await _row(fx, fx.student_ids[0], "pending")
    assert row["dues"] is not None
    assert Decimal(row["dues"]["amount"]) == Decimal(voucher["total"])
    assert row["dues"]["periods"] == [PERIOD]
    assert row["dues"]["currency"] == voucher["currency"]


async def test_dues_are_net_of_what_has_been_paid(tenant: Tenant, mailbox: list[Any]) -> None:
    """A part payment reduces the figure. Showing the gross would have the office
    chasing money the family already handed over."""
    fx = await build_fees(tenant, mailbox)
    assert (await generate(fx)).status_code == 201

    vouchers = await fx.get(f"{API}/fees/vouchers", params={"size": 100})
    voucher = next(v for v in vouchers.json()["items"] if v["student_id"] == fx.student_ids[0])
    paid = await fx.post(
        f"{API}/fees/vouchers/{voucher['id']}/payments",
        json={"amount": "100.00", "method": "cash"},
    )
    assert paid.status_code == 201, paid.text

    row = await _row(fx, fx.student_ids[0], "pending")
    assert Decimal(row["dues"]["amount"]) == Decimal(voucher["total"]) - Decimal("100.00")


async def test_dues_sum_across_periods_and_list_each_one(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    """Three unpaid months are one total and three labels, oldest first."""
    fx = await build_fees(tenant, mailbox)
    for offset, period in enumerate(("2026-08", "2026-09", "2026-10")):
        run = await generate(fx, period=period, due_in_days=offset + 1)
        assert run.status_code == 201, run.text

    vouchers = await fx.get(f"{API}/fees/vouchers", params={"size": 100})
    mine = [v for v in vouchers.json()["items"] if v["student_id"] == fx.student_ids[0]]
    expected = sum((Decimal(v["total"]) for v in mine), Decimal("0"))

    row = await _row(fx, fx.student_ids[0], "pending")
    assert Decimal(row["dues"]["amount"]) == expected
    assert row["dues"]["periods"] == ["2026-08", "2026-09", "2026-10"]


async def test_the_overdue_amount_excludes_money_not_yet_due(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    """THE TEST THAT PINS "ACCORDING TO THE FILTER".

    One late challan and one not yet due. Under `fees=overdue` the row must show the
    LATE half only -- a family shown their full balance on an overdue list is being
    chased for money they have not yet been asked for, and the school cannot defend
    the number.
    """
    fx = await build_fees(tenant, mailbox)
    late = await _generate_late(fx, period="2026-07")
    assert late.status_code == 201, late.text
    upcoming = await generate(fx, period="2026-12", due_in_days=30)
    assert upcoming.status_code == 201, upcoming.text

    vouchers = await fx.get(f"{API}/fees/vouchers", params={"size": 100})
    mine = [v for v in vouchers.json()["items"] if v["student_id"] == fx.student_ids[0]]
    late_total = sum(
        (Decimal(v["total"]) for v in mine if v["period_label"] == "2026-07"), Decimal("0")
    )
    both_total = sum((Decimal(v["total"]) for v in mine), Decimal("0"))

    overdue_row = await _row(fx, fx.student_ids[0], "overdue")
    assert Decimal(overdue_row["dues"]["amount"]) == late_total
    assert overdue_row["dues"]["periods"] == ["2026-07"]

    # ...while the pending view of the same student shows everything owed.
    pending_row = await _row(fx, fx.student_ids[0], "pending")
    assert Decimal(pending_row["dues"]["amount"]) == both_total
    assert set(pending_row["dues"]["periods"]) == {"2026-07", "2026-12"}


async def test_no_amounts_are_sent_without_a_fee_filter(tenant: Tenant, mailbox: list[Any]) -> None:
    """An unfiltered roll carries no balances at all.

    This is the disclosure boundary, not a rendering detail: `fees` requires
    `fee:read`, so refusing to compute amounts without it is what keeps every
    family's balance off a list that a teacher is allowed to read.
    """
    fx = await build_fees(tenant, mailbox)
    assert (await generate(fx)).status_code == 201

    listed = await fx.get(f"{API}/students", params={"size": 100})
    assert listed.status_code == 200, listed.text
    assert all(row["dues"] is None for row in listed.json()["items"])


async def test_dues_split_the_late_portion_out_of_the_total(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    """THE FIELD THE TABLE COLOURS BY.

    One late challan and one not yet due. Under `fees=pending` the row must report
    the FULL balance as `amount` and only the late half as `overdue_amount` -- that
    split is what lets the list show red for "chase this" and amber for "owed, not
    late", instead of painting every pending row the same and distinguishing nothing.
    """
    fx = await build_fees(tenant, mailbox)
    late = await _generate_late(fx, period="2026-07")
    assert late.status_code == 201, late.text
    upcoming = await generate(fx, period="2026-12", due_in_days=30)
    assert upcoming.status_code == 201, upcoming.text

    vouchers = await fx.get(f"{API}/fees/vouchers", params={"size": 100})
    mine = [v for v in vouchers.json()["items"] if v["student_id"] == fx.student_ids[0]]
    late_total = sum(
        (Decimal(v["total"]) for v in mine if v["period_label"] == "2026-07"), Decimal("0")
    )
    both_total = sum((Decimal(v["total"]) for v in mine), Decimal("0"))
    assert 0 < late_total < both_total, "fixture must produce a PARTLY late balance"

    row = await _row(fx, fx.student_ids[0], "pending")
    assert Decimal(row["dues"]["amount"]) == both_total
    assert Decimal(row["dues"]["overdue_amount"]) == late_total


async def test_a_balance_not_yet_due_reports_zero_overdue(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    """Owed is not late. A challan issued today with a due date next fortnight must
    report zero overdue, or the table paints it red and the office chases a family
    that has done nothing wrong."""
    fx = await build_fees(tenant, mailbox)
    assert (await generate(fx, due_in_days=14)).status_code == 201

    row = await _row(fx, fx.student_ids[0], "pending")
    assert Decimal(row["dues"]["amount"]) > 0
    assert Decimal(row["dues"]["overdue_amount"]) == 0


async def test_under_the_overdue_filter_the_whole_amount_is_late(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    """`fees=overdue` selected only late challans, so the two figures coincide.

    Worth pinning because they are computed from different predicates -- the filter's
    `due_before` and the row's own due date -- and a drift between them would show a
    row whose 'overdue' portion exceeded, or fell short of, the amount beside it.
    """
    fx = await build_fees(tenant, mailbox)
    assert (await _generate_late(fx)).status_code == 201
    assert (await generate(fx, period="2026-12", due_in_days=30)).status_code == 201

    row = await _row(fx, fx.student_ids[0], "overdue")
    assert Decimal(row["dues"]["overdue_amount"]) == Decimal(row["dues"]["amount"])
    assert Decimal(row["dues"]["amount"]) > 0
