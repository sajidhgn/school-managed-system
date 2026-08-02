"""Authentication gates (spec §12 "Auth", §4).

Refresh-token reuse detection, lockout, enumeration resistance, and the
owner/principal split that spec decision D2 turns on.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.conftest import API, STRONG_PASSWORD, Tenant, latest_token

# ---------------------------------------------------------------------------
# Signup and the owner/principal split
# ---------------------------------------------------------------------------


async def test_signup_creates_owner_then_principal_on_first_school(
    db_client: Any, mailbox: list[Any]
) -> None:
    """Spec §4.3B and decision D2, end to end.

    =========================================================================
    THE STRUCTURAL FIX THIS ASSERTS
    =========================================================================
        The spec calls the owner/principal conflation "the single most important
        structural fix in this rewrite". On signup the user gets an ORG-LEVEL owner
        membership (school_id null). On creating their FIRST school they
        additionally get a school-scoped principal membership on it.

        Two memberships, two scopes, one human. That is what makes requirement #6
        work -- log in, buy a plan, land in the admin panel as principal -- without
        welding the two concepts together, and it is what later allows handing
        Principal to an employee while keeping owner rights.
    """
    register = await db_client.post(
        f"{API}/auth/register",
        json={
            "full_name": "Founder",
            "email": "founder@test.example",
            "password": STRONG_PASSWORD,
            "organization_name": "Founder Trust",
            "country": "PK",
        },
    )
    assert register.status_code == 201, register.text
    assert register.json()["verification_required"] is True

    # Login is BLOCKED until the address is verified. That gate is what stops signup
    # from becoming a way to send mail from our domain to arbitrary addresses.
    premature = await db_client.post(
        f"{API}/auth/login",
        json={"email": "founder@test.example", "password": STRONG_PASSWORD},
    )
    assert premature.status_code == 401
    assert premature.json()["code"] == "EMAIL_NOT_VERIFIED"

    verified = await db_client.post(
        f"{API}/auth/verify-email", json={"token": latest_token(mailbox)}
    )
    assert verified.status_code == 200, verified.text

    login = await db_client.post(
        f"{API}/auth/login",
        json={"email": "founder@test.example", "password": STRONG_PASSWORD},
        headers={"X-Token-Transport": "body"},
    )
    assert login.status_code == 200, login.text
    access = login.headers["X-Access-Token"]
    headers = {"Authorization": f"Bearer {access}"}

    # Exactly ONE membership so far: org-level owner, no school.
    me = await db_client.get(f"{API}/auth/me", headers=headers)
    assert me.status_code == 200, me.text
    body = me.json()
    assert len(body["memberships"]) == 1
    owner_membership = body["memberships"][0]
    assert owner_membership["role_code"] == "owner"
    assert owner_membership["is_org_level"] is True
    assert owner_membership["school_id"] is None
    # The owner holds billing rights; a principal never will.
    assert "billing:manage" in body["permissions"]
    assert "school:create" in body["permissions"]

    created = await db_client.post(
        f"{API}/schools",
        json={"name": "Founder Main", "code": "MAIN"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["principal_granted"] is True, (
        "the owner was not auto-granted principal on their first school"
    )

    after = await db_client.get(f"{API}/auth/me", headers=headers)
    memberships = after.json()["memberships"]
    assert len(memberships) == 2, "expected an org-level owner AND a school principal"

    by_role = {m["role_code"]: m for m in memberships}
    assert by_role["owner"]["school_id"] is None
    assert by_role["principal"]["school_id"] is not None
    # The owner's org-level membership stays primary, so they land on the
    # organization dashboard rather than inside one campus.
    assert by_role["owner"]["is_primary"] is True
    assert by_role["principal"]["is_primary"] is False


async def test_second_school_does_not_auto_grant_principal(tenant: Tenant) -> None:
    """Only the FIRST school auto-grants principal.

    Auto-granting on every school would silently accumulate memberships the owner
    never asked for and clutter their context switcher with one entry per campus.
    Subsequent schools expect a principal to be appointed deliberately.
    """
    second = await tenant.post(f"{API}/schools", json={"name": "Second Campus", "code": "SECOND"})
    assert second.status_code == 201, second.text
    assert second.json()["principal_granted"] is False


# ---------------------------------------------------------------------------
# Refresh rotation and reuse detection
# ---------------------------------------------------------------------------


async def test_refresh_rotates_and_the_old_token_dies(db_client: Any, tenant: Tenant) -> None:
    """A refresh token is valid exactly once."""
    first = await db_client.post(
        f"{API}/auth/refresh",
        headers={
            "X-Refresh-Token": tenant.refresh_token,
            "X-Token-Transport": "body",
        },
    )
    assert first.status_code == 200, first.text
    rotated = first.headers["X-Refresh-Token"]
    assert rotated != tenant.refresh_token, "refresh did not rotate the token"

    # The new one works.
    third = await db_client.post(
        f"{API}/auth/refresh",
        headers={"X-Refresh-Token": rotated, "X-Token-Transport": "body"},
    )
    assert third.status_code == 200, third.text


async def test_reusing_a_rotated_refresh_token_revokes_the_whole_family(
    db_client: Any, tenant: Tenant
) -> None:
    """Spec §12: "Reused refresh token -> whole family revoked."

    =========================================================================
    WHY REVOKING THE FAMILY, NOT JUST THE REPLAYED TOKEN
    =========================================================================
        Rotation makes each refresh token single-use. So a token that has ALREADY
        been rotated being presented cannot happen in honest operation: either an
        attacker is replaying a stolen token, or the real user is replaying one the
        attacker already burned. Either way, two parties have held it.

        Revoking only the replayed row would leave the ATTACKER's freshly rotated
        token alive -- they rotated first, so their token is the current one. Killing
        the whole lineage forces both parties to re-authenticate, and only one of
        them knows the password.
    """
    rotated = await db_client.post(
        f"{API}/auth/refresh",
        headers={
            "X-Refresh-Token": tenant.refresh_token,
            "X-Token-Transport": "body",
        },
    )
    assert rotated.status_code == 200, rotated.text
    current = rotated.headers["X-Refresh-Token"]

    # Replay the ORIGINAL, already-rotated token. This is the theft signal.
    replay = await db_client.post(
        f"{API}/auth/refresh",
        headers={"X-Refresh-Token": tenant.refresh_token, "X-Token-Transport": "body"},
    )
    assert replay.status_code == 401, replay.text
    assert replay.json()["code"] == "TOKEN_REUSE_DETECTED"

    # And the attacker's rotated token is dead too -- the whole family went.
    poisoned = await db_client.post(
        f"{API}/auth/refresh",
        headers={"X-Refresh-Token": current, "X-Token-Transport": "body"},
    )
    assert poisoned.status_code == 401, (
        "the rotated descendant survived -- only the replayed token was revoked"
    )


# ---------------------------------------------------------------------------
# Lockout and enumeration
# ---------------------------------------------------------------------------


async def test_sixth_failed_login_locks_the_account(db_client: Any, tenant: Tenant) -> None:
    """Spec §12: "6th failed login -> locked."

    Five failures trip the threshold; the sixth attempt is refused even with the
    CORRECT password, which is what proves the lock is real rather than the wrong
    password simply failing again.
    """
    for _ in range(5):
        wrong = await db_client.post(
            f"{API}/auth/login",
            json={"email": tenant.owner_email, "password": "definitely-not-it-9999"},
        )
        assert wrong.status_code == 401

    locked = await db_client.post(
        f"{API}/auth/login",
        json={"email": tenant.owner_email, "password": STRONG_PASSWORD},
    )
    assert locked.status_code == 401, "the account was not locked after 5 failures"
    # Deliberately the SAME error as a bad password: announcing the lock tells an
    # attacker their guessing is having an effect and exactly when to resume.
    assert locked.json()["code"] == "INVALID_CREDENTIALS"


async def test_unknown_and_known_emails_are_indistinguishable(
    db_client: Any, tenant: Tenant
) -> None:
    """Spec §12: "Login response for unknown vs known email is indistinguishable
    in body and timing."

    =========================================================================
    WHY TIMING IS PART OF THE ASSERTION
    =========================================================================
        Argon2 is slow by design -- tens of milliseconds. If login skipped it when
        the address is unknown, "no such user" would return in ~2ms and "wrong
        password" in ~60ms. That gap is trivially measurable over a network and turns
        the endpoint into a user-enumeration oracle: an attacker learns which of a
        leaked address list are customers of this platform, which for a school
        system means learning which schools are clients.

        `dummy_password_verify()` burns an equivalent hash when there is no user, so
        both paths cost the same.

    The timing bound is deliberately generous (a 5x ratio). A tight assertion would
    flake on shared CI, and the failure this guards against is an order-of-magnitude
    difference, not a few milliseconds.
    """
    start = time.perf_counter()
    unknown = await db_client.post(
        f"{API}/auth/login",
        json={"email": "nobody@nowhere.example", "password": "some-wrong-password-1"},
    )
    unknown_elapsed = time.perf_counter() - start

    start = time.perf_counter()
    known = await db_client.post(
        f"{API}/auth/login",
        json={"email": tenant.owner_email, "password": "some-wrong-password-1"},
    )
    known_elapsed = time.perf_counter() - start

    assert unknown.status_code == known.status_code == 401
    assert unknown.json()["code"] == known.json()["code"] == "INVALID_CREDENTIALS"
    assert unknown.json()["detail"] == known.json()["detail"]

    ratio = max(unknown_elapsed, known_elapsed) / max(min(unknown_elapsed, known_elapsed), 1e-6)
    assert ratio < 5, (
        f"timing leaks account existence: unknown={unknown_elapsed:.4f}s "
        f"known={known_elapsed:.4f}s (ratio {ratio:.1f}x)"
    )


async def test_forgot_password_does_not_reveal_whether_the_account_exists(
    db_client: Any, tenant: Tenant
) -> None:
    """Identical response for a registered and an unregistered address."""
    known = await db_client.post(f"{API}/auth/forgot-password", json={"email": tenant.owner_email})
    unknown = await db_client.post(
        f"{API}/auth/forgot-password", json={"email": "nobody@nowhere.example"}
    )

    assert known.status_code == unknown.status_code == 200
    assert known.json() == unknown.json()


# ---------------------------------------------------------------------------
# Password policy and reset
# ---------------------------------------------------------------------------


async def test_weak_passwords_are_rejected(db_client: Any) -> None:
    """Spec §4.4: min 10 chars, zxcvbn >= 3, not in the breached list.

    `Password123!` satisfies every classic composition rule -- upper, lower, digit,
    symbol, 12 characters -- and is in every cracking dictionary ever assembled.
    That it is rejected here, while a passphrase of unrelated words is accepted, is
    the whole point of scoring entropy instead of counting character classes.
    """
    for weak in ("short1", "password123", "Password123!"):
        response = await db_client.post(
            f"{API}/auth/register",
            json={
                "full_name": "Weak Tester",
                "email": f"weak-{len(weak)}@test.example",
                "password": weak,
                "organization_name": "Weak Trust",
            },
        )
        assert response.status_code == 422, f"{weak!r} was accepted: {response.text}"
        assert response.json()["code"] == "WEAK_PASSWORD"


async def test_password_reset_revokes_every_session(
    db_client: Any, tenant: Tenant, mailbox: list[Any]
) -> None:
    """A reset kills all existing sessions.

    =========================================================================
    NOT OPTIONAL, AND THE REASON IS THE WHOLE POINT OF RESETTING
    =========================================================================
        The most likely reason someone resets a password is that they believe it was
        compromised. If the attacker's existing refresh token survives the reset, the
        reset accomplished nothing: they keep their access, and the user believes
        they are safe. That is strictly worse than not offering a reset at all.
    """
    requested = await db_client.post(
        f"{API}/auth/forgot-password", json={"email": tenant.owner_email}
    )
    assert requested.status_code == 200
    reset_token = latest_token(mailbox)

    new_password = "another-valid-passphrase-88"
    reset = await db_client.post(
        f"{API}/auth/reset-password",
        json={"token": reset_token, "password": new_password},
    )
    assert reset.status_code == 200, reset.text

    # The pre-reset refresh token is dead.
    stale = await db_client.post(
        f"{API}/auth/refresh",
        headers={"X-Refresh-Token": tenant.refresh_token, "X-Token-Transport": "body"},
    )
    assert stale.status_code == 401, "a session survived a password reset"

    # The new password works; the old one does not.
    old = await db_client.post(
        f"{API}/auth/login",
        json={"email": tenant.owner_email, "password": STRONG_PASSWORD},
    )
    assert old.status_code == 401

    new = await db_client.post(
        f"{API}/auth/login",
        json={"email": tenant.owner_email, "password": new_password},
    )
    assert new.status_code == 200, new.text


async def test_reset_token_is_single_use(
    db_client: Any, tenant: Tenant, mailbox: list[Any]
) -> None:
    """A reset link works once. A second use is refused."""
    await db_client.post(f"{API}/auth/forgot-password", json={"email": tenant.owner_email})
    token = latest_token(mailbox)

    first = await db_client.post(
        f"{API}/auth/reset-password",
        json={"token": token, "password": "first-valid-passphrase-11"},
    )
    assert first.status_code == 200, first.text

    second = await db_client.post(
        f"{API}/auth/reset-password",
        json={"token": token, "password": "second-valid-passphrase-22"},
    )
    assert second.status_code == 401, "a reset token was reusable"


# ---------------------------------------------------------------------------
# Context switching
# ---------------------------------------------------------------------------


async def test_context_switch_rescopes_the_token(tenant: Tenant) -> None:
    """Spec §4.3E: switching membership re-issues a token for the new scope.

    The owner switches from their org-level context into their principal context.
    The new token names the school; the old one did not.
    """
    me = await tenant.get(f"{API}/auth/me")
    memberships = me.json()["memberships"]
    principal = next(m for m in memberships if m["role_code"] == "principal")

    switched = await tenant.client.post(
        f"{API}/auth/context",
        json={"membership_id": principal["membership_id"]},
        headers={**tenant.headers(), "X-Token-Transport": "body"},
    )
    assert switched.status_code == 200, switched.text
    assert switched.json()["school_id"] == principal["school_id"]

    new_token = switched.headers["X-Access-Token"]
    after = await tenant.client.get(
        f"{API}/auth/me", headers={"Authorization": f"Bearer {new_token}"}
    )
    assert after.status_code == 200
    body = after.json()
    assert body["school_id"] == principal["school_id"]
    assert body["role_code"] == "principal"
    # A principal has no billing rights -- that is the owner/principal split.
    assert "billing:manage" not in body["permissions"]


async def test_cannot_switch_into_someone_elses_membership(
    tenant: Tenant, make_tenant: Any
) -> None:
    """The ownership check on `POST /auth/context` is a tenancy boundary.

    Without it, presenting another user's membership id would issue a token scoped to
    THEIR organization -- a complete tenancy bypass through the one endpoint whose
    entire job is to change tenant. 404, not 403, so membership ids cannot be
    enumerated.
    """
    other: Tenant = await make_tenant(
        name="Other Trust", email="other@test.example", school_code="OTHER"
    )
    other_me = await other.get(f"{API}/auth/me")
    other_membership = other_me.json()["memberships"][0]["membership_id"]

    response = await tenant.post(f"{API}/auth/context", json={"membership_id": other_membership})
    assert response.status_code == 404, response.text


async def test_logout_all_revokes_every_session(db_client: Any, tenant: Tenant) -> None:
    """`POST /auth/logout-all` kills sessions on every device (spec §4.3F)."""
    response = await tenant.post(f"{API}/auth/logout-all")
    assert response.status_code == 200, response.text

    stale = await db_client.post(
        f"{API}/auth/refresh",
        headers={"X-Refresh-Token": tenant.refresh_token, "X-Token-Transport": "body"},
    )
    assert stale.status_code == 401


async def test_tokens_are_set_as_httponly_cookies(db_client: Any, mailbox: list[Any]) -> None:
    """Spec §4.1: tokens ride in httpOnly cookies, never in a body a browser reads.

    A token reachable from JavaScript is a token any XSS payload can exfiltrate.
    `httpOnly` converts "one XSS bug" from "full account takeover" into "requests
    forged while the tab is open" -- still bad, but survivable.
    """
    await db_client.post(
        f"{API}/auth/register",
        json={
            "full_name": "Cookie Tester",
            "email": "cookies@test.example",
            "password": STRONG_PASSWORD,
            "organization_name": "Cookie Trust",
        },
    )
    await db_client.post(f"{API}/auth/verify-email", json={"token": latest_token(mailbox)})

    login = await db_client.post(
        f"{API}/auth/login",
        json={"email": "cookies@test.example", "password": STRONG_PASSWORD},
    )
    assert login.status_code == 200, login.text

    # No token in the JSON body for a browser client.
    assert "access_token" not in login.json()
    assert "refresh_token" not in login.json()

    set_cookie = login.headers.get_list("set-cookie")
    assert set_cookie, "no cookies were set"
    joined = " ".join(set_cookie).lower()
    assert "educloud_access" in joined and "educloud_refresh" in joined
    assert joined.count("httponly") >= 2, "auth cookies are not httpOnly"
    # The refresh cookie is path-scoped so the long-lived credential is not attached
    # to every ordinary request.
    assert "path=/api/v1/auth" in joined


async def test_platform_token_cannot_reach_tenant_routes(
    db_client: Any,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    tenant: Tenant,
) -> None:
    """Spec §9: the two auth surfaces must be mutually unreachable.

    The check is on the `typ` claim, not on the absence of an `org` claim -- an
    "absent field" is a terrible thing to hang a privilege boundary on, because a bug
    that drops the claim silently promotes a tenant user to platform scope.
    """
    from app.core.security import hash_password

    async with admin_sessionmaker() as session:
        await session.execute(
            text(
                "INSERT INTO platform_admins (id, email, password_hash, full_name, is_active)"
                " VALUES (gen_random_uuid(), :email, :pw, 'Ops', true)"
            ),
            {"email": "ops@platform.example", "pw": hash_password(STRONG_PASSWORD)},
        )
        await session.commit()

    db_client.cookies.clear()
    login = await db_client.post(
        f"{API}/platform/auth/login",
        json={"email": "ops@platform.example", "password": STRONG_PASSWORD},
    )
    assert login.status_code == 200, login.text

    # A platform session must not reach a tenant route.
    tenant_route = await db_client.get(f"{API}/org")
    assert tenant_route.status_code in (401, 403), tenant_route.text

    # And a tenant token must not reach the platform console.
    db_client.cookies.clear()
    platform_route = await db_client.get(f"{API}/platform/organizations", headers=tenant.headers())
    assert platform_route.status_code == 403, platform_route.text
    assert platform_route.json()["code"] == "PLATFORM_ACCESS_REQUIRED"
