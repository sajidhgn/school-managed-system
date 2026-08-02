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

from email_validator import EmailNotValidError, validate_email
from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

import app.db.registry  # noqa: F401  (side effect: registers every mapper)
from app.core.config import Environment, Settings, get_settings
from app.core.logging import configure_logging, get_logger
from app.db.session import dispose_engine, init_engine, session_scope
from app.modules.billing.models import OrganizationUsage
from app.modules.platform_admin.models import UNLIMITED, Plan, PlanCode
from app.modules.platform_admin.service import create_platform_admin
from app.modules.rbac.catalog import CATALOG
from app.modules.rbac.models import Membership, Permission, Role
from app.modules.tenancy.models import School

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
        school, _ = await tenancy.create_school(
            organization_id=organization.id,
            actor_user_id=owner.id,
            actor_membership_id=owner_membership.id,
            name=name,
            code=code,
            city="Lahore",
        )
        schools.append(school)
    await session.flush()

    # An AuthContext for the owner, so invitations go through the real service with
    # its real escalation guard rather than around it.
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
        role_code=SystemRole.OWNER.value,
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


async def reconcile_usage(session: AsyncSession) -> int:
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

    usage_rows = (await session.execute(select(OrganizationUsage))).scalars().all()
    for usage in usage_rows:
        org_id = usage.organization_id

        schools = (
            await session.execute(
                select(func.count())
                .select_from(School)
                .where(School.organization_id == org_id, School.deleted_at.is_(None))
            )
        ).scalar_one()
        staff = (
            await session.execute(
                select(func.count())
                .select_from(Membership)
                .where(
                    Membership.organization_id == org_id,
                    Membership.deleted_at.is_(None),
                )
            )
        ).scalar_one()
        custom_roles = (
            await session.execute(
                select(func.count())
                .select_from(Role)
                .where(Role.organization_id == org_id, Role.is_system.is_(False))
            )
        ).scalar_one()
        students = (
            await session.execute(
                select(func.count())
                .select_from(Student)
                .where(
                    Student.organization_id == org_id,
                    Student.deleted_at.is_(None),
                    Student.status == StudentStatus.ACTIVE,
                )
            )
        ).scalar_one()

        await session.execute(
            update(OrganizationUsage)
            .where(OrganizationUsage.organization_id == org_id)
            .values(
                schools_count=schools,
                staff_count=staff,
                custom_roles_count=custom_roles,
                students_count=students,
                recomputed_at=datetime.now(UTC),
            )
        )
    return len(usage_rows)


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
            count = await reconcile_usage(session)
            logger.info("usage_reconciled", organizations=count)
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

    args = parser.parse_args(argv)

    if args.command == "seed":
        asyncio.run(_run_seed(demo=args.demo))
    elif args.command == "reconcile-usage":
        asyncio.run(_run_reconcile())
    return 0


if __name__ == "__main__":
    sys.exit(main())
