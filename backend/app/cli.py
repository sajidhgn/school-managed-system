"""Command-line entry points -- primarily the idempotent seeder (spec §11).

WHY THIS FILE EXISTS
    Three things must exist before the application can serve a single request, and
    none of them can be created through the API:

      * the permission catalog -- roles reference it by foreign key
      * the plans -- every organization gets a subscription on verification
      * at least one platform admin -- there is no signup route for that role,
        deliberately (see `platform_admin/models.py`)

RESPONSIBILITY
    Populate that baseline, idempotently, and refuse to do anything dangerous in
    production.

USAGE
    python -m app.cli seed
    python -m app.cli seed --demo
    python -m app.cli reconcile-usage
    python -m app.cli run-maintenance

=============================================================================
IDEMPOTENT MEANS SAFE TO RE-RUN, NOT "SKIPS IF ANYTHING EXISTS"
=============================================================================
    The permission catalog is UPSERTED: a new permission added to `catalog.py` in a
    later release appears on the next seed run, and an existing one has its
    description refreshed. A seeder that bailed out on "permissions already exist"
    would mean every catalog addition needed a hand-written migration.

    Plans are INSERT-IF-ABSENT and never overwritten. Prices and limits are edited by
    the super admin through the console after launch, and a re-run that reset a
    negotiated price back to the seed value would be a billing incident.
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import sys
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.registry  # noqa: F401  (side effect: registers every mapper)
from app.core.config import Environment, Settings, get_settings
from app.core.context import (
    get_organization_id,
    get_school_id,
    set_organization_id,
    set_school_id,
)
from app.core.logging import configure_logging, get_logger
from app.core.totp import encrypt_totp_secret, generate_totp_secret, provisioning_uri
from app.db.session import dispose_engine, init_engine, session_scope
from app.modules.billing.entitlements import EntitlementService
from app.modules.billing.models import OrganizationUsage
from app.modules.invitations.models import Invitation, InvitationStatus
from app.modules.platform_admin.models import UNLIMITED, Plan, PlanCode, PlatformAdmin
from app.modules.platform_admin.service import create_platform_admin
from app.modules.rbac.catalog import CATALOG
from app.modules.rbac.models import Membership, Permission, Role
from app.modules.tenancy.models import Organization, OrganizationStatus, School

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Plan definitions (spec §6.1)
# ---------------------------------------------------------------------------
#
# `-1` means unlimited. EVERY plan defines EVERY key -- spec §6.1 forbids
# missing-key fallbacks, because `.get(key, 0)` silently blocks a paying customer
# and `.get(key, -1)` silently gives away unlimited usage.

PLAN_SEEDS: tuple[dict[str, Any], ...] = (
    {
        "code": PlanCode.FREE.value,
        "name": "Free",
        "marketing_tagline": "Try EduCloud with a single school.",
        "description": "Everything you need to evaluate the platform, at no cost.",
        "price_monthly": Decimal("0"),
        "price_yearly": Decimal("0"),
        "trial_days": 0,
        "limits": {
            "max_schools": 1,
            "max_students": 50,
            "max_staff": 3,
            "max_custom_roles": 0,
            "storage_mb": 1024,
            "audit_retention_days": 7,
        },
        "features": {
            "custom_branding": False,
            "api_access": False,
            "priority_support": False,
            "sso": False,
            "advanced_reports": False,
        },
        "is_public": True,
        "sort_order": 10,
    },
    {
        "code": PlanCode.STARTER.value,
        "name": "Starter",
        "marketing_tagline": "For a growing school.",
        "description": "Up to three campuses with email support.",
        "price_monthly": Decimal("29"),
        "price_yearly": Decimal("290"),
        "trial_days": 14,
        "limits": {
            "max_schools": 3,
            "max_students": 500,
            "max_staff": 25,
            "max_custom_roles": 5,
            "storage_mb": 20480,
            "audit_retention_days": 90,
        },
        "features": {
            "custom_branding": False,
            "api_access": False,
            "priority_support": False,
            "sso": False,
            "advanced_reports": False,
        },
        "is_public": True,
        "sort_order": 20,
    },
    {
        "code": PlanCode.GROWTH.value,
        "name": "Growth",
        "marketing_tagline": "For school groups.",
        "description": "Ten campuses, custom branding, API access and priority support.",
        "price_monthly": Decimal("79"),
        "price_yearly": Decimal("790"),
        "trial_days": 14,
        "limits": {
            "max_schools": 10,
            "max_students": 2500,
            "max_staff": 100,
            "max_custom_roles": UNLIMITED,
            "storage_mb": 102400,
            "audit_retention_days": 365,
        },
        "features": {
            "custom_branding": True,
            "api_access": True,
            "priority_support": True,
            "sso": False,
            "advanced_reports": True,
        },
        "is_public": True,
        "sort_order": 30,
    },
    {
        "code": PlanCode.ENTERPRISE.value,
        "name": "Enterprise",
        "marketing_tagline": "Tailored to your group.",
        "description": "Unlimited scale, SSO and a negotiated contract.",
        # NULL price: this tier is quoted, not listed. `is_public = False` keeps it
        # off the pricing page and out of `GET /public/plans`; the only way onto it
        # is a super admin assigning it manually.
        "price_monthly": None,
        "price_yearly": None,
        "trial_days": 0,
        "limits": {
            "max_schools": UNLIMITED,
            "max_students": UNLIMITED,
            "max_staff": UNLIMITED,
            "max_custom_roles": UNLIMITED,
            "storage_mb": UNLIMITED,
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
        "sort_order": 40,
    },
)


# ---------------------------------------------------------------------------
# Seeders
# ---------------------------------------------------------------------------


async def seed_permissions(session: AsyncSession) -> int:
    """Upsert the permission catalog.

    ON CONFLICT DO UPDATE, not DO NOTHING: a later release that adds a permission or
    reworks a description must be able to ship it with a seed run. `code` is the
    primary key, so an existing row is refreshed rather than duplicated.
    """
    rows = [
        {
            "code": p.code,
            "resource": p.resource,
            "action": p.action,
            "category": p.category,
            "description": p.description,
            "min_scope": p.min_scope.value,
            "is_dangerous": p.is_dangerous,
        }
        for p in CATALOG
    ]
    stmt = pg_insert(Permission).values(rows)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[Permission.code],
            set_={
                "resource": stmt.excluded.resource,
                "action": stmt.excluded.action,
                "category": stmt.excluded.category,
                "description": stmt.excluded.description,
                "min_scope": stmt.excluded.min_scope,
                "is_dangerous": stmt.excluded.is_dangerous,
            },
        )
    )
    return len(rows)


async def seed_plans(session: AsyncSession) -> int:
    """Insert any plan that does not exist. NEVER overwrite an existing one.

    Prices and limits are edited by the super admin through the console after
    launch. A re-run that reset a negotiated enterprise price back to the seed value
    would be a billing incident, not a convenience.
    """
    created = 0
    for seed in PLAN_SEEDS:
        exists = (
            await session.execute(select(Plan.id).where(Plan.code == seed["code"]))
        ).scalar_one_or_none()
        if exists is not None:
            continue
        session.add(Plan(currency="USD", is_active=True, **seed))
        created += 1
    await session.flush()
    return created


async def seed_superadmin(session: AsyncSession, settings: Settings) -> str | None:
    """Create the platform super admin from the environment (spec §11.3).

    =====================================================================
    THIS REFUSES TO RUN IN PRODUCTION WITH A WEAK PASSWORD
    =====================================================================
        Spec §11.3: "Refuse to run in production if the password is the default or
        shorter than 16 chars -- abort with a non-zero exit."

        This account can read every tenant's data and impersonate any organization.
        A weak password on it is not a configuration smell; it is a platform-wide
        breach waiting for someone to try `admin/admin`. Aborting with a non-zero
        exit means a deploy pipeline stops rather than proceeding to expose it.
    """
    email = settings.SUPERADMIN_EMAIL.strip()
    password = settings.SUPERADMIN_PASSWORD

    if not email:
        logger.info("superadmin_skipped", reason="SUPERADMIN_EMAIL not set")
        return None

    # =====================================================================
    # VALIDATED HERE, BECAUSE LOGIN VALIDATES IT AND THE SEEDER DID NOT
    # =====================================================================
    #   `PlatformLoginRequest.email` is an `EmailStr`, so an address this seeder
    #   happily accepts can be one the login endpoint rejects with a 422. Reserved
    #   TLDs like `.test` and `.invalid` are the common case, and they are exactly
    #   what someone reaches for when filling in a local `.env`.
    #
    #   The failure mode without this check is miserable: the seed reports success,
    #   the account exists in the database, and every sign-in attempt returns a
    #   validation error that says nothing about the account. Catching it here names
    #   the actual problem at the moment it is introduced.
    try:
        validate_email(email, check_deliverability=False)
    except EmailNotValidError as exc:
        raise SystemExit(
            f"REFUSING TO SEED: SUPERADMIN_EMAIL '{email}' is not a valid address "
            f"({exc}). The platform login endpoint validates it, so this account "
            "would be created but unable to sign in. Reserved TLDs such as .test "
            "and .invalid are rejected — use a real domain, e.g. admin@example.com."
        ) from exc

    weak = (
        not password
        or len(password) < 16
        or password.lower() in {"changeme", "password", "admin", "superadmin"}
    )
    if settings.is_production and weak:
        raise SystemExit(
            "REFUSING TO SEED: SUPERADMIN_PASSWORD must be at least 16 characters "
            "and not a common default in production. This account can read every "
            "tenant's data."
        )

    if not password:
        # Outside production, generate one and print it exactly once. Better than a
        # known default, which is what everyone would otherwise leave in place.
        password = secrets.token_urlsafe(24)
        logger.warning("superadmin_password_generated", password=password)

    admin = await create_platform_admin(
        session, email=email, password=password, full_name="Platform Super Admin"
    )
    return str(admin.id)


async def seed_demo(session: AsyncSession, settings: Settings) -> dict[str, Any]:
    """`--demo` only: one organization, two schools, staff and pending invitations.

    Deliberately built by calling the SAME services the API uses -- registration,
    school creation, invitation -- rather than by inserting rows directly. A demo
    seeded with hand-written INSERTs proves nothing; one seeded through the services
    exercises provisioning, entitlements and the escalation guards, so a broken
    signup flow fails here rather than in front of a customer.
    """
    from app.api.deps import AuthContext
    from app.core.cache import get_role_permissions
    from app.db.session import bind_tenant
    from app.modules.auth.service import AuthService
    from app.modules.billing.service import ensure_free_subscription
    from app.modules.invitations.service import InvitationService
    from app.modules.rbac.models import RolePermission, SystemRole
    from app.modules.tenancy.service import TenancyService

    auth = AuthService(session, settings)
    demo_password = "Demo-Passphrase-9271"

    owner, organization = await auth.register(
        full_name="Amina Rahman",
        email="owner@demo.educloud.test",
        password=demo_password,
        organization_name="Demo Education Trust",
        country="PK",
    )
    # Skip the email round-trip: the demo needs an active account immediately.
    owner.status = owner.status.__class__.ACTIVE
    owner.email_verified_at = datetime.now(UTC)
    await session.flush()

    await bind_tenant(session, organization.id)
    await ensure_free_subscription(session, organization_id=organization.id)

    # The free plan caps schools at 1, and the demo needs two. Move it to growth --
    # the same operation the platform console performs, so the entitlement path is
    # exercised rather than bypassed.
    growth = (
        await session.execute(select(Plan).where(Plan.code == PlanCode.GROWTH.value))
    ).scalar_one()
    from app.modules.billing.models import Subscription

    subscription = (
        await session.execute(
            select(Subscription).where(Subscription.organization_id == organization.id)
        )
    ).scalar_one()
    subscription.plan_id = growth.id
    await session.flush()

    tenancy = TenancyService(session)
    owner_membership = (
        await session.execute(
            select(Membership).where(
                Membership.organization_id == organization.id,
                Membership.school_id.is_(None),
            )
        )
    ).scalar_one()

    schools = []
    for name, code in (("Demo Central Campus", "CENTRAL"), ("Demo North Campus", "NORTH")):
        school = await tenancy.create_school(
            organization_id=organization.id,
            actor_user_id=owner.id,
            actor_membership_id=owner_membership.id,
            name=name,
            code=code,
            city="Lahore",
        )
        schools.append(school)
    await session.flush()

    # An AuthContext for the principal, so invitations go through the real service
    # with its real escalation guard rather than around it.
    owner_permissions = frozenset(
        (
            await session.execute(
                select(RolePermission.permission_code).where(
                    RolePermission.role_id == owner_membership.role_id
                )
            )
        )
        .scalars()
        .all()
    )
    principal_school = schools[0]
    ctx = AuthContext(
        user_id=owner.id,
        organization_id=organization.id,
        membership_id=owner_membership.id,
        role_id=owner_membership.role_id,
        role_code=SystemRole.PRINCIPAL.value,
        permissions=owner_permissions,
        school_id=None,
        organization_status=organization.status.value,
    )

    invitations = InvitationService(session, settings)
    roles_by_code = {
        r.code: r
        for r in (await session.execute(select(Role).where(Role.school_id == principal_school.id)))
        .scalars()
        .all()
    }

    invited = []
    demo_invites = [
        ("teacher1@demo.educloud.test", "Sana Iqbal", SystemRole.TEACHER),
        ("teacher2@demo.educloud.test", "Bilal Ahmed", SystemRole.TEACHER),
        ("accounts@demo.educloud.test", "Nadia Khan", SystemRole.ACCOUNTANT),
        ("teacher3@demo.educloud.test", "Omar Farooq", SystemRole.TEACHER),
        ("teacher4@demo.educloud.test", "Hina Malik", SystemRole.TEACHER),
    ]
    for email, name, role_code in demo_invites:
        invitation, raw = await invitations.create(
            ctx=ctx,
            school_id=principal_school.id,
            email=email,
            full_name=name,
            role_id=roles_by_code[role_code.value].id,
        )
        invited.append({"email": email, "token": raw, "id": str(invitation.id)})

    del get_role_permissions  # imported for the demo's side effects only; unused here

    return {
        "organization": organization.name,
        "owner_email": owner.email,
        "owner_password": demo_password,
        "schools": [s.code for s in schools],
        "pending_invitations": invited,
    }


async def reconcile_usage(session: AsyncSession, organization_id: UUID) -> None:
    """Recompute `organization_usage` counters from the source tables.

    WHY THIS COMMAND EXISTS
        The counters are maintained incrementally by every write path, which is what
        makes the entitlement check a single atomic statement instead of a racy
        count-then-insert. The cost of that design is drift: one write path that
        forgets its increment, or a crash between two statements outside a
        transaction, leaves the counter wrong -- and a wrong counter either blocks a
        paying customer or gives away capacity.

        This is the correction. Run it on a schedule; a `recomputed_at` that is old
        on a busy organization is the signal that a write path is missing its update.
    """
    from app.modules.students.models import Student, StudentStatus

    organization = await session.get(Organization, organization_id)
    if organization is None:
        return
    usage = (
        await session.execute(
            select(OrganizationUsage).where(OrganizationUsage.organization_id == organization_id)
        )
    ).scalar_one_or_none()
    if usage is None:
        usage = OrganizationUsage(organization_id=organization_id)
        session.add(usage)
        await session.flush()

    schools = (
        await session.execute(
            select(func.count())
            .select_from(School)
            .where(
                School.organization_id == organization_id,
                School.deleted_at.is_(None),
            )
        )
    ).scalar_one()
    active_staff = (
        await session.execute(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.organization_id == organization_id,
                Membership.deleted_at.is_(None),
                Membership.status == "active",
                Membership.user_id != organization.owner_user_id,
            )
        )
    ).scalar_one()
    pending_invitations = (
        await session.execute(
            select(func.count())
            .select_from(Invitation)
            .where(
                Invitation.organization_id == organization_id,
                Invitation.status == InvitationStatus.PENDING,
                Invitation.expires_at > datetime.now(UTC),
            )
        )
    ).scalar_one()
    custom_roles = (
        await session.execute(
            select(func.count())
            .select_from(Role)
            .where(
                Role.organization_id == organization_id,
                Role.is_system.is_(False),
            )
        )
    ).scalar_one()
    students = (
        await session.execute(
            select(func.count())
            .select_from(Student)
            .where(
                Student.organization_id == organization_id,
                Student.deleted_at.is_(None),
                Student.status == StudentStatus.ACTIVE,
            )
        )
    ).scalar_one()

    usage.schools_count = schools
    usage.staff_count = active_staff + pending_invitations
    usage.custom_roles_count = custom_roles
    usage.students_count = students
    usage.recomputed_at = datetime.now(UTC)
    await session.flush()

    over_limit = await EntitlementService(session).is_over_limit(organization_id)
    if over_limit:
        organization.status = OrganizationStatus.OVER_LIMIT
    elif organization.status is OrganizationStatus.OVER_LIMIT:
        organization.status = OrganizationStatus.ACTIVE


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


async def _run_seed(*, demo: bool) -> None:
    settings = get_settings()
    configure_logging(settings)
    init_engine(settings)

    try:
        # Seeded with the platform-admin GUC armed: the seeder writes across every
        # scope, including tables no single organization owns, and the demo
        # organization does not exist yet when the run begins.
        async with session_scope(None, platform_admin=True) as session:
            permissions = await seed_permissions(session)
            plans = await seed_plans(session)
            admin_id = await seed_superadmin(session, settings)

            logger.info(
                "seed_complete",
                permissions=permissions,
                plans_created=plans,
                superadmin=admin_id or "skipped",
            )

            if demo:
                if settings.ENVIRONMENT is Environment.PRODUCTION:
                    raise SystemExit("REFUSING: --demo cannot be run in production.")
                result = await seed_demo(session, settings)
                logger.info("demo_seed_complete", **{k: str(v) for k, v in result.items()})
                print("\nDemo data created:")
                print(f"  Organization : {result['organization']}")
                print(f"  Owner login  : {result['owner_email']} / {result['owner_password']}")
                print(f"  Schools      : {', '.join(result['schools'])}")
                print(f"  Invitations  : {len(result['pending_invitations'])} pending")
                for inv in result["pending_invitations"]:
                    print(f"    {inv['email']}  ->  /invite/accept?token={inv['token']}")
    finally:
        await dispose_engine()


async def _run_reconcile() -> None:
    settings = get_settings()
    configure_logging(settings)
    init_engine(settings)
    try:
        async with session_scope(None, platform_admin=True) as session:
            organization_ids = list((await session.execute(select(Organization.id))).scalars())
        for organization_id in organization_ids:
            async with session_scope(organization_id) as session:
                await reconcile_usage(session, organization_id)
        logger.info("usage_reconciled", organizations=len(organization_ids))
    finally:
        await dispose_engine()


async def _run_maintenance() -> None:
    """Advance billing lifecycle, apply retention, generate due challans, fine late ones."""
    from app.modules.billing.jobs import process_billing_lifecycle, purge_expired_audit_logs
    from app.modules.fees.jobs import (
        apply_late_fees_for_organization,
        generate_scheduled_challans_for_organization,
    )
    from app.modules.invitations.service import expire_pending_invitations

    settings = get_settings()
    configure_logging(settings)
    init_engine(settings)
    lifecycle_events = 0
    audit_rows_purged = 0
    invitations_expired = 0
    challans_generated = 0
    late_fees_raised = 0
    try:
        async with session_scope(None, platform_admin=True) as session:
            organization_ids = list(
                (
                    await session.execute(
                        select(Organization.id).where(Organization.deleted_at.is_(None))
                    )
                ).scalars()
            )
        for organization_id in organization_ids:
            async with session_scope(organization_id) as session:
                lifecycle_events += len(await process_billing_lifecycle(session, organization_id))
                audit_rows_purged += await purge_expired_audit_logs(session, organization_id)
                invitations_expired += await expire_pending_invitations(session, organization_id)
                # BEFORE the late-fee pass, and that order is deliberate. A challan
                # generated today is not yet due, so it cannot be fined by the run
                # that follows it -- but a school whose billing day and grace period
                # happen to coincide would, in the other order, have this month's
                # challan fined by next month's pass a day earlier than its own
                # settings say. Generating first keeps the two passes independent.
                created, _ = await generate_scheduled_challans_for_organization(
                    session, organization_id
                )
                challans_generated += created
                # Last in the sequence on purpose: it is the only step that CHARGES a
                # customer's customer, so it runs after the tenant's own subscription
                # state has been settled. A suspended organization should not be
                # fining parents on the same pass that suspended it.
                raised, _ = await apply_late_fees_for_organization(session, organization_id)
                late_fees_raised += raised
        logger.info(
            "maintenance_complete",
            organizations=len(organization_ids),
            lifecycle_events=lifecycle_events,
            audit_rows_purged=audit_rows_purged,
            invitations_expired=invitations_expired,
            challans_generated=challans_generated,
            late_fees_raised=late_fees_raised,
        )
    finally:
        await dispose_engine()


async def _run_reconcile_ledger() -> None:
    """Report every student whose ledger balance disagrees with their vouchers.

    REPORTS, NEVER REPAIRS. `fee_vouchers` and `fee_payments` are authoritative; the
    ledger is a materialised record of them. A job that silently rewrote the ledger
    to match would hide whatever caused the drift, and the cause is the thing worth
    finding -- a balance that corrects itself every night is indistinguishable from
    one that was right all along.

    A manual ADJUSTMENT is the expected legitimate difference: writing off a hardship
    balance moves the ledger and touches no voucher. So a non-empty report is a
    prompt to read the statements, not an alarm.
    """
    from app.modules.fees.service import FeeService

    settings = get_settings()
    configure_logging(settings)
    init_engine(settings)
    drifted = 0
    try:
        async with session_scope(None, platform_admin=True) as session:
            organization_ids = list(
                (
                    await session.execute(
                        select(Organization.id).where(Organization.deleted_at.is_(None))
                    )
                ).scalars()
            )
        for organization_id in organization_ids:
            async with session_scope(organization_id) as session:
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
                for school_id in school_ids:
                    previous_org = get_organization_id()
                    previous_school = get_school_id()
                    set_organization_id(organization_id)
                    set_school_id(school_id)
                    try:
                        drift = await FeeService(session).reconcile_ledger()
                    finally:
                        set_school_id(previous_school)
                        set_organization_id(previous_org)
                    for student_id, (ledger_total, voucher_total) in drift.items():
                        drifted += 1
                        logger.warning(
                            "fee_ledger_drift",
                            organization_id=str(organization_id),
                            school_id=str(school_id),
                            student_id=str(student_id),
                            ledger_balance=str(ledger_total),
                            voucher_balance=str(voucher_total),
                            difference=str(ledger_total - voucher_total),
                        )
        logger.info(
            "fee_ledger_reconciled",
            organizations=len(organization_ids),
            students_with_drift=drifted,
        )
    finally:
        await dispose_engine()


async def _run_verify_user(*, email: str, print_link: bool, force: bool) -> None:
    """Verify a tenant account's email address without the mail round-trip.

    WHY THIS COMMAND EXISTS
        `register` leaves the account `pending` and emails a link; `authenticate`
        refuses to sign in until it is clicked. That is correct in production and a
        dead end in local development, where the mail may go to spam, bounce off a
        throwaway address, or simply never be checked -- and the account is then
        unreachable with no way in.

    IT DOES NOT HAND-EDIT THE COLUMNS. `verify_email` also starts the free
    subscription on the requested plan and writes the audit row, so flipping
    `status` and `email_verified_at` directly would leave an ACTIVE-looking
    organization with no subscription -- and every entitlement check then fails on
    an organization that looks perfectly healthy. Minting a real token and consuming
    it through the real path is the only version of this that produces the same
    state the emailed link produces.
    """
    # Deferred, mirroring `seed_demo`: the module-level cycle
    # auth -> billing -> tenancy -> auth is easier to break at the call site.
    from app.core.security import generate_opaque_token, hash_token
    from app.modules.auth.models import EmailVerificationToken, User
    from app.modules.auth.service import VERIFICATION_TTL, AuthService

    settings = get_settings()
    configure_logging(settings)

    if settings.is_production and not force:
        raise SystemExit(
            "REFUSING: verifying an address out-of-band skips the proof that the "
            "user controls that mailbox, which is the entire point of the step. "
            "Re-run with --force only if you are deliberately overriding it."
        )

    init_engine(settings)
    try:
        async with session_scope(None, platform_admin=True) as session:
            user = (
                await session.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if user is None:
                raise SystemExit(f"No account exists for '{email}'.")

            if user.email_verified_at is not None and not print_link:
                print(f"{user.email} is already verified (status={user.status.value}).")
                return

            raw = generate_opaque_token()
            session.add(
                EmailVerificationToken(
                    user_id=user.id,
                    token_hash=hash_token(raw),
                    expires_at=datetime.now(UTC) + VERIFICATION_TTL,
                )
            )
            await session.flush()

            if print_link:
                # For testing the real page rather than bypassing it.
                print(f"{settings.FRONTEND_URL}/verify-email?token={raw}")
                return

            # No email sender passed, so nothing is dispatched.
            verified = await AuthService(session, settings).verify_email(raw)
            print(f"Verified {verified.email} (status={verified.status.value}).")
            print(f"Sign in at {settings.FRONTEND_URL}/login")
    finally:
        await dispose_engine()


async def _run_mfa_enroll(*, email: str) -> None:
    """Enroll or rotate platform TOTP and print the secret exactly once."""
    settings = get_settings()
    configure_logging(settings)
    init_engine(settings)
    try:
        async with session_scope(None, platform_admin=True) as session:
            admin = (
                await session.execute(select(PlatformAdmin).where(PlatformAdmin.email == email))
            ).scalar_one_or_none()
            if admin is None:
                raise SystemExit(f"No platform administrator exists for '{email}'.")

            secret = generate_totp_secret()
            admin.mfa_secret = encrypt_totp_secret(secret, settings)
            admin.mfa_last_used_step = None
            print("Platform MFA enrolled. Store this secret now; it will not be shown again.")
            print(f"Secret: {secret}")
            print(f"URI: {provisioning_uri(secret=secret, email=admin.email)}")
    finally:
        await dispose_engine()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    seed_parser = sub.add_parser("seed", help="Seed permissions, plans and the super admin.")
    seed_parser.add_argument(
        "--demo",
        action="store_true",
        help="Also create a demo organization with schools, staff and invitations.",
    )
    sub.add_parser(
        "reconcile-usage", help="Recompute organization usage counters from source tables."
    )
    sub.add_parser(
        "run-maintenance",
        help=(
            "Advance billing lifecycle, anonymize expired accounts, purge audit logs, "
            "generate challans for every campus due to bill today, and raise due late "
            "fees. Run DAILY: the schedule that decides which campuses bill today "
            "lives in each school's own settings, not in the cron line."
        ),
    )
    sub.add_parser(
        "reconcile-ledger",
        help="Report students whose fee ledger balance disagrees with their vouchers.",
    )
    mfa_parser = sub.add_parser(
        "mfa-enroll", help="Enroll or rotate TOTP for a platform administrator."
    )
    mfa_parser.add_argument("--email", required=True, help="Platform administrator email.")

    verify_parser = sub.add_parser(
        "verify-user", help="Mark a tenant account's email verified (local dev)."
    )
    verify_parser.add_argument("--email", required=True, help="The account's email address.")
    verify_parser.add_argument(
        "--print-link",
        action="store_true",
        help="Print a fresh verification URL instead of consuming it.",
    )
    verify_parser.add_argument("--force", action="store_true", help="Allow this in production.")

    args = parser.parse_args(argv)

    if args.command == "seed":
        asyncio.run(_run_seed(demo=args.demo))
    elif args.command == "reconcile-usage":
        asyncio.run(_run_reconcile())
    elif args.command == "run-maintenance":
        asyncio.run(_run_maintenance())
    elif args.command == "reconcile-ledger":
        asyncio.run(_run_reconcile_ledger())
    elif args.command == "mfa-enroll":
        asyncio.run(_run_mfa_enroll(email=args.email))
    elif args.command == "verify-user":
        asyncio.run(
            _run_verify_user(email=args.email, print_link=args.print_link, force=args.force)
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
