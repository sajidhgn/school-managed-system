"""Role, permission and member routes (spec §8 "Roles & permissions", "Members")."""

from __future__ import annotations

from itertools import groupby
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from sqlalchemy import func, select

from app.api.deps import AuthContext, CurrentAuth, DbSession, require
from app.core.exceptions import AuthorizationError, ValidationError
from app.modules.rbac.models import Membership
from app.modules.rbac.schemas import (
    MemberBranchAssign,
    MemberCreate,
    MemberRead,
    MemberUpdate,
    PermissionCategory,
    PermissionRead,
    RoleCreate,
    RoleDetail,
    RolePermissionsUpdate,
    RoleRead,
    RoleUpdate,
    TeacherOption,
)
from app.modules.rbac.service import RbacService

# Mounted at `/schools/{school_id}/...` by the aggregator, matching spec §8.
roles_router = APIRouter()
members_router = APIRouter()
permissions_router = APIRouter()


def _assert_school_scope(ctx: AuthContext, school_id: UUID) -> None:
    """A school-scoped caller may only address its own school.

    403, not 404. Spec §12 distinguishes the two: cross-ORGANIZATION access returns
    404 so existence is never disclosed, but cross-SCHOOL access inside one's own
    organization returns 403 -- the caller already knows their organization has other
    campuses, so hiding it would only confuse someone who picked the wrong menu item.
    """
    if ctx.school_id is not None and ctx.school_id != school_id:
        raise AuthorizationError(
            "Your access is limited to your own school.", code="SCHOOL_SCOPE_VIOLATION"
        )


# ---------------------------------------------------------------------------
# Permission catalog
# ---------------------------------------------------------------------------


@permissions_router.get("", response_model=list[PermissionCategory])
async def list_permissions(session: DbSession, ctx: CurrentAuth) -> list[PermissionCategory]:
    """The permission catalog, grouped by category (spec §8 `GET /permissions`).

    Available to any authenticated member: it is a description of what the software
    can do, identical for every customer, and the role editor cannot render without
    it. It discloses nothing about who holds what.
    """
    permissions = await RbacService(session).permission_catalog()
    reads = [PermissionRead.model_validate(p) for p in permissions]
    # Already ordered by (category, code) in the query, which `groupby` requires --
    # it groups consecutive runs, not all occurrences.
    return [
        PermissionCategory(category=category, permissions=list(items))
        for category, items in groupby(reads, key=lambda p: p.category)
    ]


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


@roles_router.get("/{school_id}/roles", response_model=list[RoleRead])
async def list_roles(
    school_id: UUID,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("role:read"))],
) -> list[RoleRead]:
    _assert_school_scope(ctx, school_id)
    roles = await RbacService(session).list_roles(school_id=school_id)
    return [RoleRead.model_validate(r) for r in roles]


@roles_router.post(
    "/{school_id}/roles", response_model=RoleDetail, status_code=status.HTTP_201_CREATED
)
async def create_role(
    school_id: UUID,
    payload: RoleCreate,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("role:create", "role:assign_permissions"))],
) -> RoleDetail:
    """Create a custom role.

    Requires BOTH `role:create` and `role:assign_permissions`, because the request
    carries a permission set. Requiring only the first would let someone who may
    create empty roles create a fully-privileged one in the same call.
    """
    _assert_school_scope(ctx, school_id)
    service = RbacService(session)
    role = await service.create_role(
        ctx=ctx,
        school_id=school_id,
        code=payload.code,
        name=payload.name,
        description=payload.description,
        permission_codes=frozenset(payload.permissions),
    )
    return RoleDetail(
        **RoleRead.model_validate(role).model_dump(),
        permissions=sorted(payload.permissions),
        member_count=0,
    )


@roles_router.get("/{school_id}/roles/{role_id}", response_model=RoleDetail)
async def get_role(
    school_id: UUID,
    role_id: UUID,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("role:read"))],
) -> RoleDetail:
    _assert_school_scope(ctx, school_id)
    service = RbacService(session)
    role = await service.get_role(role_id)
    codes = await service.role_permission_codes(role_id)

    member_count = (
        await session.execute(
            select(func.count())
            .select_from(Membership)
            .where(Membership.role_id == role_id, Membership.deleted_at.is_(None))
        )
    ).scalar_one()

    return RoleDetail(
        **RoleRead.model_validate(role).model_dump(),
        permissions=sorted(codes),
        member_count=member_count,
    )


@roles_router.patch("/{school_id}/roles/{role_id}", response_model=RoleRead)
async def update_role(
    school_id: UUID,
    role_id: UUID,
    payload: RoleUpdate,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("role:update"))],
) -> RoleRead:
    """Rename or re-describe. Permissions change through the PUT below."""
    _assert_school_scope(ctx, school_id)
    role = await RbacService(session).update_role(
        ctx=ctx, role_id=role_id, name=payload.name, description=payload.description
    )
    return RoleRead.model_validate(role)


@roles_router.put("/{school_id}/roles/{role_id}/permissions", response_model=RoleDetail)
async def set_role_permissions(
    school_id: UUID,
    role_id: UUID,
    payload: RolePermissionsUpdate,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("role:assign_permissions"))],
) -> RoleDetail:
    """Replace a role's permission set (spec §8 `PUT .../permissions`).

    PUT, not PATCH, because the body is the COMPLETE new set. Enforces all three
    escalation guards and bumps `permissions_version`, so affected members pick up
    the change on their next request rather than when their token expires.
    """
    _assert_school_scope(ctx, school_id)
    service = RbacService(session)
    role = await service.set_permissions(
        ctx=ctx, role_id=role_id, permission_codes=frozenset(payload.codes)
    )
    member_count = (
        await session.execute(
            select(func.count())
            .select_from(Membership)
            .where(Membership.role_id == role_id, Membership.deleted_at.is_(None))
        )
    ).scalar_one()

    return RoleDetail(
        **RoleRead.model_validate(role).model_dump(),
        permissions=sorted(payload.codes),
        member_count=member_count,
    )


@roles_router.delete("/{school_id}/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(
    school_id: UUID,
    role_id: UUID,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("role:delete"))],
) -> None:
    """Delete a custom role. 409 while any member still holds it."""
    _assert_school_scope(ctx, school_id)
    await RbacService(session).delete_role(ctx=ctx, role_id=role_id)


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


def _member_read(membership: Membership) -> MemberRead:
    return MemberRead(
        membership_id=membership.id,
        user_id=membership.user_id,
        email=membership.user.email,
        full_name=membership.user.full_name,
        school_id=membership.school_id,
        role_id=membership.role_id,
        role_code=membership.role.code,
        role_name=membership.role.name,
        status=membership.status.value,
        is_primary=membership.is_primary,
        joined_at=membership.joined_at,
        created_at=membership.created_at,
    )


@members_router.get("/{school_id}/members", response_model=list[MemberRead])
async def list_members(
    school_id: UUID,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("member:read"))],
) -> list[MemberRead]:
    _assert_school_scope(ctx, school_id)
    members = await RbacService(session).list_members(school_id=school_id)
    return [_member_read(m) for m in members]


@members_router.get("/{school_id}/teachers", response_model=list[TeacherOption])
async def list_teachers(
    school_id: UUID,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("teacher:read"))],
) -> list[TeacherOption]:
    """The branch's teaching staff, for the class-teacher and curriculum pickers.

    Gated on `teacher:read` ("View teaching staff assignments") rather than on
    `member:read`. They overlap today, but they answer different questions: this is
    "who can I put in front of this class", not "show me the staff table". A school
    that narrows its front-office role to the latter should not lose the former.

    WHY THIS IS NOT A FILTER THE BROWSER APPLIES
        Deciding who counts as a teacher means reading role permissions, and the only
        way to do that client-side is to ship every role's permission set to the page
        and re-implement `TEACHING_PERMISSIONS` in TypeScript. Two copies of one rule
        drift, and the copy that drifts is the one on the machine we do not control.
    """
    _assert_school_scope(ctx, school_id)
    members = await RbacService(session).list_teaching_staff(school_id=school_id)
    return [
        TeacherOption(
            user_id=m.user_id,
            full_name=m.user.full_name,
            email=m.user.email,
            role_name=m.role.name,
        )
        for m in members
    ]


@members_router.post(
    "/{school_id}/members", response_model=MemberRead, status_code=status.HTTP_201_CREATED
)
async def create_member(
    school_id: UUID,
    payload: MemberCreate,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("member:invite"))],
) -> MemberRead:
    """Create a login-ready member in a branch without sending an invitation."""
    _assert_school_scope(ctx, school_id)
    membership = await RbacService(session).create_member(
        ctx=ctx,
        school_id=school_id,
        email=str(payload.email),
        full_name=payload.full_name,
        password=payload.password,
        role_id=payload.role_id,
    )
    await session.refresh(membership, ["user", "role"])
    return _member_read(membership)


@members_router.post(
    "/{school_id}/members/{membership_id}/branches", response_model=list[MemberRead]
)
async def assign_member_branches(
    school_id: UUID,
    membership_id: UUID,
    payload: MemberBranchAssign,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("member:update"))],
) -> list[MemberRead]:
    """Give one member memberships in multiple school branches."""
    _assert_school_scope(ctx, school_id)
    memberships = await RbacService(session).assign_member_branches(
        ctx=ctx,
        membership_id=membership_id,
        school_ids=set(payload.school_ids),
    )
    for membership in memberships:
        await session.refresh(membership, ["user", "role"])
    return [_member_read(membership) for membership in memberships]


@members_router.patch("/{school_id}/members/{membership_id}", response_model=MemberRead)
async def update_member(
    school_id: UUID,
    membership_id: UUID,
    payload: MemberUpdate,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("member:update"))],
) -> MemberRead:
    """Change a member's role, suspend, or reactivate (spec §8).

    Two operations behind one PATCH because the members table exposes both as inline
    edits on the same row. Each is permission-checked separately: suspending needs
    `member:suspend` on top of `member:update`, since removing someone's access is a
    materially different act from correcting their job title.
    """
    _assert_school_scope(ctx, school_id)
    service = RbacService(session)

    if payload.role_id is None and payload.suspended is None:
        raise ValidationError("Provide role_id, suspended, or both.", code="EMPTY_UPDATE")

    membership = None
    if payload.role_id is not None:
        membership = await service.change_member_role(
            ctx=ctx, membership_id=membership_id, new_role_id=payload.role_id
        )
    if payload.suspended is not None:
        if not ctx.has("member:suspend"):
            raise AuthorizationError(
                "You do not have permission to change a member's status.",
                code="FORBIDDEN",
                details={"required": ["member:suspend"]},
            )
        membership = await service.set_member_status(
            ctx=ctx, membership_id=membership_id, suspended=payload.suspended
        )

    assert membership is not None  # guaranteed by the empty-update check above
    await session.refresh(membership, ["user", "role"])
    return _member_read(membership)


@members_router.delete(
    "/{school_id}/members/{membership_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def remove_member(
    school_id: UUID,
    membership_id: UUID,
    session: DbSession,
    ctx: Annotated[AuthContext, Depends(require("member:remove"))],
) -> None:
    """Remove a member. Refuses on the organization's last owner, and on yourself."""
    _assert_school_scope(ctx, school_id)
    await RbacService(session).remove_member(ctx=ctx, membership_id=membership_id)
