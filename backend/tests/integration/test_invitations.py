"""Invitation gates (spec §12 "Invitations", §7).

An invitation is the only path by which a new human enters an existing organization,
which makes it that organization's entire attack surface for unwanted members. Each
test below names the attack its guard defeats.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.conftest import API, STRONG_PASSWORD, Tenant, latest_token


async def _invite(tenant: Tenant, email: str, role_code: str = "teacher") -> tuple[str, str]:
    """Send an invitation and return `(invitation_id, raw_token)`."""
    roles = await tenant.get(f"{API}/schools/{tenant.school_id}/roles")
    role = next(r for r in roles.json() if r["code"] == role_code)

    response = await tenant.post(
        f"{API}/schools/{tenant.school_id}/invitations",
        json={"email": email, "full_name": "Invitee", "role_id": role["id"]},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"], ""


async def test_new_user_accepts_and_can_sign_in(tenant: Tenant, mailbox: list[Any]) -> None:
    """Spec §12 phase 4: "An invited teacher can log into the panel."

    The end-to-end happy path for the NEW-USER branch: no account exists, so accept
    creates one, marks it verified (the invitation email IS the proof of inbox
    control), and signs them straight in.
    """
    await _invite(tenant, "newteacher@test.example")
    token = latest_token(mailbox)

    tenant.client.cookies.clear()
    preview = await tenant.client.get(f"{API}/invitations/verify", params={"token": token})
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["email"] == "newteacher@test.example"
    assert body["requires_signup"] is True
    assert body["role_name"] == "Teacher"

    # Spec §7.2: "Do not leak org internals to an unauthenticated token holder."
    # Everything returned above already appeared in the recipient's own email.
    assert "organization_id" not in body
    assert "permissions" not in body

    accepted = await tenant.client.post(
        f"{API}/invitations/accept",
        json={"token": token, "full_name": "New Teacher", "password": STRONG_PASSWORD},
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["role_code"] == "teacher"
    assert accepted.json()["created_account"] is True

    tenant.client.cookies.clear()
    login = await tenant.client.post(
        f"{API}/auth/login",
        json={"email": "newteacher@test.example", "password": STRONG_PASSWORD},
        headers={"X-Token-Transport": "body"},
    )
    assert login.status_code == 200, login.text
    assert login.json()["select_required"] is False


async def test_same_token_twice_is_410(tenant: Tenant, mailbox: list[Any]) -> None:
    """Spec §12: "Same token used twice -> second attempt 410."

    THE ATTACK THIS STOPS: one leaked or forwarded invite link creating unlimited
    memberships. Single-use is what bounds the damage of a link that escaped.

    410 rather than 404 or 400 because it says precisely what happened: the resource
    existed and is now permanently gone, so the client can offer "request a new
    invitation" instead of a dead end.
    """
    await _invite(tenant, "once@test.example")
    token = latest_token(mailbox)

    tenant.client.cookies.clear()
    first = await tenant.client.post(
        f"{API}/invitations/accept",
        json={"token": token, "full_name": "Once", "password": STRONG_PASSWORD},
    )
    assert first.status_code == 200, first.text

    tenant.client.cookies.clear()
    second = await tenant.client.post(
        f"{API}/invitations/accept",
        json={"token": token, "full_name": "Twice", "password": STRONG_PASSWORD},
    )
    assert second.status_code == 410, second.text
    assert second.json()["code"] == "INVITATION_GONE"


async def test_expired_token_is_410(
    tenant: Tenant,
    mailbox: list[Any],
    admin_sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Spec §12: "Expired token -> 410."

    THE ATTACK THIS STOPS: an invite sitting in a former employee's mailbox, or in
    an archive, working indefinitely. Expiry bounds the window in which a leaked
    link is useful.

    Expiry is forced by writing the row directly rather than by waiting seven days.
    The superuser session is the right tool for that: it is test setup, not a code
    path the application has.
    """
    invitation_id, _ = await _invite(tenant, "stale@test.example")
    token = latest_token(mailbox)

    async with admin_sessionmaker() as session:
        await session.execute(
            text("UPDATE invitations SET expires_at = :past WHERE id = :id"),
            {"past": datetime.now(UTC) - timedelta(days=1), "id": invitation_id},
        )
        await session.commit()

    tenant.client.cookies.clear()
    response = await tenant.client.post(
        f"{API}/invitations/accept",
        json={"token": token, "full_name": "Stale", "password": STRONG_PASSWORD},
    )
    assert response.status_code == 410, response.text

    # And the public preview refuses it too, so the UI can say so before the user
    # fills in a signup form they cannot submit.
    preview = await tenant.client.get(f"{API}/invitations/verify", params={"token": token})
    assert preview.status_code == 410


async def test_logged_in_user_with_a_different_email_is_403(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    """Spec §12: "Logged-in user with a different email accepting -> 403."

    =========================================================================
    THIS IS A REAL ATTACK, AND ONE COMPARISON BLOCKS IT
    =========================================================================
        An invitation is forwarded -- deliberately or by an auto-forward rule -- to
        someone who was not invited. They are already signed in to the platform
        through another school. Without the email check, accepting would attach THEIR
        account to an organization that never invited them, and the invited person
        would never know.

        Spec §7.2 calls it out precisely because it is trivially blocked and
        trivially forgotten.
    """
    await _invite(tenant, "intended@test.example")
    token = latest_token(mailbox)

    # The owner is signed in as someone else entirely and tries to accept.
    tenant.client.cookies.clear()
    response = await tenant.client.post(
        f"{API}/invitations/accept",
        json={"token": token},
        headers=tenant.headers(),
    )

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "INVITATION_EMAIL_MISMATCH"


async def test_invitation_exceeding_staff_limit_is_402_before_the_email_is_sent(
    make_tenant: Any, mailbox: list[Any]
) -> None:
    """Spec §12: "Invite that exceeds `max_staff` -> 402 before the email is sent."

    ORDER MATTERS AS MUCH AS THE STATUS CODE. If the email went out first, an invitee
    would receive a link they could never redeem -- and would contact the school
    about it. The entitlement check runs at step 3 of spec §7.1, before step 6 sends
    anything.

    The free plan allows 3 staff; the owner already occupies one seat.
    """
    tenant: Tenant = await make_tenant(plan=None)  # stay on free

    roles = await tenant.get(f"{API}/schools/{tenant.school_id}/roles")
    teacher = next(r for r in roles.json() if r["code"] == "teacher")

    accepted_count = 0
    rejected = None
    for i in range(6):
        response = await tenant.post(
            f"{API}/schools/{tenant.school_id}/invitations",
            json={
                "email": f"staff{i}@test.example",
                "full_name": f"Staff {i}",
                "role_id": teacher["id"],
            },
        )
        if response.status_code == 201:
            accepted_count += 1
            continue
        rejected = response
        break

    assert rejected is not None, "the free plan's staff limit was never enforced"
    assert rejected.status_code == 402, rejected.text
    body = rejected.json()
    assert body["code"] == "plan_limit_exceeded"
    assert body["meta"]["limit"] == "max_staff"
    assert body["meta"]["upgrade_url"] == "/billing/plans"

    # No email was sent for the rejected invitation: the mailbox holds exactly the
    # verification mail plus one per ACCEPTED invitation.
    assert len(mailbox) == accepted_count + 1


async def test_resend_rotates_the_token_and_kills_the_old_one(
    tenant: Tenant, mailbox: list[Any]
) -> None:
    """Resend issues a NEW token; the previous link dies immediately.

    It cannot re-send the original -- only the digest was stored, so the raw token is
    unrecoverable by design. Rotating is also the safer behaviour: if the first email
    went to a mistyped or compromised address, this kills that link.
    """
    invitation_id, _ = await _invite(tenant, "resend@test.example")
    original = latest_token(mailbox)

    resent = await tenant.post(
        f"{API}/schools/{tenant.school_id}/invitations/{invitation_id}/resend"
    )
    assert resent.status_code == 200, resent.text
    assert resent.json()["resent_count"] == 1

    rotated = latest_token(mailbox)
    assert rotated != original, "resend reused the old token"

    tenant.client.cookies.clear()
    old = await tenant.client.get(f"{API}/invitations/verify", params={"token": original})
    assert old.status_code == 404, "the superseded token still works"

    new = await tenant.client.get(f"{API}/invitations/verify", params={"token": rotated})
    assert new.status_code == 200


async def test_revoking_returns_the_staff_seat(tenant: Tenant, mailbox: list[Any]) -> None:
    """A revoked invitation dies immediately and gives its reserved seat back.

    The seat is consumed when the invitation is SENT, so that a school cannot invite
    more people than it can employ. Without releasing it on revoke, an organization
    that sent and cancelled ten invitations would have permanently lost ten seats it
    never used.
    """
    before = (await tenant.get(f"{API}/org/usage")).json()
    staff_before = next(i for i in before["items"] if i["key"] == "max_staff")["current"]

    invitation_id, _ = await _invite(tenant, "revoked@test.example")
    token = latest_token(mailbox)

    during = (await tenant.get(f"{API}/org/usage")).json()
    staff_during = next(i for i in during["items"] if i["key"] == "max_staff")["current"]
    assert staff_during == staff_before + 1, "sending an invitation did not reserve a seat"

    revoked = await tenant.delete(f"{API}/schools/{tenant.school_id}/invitations/{invitation_id}")
    assert revoked.status_code == 200, revoked.text
    assert revoked.json()["status"] == "revoked"

    after = (await tenant.get(f"{API}/org/usage")).json()
    staff_after = next(i for i in after["items"] if i["key"] == "max_staff")["current"]
    assert staff_after == staff_before, "revoking did not return the seat"

    # The token is dead the moment it is revoked.
    tenant.client.cookies.clear()
    dead = await tenant.client.post(
        f"{API}/invitations/accept",
        json={"token": token, "full_name": "Revoked", "password": STRONG_PASSWORD},
    )
    assert dead.status_code == 410


async def test_inviting_an_existing_member_is_409(tenant: Tenant, mailbox: list[Any]) -> None:
    """Spec §7.1 step 4: reject if an active membership already exists."""
    await _invite(tenant, "dupe@test.example")
    token = latest_token(mailbox)

    tenant.client.cookies.clear()
    accepted = await tenant.client.post(
        f"{API}/invitations/accept",
        json={"token": token, "full_name": "Dupe", "password": STRONG_PASSWORD},
    )
    assert accepted.status_code == 200, accepted.text
    tenant.client.cookies.clear()

    roles = await tenant.get(f"{API}/schools/{tenant.school_id}/roles")
    teacher = next(r for r in roles.json() if r["code"] == "teacher")
    again = await tenant.post(
        f"{API}/schools/{tenant.school_id}/invitations",
        json={"email": "dupe@test.example", "full_name": "Dupe", "role_id": teacher["id"]},
    )
    assert again.status_code == 409, again.text
    assert again.json()["code"] == "ALREADY_MEMBER"


async def test_unknown_token_does_not_confirm_or_deny(tenant: Tenant) -> None:
    """A garbage token gets the same shape of answer as a real-but-invalid one.

    An endpoint that distinguished "no such token" from "expired token" would let an
    attacker brute-forcing tokens know when they had found a real one -- even if they
    could not use it.
    """
    tenant.client.cookies.clear()
    response = await tenant.client.get(
        f"{API}/invitations/verify",
        params={"token": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
    )
    assert response.status_code == 404
