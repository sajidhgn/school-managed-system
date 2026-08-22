"""Entitlement enforcement (spec §6.2).

WHY THIS FILE EXISTS
    A plan limit that is checked in some code paths and not others is not a limit.
    Spec §6.2 asks for a single `EntitlementService.check(org_id, key, delta)` called
    before EVERY resource-creating write, so there is exactly one place the rule
    lives and exactly one place to audit.

RESPONSIBILITY
    Decide whether an organization may create one more of something, and atomically
    reserve the capacity if so. Also release capacity on deletion.

INTERACTIONS
    * `modules/tenancy/service.py` -> `check_and_consume(org, "max_schools")`
    * `modules/invitations/service.py` -> `check_and_consume(org, "max_staff")`
    * `modules/students/service.py` -> `check_and_consume(org, "max_students")`

=============================================================================
CHECK AND INCREMENT ARE ONE STATEMENT, NOT TWO
=============================================================================
    The obvious implementation is:

        current = SELECT count FROM organization_usage ...
        if current >= limit: raise
        UPDATE organization_usage SET count = count + 1 ...

    That is a read-modify-write with no lock held between the read and the write.
    Two concurrent requests on a free plan (limit 1) both read 0, both pass the
    check, and both insert. The organization ends up with 2 schools on a 1-school
    plan, and no error was raised anywhere.

    This is not a theoretical race. It is what a double-clicked "Create school"
    button does.

    The fix is to make the check part of the UPDATE's WHERE clause:

        UPDATE organization_usage
           SET schools_count = schools_count + 1
         WHERE organization_id = :org
           AND schools_count + 1 <= :limit
        RETURNING schools_count

    PostgreSQL takes a row lock for the duration of the UPDATE, so the second
    request evaluates its predicate against the first one's committed result. If the
    predicate fails, zero rows are affected -- and that row count IS the verdict. No
    window exists between deciding and acting, because they are the same operation.

=============================================================================
FAILING WITH 402, NOT 403
=============================================================================
    A plan limit is not an authorization failure. The user is perfectly entitled to
    create schools; they have simply run out of the ones they paid for. 402 Payment
    Required, with the limit, the current count and an upgrade URL, lets the frontend
    render an upgrade prompt instead of a generic "forbidden" that reads like a bug.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AppError, ConflictError
from app.core.logging import get_logger
from app.modules.billing.models import OrganizationUsage, Subscription
from app.modules.platform_admin.models import UNLIMITED, Plan

logger = get_logger(__name__)


class PlanLimitExceededError(AppError):
    """402: the organization has used all of its plan's allowance for this resource.

    Its own exception class rather than a generic error so the API layer renders the
    exact body spec §6.2 specifies -- `limit`, `current`, `allowed`, `upgrade_url` --
    which is what the frontend needs to show a useful upgrade prompt rather than a
    dead end.
    """

    status_code = 402
    code = "plan_limit_exceeded"
    message = "Your plan's limit for this resource has been reached."


@dataclass(frozen=True, slots=True)
class UsageSnapshot:
    """Current usage against current limits, for `GET /org/usage`."""

    key: str
    current: int
    allowed: int  # -1 = unlimited

    @property
    def is_unlimited(self) -> bool:
        return self.allowed == UNLIMITED

    @property
    def remaining(self) -> int | None:
        """None when unlimited -- deliberately not a large sentinel number, which a
        frontend would render as a nonsensical "999999 remaining"."""
        return None if self.is_unlimited else max(0, self.allowed - self.current)

    @property
    def is_exhausted(self) -> bool:
        return not self.is_unlimited and self.current >= self.allowed


class EntitlementService:
    """The single gate in front of every resource-creating write."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _plan_for(self, organization_id: UUID) -> Plan:
        """The organization's current plan.

        A missing subscription is a broken invariant -- every organization gets one
        on email verification -- so it raises rather than silently defaulting to the
        free plan's limits. A silent default here would mean a provisioning bug
        presents as a customer mysteriously being unable to create their second
        school, which is a very hard thing to trace back to its cause.
        """
        plan = (
            await self.session.execute(
                select(Plan)
                .join(Subscription, Subscription.plan_id == Plan.id)
                .where(Subscription.organization_id == organization_id)
            )
        ).scalar_one_or_none()

        if plan is None:
            raise ConflictError(
                "This organization has no active subscription.",
                code="NO_SUBSCRIPTION",
            )
        return plan

    async def _usage_row(self, organization_id: UUID) -> OrganizationUsage:
        """The counter row, created on demand if provisioning missed it."""
        usage = (
            await self.session.execute(
                select(OrganizationUsage).where(
                    OrganizationUsage.organization_id == organization_id
                )
            )
        ).scalar_one_or_none()

        if usage is None:
            usage = OrganizationUsage(organization_id=organization_id)
            self.session.add(usage)
            await self.session.flush()
        return usage

    async def check_and_consume(
        self,
        organization_id: UUID,
        key: str,
        *,
        delta: int = 1,
    ) -> None:
        """Reserve `delta` units of `key`, or raise `PlanLimitExceededError`.

        MUST be called BEFORE the row it accounts for is inserted, and inside the
        same transaction. Same transaction means a failure downstream rolls the
        reservation back too -- otherwise a failed student import would permanently
        consume seats for students that were never created.

        Spec §7.1 step 3 makes the ordering explicit for invitations: the check runs
        before the email is sent, so a staff-limit rejection never results in an
        invitation landing in someone's inbox that they then cannot accept.
        """
        plan = await self._plan_for(organization_id)
        counter = OrganizationUsage.LIMIT_TO_COUNTER.get(key)
        if counter is None:
            known = sorted(OrganizationUsage.LIMIT_TO_COUNTER)
            raise KeyError(f"'{key}' is not a metered limit. Known: {known}")

        allowed = plan.limit(key)
        await self._usage_row(organization_id)  # ensure the row exists

        if allowed == UNLIMITED:
            # Still counted -- `GET /org/usage` and platform analytics both want the
            # number, and an unlimited plan that silently stops counting makes a
            # later downgrade impossible to evaluate.
            await self.session.execute(
                update(OrganizationUsage)
                .where(OrganizationUsage.organization_id == organization_id)
                .values(**{counter: getattr(OrganizationUsage, counter) + delta})
            )
            return

        column = getattr(OrganizationUsage, counter)
        result = await self.session.execute(
            update(OrganizationUsage)
            .where(
                OrganizationUsage.organization_id == organization_id,
                # THE CHECK, fused into the write. See the module docstring.
                column + delta <= allowed,
            )
            .values(**{counter: column + delta})
            .returning(column)
        )
        reserved = result.scalar_one_or_none()

        if reserved is None:
            # The predicate failed: no capacity. Re-read for an accurate error body.
            usage = await self._usage_row(organization_id)
            current = getattr(usage, counter)
            logger.info(
                "plan_limit_exceeded",
                organization_id=str(organization_id),
                limit=key,
                current=current,
                allowed=allowed,
            )
            raise PlanLimitExceededError(
                f"Your plan allows {allowed} of this resource; you are using {current}.",
                details={
                    "limit": key,
                    "current": current,
                    "allowed": allowed,
                    "upgrade_url": "/billing/plans",
                },
            )

    async def release(self, organization_id: UUID, key: str, *, delta: int = 1) -> None:
        """Give capacity back when a counted resource is removed.

        `GREATEST(count - delta, 0)` rather than a bare subtraction: the CHECK
        constraint forbids negatives, so an over-release from a double-delete would
        otherwise raise a database error in the middle of an unrelated operation.
        Clamping keeps a counter drift bug from becoming an outage; the
        reconciliation job is what actually corrects it.
        """
        counter = OrganizationUsage.LIMIT_TO_COUNTER.get(key)
        if counter is None:
            raise KeyError(f"'{key}' is not a metered limit.")

        column = getattr(OrganizationUsage, counter)
        await self.session.execute(
            update(OrganizationUsage)
            .where(OrganizationUsage.organization_id == organization_id)
            .values(**{counter: func.greatest(column - delta, 0)})
        )

    async def snapshot(self, organization_id: UUID) -> list[UsageSnapshot]:
        """Every metered limit with its current usage. Backs `GET /org/usage`."""
        plan = await self._plan_for(organization_id)
        usage = await self._usage_row(organization_id)

        return [
            UsageSnapshot(
                key=key,
                current=getattr(usage, counter),
                allowed=plan.limit(key),
            )
            for key, counter in OrganizationUsage.LIMIT_TO_COUNTER.items()
        ]

    async def is_over_limit(self, organization_id: UUID) -> bool:
        """Whether current usage exceeds the current plan -- the downgrade case.

        Spec §6.2: never delete data on downgrade. The organization moves to
        `over_limit`, existing records stay readable, and only new creates are
        blocked. This is the predicate that decides that transition.
        """
        return any(
            not snap.is_unlimited and snap.current > snap.allowed
            for snap in await self.snapshot(organization_id)
        )
