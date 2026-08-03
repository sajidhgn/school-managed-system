"""Plan management from the operator console.

Plan editing is the most dangerous thing in the console, and dangerous in a way that
is invisible at the moment of the mistake: lowering a limit succeeds instantly,
changes one JSONB value, and pushes customers into `over_limit` where their next
create is refused. Nobody finds out until support tickets arrive.

These cover the two things that make it safe to expose — the impact preview, and the
guard on the one plan that must never be disabled.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.conftest import API, STRONG_PASSWORD, Tenant


async def _platform_session(
    db_client: AsyncClient, admin_sessionmaker: async_sessionmaker[AsyncSession]
) -> dict[str, str]:
    """Seed an operator and return a bearer header for them."""
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

    login = await db_client.post(
        f"{API}/platform/auth/login",
        json={"email": "ops@platform.example", "password": STRONG_PASSWORD},
        headers={"X-Token-Transport": "body"},
    )
    assert login.status_code == 200, login.text
    return {"Authorization": f"Bearer {login.headers['X-Access-Token']}"}


async def _plan(db_client: AsyncClient, headers: dict[str, str], code: str) -> dict[str, Any]:
    plans = await db_client.get(f"{API}/platform/plans", headers=headers)
    assert plans.status_code == 200, plans.text
    return next(p for p in plans.json() if p["code"] == code)


async def test_impact_reports_who_a_lower_limit_would_break(
    db_client: AsyncClient,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    make_tenant: Callable[..., Any],
) -> None:
    """The preview names the organizations a limit reduction would push over.

    =========================================================================
    THIS IS THE WHOLE POINT OF THE ENDPOINT
    =========================================================================
        An operator lowering `max_schools` sees "this will block new records for
        Growth Trust" BEFORE saving, rather than discovering it from a support
        ticket days later. A count alone would not be enough — "3 organizations
        affected" is a number people click past; naming them is not.
    """
    tenant: Tenant = await make_tenant(
        name="Growth Trust", email="growth@test.example", plan="growth"
    )
    # Two schools on a plan that allows ten.
    second = await tenant.post(f"{API}/schools", json={"name": "Second", "code": "SECOND"})
    assert second.status_code == 201, second.text

    headers = await _platform_session(db_client, admin_sessionmaker)
    growth = await _plan(db_client, headers, "growth")

    # A limit BELOW their current usage.
    response = await db_client.post(
        f"{API}/platform/plans/{growth['id']}/impact",
        json={"limits": {"max_schools": 1}},
        headers=headers,
    )
    assert response.status_code == 200, response.text

    body = response.json()
    assert body["subscriber_count"] >= 1
    names = {org["name"] for org in body["would_exceed"]}
    assert "Growth Trust" in names, body

    affected = next(o for o in body["would_exceed"] if o["name"] == "Growth Trust")
    breach = next(b for b in affected["breaches"] if b["key"] == "max_schools")
    assert breach["current"] == 2
    assert breach["allowed"] == 1


async def test_impact_is_empty_when_the_change_is_harmless(
    db_client: AsyncClient,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    make_tenant: Callable[..., Any],
) -> None:
    """Raising a limit, or lowering one nobody has reached, breaks nobody.

    The preview must not cry wolf. An operator who sees a scary confirmation on every
    edit stops reading it, and then misses the one that mattered.
    """
    await make_tenant(name="Growth Trust", email="growth@test.example", plan="growth")

    headers = await _platform_session(db_client, admin_sessionmaker)
    growth = await _plan(db_client, headers, "growth")

    raised = await db_client.post(
        f"{API}/platform/plans/{growth['id']}/impact",
        json={"limits": {"max_schools": 50}},
        headers=headers,
    )
    assert raised.status_code == 200
    assert raised.json()["would_exceed"] == []

    # Still above the one school they actually have.
    lowered_but_safe = await db_client.post(
        f"{API}/platform/plans/{growth['id']}/impact",
        json={"limits": {"max_schools": 5}},
        headers=headers,
    )
    assert lowered_but_safe.json()["would_exceed"] == []


async def test_impact_merges_over_current_limits(
    db_client: AsyncClient,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    make_tenant: Callable[..., Any],
) -> None:
    """A partial payload is merged over the plan's existing limits, as PATCH does.

    Without the merge, sending one field would be evaluated as a plan whose other
    five limits are absent — and the preview would either crash or report a fantasy.
    """
    await make_tenant(name="Growth Trust", email="growth@test.example", plan="growth")

    headers = await _platform_session(db_client, admin_sessionmaker)
    growth = await _plan(db_client, headers, "growth")

    response = await db_client.post(
        f"{API}/platform/plans/{growth['id']}/impact",
        json={"limits": {"max_students": 1}},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    # `max_schools` is untouched and still generous, so the only breach reported is
    # the one actually being proposed.
    for org in response.json()["would_exceed"]:
        assert {b["key"] for b in org["breaches"]} == {"max_students"} or not org["breaches"]


async def test_impact_ignores_unlimited(
    db_client: AsyncClient,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    make_tenant: Callable[..., Any],
) -> None:
    """`-1` is unlimited and can never be breached."""
    await make_tenant(name="Growth Trust", email="growth@test.example", plan="growth")

    headers = await _platform_session(db_client, admin_sessionmaker)
    growth = await _plan(db_client, headers, "growth")

    response = await db_client.post(
        f"{API}/platform/plans/{growth['id']}/impact",
        json={"limits": {"max_schools": -1, "max_students": -1, "max_staff": -1}},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["would_exceed"] == []


async def test_free_plan_cannot_be_retired(
    db_client: AsyncClient, admin_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """Retiring `free` would stop every future signup from completing.

    =========================================================================
    THE FAILURE THIS PREVENTS IS SILENT AND DELAYED
    =========================================================================
        `ensure_free_subscription` runs on email verification and looks up
        `code = 'free' AND is_active = true`. Deactivate that row and every new
        organization is stranded between "account created" and "can sign in" — with
        no existing customer to complain and nothing in any dashboard to show it.

        Refusing outright rather than warning: there is no legitimate reason to
        retire the plan every organization starts on.
    """
    headers = await _platform_session(db_client, admin_sessionmaker)
    free = await _plan(db_client, headers, "free")

    response = await db_client.delete(f"{API}/platform/plans/{free['id']}", headers=headers)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "FREE_PLAN_PROTECTED"

    # And it is still usable.
    after = await _plan(db_client, headers, "free")
    assert after["is_active"] is True


async def test_free_plan_cannot_be_deactivated_through_patch(
    db_client: AsyncClient, admin_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """The same catastrophe reached by a different route is guarded too.

    A guard on `DELETE` alone would be trivially bypassed by `PATCH {is_active:
    false}` — same effect, no warning. Both paths check.
    """
    headers = await _platform_session(db_client, admin_sessionmaker)
    free = await _plan(db_client, headers, "free")

    response = await db_client.patch(
        f"{API}/platform/plans/{free['id']}",
        json={"is_active": False},
        headers=headers,
    )
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "FREE_PLAN_PROTECTED"


async def test_free_plan_can_still_be_renamed_and_repriced(
    db_client: AsyncClient, admin_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """The guard blocks disabling, not editing. Over-blocking would be its own bug."""
    headers = await _platform_session(db_client, admin_sessionmaker)
    free = await _plan(db_client, headers, "free")

    response = await db_client.patch(
        f"{API}/platform/plans/{free['id']}",
        json={"name": "Starter (Free)", "marketing_tagline": "Try it out"},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Starter (Free)"


async def test_plan_limits_must_stay_complete(
    db_client: AsyncClient, admin_sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    """Spec §6.1: every limit key must exist on every plan.

    A missing key with a `.get(key, 0)` fallback silently blocks a paying customer;
    with `.get(key, -1)` it silently gives away unlimited usage. Refusing to save a
    malformed plan is cheaper than either.
    """
    headers = await _platform_session(db_client, admin_sessionmaker)

    response = await db_client.post(
        f"{API}/platform/plans",
        json={
            "code": "broken",
            "name": "Broken",
            "limits": {"max_schools": 1},  # five keys missing
            "features": {},
            "currency": "USD",
        },
        headers=headers,
    )
    assert response.status_code == 422, response.text
    body = response.json()
    assert body["code"] == "INCOMPLETE_PLAN"
    assert "max_students" in body["meta"]["missing_limits"]


async def test_creating_a_plan_and_assigning_it_manually(
    db_client: AsyncClient,
    admin_sessionmaker: async_sessionmaker[AsyncSession],
    make_tenant: Callable[..., Any],
) -> None:
    """A hidden plan is created by the operator and assigned to one organization.

    This is the enterprise path: `is_public = false` keeps it off the pricing page
    and out of self-service, so the ONLY way onto it is a manual override.
    """
    tenant: Tenant = await make_tenant(name="Big Trust", email="big@test.example")
    headers = await _platform_session(db_client, admin_sessionmaker)

    created = await db_client.post(
        f"{API}/platform/plans",
        json={
            "code": "custom_deal",
            "name": "Custom Deal",
            "price_monthly": None,
            "currency": "USD",
            "trial_days": 0,
            "limits": {
                "max_schools": -1,
                "max_students": -1,
                "max_staff": -1,
                "max_custom_roles": -1,
                "storage_mb": -1,
                "audit_retention_days": 730,
            },
            "features": {
                "custom_branding": True,
                "api_access": True,
                "priority_support": True,
                "sso": True,
                "advanced_reports": True,
            },
            "is_public": False,
            "is_active": True,
            "sort_order": 50,
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["is_public"] is False

    # Not offered to customers.
    public = await db_client.get(f"{API}/public/plans")
    assert "custom_deal" not in {p["code"] for p in public.json()}

    # Nor self-selectable.
    self_service = await tenant.post(
        f"{API}/billing/change-plan",
        json={"plan_code": "custom_deal", "billing_cycle": "monthly"},
    )
    assert self_service.status_code == 422
    assert self_service.json()["code"] == "PLAN_NOT_SELF_SERVICE"

    # But the operator can assign it.
    override = await db_client.post(
        f"{API}/platform/organizations/{tenant.organization_id}/plan",
        json={"plan_code": "custom_deal"},
        headers=headers,
    )
    assert override.status_code == 200, override.text
    assert override.json()["plan_code"] == "custom_deal"
