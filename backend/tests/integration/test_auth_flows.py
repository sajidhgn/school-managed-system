"""End-to-end auth flows against a real PostgreSQL (app connected as `sms_app`).

Each test drives the HTTP surface exactly as a client would, and asserts on the
observable behaviour: status codes, tokens, and the emails the service would send.
"""

from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient

from tests.integration.conftest import DEFAULT_PASSWORD, SeededUser, auth_header, latest_otp


def _register_payload(email: str = "admin@springfield.edu") -> dict[str, str]:
    return {
        "school_name": "Springfield High",
        "school_email": "office@springfield.edu",
        "full_name": "Seymour Skinner",
        "email": email,
        "password": DEFAULT_PASSWORD,
    }


async def _super_admin_header() -> dict[str, str]:
    return auth_header(user_id=str(uuid4()), role="super_admin", super_admin=True)


async def test_register_creates_pending_school_and_sends_code(
    db_client: AsyncClient, mailbox: list
) -> None:
    resp = await db_client.post("/api/v1/auth/register", json=_register_payload())

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["email"] == "admin@springfield.edu"
    assert body["school_id"] and body["user_id"]
    # Exactly one verification email was dispatched, and it carries a 6-digit code.
    assert len(mailbox) == 1
    assert latest_otp(mailbox)


async def test_duplicate_email_is_conflict(db_client: AsyncClient) -> None:
    await db_client.post("/api/v1/auth/register", json=_register_payload())
    resp = await db_client.post("/api/v1/auth/register", json=_register_payload())

    assert resp.status_code == 409
    assert resp.json()["code"] == "EMAIL_TAKEN"


async def test_verify_email_activates_account(db_client: AsyncClient, mailbox: list) -> None:
    await db_client.post("/api/v1/auth/register", json=_register_payload())
    code = latest_otp(mailbox)

    resp = await db_client.post(
        "/api/v1/auth/verify-email", json={"email": "admin@springfield.edu", "code": code}
    )
    assert resp.status_code == 200, resp.text


async def test_wrong_verification_code_is_rejected(db_client: AsyncClient, mailbox: list) -> None:
    await db_client.post("/api/v1/auth/register", json=_register_payload())

    resp = await db_client.post(
        "/api/v1/auth/verify-email", json={"email": "admin@springfield.edu", "code": "000000"}
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "OTP_INVALID"


async def test_login_blocked_until_school_is_approved(
    db_client: AsyncClient, mailbox: list
) -> None:
    """A verified admin of a still-pending school cannot sign in yet."""
    await db_client.post("/api/v1/auth/register", json=_register_payload())
    await db_client.post(
        "/api/v1/auth/verify-email",
        json={"email": "admin@springfield.edu", "code": latest_otp(mailbox)},
    )

    resp = await db_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@springfield.edu", "password": DEFAULT_PASSWORD},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "SCHOOL_INACTIVE"


async def test_full_signup_approve_login_2fa_flow(db_client: AsyncClient, mailbox: list) -> None:
    """The complete happy path: register -> verify -> approve -> login -> 2FA -> /me."""
    reg = (await db_client.post("/api/v1/auth/register", json=_register_payload())).json()
    await db_client.post(
        "/api/v1/auth/verify-email",
        json={"email": "admin@springfield.edu", "code": latest_otp(mailbox)},
    )

    # Super admin approves the school.
    approve = await db_client.post(
        f"/api/v1/schools/{reg['school_id']}/approve", headers=await _super_admin_header()
    )
    assert approve.status_code == 200
    assert approve.json()["status"] == "active"

    # Admin logs in -> because admins always require 2FA, this returns a challenge.
    login = await db_client.post(
        "/api/v1/auth/login",
        json={"email": "admin@springfield.edu", "password": DEFAULT_PASSWORD},
    )
    assert login.status_code == 200
    assert login.json()["requires_2fa"] is True
    assert login.json()["tokens"] is None

    # Complete 2FA with the emailed code.
    verify = await db_client.post(
        "/api/v1/auth/login/verify-2fa",
        json={"email": "admin@springfield.edu", "code": latest_otp(mailbox)},
    )
    assert verify.status_code == 200, verify.text
    tokens = verify.json()
    assert tokens["access_token"] and tokens["refresh_token"]

    # The access token identifies the admin on /me.
    me = await db_client.get(
        "/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"}
    )
    assert me.status_code == 200
    profile = me.json()
    assert profile["email"] == "admin@springfield.edu"
    assert profile["role"] == "school_admin"
    assert profile["email_verified"] is True


async def test_teacher_login_needs_no_2fa(db_client: AsyncClient, seed_school, seed_user) -> None:
    """Teachers skip 2FA (attendance in under 10s), so login returns tokens directly."""
    school = await seed_school()
    teacher: SeededUser = await seed_user(school_id=str(school.id), email="teacher@springfield.edu")

    resp = await db_client.post(
        "/api/v1/auth/login",
        json={"email": teacher.email, "password": teacher.password},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["requires_2fa"] is False
    assert body["tokens"]["access_token"]


async def test_repeated_wrong_password_locks_account(
    db_client: AsyncClient, seed_school, seed_user
) -> None:
    school = await seed_school()
    teacher: SeededUser = await seed_user(school_id=str(school.id), email="lockme@springfield.edu")

    for _ in range(5):
        bad = await db_client.post(
            "/api/v1/auth/login", json={"email": teacher.email, "password": "wrong-password"}
        )
        assert bad.status_code == 401

    # Even the correct password is now refused: the account is locked.
    locked = await db_client.post(
        "/api/v1/auth/login", json={"email": teacher.email, "password": teacher.password}
    )
    assert locked.status_code == 401
    assert locked.json()["code"] == "ACCOUNT_LOCKED"


async def test_refresh_rotates_and_revokes_old_token(
    db_client: AsyncClient, seed_school, seed_user
) -> None:
    school = await seed_school()
    teacher: SeededUser = await seed_user(school_id=str(school.id), email="refresh@springfield.edu")

    login = (
        await db_client.post(
            "/api/v1/auth/login", json={"email": teacher.email, "password": teacher.password}
        )
    ).json()
    old_refresh = login["tokens"]["refresh_token"]

    rotated = await db_client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert rotated.status_code == 200
    assert rotated.json()["access_token"]

    # The rotated-away token can no longer be used (revoke-on-use).
    replay = await db_client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert replay.status_code == 401
    assert replay.json()["code"] == "REFRESH_INVALID"


async def test_password_reset_revokes_all_sessions(
    db_client: AsyncClient, mailbox: list, seed_school, seed_user
) -> None:
    school = await seed_school()
    teacher: SeededUser = await seed_user(school_id=str(school.id), email="reset@springfield.edu")

    login = (
        await db_client.post(
            "/api/v1/auth/login", json={"email": teacher.email, "password": teacher.password}
        )
    ).json()
    old_refresh = login["tokens"]["refresh_token"]

    # Request + perform a reset.
    await db_client.post("/api/v1/auth/forgot-password", json={"email": teacher.email})
    reset = await db_client.post(
        "/api/v1/auth/reset-password",
        json={"email": teacher.email, "code": latest_otp(mailbox), "new_password": "BrandNew123!"},
    )
    assert reset.status_code == 200

    # The pre-reset session is dead...
    replay = await db_client.post("/api/v1/auth/refresh", json={"refresh_token": old_refresh})
    assert replay.status_code == 401

    # ...and the new password works.
    relogin = await db_client.post(
        "/api/v1/auth/login", json={"email": teacher.email, "password": "BrandNew123!"}
    )
    assert relogin.status_code == 200


async def test_forgot_password_does_not_reveal_unknown_account(db_client: AsyncClient) -> None:
    """An unknown address returns the same 200 message -- no user enumeration."""
    resp = await db_client.post(
        "/api/v1/auth/forgot-password", json={"email": "ghost@absent-school.org"}
    )
    assert resp.status_code == 200


async def test_me_requires_authentication(db_client: AsyncClient) -> None:
    resp = await db_client.get("/api/v1/auth/me")
    assert resp.status_code == 401
    assert resp.json()["code"] == "TOKEN_MISSING"
