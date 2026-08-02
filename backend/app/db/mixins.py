"""Reusable model mixins.

WHY THIS FILE EXISTS
    Roughly forty tables in this system need the same four things: a UUID primary
    key, created/updated timestamps, a tenant column, and soft deletion. Repeating
    those declarations forty times guarantees drift. Mixins give one definition and
    forty consistent usages -- the DRY principle applied at the schema level.

RESPONSIBILITY
    Provide composable column sets. Mixins contain no queries and no behaviour
    beyond column definition.

INTERACTIONS
    Composed by models: `class Student(Base, UUIDPrimaryKeyMixin, TenantMixin,
    TimestampMixin, SoftDeleteMixin)`.

WHY UUID PRIMARY KEYS RATHER THAN AUTO-INCREMENT INTEGERS
    1. Sequential integer ids are enumerable. `GET /students/1..N` from a rival
       school is a real attack in multi-tenant SaaS; RLS blocks the read, but UUIDs
       remove the temptation and the information leak in URLs.
    2. Ids can be generated client-side or by a worker before insert, which makes
       idempotent retries and offline-first mobile clients straightforward.
    3. Merging data across tenants (or across environments) never collides.
    Cost: 16 bytes vs 4, and worse index locality than a monotonic key. UUIDv7
    (time-ordered) is worth revisiting if insert throughput ever becomes a problem.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, declared_attr, mapped_column


class UUIDPrimaryKeyMixin:
    """Adds a UUID `id` primary key generated in Python."""

    id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
        # Also default server-side so rows inserted by raw SQL / seed scripts
        # still get a valid id.
        server_default=func.gen_random_uuid(),
    )


class TimestampMixin:
    """Adds `created_at` / `updated_at`, both maintained by the database.

    `server_default`/`onupdate` use the database clock rather than the application
    clock. With multiple app instances, machine clocks drift; the database is the
    single source of temporal truth. Always timezone-aware -- naive timestamps in a
    system that will run across timezones are a bug waiting to happen.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class CreatedAtMixin:
    """Adds `created_at` only, for append-only tables.

    Audit logs, subscription events and payment records are never updated after
    insert, so an `updated_at` on them would be a column that is always equal to
    `created_at` -- and, worse, a column whose existence implies mutation is
    expected. Omitting it makes the append-only contract visible in the schema.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


class SoftDeleteMixin:
    """Adds `deleted_at` for reversible deletion.

    WHY SOFT DELETE HERE: a school admin who deletes a student must not destroy that
    student's fee history, attendance record, or issued certificates -- those are
    financial and legal records. Soft deletion preserves referential integrity and
    supports "restore" without backups.

    COST: every query must filter `deleted_at IS NULL`. `BaseRepository` applies
    that filter automatically so individual call sites cannot forget.
    """

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None


class TenantMixin:
    """Adds the `organization_id` tenant discriminator -- the heart of multi-tenancy.

    EVERY tenant-owned table must include this. It carries three guarantees:

      1. `ForeignKey(..., ondelete="CASCADE")` -- offboarding an organization removes
         its data in one statement, which matters for GDPR-style deletion requests.
      2. `nullable=False` -- an orphan row with no tenant is invisible to RLS
         policies and becomes a permanent data leak. The database refuses it.
      3. An index on `organization_id` -- every RLS policy adds an implicit
         `WHERE organization_id = ...` to every query, so this index is on the hot
         path of literally every read in the system. Spec §3.4 calls this out
         specifically: policies are evaluated per row, and without the index,
         queries degrade badly past a few hundred tenants.

    Note that the mixin alone does not enforce isolation; the RLS *policy* created
    in the migration does. The mixin guarantees the column the policy needs exists.

    WHY THE ORGANIZATION AND NOT THE SCHOOL (spec decision D1/D3)
        The organization is the billing entity and the isolation boundary; schools
        live inside it. An owner with three schools legitimately reads across all
        three, so keying RLS on the school would lock the owner out of their own
        data. School scoping is a separate, deliberately weaker mechanism --
        see `SchoolScopedMixin`.
    """

    @declared_attr
    def organization_id(cls) -> Mapped[UUID]:  # noqa: N805
        # `index=True` rather than an explicit `__table_args__` entry: defining
        # __table_args__ in a mixin would collide with any model that declares its
        # own UniqueConstraint/CheckConstraint, forcing every such model to
        # remember to merge the tuple. The index flag composes cleanly and the
        # naming convention in db/base.py still yields `ix_<table>_organization_id`.
        return mapped_column(
            PgUUID(as_uuid=True),
            ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )


class SchoolScopedMixin:
    """Adds a nullable `school_id` -- the SOFT scope filter inside the tenant.

    NULLABLE, AND THAT IS THE POINT (spec §2.3)
        `school_id IS NULL` means "org-level": the owner's membership, an org-level
        role, an invitation to the organization rather than to one campus. A
        NOT NULL column here would make the owner unrepresentable, which is exactly
        the conflation between "owner" and "principal" that spec decision D2 exists
        to prevent.

    NOT AN RLS KEY
        No policy compares against this column. It is enforced by the permission
        dependency, which injects `WHERE school_id = :active_school_id` for
        school-scoped memberships and omits it for org-level ones. That is a weaker
        guarantee than RLS on purpose: crossing schools inside your own org is a
        permissions question, while crossing organizations is a containment
        question, and only the latter warrants the database refusing to cooperate.

    ON DELETE CASCADE, not SET NULL: a row scoped to a deleted school must not
    silently widen to org-level visibility. Deleting a school deletes its rows.
    """

    @declared_attr
    def school_id(cls) -> Mapped[UUID | None]:  # noqa: N805
        return mapped_column(
            PgUUID(as_uuid=True),
            ForeignKey("schools.id", ondelete="CASCADE"),
            nullable=True,
            index=True,
        )


class RequiredSchoolMixin:
    """Adds a NOT NULL `school_id`, for rows that cannot exist without a campus.

    Students, classes and sections belong to exactly one school -- there is no
    meaningful org-level student. Those tables still carry `organization_id` from
    `TenantMixin` for RLS; this mixin adds the scope column on top.
    """

    @declared_attr
    def school_id(cls) -> Mapped[UUID]:  # noqa: N805
        return mapped_column(
            PgUUID(as_uuid=True),
            ForeignKey("schools.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
