"""RBAC request/response contracts."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import EmailStr, Field

from app.common.schemas import BaseSchema


class PermissionRead(BaseSchema):
    code: str
    resource: str
    action: str
    category: str
    description: str
    min_scope: str
    is_dangerous: bool


class PermissionCategory(BaseSchema):
    """Permissions grouped for the role-matrix editor (spec §8 `GET /permissions`).

    Grouped server-side rather than by the client so every surface -- the web role
    editor, a future mobile app, the API docs -- presents the same categories in the
    same order.
    """

    category: str
    permissions: list[PermissionRead]


class RoleRead(BaseSchema):
    id: UUID
    organization_id: UUID
    school_id: UUID | None
    code: str
    name: str
    description: str | None
    is_system: bool
    is_editable: bool
    permissions_version: int
    created_at: datetime


class RoleDetail(RoleRead):
    """A role plus its permission codes and how many people hold it.

    `member_count` is included because deleting a role fails with 409 while anyone
    holds it. Showing the number up front turns that into a visible precondition
    rather than a surprise after clicking delete.
    """

    permissions: list[str]
    member_count: int


class RoleCreate(BaseSchema):
    code: str = Field(min_length=2, max_length=50, pattern=r"^[a-z][a-z0-9_]*$")
    """Lowercase snake_case. Constrained because the code appears in the `rol` token
    claim and in permission-check code; allowing spaces or mixed case would make
    those comparisons quietly fragile."""

    name: str = Field(min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    permissions: list[str] = Field(default_factory=list)


class RoleUpdate(BaseSchema):
    """Rename only. Permissions change through the dedicated endpoint.

    Separate on purpose: a rename is cosmetic, a permission change alters authority.
    Merging them would blur the audit trail and churn `permissions_version` -- which
    invalidates every token for the role -- each time someone fixes a typo.
    """

    name: str | None = Field(default=None, min_length=2, max_length=100)
    description: str | None = Field(default=None, max_length=500)


class RolePermissionsUpdate(BaseSchema):
    """The complete new permission set. REPLACES, never merges.

    A replace makes the request self-describing: what you send is what the role ends
    up with. A merge-style API needs separate add and remove lists, and a client that
    forgets the remove list silently leaves revoked permissions in place -- failing
    open, which is the wrong direction for an authorization API.
    """

    codes: list[str] = Field(default_factory=list)


class MemberClassAssignment(BaseSchema):
    """One class a staff member is assigned to, for the staff table.

    `section_name` is set for a class-teacher assignment (a section's register);
    `subject_name` for a subject taught across the whole grade.
    """

    class_name: str
    section_id: UUID | None = None
    section_name: str | None = None
    class_subject_id: UUID | None = None
    subject_name: str | None = None


class MemberRead(BaseSchema):
    membership_id: UUID
    user_id: UUID
    email: str
    full_name: str
    school_id: UUID | None
    role_id: UUID
    role_code: str
    role_name: str
    status: str
    is_primary: bool
    joined_at: datetime | None
    created_at: datetime
    assigned_classes: list[MemberClassAssignment] = Field(default_factory=list)
    """Filled by the list endpoint only; single-member responses leave it empty."""


class TeacherOption(BaseSchema):
    """One selectable teacher, for the class-teacher and curriculum pickers.

    Deliberately NOT `MemberRead`. A picker needs a value, a label and enough to tell
    two same-named people apart -- nothing else. Reusing `MemberRead` would ship
    `membership_id`, `status`, `is_primary` and `joined_at` to a dropdown that cannot
    act on any of them, and would tie the shape of a UI control to the shape of the
    staff table, so a change to one would silently churn the other.

    `user_id` is the value because that is what `sections.class_teacher_id` and
    `class_subjects.teacher_id` reference -- NOT `membership_id`. The distinction
    matters for someone who teaches at two branches: one human, one user row, two
    memberships.
    """

    user_id: UUID
    full_name: str
    email: str
    role_name: str
    """Shown beside the name so "Sana Malik (Senior Teacher)" is distinguishable from
    a second Sana Malik on a different role."""


class MemberCreate(BaseSchema):
    """Create a login-ready member without the invitation flow."""

    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=1, max_length=200)
    role_id: UUID


class MemberBranchAssign(BaseSchema):
    """Additional branches to attach to an existing member."""

    school_ids: list[UUID] = Field(min_length=1, max_length=100)


class MemberUpdate(BaseSchema):
    """Change a member's name, role, status, or any combination."""

    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    role_id: UUID | None = None
    suspended: bool | None = None
