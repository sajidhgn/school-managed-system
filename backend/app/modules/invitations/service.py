"""Invitation flows (spec §7).

WHY THIS FILE EXISTS
    An invitation is the only way a new human enters an existing organization, which
    makes it that organization's entire attack surface for unwanted members. The
    guards matter more than the CRUD, and they are all here.

RESPONSIBILITY
    Send, verify, accept, resend and revoke invitations.

INTERACTIONS
    * `modules/rbac/service.py` for the escalation guard shared with role editing.
    * `modules/billing/entitlements.py` for the staff-seat check.
    * `core/security.py` for token generation and digesting.

=============================================================================
THE FOUR GUARDS ON ACCEPT, AND THE ATTACK EACH ONE STOPS
=============================================================================
    1. SINGLE USE.        A token already accepted is dead. Otherwise one leaked
                          invite link creates unlimited memberships.

    2. EXPIRY.            7 days. An invite forwarded, archived, or sitting in a
                          former employee's mailbox stops working.

    3. EMAIL MUST MATCH.  A logged-in user accepting an invitation addressed to
                          SOMEONE ELSE is a real attack -- forward the link to a
                          colleague, or find one, and join an organization you were
                          never invited to. It is blocked by one comparison, and
                          spec §7.2 calls it out for exactly that reason.

    4. NO ESCALATION.     The INVITER must already hold every permission the invited
                          role grants (spec §7.1 step 2). Without it, invitation
                          becomes an escalation backdoor: a principal who cannot
                          grant `billing:manage` directly simply invites a new
                          account into a role that has it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.deps import AuthContext
from app.common.audit import AuditAction, record_audit
from app.common.email.sender import EmailSender
from app.common.email.templates import ActionPurpose, render_action_email
from app.core.config import Settings
from app.core.exceptions import (
    AppError,
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.core.logging import get_logger
from app.core.passwords import validate_password
from app.core.security import generate_opaque_token, hash_password, hash_token
from app.db.session import bind_tenant
from app.modules.auth.models import User, UserStatus
from app.modules.billing.entitlements import EntitlementService
from app.modules.invitations.models import Invitation, InvitationStatus
from app.modules.rbac.models import Membership, MembershipStatus, Role
from app.modules.rbac.service import RbacService
from app.modules.tenancy.models import Organization, School

logger = get_logger(__name__)


class InvitationGoneError(AppError):
    """410: the invitation was already used, expired, or revoked.

    410 rather than 404 or 400 because it says precisely what happened: the resource
    existed and is now permanently unavailable. Spec §12 requires 410 for both the
    reuse and expiry cases, and a client can act on it -- "request a new invitation"
    -- in a way it cannot act on a generic 400.
    """

    status_code = 410
    code = "INVITATION_GONE"
    message = "This invitation is no longer valid."


class InvitationService:
    """Invitation lifecycle. Never commits."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        email_sender: EmailSender | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.email_sender = email_sender
        self.entitlements = EntitlementService(session)

    # -----------------------------------------------------------------------
    # Send
    # -----------------------------------------------------------------------

    async def create(
        self,
        *,
        ctx: AuthContext,
        school_id: UUID,
        email: str,
        full_name: str | None,
        role_id: UUID,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[Invitation, str]:
        """Create an invitation and email it. Returns the row and the RAW token.

        The raw token is returned so tests can assert the flow end-to-end without
        parsing an email. It is never persisted and never logged -- see the model's
        docstring.

        The order of checks follows spec §7.1 exactly, and the ordering matters:
        entitlements are checked BEFORE the email is sent, so a staff-limit rejection
        never leaves an invitation sitting in someone's inbox that they cannot
        accept.
        """
        rbac = RbacService(self.session)

        # 1. The role must belong to this organization AND this school.
        role = await self.session.get(Role, role_id)
        if role is None:
            raise NotFoundError("Role not found.")
        if role.school_id != school_id:
            raise ValidationError(
                "That role does not belong to this school.", code="ROLE_SCOPE_MISMATCH"
            )
        if role.code == "owner":
            # Ownership is transferred, never invited. An owner invitation would
            # create a second billing controller with no audit of a handover.
            raise ValidationError(
                "Ownership cannot be granted by invitation. Use transfer ownership.",
                code="CANNOT_INVITE_OWNER",
            )

        # 2. Escalation guard -- the same rule as role editing (guard 4 above).
        rbac._assert_can_grant(ctx, await rbac.role_permission_codes(role_id))

        # 4. Reject if this person is already a member here. (Step 3, the entitlement
        #    check, comes after -- there is no point consuming a seat for a duplicate.)
        already = (
            await self.session.execute(
                select(Membership.id)
                .join(User, User.id == Membership.user_id)
                .where(
                    User.email == email,
                    Membership.school_id == school_id,
                    Membership.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if already is not None:
            raise ConflictError(
                "That person is already a member of this school.",
                code="ALREADY_MEMBER",
                details={"field": "email"},
            )

        pending = (
            await self.session.execute(
                select(Invitation).where(
                    Invitation.school_id == school_id,
                    Invitation.email == email,
                    Invitation.status == InvitationStatus.PENDING,
                )
            )
        ).scalar_one_or_none()
        if pending is not None:
            raise ConflictError(
                "An invitation is already pending for that address. Resend it instead.",
                code="INVITATION_PENDING",
                details={"invitation_id": str(pending.id)},
            )

        # 3. Entitlement check -- before the email, per spec §7.1.
        await self.entitlements.check_and_consume(ctx.organization_id, "max_staff")

        # 5. Generate the token; store only its digest.
        raw = generate_opaque_token()
        invitation = Invitation(
            organization_id=ctx.organization_id,
            school_id=school_id,
            role_id=role_id,
            email=email,
            full_name=full_name,
            token_hash=hash_token(raw),
            status=InvitationStatus.PENDING,
            expires_at=datetime.now(UTC) + timedelta(days=self.settings.INVITATION_EXPIRE_DAYS),
            invited_by_user_id=ctx.user_id,
            last_sent_at=datetime.now(UTC),
        )
        self.session.add(invitation)
        await self.session.flush()

        # 6. Email the link. 7. Audit.
        await self._send_email(invitation, raw, role)
        await record_audit(
            self.session,
            organization_id=ctx.organization_id,
            school_id=school_id,
            action=AuditAction.INVITATION_SENT,
            actor_user_id=ctx.user_id,
            actor_membership_id=ctx.membership_id,
            entity_type="invitation",
            entity_id=invitation.id,
            after={"email": email, "role": role.code},
            ip=ip,
            user_agent=user_agent,
        )
        return invitation, raw

    async def _send_email(self, invitation: Invitation, raw_token: str, role: Role) -> None:
        """Render and dispatch the invitation email.

        The school and role are shown in the body so the recipient can judge whether
        the invitation is legitimate WITHOUT clicking the link to find out -- which
        is the behaviour every phishing-awareness training asks for and most
        invitation emails make impossible.
        """
        if self.email_sender is None:
            return

        school = await self.session.get(School, invitation.school_id)
        organization = await self.session.get(Organization, invitation.organization_id)

        await self.email_sender.send(
            render_action_email(
                to=invitation.email,
                action_url=f"{self.settings.FRONTEND_URL}/invite/accept?token={raw_token}",
                purpose=ActionPurpose.INVITATION,
                recipient_name=invitation.full_name,
                details=[
                    ("Organization", organization.name if organization else ""),
                    ("School", school.name if school else ""),
                    ("Role", role.name),
                ],
                expiry_text=f"{self.settings.INVITATION_EXPIRE_DAYS} days",
                settings=self.settings,
            )
        )

    async def resend(self, *, ctx: AuthContext, invitation_id: UUID) -> tuple[Invitation, str]:
        """Issue a NEW token and invalidate the previous one.

        It cannot re-send the original link: only the digest was stored, so the raw
        token is unrecoverable by design. Rotating on resend is also the safer
        behaviour -- if the first email went to a compromised or mistyped address,
        the old link dies here.
        """
        invitation = await self._get(invitation_id, ctx)

        if invitation.status is not InvitationStatus.PENDING:
            raise ConflictError(
                "Only pending invitations can be resent.", code="INVITATION_NOT_PENDING"
            )
        if invitation.resent_count >= self.settings.INVITATION_MAX_RESENDS:
            raise ConflictError(
                f"This invitation has been resent {invitation.resent_count} times. "
                "Revoke it and send a new one.",
                code="RESEND_LIMIT_REACHED",
            )

        raw = generate_opaque_token()
        invitation.token_hash = hash_token(raw)
        invitation.expires_at = datetime.now(UTC) + timedelta(
            days=self.settings.INVITATION_EXPIRE_DAYS
        )
        invitation.resent_count += 1
        invitation.last_sent_at = datetime.now(UTC)

        role = await self.session.get(Role, invitation.role_id)
        if role is not None:
            await self._send_email(invitation, raw, role)

        await record_audit(
            self.session,
            organization_id=ctx.organization_id,
            school_id=invitation.school_id,
            action=AuditAction.INVITATION_RESENT,
            actor_user_id=ctx.user_id,
            actor_membership_id=ctx.membership_id,
            entity_type="invitation",
            entity_id=invitation.id,
        )
        return invitation, raw

    async def revoke(self, *, ctx: AuthContext, invitation_id: UUID) -> Invitation:
        """Kill a pending invitation immediately and return its reserved seat."""
        invitation = await self._get(invitation_id, ctx)
        if invitation.status is not InvitationStatus.PENDING:
            raise ConflictError(
                "Only pending invitations can be revoked.", code="INVITATION_NOT_PENDING"
            )

        invitation.status = InvitationStatus.REVOKED
        # The seat was consumed when the invitation was sent; revoking gives it back.
        # Without this, an organization that sends and revokes ten invitations has
        # permanently lost ten staff seats it never used.
        await self.entitlements.release(ctx.organization_id, "max_staff")

        await record_audit(
            self.session,
            organization_id=ctx.organization_id,
            school_id=invitation.school_id,
            action=AuditAction.INVITATION_REVOKED,
            actor_user_id=ctx.user_id,
            actor_membership_id=ctx.membership_id,
            entity_type="invitation",
            entity_id=invitation.id,
        )
        return invitation

    async def list_for_school(self, school_id: UUID) -> list[Invitation]:
        rows = await self.session.execute(
            select(Invitation)
            .options(joinedload(Invitation.role))
            .where(Invitation.school_id == school_id)
            .order_by(Invitation.created_at.desc())
        )
        return list(rows.scalars().all())

    async def _get(self, invitation_id: UUID, ctx: AuthContext) -> Invitation:
        invitation = await self.session.get(Invitation, invitation_id)
        if invitation is None:
            raise NotFoundError("Invitation not found.")
        if ctx.school_id is not None and invitation.school_id != ctx.school_id:
            raise AuthorizationError(
                "That invitation belongs to a different school.", code="SCOPE_VIOLATION"
            )
        return invitation

    # -----------------------------------------------------------------------
    # Verify (public)
    # -----------------------------------------------------------------------

    async def verify(self, raw_token: str) -> dict[str, object]:
        """Public preview of an invitation (spec §7.2 `GET /invitations/verify`).

        =====================================================================
        RETURNS THE MINIMUM, TO AN UNAUTHENTICATED CALLER
        =====================================================================
            Whoever holds this token has not proven anything except that they
            received an email. Spec §7.2: "Do not leak org internals to an
            unauthenticated token holder."

            So: school name, role name, the invited email, the inviter's name, and
            whether signup is required. NOT the organization's id, its other schools,
            its member list, or the role's permission set -- all of which a naive
            implementation returning the joined rows would expose to anyone who
            guessed or intercepted a token.
        """
        await bind_tenant(self.session, None, platform_admin=True)
        try:
            invitation = (
                await self.session.execute(
                    select(Invitation).where(Invitation.token_hash == hash_token(raw_token))
                )
            ).scalar_one_or_none()

            if invitation is None:
                raise NotFoundError("Invitation not found.", code="INVITATION_NOT_FOUND")
            if not invitation.is_acceptable:
                raise InvitationGoneError()

            school = await self.session.get(School, invitation.school_id)
            role = await self.session.get(Role, invitation.role_id)
            inviter = (
                await self.session.get(User, invitation.invited_by_user_id)
                if invitation.invited_by_user_id
                else None
            )
            existing_user = (
                await self.session.execute(
                    select(User.id).where(User.email == invitation.email, User.deleted_at.is_(None))
                )
            ).scalar_one_or_none()

            return {
                "school_name": school.name if school else None,
                "role_name": role.name if role else None,
                "email": invitation.email,
                "inviter_name": inviter.full_name if inviter else None,
                "requires_signup": existing_user is None,
                "expires_at": invitation.expires_at,
            }
        finally:
            await bind_tenant(self.session, None)

    # -----------------------------------------------------------------------
    # Accept (public)
    # -----------------------------------------------------------------------

    async def accept(
        self,
        *,
        raw_token: str,
        full_name: str | None,
        password: str | None,
        authenticated_user_id: UUID | None,
        ip: str | None = None,
        user_agent: str | None = None,
    ) -> tuple[User, Membership]:
        """Redeem an invitation. Two branches, ONE transaction (spec §7.2).

        NEW USER      -- no `users` row for the invited address. Creates the user
                         (already ACTIVE and email-verified: the invitation email IS
                         the verification, so a second round-trip would be asking
                         them to prove twice what they just proved once) plus the
                         membership.

        EXISTING USER -- creates only the membership, and requires an authenticated
                         session whose email matches the invited address exactly.

        The whole thing runs in the caller's request transaction, so a failure at any
        point leaves neither a user nor a membership -- never a user who exists but
        belongs to nothing and cannot be re-invited.
        """
        await bind_tenant(self.session, None, platform_admin=True)

        invitation = (
            await self.session.execute(
                select(Invitation).where(Invitation.token_hash == hash_token(raw_token))
            )
        ).scalar_one_or_none()

        if invitation is None:
            raise NotFoundError("Invitation not found.", code="INVITATION_NOT_FOUND")

        # Guards 1 and 2, checked together and BEFORE anything is created. A valid
        # digest on a consumed or expired invitation is still a failed acceptance.
        if not invitation.is_acceptable:
            raise InvitationGoneError()

        existing_user = (
            await self.session.execute(
                select(User).where(User.email == invitation.email, User.deleted_at.is_(None))
            )
        ).scalar_one_or_none()

        if authenticated_user_id is not None:
            # --- EXISTING-USER BRANCH ---------------------------------------
            caller = await self.session.get(User, authenticated_user_id)
            if caller is None:
                raise NotFoundError("Account not found.")

            # GUARD 3. The single comparison that blocks a logged-in user from
            # accepting somebody else's invitation. CITEXT makes it case-insensitive,
            # so `Ayesha@` and `ayesha@` match -- they are the same mailbox.
            if caller.email != invitation.email:
                logger.warning(
                    "invitation_email_mismatch",
                    invitation_id=str(invitation.id),
                    caller_user_id=str(authenticated_user_id),
                )
                raise AuthorizationError(
                    "This invitation was sent to a different email address. "
                    "Sign in as that address to accept it.",
                    code="INVITATION_EMAIL_MISMATCH",
                )
            user = caller

        elif existing_user is not None:
            # An account exists for the invited address, but the caller is anonymous.
            # Refuse rather than creating a second account or silently binding the
            # membership -- otherwise anyone holding the token could attach
            # themselves to an existing person's identity.
            raise AuthorizationError(
                "An account already exists for this address. Sign in to accept the invitation.",
                code="SIGN_IN_REQUIRED",
            )

        else:
            # --- NEW-USER BRANCH --------------------------------------------
            if not password or not full_name:
                raise ValidationError(
                    "A name and password are required to create your account.",
                    code="SIGNUP_DETAILS_REQUIRED",
                )
            validate_password(
                password, user_inputs=[full_name, invitation.email], settings=self.settings
            )
            user = User(
                email=invitation.email,
                full_name=full_name,
                password_hash=hash_password(password),
                # ACTIVE and verified immediately: receiving the invitation email
                # already proved control of this mailbox.
                status=UserStatus.ACTIVE,
                email_verified_at=datetime.now(UTC),
            )
            self.session.add(user)
            await self.session.flush()

        # Asked BEFORE the org is bound, because it deliberately spans organizations:
        # "does this person already have a context anywhere?" cannot be answered from
        # inside one tenant. Ordering matters -- `_has_other_membership` leaves the
        # GUCs cleared, so calling it after the bind below would silently unbind the
        # organization and make the membership INSERT fail its WITH CHECK.
        is_first_context = not await self._has_other_membership(user.id)

        # Bind the invitation's organization so the membership INSERT satisfies the
        # WITH CHECK policy. The caller has proven which org they are acting for by
        # presenting a token that only that org could have issued.
        await bind_tenant(self.session, invitation.organization_id, school_id=invitation.school_id)

        duplicate = (
            await self.session.execute(
                select(Membership.id).where(
                    Membership.user_id == user.id,
                    Membership.school_id == invitation.school_id,
                    Membership.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if duplicate is not None:
            raise ConflictError("You are already a member of this school.", code="ALREADY_MEMBER")

        membership = Membership(
            organization_id=invitation.organization_id,
            user_id=user.id,
            school_id=invitation.school_id,
            role_id=invitation.role_id,
            status=MembershipStatus.ACTIVE,
            # Primary only if this is their first context anywhere -- otherwise a new
            # invitation would silently change where an existing user lands at login.
            is_primary=is_first_context,
            invited_by_user_id=invitation.invited_by_user_id,
            joined_at=datetime.now(UTC),
        )
        self.session.add(membership)

        invitation.status = InvitationStatus.ACCEPTED
        invitation.accepted_at = datetime.now(UTC)
        invitation.accepted_user_id = user.id
        await self.session.flush()

        # The seat was already consumed when the invitation was sent, so acceptance
        # does not consume another. Counting again here is the easiest way to
        # double-charge a customer for one hire.
        await record_audit(
            self.session,
            organization_id=invitation.organization_id,
            school_id=invitation.school_id,
            action=AuditAction.INVITATION_ACCEPTED,
            actor_user_id=user.id,
            actor_membership_id=membership.id,
            entity_type="invitation",
            entity_id=invitation.id,
            after={"user_id": str(user.id), "email": invitation.email},
            ip=ip,
            user_agent=user_agent,
        )
        return user, membership

    async def _has_other_membership(self, user_id: UUID) -> bool:
        await bind_tenant(self.session, None, platform_admin=True)
        try:
            found = (
                await self.session.execute(
                    select(Membership.id)
                    .where(Membership.user_id == user_id, Membership.deleted_at.is_(None))
                    .limit(1)
                )
            ).scalar_one_or_none()
            return found is not None
        finally:
            await bind_tenant(self.session, None)
