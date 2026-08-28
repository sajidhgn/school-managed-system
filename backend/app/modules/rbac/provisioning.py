"""Role and membership provisioning for new organizations and schools.

WHY THIS FILE EXISTS
    Two moments in the product create access out of nothing: an organization is
    registered, and a school is created inside it. Both must produce a correct,
    complete set of roles and at least one usable membership, atomically. Getting
    either half-done leaves a customer locked out of the account they just paid for.

    Kept separate from `service.py` because these run during signup and onboarding --
    before any `AuthContext` exists -- while `service.py` operates on behalf of an
    authenticated actor and enforces the escalation guards. Mixing them would blur
    which functions are permission-checked and which are not.

RESPONSIBILITY
    Create system roles with their catalog-defined permission sets, and mint the
    memberships that follow from them.

INTERACTIONS
    * `modules/auth/service.py::register` -> `provision_organization`
    * `modules/tenancy/service.py::create_school` -> `provision_school`

=============================================================================
ONE HUMAN, ONE ROLE
=============================================================================
    On signup the user gets an ORG-LEVEL `principal` membership (`school_id IS
    NULL`) holding the entire catalog: billing, school creation, and every
    school-scoped capability across every campus.

    Creating a school adds NOTHING to that membership. The principal already reaches
    the new campus through the org-level row, so there is no second membership to
    mint, no duplicate line in the members list, and no second entry in the context
    switcher for the same person.

    This is what "one human, one role" costs and buys. It costs the ability to hand
    someone full control of a single campus without also handing them billing --
    there is no per-campus admin role. It buys an access model a customer can
    actually read: a member holds exactly one role, and its scope is either the
    organization or one school.

    Handing the organization to someone else is `transfer_ownership`, which moves
    this single org-level membership rather than juggling two.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError
from app.modules.rbac.catalog import (
    LOCKED_ROLE_CODES,
    SCHOOL_SYSTEM_ROLES,
    SYSTEM_ROLE_META,
    SYSTEM_ROLE_PERMISSIONS,
)
from app.modules.rbac.models import (
    Membership,
    MembershipStatus,
    Role,
    RolePermission,
    SystemRole,
)


async def _create_role(
    session: AsyncSession,
    *,
    organization_id: UUID,
    school_id: UUID | None,
    system_role: SystemRole,
) -> Role:
    """Create one system role and attach its catalog-defined permissions."""
    name, description = SYSTEM_ROLE_META[system_role]

    role = Role(
        organization_id=organization_id,
        school_id=school_id,
        code=system_role.value,
        name=name,
        description=description,
        is_system=True,
        # `owner` and `principal` are locked so a principal cannot widen its own
        # role or the owner's (spec §5.3 rule 2). `teacher` and `accountant` ship as
        # starting points that each customer is expected to tailor -- a school that
        # cannot adjust what its teachers may do will simply grant everyone
        # principal, which is worse than an editable teacher role.
        is_editable=system_role.value not in LOCKED_ROLE_CODES,
        permissions_version=1,
    )
    session.add(role)
    # Flush to obtain `role.id` before inserting the join rows below. This is the
    # narrow, legitimate use of flush inside a service: the id is needed within the
    # same unit of work, and the request-scoped transaction still owns the commit.
    await session.flush()

    session.add_all(
        RolePermission(
            role_id=role.id,
            organization_id=organization_id,
            permission_code=code,
        )
        for code in sorted(SYSTEM_ROLE_PERMISSIONS[system_role])
    )
    return role


async def provision_organization(
    session: AsyncSession,
    *,
    organization_id: UUID,
    owner_user_id: UUID,
) -> tuple[Role, Membership]:
    """Create the org-level `principal` role and grant it to the registering user.

    Called inside the registration transaction, so a failure here rolls the whole
    signup back rather than leaving an organization nobody can administer.

    This is the ONLY membership the registering user ever receives. Creating their
    first school does not add a second one -- see the module docstring.

    Returns the role and membership so the caller can reference them in its audit
    row without a second query.
    """
    principal_role = await _create_role(
        session,
        organization_id=organization_id,
        school_id=None,
        system_role=SystemRole.PRINCIPAL,
    )

    membership = Membership(
        organization_id=organization_id,
        user_id=owner_user_id,
        school_id=None,  # org-level: spans every school in the organization
        role_id=principal_role.id,
        status=MembershipStatus.ACTIVE,
        is_primary=True,
        joined_at=datetime.now(UTC),
    )
    session.add(membership)
    await session.flush()

    return principal_role, membership


async def provision_school(
    session: AsyncSession,
    *,
    organization_id: UUID,
    school_id: UUID,
) -> dict[SystemRole, Role]:
    """Create the school's system roles. Mints no memberships.

    NOTHING is granted to the creating user here. They hold the org-level
    `principal` membership, which already reaches this school and everything in it;
    adding a school-scoped row would give them a second role that grants strictly
    less than the one they have, and put their name in the members list twice.

    Returns the roles keyed by their system code, so the caller can pick out
    `SystemRole.TEACHER` to pre-select in an invitation form without re-querying.
    """
    return {
        system_role: await _create_role(
            session,
            organization_id=organization_id,
            school_id=school_id,
            system_role=system_role,
        )
        for system_role in SCHOOL_SYSTEM_ROLES
    }


async def get_system_role(
    session: AsyncSession,
    *,
    organization_id: UUID,
    school_id: UUID | None,
    code: SystemRole,
) -> Role:
    """Fetch a seeded system role, raising if provisioning never ran.

    A missing system role means an organization or school was created without its
    roles -- a broken invariant, not a user error. Failing loudly beats returning
    None and letting the caller create a membership with a null role, which the
    database would reject anyway but far from the actual cause.
    """
    role = (
        await session.execute(
            select(Role).where(
                Role.organization_id == organization_id,
                Role.school_id.is_(None) if school_id is None else Role.school_id == school_id,
                Role.code == code.value,
            )
        )
    ).scalar_one_or_none()

    if role is None:
        raise ConflictError(
            f"System role '{code.value}' is missing for this scope. "
            "The organization or school was not provisioned correctly.",
            code="SYSTEM_ROLE_MISSING",
        )
    return role
