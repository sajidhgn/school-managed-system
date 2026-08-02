"""Organization and school operations.

WHY THIS FILE EXISTS
    School creation is where three subsystems meet: entitlements (does the plan
    allow another school?), provisioning (create its roles), and the owner/principal
    split (grant principal on the first one). Ownership transfer is where the
    system's most dangerous invariant lives. Both belong in one reviewed place.

RESPONSIBILITY
    Mutate organizations and schools, enforcing the invariants that go with them.

INTERACTIONS
    * `modules/billing/entitlements.py` before every school create.
    * `modules/rbac/provisioning.py` after it.

=============================================================================
OWNERSHIP TRANSFER IS THE MOST DANGEROUS OPERATION IN THE SYSTEM
=============================================================================
    Spec §5.3: "The last active owner membership of an organization cannot be
    removed, suspended, or demoted. Ownership transfer is a single atomic operation
    that promotes the new owner before demoting the old one."

    The ordering is not stylistic. Demote-then-promote has a window in which the
    organization has NO owner. If anything fails in that window -- a constraint
    violation, a lost connection, a deploy -- nobody can access billing, create
    schools, or appoint a new owner. There is no in-app recovery from that state;
    it requires a database operator.

    Promote-then-demote has no such window. At every instant there is at least one
    owner, and a failure leaves two, which is recoverable through the UI.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditAction, record_audit
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.modules.billing.entitlements import EntitlementService
from app.modules.rbac.models import Membership, MembershipStatus, Role, SystemRole
from app.modules.rbac.provisioning import get_system_role, provision_school
from app.modules.tenancy.models import Organization, School, SchoolStatus

logger = get_logger(__name__)


class TenancyService:
    """Organization and school mutations. Never commits."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.entitlements = EntitlementService(session)

    # -----------------------------------------------------------------------
    # Organization
    # -----------------------------------------------------------------------

    async def get_organization(self, organization_id: UUID) -> Organization:
        organization = await self.session.get(Organization, organization_id)
        if organization is None or organization.deleted_at is not None:
            raise NotFoundError("Organization not found.")
        return organization

    async def update_organization(
        self,
        *,
        organization_id: UUID,
        changes: dict[str, object],
        actor_user_id: UUID,
        actor_membership_id: UUID,
    ) -> Organization:
        organization = await self.get_organization(organization_id)

        before = {k: getattr(organization, k) for k in changes}
        for field, value in changes.items():
            setattr(organization, field, value)

        await record_audit(
            self.session,
            organization_id=organization_id,
            action=AuditAction.ORGANIZATION_UPDATED,
            actor_user_id=actor_user_id,
            actor_membership_id=actor_membership_id,
            entity_type="organization",
            entity_id=organization_id,
            before={k: str(v) for k, v in before.items()},
            after={k: str(v) for k, v in changes.items()},
        )
        return organization

    async def transfer_ownership(
        self,
        *,
        organization_id: UUID,
        new_owner_membership_id: UUID,
        actor_user_id: UUID,
        actor_membership_id: UUID,
    ) -> Organization:
        """Hand the organization to another member. PROMOTE FIRST, THEN DEMOTE.

        See the module docstring for why that order is load-bearing.
        """
        organization = await self.get_organization(organization_id)
        owner_role = await get_system_role(
            self.session,
            organization_id=organization_id,
            school_id=None,
            code=SystemRole.OWNER,
        )

        new_membership = await self.session.get(Membership, new_owner_membership_id)
        # RLS has already scoped this to the caller's organization, so a membership
        # from another tenant simply is not found.
        if new_membership is None or new_membership.deleted_at is not None:
            raise NotFoundError("No such member in this organization.")
        if new_membership.status is not MembershipStatus.ACTIVE:
            raise ValidationError(
                "Ownership can only be transferred to an active member.",
                code="MEMBER_NOT_ACTIVE",
            )
        if new_membership.user_id == organization.owner_user_id:
            raise ConflictError("This member already owns the organization.", code="ALREADY_OWNER")

        outgoing = (
            await self.session.execute(
                select(Membership).where(
                    Membership.organization_id == organization_id,
                    Membership.user_id == organization.owner_user_id,
                    Membership.school_id.is_(None),
                    Membership.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

        # --- STEP 1: PROMOTE. There are now two owners, briefly. ---
        #
        # The new owner may hold a school-scoped membership (a principal being
        # promoted), which cannot simply be repointed at the org-level owner role --
        # the unique index is on (user, org, school), so an org-level membership is a
        # different row. Reuse an existing org-level one if present, else create it.
        promoted = (
            await self.session.execute(
                select(Membership).where(
                    Membership.organization_id == organization_id,
                    Membership.user_id == new_membership.user_id,
                    Membership.school_id.is_(None),
                    Membership.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()

        if promoted is None:
            promoted = Membership(
                organization_id=organization_id,
                user_id=new_membership.user_id,
                school_id=None,
                role_id=owner_role.id,
                status=MembershipStatus.ACTIVE,
                is_primary=True,
                joined_at=datetime.now(UTC),
            )
            self.session.add(promoted)
        else:
            promoted.role_id = owner_role.id
            promoted.status = MembershipStatus.ACTIVE

        organization.owner_user_id = new_membership.user_id
        await self.session.flush()

        # --- STEP 2: DEMOTE. Only now, with the new owner already in place. ---
        #
        # The outgoing owner is removed from the org-level scope rather than
        # downgraded to some lesser org role -- there is no such role. Their
        # school-scoped memberships are untouched, so a founder who hands over
        # billing but stays principal of a campus keeps that access.
        if outgoing is not None and outgoing.id != promoted.id:
            outgoing.deleted_at = datetime.now(UTC)

        await record_audit(
            self.session,
            organization_id=organization_id,
            action=AuditAction.OWNERSHIP_TRANSFERRED,
            actor_user_id=actor_user_id,
            actor_membership_id=actor_membership_id,
            entity_type="organization",
            entity_id=organization_id,
            before={"owner_user_id": str(actor_user_id)},
            after={"owner_user_id": str(new_membership.user_id)},
        )
        logger.info(
            "ownership_transferred",
            organization_id=str(organization_id),
            to_user_id=str(new_membership.user_id),
        )
        return organization

    # -----------------------------------------------------------------------
    # Schools
    # -----------------------------------------------------------------------

    async def list_schools(self, *, school_id_filter: UUID | None = None) -> list[School]:
        """Schools visible to the caller.

        `school_id_filter` implements spec §2.3: a school-scoped membership sees only
        its own campus, while an org-level owner (filter None) sees all of them. RLS
        has already confined the query to the organization; this narrows it further
        inside that boundary.
        """
        stmt = select(School).where(School.deleted_at.is_(None)).order_by(School.name)
        if school_id_filter is not None:
            stmt = stmt.where(School.id == school_id_filter)
        return list((await self.session.execute(stmt)).scalars().all())

    async def get_school(self, school_id: UUID, *, allowed_school_id: UUID | None) -> School:
        """One school, respecting the caller's scope.

        A school-scoped caller asking for a DIFFERENT school in the same organization
        gets 403 -- not 404. Spec §12 is specific about this: cross-ORGANIZATION
        access returns 404 so existence is never disclosed, but cross-SCHOOL access
        inside one's own organization returns 403, because the caller already knows
        their organization has other campuses. Hiding it would be pointless
        obfuscation that only confuses a legitimate user who picked the wrong menu.
        """
        if allowed_school_id is not None and school_id != allowed_school_id:
            from app.core.exceptions import AuthorizationError

            raise AuthorizationError(
                "Your access is limited to your own school.",
                code="SCHOOL_SCOPE_VIOLATION",
            )

        school = await self.session.get(School, school_id)
        if school is None or school.deleted_at is not None:
            raise NotFoundError("School not found.")
        return school

    async def create_school(
        self,
        *,
        organization_id: UUID,
        actor_user_id: UUID,
        actor_membership_id: UUID,
        name: str,
        code: str,
        **fields: object,
    ) -> tuple[School, bool]:
        """Create a school, its system roles, and possibly a principal membership.

        =====================================================================
        THE ENTITLEMENT CHECK COMES FIRST, AND IT RESERVES CAPACITY
        =====================================================================
            `check_and_consume` runs BEFORE the INSERT, in the same transaction. It
            is a single atomic UPDATE whose WHERE clause carries the limit, so two
            concurrent "create school" requests on a 1-school plan cannot both pass.
            A plain count-then-insert would let a double-clicked button create two.

            Because it shares the transaction, a failure below rolls the reservation
            back too -- capacity is never consumed by a school that was not created.

        Returns the school and whether the caller was granted principal on it.
        """
        await self.entitlements.check_and_consume(organization_id, "max_schools")

        existing = (
            await self.session.execute(
                select(School.id).where(School.code == code.upper(), School.deleted_at.is_(None))
            )
        ).scalar_one_or_none()
        if existing is not None:
            raise ConflictError(
                f"A school with code '{code.upper()}' already exists in this organization.",
                code="SCHOOL_CODE_TAKEN",
                details={"field": "code"},
            )

        # Is this the organization's FIRST school? Decided before the insert, so the
        # new row does not count itself.
        school_count = (
            await self.session.execute(
                select(func.count()).select_from(School).where(School.deleted_at.is_(None))
            )
        ).scalar_one()
        is_first_school = school_count == 0

        school = School(
            organization_id=organization_id,
            name=name,
            code=code.upper(),
            slug=_slugify(name),
            status=SchoolStatus.ACTIVE,
            **fields,
        )
        self.session.add(school)
        await self.session.flush()

        # Spec §4.3B step 6: the owner is auto-granted principal on their FIRST
        # school, which is what lands them in the admin panel. Not on later ones --
        # see `provision_school` for why.
        await provision_school(
            self.session,
            organization_id=organization_id,
            school_id=school.id,
            grant_principal_to_user_id=actor_user_id if is_first_school else None,
        )
        if is_first_school:
            await self.entitlements.check_and_consume(organization_id, "max_staff")

        await record_audit(
            self.session,
            organization_id=organization_id,
            school_id=school.id,
            action=AuditAction.SCHOOL_CREATED,
            actor_user_id=actor_user_id,
            actor_membership_id=actor_membership_id,
            entity_type="school",
            entity_id=school.id,
            after={"name": name, "code": school.code},
        )
        return school, is_first_school

    async def update_school(
        self,
        *,
        school_id: UUID,
        organization_id: UUID,
        changes: dict[str, object],
        actor_user_id: UUID,
        actor_membership_id: UUID,
        allowed_school_id: UUID | None,
    ) -> School:
        school = await self.get_school(school_id, allowed_school_id=allowed_school_id)

        before = {k: getattr(school, k) for k in changes}
        for field, value in changes.items():
            setattr(school, field, value)

        await record_audit(
            self.session,
            organization_id=organization_id,
            school_id=school_id,
            action=AuditAction.SCHOOL_UPDATED,
            actor_user_id=actor_user_id,
            actor_membership_id=actor_membership_id,
            entity_type="school",
            entity_id=school_id,
            before={k: str(v) for k, v in before.items()},
            after={k: str(v) for k, v in changes.items()},
        )
        return school

    async def archive_school(
        self,
        *,
        school_id: UUID,
        organization_id: UUID,
        actor_user_id: UUID,
        actor_membership_id: UUID,
        allowed_school_id: UUID | None,
    ) -> School:
        """Archive a school and return its seat to the plan allowance.

        ARCHIVE, NOT DELETE. The school's students, grades and fee history remain --
        they are records a school is often legally required to retain for years after
        a campus closes. Status becomes `archived` and the row is soft-deleted, so it
        disappears from lists while staying restorable and exportable.
        """
        school = await self.get_school(school_id, allowed_school_id=allowed_school_id)

        school.status = SchoolStatus.ARCHIVED
        school.deleted_at = datetime.now(UTC)
        await self.entitlements.release(organization_id, "max_schools")

        await record_audit(
            self.session,
            organization_id=organization_id,
            school_id=school_id,
            action=AuditAction.SCHOOL_ARCHIVED,
            actor_user_id=actor_user_id,
            actor_membership_id=actor_membership_id,
            entity_type="school",
            entity_id=school_id,
        )
        return school


def _slugify(value: str) -> str:
    """URL-safe form of a name. Unique per organization, enforced by a partial index."""
    slug = "".join(c if c.isalnum() else "-" for c in value.lower())
    return "-".join(filter(None, slug.split("-")))[:60] or "school"


async def count_active_owners(session: AsyncSession, organization_id: UUID) -> int:
    """How many live org-level owner memberships an organization has.

    Used by the RBAC service to enforce "the last owner cannot be removed" (spec
    §5.3). Lives here rather than there because it is a question about the
    organization's structure, and both modules ask it.
    """
    owner_role_id = (
        await session.execute(
            select(Role.id).where(
                Role.organization_id == organization_id,
                Role.school_id.is_(None),
                Role.code == SystemRole.OWNER.value,
            )
        )
    ).scalar_one_or_none()
    if owner_role_id is None:
        return 0

    return (
        await session.execute(
            select(func.count())
            .select_from(Membership)
            .where(
                Membership.organization_id == organization_id,
                Membership.role_id == owner_role_id,
                Membership.deleted_at.is_(None),
                Membership.status == MembershipStatus.ACTIVE,
            )
        )
    ).scalar_one()
