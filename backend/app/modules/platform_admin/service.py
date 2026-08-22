"""Platform operator service: login, organization oversight, plan management.

WHY THIS FILE EXISTS
    Platform admins sit outside tenancy entirely. Their reads cross every
    organization, and that capability is the single highest-value target on the
    system -- one validation slip here exposes every school's records.

    So the rules differ from the tenant side in three ways, and all three are
    implemented here rather than assumed:
      * no self-service anything -- no signup, no emailed password reset
      * cross-tenant reads only inside an explicit, audited context
      * every action written to `platform_audit_logs`, which no tenant can influence

RESPONSIBILITY
    Authenticate operators, manage organizations and plans, and expose platform
    metrics.

INTERACTIONS
    * `api/deps.py::require_platform_admin` guards the routes.
    * `common/audit.py::record_platform_audit` for the trail.

=============================================================================
IMPERSONATION IS READ-ONLY, TIME-BOXED, AND AUDITED
=============================================================================
    Support needs to see what a customer sees. It does not need to act as them.

    Arming `app.is_platform_admin` grants cross-tenant READS only: the `WITH CHECK`
    half of every RLS policy has no admin escape (see `alembic/rls.py`), so a
    platform admin physically cannot write into a tenant through it. Combined with
    the audit row written before the context opens, the customer can always be told
    exactly who looked at their data and when.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import PlatformAuditAction, record_platform_audit
from app.core.config import Settings
from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.core.logging import get_logger
from app.core.security import (
    dummy_password_verify,
    hash_password,
    verify_password,
)
from app.core.totp import decrypt_totp_secret, encrypt_totp_secret, verify_totp
from app.db.session import bind_tenant
from app.modules.billing.models import (
    OrganizationUsage,
    Payment,
    PaymentStatus,
    Subscription,
    SubscriptionEvent,
    SubscriptionStatus,
)
from app.modules.platform_admin.models import (
    REQUIRED_FEATURE_KEYS,
    REQUIRED_LIMIT_KEYS,
    UNLIMITED,
    Plan,
    PlanCode,
    PlatformAdmin,
)
from app.modules.tenancy.models import Organization, OrganizationStatus, School

logger = get_logger(__name__)

# How long an impersonation context stays valid (spec §8: "time-boxed").
IMPERSONATION_TTL = timedelta(minutes=30)


class PlatformService:
    """Platform operator actions. Never commits."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    # -----------------------------------------------------------------------
    # Authentication
    # -----------------------------------------------------------------------

    async def authenticate(
        self,
        *,
        email: str,
        password: str,
        totp_code: str | None = None,
        ip: str | None = None,
    ) -> PlatformAdmin:
        """Verify operator credentials (spec §4.3A).

        Same enumeration and timing defences as the tenant login -- more important
        here, not less: the set of valid platform-admin addresses is tiny, so
        confirming even one is a meaningful head start for an attacker.
        """
        admin = (
            await self.session.execute(select(PlatformAdmin).where(PlatformAdmin.email == email))
        ).scalar_one_or_none()

        if admin is None:
            dummy_password_verify()
            await record_platform_audit(
                self.session,
                action=PlatformAuditAction.ADMIN_LOGIN_FAILED,
                ip=ip,
                metadata={"reason": "invalid_credentials"},
            )
            raise self._invalid()

        if admin.locked_until is not None and admin.locked_until > datetime.now(UTC):
            await record_platform_audit(
                self.session,
                action=PlatformAuditAction.ADMIN_LOGIN_FAILED,
                actor_admin_id=admin.id,
                ip=ip,
                metadata={"reason": "locked"},
            )
            raise self._invalid()

        if not verify_password(password, admin.password_hash):
            admin.failed_login_count += 1
            if admin.failed_login_count >= self.settings.LOGIN_MAX_FAILURES:
                admin.locked_until = datetime.now(UTC) + timedelta(
                    minutes=self.settings.LOGIN_LOCKOUT_MINUTES
                )
                admin.failed_login_count = 0
                logger.warning("platform_admin_locked", admin_id=str(admin.id), ip=ip)
            await record_platform_audit(
                self.session,
                action=PlatformAuditAction.ADMIN_LOGIN_FAILED,
                actor_admin_id=admin.id,
                ip=ip,
            )
            raise self._invalid()

        if not admin.is_active:
            await record_platform_audit(
                self.session,
                action=PlatformAuditAction.ADMIN_LOGIN_FAILED,
                actor_admin_id=admin.id,
                ip=ip,
                metadata={"reason": "inactive"},
            )
            raise self._invalid()

        # Spec §4.3A: "MFA required in production." Refusing at login is the only
        # place this can be enforced -- an unenrolled operator who gets a session is
        # an unenrolled operator with full platform access until someone notices.
        if self.settings.is_production and not admin.mfa_secret:
            await record_platform_audit(
                self.session,
                action=PlatformAuditAction.ADMIN_LOGIN_FAILED,
                actor_admin_id=admin.id,
                ip=ip,
                metadata={"reason": "mfa_not_enrolled"},
            )
            raise AuthorizationError(
                "Multi-factor authentication must be enrolled before signing in. "
                "Enrol via the CLI.",
                code="MFA_ENROLMENT_REQUIRED",
            )

        if admin.mfa_secret:
            secret, was_legacy_plaintext = decrypt_totp_secret(admin.mfa_secret, self.settings)
            accepted_step = verify_totp(
                secret,
                totp_code or "",
                unix_time=int(datetime.now(UTC).timestamp()),
                last_used_step=admin.mfa_last_used_step,
            )
            if accepted_step is None:
                await record_platform_audit(
                    self.session,
                    action=PlatformAuditAction.ADMIN_LOGIN_FAILED,
                    actor_admin_id=admin.id,
                    ip=ip,
                    metadata={"reason": "invalid_or_replayed_totp"},
                )
                raise AuthenticationError(
                    "The authentication code is invalid or has expired.",
                    code="MFA_CODE_INVALID",
                )
            admin.mfa_last_used_step = accepted_step
            if was_legacy_plaintext:
                admin.mfa_secret = encrypt_totp_secret(secret, self.settings)

        admin.failed_login_count = 0
        admin.locked_until = None
        admin.last_login_at = datetime.now(UTC)

        await record_platform_audit(
            self.session,
            action=PlatformAuditAction.ADMIN_LOGGED_IN,
            actor_admin_id=admin.id,
            ip=ip,
        )
        return admin

    @staticmethod
    def _invalid() -> AuthenticationError:
        return AuthenticationError("Email or password is incorrect.", code="INVALID_CREDENTIALS")

    # -----------------------------------------------------------------------
    # Organizations
    # -----------------------------------------------------------------------

    async def list_organizations(
        self,
        *,
        status_filter: str | None = None,
        plan_code: str | None = None,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Every organization on the platform, with its plan and usage.

        Arms the cross-tenant read GUC -- this is precisely the audited platform
        context that justifies it. Disarmed in `finally` so a later query in the same
        transaction cannot inherit platform-wide visibility.
        """
        await bind_tenant(self.session, None, platform_admin=True)
        try:
            stmt = (
                select(Organization, Plan, OrganizationUsage, Subscription)
                .outerjoin(Subscription, Subscription.organization_id == Organization.id)
                .outerjoin(Plan, Plan.id == Subscription.plan_id)
                .outerjoin(
                    OrganizationUsage,
                    OrganizationUsage.organization_id == Organization.id,
                )
                .where(Organization.deleted_at.is_(None))
            )
            if status_filter:
                stmt = stmt.where(Organization.status == status_filter)
            if plan_code:
                stmt = stmt.where(Plan.code == plan_code)
            if query:
                like = f"%{query}%"
                stmt = stmt.where(Organization.name.ilike(like) | Organization.slug.ilike(like))

            rows = (
                await self.session.execute(
                    stmt.order_by(Organization.created_at.desc()).limit(limit).offset(offset)
                )
            ).all()

            return [
                {
                    "organization": organization,
                    "plan": plan,
                    "usage": usage,
                    "subscription": subscription,
                }
                for organization, plan, usage, subscription in rows
            ]
        finally:
            await bind_tenant(self.session, None)

    async def get_organization(self, organization_id: UUID) -> dict[str, Any]:
        await bind_tenant(self.session, None, platform_admin=True)
        try:
            organization = await self.session.get(Organization, organization_id)
            if organization is None or organization.deleted_at is not None:
                raise NotFoundError("Organization not found.")

            subscription = (
                await self.session.execute(
                    select(Subscription).where(Subscription.organization_id == organization_id)
                )
            ).scalar_one_or_none()
            plan = await self.session.get(Plan, subscription.plan_id) if subscription else None
            usage = (
                await self.session.execute(
                    select(OrganizationUsage).where(
                        OrganizationUsage.organization_id == organization_id
                    )
                )
            ).scalar_one_or_none()
            school_count = (
                await self.session.execute(
                    select(func.count())
                    .select_from(School)
                    .where(
                        School.organization_id == organization_id,
                        School.deleted_at.is_(None),
                    )
                )
            ).scalar_one()

            return {
                "organization": organization,
                "subscription": subscription,
                "plan": plan,
                "usage": usage,
                "school_count": school_count,
            }
        finally:
            await bind_tenant(self.session, None)

    async def list_schools(self, organization_id: UUID) -> list[School]:
        """Every campus inside one organization, for the operator's org-detail drilldown."""
        await bind_tenant(self.session, None, platform_admin=True)
        try:
            organization = await self.session.get(Organization, organization_id)
            if organization is None or organization.deleted_at is not None:
                raise NotFoundError("Organization not found.")

            rows = await self.session.execute(
                select(School)
                .where(
                    School.organization_id == organization_id,
                    School.deleted_at.is_(None),
                )
                .order_by(School.name)
            )
            return list(rows.scalars())
        finally:
            await bind_tenant(self.session, None)

    async def set_organization_status(
        self,
        *,
        admin_id: UUID,
        organization_id: UUID,
        suspend: bool,
        reason: str | None = None,
        ip: str | None = None,
    ) -> Organization:
        """Suspend or reactivate an organization.

        SUSPENSION IS READ-ONLY, NOT A LOCKOUT (spec §6.3). The admin panel keeps
        working for reads and exports; only writes are refused, by `require()`.
        Cutting a school off from its own student records over a billing dispute is
        leverage no software vendor should hold, and in several jurisdictions the
        records are ones the school is legally required to be able to produce.
        """
        # Read across tenants to find it, then bind THAT organization for the write --
        # spec §2.2's rule, and the only shape the `WITH CHECK` policy accepts. See
        # `override_plan` for the full reasoning.
        await bind_tenant(self.session, None, platform_admin=True)
        try:
            organization = await self.session.get(Organization, organization_id)
            if organization is None:
                raise NotFoundError("Organization not found.")
        finally:
            await bind_tenant(self.session, None)

        await bind_tenant(self.session, organization_id)
        try:
            previous = organization.status
            organization.status = (
                OrganizationStatus.SUSPENDED if suspend else OrganizationStatus.ACTIVE
            )

            await record_platform_audit(
                self.session,
                action=(
                    PlatformAuditAction.ORGANIZATION_SUSPENDED
                    if suspend
                    else PlatformAuditAction.ORGANIZATION_REACTIVATED
                ),
                actor_admin_id=admin_id,
                entity_type="organization",
                entity_id=organization_id,
                target_organization_id=organization_id,
                metadata={
                    "from": previous.value,
                    "to": organization.status.value,
                    "reason": reason,
                },
                ip=ip,
            )
            # Flushed before the GUC is cleared -- see `override_plan`.
            await self.session.flush()
            return organization
        finally:
            await bind_tenant(self.session, None)

    async def override_plan(
        self,
        *,
        admin_id: UUID,
        organization_id: UUID,
        plan_code: str,
        ip: str | None = None,
    ) -> Subscription:
        """Assign any plan manually, including hidden ones (spec §8).

        The only path onto the `enterprise` tier, which is `is_public = false` and
        therefore unreachable through self-service. Bypasses the gateway entirely:
        an enterprise contract is invoiced offline, so there is no recurring charge
        to set up.

        =====================================================================
        THE WRITE IS BOUND TO THE TARGET ORGANIZATION, NOT TO THE ADMIN GUC
        =====================================================================
            Spec §2.2 spells this out: "a platform admin may read across tenants, not
            write into them, except through dedicated admin endpoints that set
            `app.current_org_id` to the target org first."

            This is one of those endpoints, and the reason is enforced by the
            database rather than by convention: the `WITH CHECK` half of every RLS
            policy has NO platform-admin branch, so an UPDATE attempted with only
            `is_platform_admin = on` matches zero rows and SQLAlchemy raises
            `StaleDataError`. There is no way to write into a tenant without naming
            it.

            The practical effect is that the change lands inside the customer's own
            tenant scope and appears in their audit trail, rather than materialising
            from nowhere.
        """
        # Reads first, with the cross-tenant escape armed: the plan is global and the
        # subscription belongs to an organization this admin is not a member of.
        await bind_tenant(self.session, None, platform_admin=True)
        try:
            plan = (
                await self.session.execute(select(Plan).where(Plan.code == plan_code))
            ).scalar_one_or_none()
            if plan is None:
                raise NotFoundError(f"No plan with code '{plan_code}'.")

            subscription = (
                await self.session.execute(
                    select(Subscription).where(Subscription.organization_id == organization_id)
                )
            ).scalar_one_or_none()
            if subscription is None:
                raise NotFoundError("That organization has no subscription.")
        finally:
            await bind_tenant(self.session, None)

        # Now bind the TARGET organization for the writes. Everything below is an
        # ordinary tenant write that the policy accepts on its own terms.
        await bind_tenant(self.session, organization_id)
        try:
            previous_plan_id = subscription.plan_id
            subscription.plan_id = plan.id
            subscription.status = SubscriptionStatus.ACTIVE

            organization = await self.session.get(Organization, organization_id)
            if organization is not None and organization.status in (
                OrganizationStatus.OVER_LIMIT,
                OrganizationStatus.PAST_DUE,
            ):
                # A manual upgrade is usually the resolution of exactly these states.
                organization.status = OrganizationStatus.ACTIVE

            self.session.add(
                SubscriptionEvent(
                    organization_id=organization_id,
                    subscription_id=subscription.id,
                    event_type="subscription.admin_override",
                    from_plan_id=previous_plan_id,
                    to_plan_id=plan.id,
                    payload={"admin_id": str(admin_id), "plan_code": plan_code},
                )
            )
            await record_platform_audit(
                self.session,
                action=PlatformAuditAction.ORGANIZATION_PLAN_OVERRIDDEN,
                actor_admin_id=admin_id,
                entity_type="subscription",
                entity_id=subscription.id,
                target_organization_id=organization_id,
                metadata={"plan_code": plan_code},
                ip=ip,
            )

            # FLUSHED BEFORE THE GUC IS CLEARED, and that ordering is load-bearing.
            #
            # SQLAlchemy defers the UPDATE until flush time. Without this, the flush
            # happens at commit -- after `finally` has unbound the organization -- so
            # the statement runs with no tenant, the RLS policy matches zero rows, and
            # it surfaces as a baffling `StaleDataError` far from its cause.
            await self.session.flush()
            return subscription
        finally:
            await bind_tenant(self.session, None)

    async def begin_impersonation(
        self,
        *,
        admin_id: UUID,
        organization_id: UUID,
        reason: str | None = None,
        ip: str | None = None,
    ) -> dict[str, Any]:
        """Open an audited, time-boxed, read-only window into one organization.

        The audit row is written BEFORE the window opens. If the request fails
        afterwards, the record of the attempt survives -- which is the property that
        makes the trail trustworthy. Writing it after would mean a crash mid-session
        leaves no evidence anyone looked.
        """
        await bind_tenant(self.session, None, platform_admin=True)
        try:
            organization = await self.session.get(Organization, organization_id)
            if organization is None or organization.deleted_at is not None:
                raise NotFoundError("Organization not found.")

            await record_platform_audit(
                self.session,
                action=PlatformAuditAction.IMPERSONATION_STARTED,
                actor_admin_id=admin_id,
                entity_type="organization",
                entity_id=organization_id,
                target_organization_id=organization_id,
                metadata={"reason": reason, "read_only": True},
                ip=ip,
            )
            return {
                "organization_id": organization_id,
                "organization_name": organization.name,
                "expires_at": datetime.now(UTC) + IMPERSONATION_TTL,
                "read_only": True,
            }
        finally:
            await bind_tenant(self.session, None)

    # -----------------------------------------------------------------------
    # Plans
    # -----------------------------------------------------------------------

    @staticmethod
    def _validate_plan_payload(limits: dict[str, Any], features: dict[str, Any]) -> None:
        """Reject a plan with missing limit or feature keys.

        Spec §6.1: "Every limit key must exist on every plan -- no missing-key
        fallbacks." A missing key with a `.get(key, 0)` fallback silently blocks a
        paying customer; with `.get(key, -1)` it silently grants unlimited usage.
        Refusing to save a malformed plan is cheaper than either.
        """
        missing_limits = REQUIRED_LIMIT_KEYS - set(limits)
        missing_features = REQUIRED_FEATURE_KEYS - set(features)
        if missing_limits or missing_features:
            raise ValidationError(
                "Plans must define every limit and feature key.",
                code="INCOMPLETE_PLAN",
                details={
                    "missing_limits": sorted(missing_limits),
                    "missing_features": sorted(missing_features),
                },
            )
        non_integer = [k for k, v in limits.items() if not isinstance(v, int)]
        if non_integer:
            raise ValidationError(
                "Every limit must be an integer (-1 for unlimited).",
                code="INVALID_LIMIT_TYPE",
                details={"invalid": sorted(non_integer)},
            )

    @staticmethod
    def _assert_not_the_free_plan(plan: Plan, action: str) -> None:
        """The `free` plan cannot be retired or deactivated.

        =====================================================================
        THIS ONE BREAKS SIGNUP ENTIRELY, AND SILENTLY
        =====================================================================
            `ensure_free_subscription` -- which runs when a new user verifies their
            email -- looks up `code = 'free' AND is_active = true`. Deactivate that
            row and the lookup finds nothing, so every verification from that moment
            raises, and every new organization is stranded between "account created"
            and "can sign in".

            Nothing about the operator's action would suggest that. They retired an
            unused-looking plan; the damage lands on people who have not signed up
            yet, so there is no existing customer to complain and no error in any
            dashboard. It surfaces days later as "nobody can register".

            Refusing outright is right rather than warning: there is no legitimate
            reason to retire the plan that every organization starts on. Renaming or
            re-pricing it is still allowed.
        """
        if plan.code == PlanCode.FREE.value:
            raise ConflictError(
                f"The free plan cannot be {action}. Every new organization is placed "
                "on it at signup, so disabling it would stop registrations from "
                "completing. You can still rename or re-price it.",
                code="FREE_PLAN_PROTECTED",
            )

    async def list_plans(self) -> list[Plan]:
        rows = await self.session.execute(select(Plan).order_by(Plan.sort_order, Plan.code))
        return list(rows.scalars().all())

    async def plan_impact(
        self, *, plan_id: UUID, proposed_limits: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Who would be affected by changing this plan's limits, and how.

        =====================================================================
        WHY THIS EXISTS AT ALL
        =====================================================================
            Editing a plan limit is the single most dangerous thing in the operator
            console, and it is dangerous in a way that is INVISIBLE at the moment of
            the mistake.

            Lowering `max_students` from 2500 to 250 succeeds instantly, changes one
            JSONB value, and produces no error. What it actually does is push every
            organization above the new figure into `over_limit`, where their next
            enrolment is refused with a 402. Nobody finds out until a school tries to
            admit a student and support tickets start arriving — by which point the
            operator has forgotten they touched it.

            So the console asks this endpoint first and shows the answer before the
            save. It is the difference between "are you sure?" — which everyone
            clicks through — and "this will block new records for 3 organizations,
            named", which people actually read.

        =====================================================================
        COMPUTED SERVER-SIDE, BECAUSE ONLY THE SERVER HAS THE NUMBERS
        =====================================================================
            The console could compare a couple of counters it already lists per
            organization, but that covers three of the six metered limits and would
            silently miss `max_custom_roles` and `storage_mb`. Doing it here means the
            answer is complete and the console cannot drift from it.

        `proposed_limits` is merged over the plan's current limits, matching what
        `update_plan` does — so an operator adjusting one field gets an impact report
        for exactly the change they are about to make. Passing None reports the
        current state, which is what the retire flow wants.
        """
        plan = await self.session.get(Plan, plan_id)
        if plan is None:
            raise NotFoundError("Plan not found.")

        limits = {**plan.limits, **(proposed_limits or {})}

        await bind_tenant(self.session, None, platform_admin=True)
        try:
            rows = (
                await self.session.execute(
                    select(Organization, OrganizationUsage)
                    .join(Subscription, Subscription.organization_id == Organization.id)
                    .outerjoin(
                        OrganizationUsage,
                        OrganizationUsage.organization_id == Organization.id,
                    )
                    .where(
                        Subscription.plan_id == plan_id,
                        Organization.deleted_at.is_(None),
                    )
                    .order_by(Organization.name)
                )
            ).all()

            affected: list[dict[str, Any]] = []
            for organization, usage in rows:
                if usage is None:
                    continue

                breaches = [
                    {
                        "key": key,
                        "current": getattr(usage, counter),
                        "allowed": int(limits[key]),
                    }
                    for key, counter in OrganizationUsage.LIMIT_TO_COUNTER.items()
                    # `-1` is unlimited and can never be breached. A missing key is a
                    # malformed plan, which `_validate_plan_payload` rejects before a
                    # save -- so it is skipped here rather than crashing the preview.
                    if key in limits
                    and int(limits[key]) != UNLIMITED
                    and getattr(usage, counter) > int(limits[key])
                ]

                if breaches:
                    affected.append(
                        {
                            "organization_id": organization.id,
                            "name": organization.name,
                            "slug": organization.slug,
                            "breaches": breaches,
                        }
                    )

            return {
                "plan_id": plan_id,
                "plan_code": plan.code,
                "subscriber_count": len(rows),
                "would_exceed": affected,
            }
        finally:
            await bind_tenant(self.session, None)

    async def create_plan(self, *, admin_id: UUID, data: dict[str, Any]) -> Plan:
        self._validate_plan_payload(data["limits"], data["features"])

        clash = (
            await self.session.execute(select(Plan.id).where(Plan.code == data["code"]))
        ).scalar_one_or_none()
        if clash is not None:
            raise ConflictError(
                f"A plan with code '{data['code']}' already exists.", code="PLAN_CODE_TAKEN"
            )

        plan = Plan(**data)
        self.session.add(plan)
        await self.session.flush()

        await record_platform_audit(
            self.session,
            action=PlatformAuditAction.PLAN_CREATED,
            actor_admin_id=admin_id,
            entity_type="plan",
            entity_id=plan.id,
            metadata={"code": plan.code},
        )
        return plan

    async def update_plan(self, *, admin_id: UUID, plan_id: UUID, changes: dict[str, Any]) -> Plan:
        plan = await self.session.get(Plan, plan_id)
        if plan is None:
            raise NotFoundError("Plan not found.")

        # `limits` and `features` MERGE rather than replace, so a request adjusting
        # one limit does not have to resend all six -- and cannot silently drop the
        # five it omitted, which validation would then reject as an incomplete plan.
        merged_limits = {**plan.limits, **changes.get("limits", {})}
        merged_features = {**plan.features, **changes.get("features", {})}
        self._validate_plan_payload(merged_limits, merged_features)

        # Deactivating the free plan through a PATCH is the same catastrophe as
        # retiring it, reached by a different route. Guarded in both places rather
        # than only on the obvious one.
        if changes.get("is_active") is False:
            self._assert_not_the_free_plan(plan, "deactivated")

        scalar_changes = {k: v for k, v in changes.items() if k not in ("limits", "features")}
        for field, value in scalar_changes.items():
            setattr(plan, field, value)
        plan.limits = merged_limits
        plan.features = merged_features

        await record_platform_audit(
            self.session,
            action=PlatformAuditAction.PLAN_UPDATED,
            actor_admin_id=admin_id,
            entity_type="plan",
            entity_id=plan.id,
            metadata={"changed": sorted(changes)},
        )
        return plan

    async def retire_plan(self, *, admin_id: UUID, plan_id: UUID) -> Plan:
        """Retire a plan. NEVER a hard delete.

        Deleting would orphan the subscriptions of every customer on it -- and the
        FK is RESTRICT, so it would simply fail. `is_active = false` stops new
        signups while leaving existing customers on the terms they agreed to, and
        preserves the historical record of what those terms were.
        """
        plan = await self.session.get(Plan, plan_id)
        if plan is None:
            raise NotFoundError("Plan not found.")

        self._assert_not_the_free_plan(plan, "retired")

        subscribers = (
            await self.session.execute(
                select(func.count())
                .select_from(Subscription)
                .where(Subscription.plan_id == plan_id)
            )
        ).scalar_one()

        plan.is_active = False
        plan.is_public = False

        await record_platform_audit(
            self.session,
            action=PlatformAuditAction.PLAN_DELETED,
            actor_admin_id=admin_id,
            entity_type="plan",
            entity_id=plan.id,
            metadata={"code": plan.code, "active_subscribers": subscribers},
        )
        return plan

    # -----------------------------------------------------------------------
    # Metrics
    # -----------------------------------------------------------------------

    async def metrics(self) -> dict[str, Any]:
        """Platform-wide numbers for the operator dashboard (spec §8).

        MRR is computed by normalising each subscription to a monthly figure -- a
        yearly plan contributes one twelfth per month. Summing raw prices across
        mixed billing cycles is the standard way to overstate MRR by an order of
        magnitude the moment annual plans sell.
        """
        await bind_tenant(self.session, None, platform_admin=True)
        try:
            total_orgs = (
                await self.session.execute(
                    select(func.count())
                    .select_from(Organization)
                    .where(Organization.deleted_at.is_(None))
                )
            ).scalar_one()

            by_status: dict[OrganizationStatus, int] = dict(
                (
                    await self.session.execute(
                        select(Organization.status, func.count())
                        .where(Organization.deleted_at.is_(None))
                        .group_by(Organization.status)
                    )
                ).all()  # type: ignore[arg-type]
            )

            paying = (
                await self.session.execute(
                    select(Subscription.billing_cycle, Plan.price_monthly, Plan.price_yearly)
                    .join(Plan, Plan.id == Subscription.plan_id)
                    .where(
                        Subscription.status.in_(
                            [SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE]
                        )
                    )
                )
            ).all()

            mrr = Decimal("0")
            for cycle, monthly, yearly in paying:
                if cycle.value == "yearly" and yearly:
                    mrr += Decimal(yearly) / 12
                elif monthly:
                    mrr += Decimal(monthly)

            total_schools = (
                await self.session.execute(
                    select(func.count()).select_from(School).where(School.deleted_at.is_(None))
                )
            ).scalar_one()

            seats = (
                await self.session.execute(
                    select(func.coalesce(func.sum(OrganizationUsage.staff_count), 0))
                )
            ).scalar_one()

            failed_payments = (
                await self.session.execute(
                    select(func.count())
                    .select_from(Payment)
                    .where(
                        Payment.status == PaymentStatus.FAILED,
                        Payment.created_at >= datetime.now(UTC) - timedelta(days=30),
                    )
                )
            ).scalar_one()

            cancelled = int(by_status.get(OrganizationStatus.CANCELLED, 0))
            return {
                "organizations_total": total_orgs,
                "organizations_by_status": {
                    k.value if hasattr(k, "value") else str(k): v for k, v in by_status.items()
                },
                "schools_total": total_schools,
                "staff_seats_total": int(seats or 0),
                "mrr": mrr.quantize(Decimal("0.01")),
                "failed_payments_30d": failed_payments,
                # Cumulative churn -- share of all organizations ever created that are
                # now cancelled. NOT period churn, which needs a cohort window; this
                # is a health indicator, not a reporting figure.
                "churn_rate": (round(cancelled / total_orgs, 4) if total_orgs else 0.0),
            }
        finally:
            await bind_tenant(self.session, None)


async def create_platform_admin(
    session: AsyncSession, *, email: str, password: str, full_name: str
) -> PlatformAdmin:
    """Create an operator account. Called ONLY by the seed CLI (spec §11.3).

    Lives here rather than in the CLI so the hashing and the uniqueness check are
    shared with any future rotation command, and so there is exactly one place that
    can mint an account with platform-wide reach.
    """
    existing = (
        await session.execute(select(PlatformAdmin).where(PlatformAdmin.email == email))
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    admin = PlatformAdmin(
        email=email,
        password_hash=hash_password(password),
        full_name=full_name,
        is_active=True,
    )
    session.add(admin)
    await session.flush()
    return admin
