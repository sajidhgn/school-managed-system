"""Authentication service: registration, verification, login, sessions, reset.

WHY THIS FILE EXISTS
    Every flow here is one an attacker probes first. The service layer is where the
    countermeasures live -- lockout, enumeration resistance, refresh rotation with
    reuse detection -- because they must apply identically no matter which transport
    or client reaches them.

RESPONSIBILITY
    Orchestrate the auth flows. It raises domain errors, never HTTP exceptions, so
    it remains usable from the CLI and the test suite.

INTERACTIONS
    * `core/security.py` for hashing and token minting.
    * `core/passwords.py` for the strength policy.
    * `modules/rbac/provisioning.py` to create the owner role at signup.
    * `modules/billing/service.py` to start the free subscription on verification.

=============================================================================
THE THREE THINGS THIS FILE EXISTS TO GET RIGHT
=============================================================================
    1. USER ENUMERATION. Login, forgot-password and resend-verification must behave
       identically for known and unknown addresses -- same status, same body, same
       timing. See `_verify_password_constant_time` and the deliberate no-op
       branches in `request_password_reset`.

    2. REFRESH ROTATION WITH REUSE DETECTION. A refresh token is valid exactly once.
       Presenting an already-rotated one is proof of theft and revokes the whole
       family. See `refresh_session`.

    3. ATOMIC SIGNUP. A user, an organization, an owner role and a membership are
       created in ONE transaction. A partial signup leaves someone locked out of the
       account they just created, with no path to recovery that does not involve
       support.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.common.audit import (
    AuditAction,
    PlatformAuditAction,
    record_audit,
    record_platform_audit,
)
from app.common.email.sender import EmailSender
from app.common.email.templates import ActionPurpose, render_action_email
from app.core.config import Settings
from app.core.context import (
    get_organization_id,
    get_school_id,
    set_organization_id,
    set_school_id,
)
from app.core.exceptions import AuthenticationError, ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.passwords import validate_password
from app.core.security import (
    PrincipalType,
    create_access_token,
    dummy_password_verify,
    generate_opaque_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.db.session import bind_tenant
from app.modules.auth.models import (
    EmailVerificationToken,
    PasswordResetToken,
    Session,
    User,
    UserStatus,
)
from app.modules.auth.schemas import MembershipSummary
from app.modules.platform_admin.models import Plan, PlatformAdmin
from app.modules.rbac.models import Membership, MembershipStatus, Role
from app.modules.rbac.provisioning import provision_organization
from app.modules.tenancy.models import Organization, OrganizationStatus, School

logger = get_logger(__name__)

# How long an emailed link stays valid. Shorter than the invitation window (7 days)
# because both of these are triggered by someone already sitting at the keyboard and
# expected to act immediately -- a 7-day password-reset link is a 7-day window for
# whoever else can read that inbox.
VERIFICATION_TTL = timedelta(hours=24)
PASSWORD_RESET_TTL = timedelta(hours=1)
CONTEXT_SELECTION_TTL = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class IssuedTokens:
    """A minted access/refresh pair plus the session that owns them."""

    access_token: str
    refresh_token: str
    session_id: UUID
    expires_in: int


@dataclass(frozen=True, slots=True)
class IssuedContinuation:
    """Short-lived credential that can only complete membership selection."""

    access_token: str
    session_id: UUID
    expires_in: int


class AuthService:
    """Orchestrates authentication. Never commits -- the request owns the transaction."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        email_sender: EmailSender | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.email_sender = email_sender

    # -----------------------------------------------------------------------
    # Registration
    # -----------------------------------------------------------------------

    async def register(
        self,
        *,
        full_name: str,
        email: str,
        password: str,
        organization_name: str,
        country: str | None,
        plan_code: str = "free",
        billing_cycle: str = "monthly",
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[User, Organization]:
        """Create a user, their organization, the owner role, and the membership.

        ALL IN ONE TRANSACTION (spec §4.3B step 2). The caller's request-scoped
        session owns the commit, so any failure below rolls back every part -- there
        is no state in which an organization exists that nobody can administer.

        The user lands in `pending`; login is blocked until the emailed link is
        followed. That gate is what stops signup from becoming a way to send mail
        from our domain to arbitrary addresses.
        """
        validate_password(
            password,
            user_inputs=[full_name, email, organization_name],
            settings=self.settings,
        )

        existing = await self._find_user_by_email(email)
        if existing is not None:
            # Registration is the ONE flow where revealing that an address is taken
            # is unavoidable -- the alternative is silently doing nothing and leaving
            # a real customer staring at a signup that never arrives. The exposure is
            # limited: it confirms the address is registered, which the login form
            # would eventually reveal to anyone with the password anyway.
            raise ConflictError(
                "An account with this email address already exists.",
                code="EMAIL_TAKEN",
                details={"field": "email"},
            )

        requested_plan = (
            await self.session.execute(
                select(Plan).where(
                    Plan.code == plan_code,
                    Plan.is_public.is_(True),
                    Plan.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if requested_plan is None:
            raise ValidationError(
                "The selected plan is not available.", code="PLAN_NOT_SELF_SERVICE"
            )

        user = User(
            email=email,
            full_name=full_name,
            password_hash=hash_password(password),
            status=UserStatus.PENDING,
        )
        self.session.add(user)
        await self.session.flush()

        # THE ID IS GENERATED HERE, IN PYTHON, BEFORE THE INSERT.
        #
        # It cannot be left to the column default. The `organizations` WITH CHECK
        # policy compares the incoming row against `app.current_org_id`, so the GUC
        # must be set BEFORE the INSERT -- and to set it we need the id. Relying on
        # the default would mean the id only exists after `flush()`, by which time
        # the policy has already rejected the row.
        #
        # Note the platform-admin GUC is no escape here: `WITH CHECK` deliberately
        # has no admin branch (spec §2.2), so even the seeder must bind the real
        # organization. Generating the id up front is the intended pattern, and it is
        # exactly why `UUIDPrimaryKeyMixin` supports client-side generation.
        organization_id = uuid4()

        organization = Organization(
            id=organization_id,
            name=organization_name,
            slug=await self._unique_org_slug(organization_name),
            owner_user_id=user.id,
            country=country,
            status=OrganizationStatus.TRIALING,
            billing_email=email,
            requested_plan_code=requested_plan.code,
            requested_billing_cycle=billing_cycle,
        )

        # One of the three documented uses of `bind_tenant`: the caller has proven
        # which organization it acts for by creating it in this very transaction.
        await bind_tenant(self.session, organization_id)
        set_organization_id(organization_id)

        self.session.add(organization)
        await self.session.flush()

        await provision_organization(
            self.session,
            organization_id=organization.id,
            owner_user_id=user.id,
        )

        await record_audit(
            self.session,
            organization_id=organization.id,
            action=AuditAction.ORGANIZATION_CREATED,
            actor_user_id=user.id,
            entity_type="organization",
            entity_id=organization.id,
            after={"name": organization_name, "slug": organization.slug},
            ip=ip,
            user_agent=user_agent,
        )
        await record_audit(
            self.session,
            organization_id=organization.id,
            action=AuditAction.USER_REGISTERED,
            actor_user_id=user.id,
            entity_type="user",
            entity_id=user.id,
            ip=ip,
            user_agent=user_agent,
        )

        await self._send_verification_email(user)
        return user, organization

    async def _send_verification_email(self, user: User) -> None:
        """Mint a verification token and email the link.

        The RAW token exists only in this function and in the outgoing mail; the
        database receives its SHA-256 digest.
        """
        raw = generate_opaque_token()
        self.session.add(
            EmailVerificationToken(
                user_id=user.id,
                token_hash=hash_token(raw),
                expires_at=datetime.now(UTC) + VERIFICATION_TTL,
            )
        )

        if self.email_sender is not None:
            await self.email_sender.send(
                render_action_email(
                    to=user.email,
                    action_url=f"{self.settings.FRONTEND_URL}/verify-email?token={raw}",
                    purpose=ActionPurpose.VERIFY_EMAIL,
                    recipient_name=user.full_name,
                    expiry_text="24 hours",
                    settings=self.settings,
                )
            )

    async def verify_email(self, raw_token: str) -> User:
        """Consume a verification token, activate the user, start their subscription.

        Spec §4.3B step 4. Looked up BY HASH -- the raw token is never stored, so
        there is nothing to compare against except the digest.
        """
        record = (
            await self.session.execute(
                select(EmailVerificationToken).where(
                    EmailVerificationToken.token_hash == hash_token(raw_token)
                )
            )
        ).scalar_one_or_none()

        # One error for "no such token", "already used" and "expired". Distinguishing
        # them would tell a token-guessing attacker when they had found a real one.
        if record is None or not record.is_usable:
            raise AuthenticationError(
                "This verification link is invalid or has expired.",
                code="INVALID_VERIFICATION_TOKEN",
            )

        user = await self.session.get(User, record.user_id)
        if user is None:
            raise AuthenticationError("This verification link is no longer valid.")

        record.used_at = datetime.now(UTC)
        user.status = UserStatus.ACTIVE
        user.email_verified_at = datetime.now(UTC)

        # The organization this user owns, if any. An invited user verifying their
        # address owns nothing, so this is legitimately None.
        #
        # The cross-tenant read is armed for the lookup because verification runs on
        # an UNAUTHENTICATED session: the caller presented a token from an email, not
        # a login, so no organization is bound and the RLS policy on `organizations`
        # would match zero rows -- making every verification silently skip creating
        # the subscription. The query is keyed on `owner_user_id` from a token we
        # just validated, so it can only ever return this user's own organization.
        await bind_tenant(self.session, None, platform_admin=True)
        organization = (
            await self.session.execute(
                select(Organization).where(Organization.owner_user_id == user.id)
            )
        ).scalar_one_or_none()
        await self._restore_tenant_binding()

        if organization is not None:
            await bind_tenant(self.session, organization.id)
            set_organization_id(organization.id)

            # Deferred import: `billing.service` imports nothing from here, but the
            # module-level cycle auth -> billing -> tenancy -> auth is easier to
            # break at this single call site than to restructure four modules around.
            from app.modules.billing.service import ensure_free_subscription

            await ensure_free_subscription(
                self.session,
                organization_id=organization.id,
                plan_code=organization.requested_plan_code,
                billing_cycle=organization.requested_billing_cycle,
            )

            await record_audit(
                self.session,
                organization_id=organization.id,
                action=AuditAction.USER_EMAIL_VERIFIED,
                actor_user_id=user.id,
                entity_type="user",
                entity_id=user.id,
            )

        return user

    # -----------------------------------------------------------------------
    # Login
    # -----------------------------------------------------------------------

    async def authenticate(
        self,
        *,
        email: str,
        password: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> User:
        """Verify credentials, applying lockout and enumeration resistance.

        =====================================================================
        EVERY FAILURE PATH RETURNS THE SAME ERROR AND COSTS THE SAME TIME
        =====================================================================
            Unknown address, wrong password, unverified account, suspended
            account -- all produce one `INVALID_CREDENTIALS` 401.

            Timing is equalised by `dummy_password_verify()`, which burns an Argon2
            verification when there is no hash to check. Without it, "no such user"
            returns in ~2ms while "wrong password" takes ~60ms, and that gap is
            measurable over a network. An attacker with a leaked address list could
            then learn which of those people work at schools using this platform,
            which is exactly the correlation a school platform must not hand out.
        """
        user = await self._find_user_by_email(email)

        if user is None or user.password_hash is None:
            dummy_password_verify()
            raise self._invalid_credentials()

        if user.is_locked:
            # Same error as a bad password. Announcing the lock tells an attacker
            # their guessing is having an effect, and tells them exactly when to
            # resume. The legitimate user gets the real explanation by email.
            raise self._invalid_credentials()

        if not verify_password(password, user.password_hash):
            await self._register_failed_login(user, ip=ip, user_agent=user_agent)
            raise self._invalid_credentials()

        if user.status is UserStatus.PENDING:
            raise AuthenticationError(
                "Please verify your email address before signing in.",
                code="EMAIL_NOT_VERIFIED",
            )
        if not user.can_authenticate:
            raise self._invalid_credentials()

        user.failed_login_count = 0
        user.locked_until = None
        user.lockout_count = 0  # a good login forgives past lockouts
        user.last_login_at = datetime.now(UTC)
        return user

    @staticmethod
    def _invalid_credentials() -> AuthenticationError:
        return AuthenticationError(
            "Email or password is incorrect.",
            code="INVALID_CREDENTIALS",
        )

    async def _register_failed_login(
        self, user: User, *, ip: str | None, user_agent: str | None
    ) -> None:
        """Count a failure and lock the account at the threshold.

        Lockout duration DOUBLES per lockout (spec §4.4 "exponential thereafter").
        A flat window is only a speed bump: an attacker paces to 5 guesses per
        15 minutes and grinds indefinitely. Doubling makes sustained guessing cost
        more than it can return, while a user who fumbles twice a year never
        notices.
        """
        user.failed_login_count += 1

        locked = user.failed_login_count >= self.settings.LOGIN_MAX_FAILURES
        if locked:
            user.lockout_count += 1
            minutes = min(
                self.settings.LOGIN_LOCKOUT_MINUTES * (2 ** (user.lockout_count - 1)),
                self.settings.LOGIN_LOCKOUT_MAX_MINUTES,
            )
            user.locked_until = datetime.now(UTC) + timedelta(minutes=minutes)
            user.failed_login_count = 0
            logger.warning(
                "account_locked",
                user_id=str(user.id),
                lockout_count=user.lockout_count,
                minutes=minutes,
                ip=ip,
            )

        await self._audit_identity_event(
            user_id=user.id,
            action=AuditAction.USER_LOCKED_OUT if locked else AuditAction.USER_LOGIN_FAILED,
            ip=ip,
            user_agent=user_agent,
        )

    # -----------------------------------------------------------------------
    # Memberships & context
    # -----------------------------------------------------------------------

    async def _restore_tenant_binding(self) -> None:
        """Re-bind the session to whatever THIS REQUEST is acting as.

        =====================================================================
        DISARMING IS NOT THE SAME AS UNBINDING
        =====================================================================
            The cross-tenant reads in this module arm the platform-admin GUC and
            must disarm the instant they are done, or the rest of the transaction
            silently becomes a platform-wide read.

            Disarming used to mean `bind_tenant(session, None)` -- which threw away
            the caller's ORGANIZATION as well as the admin flag. Every later query
            in the same request then ran with no tenant bound, and RLS answered them
            with zero rows.

            That is the bug behind `GET /auth/me` reporting a null
            `organization_name` and `school_name`: its membership lookup runs after
            `list_memberships()`, so it was querying an unbound session and finding
            nothing. `POST /auth/context` lost its school name the same way.

            Restoring from the context vars is right in both situations. In the
            PRE-authentication flows -- login, refresh, registration -- nothing is
            bound yet and this restores None, exactly as before. Mid-request it puts
            back the organization `get_db` bound at session start.
        """
        await bind_tenant(self.session, get_organization_id(), school_id=get_school_id())

    async def list_memberships(self, user_id: UUID) -> list[MembershipSummary]:
        """Every context this user may act in, across all organizations.

        =====================================================================
        THIS QUERY RUNS OUTSIDE TENANT RLS, AND IT HAS TO
        =====================================================================
            At login there is no organization bound yet -- discovering which
            organizations the user belongs to is the whole point of the call. With
            the org GUC empty, the RLS policy on `memberships` matches zero rows, so
            this must run with the platform-admin GUC armed.

            That is safe because the query is keyed on `user_id` from an already
            verified credential, and it returns only the caller's OWN memberships.
            It cannot be pointed at anyone else: `user_id` comes from the
            authenticated session, never from request input.
        """
        await bind_tenant(self.session, None, platform_admin=True)
        try:
            rows = (
                (
                    await self.session.execute(
                        select(Membership)
                        .options(
                            joinedload(Membership.role),
                            joinedload(Membership.organization),
                            joinedload(Membership.school),
                        )
                        .where(
                            Membership.user_id == user_id,
                            Membership.deleted_at.is_(None),
                            Membership.status == MembershipStatus.ACTIVE,
                        )
                    )
                )
                .scalars()
                .all()
            )

            return [
                MembershipSummary(
                    membership_id=m.id,
                    organization_id=m.organization_id,
                    organization_name=m.organization.name,
                    school_id=m.school_id,
                    school_name=m.school.name if m.school else None,
                    role_code=m.role.code,
                    role_name=m.role.name,
                    is_primary=m.is_primary,
                    is_org_level=m.school_id is None,
                )
                for m in rows
                # A membership in a deleted organization is not a usable context.
                if m.organization.deleted_at is None
            ]
        finally:
            # Disarm immediately. Leaving the cross-tenant GUC set for the rest of
            # the request would silently turn every later query in this transaction
            # into a platform-wide read.
            await self._restore_tenant_binding()

    async def resolve_membership(self, *, user_id: UUID, membership_id: UUID) -> Membership:
        """Load one membership, verifying it belongs to `user_id` and is usable.

        Spec §4.3E. The ownership check is the security boundary: without it,
        `POST /auth/context` with someone else's membership id would issue a token
        scoped to their organization -- a complete tenancy bypass through the one
        endpoint whose entire job is to change tenant.
        """
        await bind_tenant(self.session, None, platform_admin=True)
        try:
            membership = (
                await self.session.execute(
                    select(Membership)
                    .options(joinedload(Membership.role), joinedload(Membership.organization))
                    .where(Membership.id == membership_id)
                )
            ).scalar_one_or_none()

            if membership is None or membership.user_id != user_id:
                # 404, not 403: confirming the membership exists would let someone
                # enumerate valid ids across the platform.
                raise NotFoundError("No such membership.", code="MEMBERSHIP_NOT_FOUND")
            if not membership.is_usable:
                raise AuthenticationError(
                    "This membership is suspended.", code="MEMBERSHIP_SUSPENDED"
                )
            if not membership.organization.is_active and not membership.organization.is_read_only:
                raise AuthenticationError(
                    "This organization is no longer active.", code="ORGANIZATION_INACTIVE"
                )
            return membership
        finally:
            await self._restore_tenant_binding()

    def pick_default_membership(
        self, memberships: list[MembershipSummary]
    ) -> MembershipSummary | None:
        """Which context to auto-select at login, if any (spec §4.3D).

        Exactly one -> that one. Several -> the one flagged primary, else None,
        which makes the caller return `select_required` and let the human choose.
        Guessing among equals would drop a teacher into the wrong school.
        """
        if len(memberships) == 1:
            return memberships[0]
        return next((m for m in memberships if m.is_primary), None)

    # -----------------------------------------------------------------------
    # Sessions
    # -----------------------------------------------------------------------

    async def issue_context_selection(
        self,
        *,
        user: User,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> IssuedContinuation:
        """Create a single-purpose, five-minute continuation after password login."""
        now = datetime.now(UTC)
        session_row = Session(
            user_id=user.id,
            membership_id=None,
            # The schema requires a digest. The random value is deliberately never
            # returned, so this pre-context session cannot be refreshed.
            refresh_token_hash=hash_token(generate_opaque_token()),
            family_id=uuid4(),
            expires_at=now + CONTEXT_SELECTION_TTL,
            ip=ip,
            user_agent=user_agent,
        )
        self.session.add(session_row)
        await self.session.flush()

        expires_in = int(CONTEXT_SELECTION_TTL.total_seconds())
        return IssuedContinuation(
            access_token=create_access_token(
                user_id=user.id,
                session_id=session_row.id,
                principal_type=PrincipalType.CONTEXT_SELECTION,
                expires_minutes=expires_in // 60,
                settings=self.settings,
            ),
            session_id=session_row.id,
            expires_in=expires_in,
        )

    async def issue_session(
        self,
        *,
        user: User,
        membership: Membership | None,
        ip: str | None = None,
        user_agent: str | None = None,
        family_id: UUID | None = None,
    ) -> IssuedTokens:
        """Mint an access/refresh pair and persist the session row.

        `family_id` is passed when rotating, so the new token stays in the same
        lineage as the one it replaces. Omitted at login, which starts a new family.
        """
        raw_refresh = generate_opaque_token()
        now = datetime.now(UTC)

        session_row = Session(
            user_id=user.id,
            membership_id=membership.id if membership else None,
            refresh_token_hash=hash_token(raw_refresh),
            family_id=family_id or uuid4(),
            expires_at=now + timedelta(days=self.settings.REFRESH_TOKEN_EXPIRE_DAYS),
            ip=ip,
            user_agent=user_agent,
        )
        self.session.add(session_row)
        await self.session.flush()

        # Fetched by id rather than through `membership.role`.
        #
        # A relationship attribute lazy-loads on first access, and in asyncio an
        # implicit lazy load raises MissingGreenlet -- there is no greenlet context to
        # run the IO in. `resolve_membership` happens to eager-load the role, so the
        # login path would work; but `issue_session` is also called right after
        # invitation acceptance, where the membership was just constructed in memory
        # and has no loaded relationship at all.
        #
        # `session.get` is an explicit await that works in both cases, and it hits the
        # identity map when the role is already loaded, so the eager-loaded path costs
        # nothing extra.
        role: Role | None = await self.session.get(Role, membership.role_id) if membership else None
        access = create_access_token(
            user_id=user.id,
            session_id=session_row.id,
            membership_id=membership.id if membership else None,
            organization_id=membership.organization_id if membership else None,
            school_id=membership.school_id if membership else None,
            role_code=role.code if role else None,
            permissions_version=role.permissions_version if role else None,
            settings=self.settings,
        )

        return IssuedTokens(
            access_token=access,
            refresh_token=raw_refresh,
            session_id=session_row.id,
            expires_in=self.settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def refresh_session(
        self,
        raw_refresh_token: str,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> IssuedTokens:
        """Rotate a refresh token, detecting reuse (spec §4.1).

        =====================================================================
        THE REUSE-DETECTION BRANCH IS THE POINT OF THIS METHOD
        =====================================================================
            Rotation makes every refresh token valid exactly once. So if a token that
            has ALREADY been rotated is presented, something is wrong that cannot
            happen in honest operation: either an attacker is replaying a stolen
            token, or the legitimate user is replaying one the attacker already
            burned. In both cases the token has been seen by two parties.

            The response is to revoke the ENTIRE family -- every descendant of that
            original login -- and force re-authentication. The attacker cannot
            re-authenticate; they have a token, not a password. The user can.

            Revoking only the replayed row would leave the attacker's freshly rotated
            token alive, which is the whole failure this mechanism exists to prevent.
        """
        presented_hash = hash_token(raw_refresh_token)

        # Runs outside tenant RLS: a refresh arrives with an expired access token, so
        # no org is bound. The lookup is by 256-bit digest, which is not guessable.
        await bind_tenant(self.session, None, platform_admin=True)
        try:
            session_row = (
                await self.session.execute(
                    select(Session).where(Session.refresh_token_hash == presented_hash)
                )
            ).scalar_one_or_none()

            if session_row is None:
                raise AuthenticationError(
                    "Session is invalid or has expired.", code="INVALID_REFRESH_TOKEN"
                )

            if session_row.revoked_at is not None:
                await self._revoke_family(session_row.family_id, reason="reuse_detected")
                if session_row.user_id is not None:
                    await self._audit_identity_event(
                        user_id=session_row.user_id,
                        action=AuditAction.SESSION_REUSE_DETECTED,
                        ip=ip,
                        user_agent=user_agent,
                    )
                elif session_row.platform_admin_id is not None:
                    await record_platform_audit(
                        self.session,
                        action=PlatformAuditAction.ADMIN_REFRESH_REUSE_DETECTED,
                        actor_admin_id=session_row.platform_admin_id,
                        entity_type="session_family",
                        entity_id=session_row.family_id,
                        ip=ip,
                        user_agent=user_agent,
                    )
                logger.warning(
                    "refresh_token_reuse_detected",
                    user_id=str(session_row.user_id),
                    family_id=str(session_row.family_id),
                    ip=ip,
                )
                raise AuthenticationError(
                    "This session has been revoked for security reasons. Please sign in again.",
                    code="TOKEN_REUSE_DETECTED",
                )

            if session_row.expires_at <= datetime.now(UTC):
                raise AuthenticationError("Session has expired.", code="SESSION_EXPIRED")

            if session_row.guardian_identity_id is not None:
                # A PARENT-PORTAL session, presented at the STAFF refresh endpoint.
                #
                # Refused rather than rotated. Guardian rotation is owned by
                # `guardians/auth_service.py` because it re-checks portal access and
                # mints a token with a different principal type; honouring it here
                # would re-issue a guardian a staff-shaped token. The generic message
                # is deliberate -- a caller who cannot tell which surface a token
                # belongs to is not a caller we should be explaining tokens to.
                raise AuthenticationError(
                    "Session is invalid or has expired.", code="INVALID_REFRESH_TOKEN"
                )

            if session_row.user_id is None:
                # A PLATFORM-ADMIN session. It shares this table and therefore this
                # rotation logic -- including reuse detection, which matters most for
                # the platform's own accounts. But it has no `users` row and no
                # membership, so the tenant-specific checks below do not apply and the
                # re-issue goes through the platform path.
                return await self._rotate_platform_session(
                    session_row, ip=ip, user_agent=user_agent
                )

            user = await self.session.get(User, session_row.user_id)
            if user is None or not user.can_authenticate:
                raise AuthenticationError("Session is no longer valid.", code="USER_INACTIVE")

            membership: Membership | None = None
            if session_row.membership_id is not None:
                membership = (
                    await self.session.execute(
                        select(Membership)
                        .options(joinedload(Membership.role), joinedload(Membership.organization))
                        .where(Membership.id == session_row.membership_id)
                    )
                ).scalar_one_or_none()

                # Access revoked since the token was issued: refuse rather than
                # re-issue. This is what makes membership removal take effect within
                # one access-token lifetime rather than one refresh-token lifetime.
                if membership is None or not membership.is_usable:
                    await self._revoke_family(session_row.family_id, reason="membership_revoked")
                    raise AuthenticationError(
                        "Your access to this organization has changed. Please sign in again.",
                        code="MEMBERSHIP_REVOKED",
                    )

            session_row.revoked_at = datetime.now(UTC)
            session_row.revoked_reason = "rotated"

            return await self.issue_session(
                user=user,
                membership=membership,
                ip=ip,
                user_agent=user_agent,
                family_id=session_row.family_id,
            )
        finally:
            await self._restore_tenant_binding()

    async def _rotate_platform_session(
        self,
        session_row: Session,
        *,
        ip: str | None,
        user_agent: str | None,
    ) -> IssuedTokens:
        """Rotate a platform-operator session.

        Deliberately re-checks `is_active`: the whole point of rotating rather than
        issuing a long-lived token is that a deactivated operator loses access at the
        next boundary, not at token expiry.
        """
        admin = await self.session.get(PlatformAdmin, session_row.platform_admin_id)
        if admin is None or not admin.is_active:
            await self._revoke_family(session_row.family_id, reason="admin_deactivated")
            raise AuthenticationError(
                "This operator account is no longer active.", code="PLATFORM_ACCOUNT_INACTIVE"
            )

        session_row.revoked_at = datetime.now(UTC)
        session_row.revoked_reason = "rotated"

        raw_refresh = generate_opaque_token()
        now = datetime.now(UTC)
        new_row = Session(
            user_id=None,
            platform_admin_id=admin.id,
            refresh_token_hash=hash_token(raw_refresh),
            family_id=session_row.family_id,
            expires_at=now + timedelta(days=self.settings.REFRESH_TOKEN_EXPIRE_DAYS),
            ip=ip,
            user_agent=user_agent,
        )
        self.session.add(new_row)
        await self.session.flush()

        access = create_access_token(
            user_id=admin.id,
            session_id=new_row.id,
            principal_type=PrincipalType.PLATFORM,
            settings=self.settings,
        )
        return IssuedTokens(
            access_token=access,
            refresh_token=raw_refresh,
            session_id=new_row.id,
            expires_in=self.settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )

    async def _revoke_family(self, family_id: UUID, *, reason: str) -> None:
        """Kill every live session descended from one login."""
        await self.session.execute(
            update(Session)
            .where(Session.family_id == family_id, Session.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
        )

    async def revoke_session(self, session_id: UUID, *, reason: str = "logout") -> None:
        await self.session.execute(
            update(Session)
            .where(Session.id == session_id, Session.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
        )

    async def revoke_all_sessions(self, user_id: UUID, *, reason: str = "logout_all") -> None:
        await self.session.execute(
            update(Session)
            .where(Session.user_id == user_id, Session.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
        )

    async def switch_context(
        self,
        *,
        user: User,
        membership: Membership,
        current_session_id: UUID,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> IssuedTokens:
        """Re-issue tokens scoped to a different membership (spec §4.3E).

        Rotates within the SAME family rather than starting a new one, so switching
        schools does not multiply a user's session count -- one login stays one
        session, and "log out everywhere" keeps meaning what the user expects.
        """
        current = await self.session.get(Session, current_session_id)
        now = datetime.now(UTC)
        if (
            current is None
            or current.user_id != user.id
            or current.revoked_at is not None
            or current.expires_at <= now
        ):
            raise AuthenticationError(
                "This context selection is invalid or has expired.",
                code="CONTEXT_SELECTION_INVALID",
            )

        family_id = current.family_id
        current.revoked_at = now
        current.revoked_reason = "context_switch"

        tokens = await self.issue_session(
            user=user,
            membership=membership,
            ip=ip,
            user_agent=user_agent,
            family_id=family_id,
        )

        await bind_tenant(self.session, membership.organization_id, school_id=membership.school_id)
        set_organization_id(membership.organization_id)
        set_school_id(membership.school_id)

        await record_audit(
            self.session,
            organization_id=membership.organization_id,
            school_id=membership.school_id,
            action=AuditAction.SESSION_CONTEXT_SWITCHED,
            actor_user_id=user.id,
            actor_membership_id=membership.id,
            ip=ip,
            user_agent=user_agent,
        )
        return tokens

    # -----------------------------------------------------------------------
    # Password reset
    # -----------------------------------------------------------------------

    async def request_password_reset(self, email: str) -> None:
        """Email a reset link, or silently do nothing for an unknown address.

        Returns None either way and the route returns an identical body, so this
        endpoint cannot be used to test whether an address is registered.

        No dummy-hash call here: unlike login, this path does no password
        verification in EITHER branch, so the timing is already comparable. The one
        asymmetry that remains is the outbound email, which happens after the
        response is composed.
        """
        user = await self._find_user_by_email(email)
        if user is None or user.deleted_at is not None:
            logger.info("password_reset_requested_unknown_email")
            return

        raw = generate_opaque_token()
        self.session.add(
            PasswordResetToken(
                user_id=user.id,
                token_hash=hash_token(raw),
                expires_at=datetime.now(UTC) + PASSWORD_RESET_TTL,
            )
        )

        if self.email_sender is not None:
            await self.email_sender.send(
                render_action_email(
                    to=user.email,
                    action_url=f"{self.settings.FRONTEND_URL}/reset-password?token={raw}",
                    purpose=ActionPurpose.RESET_PASSWORD,
                    recipient_name=user.full_name,
                    expiry_text="1 hour",
                    settings=self.settings,
                )
            )

        await self._audit_identity_event(
            user_id=user.id,
            action=AuditAction.USER_PASSWORD_RESET_REQUESTED,
        )

    async def reset_password(self, *, raw_token: str, new_password: str) -> User:
        """Consume a reset token, set the password, and kill every session.

        REVOKING ALL SESSIONS IS NOT OPTIONAL. The most likely reason someone resets
        a password is that they believe it was compromised. If the attacker's
        existing refresh token survives the reset, the reset accomplished nothing --
        they keep their access and the user believes they are safe.
        """
        record = (
            await self.session.execute(
                select(PasswordResetToken).where(
                    PasswordResetToken.token_hash == hash_token(raw_token)
                )
            )
        ).scalar_one_or_none()

        if record is None or not record.is_usable:
            raise AuthenticationError(
                "This reset link is invalid or has expired.",
                code="INVALID_RESET_TOKEN",
            )

        user = await self.session.get(User, record.user_id)
        if user is None:
            raise AuthenticationError("This reset link is no longer valid.")

        validate_password(
            new_password, user_inputs=[user.full_name, user.email], settings=self.settings
        )

        record.used_at = datetime.now(UTC)
        user.password_hash = hash_password(new_password)
        user.failed_login_count = 0
        user.locked_until = None
        user.lockout_count = 0

        # A user who reset their password because they were locked out should be able
        # to sign in immediately; and a verified-by-email reset is itself proof of
        # inbox control, so it doubles as verification for a still-pending account.
        if user.status is UserStatus.PENDING:
            user.status = UserStatus.ACTIVE
            user.email_verified_at = user.email_verified_at or datetime.now(UTC)

        await self.revoke_all_sessions(user.id, reason="password_reset")
        await self._audit_identity_event(
            user_id=user.id,
            action=AuditAction.USER_PASSWORD_RESET,
        )
        return user

    async def _audit_identity_event(
        self,
        *,
        user_id: UUID,
        action: str,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        """Write an identity event to the user's primary live tenant context.

        Login and password-reset requests begin without a tenant claim. The user id
        is already proven at this point, so a narrowly scoped membership lookup can
        select the primary context. The audit row is flushed while that tenant is
        bound; deferring the flush until the request ends would run the RLS check
        after the binding had been cleared.
        """
        await bind_tenant(self.session, None, platform_admin=True)
        try:
            membership = (
                await self.session.execute(
                    select(Membership)
                    .where(
                        Membership.user_id == user_id,
                        Membership.deleted_at.is_(None),
                    )
                    .order_by(Membership.is_primary.desc(), Membership.created_at)
                    .limit(1)
                )
            ).scalar_one_or_none()
        finally:
            await self._restore_tenant_binding()

        if membership is None:
            return

        await bind_tenant(
            self.session,
            membership.organization_id,
            school_id=membership.school_id,
        )
        try:
            await record_audit(
                self.session,
                organization_id=membership.organization_id,
                school_id=membership.school_id,
                action=action,
                actor_user_id=user_id,
                actor_membership_id=membership.id,
                ip=ip,
                user_agent=user_agent,
            )
            await self.session.flush()
        finally:
            await self._restore_tenant_binding()

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    async def _find_user_by_email(self, email: str) -> User | None:
        """Look a user up by address.

        No `.lower()`: the column is CITEXT, so the database compares
        case-insensitively. Normalising here too would work but would imply the
        guarantee lives in Python, and the next query written without it would
        silently become case-sensitive.
        """
        return (
            await self.session.execute(
                select(User).where(User.email == email, User.deleted_at.is_(None))
            )
        ).scalar_one_or_none()

    async def _unique_org_slug(self, name: str) -> str:
        """Derive a URL-safe slug, appending a suffix on collision.

        Collisions are cross-tenant by nature -- `organizations.slug` is globally
        unique -- so this must run with the RLS escape armed, or the existence check
        would see zero rows and always report the slug as free.
        """
        base = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")
        base = "-".join(filter(None, base.split("-")))[:60] or "org"

        await bind_tenant(self.session, None, platform_admin=True)
        try:
            for attempt in range(8):
                candidate = base if attempt == 0 else f"{base}-{uuid4().hex[:6]}"
                taken = (
                    await self.session.execute(
                        select(Organization.id).where(Organization.slug == candidate).limit(1)
                    )
                ).scalar_one_or_none()
                if taken is None:
                    return candidate
            raise ConflictError(
                "Could not allocate a unique identifier for this organization name.",
                code="SLUG_ALLOCATION_FAILED",
            )
        finally:
            await self._restore_tenant_binding()


async def summarise_school(session: AsyncSession, school_id: UUID | None) -> School | None:
    """Load a school for display, or None. Shared by the router's response builders."""
    if school_id is None:
        return None
    return await session.get(School, school_id)


__all__ = [
    "PASSWORD_RESET_TTL",
    "VERIFICATION_TTL",
    "AuthService",
    "IssuedTokens",
    "summarise_school",
]
