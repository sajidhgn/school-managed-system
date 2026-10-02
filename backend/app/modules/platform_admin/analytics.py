"""Platform-wide analytics for the operator dashboard.

WHY THIS FILE EXISTS
    `PlatformService.metrics()` answers "what are the totals right now". The
    dashboard needs the questions an operator actually asks on a Monday morning:
    is the platform growing, where does the money come from, who is about to churn
    and who is about to convert. That is a different read -- several grouped
    queries and two monthly series -- and it would double the size of a service
    that is otherwise about authentication and mutations.

RESPONSIBILITY
    One read-only aggregate, `platform_analytics()`, computed under the audited
    cross-tenant read context and disarmed in `finally`.

=============================================================================
MONEY IS NEVER SUMMED ACROSS CURRENCIES
=============================================================================
    Plans carry their own currency. Adding a PKR price to a USD one produces a
    number that is not wrong by a rounding error but meaningless, so MRR is
    reported per currency, and the revenue series is drawn in the currency that
    carries the most of it (`revenue_currency`). The other currencies are still
    visible in `mrr_by_currency`.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import bind_tenant
from app.modules.billing.models import (
    BillingCycle,
    OrganizationUsage,
    Payment,
    PaymentStatus,
    Subscription,
    SubscriptionStatus,
)
from app.modules.platform_admin.models import Plan
from app.modules.tenancy.models import Organization, OrganizationStatus, School

MONTHS = 12
TRIAL_HORIZON = timedelta(days=14)
LIST_SIZE = 6

# Subscriptions that are billed: a trial has not paid yet, and a cancelled or
# expired one has stopped paying.
PAYING = (SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE)

_CENT = Decimal("0.01")


def _month_keys(now: datetime) -> list[str]:
    """The last MONTHS calendar months, oldest first, as `YYYY-MM`."""
    year, month = now.year, now.month
    keys: list[str] = []
    for _ in range(MONTHS):
        keys.append(f"{year:04d}-{month:02d}")
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return keys[::-1]


def _monthly(
    subscription_cycle: BillingCycle, monthly: Decimal | None, yearly: Decimal | None
) -> Decimal:
    """One subscription's contribution to MRR. A yearly plan is one twelfth a month."""
    if subscription_cycle == BillingCycle.YEARLY and yearly:
        return Decimal(yearly) / 12
    return Decimal(monthly or 0)


async def platform_analytics(session: AsyncSession) -> dict[str, Any]:
    now = datetime.now(UTC)
    months = _month_keys(now)
    series_start = datetime(int(months[0][:4]), int(months[0][5:]), 1, tzinfo=UTC)

    await bind_tenant(session, None, platform_admin=True)
    try:
        live_org = Organization.deleted_at.is_(None)

        # --- Organizations -------------------------------------------------
        by_status = {
            (status.value if hasattr(status, "value") else str(status)): count
            for status, count in (
                await session.execute(
                    select(Organization.status, func.count())
                    .where(live_org)
                    .group_by(Organization.status)
                )
            ).all()
        }
        organizations_total = sum(by_status.values())

        new_30d = (
            await session.execute(
                select(func.count())
                .select_from(Organization)
                .where(live_org, Organization.created_at >= now - timedelta(days=30))
            )
        ).scalar_one()
        new_prev_30d = (
            await session.execute(
                select(func.count())
                .select_from(Organization)
                .where(
                    live_org,
                    Organization.created_at >= now - timedelta(days=60),
                    Organization.created_at < now - timedelta(days=30),
                )
            )
        ).scalar_one()

        month_col = func.to_char(func.date_trunc("month", Organization.created_at), "YYYY-MM")
        org_signups: dict[str, int] = {
            str(month): int(count)
            for month, count in (
                await session.execute(
                    select(month_col, func.count())
                    .where(live_org, Organization.created_at >= series_start)
                    .group_by(month_col)
                )
            ).all()
        }
        school_month = func.to_char(func.date_trunc("month", School.created_at), "YYYY-MM")
        school_signups: dict[str, int] = {
            str(month): int(count)
            for month, count in (
                await session.execute(
                    select(school_month, func.count())
                    .where(School.deleted_at.is_(None), School.created_at >= series_start)
                    .group_by(school_month)
                )
            ).all()
        }

        # --- Usage ---------------------------------------------------------
        schools_total, students_total, staff_total = (
            await session.execute(
                select(
                    func.coalesce(func.sum(OrganizationUsage.schools_count), 0),
                    func.coalesce(func.sum(OrganizationUsage.students_count), 0),
                    func.coalesce(func.sum(OrganizationUsage.staff_count), 0),
                )
                .join(Organization, Organization.id == OrganizationUsage.organization_id)
                .where(live_org)
            )
        ).one()

        # --- Subscriptions, plans and MRR ----------------------------------
        sub_rows = (
            await session.execute(
                select(Subscription, Plan)
                .join(Plan, Plan.id == Subscription.plan_id)
                .join(Organization, Organization.id == Subscription.organization_id)
                .where(live_org)
            )
        ).all()

        subscriptions_by_status: dict[str, int] = defaultdict(int)
        mrr_by_currency: dict[str, Decimal] = defaultdict(Decimal)
        plan_stats: dict[Any, dict[str, Any]] = {}
        paying_total = 0
        for subscription, plan in sub_rows:
            subscriptions_by_status[subscription.status.value] += 1
            stats = plan_stats.setdefault(
                plan.id,
                {
                    "plan_id": plan.id,
                    "code": plan.code,
                    "name": plan.name,
                    "currency": plan.currency,
                    "subscribers": 0,
                    "paying": 0,
                    "mrr": Decimal("0"),
                },
            )
            stats["subscribers"] += 1
            if subscription.status in PAYING:
                contribution = _monthly(
                    subscription.billing_cycle, plan.price_monthly, plan.price_yearly
                )
                stats["paying"] += 1
                stats["mrr"] += contribution
                mrr_by_currency[plan.currency] += contribution
                paying_total += 1

        # Every plan appears, including ones nobody is on yet -- an empty plan is
        # itself a finding on a catalog page.
        for plan in (await session.execute(select(Plan))).scalars():
            plan_stats.setdefault(
                plan.id,
                {
                    "plan_id": plan.id,
                    "code": plan.code,
                    "name": plan.name,
                    "currency": plan.currency,
                    "subscribers": 0,
                    "paying": 0,
                    "mrr": Decimal("0"),
                },
            )

        plans = sorted(plan_stats.values(), key=lambda p: (-p["subscribers"], p["name"]))
        for p in plans:
            p["mrr"] = p["mrr"].quantize(_CENT)

        # --- Payments ------------------------------------------------------
        pay_month = func.to_char(func.date_trunc("month", Payment.created_at), "YYYY-MM")
        payment_rows = (
            await session.execute(
                select(
                    pay_month,
                    Payment.currency,
                    Payment.status,
                    func.count(),
                    func.sum(Payment.amount),
                )
                .where(Payment.created_at >= series_start)
                .group_by(pay_month, Payment.currency, Payment.status)
            )
        ).all()

        collected_by_currency: dict[str, Decimal] = defaultdict(Decimal)
        for _, currency, status, _, amount in payment_rows:
            if status == PaymentStatus.SUCCEEDED:
                collected_by_currency[currency] += Decimal(amount or 0)

        # The series is drawn in ONE currency: the one carrying the most revenue,
        # falling back to the largest MRR currency, then the platform default.
        revenue_currency = (
            max(collected_by_currency, key=lambda c: collected_by_currency[c])
            if collected_by_currency
            else max(mrr_by_currency, key=lambda c: mrr_by_currency[c])
            if mrr_by_currency
            else "USD"
        )

        revenue: dict[str, dict[str, Any]] = {
            m: {"month": m, "collected": Decimal("0"), "succeeded": 0, "failed": 0} for m in months
        }
        for month, currency, status, count, amount in payment_rows:
            bucket = revenue.get(month)
            if bucket is None:
                continue
            if status == PaymentStatus.FAILED:
                bucket["failed"] += count
            elif status == PaymentStatus.SUCCEEDED and currency == revenue_currency:
                bucket["succeeded"] += count
                bucket["collected"] += Decimal(amount or 0)
        for bucket in revenue.values():
            bucket["collected"] = bucket["collected"].quantize(_CENT)

        failed_30d = (
            await session.execute(
                select(func.count())
                .select_from(Payment)
                .where(
                    Payment.status == PaymentStatus.FAILED,
                    Payment.created_at >= now - timedelta(days=30),
                )
            )
        ).scalar_one()

        # --- Watch lists ---------------------------------------------------
        trials_ending = [
            {
                "organization_id": org.id,
                "name": org.name,
                "slug": org.slug,
                "plan_name": plan.name,
                "at": subscription.trial_ends_at,
            }
            for org, subscription, plan in (
                await session.execute(
                    select(Organization, Subscription, Plan)
                    .join(Subscription, Subscription.organization_id == Organization.id)
                    .join(Plan, Plan.id == Subscription.plan_id)
                    .where(
                        live_org,
                        Subscription.status == SubscriptionStatus.TRIALING,
                        Subscription.trial_ends_at.is_not(None),
                        Subscription.trial_ends_at <= now + TRIAL_HORIZON,
                    )
                    .order_by(Subscription.trial_ends_at)
                    .limit(LIST_SIZE)
                )
            ).all()
        ]

        at_risk = [
            {
                "organization_id": org.id,
                "name": org.name,
                "slug": org.slug,
                "plan_name": plan.name if plan else None,
                "status": org.status.value,
                "at": subscription.current_period_end if subscription else None,
            }
            for org, subscription, plan in (
                await session.execute(
                    select(Organization, Subscription, Plan)
                    .outerjoin(Subscription, Subscription.organization_id == Organization.id)
                    .outerjoin(Plan, Plan.id == Subscription.plan_id)
                    .where(
                        live_org,
                        Organization.status.in_(
                            [OrganizationStatus.PAST_DUE, OrganizationStatus.OVER_LIMIT]
                        ),
                    )
                    .order_by(Organization.updated_at.desc())
                    .limit(LIST_SIZE)
                )
            ).all()
        ]

        top_organizations = [
            {
                "organization_id": org.id,
                "name": org.name,
                "slug": org.slug,
                "plan_name": plan.name if plan else None,
                "students": usage.students_count,
                "staff": usage.staff_count,
                "schools": usage.schools_count,
            }
            for org, usage, plan in (
                await session.execute(
                    select(Organization, OrganizationUsage, Plan)
                    .join(OrganizationUsage, OrganizationUsage.organization_id == Organization.id)
                    .outerjoin(Subscription, Subscription.organization_id == Organization.id)
                    .outerjoin(Plan, Plan.id == Subscription.plan_id)
                    .where(live_org)
                    .order_by(OrganizationUsage.students_count.desc(), Organization.name)
                    .limit(LIST_SIZE)
                )
            ).all()
        ]

        recent_organizations = [
            {
                "organization_id": org.id,
                "name": org.name,
                "slug": org.slug,
                "status": org.status.value,
                "plan_name": plan.name if plan else None,
                "created_at": org.created_at,
            }
            for org, plan in (
                await session.execute(
                    select(Organization, Plan)
                    .outerjoin(Subscription, Subscription.organization_id == Organization.id)
                    .outerjoin(Plan, Plan.id == Subscription.plan_id)
                    .where(live_org)
                    .order_by(Organization.created_at.desc())
                    .limit(LIST_SIZE)
                )
            ).all()
        ]

        trialing = by_status.get(OrganizationStatus.TRIALING.value, 0)
        cancelled = by_status.get(OrganizationStatus.CANCELLED.value, 0)

        return {
            "generated_at": now,
            "organizations_total": organizations_total,
            "organizations_new_30d": new_30d,
            "organizations_new_prev_30d": new_prev_30d,
            "organizations_by_status": by_status,
            "subscriptions_by_status": dict(subscriptions_by_status),
            "paying_organizations": paying_total,
            "trialing_organizations": trialing,
            "schools_total": int(schools_total),
            "students_total": int(students_total),
            "staff_total": int(staff_total),
            "mrr_by_currency": [
                {"currency": c, "mrr": v.quantize(_CENT), "arr": (v * 12).quantize(_CENT)}
                for c, v in sorted(mrr_by_currency.items(), key=lambda kv: -kv[1])
            ],
            "failed_payments_30d": failed_30d,
            "churn_rate": round(cancelled / organizations_total, 4) if organizations_total else 0.0,
            "revenue_currency": revenue_currency,
            "growth": [
                {
                    "month": m,
                    "organizations": int(org_signups.get(m, 0)),
                    "schools": int(school_signups.get(m, 0)),
                }
                for m in months
            ],
            "revenue": [revenue[m] for m in months],
            "plans": plans,
            "trials_ending": trials_ending,
            "at_risk": at_risk,
            "top_organizations": top_organizations,
            "recent_organizations": recent_organizations,
        }
    finally:
        await bind_tenant(session, None)
