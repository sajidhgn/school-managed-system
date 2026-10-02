"""Billing routes (spec §8 "Billing", "Public").

WHY THIS FILE EXISTS
    Three audiences reach billing through three very different doors:
      * the marketing site, unauthenticated, wanting the plan catalog
      * an organization owner, authenticated and permission-checked
      * the payment gateway, unauthenticated but signature-verified
    Keeping them in one module makes the asymmetry visible instead of accidental.

RESPONSIBILITY
    Route definitions and response assembly.

INTERACTIONS
    `modules/billing/service.py` for every state change; `api/deps.py::require` for
    the permission gates.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.api.deps import (
    AuthContext,
    DbSession,
    PublicDbSession,
    SettingsDep,
    require,
)
from app.core.exceptions import NotFoundError, ValidationError
from app.modules.billing.gateways import GatewayError, PaymentGateway, build_gateway
from app.modules.billing.idempotency import BillingIdempotencyService
from app.modules.billing.invoice_pdf import render_invoice_pdf
from app.modules.billing.models import Invoice, Subscription
from app.modules.billing.schemas import (
    CancelRequest,
    InvoiceRead,
    PlanPublic,
    SubscribeRequest,
    SubscriptionRead,
)
from app.modules.billing.service import BillingService, WebhookService
from app.modules.platform_admin.models import Plan
from app.modules.tenancy.models import Organization

# Three routers, mounted under different prefixes by the v1 aggregator. Separate
# because their auth posture differs: `public_router` and `webhook_router` are
# deliberately unauthenticated, and keeping them apart from the guarded routes means
# a new endpoint cannot land in an unauthenticated group by accident.
router = APIRouter()
public_router = APIRouter()
webhook_router = APIRouter()


def get_gateway(settings: SettingsDep) -> PaymentGateway:
    return build_gateway(settings)


GatewayDep = Annotated[PaymentGateway, Depends(get_gateway)]
IdempotencyKey = Annotated[
    str | None,
    Header(alias="Idempotency-Key", min_length=1, max_length=128),
]


# ---------------------------------------------------------------------------
# Public catalog
# ---------------------------------------------------------------------------


@public_router.get("/plans", response_model=list[PlanPublic])
async def list_public_plans(session: PublicDbSession, response: Response) -> list[Plan]:
    """The pricing page's data source (spec §8 "Public"). No authentication.

    Returns only `is_public AND is_active` plans, so the hidden `enterprise` tier
    stays invisible to anyone who has not negotiated it.

    Cached for 5 minutes at the edge: the catalog changes a few times a year and this
    endpoint is hit by every visitor to the marketing site.
    """
    response.headers["Cache-Control"] = "public, max-age=300"

    rows = (
        (
            await session.execute(
                select(Plan)
                .where(Plan.is_public.is_(True), Plan.is_active.is_(True))
                .order_by(Plan.sort_order, Plan.price_monthly)
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


# ---------------------------------------------------------------------------
# Subscription
# ---------------------------------------------------------------------------


def _subscription_read(subscription: Subscription, plan: Plan) -> SubscriptionRead:
    """Assemble the response from two rows.

    Not `model_validate(subscription)`: the plan's code and name live on a different
    table, and the frontend needs them together. Building it explicitly keeps that
    join visible rather than hiding it behind a lazy-loaded relationship that would
    fire a second query per row.
    """
    return SubscriptionRead(
        id=subscription.id,
        plan_code=plan.code,
        plan_name=plan.name,
        status=subscription.status.value,
        billing_cycle=subscription.billing_cycle.value,
        trial_ends_at=subscription.trial_ends_at,
        current_period_start=subscription.current_period_start,
        current_period_end=subscription.current_period_end,
        cancel_at_period_end=subscription.cancel_at_period_end,
        cancelled_at=subscription.cancelled_at,
    )


@router.get("/subscription", response_model=SubscriptionRead)
async def get_subscription(
    session: DbSession,
    gateway: GatewayDep,
    ctx: Annotated[AuthContext, Depends(require("billing:read"))],
) -> SubscriptionRead:
    subscription, plan = await BillingService(session, gateway).get_subscription(
        ctx.organization_id
    )
    return _subscription_read(subscription, plan)


@router.post("/subscribe", response_model=SubscriptionRead)
async def subscribe(
    payload: SubscribeRequest,
    session: DbSession,
    gateway: GatewayDep,
    ctx: Annotated[AuthContext, Depends(require("billing:manage", allow_read_only=True))],
    idempotency_key: IdempotencyKey = None,
) -> SubscriptionRead:
    """Move onto a paid plan.

    Shares an implementation with `change-plan`: from the system's point of view
    "subscribe" and "change plan" are the same transition, since every organization
    already holds a free-plan subscription row. Kept as two endpoints because they
    are two different intentions in the UI, and the audit trail reads better for it.
    """
    request_payload = payload.model_dump(mode="json")
    idempotency = BillingIdempotencyService(session)
    replay = await idempotency.begin(
        organization_id=ctx.organization_id,
        operation="billing.subscribe",
        key=idempotency_key,
        request_payload=request_payload,
    )
    if replay is not None:
        return SubscriptionRead.model_validate(replay)

    service = BillingService(session, gateway)
    subscription = await service.change_plan(
        organization_id=ctx.organization_id,
        plan_code=payload.plan_code,
        billing_cycle=payload.billing_cycle,
        actor_user_id=ctx.user_id,
    )
    _, plan = await service.get_subscription(ctx.organization_id)
    result = _subscription_read(subscription, plan)
    await idempotency.complete(
        organization_id=ctx.organization_id,
        operation="billing.subscribe",
        key=idempotency_key,
        request_payload=request_payload,
        response_payload=result.model_dump(mode="json"),
    )
    return result


@router.post("/change-plan", response_model=SubscriptionRead)
async def change_plan(
    payload: SubscribeRequest,
    session: DbSession,
    gateway: GatewayDep,
    ctx: Annotated[AuthContext, Depends(require("billing:manage", allow_read_only=True))],
    idempotency_key: IdempotencyKey = None,
) -> SubscriptionRead:
    """Upgrade or downgrade. A downgrade below current usage never deletes data."""
    request_payload = payload.model_dump(mode="json")
    idempotency = BillingIdempotencyService(session)
    replay = await idempotency.begin(
        organization_id=ctx.organization_id,
        operation="billing.change_plan",
        key=idempotency_key,
        request_payload=request_payload,
    )
    if replay is not None:
        return SubscriptionRead.model_validate(replay)

    service = BillingService(session, gateway)
    subscription = await service.change_plan(
        organization_id=ctx.organization_id,
        plan_code=payload.plan_code,
        billing_cycle=payload.billing_cycle,
        actor_user_id=ctx.user_id,
    )
    _, plan = await service.get_subscription(ctx.organization_id)
    result = _subscription_read(subscription, plan)
    await idempotency.complete(
        organization_id=ctx.organization_id,
        operation="billing.change_plan",
        key=idempotency_key,
        request_payload=request_payload,
        response_payload=result.model_dump(mode="json"),
    )
    return result


@router.post("/cancel", response_model=SubscriptionRead)
async def cancel_subscription(
    payload: CancelRequest,
    session: DbSession,
    gateway: GatewayDep,
    ctx: Annotated[AuthContext, Depends(require("billing:manage"))],
    idempotency_key: IdempotencyKey = None,
) -> SubscriptionRead:
    """Cancel at period end. Immediate cancellation is a super-admin action."""
    if not payload.at_period_end:
        raise ValidationError(
            "Immediate cancellation is not available for self-service. "
            "Your subscription will end at the close of the current period.",
            code="IMMEDIATE_CANCEL_NOT_ALLOWED",
        )

    request_payload = payload.model_dump(mode="json")
    idempotency = BillingIdempotencyService(session)
    replay = await idempotency.begin(
        organization_id=ctx.organization_id,
        operation="billing.cancel",
        key=idempotency_key,
        request_payload=request_payload,
    )
    if replay is not None:
        return SubscriptionRead.model_validate(replay)

    service = BillingService(session, gateway)
    subscription = await service.cancel(
        organization_id=ctx.organization_id,
        at_period_end=True,
        actor_user_id=ctx.user_id,
    )
    _, plan = await service.get_subscription(ctx.organization_id)
    result = _subscription_read(subscription, plan)
    await idempotency.complete(
        organization_id=ctx.organization_id,
        operation="billing.cancel",
        key=idempotency_key,
        request_payload=request_payload,
        response_payload=result.model_dump(mode="json"),
    )
    return result


@router.get("/invoices", response_model=list[InvoiceRead])
async def list_invoices(
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("invoice:read"))],
) -> list[Invoice]:
    """This organization's invoices.

    No explicit `WHERE organization_id` filter: RLS applies it at the database, and
    adding a redundant one here would suggest the filter is what provides the
    isolation. It is not -- the policy is.
    """
    rows = (
        (await session.execute(select(Invoice).order_by(Invoice.created_at.desc()).limit(200)))
        .scalars()
        .all()
    )
    return list(rows)


@router.get("/invoices/{invoice_id}/pdf")
async def download_invoice_pdf(
    invoice_id: UUID,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("invoice:read"))],
) -> StreamingResponse:
    """Generate one invoice after RLS and permission checks have resolved it."""
    invoice = await session.get(Invoice, invoice_id)
    if invoice is None:
        raise NotFoundError("Invoice not found.")
    organization = await session.get(Organization, ctx.organization_id)
    if organization is None:
        raise NotFoundError("Organization not found.")

    payload = render_invoice_pdf(invoice, organization)
    return StreamingResponse(
        iter([payload]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="invoice-{invoice.number}.pdf"',
            "Cache-Control": "private, no-store",
        },
    )


# Usage lives on the tenancy router as `GET /org/usage` (spec §8), because it
# describes the organization rather than its billing relationship -- and because it
# is readable by any member, unlike everything else in this file.


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------


@webhook_router.post("/payments/{gateway_name}", status_code=status.HTTP_200_OK)
async def receive_webhook(
    gateway_name: str,
    request: Request,
    session: PublicDbSession,
    gateway: GatewayDep,
) -> dict[str, str]:
    """Receive a gateway webhook (spec §8, §6.4).

    UNAUTHENTICATED BUT NOT UNVERIFIED. There is no session here -- the caller is a
    payment provider, not a user -- so authenticity comes entirely from the HMAC
    signature over the raw body. `verify_and_parse` fuses verification with parsing
    precisely so this handler cannot obtain an event it failed to verify.

    Reads `await request.body()` rather than a parsed model: the signature covers the
    EXACT bytes sent, and letting Pydantic parse and re-serialise would change them.
    """
    if gateway_name != gateway.name:
        # Routing mismatch, not an auth failure. Returning 200 would tell a
        # misconfigured provider everything is fine while we silently drop events.
        raise ValidationError(
            f"This deployment is configured for the '{gateway.name}' gateway.",
            code="GATEWAY_MISMATCH",
        )

    payload = await request.body()
    try:
        processed = await WebhookService(session, gateway).handle(
            payload=payload, headers=dict(request.headers)
        )
    except GatewayError as exc:
        # 400, never 500. A 5xx tells the gateway to retry, and a bad signature will
        # never become a good one -- retrying it forever accomplishes nothing.
        raise ValidationError(str(exc), code="WEBHOOK_VERIFICATION_FAILED") from exc

    # 200 for a duplicate too. The gateway's contract is "2xx means delivered", and
    # a duplicate WAS delivered -- we simply had it already. Any other status
    # provokes further retries of an event that is fully handled.
    return {"status": "processed" if processed else "duplicate"}
