"""Guardian registry and parent-portal release gate.

These run through the app's own `sms_app` connection (NOBYPASSRLS), so the isolation
cases exercise PostgreSQL's policies rather than an application filter. If the policy
on `guardians` or `guardian_students` regressed -- or was never created -- they fail
even though every behavioural test still passes.

WHAT THESE GUARD, IN ORDER OF HOW BADLY IT WOULD HURT TO GET WRONG

  1. NO ENUMERATION. `POST /guardian/auth/request-code` must answer identically for a
     registered and an unregistered number. Anything else turns an unauthenticated
     endpoint into a way to ask whether a specific person has a child at a school.

  2. THE OTP CONTROLS. Wrong codes are capped and then lock the identity; a consumed
     code cannot be replayed; issuing a new code retires the old one. A 6-digit code
     with any one of those missing is worth nothing.

  3. THE PORTAL BOUNDARY IS PER CHILD. `can_view_results=false` means the parent sees
     that child nowhere, even though the link exists for pickup purposes.

  4. ONE HANDSET, ONE PERSON, ACROSS GROUPS. The same phone registered by two
     organizations is one identity with two contexts -- and neither organization can
     see the other's record.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.common.email.sender import EmailMessage
from app.common.sms import SmsMessage
from app.modules.guardians.auth_router import get_sms_dispatcher
from tests.integration.conftest import API, Tenant, make_campus_head

PHONE = "+923001234567"
OTHER_PHONE = "+923009999999"

# The code is read out of the captured SMS body and nowhere else. That is the point:
# the database stores only a peppered digest, so a test that could read the code from
# a row would be testing a system that leaks credentials.
_CODE_RE = re.compile(r"\b(\d{6})\b")


# ---------------------------------------------------------------------------
# SMS capture
# ---------------------------------------------------------------------------


class _CaptureSms:
    """Records messages instead of sending them, so tests can read the codes."""

    def __init__(self, outbox: list[SmsMessage]) -> None:
        self._outbox = outbox

    async def send(self, message: SmsMessage) -> None:
        self._outbox.append(message)


@pytest.fixture
def sms_outbox(db_client: Any) -> list[SmsMessage]:
    """Captured outbound texts, wired into the running app.

    Overrides the dependency on the SAME app instance `db_client` built, rather than
    constructing a second one: two apps would mean two engines and two event loops,
    which is the failure `conftest` documents at length.
    """
    outbox: list[SmsMessage] = []
    db_client._transport.app.dependency_overrides[get_sms_dispatcher] = lambda: _CaptureSms(outbox)
    return outbox


def latest_code(outbox: list[SmsMessage]) -> str:
    assert outbox, "no SMS was dispatched"
    match = _CODE_RE.search(outbox[-1].body)
    assert match, f"no code found in SMS: {outbox[-1].body!r}"
    return match.group(1)


# ---------------------------------------------------------------------------
# Fixture: a school with a class, a section, two students and a registrar
# ---------------------------------------------------------------------------


@dataclass
class GuardianFixture:
    tenant: Tenant
    token: str
    section_id: str = ""
    student_ids: list[str] = field(default_factory=list)

    @property
    def headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "X-Active-School": self.tenant.school_id,
        }

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

    async def register_guardian(self, phone: str = PHONE, **overrides: Any) -> str:
        payload = {"phone": phone, "full_name": "Muhammad Aslam", **overrides}
        created = await self.post(f"{API}/guardians", json=payload)
        assert created.status_code == 201, created.text
        return str(created.json()["id"])

    async def link(self, guardian_id: str, student_id: str, **overrides: Any) -> Any:
        payload: dict[str, Any] = {
            "student_id": student_id,
            "relationship_type": "father",
            **overrides,
        }
        return await self.post(f"{API}/guardians/{guardian_id}/students", json=payload)


async def build_guardians(
    tenant: Tenant,
    mailbox: list[EmailMessage],
    *,
    email: str = "registrar@test.example",
    students: int = 2,
) -> GuardianFixture:
    """Class -> section -> students, built through the public API.

    Nothing is inserted directly, so a fixture cannot construct a state the
    application itself could never produce.
    """
    token = await make_campus_head(tenant, mailbox, email)
    fx = GuardianFixture(tenant, token)

    created_class = await fx.post(f"{API}/classes", json={"name": "Grade 10", "level": 10})
    assert created_class.status_code == 201, created_class.text
    class_id = created_class.json()["id"]

    section = await fx.post(f"{API}/classes/{class_id}/sections", json={"name": "A"})
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
    return fx


@pytest.fixture
async def fx(tenant: Tenant, mailbox: list[EmailMessage]) -> GuardianFixture:
    return await build_guardians(tenant, mailbox)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phone_is_normalised_to_e164_on_registration(fx: GuardianFixture) -> None:
    """A national-format number becomes the same identity as its E.164 spelling.

    THE WHOLE MODULE RESTS ON THIS. If `0300-1234567` and `+923001234567` were two
    rows, a father enrolling a second child would get a second portal account and see
    one of his two children.
    """
    guardian_id = await fx.register_guardian(phone="0300-1234567")
    detail = await fx.get(f"{API}/guardians/{guardian_id}")
    assert detail.status_code == 200, detail.text
    assert detail.json()["phone"] == PHONE

    # The same handset, typed a third way, is refused as already registered rather
    # than creating a duplicate.
    again = await fx.post(
        f"{API}/guardians", json={"phone": "0092 300 1234567", "full_name": "Aslam"}
    )
    assert again.status_code == 409, again.text


@pytest.mark.asyncio
async def test_one_guardian_serves_several_children(fx: GuardianFixture) -> None:
    guardian_id = await fx.register_guardian()
    for student_id in fx.student_ids:
        linked = await fx.link(guardian_id, student_id)
        assert linked.status_code == 201, linked.text

    detail = await fx.get(f"{API}/guardians/{guardian_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["student_count"] == 2
    assert {s["student_id"] for s in body["students"]} == set(fx.student_ids)


@pytest.mark.asyncio
async def test_only_one_primary_contact_per_student(fx: GuardianFixture) -> None:
    """Granting primary contact demotes whoever held it.

    Enforced by a partial unique index, so an application bug cannot produce two --
    but the service must DEMOTE rather than let the constraint reject the write, or
    "make the father the primary contact" answers with a 500.
    """
    student_id = fx.student_ids[0]
    father = await fx.register_guardian(phone=PHONE, full_name="Aslam")
    mother = await fx.register_guardian(phone=OTHER_PHONE, full_name="Ayesha")

    first = await fx.link(father, student_id, is_primary_contact=True)
    assert first.status_code == 201, first.text

    second = await fx.link(mother, student_id, relationship_type="mother", is_primary_contact=True)
    assert second.status_code == 201, second.text

    contacts = await fx.get(f"{API}/guardians/students/{student_id}")
    assert contacts.status_code == 200
    primaries = [c for c in contacts.json() if c["is_primary_contact"]]
    assert len(primaries) == 1
    assert primaries[0]["guardian_id"] == mother


@pytest.mark.asyncio
async def test_other_relationship_requires_a_label(fx: GuardianFixture) -> None:
    guardian_id = await fx.register_guardian()
    refused = await fx.link(guardian_id, fx.student_ids[0], relationship_type="other")
    assert refused.status_code == 422, refused.text
    assert refused.json()["code"] == "RELATIONSHIP_LABEL_REQUIRED"

    accepted = await fx.link(
        guardian_id,
        fx.student_ids[0],
        relationship_type="other",
        relationship_label="Step-father",
    )
    assert accepted.status_code == 201, accepted.text


@pytest.mark.asyncio
async def test_guardian_with_children_cannot_be_removed(fx: GuardianFixture) -> None:
    """Refuse rather than cascade -- the emergency contact for four children must not
    disappear on one mis-click."""
    guardian_id = await fx.register_guardian()
    assert (await fx.link(guardian_id, fx.student_ids[0])).status_code == 201

    refused = await fx.delete(f"{API}/guardians/{guardian_id}")
    assert refused.status_code == 409, refused.text

    unlinked = await fx.delete(f"{API}/guardians/{guardian_id}/students/{fx.student_ids[0]}")
    assert unlinked.status_code == 204, unlinked.text
    assert (await fx.delete(f"{API}/guardians/{guardian_id}")).status_code == 204


@pytest.mark.asyncio
async def test_changing_the_phone_needs_the_portal_permission(
    fx: GuardianFixture, mailbox: list[EmailMessage]
) -> None:
    """`guardian:update` fixes typos; only `guardian:portal` moves a login.

    The separation is the point: a clerk who may correct a spelling must not be able
    to re-point a father's login at their own handset, which is an account takeover
    that looks like ordinary data entry in every log.
    """
    from app.modules.rbac.catalog import SCHOOL_SCOPED_CODES

    guardian_id = await fx.register_guardian()

    role = await fx.post(
        f"{API}/schools/{fx.tenant.school_id}/roles",
        json={
            "code": "front_desk",
            "name": "Front desk",
            "permissions": sorted(SCHOOL_SCOPED_CODES - {"guardian:portal"}),
        },
    )
    assert role.status_code == 201, role.text

    invited = await fx.post(
        f"{API}/schools/{fx.tenant.school_id}/invitations",
        json={
            "email": "frontdesk@test.example",
            "full_name": "Front Desk",
            "role_id": role.json()["id"],
        },
    )
    assert invited.status_code == 201, invited.text

    from tests.integration.conftest import STRONG_PASSWORD, latest_token

    fx.tenant.client.cookies.clear()
    accepted = await fx.tenant.client.post(
        f"{API}/invitations/accept",
        json={
            "token": latest_token(mailbox),
            "full_name": "Front Desk",
            "password": STRONG_PASSWORD,
        },
    )
    assert accepted.status_code == 200, accepted.text
    fx.tenant.client.cookies.clear()

    login = await fx.tenant.client.post(
        f"{API}/auth/login",
        json={"email": "frontdesk@test.example", "password": STRONG_PASSWORD},
        headers={"X-Token-Transport": "body"},
    )
    assert login.status_code == 200, login.text
    fx.tenant.client.cookies.clear()
    desk = {"Authorization": f"Bearer {login.headers['X-Access-Token']}"}

    # They CAN correct the name...
    renamed = await fx.tenant.client.patch(
        f"{API}/guardians/{guardian_id}", json={"full_name": "M. Aslam Khan"}, headers=desk
    )
    assert renamed.status_code == 200, renamed.text

    # ...and they CANNOT move the login.
    moved = await fx.tenant.client.put(
        f"{API}/guardians/{guardian_id}/phone", json={"phone": OTHER_PHONE}, headers=desk
    )
    assert moved.status_code == 403, moved.text
    assert moved.json()["meta"]["missing"] == ["guardian:portal"]


# ---------------------------------------------------------------------------
# Portal authentication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_code_does_not_reveal_whether_a_number_is_registered(
    fx: GuardianFixture, sms_outbox: list[SmsMessage]
) -> None:
    """Identical response, registered or not. Only the SMS differs.

    An honest 404 here would let anyone test whether a given person has a child at a
    school on this platform -- exactly what a stalker or an abusive ex-partner wants,
    and what no parent agreed to publish.
    """
    await fx.register_guardian()

    known = await fx.tenant.client.post(f"{API}/guardian/auth/request-code", json={"phone": PHONE})
    unknown = await fx.tenant.client.post(
        f"{API}/guardian/auth/request-code", json={"phone": "+923215550000"}
    )

    assert known.status_code == unknown.status_code == 200
    assert known.json()["message"] == unknown.json()["message"]
    assert set(known.json()) == set(unknown.json())
    # One text went out, for the registered number only.
    assert len(sms_outbox) == 1
    assert sms_outbox[0].to == PHONE


@pytest.mark.asyncio
async def test_full_portal_login_reaches_only_the_linked_child(
    fx: GuardianFixture, sms_outbox: list[SmsMessage]
) -> None:
    guardian_id = await fx.register_guardian()
    assert (await fx.link(guardian_id, fx.student_ids[0])).status_code == 201

    requested = await fx.tenant.client.post(
        f"{API}/guardian/auth/request-code", json={"phone": PHONE}
    )
    assert requested.status_code == 200, requested.text

    verified = await fx.tenant.client.post(
        f"{API}/guardian/auth/verify",
        json={"phone": PHONE, "code": latest_code(sms_outbox)},
        headers={"X-Token-Transport": "body"},
    )
    assert verified.status_code == 200, verified.text
    body = verified.json()
    assert body["status"] == "authenticated"
    assert body["guardian"]["phone"] == PHONE
    token = body["tokens"]["access_token"]
    fx.tenant.client.cookies.clear()

    portal = {"Authorization": f"Bearer {token}"}
    children = await fx.tenant.client.get(f"{API}/portal/children", headers=portal)
    assert children.status_code == 200, children.text
    assert [c["student_id"] for c in children.json()] == [fx.student_ids[0]]

    # The OTHER child at the same school, whom this guardian is not linked to.
    other = await fx.tenant.client.get(f"{API}/portal/children/{fx.student_ids[1]}", headers=portal)
    assert other.status_code == 404, other.text


@pytest.mark.asyncio
async def test_portal_hides_a_child_the_guardian_may_only_collect(
    fx: GuardianFixture, sms_outbox: list[SmsMessage]
) -> None:
    """`can_pickup` and `can_view_results` are independent, and must stay that way.

    The neighbour who collects the child at the gate must read nothing about them.
    Collapsing the two flags into one "is guardian" boolean is how that goes wrong.
    """
    guardian_id = await fx.register_guardian()
    linked = await fx.link(
        guardian_id,
        fx.student_ids[0],
        relationship_type="other",
        relationship_label="Neighbour",
        can_pickup=True,
        can_view_results=False,
    )
    assert linked.status_code == 201, linked.text

    await fx.tenant.client.post(f"{API}/guardian/auth/request-code", json={"phone": PHONE})
    verified = await fx.tenant.client.post(
        f"{API}/guardian/auth/verify",
        json={"phone": PHONE, "code": latest_code(sms_outbox)},
        headers={"X-Token-Transport": "body"},
    )
    assert verified.status_code == 200, verified.text
    # No child is viewable, so there is no organization to open at all.
    assert verified.json()["status"] == "no_access"


@pytest.mark.asyncio
async def test_a_code_cannot_be_used_twice(
    fx: GuardianFixture, sms_outbox: list[SmsMessage]
) -> None:
    guardian_id = await fx.register_guardian()
    assert (await fx.link(guardian_id, fx.student_ids[0])).status_code == 201

    await fx.tenant.client.post(f"{API}/guardian/auth/request-code", json={"phone": PHONE})
    code = latest_code(sms_outbox)

    first = await fx.tenant.client.post(
        f"{API}/guardian/auth/verify", json={"phone": PHONE, "code": code}
    )
    assert first.status_code == 200, first.text
    fx.tenant.client.cookies.clear()

    replay = await fx.tenant.client.post(
        f"{API}/guardian/auth/verify", json={"phone": PHONE, "code": code}
    )
    assert replay.status_code == 401, replay.text
    assert replay.json()["code"] == "INVALID_CODE"


@pytest.mark.asyncio
async def test_wrong_codes_are_capped_and_then_lock_the_identity(
    fx: GuardianFixture, sms_outbox: list[SmsMessage]
) -> None:
    """The attempt cap is the ONLY thing making a 6-digit code worth anything.

    Note the counter lives on the IDENTITY, not the code row: requesting a fresh code
    must not hand an attacker a fresh budget, which is the obvious bypass of a
    per-code counter and the one people ship.
    """
    guardian_id = await fx.register_guardian()
    assert (await fx.link(guardian_id, fx.student_ids[0])).status_code == 201

    await fx.tenant.client.post(f"{API}/guardian/auth/request-code", json={"phone": PHONE})
    real = latest_code(sms_outbox)
    wrong = "000000" if real != "000000" else "111111"

    codes = []
    for _ in range(6):
        response = await fx.tenant.client.post(
            f"{API}/guardian/auth/verify", json={"phone": PHONE, "code": wrong}
        )
        codes.append(response.json()["code"])

    assert codes[:5] == ["INVALID_CODE"] * 5
    assert codes[5] == "GUARDIAN_LOCKED"

    # And the real code no longer works either: the code was burned with the identity.
    after = await fx.tenant.client.post(
        f"{API}/guardian/auth/verify", json={"phone": PHONE, "code": real}
    )
    assert after.json()["code"] == "GUARDIAN_LOCKED"


@pytest.mark.asyncio
async def test_a_staff_token_cannot_open_the_portal(fx: GuardianFixture) -> None:
    """Refused on the `typ` claim, not on a missing field.

    "Has an org claim but no membership claim" would also describe a mis-minted staff
    token, and that must never open a parent surface.
    """
    refused = await fx.tenant.client.get(f"{API}/portal/children", headers=fx.headers)
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "GUARDIAN_ACCESS_REQUIRED"


@pytest.mark.asyncio
async def test_disabling_the_portal_takes_effect_immediately(
    fx: GuardianFixture, sms_outbox: list[SmsMessage]
) -> None:
    """Revocation that takes effect "eventually" is not revocation.

    The guardian record is re-read on every request, so switching the portal off must
    close an already-issued token within one access-token lifetime -- not one
    refresh-token lifetime.
    """
    guardian_id = await fx.register_guardian()
    assert (await fx.link(guardian_id, fx.student_ids[0])).status_code == 201

    await fx.tenant.client.post(f"{API}/guardian/auth/request-code", json={"phone": PHONE})
    verified = await fx.tenant.client.post(
        f"{API}/guardian/auth/verify",
        json={"phone": PHONE, "code": latest_code(sms_outbox)},
        headers={"X-Token-Transport": "body"},
    )
    assert verified.status_code == 200, verified.text
    portal = {"Authorization": f"Bearer {verified.json()['tokens']['access_token']}"}
    fx.tenant.client.cookies.clear()

    assert (await fx.tenant.client.get(f"{API}/portal/children", headers=portal)).status_code == 200

    disabled = await fx.put(f"{API}/guardians/{guardian_id}/portal", json={"enabled": False})
    assert disabled.status_code == 200, disabled.text

    closed = await fx.tenant.client.get(f"{API}/portal/children", headers=portal)
    assert closed.status_code == 403, closed.text
    assert closed.json()["code"] == "GUARDIAN_PORTAL_DISABLED"


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_handset_two_school_groups_stays_one_identity(
    make_tenant: Callable[..., Any],
    mailbox: list[EmailMessage],
    sms_outbox: list[SmsMessage],
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """The father with a child in each of two groups.

    ONE identity, TWO guardian records, and each group sees only its own -- which is
    the case four denormalised columns on `students` cannot express at all.
    """
    first = await make_tenant(name="Alpha Trust", email="alpha@test.example", school_code="ALPHA")
    fx_a = await build_guardians(first, mailbox, email="registrar-a@test.example", students=1)
    guardian_a = await fx_a.register_guardian()
    assert (await fx_a.link(guardian_a, fx_a.student_ids[0])).status_code == 201

    second = await make_tenant(name="Beta Trust", email="beta@test.example", school_code="BETA")
    fx_b = await build_guardians(second, mailbox, email="registrar-b@test.example", students=1)
    # The SAME number, registered independently by an organization that cannot see the
    # first one's records -- and is told nothing about them.
    guardian_b = await fx_b.register_guardian()
    assert guardian_b != guardian_a
    assert (await fx_b.link(guardian_b, fx_b.student_ids[0])).status_code == 201

    async with admin_sessionmaker() as session:
        identities = (
            await session.execute(
                text("SELECT count(*) FROM guardian_identities WHERE phone = :p"), {"p": PHONE}
            )
        ).scalar_one()
        records = (
            await session.execute(
                text(
                    "SELECT count(*) FROM guardians g "
                    "JOIN guardian_identities i ON i.id = g.identity_id "
                    "WHERE i.phone = :p"
                ),
                {"p": PHONE},
            )
        ).scalar_one()
    assert identities == 1, "the same handset must be one identity"
    assert records == 2, "each organization keeps its own record"

    # Group A cannot see group B's record.
    cross = await fx_a.get(f"{API}/guardians/{guardian_b}")
    assert cross.status_code == 404, cross.text

    # And the login offers a choice rather than guessing.
    await fx_a.tenant.client.post(f"{API}/guardian/auth/request-code", json={"phone": PHONE})
    verified = await fx_a.tenant.client.post(
        f"{API}/guardian/auth/verify",
        json={"phone": PHONE, "code": latest_code(sms_outbox)},
        headers={"X-Token-Transport": "body"},
    )
    assert verified.status_code == 200, verified.text
    body = verified.json()
    assert body["status"] == "select_required"
    assert {c["guardian_id"] for c in body["contexts"]} == {guardian_a, guardian_b}


@pytest.mark.asyncio
async def test_rls_blocks_a_cross_tenant_guardian_read(
    make_tenant: Callable[..., Any],
    mailbox: list[EmailMessage],
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """The database refuses, not the application.

    Run on the app's own restricted connection with another organization's id bound,
    so a passing result would mean the policy on `guardians` is genuinely doing the
    work rather than a repository filter happening to be present.
    """
    from app.db.session import bind_tenant, get_session_factory

    first = await make_tenant(name="Gamma Trust", email="gamma@test.example", school_code="GAMMA")
    fx_a = await build_guardians(first, mailbox, email="registrar-g@test.example", students=1)
    guardian_a = await fx_a.register_guardian()

    second = await make_tenant(name="Delta Trust", email="delta@test.example", school_code="DELTA")

    async with get_session_factory()() as session:
        await bind_tenant(session, second.organization_id)
        rows = (
            await session.execute(
                text("SELECT count(*) FROM guardians WHERE id = :id"), {"id": guardian_a}
            )
        ).scalar_one()
        assert rows == 0, "RLS did not hide another organization's guardian"

        # And a WRITE stamped with the other tenant's id is refused outright -- the
        # WITH CHECK half of the policy, which a USING-only policy would not catch.
        #
        # The identity id is read from the UNPROTECTED `guardian_identities` table on
        # purpose: sourcing it from `guardians` would return no rows under the USING
        # clause, the INSERT would write nothing, and the test would pass while
        # proving nothing about WITH CHECK.
        identity_id = (
            await session.execute(
                text("SELECT id FROM guardian_identities WHERE phone = :p"), {"p": PHONE}
            )
        ).scalar_one()
        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    "INSERT INTO guardians (organization_id, identity_id, full_name) "
                    "VALUES (:org, :identity, 'Injected')"
                ),
                {"org": first.organization_id, "identity": identity_id},
            )
        await session.rollback()

    async with admin_sessionmaker() as session:
        surviving = (
            await session.execute(
                text("SELECT count(*) FROM guardians WHERE full_name = 'Injected'")
            )
        ).scalar_one()
    assert surviving == 0
