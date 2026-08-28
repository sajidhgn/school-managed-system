"""Fees module release gate -- docs/modules/fees.md §14.

These run through the app's own `sms_app` connection (NOBYPASSRLS), so the isolation
cases exercise PostgreSQL's policies rather than an application filter. If a policy
regressed -- or was never created on one of the six new tables -- they fail even
though every behavioural test still passes.

The behavioural cases guard the two rules the module is built on: issued money
records are immutable (a rename or a reprice never rewrites a challan a parent
holds), and financial rows are voided or reversed rather than deleted.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.email.sender import EmailMessage
from app.db.session import bind_tenant, get_session_factory
from app.modules.fees.models import FeeLineType
from tests.integration.conftest import (
    API,
    STRONG_PASSWORD,
    Tenant,
    latest_token,
    make_campus_head,
)

YEAR = "2026-2027"
PERIOD = "2026-08"


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------


async def make_scoped_actor(
    tenant: Tenant,
    mailbox: list[EmailMessage],
    email: str,
    permissions: list[str],
    *,
    code: str,
    school_id: str | None = None,
) -> str:
    """A school-scoped member holding EXACTLY `permissions`. Returns their token.

    `make_campus_head` grants every school-scoped code, which is the wrong subject
    for the separation-of-duties cases: proving `fee:collect` cannot void requires an
    actor who holds one and not the other. Built through the public role editor, so
    it also checks the editor can express these sets at all.
    """
    role = await tenant.post(
        f"{API}/schools/{school_id or tenant.school_id}/roles",
        json={"code": code, "name": code.replace("_", " ").title(), "permissions": permissions},
    )
    assert role.status_code == 201, role.text

    invited = await tenant.post(
        f"{API}/schools/{school_id or tenant.school_id}/invitations",
        json={"email": email, "full_name": "Fee Actor", "role_id": role.json()["id"]},
    )
    assert invited.status_code == 201, invited.text

    tenant.client.cookies.clear()
    accepted = await tenant.client.post(
        f"{API}/invitations/accept",
        json={
            "token": latest_token(mailbox),
            "full_name": "Fee Actor",
            "password": STRONG_PASSWORD,
        },
    )
    assert accepted.status_code == 200, accepted.text
    tenant.client.cookies.clear()

    login = await tenant.client.post(
        f"{API}/auth/login",
        json={"email": email, "password": STRONG_PASSWORD},
        headers={"X-Token-Transport": "body"},
    )
    assert login.status_code == 200, login.text
    tenant.client.cookies.clear()
    return str(login.headers["X-Access-Token"])


class FeeFixture:
    """A school with a priced class and two enrolled students, ready to bill."""

    def __init__(self, tenant: Tenant, token: str) -> None:
        self.tenant = tenant
        self.token = token
        self.headers = {"Authorization": f"Bearer {token}"}
        self.class_id: str = ""
        self.section_id: str = ""
        self.student_ids: list[str] = []
        self.head_ids: dict[str, str] = {}
        self.structure_id: str = ""

    async def post(self, url: str, **kw: Any) -> Any:
        return await self.tenant.client.post(url, headers=self.headers, **kw)

    async def get(self, url: str, **kw: Any) -> Any:
        return await self.tenant.client.get(url, headers=self.headers, **kw)

    async def patch(self, url: str, **kw: Any) -> Any:
        return await self.tenant.client.patch(url, headers=self.headers, **kw)

    async def put(self, url: str, **kw: Any) -> Any:
        return await self.tenant.client.put(url, headers=self.headers, **kw)

    async def delete(self, url: str, **kw: Any) -> Any:
        return await self.tenant.client.delete(url, headers=self.headers, **kw)


async def build_fees(
    tenant: Tenant,
    mailbox: list[EmailMessage],
    *,
    email: str = "fees-head@test.example",
    students: int = 2,
    tuition: str = "5000.00",
    transport: str = "1500.00",
) -> FeeFixture:
    """Class -> section -> students -> heads -> ACTIVE structure.

    Everything is built through the public API rather than by inserting rows, so a
    fixture can never construct a state the application itself could not produce.
    """
    token = await make_campus_head(tenant, mailbox, email)
    fx = FeeFixture(tenant, token)

    created_class = await fx.post(f"{API}/classes", json={"name": "Grade 10", "level": 10})
    assert created_class.status_code == 201, created_class.text
    fx.class_id = created_class.json()["id"]

    section = await fx.post(f"{API}/classes/{fx.class_id}/sections", json={"name": "A"})
    assert section.status_code == 201, section.text
    fx.section_id = section.json()["id"]

    for index in range(students):
        student = await fx.post(
            f"{API}/students",
            json={
                "admission_number": f"2026-{index + 1:03d}",
                "first_name": "Student",
                "last_name": f"Number{index + 1}",
                "section_id": fx.section_id,
            },
        )
        assert student.status_code == 201, student.text
        fx.student_ids.append(student.json()["id"])

    for code, name in (("TUITION", "Tuition"), ("TRANSPORT", "Transport")):
        head = await fx.post(
            f"{API}/fees/heads", json={"code": code, "name": name, "recurrence": "monthly"}
        )
        assert head.status_code == 201, head.text
        fx.head_ids[code] = head.json()["id"]

    structure = await fx.post(
        f"{API}/fees/structures",
        json={
            "class_id": fx.class_id,
            "academic_year": YEAR,
            "name": f"Grade 10 {YEAR}",
            "items": [
                {"head_id": fx.head_ids["TUITION"], "amount": tuition},
                {"head_id": fx.head_ids["TRANSPORT"], "amount": transport},
            ],
        },
    )
    assert structure.status_code == 201, structure.text
    fx.structure_id = structure.json()["id"]

    activated = await fx.post(f"{API}/fees/structures/{fx.structure_id}/activate")
    assert activated.status_code == 200, activated.text
    return fx


async def generate(
    fx: FeeFixture,
    *,
    period: str = PERIOD,
    issue: bool = True,
    due_in_days: int = 14,
    **extra: Any,
) -> Any:
    today = date.today()
    return await fx.post(
        f"{API}/fees/vouchers/generate",
        json={
            "structure_id": fx.structure_id,
            "period_label": period,
            "issue_date": today.isoformat(),
            "due_date": (today + timedelta(days=due_in_days)).isoformat(),
            "issue_immediately": issue,
            **extra,
        },
    )


# ---------------------------------------------------------------------------
# 1-4. Isolation -- the gate that matters most
# ---------------------------------------------------------------------------


async def test_organization_cannot_read_another_organizations_fee_records(
    make_tenant: Callable[..., Any],
    mailbox: list[EmailMessage],
) -> None:
    """Spec §14.1/§14.2: Org A sees no row of Org B's, and known ids are 404 not 403.

    A 403 would confirm the record exists, which over a fee ledger discloses that a
    school is a customer and lets an attacker enumerate valid ids by watching which
    ones answer differently.
    """
    org_a: Tenant = await make_tenant(name="Alpha Trust", email="a@test.example", school_code="A")
    org_b: Tenant = await make_tenant(name="Beta Trust", email="b@test.example", school_code="B")

    fx_a = await build_fees(org_a, mailbox, email="a-fees@test.example")
    fx_b = await build_fees(org_b, mailbox, email="b-fees@test.example")

    b_run = await generate(fx_b)
    assert b_run.status_code == 201, b_run.text
    b_voucher_id = b_run.json()["voucher_ids"][0]

    b_payment = await fx_b.post(
        f"{API}/fees/vouchers/{b_voucher_id}/payments", json={"amount": "100.00", "method": "cash"}
    )
    assert b_payment.status_code == 201, b_payment.text
    b_payment_id = b_payment.json()["id"]

    # A's listings contain nothing of B's.
    a_heads = await fx_a.get(f"{API}/fees/heads")
    a_structures = await fx_a.get(f"{API}/fees/structures")
    a_vouchers = await fx_a.get(f"{API}/fees/vouchers")
    assert a_heads.status_code == a_structures.status_code == a_vouchers.status_code == 200
    assert b_voucher_id not in {row["id"] for row in a_vouchers.json()["items"]}
    assert fx_b.structure_id not in {row["id"] for row in a_structures.json()["items"]}
    assert set(fx_b.head_ids.values()).isdisjoint({row["id"] for row in a_heads.json()["items"]})

    # Every direct read of a known B id is a 404.
    reads = (
        await fx_a.get(f"{API}/fees/heads/{fx_b.head_ids['TUITION']}"),
        await fx_a.get(f"{API}/fees/structures/{fx_b.structure_id}"),
        await fx_a.get(f"{API}/fees/vouchers/{b_voucher_id}"),
        await fx_a.get(f"{API}/fees/vouchers/{b_voucher_id}/pdf"),
        await fx_a.get(f"{API}/fees/vouchers/{b_voucher_id}/payments"),
    )
    assert all(r.status_code == 404 for r in reads), [(r.status_code, r.text) for r in reads]

    # Spec §14.2: and every mutation, too.
    writes = (
        await fx_a.patch(f"{API}/fees/heads/{fx_b.head_ids['TUITION']}", json={"name": "Hijacked"}),
        await fx_a.delete(f"{API}/fees/heads/{fx_b.head_ids['TUITION']}"),
        await fx_a.patch(f"{API}/fees/structures/{fx_b.structure_id}", json={"name": "Hijacked"}),
        await fx_a.post(f"{API}/fees/structures/{fx_b.structure_id}/archive"),
        await fx_a.post(f"{API}/fees/vouchers/{b_voucher_id}/issue"),
        await fx_a.post(
            f"{API}/fees/vouchers/{b_voucher_id}/void", json={"reason": "hijack attempt"}
        ),
        await fx_a.post(
            f"{API}/fees/vouchers/{b_voucher_id}/payments",
            json={"amount": "1.00", "method": "cash"},
        ),
        await fx_a.post(f"{API}/fees/payments/{b_payment_id}/reverse", json={"reason": "hijack"}),
    )
    assert all(r.status_code == 404 for r in writes), [(r.status_code, r.text) for r in writes]

    # And B is byte-identical afterwards.
    check = await fx_b.get(f"{API}/fees/vouchers/{b_voucher_id}")
    assert check.status_code == 200
    body = check.json()
    assert body["status"] == "partly_paid"
    assert body["paid_total"] == "100.00"
    assert body["void_reason"] is None

    head = await fx_b.get(f"{API}/fees/heads/{fx_b.head_ids['TUITION']}")
    assert head.json()["name"] == "Tuition"


async def test_campus_scope_holds_between_schools_in_one_organization(
    tenant: Tenant,
    mailbox: list[EmailMessage],
) -> None:
    """Spec §14.3: RLS deliberately permits every school inside one organization, so
    the campus boundary is the repository's job. A School A accountant must not reach
    School B's vouchers -- while the org-level principal still reads both."""
    second = await tenant.post(f"{API}/schools", json={"name": "Second Campus", "code": "SECOND"})
    assert second.status_code == 201, second.text
    second_school_id = second.json()["id"]

    fx_a = await build_fees(tenant, mailbox, email="campus-a@test.example")
    a_run = await generate(fx_a)
    assert a_run.status_code == 201, a_run.text
    a_voucher_id = a_run.json()["voucher_ids"][0]

    # A genuinely school-scoped actor at the SECOND campus.
    b_token = await make_campus_head(
        tenant, mailbox, "campus-b@test.example", school_id=second_school_id, code="campus_b_head"
    )
    b_headers = {"Authorization": f"Bearer {b_token}"}

    listing = await tenant.client.get(f"{API}/fees/vouchers", headers=b_headers)
    assert listing.status_code == 200
    assert listing.json()["items"] == []

    heads = await tenant.client.get(f"{API}/fees/heads", headers=b_headers)
    assert heads.json()["items"] == [], "campus B saw campus A's fee heads"

    cross = (
        await tenant.client.get(f"{API}/fees/vouchers/{a_voucher_id}", headers=b_headers),
        await tenant.client.get(f"{API}/fees/vouchers/{a_voucher_id}/pdf", headers=b_headers),
        await tenant.client.post(
            f"{API}/fees/vouchers/{a_voucher_id}/payments",
            json={"amount": "1.00", "method": "cash"},
            headers=b_headers,
        ),
        await tenant.client.post(
            f"{API}/fees/vouchers/{a_voucher_id}/void",
            json={"reason": "cross-campus"},
            headers=b_headers,
        ),
    )
    assert all(r.status_code == 404 for r in cross), [(r.status_code, r.text) for r in cross]

    # The org-level principal, naming no campus, intentionally spans both.
    principal_view = await tenant.get(f"{API}/fees/vouchers")
    assert principal_view.status_code == 200
    assert a_voucher_id in {row["id"] for row in principal_view.json()["items"]}


async def test_direct_fee_dml_cannot_cross_tenants(
    make_tenant: Callable[..., Any],
    mailbox: list[EmailMessage],
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Spec §14.4: the policies hold even when the service layer is bypassed entirely.

    This is what proves `setup_tenant_table()` ran on these tables. An application
    filter would pass every other test in this file and fail here.
    """
    org_a: Tenant = await make_tenant(name="Guard A", email="ga@test.example", school_code="GA")
    org_b: Tenant = await make_tenant(name="Guard B", email="gb@test.example", school_code="GB")

    fx_b = await build_fees(org_b, mailbox, email="gb-fees@test.example")

    # Every fee table, not just one: a policy missing from any single table is the
    # failure this test exists to catch, and checking only `fee_heads` would miss it.
    inserts = {
        "fee_heads": (
            "INSERT INTO fee_heads "
            "(organization_id, school_id, code, name, recurrence, "
            " is_refundable, is_active, sort_order) "
            "VALUES (:org, :school, 'HIJACK', 'Hijack', 'monthly', false, true, 0)"
        ),
        "fee_structures": (
            "INSERT INTO fee_structures "
            "(organization_id, school_id, class_id, academic_year, name, status) "
            "VALUES (:org, :school, :class_id, '2026-2027', 'Hijack', 'draft')"
        ),
        "fee_vouchers": (
            "INSERT INTO fee_vouchers "
            "(organization_id, school_id, student_id, voucher_number, academic_year, "
            " period_label, issue_date, due_date, status, currency, "
            " subtotal, discount_total, total, paid_total) "
            "VALUES (:org, :school, :student_id, 'HIJACK-1', '2026-2027', "
            " '2026-08', CURRENT_DATE, CURRENT_DATE, 'issued', 'PKR', 0, 0, 0, 0)"
        ),
    }

    factory = get_session_factory()
    async with factory() as app_session:
        for table, statement in inserts.items():
            # WITH CHECK has no platform-admin escape hatch and no exception for a
            # connection bound to a different tenant: A cannot stamp a row into B.
            await bind_tenant(app_session, UUID(org_a.organization_id))
            with pytest.raises(DBAPIError, match="row-level security") as caught:
                await app_session.execute(
                    text(statement),
                    {
                        "org": org_b.organization_id,
                        "school": org_b.school_id,
                        "class_id": fx_b.class_id,
                        "student_id": fx_b.student_ids[0],
                    },
                )
            assert table in statement, "the insert must target the table it names"
            assert caught.value is not None
            await app_session.rollback()

        # And the USING half hides B's existing rows from A entirely -- a cross-tenant
        # SELECT returns zero rows rather than erroring, which is what makes a
        # foreign id indistinguishable from a nonexistent one at the service layer.
        await bind_tenant(app_session, UUID(org_a.organization_id))
        for table in ("fee_heads", "fee_structures", "fee_vouchers", "fee_payments"):
            visible = (
                await app_session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE organization_id = :org"),
                    {"org": org_b.organization_id},
                )
            ).scalar_one()
            assert visible == 0, f"{table} leaked rows across the tenant boundary"

    async with admin_sessionmaker() as admin:
        surviving = (
            await admin.execute(
                text("SELECT count(*) FROM fee_heads WHERE code LIKE 'HIJACK%'"),
            )
        ).scalar_one()
        assert surviving == 0

    # B's own heads are untouched.
    heads = await fx_b.get(f"{API}/fees/heads")
    assert {row["code"] for row in heads.json()["items"]} == {"TUITION", "TRANSPORT"}


# ---------------------------------------------------------------------------
# 5-6. Generation and the immutability of an issued challan
# ---------------------------------------------------------------------------


async def test_generation_bills_each_student_and_snapshots_amounts(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Spec §14.5: one voucher per eligible student, with the amounts and head names
    copied onto it."""
    fx = await build_fees(tenant, mailbox, students=3)

    run = await generate(fx)
    assert run.status_code == 201, run.text
    body = run.json()
    assert body["created"] == 3
    assert body["skipped"] == []
    assert body["truncated"] is False
    assert len(body["voucher_ids"]) == 3

    detail = await fx.get(f"{API}/fees/vouchers/{body['voucher_ids'][0]}")
    assert detail.status_code == 200
    voucher = detail.json()

    assert voucher["status"] == "issued"
    assert voucher["academic_year"] == YEAR
    assert voucher["period_label"] == PERIOD
    assert voucher["currency"] == "PKR"
    assert voucher["subtotal"] == "6500.00"
    assert voucher["total"] == "6500.00"
    assert voucher["paid_total"] == "0.00"
    assert voucher["outstanding"] == "6500.00"
    assert voucher["voucher_number"].startswith(f"FV-{date.today().year}-")

    assert {(i["line_name"], i["amount"]) for i in voucher["items"]} == {
        ("Tuition", "5000.00"),
        ("Transport", "1500.00"),
    }

    # Every voucher number in the run is distinct -- the sequence advanced per row.
    numbers = set()
    for voucher_id in body["voucher_ids"]:
        one = await fx.get(f"{API}/fees/vouchers/{voucher_id}")
        numbers.add(one.json()["voucher_number"])
    assert len(numbers) == 3


async def test_generation_skips_already_billed_students_without_failing_the_run(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Spec §14.5/§14.11: a partial re-run reports skips and still bills the rest.

    Rolling the whole batch back because one student was billed yesterday is the
    failure mode that makes an operator stop trusting the button.
    """
    fx = await build_fees(tenant, mailbox, students=2)

    first = await generate(fx, student_ids=[fx.student_ids[0]])
    assert first.status_code == 201, first.text
    assert first.json()["created"] == 1

    # Re-run over the whole class: one skip, one new voucher.
    second = await generate(fx)
    assert second.status_code == 201, second.text
    body = second.json()
    assert body["created"] == 1
    assert len(body["skipped"]) == 1
    assert body["skipped"][0]["student_id"] == fx.student_ids[0]
    assert "already has a challan" in body["skipped"][0]["reason"].lower()

    listing = await fx.get(f"{API}/fees/vouchers", params={"period_label": PERIOD})
    assert listing.json()["meta"]["total"] == 2


async def test_voiding_frees_the_period_for_a_corrected_reissue(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Spec §14.11: the duplicate guard is PARTIAL on `status <> 'void'`, so a
    cancelled challan can be reissued for the same period."""
    fx = await build_fees(tenant, mailbox, students=1)

    first = await generate(fx)
    voucher_id = first.json()["voucher_ids"][0]

    blocked = await generate(fx)
    assert blocked.status_code == 201
    assert blocked.json()["created"] == 0, "the same period was billed twice"

    voided = await fx.post(
        f"{API}/fees/vouchers/{voucher_id}/void", json={"reason": "Wrong due date"}
    )
    assert voided.status_code == 200, voided.text
    assert voided.json()["status"] == "void"

    reissued = await generate(fx)
    assert reissued.status_code == 201, reissued.text
    assert reissued.json()["created"] == 1, "voiding did not free the period"


async def test_renaming_a_head_or_repricing_a_structure_never_rewrites_a_challan(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Spec §14.6 -- the module's headline invariant.

    A parent holds a piece of paper. Nothing an administrator does next term may
    change what that paper says, and nothing may restate what August billed.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    run = await generate(fx)
    voucher_id = run.json()["voucher_ids"][0]

    before = (await fx.get(f"{API}/fees/vouchers/{voucher_id}")).json()

    renamed = await fx.patch(
        f"{API}/fees/heads/{fx.head_ids['TUITION']}", json={"name": "Tuition & Lab"}
    )
    assert renamed.status_code == 200, renamed.text

    repriced = await fx.put(
        f"{API}/fees/structures/{fx.structure_id}/items",
        json={"head_id": fx.head_ids["TUITION"], "amount": "9999.00"},
    )
    assert repriced.status_code == 200, repriced.text

    removed = await fx.delete(
        f"{API}/fees/structures/{fx.structure_id}/items/{fx.head_ids['TRANSPORT']}"
    )
    assert removed.status_code == 200, removed.text

    after = (await fx.get(f"{API}/fees/vouchers/{voucher_id}")).json()
    assert after["total"] == before["total"] == "6500.00"
    assert after["subtotal"] == before["subtotal"]
    assert {(i["line_name"], i["amount"]) for i in after["items"]} == {
        ("Tuition", "5000.00"),
        ("Transport", "1500.00"),
    }, "an issued challan was rewritten by a later edit"

    # The NEXT run does pick up the new prices -- the edit was not simply ignored.
    nxt = await generate(fx, period="2026-09")
    assert nxt.status_code == 201, nxt.text
    fresh = (await fx.get(f"{API}/fees/vouchers/{nxt.json()['voucher_ids'][0]}")).json()
    assert fresh["total"] == "9999.00"
    assert {i["line_name"] for i in fresh["items"]} == {"Tuition & Lab"}


# ---------------------------------------------------------------------------
# 7-10. Payments
# ---------------------------------------------------------------------------


async def test_payment_lifecycle_partial_then_full(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Spec §14.7: partial moves to PARTLY_PAID, the balancing payment to PAID."""
    fx = await build_fees(tenant, mailbox, students=1)
    voucher_id = (await generate(fx)).json()["voucher_ids"][0]

    partial = await fx.post(
        f"{API}/fees/vouchers/{voucher_id}/payments",
        json={"amount": "2000.00", "method": "cash", "reference": "counter-1"},
    )
    assert partial.status_code == 201, partial.text
    assert partial.json()["receipt_number"].startswith(f"RC-{date.today().year}-")
    assert partial.json()["status"] == "recorded"

    mid = (await fx.get(f"{API}/fees/vouchers/{voucher_id}")).json()
    assert mid["status"] == "partly_paid"
    assert mid["paid_total"] == "2000.00"
    assert mid["outstanding"] == "4500.00"

    rest = await fx.post(
        f"{API}/fees/vouchers/{voucher_id}/payments",
        json={"amount": "4500.00", "method": "bank_transfer", "reference": "TXN-99"},
    )
    assert rest.status_code == 201, rest.text

    final = (await fx.get(f"{API}/fees/vouchers/{voucher_id}")).json()
    assert final["status"] == "paid"
    assert final["paid_total"] == "6500.00"
    assert final["outstanding"] == "0.00"
    assert final["paid_at"] is not None
    assert len(final["payments"]) == 2


async def test_overpayment_is_rejected(tenant: Tenant, mailbox: list[EmailMessage]) -> None:
    """Spec §14.7: credit with no ledger to hold it is a number that goes missing."""
    fx = await build_fees(tenant, mailbox, students=1)
    voucher_id = (await generate(fx)).json()["voucher_ids"][0]

    too_much = await fx.post(
        f"{API}/fees/vouchers/{voucher_id}/payments",
        json={"amount": "6500.01", "method": "cash"},
    )
    assert too_much.status_code == 422, too_much.text
    assert too_much.json()["code"] == "PAYMENT_EXCEEDS_OUTSTANDING"

    unchanged = (await fx.get(f"{API}/fees/vouchers/{voucher_id}")).json()
    assert unchanged["paid_total"] == "0.00"
    assert unchanged["status"] == "issued"

    # Exactly the outstanding balance is fine.
    exact = await fx.post(
        f"{API}/fees/vouchers/{voucher_id}/payments",
        json={"amount": "6500.00", "method": "cash"},
    )
    assert exact.status_code == 201, exact.text

    # ...and a second payment on a settled voucher has nothing left to pay.
    again = await fx.post(
        f"{API}/fees/vouchers/{voucher_id}/payments", json={"amount": "1.00", "method": "cash"}
    )
    assert again.status_code == 422
    assert again.json()["code"] == "PAYMENT_EXCEEDS_OUTSTANDING"


async def test_payments_are_rejected_against_draft_and_void_vouchers(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Spec §14.8. A draft has not reached the parent, so money against it is a
    mis-selection in the UI rather than an early payment."""
    fx = await build_fees(tenant, mailbox, students=2)

    drafted = await generate(fx, issue=False)
    assert drafted.status_code == 201, drafted.text
    draft_id, other_id = drafted.json()["voucher_ids"][:2]

    on_draft = await fx.post(
        f"{API}/fees/vouchers/{draft_id}/payments", json={"amount": "10.00", "method": "cash"}
    )
    assert on_draft.status_code == 409, on_draft.text

    issued = await fx.post(f"{API}/fees/vouchers/{other_id}/issue")
    assert issued.status_code == 200, issued.text
    voided = await fx.post(f"{API}/fees/vouchers/{other_id}/void", json={"reason": "Duplicate"})
    assert voided.status_code == 200, voided.text

    on_void = await fx.post(
        f"{API}/fees/vouchers/{other_id}/payments", json={"amount": "10.00", "method": "cash"}
    )
    assert on_void.status_code == 409, on_void.text


async def test_void_is_refused_while_money_is_held_and_reversal_restores_the_balance(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Spec §14.9/§14.10.

    Voiding a bill money was received against would leave the receipt pointing at
    nothing, which is exactly how a cash shortfall gets papered over.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    voucher_id = (await generate(fx)).json()["voucher_ids"][0]

    payment = await fx.post(
        f"{API}/fees/vouchers/{voucher_id}/payments",
        json={"amount": "3000.00", "method": "cheque", "reference": "CHQ-1"},
    )
    assert payment.status_code == 201, payment.text
    payment_id = payment.json()["id"]

    refused = await fx.post(
        f"{API}/fees/vouchers/{voucher_id}/void", json={"reason": "Parent withdrew"}
    )
    assert refused.status_code == 409, refused.text
    assert "reverse" in refused.json()["detail"].lower()

    reversed_payment = await fx.post(
        f"{API}/fees/payments/{payment_id}/reverse", json={"reason": "Cheque bounced"}
    )
    assert reversed_payment.status_code == 200, reversed_payment.text
    assert reversed_payment.json()["status"] == "reversed"
    assert reversed_payment.json()["reversal_reason"] == "Cheque bounced"

    restored = (await fx.get(f"{API}/fees/vouchers/{voucher_id}")).json()
    assert restored["paid_total"] == "0.00"
    assert restored["outstanding"] == "6500.00"
    assert restored["status"] == "issued"
    # The reversed receipt is retained -- it is part of the trail, not an error.
    assert len(restored["payments"]) == 1

    # Now the void succeeds.
    now_void = await fx.post(
        f"{API}/fees/vouchers/{voucher_id}/void", json={"reason": "Parent withdrew"}
    )
    assert now_void.status_code == 200, now_void.text
    assert now_void.json()["status"] == "void"
    assert now_void.json()["void_reason"] == "Parent withdrew"

    # A reversal cannot be applied twice.
    again = await fx.post(f"{API}/fees/payments/{payment_id}/reverse", json={"reason": "again"})
    assert again.status_code == 409


# ---------------------------------------------------------------------------
# 12. Separation of duties
# ---------------------------------------------------------------------------


async def test_collect_cannot_void_and_void_cannot_collect(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Spec §14.12 -- why `fee:collect` and `fee:void` are two codes.

    The person who records money coming in must not be the person who can make a
    record of money disappear.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    voucher_id = (await generate(fx)).json()["voucher_ids"][0]

    collector = await make_scoped_actor(
        tenant,
        mailbox,
        "collector@test.example",
        ["fee:read", "fee:collect"],
        code="fee_collector",
    )
    voider = await make_scoped_actor(
        tenant, mailbox, "voider@test.example", ["fee:read", "fee:void"], code="fee_voider"
    )
    collector_headers = {"Authorization": f"Bearer {collector}"}
    voider_headers = {"Authorization": f"Bearer {voider}"}

    # The collector may take money...
    took = await tenant.client.post(
        f"{API}/fees/vouchers/{voucher_id}/payments",
        json={"amount": "1000.00", "method": "cash"},
        headers=collector_headers,
    )
    assert took.status_code == 201, took.text
    payment_id = took.json()["id"]

    # ...but may not undo it, in either form.
    for response in (
        await tenant.client.post(
            f"{API}/fees/payments/{payment_id}/reverse",
            json={"reason": "trying"},
            headers=collector_headers,
        ),
        await tenant.client.post(
            f"{API}/fees/vouchers/{voucher_id}/void",
            json={"reason": "trying"},
            headers=collector_headers,
        ),
    ):
        assert response.status_code == 403, response.text
        assert response.json()["code"] == "FORBIDDEN"

    # And the voider may not take money.
    blocked = await tenant.client.post(
        f"{API}/fees/vouchers/{voucher_id}/payments",
        json={"amount": "10.00", "method": "cash"},
        headers=voider_headers,
    )
    assert blocked.status_code == 403, blocked.text

    # The voider can do their own job.
    allowed = await tenant.client.post(
        f"{API}/fees/payments/{payment_id}/reverse",
        json={"reason": "Mis-keyed"},
        headers=voider_headers,
    )
    assert allowed.status_code == 200, allowed.text


async def test_seeded_accountant_can_collect_but_not_void(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """The default `accountant` role holds `fee:collect`, not `fee:void` (fees.md §4).

    Asserted on the SEEDED role rather than a hand-built one, because the point is
    the default a customer gets without configuring anything.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    voucher_id = (await generate(fx)).json()["voucher_ids"][0]

    roles = await tenant.get(f"{API}/schools/{tenant.school_id}/roles")
    assert roles.status_code == 200, roles.text
    accountant = next(r for r in roles.json() if r["code"] == "accountant")

    invited = await tenant.post(
        f"{API}/schools/{tenant.school_id}/invitations",
        json={
            "email": "bursar@test.example",
            "full_name": "Bursar",
            "role_id": accountant["id"],
        },
    )
    assert invited.status_code == 201, invited.text

    tenant.client.cookies.clear()
    accepted = await tenant.client.post(
        f"{API}/invitations/accept",
        json={"token": latest_token(mailbox), "full_name": "Bursar", "password": STRONG_PASSWORD},
    )
    assert accepted.status_code == 200, accepted.text
    tenant.client.cookies.clear()

    login = await tenant.client.post(
        f"{API}/auth/login",
        json={"email": "bursar@test.example", "password": STRONG_PASSWORD},
        headers={"X-Token-Transport": "body"},
    )
    assert login.status_code == 200, login.text
    tenant.client.cookies.clear()
    headers = {"Authorization": f"Bearer {login.headers['X-Access-Token']}"}

    took = await tenant.client.post(
        f"{API}/fees/vouchers/{voucher_id}/payments",
        json={"amount": "500.00", "method": "cash"},
        headers=headers,
    )
    assert took.status_code == 201, took.text

    refused = await tenant.client.post(
        f"{API}/fees/vouchers/{voucher_id}/void", json={"reason": "nope"}, headers=headers
    )
    assert refused.status_code == 403, refused.text
    assert "fee:void" in refused.json()["meta"]["missing"]


# ---------------------------------------------------------------------------
# 13-14. Audit trail and the challan PDF
# ---------------------------------------------------------------------------


async def test_every_fee_mutation_writes_an_audit_row(
    tenant: Tenant,
    mailbox: list[EmailMessage],
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Spec §14.13. The audit row shares the mutation's transaction, so "it happened"
    and "we recorded that it happened" are atomic."""
    fx = await build_fees(tenant, mailbox, students=1)
    run = await generate(fx)
    voucher_id = run.json()["voucher_ids"][0]

    payment = await fx.post(
        f"{API}/fees/vouchers/{voucher_id}/payments", json={"amount": "100.00", "method": "cash"}
    )
    assert payment.status_code == 201, payment.text
    reversed_response = await fx.post(
        f"{API}/fees/payments/{payment.json()['id']}/reverse", json={"reason": "Mis-keyed"}
    )
    assert reversed_response.status_code == 200, reversed_response.text
    voided = await fx.post(f"{API}/fees/vouchers/{voucher_id}/void", json={"reason": "Withdrawn"})
    assert voided.status_code == 200, voided.text
    archived = await fx.post(f"{API}/fees/structures/{fx.structure_id}/archive")
    assert archived.status_code == 200, archived.text

    async with admin_sessionmaker() as admin:
        actions = set(
            (
                await admin.execute(
                    text(
                        "SELECT action FROM audit_logs "
                        "WHERE organization_id = :org AND action LIKE 'fee%'"
                    ),
                    {"org": tenant.organization_id},
                )
            )
            .scalars()
            .all()
        )

    assert {
        "fee_head.created",
        "fee_structure.created",
        "fee_structure.activated",
        "fee_structure.archived",
        "fee_voucher.generated",
        "fee_payment.recorded",
        "fee_payment.reversed",
        "fee_voucher.voided",
    } <= actions, f"missing audit actions: {actions}"

    # The void reason reached the trail -- that is why the field is mandatory.
    async with admin_sessionmaker() as admin:
        after = (
            await admin.execute(
                text(
                    "SELECT after FROM audit_logs "
                    "WHERE organization_id = :org AND action = 'fee_voucher.voided'"
                ),
                {"org": tenant.organization_id},
            )
        ).scalar_one()
    assert after["reason"] == "Withdrawn"


async def test_challan_pdf_renders_three_copies(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Spec §14.14: one A4 page carrying Bank / School / Student copies.

    A single-copy challan is refused at the bank counter, so the three copies are a
    functional requirement rather than a layout preference.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    voucher_id = (await generate(fx)).json()["voucher_ids"][0]

    response = await fx.get(f"{API}/fees/vouchers/{voucher_id}/pdf")
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    assert "challan-FV-" in response.headers["content-disposition"]
    # A challan names a minor and what their family owes.
    assert response.headers["cache-control"] == "private, no-store"

    payload = response.content
    assert payload.startswith(b"%PDF-"), "not a PDF"
    assert payload.rstrip().endswith(b"%%EOF")
    assert len(payload) > 1500

    # One page, three copies. `/Count 1` is the page tree's page count.
    assert b"/Count 1" in payload


# ---------------------------------------------------------------------------
# Structure lifecycle and the collection summary
# ---------------------------------------------------------------------------


async def test_only_an_active_structure_can_bill(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """A DRAFT structure is half-built; an ARCHIVED one is history. Neither bills."""
    fx = await build_fees(tenant, mailbox, students=1)

    empty = await fx.post(
        f"{API}/fees/structures",
        json={"class_id": fx.class_id, "academic_year": "2027-2028", "name": "Empty"},
    )
    assert empty.status_code == 201, empty.text
    empty_id = empty.json()["id"]

    # An empty ACTIVE structure would issue zero-value challans to a whole class,
    # which reads as "fees are paid" on every dashboard downstream.
    refused = await fx.post(f"{API}/fees/structures/{empty_id}/activate")
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "FEE_STRUCTURE_EMPTY"

    draft_run = await fx.post(
        f"{API}/fees/vouchers/generate",
        json={
            "structure_id": empty_id,
            "period_label": "2027-08",
            "issue_date": date.today().isoformat(),
            "due_date": (date.today() + timedelta(days=7)).isoformat(),
        },
    )
    assert draft_run.status_code == 409, draft_run.text

    archived = await fx.post(f"{API}/fees/structures/{fx.structure_id}/archive")
    assert archived.status_code == 200, archived.text

    after_archive = await generate(fx, period="2026-10")
    assert after_archive.status_code == 409, after_archive.text

    # An archived structure is frozen against edits too.
    frozen = await fx.put(
        f"{API}/fees/structures/{fx.structure_id}/items",
        json={"head_id": fx.head_ids["TUITION"], "amount": "1.00"},
    )
    assert frozen.status_code == 409, frozen.text


async def test_a_head_in_use_cannot_be_deleted(tenant: Tenant, mailbox: list[EmailMessage]) -> None:
    """Cascading would silently change what a class is billed. Deactivate instead."""
    fx = await build_fees(tenant, mailbox, students=1)

    refused = await fx.delete(f"{API}/fees/heads/{fx.head_ids['TUITION']}")
    assert refused.status_code == 409, refused.text
    assert "deactivate" in refused.json()["detail"].lower()

    deactivated = await fx.patch(
        f"{API}/fees/heads/{fx.head_ids['TUITION']}", json={"is_active": False}
    )
    assert deactivated.status_code == 200, deactivated.text

    # Deactivated heads leave the picker but the structure still prices them.
    active = await fx.get(f"{API}/fees/heads", params={"active_only": True})
    assert fx.head_ids["TUITION"] not in {row["id"] for row in active.json()["items"]}

    structure = await fx.get(f"{API}/fees/structures/{fx.structure_id}")
    assert fx.head_ids["TUITION"] in {i["head_id"] for i in structure.json()["items"]}

    # An unused head deletes cleanly.
    spare = await fx.post(f"{API}/fees/heads", json={"code": "LIBRARY", "name": "Library"})
    assert spare.status_code == 201, spare.text
    removed = await fx.delete(f"{API}/fees/heads/{spare.json()['id']}")
    assert removed.status_code == 204, removed.text


async def test_duplicate_head_code_and_duplicate_structure_are_refused(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Uniqueness is per school, and codes are case-folded so `tuition` collides."""
    fx = await build_fees(tenant, mailbox, students=1)

    clash = await fx.post(f"{API}/fees/heads", json={"code": "tuition", "name": "Tuition Again"})
    assert clash.status_code == 409, clash.text

    duplicate = await fx.post(
        f"{API}/fees/structures",
        json={"class_id": fx.class_id, "academic_year": YEAR, "name": "Second try"},
    )
    assert duplicate.status_code == 409, duplicate.text


async def test_collection_summary_excludes_void_and_draft(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """A voided bill is not owed and a draft has not been sent, so neither counts as
    revenue. `outstanding` is `billed - collected`, never a third aggregate."""
    fx = await build_fees(tenant, mailbox, students=3)
    run = await generate(fx)
    first, second, third = run.json()["voucher_ids"]

    paid = await fx.post(
        f"{API}/fees/vouchers/{first}/payments", json={"amount": "6500.00", "method": "cash"}
    )
    assert paid.status_code == 201, paid.text
    partial = await fx.post(
        f"{API}/fees/vouchers/{second}/payments", json={"amount": "1500.00", "method": "cash"}
    )
    assert partial.status_code == 201, partial.text
    voided = await fx.post(f"{API}/fees/vouchers/{third}/void", json={"reason": "Left school"})
    assert voided.status_code == 200, voided.text

    summary = await fx.get(
        f"{API}/fees/summary", params={"academic_year": YEAR, "period_label": PERIOD}
    )
    assert summary.status_code == 200, summary.text
    body = summary.json()

    assert body["billed"] == "13000.00", "the voided voucher was counted as billed"
    assert body["collected"] == "8000.00"
    assert body["outstanding"] == "5000.00"
    assert body["voucher_count"] == 3
    assert {row["status"] for row in body["by_status"]} == {"paid", "partly_paid", "void"}


async def test_overdue_is_derived_from_the_due_date(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """A voucher past its due date with money owed reads as OVERDUE without a job
    having swept the table -- so the figure is right the morning after a due date."""
    fx = await build_fees(tenant, mailbox, students=1)
    today = date.today()

    run = await fx.post(
        f"{API}/fees/vouchers/generate",
        json={
            "structure_id": fx.structure_id,
            "period_label": "2026-07",
            "issue_date": (today - timedelta(days=40)).isoformat(),
            "due_date": (today - timedelta(days=10)).isoformat(),
            "issue_immediately": True,
        },
    )
    assert run.status_code == 201, run.text
    voucher_id = run.json()["voucher_ids"][0]

    detail = await fx.get(f"{API}/fees/vouchers/{voucher_id}")
    assert detail.json()["status"] == "overdue"

    summary = await fx.get(
        f"{API}/fees/summary", params={"academic_year": YEAR, "period_label": "2026-07"}
    )
    assert summary.json()["overdue"] == "6500.00"

    # Paying it in full clears the overdue state rather than leaving it stuck.
    settled = await fx.post(
        f"{API}/fees/vouchers/{voucher_id}/payments",
        json={"amount": "6500.00", "method": "cash"},
    )
    assert settled.status_code == 201, settled.text
    assert (await fx.get(f"{API}/fees/vouchers/{voucher_id}")).json()["status"] == "paid"


async def test_generation_rejects_a_due_date_before_the_issue_date(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Caught in the service so the message names the problem, and by a CHECK
    constraint underneath so no other path can write the row."""
    fx = await build_fees(tenant, mailbox, students=1)
    today = date.today()

    response = await fx.post(
        f"{API}/fees/vouchers/generate",
        json={
            "structure_id": fx.structure_id,
            "period_label": PERIOD,
            "issue_date": today.isoformat(),
            "due_date": (today - timedelta(days=1)).isoformat(),
        },
    )
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "DUE_BEFORE_ISSUE"


async def test_academic_year_must_span_consecutive_years(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """`2026-2030` is a typo every time, and a structure filed under a year that does
    not exist is one nobody can find again."""
    fx = await build_fees(tenant, mailbox, students=1)

    for bad in ("2026-2030", "20262027", "2026/2027"):
        response = await fx.post(
            f"{API}/fees/structures",
            json={"class_id": fx.class_id, "academic_year": bad, "name": "Bad year"},
        )
        assert response.status_code == 422, f"{bad} was accepted: {response.text}"


# ---------------------------------------------------------------------------
# Stationery -- what the school SELLS, priced by quantity
# ---------------------------------------------------------------------------


async def add_stationery(
    fx: FeeFixture,
    *,
    code: str = "COPY-100",
    name: str = "Copy (Register, 100 pages)",
    unit_price: str = "60.00",
    unit: str = "piece",
    category: str = "notebook",
) -> str:
    """Put one article in the catalog. Returns its id."""
    created = await fx.post(
        f"{API}/fees/stationery",
        json={
            "code": code,
            "name": name,
            "unit_price": unit_price,
            "unit": unit,
            "category": category,
        },
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def test_a_stationery_line_bills_quantity_times_unit_price(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """The whole reason stationery is not a fee head: three copies at 60 is 180.

    Also pins the arithmetic to ONE place -- the structure line, the voucher line and
    the voucher total must all agree, because they are three caches of the same fact.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    copy_id = await add_stationery(fx)

    priced = await fx.put(
        f"{API}/fees/structures/{fx.structure_id}/stationery",
        json={"stationery_item_id": copy_id, "quantity": "3"},
    )
    assert priced.status_code == 200, priced.text
    body = priced.json()

    line = next(i for i in body["items"] if i["line_type"] == "stationery")
    assert line["quantity"] == "3.00"
    assert line["unit_price"] == "60.00"
    assert line["amount"] == "180.00"
    assert line["unit"] == "piece"
    assert line["head_id"] is None

    # Fees and stationery are reported apart as well as together: "what does this
    # class pay monthly" and "what did we sell them" are different questions.
    assert body["fee_total"] == "6500.00"
    assert body["stationery_total"] == "180.00"
    assert body["total"] == "6680.00"

    voucher_id = (await generate(fx)).json()["voucher_ids"][0]
    voucher = (await fx.get(f"{API}/fees/vouchers/{voucher_id}")).json()
    assert voucher["total"] == "6680.00"

    charged = next(i for i in voucher["items"] if i["line_type"] == "stationery")
    assert (charged["line_name"], charged["quantity"], charged["amount"]) == (
        "Copy (Register, 100 pages)",
        "3.00",
        "180.00",
    )
    # The unit is snapshotted too: switching the article to dozens later must not
    # turn twelve pencils into twelve dozen on a challan already issued.
    assert charged["unit_label"] == "piece"


async def test_generation_can_leave_the_structures_stationery_off(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """`include_stationery=False` bills the fees alone.

    Without it, a structure carrying the annual book set would re-bill those books on
    every monthly run -- twelve times the books, at the parent's expense.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    book_id = await add_stationery(fx, code="BOOK-SET", name="Book set", unit_price="4000.00")

    priced = await fx.put(
        f"{API}/fees/structures/{fx.structure_id}/stationery",
        json={"stationery_item_id": book_id, "quantity": "1"},
    )
    assert priced.status_code == 200, priced.text

    august = (await generate(fx, period="2026-08")).json()["voucher_ids"][0]
    assert (await fx.get(f"{API}/fees/vouchers/{august}")).json()["total"] == "10500.00"

    september = (await generate(fx, period="2026-09", include_stationery=False)).json()[
        "voucher_ids"
    ][0]
    detail = (await fx.get(f"{API}/fees/vouchers/{september}")).json()
    assert detail["total"] == "6500.00"
    assert [i for i in detail["items"] if i["line_type"] == "stationery"] == []


async def test_a_charge_can_be_added_to_a_draft_and_never_to_an_issued_challan(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """RULE 1, exercised on the one path that could break it.

    A parent holding a challan for 6,500 must not discover at the counter that a
    clerk made it 6,680 this morning. Drafts are still being assembled and accept
    charges; an issued bill is a document and refuses them.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    copy_id = await add_stationery(fx)
    voucher_id = (await generate(fx, issue=False)).json()["voucher_ids"][0]

    charged = await fx.put(
        f"{API}/fees/vouchers/{voucher_id}/stationery",
        json={"stationery_item_id": copy_id, "quantity": "3"},
    )
    assert charged.status_code == 200, charged.text
    assert charged.json()["total"] == "6680.00"

    # Idempotent by article: the same item again SETS the quantity rather than
    # adding a second "Copy" line beneath the first.
    again = await fx.put(
        f"{API}/fees/vouchers/{voucher_id}/stationery",
        json={"stationery_item_id": copy_id, "quantity": "5"},
    )
    assert again.status_code == 200, again.text
    body = again.json()
    assert len([i for i in body["items"] if i["line_type"] == "stationery"]) == 1
    assert body["total"] == "6800.00"

    # Removing it puts the total back exactly, which is the check that the voucher's
    # cached subtotal is recomputed from the lines rather than adjusted.
    removed = await fx.delete(f"{API}/fees/vouchers/{voucher_id}/stationery/{copy_id}")
    assert removed.status_code == 200, removed.text
    assert removed.json()["total"] == "6500.00"

    # Re-add, then issue. From here the bill is final.
    await fx.put(
        f"{API}/fees/vouchers/{voucher_id}/stationery",
        json={"stationery_item_id": copy_id, "quantity": "3"},
    )
    issued = await fx.post(f"{API}/fees/vouchers/{voucher_id}/issue")
    assert issued.status_code == 200, issued.text

    refused = await fx.put(
        f"{API}/fees/vouchers/{voucher_id}/stationery",
        json={"stationery_item_id": copy_id, "quantity": "9"},
    )
    assert refused.status_code == 409, refused.text

    still_refused = await fx.delete(f"{API}/fees/vouchers/{voucher_id}/stationery/{copy_id}")
    assert still_refused.status_code == 409, still_refused.text

    # And the bill is untouched by either attempt.
    final = (await fx.get(f"{API}/fees/vouchers/{voucher_id}")).json()
    assert final["total"] == "6680.00"


async def test_repricing_the_catalog_never_restates_what_was_charged(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """The snapshot rule, extended to the two numbers that now justify an amount.

    Repricing a copy from 60 to 100 must change the NEXT challan and no past one --
    otherwise a parent's bill changes after they were handed it, and the school has
    no defence when they say so.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    copy_id = await add_stationery(fx)
    await fx.put(
        f"{API}/fees/structures/{fx.structure_id}/stationery",
        json={"stationery_item_id": copy_id, "quantity": "3"},
    )
    voucher_id = (await generate(fx, period="2026-08")).json()["voucher_ids"][0]

    repriced = await fx.patch(
        f"{API}/fees/stationery/{copy_id}",
        json={"unit_price": "100.00", "name": "Copy (Register, 120 pages)"},
    )
    assert repriced.status_code == 200, repriced.text

    issued = (await fx.get(f"{API}/fees/vouchers/{voucher_id}")).json()
    frozen = next(i for i in issued["items"] if i["line_type"] == "stationery")
    assert frozen["unit_price"] == "60.00"
    assert frozen["amount"] == "180.00"
    assert frozen["line_name"] == "Copy (Register, 100 pages)"
    assert issued["total"] == "6680.00"

    # The STRUCTURE froze the price too -- it is a price list, not a live lookup, so
    # a January reprice cannot silently change what it says the class is charged.
    structure = (await fx.get(f"{API}/fees/structures/{fx.structure_id}")).json()
    assert (
        next(i for i in structure["items"] if i["line_type"] == "stationery")["unit_price"]
        == "60.00"
    )

    # Re-adding the line is the explicit, audited act that picks the new price up.
    await fx.put(
        f"{API}/fees/structures/{fx.structure_id}/stationery",
        json={"stationery_item_id": copy_id, "quantity": "3"},
    )
    september = (await generate(fx, period="2026-09")).json()["voucher_ids"][0]
    fresh = (await fx.get(f"{API}/fees/vouchers/{september}")).json()
    assert next(i for i in fresh["items"] if i["line_type"] == "stationery")["amount"] == "300.00"
    assert fresh["total"] == "6800.00"


async def test_a_charged_stationery_item_cannot_be_deleted(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Stricter than the fee-head rule, because an article can reach a challan two ways.

    A head only ever arrives through a structure. An article can also be charged
    straight onto a draft, so guarding structures alone would leave a challan naming
    a record that no longer exists.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    copy_id = await add_stationery(fx)

    # Unreferenced: deletable.
    spare_id = await add_stationery(fx, code="PENCIL", name="Pencil", unit_price="20.00")
    assert (await fx.delete(f"{API}/fees/stationery/{spare_id}")).status_code == 204

    voucher_id = (await generate(fx, issue=False)).json()["voucher_ids"][0]
    await fx.put(
        f"{API}/fees/vouchers/{voucher_id}/stationery",
        json={"stationery_item_id": copy_id, "quantity": "2"},
    )

    refused = await fx.delete(f"{API}/fees/stationery/{copy_id}")
    assert refused.status_code == 409, refused.text
    assert "Deactivate it instead" in refused.text

    # Deactivation is the supported retirement path, and it keeps the challan working.
    assert (
        await fx.patch(f"{API}/fees/stationery/{copy_id}", json={"is_active": False})
    ).status_code == 200
    assert (await fx.get(f"{API}/fees/vouchers/{voucher_id}")).status_code == 200

    # An inactive article cannot be charged again -- retired means retired.
    stale = await fx.put(
        f"{API}/fees/vouchers/{voucher_id}/stationery",
        json={"stationery_item_id": copy_id, "quantity": "1"},
    )
    assert stale.status_code == 422, stale.text


async def test_stationery_appears_on_the_challan_with_its_working_shown(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """A parent handed "Copy — 180" cannot check it; "3 pieces @ 60.00" they can.

    The PDF is compressed, so this asserts on the extracted line rather than on the
    raw bytes -- what matters is what the renderer produced, not how it encoded it.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    copy_id = await add_stationery(fx)
    await fx.put(
        f"{API}/fees/structures/{fx.structure_id}/stationery",
        json={"stationery_item_id": copy_id, "quantity": "3"},
    )
    voucher_id = (await generate(fx)).json()["voucher_ids"][0]

    response = await fx.get(f"{API}/fees/vouchers/{voucher_id}/pdf")
    assert response.status_code == 200, response.text
    assert response.content.startswith(b"%PDF-")

    # The renderer's description logic, fed the API's own snapshot of the line. The
    # PDF's streams are compressed, so asserting on the bytes would test zlib; this
    # asserts on the text the renderer actually put in them.
    from app.modules.fees.challan_pdf import _description
    from app.modules.fees.models import FeeVoucherItem

    voucher = (await fx.get(f"{API}/fees/vouchers/{voucher_id}")).json()
    line = next(i for i in voucher["items"] if i["line_type"] == "stationery")
    assert line["unit_price"] == "60.00" and line["quantity"] == "3.00"

    rendered = FeeVoucherItem(
        line_type=FeeLineType.STATIONERY,
        line_name=line["line_name"],
        quantity=Decimal(line["quantity"]),
        unit_label=line["unit_label"],
        unit_price=Decimal(line["unit_price"]),
    )
    assert _description(rendered) == "Copy (Register, 100 pages) — 3 pieces @ 60.00"

    # And a fee line stays bare -- "Tuition", with no arithmetic to show.
    fee_line = next(i for i in voucher["items"] if i["line_type"] == "fee")
    assert (
        _description(FeeVoucherItem(line_type=FeeLineType.FEE, line_name=fee_line["line_name"]))
        == fee_line["line_name"]
    )


async def test_the_collection_summary_splits_out_what_was_sold(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """`stationery_billed` is a PART of `billed`, computed over the same rows.

    Computing it over a different row set is how a dashboard ends up showing a
    component larger than the whole it belongs to -- so the void case is the point of
    this test, not an afterthought.
    """
    fx = await build_fees(tenant, mailbox, students=2)
    copy_id = await add_stationery(fx)
    await fx.put(
        f"{API}/fees/structures/{fx.structure_id}/stationery",
        json={"stationery_item_id": copy_id, "quantity": "3"},
    )
    ids = (await generate(fx)).json()["voucher_ids"]

    summary = (
        await fx.get(f"{API}/fees/summary", params={"academic_year": YEAR, "period_label": PERIOD})
    ).json()
    assert summary["billed"] == "13360.00"
    assert summary["stationery_billed"] == "360.00"

    voided = await fx.post(f"{API}/fees/vouchers/{ids[0]}/void", json={"reason": "Left school"})
    assert voided.status_code == 200, voided.text

    after = (
        await fx.get(f"{API}/fees/summary", params={"academic_year": YEAR, "period_label": PERIOD})
    ).json()
    assert after["billed"] == "6680.00"
    assert after["stationery_billed"] == "180.00"


async def test_stationery_mutations_write_audit_rows(
    tenant: Tenant,
    mailbox: list[EmailMessage],
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Every price change and every charge is answerable to a name and a time.

    "Who put the copy up to 100 and when" is the question this catalog gets asked,
    and a repriced article with no trail is indistinguishable from a mistake.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    copy_id = await add_stationery(fx)
    await fx.patch(f"{API}/fees/stationery/{copy_id}", json={"unit_price": "100.00"})

    voucher_id = (await generate(fx, issue=False)).json()["voucher_ids"][0]
    await fx.put(
        f"{API}/fees/vouchers/{voucher_id}/stationery",
        json={"stationery_item_id": copy_id, "quantity": "2"},
    )
    await fx.delete(f"{API}/fees/vouchers/{voucher_id}/stationery/{copy_id}")

    async with admin_sessionmaker() as admin:
        actions = {
            row[0]
            for row in (
                await admin.execute(
                    text(
                        "SELECT action FROM audit_logs WHERE organization_id = :org "
                        "AND (action LIKE 'stationery_item.%' OR action LIKE 'fee_voucher.charge%')"
                    ),
                    {"org": tenant.organization_id},
                )
            ).all()
        }
        priced = (
            await admin.execute(
                text(
                    "SELECT before, after FROM audit_logs WHERE organization_id = :org "
                    "AND action = 'stationery_item.updated'"
                ),
                {"org": tenant.organization_id},
            )
        ).one()

    assert actions == {
        "stationery_item.created",
        "stationery_item.updated",
        "fee_voucher.charge_added",
        "fee_voucher.charge_removed",
    }
    # Both sides of the reprice, which is what makes the row answer the question.
    assert priced[0]["unit_price"] == "60.00"
    assert priced[1]["unit_price"] == "100.00"


async def test_stationery_catalog_needs_manage_and_charging_needs_issue(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """The permission split, verified rather than asserted in a docstring.

    Stationery adds no sixth code: the catalog is `fee:manage` (what may be charged)
    and charging is `fee:issue` (who is charged). An actor holding one must not be
    able to do the other's job.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    copy_id = await add_stationery(fx)
    voucher_id = (await generate(fx, issue=False)).json()["voucher_ids"][0]

    issuer = await make_scoped_actor(
        tenant,
        mailbox,
        "fee-issuer@test.example",
        ["fee:read", "fee:issue"],
        code="fee_issuer",
    )
    issuer_headers = {"Authorization": f"Bearer {issuer}"}

    # `fee:issue` charges a student, and cannot touch the catalog.
    charged = await tenant.client.put(
        f"{API}/fees/vouchers/{voucher_id}/stationery",
        headers=issuer_headers,
        json={"stationery_item_id": copy_id, "quantity": "2"},
    )
    assert charged.status_code == 200, charged.text

    blocked = await tenant.client.post(
        f"{API}/fees/stationery",
        headers=issuer_headers,
        json={"code": "PEN", "name": "Pen", "unit_price": "30.00"},
    )
    assert blocked.status_code == 403, blocked.text

    manager = await make_scoped_actor(
        tenant,
        mailbox,
        "fee-manager@test.example",
        ["fee:read", "fee:manage"],
        code="fee_manager",
    )
    manager_headers = {"Authorization": f"Bearer {manager}"}

    # `fee:manage` owns the catalog, and cannot charge a student.
    created = await tenant.client.post(
        f"{API}/fees/stationery",
        headers=manager_headers,
        json={"code": "PEN", "name": "Pen", "unit_price": "30.00"},
    )
    assert created.status_code == 201, created.text

    refused = await tenant.client.put(
        f"{API}/fees/vouchers/{voucher_id}/stationery",
        headers=manager_headers,
        json={"stationery_item_id": copy_id, "quantity": "4"},
    )
    assert refused.status_code == 403, refused.text


# ---------------------------------------------------------------------------
# Per-student fee assignments -- optional services on top of the class base
# ---------------------------------------------------------------------------


async def assign(
    fx: FeeFixture,
    student_id: str,
    head_id: str,
    *,
    mode: str,
    amount: str | None = None,
    note: str | None = None,
) -> Any:
    body: dict[str, Any] = {"head_id": head_id, "academic_year": YEAR, "mode": mode}
    if amount is not None:
        body["amount"] = amount
    if note is not None:
        body["note"] = note
    return await fx.put(f"{API}/fees/students/{student_id}/fee-assignments", json=body)


async def test_a_student_with_no_arrangements_is_billed_the_class_base(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """The common case, and the reason this is a delta table rather than a fee plan.

    A newly admitted student is billed correctly the moment they are placed in a
    section — nobody types six lines first, so nobody can forget to.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    profile = await fx.get(
        f"{API}/fees/students/{fx.student_ids[0]}/fee-profile", params={"academic_year": YEAR}
    )
    assert profile.status_code == 200, profile.text
    body = profile.json()

    assert body["assignments"] == []
    assert body["effective_total"] == "6500.00"
    assert {(line["head_name"], line["amount"], line["source"]) for line in body["effective"]} == {
        ("Tuition", "5000.00", "class"),
        ("Transport", "1500.00", "class"),
    }


async def test_adding_and_excluding_a_head_changes_only_that_student(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """One takes the bus and boards; one walks. Their classmates are untouched.

    This is the whole feature: the class structure stays the base, and each student's
    departures from it are theirs alone.
    """
    fx = await build_fees(tenant, mailbox, students=2)
    boarder, walker = fx.student_ids

    hostel = await fx.post(
        f"{API}/fees/heads", json={"code": "HOSTEL", "name": "Hostel", "recurrence": "monthly"}
    )
    assert hostel.status_code == 201, hostel.text
    hostel_id = hostel.json()["id"]

    added = await assign(
        fx, boarder, hostel_id, mode="added", amount="4000.00", note="Boards from Jan"
    )
    assert added.status_code == 200, added.text
    body = added.json()
    assert body["effective_total"] == "10500.00"
    assert ("Hostel", "4000.00", "student") in {
        (line["head_name"], line["amount"], line["source"]) for line in body["effective"]
    }
    # The base is returned beside the result, so the screen can answer "why is this
    # student paying more than their class?" rather than making someone reconstruct it.
    assert sum(float(line["amount"]) for line in body["base"]) == 6500.0

    excluded = await assign(fx, walker, fx.head_ids["TRANSPORT"], mode="excluded")
    assert excluded.status_code == 200, excluded.text
    walker_body = excluded.json()
    assert walker_body["effective_total"] == "5000.00"
    # ABSENT, not zero. A "Transport 0.00" line is a question a parent phones about.
    assert [line for line in walker_body["effective"] if line["head_name"] == "Transport"] == []

    # And the arrangement is per student: the boarder still pays transport.
    boarder_now = (
        await fx.get(f"{API}/fees/students/{boarder}/fee-profile", params={"academic_year": YEAR})
    ).json()
    assert boarder_now["effective_total"] == "10500.00"


async def test_generation_bills_each_student_their_own_effective_lines(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """The preview and the challan must agree — that is why both go through one merge.

    A preview showing 10,500 against a challan billing 6,500 is worse than no preview
    at all, because the operator checked and was told the wrong thing.
    """
    fx = await build_fees(tenant, mailbox, students=2)
    boarder, walker = fx.student_ids

    hostel_id = (
        await fx.post(
            f"{API}/fees/heads", json={"code": "HOSTEL", "name": "Hostel", "recurrence": "monthly"}
        )
    ).json()["id"]
    await assign(fx, boarder, hostel_id, mode="added", amount="4000.00")
    await assign(fx, walker, fx.head_ids["TRANSPORT"], mode="excluded")

    run = await generate(fx)
    assert run.status_code == 201, run.text
    assert run.json()["created"] == 2

    totals: dict[str, str] = {}
    names: dict[str, set[str]] = {}
    for voucher_id in run.json()["voucher_ids"]:
        detail = (await fx.get(f"{API}/fees/vouchers/{voucher_id}")).json()
        totals[detail["student_id"]] = detail["total"]
        names[detail["student_id"]] = {i["line_name"] for i in detail["items"]}

    assert totals[boarder] == "10500.00"
    assert names[boarder] == {"Tuition", "Transport", "Hostel"}

    assert totals[walker] == "5000.00"
    assert names[walker] == {"Tuition"}

    # Each challan agrees with the preview that produced it.
    for student_id, expected in ((boarder, "10500.00"), (walker, "5000.00")):
        profile = (
            await fx.get(
                f"{API}/fees/students/{student_id}/fee-profile", params={"academic_year": YEAR}
            )
        ).json()
        assert profile["effective_total"] == expected


async def test_changing_an_arrangement_never_restates_an_issued_challan(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """Same snapshot rule as repricing a structure — it applies to the NEXT run only."""
    fx = await build_fees(tenant, mailbox, students=1)
    student = fx.student_ids[0]
    hostel_id = (
        await fx.post(
            f"{API}/fees/heads", json={"code": "HOSTEL", "name": "Hostel", "recurrence": "monthly"}
        )
    ).json()["id"]
    await assign(fx, student, hostel_id, mode="added", amount="4000.00")

    august = (await generate(fx, period="2026-08")).json()["voucher_ids"][0]
    assert (await fx.get(f"{API}/fees/vouchers/{august}")).json()["total"] == "10500.00"

    # The fare goes up. Idempotent by head — this UPDATES the arrangement rather than
    # creating a second one, so the student cannot end up on two conflicting rates.
    raised = await assign(fx, student, hostel_id, mode="added", amount="5000.00")
    assert raised.status_code == 200, raised.text
    assert len(raised.json()["assignments"]) == 1

    assert (await fx.get(f"{API}/fees/vouchers/{august}")).json()["total"] == "10500.00"
    september = (await generate(fx, period="2026-09")).json()["voucher_ids"][0]
    assert (await fx.get(f"{API}/fees/vouchers/{september}")).json()["total"] == "11500.00"


async def test_removing_an_arrangement_returns_the_student_to_the_class_default(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    fx = await build_fees(tenant, mailbox, students=1)
    student = fx.student_ids[0]

    await assign(fx, student, fx.head_ids["TRANSPORT"], mode="excluded")
    assert (
        await fx.get(f"{API}/fees/students/{student}/fee-profile", params={"academic_year": YEAR})
    ).json()["effective_total"] == "5000.00"

    removed = await fx.delete(
        f"{API}/fees/students/{student}/fee-assignments/{fx.head_ids['TRANSPORT']}",
        params={"academic_year": YEAR},
    )
    assert removed.status_code == 200, removed.text
    assert removed.json()["effective_total"] == "6500.00"
    assert removed.json()["assignments"] == []


async def test_an_excluded_head_carries_no_amount_and_an_added_one_must(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """The two halves of the row must agree about what it means.

    An excluded line is ABSENT from the challan, not zero, so an amount on it is
    meaningless — and an added head with no amount has no rate to bill.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    student = fx.student_ids[0]

    no_amount = await assign(fx, student, fx.head_ids["TRANSPORT"], mode="added")
    assert no_amount.status_code == 422, no_amount.text

    stray_amount = await assign(
        fx, student, fx.head_ids["TRANSPORT"], mode="excluded", amount="100.00"
    )
    assert stray_amount.status_code == 422, stray_amount.text


async def test_a_head_assigned_to_a_student_cannot_be_deleted(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """The other half of the delete guard.

    Counting only structure lines would let someone tidy "Hostel" away while every
    individually boarded student silently stopped being billed — damage that stays
    invisible until the money does not arrive.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    hostel_id = (
        await fx.post(
            f"{API}/fees/heads", json={"code": "HOSTEL", "name": "Hostel", "recurrence": "monthly"}
        )
    ).json()["id"]

    # Unreferenced by any structure OR student: deletable.
    assert (await fx.delete(f"{API}/fees/heads/{hostel_id}")).status_code == 204

    hostel_id = (
        await fx.post(
            f"{API}/fees/heads", json={"code": "HOSTEL2", "name": "Hostel", "recurrence": "monthly"}
        )
    ).json()["id"]
    await assign(fx, fx.student_ids[0], hostel_id, mode="added", amount="4000.00")

    refused = await fx.delete(f"{API}/fees/heads/{hostel_id}")
    assert refused.status_code == 409, refused.text
    assert "student arrangement" in refused.text


async def test_a_student_profile_is_empty_rather_than_broken_before_setup(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """A student in no section, or a class with no structure, is an ordinary
    mid-setup state — not a 404 that makes the fee tab look broken."""
    fx = await build_fees(tenant, mailbox, students=1)
    profile = await fx.get(
        f"{API}/fees/students/{fx.student_ids[0]}/fee-profile",
        params={"academic_year": "2030-2031"},
    )
    assert profile.status_code == 200, profile.text
    body = profile.json()
    assert body["structure_id"] is None
    assert body["base"] == []
    assert body["effective_total"] == "0.00"


async def test_assignments_are_isolated_and_need_manage(
    tenant: Tenant, mailbox: list[EmailMessage]
) -> None:
    """`fee:manage`, not `fee:issue`.

    A clerk trusted to run the monthly billing must not be able to quietly attach a
    4,000 hostel charge to a student's bill — that is a pricing decision.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    hostel_id = (
        await fx.post(
            f"{API}/fees/heads", json={"code": "HOSTEL", "name": "Hostel", "recurrence": "monthly"}
        )
    ).json()["id"]

    issuer = await make_scoped_actor(
        tenant,
        mailbox,
        "assign-issuer@test.example",
        ["fee:read", "fee:issue"],
        code="assign_issuer",
    )
    headers = {"Authorization": f"Bearer {issuer}"}

    blocked = await tenant.client.put(
        f"{API}/fees/students/{fx.student_ids[0]}/fee-assignments",
        headers=headers,
        json={
            "head_id": hostel_id,
            "academic_year": YEAR,
            "mode": "added",
            "amount": "4000.00",
        },
    )
    assert blocked.status_code == 403, blocked.text

    # Reading the profile is `fee:read`, which they do hold — they need to see what
    # they are about to bill.
    readable = await tenant.client.get(
        f"{API}/fees/students/{fx.student_ids[0]}/fee-profile",
        headers=headers,
        params={"academic_year": YEAR},
    )
    assert readable.status_code == 200, readable.text


async def test_assignment_mutations_write_audit_rows_against_the_student(
    tenant: Tenant,
    mailbox: list[EmailMessage],
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """`entity_type` is `student`, not the join table.

    The question this trail answers is "what changed about what THIS CHILD pays", and
    an audit filtered by a join-table id cannot answer it.
    """
    fx = await build_fees(tenant, mailbox, students=1)
    student = fx.student_ids[0]
    hostel_id = (
        await fx.post(
            f"{API}/fees/heads", json={"code": "HOSTEL", "name": "Hostel", "recurrence": "monthly"}
        )
    ).json()["id"]

    await assign(fx, student, hostel_id, mode="added", amount="4000.00", note="Route 4")
    await assign(fx, student, hostel_id, mode="added", amount="5000.00")
    await fx.delete(
        f"{API}/fees/students/{student}/fee-assignments/{hostel_id}", params={"academic_year": YEAR}
    )

    async with admin_sessionmaker() as admin:
        rows = (
            await admin.execute(
                text(
                    "SELECT action, entity_type, entity_id, before, after FROM audit_logs "
                    "WHERE organization_id = :org AND action LIKE 'student_fee.%' "
                    "ORDER BY created_at"
                ),
                {"org": tenant.organization_id},
            )
        ).all()

    assert [r[0] for r in rows] == [
        "student_fee.assigned",
        "student_fee.assigned",
        "student_fee.unassigned",
    ]
    assert {r[1] for r in rows} == {"student"}
    assert {str(r[2]) for r in rows} == {student}
    # Both sides of the fare change, which is what makes the row answer the question.
    assert rows[1][3]["amount"] == "4000.00"
    assert rows[1][4]["amount"] == "5000.00"
