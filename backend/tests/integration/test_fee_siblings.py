"""Sibling remission -- families found through their parents, proposed, then applied.

Everything is built through the public API: classes, students, parents linked with
the staff "turn on parent access" call, concession schemes, the sibling rule, the
review and apply, and the challan the next billing run prints.

WHAT THESE GUARD

  1. NOTHING CHANGES UNTIL A PERSON APPLIES IT. Saving the rule touches no child.
  2. A FAMILY IS WHO THE PARENTS ARE. Children sharing a father, mother or legal
     guardian are one family -- transitively, so a blended household is one family --
     and a shared grandparent or neighbour makes nobody a sibling.
  3. THE HIGHEST CLASS PAYS IN FULL, then positions follow class, with a blank
     position taking the scheme before it.
  4. ANOTHER ARRANGEMENT ON THE HEAD IS NEVER OVERWRITTEN; it is reported.
  5. WHEN A FAMILY CHANGES, THE DISCOUNT FOLLOWS ON THE NEXT REVIEW: an elder child
     leaving moves the others up, and a child with no sibling left is proposed off.
  6. A SIBLING AT ANOTHER CAMPUS COUNTS toward positions but is that campus's to
     discount.
  7. An arrangement taken off and put back is restored, not refused as a duplicate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import pytest

from app.common.email.sender import EmailMessage
from tests.integration.conftest import API, Tenant, make_campus_head
from tests.integration.test_fees import YEAR, FeeFixture, build_fees, make_scoped_actor

MOTHER = "0300-1110001"
FATHER = "0300-1110002"


@dataclass
class Siblings:
    """A campus with Grade 10 (tuition 5,000) and Grade 5 (tuition 3,000), three
    sibling schemes, and an empty Grade 5 waiting for younger children."""

    fx: FeeFixture
    grade5_section_id: str = ""
    grade5_structure_id: str = ""
    schemes: dict[str, str] = field(default_factory=dict)
    counter: int = 100

    async def student(self, first: str, *, grade: int = 10) -> str:
        self.counter += 1
        section = self.fx.section_id if grade == 10 else self.grade5_section_id
        created = await self.fx.post(
            f"{API}/students",
            json={
                "admission_number": f"2026-{self.counter}",
                "first_name": first,
                "last_name": "Khan",
                "section_id": section,
            },
        )
        assert created.status_code == 201, created.text
        return str(created.json()["id"])

    async def link(
        self, student_id: str, phone: str, relationship: str, name: str = "Parent"
    ) -> None:
        body: dict[str, Any] = {
            "phone": phone,
            "full_name": name,
            "relationship_type": relationship,
        }
        if relationship == "other":
            body["relationship_label"] = "Neighbour"
        granted = await self.fx.post(
            f"{API}/guardians/students/{student_id}/portal-access", json=body
        )
        assert granted.status_code == 200, granted.text

    async def rule(self, **overrides: Any) -> Any:
        body: dict[str, Any] = {
            "head_id": self.fx.head_ids["TUITION"],
            "second_concession_id": self.schemes["SIB2"],
        }
        body.update(overrides)
        return await self.fx.put(f"{API}/fees/sibling-rule", json=body)

    async def review(self) -> dict[str, Any]:
        reviewed = await self.fx.get(f"{API}/fees/siblings", params={"academic_year": YEAR})
        assert reviewed.status_code == 200, reviewed.text
        return dict(reviewed.json())

    async def apply(self, *student_ids: str) -> dict[str, Any]:
        applied = await self.fx.post(
            f"{API}/fees/siblings/apply",
            json={"academic_year": YEAR, "student_ids": list(student_ids)},
        )
        assert applied.status_code == 200, applied.text
        return dict(applied.json())

    async def set_status(self, student_id: str, status: str) -> None:
        updated = await self.fx.patch(f"{API}/students/{student_id}", json={"status": status})
        assert updated.status_code == 200, updated.text

    async def tuition_arrangement(self, student_id: str) -> dict[str, Any] | None:
        profile = await self.fx.get(
            f"{API}/fees/students/{student_id}/fee-profile", params={"academic_year": YEAR}
        )
        assert profile.status_code == 200, profile.text
        for assignment in profile.json()["assignments"]:
            if assignment["head_id"] == self.fx.head_ids["TUITION"]:
                return dict(assignment)
        return None


def _actions(review: dict[str, Any]) -> list[list[tuple[str, int | None, str]]]:
    """Each family as [(name, position, action), ...]."""
    return [
        [(m["student_name"], m["position"], m["action"]) for m in family["members"]]
        for family in review["families"]
    ]


def _member(review: dict[str, Any], student_id: str) -> dict[str, Any]:
    for family in review["families"]:
        for member in family["members"]:
            if member["student_id"] == student_id:
                return dict(member)
    raise AssertionError(f"{student_id} is in no family")


@pytest.fixture
async def sib(tenant: Tenant, mailbox: list[EmailMessage]) -> Siblings:
    fx = await build_fees(tenant, mailbox, students=0)
    s = Siblings(fx)

    grade5 = await fx.post(f"{API}/classes", json={"name": "Grade 5", "level": 5})
    assert grade5.status_code == 201, grade5.text
    section = await fx.post(f"{API}/classes/{grade5.json()['id']}/sections", json={"name": "A"})
    assert section.status_code == 201, section.text
    s.grade5_section_id = section.json()["id"]

    structure = await fx.post(
        f"{API}/fees/structures",
        json={
            "class_id": grade5.json()["id"],
            "academic_year": YEAR,
            "name": f"Grade 5 {YEAR}",
            "items": [{"head_id": fx.head_ids["TUITION"], "amount": "3000.00"}],
        },
    )
    assert structure.status_code == 201, structure.text
    s.grade5_structure_id = structure.json()["id"]
    activated = await fx.post(f"{API}/fees/structures/{s.grade5_structure_id}/activate")
    assert activated.status_code == 200, activated.text

    for code, name, value in (
        ("SIB2", "Sibling - 2nd child", "10.00"),
        ("SIB3", "Sibling - 3rd child", "15.00"),
        ("SIB4", "Sibling - 4th child and later", "20.00"),
    ):
        created = await fx.post(
            f"{API}/fees/concessions",
            json={"code": code, "name": name, "kind": "percent", "value": value},
        )
        assert created.status_code == 201, created.text
        s.schemes[code] = created.json()["id"]
    return s


# ---------------------------------------------------------------------------
# 1. The rule
# ---------------------------------------------------------------------------


async def test_the_review_needs_a_rule_and_saving_one_changes_no_fees(sib: Siblings) -> None:
    elder = await sib.student("Ali")
    younger = await sib.student("Sara", grade=5)
    await sib.link(elder, MOTHER, "mother")
    await sib.link(younger, MOTHER, "mother")

    assert (await sib.fx.get(f"{API}/fees/sibling-rule")).json() is None
    missing = await sib.fx.get(f"{API}/fees/siblings", params={"academic_year": YEAR})
    assert missing.status_code == 422, missing.text
    assert missing.json()["code"] == "SIBLING_RULE_MISSING"

    saved = await sib.rule()
    assert saved.status_code == 200, saved.text
    rule = saved.json()
    assert rule["head_name"] == "Tuition"
    assert rule["second"]["name"] == "Sibling - 2nd child"
    assert rule["third"] is None and rule["later"] is None

    assert await sib.tuition_arrangement(younger) is None


async def test_an_inactive_scheme_cannot_be_put_in_the_rule(sib: Siblings) -> None:
    retired = await sib.fx.patch(
        f"{API}/fees/concessions/{sib.schemes['SIB3']}", json={"is_active": False}
    )
    assert retired.status_code == 200, retired.text
    refused = await sib.rule(third_concession_id=sib.schemes["SIB3"])
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "CONCESSION_INACTIVE"


async def test_the_rules_head_and_schemes_cannot_be_deleted(sib: Siblings) -> None:
    assert (await sib.rule(later_concession_id=sib.schemes["SIB4"])).status_code == 200

    scheme = await sib.fx.delete(f"{API}/fees/concessions/{sib.schemes['SIB4']}")
    assert scheme.status_code == 409, scheme.text
    assert "sibling rule" in scheme.json()["detail"]

    head = await sib.fx.delete(f"{API}/fees/heads/{sib.fx.head_ids['TUITION']}")
    assert head.status_code == 409, head.text
    assert "the sibling rule" in head.json()["detail"]

    removed = await sib.fx.delete(f"{API}/fees/sibling-rule")
    assert removed.status_code == 204, removed.text
    assert (await sib.fx.delete(f"{API}/fees/concessions/{sib.schemes['SIB4']}")).status_code == 204


# ---------------------------------------------------------------------------
# 2-3. Who is a family, and who pays in full
# ---------------------------------------------------------------------------


async def test_the_highest_class_pays_in_full_and_the_younger_child_is_discounted(
    sib: Siblings,
) -> None:
    # The younger child is admitted FIRST, so position follows class, not admission.
    younger = await sib.student("Sara", grade=5)
    elder = await sib.student("Ali")
    await sib.link(younger, MOTHER, "mother", name="Ayesha Khan")
    await sib.link(elder, MOTHER, "mother", name="Ayesha Khan")
    await sib.rule()

    review = await sib.review()
    assert _actions(review) == [[("Ali Khan", 1, "full_fee"), ("Sara Khan", 2, "apply")]]
    family = review["families"][0]
    assert [(g["full_name"], g["relationships"]) for g in family["guardians"]] == [
        ("Ayesha Khan", ["mother"])
    ]
    assert _member(review, younger)["proposed_concession_name"] == "Sibling - 2nd child"
    assert review["to_apply"] == 1

    result = await sib.apply(younger, elder)
    assert (result["applied"], result["changed"], result["removed"]) == (1, 0, 0)
    assert [s["student_id"] for s in result["skipped"]] == [elder]
    assert _member(result["review"], younger)["action"] == "ok"

    arrangement = await sib.tuition_arrangement(younger)
    assert arrangement is not None
    assert arrangement["mode"] == "discount"
    assert arrangement["concession_id"] == sib.schemes["SIB2"]
    assert arrangement["note"] == "Sibling discount: 2nd child"

    # And the next billing run prints it: 10% off Grade 5's 3,000.
    today = date.today()
    run = await sib.fx.post(
        f"{API}/fees/vouchers/generate",
        json={
            "structure_id": sib.grade5_structure_id,
            "period_label": "2026-11",
            "issue_date": today.isoformat(),
            "due_date": (today + timedelta(days=10)).isoformat(),
        },
    )
    assert run.status_code == 201, run.text
    listed = await sib.fx.get(f"{API}/fees/vouchers", params={"student_id": younger})
    (voucher,) = listed.json()["items"]
    assert Decimal(voucher["discount_total"]) == Decimal("300.00")
    assert Decimal(voucher["total"]) == Decimal("2700.00")


async def test_a_shared_grandparent_or_neighbour_makes_nobody_a_sibling(sib: Siblings) -> None:
    first = await sib.student("Hamza")
    second = await sib.student("Zain", grade=5)
    for child in (first, second):
        await sib.link(child, "0300-2220001", "grandparent")
        await sib.link(child, "0300-2220002", "other")
    await sib.rule()

    review = await sib.review()
    assert review["families"] == []
    assert review["no_longer_eligible"] == []


async def test_a_blended_family_is_one_family_and_blank_positions_take_the_one_before(
    sib: Siblings,
) -> None:
    """A and B share a mother; B, C and D share a father. One household of four.

    The third position is left blank, so the third child gets the second child's
    scheme; the fourth gets its own.
    """
    a = await sib.student("Amna")
    b = await sib.student("Bilal")
    c = await sib.student("Chand", grade=5)
    d = await sib.student("Dua", grade=5)
    await sib.link(a, MOTHER, "mother", name="Mother")
    await sib.link(b, MOTHER, "mother", name="Mother")
    for child in (b, c, d):
        await sib.link(child, FATHER, "father", name="Father")
    await sib.rule(later_concession_id=sib.schemes["SIB4"])

    review = await sib.review()
    assert _actions(review) == [
        [
            ("Amna Khan", 1, "full_fee"),
            ("Bilal Khan", 2, "apply"),
            ("Chand Khan", 3, "apply"),
            ("Dua Khan", 4, "apply"),
        ]
    ]
    assert _member(review, c)["proposed_concession_id"] == sib.schemes["SIB2"]
    assert _member(review, d)["proposed_concession_id"] == sib.schemes["SIB4"]
    assert [g["relationships"] for g in review["families"][0]["guardians"]] == [
        ["father"],
        ["mother"],
    ]


# ---------------------------------------------------------------------------
# 4. Another arrangement is reported, not overwritten
# ---------------------------------------------------------------------------


async def test_another_discount_on_the_head_is_a_conflict_and_is_left_alone(
    sib: Siblings,
) -> None:
    elder = await sib.student("Ali")
    younger = await sib.student("Sara", grade=5)
    await sib.link(elder, MOTHER, "mother")
    await sib.link(younger, MOTHER, "mother")
    staff = await sib.fx.post(
        f"{API}/fees/concessions",
        json={"code": "STAFF", "name": "Staff child remission", "kind": "percent", "value": "50"},
    )
    assert staff.status_code == 201, staff.text
    on_staff = await sib.fx.put(
        f"{API}/fees/students/{younger}/fee-assignments",
        json={
            "academic_year": YEAR,
            "head_id": sib.fx.head_ids["TUITION"],
            "mode": "discount",
            "concession_id": staff.json()["id"],
        },
    )
    assert on_staff.status_code == 200, on_staff.text
    await sib.rule()

    member = _member(await sib.review(), younger)
    assert member["action"] == "conflict"
    assert member["current"] == "Staff child remission"
    assert "Staff child remission" in member["reason"]

    result = await sib.apply(younger)
    assert result["applied"] == 0
    assert result["skipped"][0]["reason"] == member["reason"]
    arrangement = await sib.tuition_arrangement(younger)
    assert arrangement is not None
    assert arrangement["concession_id"] == staff.json()["id"]


# ---------------------------------------------------------------------------
# 5. When the family changes
# ---------------------------------------------------------------------------


async def test_when_the_only_sibling_leaves_the_discount_is_proposed_off_and_can_return(
    sib: Siblings,
) -> None:
    elder = await sib.student("Ali")
    younger = await sib.student("Sara", grade=5)
    await sib.link(elder, MOTHER, "mother")
    await sib.link(younger, MOTHER, "mother")
    await sib.rule()
    await sib.apply(younger)

    await sib.set_status(elder, "inactive")
    review = await sib.review()
    assert review["families"] == []
    (orphan,) = review["no_longer_eligible"]
    assert (orphan["student_id"], orphan["action"]) == (younger, "remove")
    assert orphan["current"] == "Sibling - 2nd child"
    assert review["to_remove"] == 1

    result = await sib.apply(younger)
    assert result["removed"] == 1
    assert result["review"]["no_longer_eligible"] == []
    assert await sib.tuition_arrangement(younger) is None

    # The brother comes back. Putting the discount back RESTORES the removed row
    # instead of colliding with it.
    await sib.set_status(elder, "active")
    result = await sib.apply(younger)
    assert result["applied"] == 1, result
    arrangement = await sib.tuition_arrangement(younger)
    assert arrangement is not None
    assert arrangement["concession_id"] == sib.schemes["SIB2"]


async def test_positions_move_up_when_the_eldest_leaves(sib: Siblings) -> None:
    eldest = await sib.student("Amna")
    middle = await sib.student("Bilal", grade=5)
    youngest = await sib.student("Chand", grade=5)
    for child in (eldest, middle, youngest):
        await sib.link(child, MOTHER, "mother")
    await sib.rule(third_concession_id=sib.schemes["SIB3"])
    await sib.apply(middle, youngest)
    assert (await sib.tuition_arrangement(youngest) or {})["concession_id"] == sib.schemes["SIB3"]

    await sib.set_status(eldest, "inactive")
    review = await sib.review()
    assert _actions(review) == [[("Bilal Khan", 1, "remove"), ("Chand Khan", 2, "change")]]
    assert review["to_apply"] == 1 and review["to_remove"] == 1

    result = await sib.apply(middle, youngest)
    assert (result["applied"], result["changed"], result["removed"]) == (0, 1, 1)
    assert await sib.tuition_arrangement(middle) is None
    assert (await sib.tuition_arrangement(youngest) or {})["concession_id"] == sib.schemes["SIB2"]


# ---------------------------------------------------------------------------
# 6. Across campuses
# ---------------------------------------------------------------------------


async def test_a_sibling_at_another_campus_counts_but_is_that_campus_s_to_discount(
    tenant: Tenant, mailbox: list[EmailMessage], sib: Siblings
) -> None:
    second = await tenant.post(f"{API}/schools", json={"name": "Girls Campus", "code": "GIRLS"})
    assert second.status_code == 201, second.text
    mailbox.clear()
    token = await make_campus_head(
        tenant, mailbox, "girls-head@test.example", school_id=second.json()["id"], code="girls"
    )
    other = FeeFixture(tenant, token)
    grade12 = await other.post(f"{API}/classes", json={"name": "Grade 12", "level": 12})
    assert grade12.status_code == 201, grade12.text
    section = await other.post(f"{API}/classes/{grade12.json()['id']}/sections", json={"name": "A"})
    assert section.status_code == 201, section.text
    sister = await other.post(
        f"{API}/students",
        json={
            "admission_number": "G-001",
            "first_name": "Maryam",
            "last_name": "Khan",
            "section_id": section.json()["id"],
        },
    )
    assert sister.status_code == 201, sister.text
    sister_id = sister.json()["id"]
    linked = await other.post(
        f"{API}/guardians/students/{sister_id}/portal-access",
        json={"phone": MOTHER, "full_name": "Ayesha Khan", "relationship_type": "mother"},
    )
    assert linked.status_code == 200, linked.text

    elder = await sib.student("Ali")
    younger = await sib.student("Sara", grade=5)
    await sib.link(elder, MOTHER, "mother", name="Ayesha Khan")
    await sib.link(younger, MOTHER, "mother", name="Ayesha Khan")
    await sib.rule(third_concession_id=sib.schemes["SIB3"])

    review = await sib.review()
    assert _actions(review) == [
        [("Maryam Khan", 1, "other_campus"), ("Ali Khan", 2, "apply"), ("Sara Khan", 3, "apply")]
    ]
    sister_row = _member(review, sister_id)
    assert (sister_row["campus_name"], sister_row["at_this_campus"]) == ("Girls Campus", False)

    result = await sib.apply(sister_id, elder, younger)
    assert result["applied"] == 2
    assert [s["student_id"] for s in result["skipped"]] == [sister_id]

    # The girls' campus has no rule of its own, and its review says so.
    theirs = await other.get(f"{API}/fees/siblings", params={"academic_year": YEAR})
    assert theirs.status_code == 422, theirs.text


# ---------------------------------------------------------------------------
# 7. Permissions and the arrangement fix
# ---------------------------------------------------------------------------


async def test_the_review_and_apply_need_fee_manage(
    tenant: Tenant, mailbox: list[EmailMessage], sib: Siblings
) -> None:
    await sib.rule()
    mailbox.clear()
    token = await make_scoped_actor(
        tenant, mailbox, "reader@test.example", ["fee:read"], code="fee_reader"
    )
    reader = FeeFixture(tenant, token)

    assert (await reader.get(f"{API}/fees/sibling-rule")).status_code == 200
    review = await reader.get(f"{API}/fees/siblings", params={"academic_year": YEAR})
    assert review.status_code == 403, review.text
    student = await sib.student("Ali")
    applied = await reader.post(
        f"{API}/fees/siblings/apply", json={"academic_year": YEAR, "student_ids": [student]}
    )
    assert applied.status_code == 403, applied.text
    rule = await reader.put(
        f"{API}/fees/sibling-rule",
        json={"head_id": sib.fx.head_ids["TUITION"], "second_concession_id": sib.schemes["SIB2"]},
    )
    assert rule.status_code == 403, rule.text


async def test_an_arrangement_taken_off_and_put_back_is_restored(sib: Siblings) -> None:
    student = await sib.student("Ali")
    url = f"{API}/fees/students/{student}/fee-assignments"
    body = {
        "academic_year": YEAR,
        "head_id": sib.fx.head_ids["TUITION"],
        "mode": "discount",
        "percent": "10.00",
    }
    assert (await sib.fx.put(url, json=body)).status_code == 200
    removed = await sib.fx.delete(
        f"{url}/{sib.fx.head_ids['TUITION']}", params={"academic_year": YEAR}
    )
    assert removed.status_code == 200, removed.text

    again = await sib.fx.put(url, json={**body, "percent": "20.00"})
    assert again.status_code == 200, again.text
    arrangement = await sib.tuition_arrangement(student)
    assert arrangement is not None
    assert Decimal(arrangement["percent"]) == Decimal("20.00")
