"""RBAC models: Permission, Role, RolePermission, Membership, AuditLog.

WHY THIS FILE EXISTS
    Spec requirement #3 lets a principal define custom roles and assign permissions
    to them. That is a genuine authorization system, not a role enum -- and the part
    that gets built wrong is not the happy path but the escalation guards (spec §5.3).
    This file defines the tables those guards operate on.

RESPONSIBILITY
    Define the permission catalog, roles, the role-permission join, the membership
    that binds a user to a role within a scope, and the tenant audit trail.

INTERACTIONS
    * `api/deps.py::require()` resolves a membership's role into a permission set.
    * `core/cache.py` caches that set keyed by `(role_id, permissions_version)`.
    * `modules/invitations` creates memberships on accept.

=============================================================================
THE THREE-PART SHAPE: WHO x WHERE x WHAT
=============================================================================
    Membership  = WHO (user) x WHERE (organization + optional school) x role
    Role        = a named bundle, scoped to an org or to one school
    Permission  = an atomic `resource:action` string from a global catalog

    `school_id IS NULL` on either a role or a membership means ORG-LEVEL. That is how
    the PRINCIPAL is represented: one org-level row per human who runs the
    organization, spanning every school in it.

    There is deliberately no second, school-scoped copy of that person. A principal
    who also held a campus-level role would appear twice in the members list and
    twice in the context switcher while gaining nothing -- the org-level row already
    carries the entire catalog. One human, one role.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, str_enum
from app.db.mixins import (
    CreatedAtMixin,
    SchoolScopedMixin,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, types only
    from app.modules.auth.models import User
    from app.modules.tenancy.models import Organization, School


class PermissionScope(StrEnum):
    """The narrowest role scope a permission may be attached to (spec §5.1).

    ORG means the permission is meaningless -- or dangerous -- on a school-scoped
    role. `billing:manage` on a teacher role at one campus would let that teacher
    change the plan for the entire group; `school:create` would let a principal
    manufacture campuses their organization has not paid for. Attempting either
    returns 422, enforced in the service and covered by a test gate.
    """

    ORG = "org"
    SCHOOL = "school"


class SystemRole(StrEnum):
    """Role codes the platform creates and depends on.

    Custom roles created by a principal use arbitrary codes; these three are seeded
    and referenced by name in the signup and invitation flows, so they are an enum.

    `principal` is the organization's top role: ORG-LEVEL, holding the whole catalog
    including billing and `school:create`. It is what the registering user receives,
    and what `POST /org/transfer-ownership` moves between people. `teacher` and
    `accountant` are school-scoped starting points each customer tailors.
    """

    PRINCIPAL = "principal"
    TEACHER = "teacher"
    ACCOUNTANT = "accountant"


class MembershipStatus(StrEnum):
    ACTIVE = "active"
    SUSPENDED = "suspended"


class Permission(Base):
    """One atomic capability, e.g. `student:create`. A GLOBAL catalog row.

    NOT tenant data, and therefore no `organization_id` and no RLS. The catalog is
    the same for every customer -- it enumerates what this software can do, which is
    a property of the software, not of who bought it. Organizations differ in which
    permissions they GRANT (that is `role_permissions`), never in which exist.

    Primary key is the code itself rather than a surrogate UUID. The code is already
    unique, immutable and human-meaningful; a UUID would add a join to every
    permission check to recover a string that was right there.
    """

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(80), primary_key=True)
    """`resource:action`, e.g. `member:invite`."""

    resource: Mapped[str] = mapped_column(String(40), nullable=False)
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    """Grouping for the role-matrix editor UI, e.g. "People & access". Stored rather
    than derived from `resource` so the UI's grouping can be curated without a
    code change."""

    description: Mapped[str] = mapped_column(Text, nullable=False)

    min_scope: Mapped[PermissionScope] = mapped_column(
        str_enum(PermissionScope, name="min_scope"),
        nullable=False,
        default=PermissionScope.SCHOOL,
    )

    is_dangerous: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """Renders a confirmation step in the role editor. Purely advisory -- the server
    enforces nothing extra. Marked on permissions that destroy data or move money."""

    __table_args__ = (Index("ix_permissions_category_resource", "category", "resource"),)


class Role(Base, UUIDPrimaryKeyMixin, TenantMixin, SchoolScopedMixin, TimestampMixin):
    """A named bundle of permissions, owned by one organization.

    Roles are TENANT data even for the system ones. Each organization gets its own
    `principal` row rather than sharing a global one, because `role_permissions`
    hangs off the role id and a shared row would mean one customer's edit changed
    every customer's principal. The `is_editable` flag then protects the system roles
    from being edited at all -- but the isolation is structural, not just a flag.
    """

    __tablename__ = "roles"

    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """System roles cannot be deleted. Deleting `principal` would strip every
    principal in the organization of their access with no way to restore it."""

    is_editable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """False on `principal` (spec §5.3 rule 2).

    This is what stops a principal NARROWING or widening its own role. Without it,
    "a principal may assign permissions to roles" trivially becomes "a principal may
    rewrite the role that defines its own authority", and the escalation guard in
    rule 1 -- which only checks that the actor already HOLDS what it grants -- cannot
    catch it, since the actor is editing the very role that defines what it holds.
    """

    permissions_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    """Incremented on every permission change to this role. THE INVALIDATION KEY.

    Access tokens carry this number (`pv`). The permission set is cached under
    `perm:{role_id}:{pv}`, so bumping it makes every token minted before the edit
    resolve against a different cache key -- and the dependency, seeing the token's
    `pv` disagree with the row's, re-resolves from the database. Net effect: a
    revoked permission stops working on the affected user's very NEXT request rather
    than after their token expires. See `core/cache.py`.
    """

    __table_args__ = (
        UniqueConstraint("id", "organization_id", name="uq_roles_id_organization_id"),
        # Unique per (org, school, code). `school_id` is nullable and PostgreSQL
        # treats NULLs as distinct in a unique index, so `NULLS NOT DISTINCT` is
        # required -- without it an organization could hold unlimited org-level
        # roles all coded `owner`.
        Index(
            "uq_roles_organization_id_school_id_code",
            "organization_id",
            "school_id",
            "code",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_roles_organization_id_school_id", "organization_id", "school_id"),
    )

    @property
    def is_org_level(self) -> bool:
        return self.school_id is None


class RolePermission(Base, TenantMixin):
    """Join table: which permissions a role grants.

    Composite primary key, no surrogate id and no timestamps. A grant either exists
    or it does not; there is nothing else to say about it, and a surrogate key would
    permit duplicate rows expressing the same fact.

    `organization_id` is deliberately duplicated from the parent role so PostgreSQL
    can enforce RLS on this table directly. A composite foreign key guarantees the
    duplicate can never disagree with the role it belongs to.
    """

    __tablename__ = "role_permissions"

    role_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
    )
    permission_code: Mapped[str] = mapped_column(
        String(80),
        ForeignKey("permissions.code", ondelete="RESTRICT"),
        primary_key=True,
    )
    """RESTRICT: removing a permission from the catalog while roles still grant it
    must fail loudly. The alternative -- CASCADE -- would silently strip capabilities
    from live roles during a deploy, with no audit row and no way to tell what was
    lost."""

    __table_args__ = (
        ForeignKeyConstraint(
            ["role_id", "organization_id"],
            ["roles.id", "roles.organization_id"],
            name="fk_role_permissions_role_id_organization_id_roles",
            ondelete="CASCADE",
        ),
    )


class Membership(
    Base, UUIDPrimaryKeyMixin, TenantMixin, SchoolScopedMixin, SoftDeleteMixin, TimestampMixin
):
    """A user's role within one scope of one organization.

    `school_id IS NULL` = org-level (the principal). Otherwise the membership is
    confined to that school, and the permission dependency injects the corresponding filter.

    One human may hold several of these -- across schools and across organizations --
    which is the whole point of decision D4. The access token names exactly one at a
    time; `POST /auth/context` swaps which.
    """

    __tablename__ = "memberships"

    user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    role_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("roles.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    """RESTRICT enforces spec §5.3: deleting a role requires reassigning its members
    first, and the endpoint returns 409 with the blocking count. Letting the database
    CASCADE here would delete people's access as a side effect of tidying up a role."""

    status: Mapped[MembershipStatus] = mapped_column(
        str_enum(MembershipStatus, name="status"),
        nullable=False,
        default=MembershipStatus.ACTIVE,
    )

    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """Which membership to auto-select at login for a user holding several. Without
    it, a teacher at two schools would face a context picker on every single login."""

    invited_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Eager-loaded together by the auth dependency, which needs all three on every
    # authorised request: the role to resolve permissions, the organization to check
    # suspension. `lazy="raise"` on the rest of the codebase would be the ideal
    # guard against accidental N+1, but these two are always fetched via an explicit
    # `joinedload`, so the default is left alone.
    role: Mapped[Role] = relationship(foreign_keys=[role_id], lazy="select")
    organization: Mapped[Organization] = relationship(lazy="select")
    user: Mapped[User] = relationship(foreign_keys=[user_id], lazy="select")
    school: Mapped[School | None] = relationship(lazy="select")

    __table_args__ = (
        # One membership per (user, org, school) among LIVE rows. Partial, so a
        # removed member can be re-added later; NULLS NOT DISTINCT so a user cannot
        # accumulate several org-level memberships in the same organization.
        Index(
            "uq_memberships_user_organization_school",
            "user_id",
            "organization_id",
            "school_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # Login's first query: "what memberships does this person hold?" Partial, so
        # the index carries only live rows -- it is read on every login.
        Index(
            "ix_memberships_user_id_live",
            "user_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # The staff list for one school.
        Index("ix_memberships_organization_id_school_id", "organization_id", "school_id"),
    )

    @property
    def is_org_level(self) -> bool:
        return self.school_id is None

    @property
    def is_usable(self) -> bool:
        return self.status is MembershipStatus.ACTIVE and self.deleted_at is None


class AuditLog(Base, UUIDPrimaryKeyMixin, TenantMixin, SchoolScopedMixin, CreatedAtMixin):
    """Tenant-scoped record of who changed what.

    RLS-protected like any tenant table, so an organization reads its own trail and
    nobody else's. Platform-operator actions go to `platform_audit_logs` instead --
    see that model for why the two are separate.

    Append-only: no `updated_at`, no soft delete. Retention is enforced by a purge
    job reading the plan's `audit_retention_days`, which is the only thing permitted
    to remove rows.
    """

    __tablename__ = "audit_logs"

    actor_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    actor_membership_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="SET NULL"),
    )
    """Both recorded, because they answer different questions. The user says WHO;
    the membership says IN WHAT CAPACITY. For a person who is a teacher at one campus
    and an accountant at another, the second is what makes the entry interpretable."""

    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(80))
    entity_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    before: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    after: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """The changed fields only, never the whole row. Whole-row snapshots of student
    records would turn the audit table into a second, unprotected copy of the
    database -- with the same personal data and a much longer retention."""

    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(400))

    __table_args__ = (
        # Spec §3.4. The audit screen's default query, and the one the retention
        # purge uses.
        Index(
            "ix_audit_logs_organization_id_created_at", "organization_id", text("created_at DESC")
        ),
        Index("ix_audit_logs_school_id_created_at", "school_id", text("created_at DESC")),
        Index("ix_audit_logs_entity", "entity_type", "entity_id"),
    )
