"""Parent-portal authentication -- phone, one-time code, no password.

WHY THIS FILE EXISTS
    The staff surface authenticates a globally unique EMAIL with an Argon2 password.
    Neither half works for guardians:

      * A large share of parents in the target market have no email address, and
        minting `parent-3f2a@school.invalid` for them is a fabricated identity that
        breaks the moment two schools do it for the same person.
      * A password is a credential a parent will use twice a year. They will forget
        it, and every reset needs a channel we do not have -- which is the email
        address they do not have. The handset IS the channel, so the handset is the
        credential.

    So: the phone number is the identifier, an SMS code is the proof, and the code
    is short-lived, single-use, attempt-capped and rate-limited.

RESPONSIBILITY
    Issue codes, verify them, choose an organization, mint and rotate sessions.
    Registry CRUD is `service.py`; this file never creates a guardian record.

INTERACTIONS
    * `core/otp.py` for the cryptographic primitives -- generation, the peppered
      digest, and constant-time comparison. None of that is re-implemented here.
    * `common/sms/sender.py` for delivery, injected so tests can capture it.
    * `auth/models.Session` for the session row: guardians share the staff table and
      therefore its rotation and reuse detection.

=============================================================================
FIVE CONTROLS, AND THE CODE IS WORTHLESS WITHOUT ANY ONE OF THEM
=============================================================================
    A 6-digit code has 10^6 values. That is trivially brute-forceable, and the
    security comes entirely from the controls around it:

      1. EXPIRY -- five minutes. An SMS lands on a lock screen in seconds; a longer
         window only widens the period in which a borrowed handset is a login.
      2. ATTEMPT CAP -- five wrong guesses burns the code AND counts against the
         identity. Held on the IDENTITY, not the code row, so requesting a fresh code
         does not reset the attacker's budget. That reset is the obvious bypass of a
         per-code counter and it is the one people ship.
      3. SINGLE USE -- `consumed_at`. A code that worked once must not work twice.
      4. NEWEST ONLY -- issuing a code retires the previous one. Otherwise ten sends
         become ten simultaneous guesses.
      5. RATE LIMIT + DAILY QUOTA -- per phone and per IP. SMS costs real money, so an
         unthrottled request endpoint spends a tenant's budget as easily as it
         harasses a parent.

=============================================================================
NO ENUMERATION, ANYWHERE ON THIS SURFACE
=============================================================================
    `request_code` returns the same body, the same status and the same shape whether
    or not the number is known -- and does the same rate-limit bookkeeping either way.
    An honest 404 would turn an unauthenticated endpoint into a way to ask "does this
    person have a child at a school on this platform", which is exactly what a stalker
    or an abusive ex-partner wants and which no parent agreed to publish.

    `verify_code` is the same: an unknown number and a wrong code both return
    INVALID_CODE, and both burn the same amount of time.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.sms import SmsMessage, SmsSender, build_sms_sender
from app.core.config import Settings, get_settings
from app.core.context import get_organization_id, get_school_id
from app.core.exceptions import AuthenticationError, AuthorizationError, RateLimitError
from app.core.logging import get_logger
from app.core.otp import generate_otp, hash_otp, verify_otp
from app.core.phone import mask_phone, normalise_phone
from app.core.rate_limit import enforce_rate_limit
from app.core.security import (
    PrincipalType,
    create_access_token,
    generate_opaque_token,
    hash_token,
)
from app.db.session import bind_tenant
from app.modules.auth.models import Session
from app.modules.guardians.models import (
    Guardian,
    GuardianIdentity,
    GuardianOtpCode,
    GuardianOtpPurpose,
    GuardianStudent,
)
from app.modules.guardians.repository import GuardianIdentityRepository
from app.modules.guardians.schemas import (
    GuardianContextSummary,
    GuardianProfile,
)
from app.modules.tenancy.models import Organization, School

logger = get_logger(__name__)

# Lockout applied to the IDENTITY once the attempt cap is exhausted. Fixed rather
# than exponential, unlike the staff lockout: a guardian has no password to remember
# and no support desk to call at 9pm, and a doubling lock would put a parent out of
# the portal for a day over five fat-fingered digits. Fifteen minutes is enough to
# make online guessing pointless at 10^6 codes.
OTP_LOCKOUT = timedelta(minutes=15)

# How long the pre-context token lives when a guardian holds records in more than one
# organization. Matches the staff continuation window: long enough to read a picker,
# short enough that an abandoned tab is not a session.
CONTEXT_SELECTION_TTL = timedelta(minutes=5)


@dataclass(frozen=True, slots=True)
class IssuedGuardianTokens:
    access_token: str
    refresh_token: str
    session_id: UUID
    expires_in: int


@dataclass(frozen=True, slots=True)
class VerifiedGuardian:
    """The outcome of a successful code check, before an organization is chosen."""

    identity: GuardianIdentity
    contexts: list[Guardian]


class GuardianAuthService:
    """Phone-OTP login for the parent portal."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        sms: SmsSender | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.sms = sms or build_sms_sender(self.settings)
        self.identities = GuardianIdentityRepository(session)

    # -----------------------------------------------------------------------
    # Step 1: request a code
    # -----------------------------------------------------------------------

    async def request_code(
        self,
        raw_phone: str,
        *,
        ip: str | None = None,
        purpose: GuardianOtpPurpose = GuardianOtpPurpose.PORTAL_LOGIN,
    ) -> tuple[str, int, int]:
        """Send a login code. Returns `(masked_phone, ttl_seconds, retry_after)`.

        Runs the SAME bookkeeping whether or not the number is known -- see the module
        docstring on enumeration. The only observable difference between a registered
        and an unregistered number is that one handset receives a text.
        """
        phone = self._normalise(raw_phone)
        ttl_seconds = self.settings.GUARDIAN_OTP_TTL_MINUTES * 60
        cooldown = self.settings.GUARDIAN_OTP_RESEND_COOLDOWN_SECONDS

        # Per-number first: this is the limit that protects the PARENT from being
        # texted every ten seconds by someone who knows their number.
        await enforce_rate_limit(
            "guardian_otp_phone",
            phone,
            limit=self.settings.AUTH_RATE_LIMIT,
            window_seconds=self.settings.AUTH_RATE_WINDOW_SECONDS,
        )
        if ip:
            # Per-IP second: this is the limit that protects the TENANT'S SMS BUDGET
            # from one script walking a range of numbers. Both are needed -- an
            # attacker rotating numbers defeats the first, and one rotating proxies
            # defeats the second.
            await enforce_rate_limit(
                "guardian_otp_ip",
                ip,
                limit=self.settings.AUTH_RATE_LIMIT * 4,
                window_seconds=self.settings.AUTH_RATE_WINDOW_SECONDS,
            )

        masked = mask_phone(phone)

        # `guardian_identities` is outside RLS, but this method may be reached on a
        # session that still carries some other tenant's GUC (a staff user testing the
        # portal). Clearing it makes the lookup deterministic.
        identity = await self.identities.get_by_phone(phone)
        if identity is None or not identity.can_authenticate:
            logger.info("guardian_otp_requested_unknown", phone_masked=masked)
            return masked, ttl_seconds, cooldown

        previous = await self.identities.latest_code(identity.id, purpose)
        if previous is not None:
            elapsed = (datetime.now(UTC) - previous.created_at).total_seconds()
            if elapsed < cooldown:
                # A real 429, not a silent no-op. The caller here is the parent's own
                # browser hammering "resend", and telling it exactly how long to wait
                # is the difference between a countdown and a broken button.
                raise RateLimitError(
                    "A code was just sent. Please wait before requesting another.",
                    details={"retry_after": int(cooldown - elapsed)},
                )

        issued_today = await self.identities.codes_issued_since(identity.id, hours=24)
        if issued_today >= self.settings.GUARDIAN_OTP_DAILY_LIMIT:
            raise RateLimitError(
                "Too many codes requested today. Please contact the school office.",
                details={"retry_after": 3600},
            )

        code = generate_otp()
        await self.identities.add_code(
            GuardianOtpCode(
                identity_id=identity.id,
                purpose=purpose,
                # The digest binds purpose AND phone, so a code minted for this handset
                # cannot be submitted for another, and a login code cannot be replayed
                # against a future "confirm phone change" flow.
                code_hash=hash_otp(code, purpose=purpose, identifier=phone, settings=self.settings),
                expires_at=datetime.now(UTC)
                + timedelta(minutes=self.settings.GUARDIAN_OTP_TTL_MINUTES),
                ip=ip,
            )
        )

        await self.sms.send(
            SmsMessage(
                to=phone,
                body=(
                    f"{code} is your {self.settings.SMS_SENDER_ID} verification code. "
                    f"It expires in {self.settings.GUARDIAN_OTP_TTL_MINUTES} minutes. "
                    "Do not share it with anyone."
                ),
                purpose=purpose.value,
            )
        )
        logger.info("guardian_otp_sent", identity_id=str(identity.id), phone_masked=masked)
        return masked, ttl_seconds, cooldown

    # -----------------------------------------------------------------------
    # Step 2: verify it
    # -----------------------------------------------------------------------

    async def verify_code(
        self,
        raw_phone: str,
        code: str,
        *,
        purpose: GuardianOtpPurpose = GuardianOtpPurpose.PORTAL_LOGIN,
    ) -> VerifiedGuardian:
        """Check a submitted code and return the identity plus its usable contexts.

        Does NOT issue a session -- the caller decides between the one-context and
        several-contexts paths. Keeping session minting out of here is what lets the
        phone-change flow reuse the same verification without accidentally logging
        someone in.
        """
        phone = self._normalise(raw_phone)
        identity = await self.identities.get_by_phone(phone)

        if identity is None:
            # Same error, same shape, as a wrong code. See the module docstring.
            raise self._invalid_code()
        if identity.is_locked:
            raise AuthenticationError(
                "Too many incorrect codes. Please try again shortly.",
                code="GUARDIAN_LOCKED",
            )
        if not identity.can_authenticate:
            raise AuthenticationError(
                "This account cannot sign in. Please contact the school office.",
                code="GUARDIAN_INACTIVE",
            )

        record = await self.identities.latest_code(identity.id, purpose)
        if record is None or record.consumed_at is not None:
            raise self._invalid_code()
        if record.expires_at <= datetime.now(UTC):
            raise AuthenticationError(
                "That code has expired. Request a new one.", code="CODE_EXPIRED"
            )

        # INCREMENTED BEFORE THE COMPARISON, not after. If the comparison raised and
        # the increment were below it, every wrong guess would be free and the attempt
        # cap would never fire -- the single most common way an OTP implementation is
        # actually broken.
        record.attempts += 1
        identity.failed_otp_count += 1

        if record.attempts > self.settings.GUARDIAN_OTP_MAX_ATTEMPTS:
            record.consumed_at = datetime.now(UTC)
            identity.locked_until = datetime.now(UTC) + OTP_LOCKOUT
            await self.session.flush()
            logger.warning("guardian_otp_exhausted", identity_id=str(identity.id))
            raise AuthenticationError(
                "Too many incorrect codes. Please try again shortly.",
                code="GUARDIAN_LOCKED",
            )

        if not verify_otp(
            code,
            record.code_hash,
            purpose=purpose,
            identifier=phone,
            settings=self.settings,
        ):
            await self.session.flush()
            raise self._invalid_code()

        record.consumed_at = datetime.now(UTC)
        identity.failed_otp_count = 0
        identity.locked_until = None
        identity.last_login_at = datetime.now(UTC)
        await self.session.flush()

        contexts = await self._usable_contexts(identity.id)
        logger.info("guardian_otp_verified", identity_id=str(identity.id), contexts=len(contexts))
        return VerifiedGuardian(identity=identity, contexts=contexts)

    async def _usable_contexts(self, identity_id: UUID) -> list[Guardian]:
        """Every organization whose records this handset may open.

        =====================================================================
        THE ONE PLACE THE CROSS-TENANT READ IS ARMED ON THIS SURFACE
        =====================================================================
            "Which organizations may this person choose between?" is by definition a
            cross-organization question asked before any organization is chosen -- the
            exact analogue of listing a staff user's memberships at login, which runs
            the same way.

            `guardians` is RLS-protected, so the query returns nothing unless the read
            GUC is armed. It is armed HERE, for this one query, AFTER the code has been
            verified, and the predicate pins `identity_id` to the person who just
            proved control of the handset. The binding is restored immediately
            afterwards, and it grants reads only: the WITH CHECK half of every policy
            has no admin escape, so nothing can be written through this window.
        """
        previous_org = get_organization_id()
        previous_school = get_school_id()
        await bind_tenant(self.session, None, platform_admin=True)
        try:
            return list(await self.identities.contexts_for_identity(identity_id))
        finally:
            await bind_tenant(
                self.session, previous_org, school_id=previous_school, platform_admin=False
            )

    # -----------------------------------------------------------------------
    # Step 3: sessions
    # -----------------------------------------------------------------------

    async def issue_context_selection(
        self,
        identity: GuardianIdentity,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[str, int]:
        """A five-minute, single-purpose token for the organization picker.

        Backed by a real session row whose refresh secret is generated and then
        DISCARDED -- never returned. That makes the pre-context credential
        unrefreshable by construction rather than by a check somebody could forget:
        there is no token in existence that would rotate it.
        """
        now = datetime.now(UTC)
        row = Session(
            guardian_identity_id=identity.id,
            refresh_token_hash=hash_token(generate_opaque_token()),
            family_id=uuid4(),
            expires_at=now + CONTEXT_SELECTION_TTL,
            ip=ip,
            user_agent=user_agent,
        )
        self.session.add(row)
        await self.session.flush()

        expires_in = int(CONTEXT_SELECTION_TTL.total_seconds())
        token = create_access_token(
            user_id=identity.id,
            session_id=row.id,
            principal_type=PrincipalType.GUARDIAN_CONTEXT_SELECTION,
            expires_minutes=expires_in // 60,
            settings=self.settings,
        )
        return token, expires_in

    async def issue_session(
        self,
        *,
        identity: GuardianIdentity,
        guardian: Guardian,
        ip: str | None = None,
        user_agent: str | None = None,
        family_id: UUID | None = None,
    ) -> IssuedGuardianTokens:
        """Mint the portal access/refresh pair for one organization.

        The access token carries `org`, which is what binds RLS when the portal reads
        that organization's students -- and `grd`, the guardian record, which is what
        the portal filters its child list by. Both are signed, so a parent cannot edit
        either to reach another family or another school group.
        """
        raw_refresh = generate_opaque_token()
        now = datetime.now(UTC)

        row = Session(
            guardian_identity_id=identity.id,
            guardian_id=guardian.id,
            refresh_token_hash=hash_token(raw_refresh),
            family_id=family_id or uuid4(),
            expires_at=now + timedelta(days=self.settings.GUARDIAN_SESSION_EXPIRE_DAYS),
            ip=ip,
            user_agent=user_agent,
        )
        self.session.add(row)
        await self.session.flush()

        expires_minutes = self.settings.GUARDIAN_ACCESS_TOKEN_EXPIRE_MINUTES
        access = create_access_token(
            user_id=identity.id,
            session_id=row.id,
            principal_type=PrincipalType.GUARDIAN,
            organization_id=guardian.organization_id,
            guardian_id=guardian.id,
            expires_minutes=expires_minutes,
            settings=self.settings,
        )
        logger.info(
            "guardian_session_issued",
            identity_id=str(identity.id),
            guardian_id=str(guardian.id),
        )
        return IssuedGuardianTokens(
            access_token=access,
            refresh_token=raw_refresh,
            session_id=row.id,
            expires_in=expires_minutes * 60,
        )

    async def select_context(
        self,
        *,
        identity_id: UUID,
        guardian_id: UUID,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[GuardianIdentity, Guardian]:
        """Resolve a chosen organization, re-checking that it is still choosable.

        RE-READ, NOT TRUSTED FROM THE PICKER. Between the code being verified and the
        parent tapping a school, the school may have disabled the portal or removed
        the record. Trusting the id the client sent back would let a stale tab open a
        context that no longer exists.
        """
        identity = await self.identities.get(identity_id)
        if identity is None or not identity.can_authenticate:
            raise AuthenticationError("This account cannot sign in.", code="GUARDIAN_INACTIVE")

        contexts = await self._usable_contexts(identity_id)
        guardian = next((g for g in contexts if g.id == guardian_id), None)
        if guardian is None:
            # 403, not 404: the caller has proven who they are, and the honest answer
            # is that this organization is not one of theirs. There is nothing to leak
            # -- they already know the id, because they just sent it.
            raise AuthorizationError(
                "That school is not available for this account.",
                code="GUARDIAN_CONTEXT_UNAVAILABLE",
            )
        return identity, guardian

    async def refresh_session(
        self,
        raw_refresh_token: str,
        *,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> IssuedGuardianTokens:
        """Rotate a portal refresh token, with the same reuse detection as staff.

        The reuse branch is not boilerplate here either: a parent's handset is shared,
        lost and resold far more often than a staff laptop, so a replayed token is a
        realistic event rather than a theoretical one. Revoking the whole family forces
        both parties back through an SMS to a number only one of them holds.
        """
        presented = hash_token(raw_refresh_token)

        previous_org = get_organization_id()
        previous_school = get_school_id()
        # Runs outside tenant RLS: a refresh arrives with an expired access token, so
        # no org is bound. The lookup is by 256-bit digest, which is not guessable.
        await bind_tenant(self.session, None, platform_admin=True)
        try:
            row = (
                await self.session.execute(
                    select(Session).where(Session.refresh_token_hash == presented)
                )
            ).scalar_one_or_none()

            if row is None or row.guardian_identity_id is None:
                raise AuthenticationError(
                    "Session is invalid or has expired.", code="INVALID_REFRESH_TOKEN"
                )

            if row.revoked_at is not None:
                await self._revoke_family(row.family_id, reason="reuse_detected")
                logger.warning(
                    "guardian_refresh_reuse_detected",
                    identity_id=str(row.guardian_identity_id),
                    family_id=str(row.family_id),
                    ip=ip,
                )
                raise AuthenticationError(
                    "This session has been ended for security reasons. Please sign in again.",
                    code="TOKEN_REUSE_DETECTED",
                )

            if row.expires_at <= datetime.now(UTC):
                raise AuthenticationError("Session has expired.", code="SESSION_EXPIRED")

            identity = await self.identities.get(row.guardian_identity_id)
            if identity is None or not identity.can_authenticate:
                raise AuthenticationError("Session is no longer valid.", code="GUARDIAN_INACTIVE")

            if row.guardian_id is None:
                # A pre-context session. Its refresh secret was never returned, so
                # reaching here at all means a forged or mis-minted token.
                raise AuthenticationError(
                    "Session is invalid or has expired.", code="INVALID_REFRESH_TOKEN"
                )

            # RE-READ AND RE-CHECKED, not carried forward. Between two refreshes the
            # school may have disabled its portal or removed this parent's record, and
            # the whole point of a 15-minute access token is that such a change takes
            # effect at the next boundary rather than at the end of a 30-day refresh
            # lifetime. The read runs with the cross-tenant window armed because no org
            # is bound during a refresh; it is pinned to this session's own guardian id.
            guardian = (
                await self.session.execute(
                    select(Guardian).where(
                        Guardian.id == row.guardian_id,
                        Guardian.identity_id == identity.id,
                        Guardian.deleted_at.is_(None),
                        Guardian.portal_enabled.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if guardian is None:
                await self._revoke_family(row.family_id, reason="guardian_access_revoked")
                raise AuthenticationError(
                    "Your access to this school has changed. Please sign in again.",
                    code="GUARDIAN_ACCESS_REVOKED",
                )

            row.revoked_at = datetime.now(UTC)
            row.revoked_reason = "rotated"

            return await self.issue_session(
                identity=identity,
                guardian=guardian,
                ip=ip,
                user_agent=user_agent,
                family_id=row.family_id,
            )
        finally:
            await bind_tenant(
                self.session, previous_org, school_id=previous_school, platform_admin=False
            )

    async def revoke_session(self, session_id: UUID, *, reason: str = "logout") -> None:
        await self.session.execute(
            update(Session)
            .where(Session.id == session_id, Session.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
        )

    async def revoke_all(self, identity_id: UUID, *, reason: str = "logout_all") -> None:
        await self.session.execute(
            update(Session)
            .where(
                Session.guardian_identity_id == identity_id,
                Session.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
        )

    async def _revoke_family(self, family_id: UUID, *, reason: str) -> None:
        await self.session.execute(
            update(Session)
            .where(Session.family_id == family_id, Session.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
        )

    # -----------------------------------------------------------------------
    # Presentation helpers
    # -----------------------------------------------------------------------

    async def describe_contexts(self, contexts: list[Guardian]) -> list[GuardianContextSummary]:
        """Turn choosable guardians into picker rows.

        Runs with the cross-tenant read armed for the same reason `_usable_contexts`
        does: the picker spans organizations by definition, and the organization names
        and campus names it shows live in RLS-protected tables. Scoped to the ids
        already resolved for this identity, so nothing else is reachable.
        """
        if not contexts:
            return []

        previous_org = get_organization_id()
        previous_school = get_school_id()
        await bind_tenant(self.session, None, platform_admin=True)
        try:
            guardian_ids = [g.id for g in contexts]
            org_rows = (
                await self.session.execute(
                    select(Organization.id, Organization.name).where(
                        Organization.id.in_([g.organization_id for g in contexts])
                    )
                )
            ).all()
            org_names: dict[UUID, str] = dict(org_rows)  # type: ignore[arg-type]

            # ONE query for every (guardian, school) pair across every context, joined
            # to the school name. The obvious alternative -- two queries per context --
            # is an N+1 on a login screen, which is the worst place to put one.
            pairs = (
                await self.session.execute(
                    select(GuardianStudent.guardian_id, School.name, GuardianStudent.student_id)
                    .join(School, School.id == GuardianStudent.school_id)
                    .where(
                        GuardianStudent.guardian_id.in_(guardian_ids),
                        GuardianStudent.deleted_at.is_(None),
                        GuardianStudent.can_view_results.is_(True),
                    )
                )
            ).all()

            schools: dict[UUID, set[str]] = {gid: set() for gid in guardian_ids}
            children: dict[UUID, set[UUID]] = {gid: set() for gid in guardian_ids}
            for guardian_id, school_name, student_id in pairs:
                schools[guardian_id].add(school_name)
                children[guardian_id].add(student_id)

            return [
                GuardianContextSummary(
                    guardian_id=g.id,
                    organization_id=g.organization_id,
                    organization_name=org_names.get(g.organization_id, "School"),
                    student_count=len(children[g.id]),
                    schools=sorted(schools[g.id]),
                )
                for g in contexts
            ]
        finally:
            await bind_tenant(
                self.session, previous_org, school_id=previous_school, platform_admin=False
            )

    async def profile(self, identity: GuardianIdentity, guardian: Guardian) -> GuardianProfile:
        """Who the portal says you are, for the header of every screen."""
        organization = await self.session.get(Organization, guardian.organization_id)
        return GuardianProfile(
            identity_id=identity.id,
            guardian_id=guardian.id,
            organization_id=guardian.organization_id,
            organization_name=organization.name if organization else "School",
            full_name=guardian.full_name,
            phone=identity.phone,
            email=identity.email,
            preferred_locale=identity.preferred_locale,
        )

    # -----------------------------------------------------------------------
    # Internals
    # -----------------------------------------------------------------------

    def _normalise(self, raw: str) -> str:
        return normalise_phone(
            raw,
            default_calling_code=self.settings.DEFAULT_COUNTRY_CALLING_CODE,
            trunk_prefix=self.settings.NATIONAL_TRUNK_PREFIX,
        )

    @staticmethod
    def _invalid_code() -> AuthenticationError:
        """ONE error for every failure mode a guesser could distinguish.

        Unknown number, wrong code, already-used code and retired code all land here.
        Separate messages would be a working oracle: an attacker submitting `000000`
        to a list of numbers would learn which of them are registered parents without
        ever guessing a code correctly.
        """
        return AuthenticationError(
            "That code is not valid. Request a new one.", code="INVALID_CODE"
        )
