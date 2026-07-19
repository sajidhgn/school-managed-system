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
    """Adds the `school_id` tenant discriminator -- the heart of multi-tenancy.

    EVERY tenant-owned table must include this. It carries three guarantees:

      1. `ForeignKey(..., ondelete="CASCADE")` -- offboarding a school removes its
         data in one statement, which matters for GDPR-style deletion requests.
      2. `nullable=False` -- an orphan row with no tenant is invisible to RLS
         policies and becomes a permanent data leak. The database refuses it.
      3. An index on `school_id` -- every RLS policy adds an implicit
         `WHERE school_id = ...` to every query, so this index is on the hot path
         of literally every read in the system.

    Note that the mixin alone does not enforce isolation; the RLS *policy* created
    in the migration does. The mixin guarantees the column the policy needs exists.
    """

    @declared_attr
    def school_id(cls) -> Mapped[UUID]:  # noqa: N805
        # `index=True` rather than an explicit `__table_args__` entry: defining
        # __table_args__ in a mixin would collide with any model that declares its
        # own UniqueConstraint/CheckConstraint, forcing every such model to
        # remember to merge the tuple. The index flag composes cleanly and the
        # naming convention in db/base.py still yields `ix_<table>_school_id`.
        return mapped_column(
            PgUUID(as_uuid=True),
            ForeignKey("schools.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
