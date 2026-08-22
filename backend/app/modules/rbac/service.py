"""Role and membership management, with the escalation guards (spec §5.3).

WHY THIS FILE EXISTS
    Requirement #3 lets a principal define custom roles and assign permissions to
    them. That is a delegation of authority, and every delegation of authority needs
    a ceiling -- otherwise "you may configure roles" silently means "you may grant
    yourself anything".

    Spec §5.3 names three invariants and calls them "the part that gets built wrong".
    They are implemented here, server-side, and they are the reason this module
    exists as something other than CRUD.

RESPONSIBILITY
    Create, edit and delete roles; change their permissions; manage memberships.
    Every mutation enforces the invariants below.

INTERACTIONS
    * `catalog.py` for the permission catalog and scope rules.
    * `core/cache.py` to invalidate the permission cache on change.
    * `tenancy/service.py::count_active_owners` for the last-owner guard.

=============================================================================
THE FOUR INVARIANTS, AND WHY EACH ONE IS NECESSARY
=============================================================================
    1. NO SELF-ELEVATION BEYOND OWN GRANT.  `granted ⊆ actor_permissions`.
       Without it, a principal creates a role holding `billing:manage`, assigns it to
       themselves, and now controls the organization's money. The check is one line;
       its absence is total.

    2. NO EDITING LOCKED ROLES.  `owner` and `principal` have `is_editable = false`.
       Invariant 1 alone does not cover this: a principal editing the PRINCIPAL role
       is granting permissions it already holds, so rule 1 passes -- but the edit
       still changes what every principal in the organization can do, including
       themselves after a future revocation.

    3. NO SCOPE CROSSING.  A school-scoped actor may only touch roles in its own
       school, and no school-scoped role may hold an org-scoped permission.
       Otherwise a principal at one campus edits another campus's roles, or grants
       `school:create` to a teacher.

    4. THE LAST OWNER IS IMMOVABLE. An organization with no owner has no one who can
       pay for it, create schools, or appoint a replacement. There is no in-app
       recovery -- it needs a database operator. So the last active owner membership
       cannot be removed, suspended, or demoted.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from app.api.deps import AuthContext
from app.common.audit import AuditAction, record_audit
from app.core.cache import invalidate_role_permissions
from app.core.exceptions import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.core.logging import get_logger
from app.modules.billing.entitlements import EntitlementService
from app.modules.rbac.catalog import scope_violations, unknown_codes
from app.modules.rbac.models import (
    Membership,
    MembershipStatus,
    Permission,
    Role,
    RolePermission,
    SystemRole,
)
from app.modules.tenancy.service import count_active_owners

logger = get_logger(__name__)


class RbacService:
    """Role and membership operations. Never commits."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.entitlements = EntitlementService(session)

    # -----------------------------------------------------------------------
    # Scope guards
    # -----------------------------------------------------------------------

    def _assert_scope(self, ctx: AuthContext, role: Role) -> None:
        """Invariant 3: an actor may only touch roles inside its own scope.

        An org-level actor (the owner) may touch any role in the organization. A
        school-scoped actor may touch only roles belonging to its own school -- and
        specifically NOT org-level roles, which is what stops a principal from
        editing the owner role.
        """
        if ctx.is_org_level:
            return
        if role.school_id != ctx.school_id:
            raise AuthorizationError(
                "This role belongs to a different school.",
                code="SCOPE_VIOLATION",
            )

    def _assert_can_grant(self, ctx: AuthContext, codes: frozenset[str]) -> None:
        """Invariant 1: an actor may only grant permissions it currently holds.

        Applies to role edits AND to invitations (spec §7.1 step 2) -- otherwise
        inviting someone to a role becomes a way to create authority the inviter
        does not have, which is the same escalation by a different door.
        """
        excess = codes - ctx.permissions
        if excess:
            raise AuthorizationError(
                "You cannot grant permissions you do not hold yourself.",
                code="PERMISSION_ESCALATION",
                details={"excess": sorted(excess)},
            )

    @staticmethod
    def _assert_editable(role: Role) -> None:
        """Invariant 2: system roles marked non-editable cannot be changed."""
        if not role.is_editable:
            raise AuthorizationError(
                f"The '{role.name}' role is managed by the platform and cannot be edited.",
                code="ROLE_NOT_EDITABLE",
            )

    @staticmethod
    def _validate_codes(codes: frozenset[str], *, is_school_scoped: bool) -> None:
        """Reject unknown codes, then org-scoped codes on a school role.

        Order matters for the error message: an unknown code reported as a scope
        error sends the reader hunting in entirely the wrong direction.
        """
        unknown = unknown_codes(codes)
        if unknown:
            raise ValidationError(
                "Unknown permission codes.",
                code="UNKNOWN_PERMISSIONS",
                details={"unknown": sorted(unknown)},
            )

        # Invariant 3, second half. 422 rather than 403: the request is not
        # forbidden, it is malformed -- `billing:manage` on a single campus has no
        # coherent meaning, whoever asks for it.
        violations = scope_violations(codes, is_school_scoped=is_school_scoped)
        if violations:
            raise ValidationError(
                "These permissions can only be granted to organization-level roles.",
                code="PERMISSION_SCOPE_VIOLATION",
                details={"org_scoped": sorted(violations)},
            )

    # -----------------------------------------------------------------------
    # Roles
    # -----------------------------------------------------------------------

    async def list_roles(self, *, school_id: UUID | None) -> list[Role]:
        """Roles for one school, plus the organization's org-level roles.

        Org-level roles are included so the role picker can show `owner` -- greyed
        out and unassignable, but visible, because a principal who cannot see that
        the owner role exists cannot understand why they are unable to grant billing
        access.
        """
        stmt = select(Role).where(
            (Role.school_id == school_id) | (Role.school_id.is_(None))
            if school_id is not None
            else Role.school_id.is_(None)
        )
        return list((await self.session.execute(stmt.order_by(Role.name))).scalars().all())

    async def get_role(self, role_id: UUID) -> Role:
        role = await self.session.get(Role, role_id)
        if role is None:
            raise NotFoundError("Role not found.")
        return role

    async def role_permission_codes(self, role_id: UUID) -> frozenset[str]:
        rows = await self.session.execute(
            select(RolePermission.permission_code).where(RolePermission.role_id == role_id)
        )
        return frozenset(rows.scalars().all())

    async def create_role(
        self,
        *,
        ctx: AuthContext,
        school_id: UUID,
        code: str,
        name: str,
        description: str | None,
        permission_codes: frozenset[str],
    ) -> Role:
        """Create a custom role, counted against the plan's `max_custom_roles`."""
        if ctx.school_id is not None and school_id != ctx.school_id:
            raise AuthorizationError(
                "You can only create roles in your own school.", code="SCOPE_VIOLATION"
            )

        self._validate_codes(permission_codes, is_school_scoped=True)
        self._assert_can_grant(ctx, permission_codes)

        clash = (
            await self.session.execute(
                select(Role.id).where(Role.school_id == school_id, Role.code == code)
            )
        ).scalar_one_or_none()
        if clash is not None:
            raise ConflictError(
                f"A role with code '{code}' already exists in this school.",
                code="ROLE_CODE_TAKEN",
                details={"field": "code"},
            )

        await self.entitlements.check_and_consume(ctx.organization_id, "max_custom_roles")

        role = Role(
            organization_id=ctx.organization_id,
            school_id=school_id,
            code=code,
            name=name,
            description=description,
            is_system=False,
            is_editable=True,
            permissions_version=1,
        )
        self.session.add(role)
        await self.session.flush()

        self.session.add_all(
            RolePermission(
                role_id=role.id,
                organization_id=ctx.organization_id,
                permission_code=c,
            )
            for c in sorted(permission_codes)
        )

        await record_audit(
            self.session,
            organization_id=ctx.organization_id,
            school_id=school_id,
            action=AuditAction.ROLE_CREATED,
            actor_user_id=ctx.user_id,
            actor_membership_id=ctx.membership_id,
            entity_type="role",
            entity_id=role.id,
            after={"code": code, "name": name, "permissions": sorted(permission_codes)},
        )
        return role

    async def update_role(
        self,
        *,
        ctx: AuthContext,
        role_id: UUID,
        name: str | None,
        description: str | None,
    ) -> Role:
        """Rename or re-describe a role. Permissions change through `set_permissions`.

        Deliberately separate operations. A rename is cosmetic; a permission change
        alters who can do what. Sharing an endpoint would mean the audit trail cannot
        distinguish them, and a UI that saves the whole form on every keystroke would
        churn `permissions_version` -- invalidating every token for that role each
        time someone fixes a typo in a description.
        """
        role = await self.get_role(role_id)
        self._assert_scope(ctx, role)
        self._assert_editable(role)

        before = {"name": role.name, "description": role.description}
        if name is not None:
            role.name = name
        if description is not None:
            role.description = description

        await record_audit(
            self.session,
            organization_id=ctx.organization_id,
            school_id=role.school_id,
            action=AuditAction.ROLE_UPDATED,
            actor_user_id=ctx.user_id,
            actor_membership_id=ctx.membership_id,
            entity_type="role",
            entity_id=role.id,
            before=before,
            after={"name": role.name, "description": role.description},
        )
        return role

    async def set_permissions(
        self,
        *,
        ctx: AuthContext,
        role_id: UUID,
        permission_codes: frozenset[str],
    ) -> Role:
        """Replace a role's permission set. THE most security-sensitive operation here.

        =====================================================================
        BUMPING `permissions_version` IS WHAT MAKES REVOCATION IMMEDIATE
        =====================================================================
            The cache key is `perm:{role_id}:{pv}`. Incrementing `pv` means every
            access token issued before this moment carries a stale version, so the
            auth dependency resolves against a fresh key and picks up the new set on
            the affected member's very NEXT request.

            Without the bump, a revoked permission would keep working until every
            existing token expired -- the classic "I removed their access fifteen
            minutes ago and they can still delete records" bug that spec §4.2 calls
            out by name.

            Note the increment happens even if the set is unchanged. Detecting a
            no-op edit and skipping it would save a cache miss and introduce a subtle
            correctness hole the first time the comparison was wrong.
        """
        role = await self.get_role(role_id)
        self._assert_scope(ctx, role)
        self._assert_editable(role)
        self._validate_codes(permission_codes, is_school_scoped=role.school_id is not None)
        self._assert_can_grant(ctx, permission_codes)

        previous = await self.role_permission_codes(role_id)
        old_version = role.permissions_version

        await self.session.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
        self.session.add_all(
            RolePermission(
                role_id=role_id,
                organization_id=role.organization_id,
                permission_code=c,
            )
            for c in sorted(permission_codes)
        )

        role.permissions_version += 1
        await self.session.flush()

        # Best-effort eviction of the superseded key. Correctness does not depend on
        # it -- nothing reads the old key after the bump -- but it stops abandoned
        # versions sitting in memory for the full TTL.
        await invalidate_role_permissions(str(role_id), old_version)

        await record_audit(
            self.session,
            organization_id=ctx.organization_id,
            school_id=role.school_id,
            action=AuditAction.ROLE_PERMISSIONS_CHANGED,
            actor_user_id=ctx.user_id,
            actor_membership_id=ctx.membership_id,
            entity_type="role",
            entity_id=role_id,
            before={"permissions": sorted(previous)},
            after={"permissions": sorted(permission_codes)},
        )
        logger.info(
            "role_permissions_changed",
            role_id=str(role_id),
            added=sorted(permission_codes - previous),
            removed=sorted(previous - permission_codes),
            new_version=role.permissions_version,
        )
        return role

    async def delete_role(self, *, ctx: AuthContext, role_id: UUID) -> None:
        """Delete a custom role, refusing while anyone still holds it.

        Spec §5.3: "Deleting a role requires reassigning its members first (409 with
        the blocking member count)." Cascading the delete would strip those people of
        access as a side effect of tidying up, with no record of what they lost --
        which is why the FK is RESTRICT rather than CASCADE.
        """
        role = await self.get_role(role_id)
        self._assert_scope(ctx, role)

        if role.is_system:
            raise AuthorizationError("System roles cannot be deleted.", code="ROLE_IS_SYSTEM")

        holders = (
            await self.session.execute(
                select(func.count())
                .select_from(Membership)
                .where(Membership.role_id == role_id, Membership.deleted_at.is_(None))
            )
        ).scalar_one()

        if holders:
            raise ConflictError(
                f"{holders} member(s) still hold this role. Reassign them first.",
                code="ROLE_IN_USE",
                details={"members": holders},
            )

        await self.session.execute(delete(RolePermission).where(RolePermission.role_id == role_id))
        await self.session.delete(role)
        await self.entitlements.release(ctx.organization_id, "max_custom_roles")

        await record_audit(
            self.session,
            organization_id=ctx.organization_id,
            school_id=role.school_id,
            action=AuditAction.ROLE_DELETED,
            actor_user_id=ctx.user_id,
            actor_membership_id=ctx.membership_id,
            entity_type="role",
            entity_id=role_id,
            before={"code": role.code, "name": role.name},
        )

    # -----------------------------------------------------------------------
    # Memberships
    # -----------------------------------------------------------------------

    async def list_members(self, *, school_id: UUID | None) -> list[Membership]:
        """Staff of one school, or of the whole organization for an org-level caller."""
        stmt = (
            select(Membership)
            .options(joinedload(Membership.user), joinedload(Membership.role))
            .where(Membership.deleted_at.is_(None))
        )
        if school_id is not None:
            stmt = stmt.where(Membership.school_id == school_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def _get_member(self, ctx: AuthContext, membership_id: UUID) -> Membership:
        membership = (
            await self.session.execute(
                select(Membership)
                .options(joinedload(Membership.role))
                .where(Membership.id == membership_id, Membership.deleted_at.is_(None))
            )
        ).scalar_one_or_none()

        if membership is None:
            raise NotFoundError("Member not found.")
        if not ctx.is_org_level and membership.school_id != ctx.school_id:
            raise AuthorizationError(
                "This member belongs to a different school.", code="SCOPE_VIOLATION"
            )
        return membership

    async def _assert_not_last_owner(self, membership: Membership) -> None:
        """Invariant 4. Raises 409 when this is the organization's only owner."""
        if membership.role.code != SystemRole.OWNER.value:
            return
        if await count_active_owners(self.session, membership.organization_id) <= 1:
            raise ConflictError(
                "This is the organization's only owner. Transfer ownership first.",
                code="LAST_OWNER",
            )

    @staticmethod
    def _assert_not_self(ctx: AuthContext, membership: Membership) -> None:
        """Spec §5.3: a user cannot suspend or remove their own membership.

        Not paternalism -- it is the only thing standing between a mis-click and an
        administrator locking themselves out of an organization they alone
        administer. Leaving is a different operation with a different confirmation.
        """
        if membership.id == ctx.membership_id:
            raise ConflictError(
                "You cannot change your own membership here.", code="SELF_MODIFICATION"
            )

    async def change_member_role(
        self, *, ctx: AuthContext, membership_id: UUID, new_role_id: UUID
    ) -> Membership:
        """Move a member to a different role.

        The escalation guard applies to the TARGET role's permission set: assigning
        someone a role more powerful than your own would create authority you do not
        hold, just at one remove.
        """
        membership = await self._get_member(ctx, membership_id)
        self._assert_not_self(ctx, membership)
        await self._assert_not_last_owner(membership)

        new_role = await self.get_role(new_role_id)
        self._assert_scope(ctx, new_role)

        if new_role.school_id != membership.school_id:
            raise ValidationError(
                "The role's scope does not match the member's scope.",
                code="ROLE_SCOPE_MISMATCH",
            )
        self._assert_can_grant(ctx, await self.role_permission_codes(new_role_id))

        old_role_code = membership.role.code
        membership.role_id = new_role_id

        await record_audit(
            self.session,
            organization_id=ctx.organization_id,
            school_id=membership.school_id,
            action=AuditAction.MEMBER_ROLE_CHANGED,
            actor_user_id=ctx.user_id,
            actor_membership_id=ctx.membership_id,
            entity_type="membership",
            entity_id=membership_id,
            before={"role": old_role_code},
            after={"role": new_role.code},
        )
        return membership

    async def set_member_status(
        self, *, ctx: AuthContext, membership_id: UUID, suspended: bool
    ) -> Membership:
        """Suspend or reactivate a member.

        Suspension takes effect on their very next request: the auth dependency
        re-reads the membership every time, so a suspended member does not keep
        working until their token expires.
        """
        membership = await self._get_member(ctx, membership_id)
        self._assert_not_self(ctx, membership)
        if suspended:
            await self._assert_not_last_owner(membership)

        membership.status = MembershipStatus.SUSPENDED if suspended else MembershipStatus.ACTIVE

        await record_audit(
            self.session,
            organization_id=ctx.organization_id,
            school_id=membership.school_id,
            action=AuditAction.MEMBER_SUSPENDED if suspended else AuditAction.MEMBER_REACTIVATED,
            actor_user_id=ctx.user_id,
            actor_membership_id=ctx.membership_id,
            entity_type="membership",
            entity_id=membership_id,
            after={"status": membership.status.value},
        )
        return membership

    async def remove_member(self, *, ctx: AuthContext, membership_id: UUID) -> None:
        """Remove a member and return their seat to the plan allowance.

        SOFT delete. The `audit_logs` rows they generated reference this membership,
        and a hard delete would either cascade those away or leave dangling ids --
        both of which destroy the answer to "who changed this student's grade".
        """
        membership = await self._get_member(ctx, membership_id)
        self._assert_not_self(ctx, membership)
        await self._assert_not_last_owner(membership)

        membership.deleted_at = datetime.now(UTC)
        await self.entitlements.release(ctx.organization_id, "max_staff")

        await record_audit(
            self.session,
            organization_id=ctx.organization_id,
            school_id=membership.school_id,
            action=AuditAction.MEMBER_REMOVED,
            actor_user_id=ctx.user_id,
            actor_membership_id=ctx.membership_id,
            entity_type="membership",
            entity_id=membership_id,
            before={"role": membership.role.code, "user_id": str(membership.user_id)},
        )

    # -----------------------------------------------------------------------
    # Catalog
    # -----------------------------------------------------------------------

    async def permission_catalog(self) -> list[Permission]:
        """The full catalog, for the role-matrix editor (spec §8 `GET /permissions`)."""
        return list(
            (
                await self.session.execute(
                    select(Permission).order_by(Permission.category, Permission.code)
                )
            )
            .scalars()
            .all()
        )
