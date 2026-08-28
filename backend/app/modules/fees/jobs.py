"""Scheduled fee work: the late-fee run.

WHY THIS FILE EXISTS
    `apply_late_fees` on the service is tenant- AND school-scoped: it reads the
    active policy for one campus and fines that campus's overdue challans. Something
    has to walk every campus that has a policy and call it, and that walk is not a
    business rule -- it is orchestration, so it lives here rather than in the service.

    It mirrors `billing/jobs.py`, which does the same walk one level up (per
    organization rather than per school). The two are deliberately separate jobs:
    one collects what schools owe EduCloud, the other fines what parents owe schools,
    and folding them together would put a customer-facing penalty inside our own
    revenue path.

=============================================================================
CONTEXTVARS, NOT JUST GUCs -- THE HALF THAT IS EASY TO MISS
=============================================================================
    `session_scope(org_id, school_id=...)` sets the PostgreSQL GUCs that RLS reads,
    which is what stops the job seeing another tenant's rows. It does NOT set the
    request ContextVars that `BaseRepository._school_scope_condition` and
    `require_school_id()` read -- those are populated by the auth dependency, and a
    job has no request.

    So this file sets them explicitly and resets them in a `finally`. Without that,
    every repository read would run with NO campus predicate: RLS would still hold
    the organization boundary, but a two-campus customer would have School A's job
    fining School B's parents under School A's policy. That is the exact failure the
    module's own repository docstring warns about -- correct RLS, wrong campus.

WHICH YEARS RUN
    Whatever has an ACTIVE policy. The job is self-configuring: a school with no
    policy is skipped without a row being read, and a school that retires its policy
    stops being fined the same night. Nothing here needs to know what "the current
    academic year" is, which is deliberate -- that fact does not exist in the schema
    yet (see the `academic_year` string on every fee table) and guessing it in a
    background job is how a school gets fined against last year's rule.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import (
    get_organization_id,
    get_school_id,
    set_organization_id,
    set_school_id,
)
from app.core.logging import get_logger
from app.modules.fees.models import LateFeePolicy
from app.modules.fees.service import FeeService
from app.modules.tenancy.models import School

logger = get_logger(__name__)

_ZERO = Decimal("0.00")


async def apply_late_fees_for_school(
    session: AsyncSession,
    *,
    organization_id: UUID,
    school_id: UUID,
    today: date | None = None,
) -> tuple[int, Decimal]:
    """Fine every overdue challan at one campus, for every year it has a policy.

    Returns `(fines_raised, total_charged)`. Idempotent: the service's own three
    guards mean a second run on the same day assesses nothing further, which is what
    makes it safe to put on a cron that might overlap or be retried.
    """
    # Saved and restored by VALUE rather than by ContextVar token. A token may only
    # be reset in the context it was created in, and this coroutine can be awaited
    # from a task group where that no longer holds; restoring the value is correct in
    # both cases and cannot raise mid-cleanup.
    previous_org = get_organization_id()
    previous_school = get_school_id()
    set_organization_id(organization_id)
    set_school_id(school_id)
    try:
        years = (
            (
                await session.execute(
                    select(LateFeePolicy.academic_year).where(
                        LateFeePolicy.school_id == school_id,
                        LateFeePolicy.is_active.is_(True),
                        LateFeePolicy.deleted_at.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        if not years:
            return 0, _ZERO

        service = FeeService(session)
        raised = 0
        charged = _ZERO
        for academic_year in years:
            # `actor_id=None` on purpose. The audit row for this run has no human
            # actor, and attributing it to a system user that does not exist would
            # make "who fined us?" unanswerable. Null is the honest answer: the
            # policy did.
            result = await service.apply_late_fees(academic_year, actor_id=None, today=today)
            raised += result.assessed
            charged += result.total_charged
            if result.truncated:
                # LOUD, because the alternative is a school quietly under-fined every
                # night while the run reports success. The remainder is picked up by
                # the next pass, oldest delinquency first.
                logger.warning(
                    "fee_late_fee_run_truncated",
                    school_id=str(school_id),
                    academic_year=academic_year,
                    assessed=result.assessed,
                )
        return raised, charged
    finally:
        set_school_id(previous_school)
        set_organization_id(previous_org)


async def apply_late_fees_for_organization(
    session: AsyncSession,
    organization_id: UUID,
    *,
    today: date | None = None,
) -> tuple[int, Decimal]:
    """Every campus in one organization.

    The session is already bound to the organization by the caller, so the school
    list is RLS-filtered and cannot reach another tenant's campuses.
    """
    school_ids = list(
        (
            await session.execute(
                select(School.id).where(
                    School.organization_id == organization_id,
                    School.deleted_at.is_(None),
                )
            )
        ).scalars()
    )

    raised = 0
    charged = _ZERO
    for school_id in school_ids:
        school_raised, school_charged = await apply_late_fees_for_school(
            session, organization_id=organization_id, school_id=school_id, today=today
        )
        raised += school_raised
        charged += school_charged
    return raised, charged


async def generate_scheduled_challans_for_school(
    session: AsyncSession,
    *,
    organization_id: UUID,
    school_id: UUID,
    today: date | None = None,
) -> tuple[int, int]:
    """Bill every class this campus is due to bill today.

    Returns `(created, skipped)`. The campus is asked, not told: the job knows only
    that it is a new day, and each school's own `fee_billing_schedules` row decides
    whether today is its billing day, how long parents get to pay, whether the run
    issues or drafts, and whether unpaid earlier challans are carried forward.

    IDEMPOTENT, and by two separate mechanisms. `last_run_period` stops a second pass
    on the same day doing any work; the partial unique index on `fee_vouchers` stops a
    second pass BILLING anyone it already billed, even if the first pass crashed
    before it could write its bookmark. The second is the one that matters -- a
    half-finished run is completed by running again, not by an operator working out
    which students got a challan.

    A campus with no schedule costs one indexed read and nothing else, which is what
    keeps this safe to put in the same nightly pass as everything else.
    """
    # Same ContextVar dance as `apply_late_fees_for_school`, and for the same reason:
    # the GUCs hold the ORGANIZATION boundary, but the repositories read the campus
    # scope from a ContextVar that only the auth dependency normally sets. Without
    # this, a two-campus customer would have School A's schedule billing School B's
    # students -- correct RLS, wrong campus.
    previous_org = get_organization_id()
    previous_school = get_school_id()
    set_organization_id(organization_id)
    set_school_id(school_id)
    try:
        service = FeeService(session)
        schedules = await service.billing_schedules.list_active_for_school(school_id)
        if not schedules:
            return 0, 0

        created = 0
        skipped = 0
        for schedule in schedules:
            # `actor_id=None` on purpose, like the late-fee run. There is no human
            # behind this billing, and attributing it to a system user that does not
            # exist would make "who billed us?" unanswerable. Null is the honest
            # answer: the schedule did.
            result = await service.run_scheduled_generation(
                schedule.academic_year, actor_id=None, today=today
            )
            created += result.created
            skipped += result.skipped
            if result.truncated:
                # LOUD, because the alternative is a class quietly part-billed while
                # the run reports success. The remainder needs a narrower manual run.
                logger.warning(
                    "fee_scheduled_generation_truncated",
                    school_id=str(school_id),
                    academic_year=schedule.academic_year,
                    period_label=result.period_label,
                    created=result.created,
                )
        return created, skipped
    finally:
        set_school_id(previous_school)
        set_organization_id(previous_org)


async def generate_scheduled_challans_for_organization(
    session: AsyncSession,
    organization_id: UUID,
    *,
    today: date | None = None,
) -> tuple[int, int]:
    """Every campus in one organization.

    The session is already bound to the organization by the caller, so the school list
    is RLS-filtered and cannot reach another tenant's campuses.
    """
    school_ids = list(
        (
            await session.execute(
                select(School.id).where(
                    School.organization_id == organization_id,
                    School.deleted_at.is_(None),
                )
            )
        ).scalars()
    )

    created = 0
    skipped = 0
    for school_id in school_ids:
        school_created, school_skipped = await generate_scheduled_challans_for_school(
            session, organization_id=organization_id, school_id=school_id, today=today
        )
        created += school_created
        skipped += school_skipped
    return created, skipped
