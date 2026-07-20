"""Tenancy models -- the School aggregate.

WHY THIS FILE EXISTS
    `School` is the tenant root. Every other tenant-owned row in the system points
    at it via `school_id`, and every RLS policy compares against its id. It is the
    single most structurally important table in the schema.

RESPONSIBILITY
    Define the School entity, its lifecycle status, and its SaaS subscription state.

INTERACTIONS
    * `TenantMixin.school_id` targets `schools.id` with ON DELETE CASCADE.
    * `auth.User.school_id` points here (nullable -- platform staff have no school).

=============================================================================
WHY `School` DOES NOT USE `TenantMixin`
=============================================================================
    Every other table is scoped BY a school. This table IS the school -- giving it
    a `school_id` column pointing at itself would be circular.

    Its RLS policy is therefore different in shape: a user may see the one row whose
    `id` matches their tenant, rather than rows whose `school_id` matches:

        USING (id = current_setting('app.current_school_id')::uuid
               OR current_setting('app.is_super_admin', true) = 'on')

    Written by hand in the bootstrap migration, not via `setup_tenant_table()`.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, str_enum
from app.db.mixins import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class SchoolStatus(StrEnum):
    """Lifecycle of a tenant.

    PENDING_APPROVAL is the landing state for self-service registration. The PDF
    assigns school onboarding to the Super Admin, so a self-registered school is
    NOT live until a platform administrator approves it. This is what stops anyone
    with an email address from provisioning a tenant on your infrastructure.
    """

    PENDING_APPROVAL = "pending_approval"
    ACTIVE = "active"
    SUSPENDED = "suspended"  # non-payment or ToS violation; data retained
    CANCELLED = "cancelled"  # offboarded; retained for the contractual window


class SubscriptionPlan(StrEnum):
    """SaaS tier. Drives the seat/student limits enforced by the tenancy service."""

    TRIAL = "trial"
    BASIC = "basic"
    STANDARD = "standard"
    PREMIUM = "premium"


class School(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A tenant. One row per customer school."""

    __tablename__ = "schools"

    # --- Identity ----------------------------------------------------------
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    """URL-safe identifier, e.g. `springfield-high`.

    Globally unique because it will appear in tenant-specific URLs
    (`springfield-high.app.com` or `/s/springfield-high`). Generated from the name
    at registration and immutable afterwards -- changing it would break every
    bookmark and any ID card QR code already printed.
    """

    # --- Contact -----------------------------------------------------------
    # The school's official contact address. Deliberately NOT a login credential:
    # authentication belongs to `users`. Two schools may share a contact address
    # (a trust running several campuses), so this is not unique.
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    country: Mapped[str | None] = mapped_column(String(100))

    # Used on ID cards, certificates and PDF fee vouchers -- all three PDF features
    # need the school's mark.
    logo_url: Mapped[str | None] = mapped_column(String(500))

    # --- Lifecycle ---------------------------------------------------------
    # No `index=True`: ix_schools_status_created_at below covers status-only
    # filtering via its leftmost prefix.
    status: Mapped[SchoolStatus] = mapped_column(
        str_enum(SchoolStatus, name="status"),
        nullable=False,
        default=SchoolStatus.PENDING_APPROVAL,
    )
    """Stored as VARCHAR + CHECK, not a PostgreSQL ENUM type, deliberately.

    Adding a value to a PG enum requires ALTER TYPE, which historically could not
    run inside a transaction and still cannot be reversed in a downgrade. A
    VARCHAR + CHECK constraint (see `str_enum` in db/base.py) gives the same
    integrity with migrations that are trivially reversible, and returns real
    `StrEnum` members in Python so lifecycle checks are type-safe.
    """

    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # --- Subscription ------------------------------------------------------
    plan: Mapped[SubscriptionPlan] = mapped_column(
        str_enum(SubscriptionPlan, name="plan"),
        nullable=False,
        default=SubscriptionPlan.TRIAL,
    )
    trial_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    subscription_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    max_students: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    """Plan seat limit, denormalised onto the tenant.

    Copied here rather than looked up from a plans table so that enforcing it on
    student creation is a field comparison, not a join -- and so that a negotiated
    custom limit for one school does not require inventing a bespoke plan row.
    """

    __table_args__ = (
        # Super Admin dashboard lists schools filtered by status and sorted by
        # signup date ("show me pending approvals, newest first"). A composite
        # index serves that exact access pattern.
        Index("ix_schools_status_created_at", "status", "created_at"),
    )

    @property
    def is_active(self) -> bool:
        """Whether the tenant may currently be used.

        Checked when issuing tokens: a suspended school's staff must not be able to
        log in, even with valid credentials.
        """
        return self.status is SchoolStatus.ACTIVE and self.deleted_at is None
