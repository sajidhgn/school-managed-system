"""Tenancy models: Organization (the tenant) and School (a scope inside it).

WHY THIS FILE EXISTS
    `Organization` is the tenant root. Every other tenant-owned row in the system
    points at it via `organization_id`, and every RLS policy compares against its id.
    It is the single most structurally important table in the schema.

RESPONSIBILITY
    Define the client account (Organization) and the campuses it operates (School),
    plus their lifecycle states.

INTERACTIONS
    * `TenantMixin.organization_id` targets `organizations.id` with ON DELETE CASCADE.
    * `subscriptions.organization_id` is UNIQUE -- one subscription per org.
    * `memberships`, `roles`, `invitations` all scope to a school via nullable FK.

=============================================================================
THE TENANT IS THE ORGANIZATION, NOT THE SCHOOL -- spec decision D1
=============================================================================
    A client buys one plan and may operate several campuses under it. The billing
    boundary and the isolation boundary have to be the same thing, or you get
    absurdities: which of a group's three schools "owns" the invoice? So the
    subscription hangs off the organization, and the plan's `max_schools` limit caps
    how many schools that organization may create.

    The alternative -- one subscription per school -- is a legitimate design, and the
    spec says so explicitly. Moving to it means relocating `subscription.organization_id`
    to `subscription.school_id` and changing the entitlement checks. Everything else
    in this file survives unchanged. It is not being built that way because a school
    group buying one plan for five campuses is the common case in the target market.

=============================================================================
WHY `Organization` DOES NOT USE `TenantMixin`
=============================================================================
    Every other table is scoped BY an organization. This table IS the organization --
    giving it an `organization_id` column pointing at itself would be circular.

    Its RLS policy is therefore different in shape: a user may see the one row whose
    `id` matches their tenant, rather than rows whose `organization_id` matches.
    See `alembic/rls.py::setup_organizations_table`.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, str_enum
from app.db.mixins import SoftDeleteMixin, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class OrganizationStatus(StrEnum):
    """Lifecycle of a client account (spec §3.3, §6.3).

    NOTE what is absent: there is no `pending_approval`. Self-service signup lands
    directly in `trialing`. Gating every new account behind manual platform review
    would make the funnel the spec describes -- sign up, buy a plan, land in the
    admin panel -- impossible to complete without a human in the loop. Abuse is
    handled by suspension after the fact, which is reversible; a blocked signup is
    a lost customer who never comes back.
    """

    TRIALING = "trialing"
    ACTIVE = "active"
    PAST_DUE = "past_due"  # failed charge; 7-day grace with full access
    OVER_LIMIT = "over_limit"  # downgraded below current usage; reads OK, creates blocked
    SUSPENDED = "suspended"  # read-only; exports still available
    CANCELLED = "cancelled"


class SchoolStatus(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    ARCHIVED = "archived"


class Organization(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """A client account. The tenant, the billing entity, and the RLS key."""

    __tablename__ = "organizations"

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    """URL-safe identifier, e.g. `springfield-trust`.

    Globally unique because it will appear in tenant-specific URLs. Generated from
    the name at registration and immutable afterwards -- changing it breaks every
    bookmark and every link already sent by email.
    """

    owner_user_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    """The human who owns billing and can create schools.

    RESTRICT, not CASCADE or SET NULL. Deleting the owner's user row must fail loudly
    rather than either destroying the organization or leaving it ownerless. Handing
    over is an explicit, atomic operation (`POST /org/transfer-ownership`) that
    promotes the new owner *before* demoting the old one -- see the RBAC service.

    DENORMALISED ON PURPOSE. The authoritative grant is the org-level `owner`
    membership row; this column is a fast pointer so that "who do we bill, and who
    do we email about a failed charge" never requires a join through memberships and
    roles. The two are kept in step by the ownership-transfer transaction, which is
    the only code permitted to write this column.
    """

    # --- Locale & billing --------------------------------------------------
    country: Mapped[str | None] = mapped_column(String(2))  # ISO 3166-1 alpha-2
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en")

    status: Mapped[OrganizationStatus] = mapped_column(
        str_enum(OrganizationStatus, name="status"),
        nullable=False,
        default=OrganizationStatus.TRIALING,
    )
    """Stored as VARCHAR + CHECK, not a PostgreSQL ENUM type, deliberately.

    Adding a value to a PG enum requires ALTER TYPE, which cannot be reversed in a
    downgrade. VARCHAR + CHECK (see `str_enum` in db/base.py) gives the same
    integrity with trivially reversible migrations, and still returns real StrEnum
    members in Python so lifecycle checks are type-safe.
    """

    billing_email: Mapped[str | None] = mapped_column(CITEXT)
    """Separate from the owner's login address: invoices usually go to accounts
    payable, not to the principal who signed up."""

    tax_id: Mapped[str | None] = mapped_column(String(64))

    # --- Branding ----------------------------------------------------------
    # The organization-wide default. A school whose own branding columns are NULL
    # inherits these, so a single-campus client (or a trust that wants one identity
    # everywhere) configures branding exactly once. A campus that sets its own
    # overrides them -- see `School.logo_url` / `School.theme_color`.
    logo_url: Mapped[str | None] = mapped_column(Text)
    """An `https://` URL or a `data:image/...` URI. Text, not varchar: uploaded
    logos are stored inline as client-downscaled data URIs (tens of KB), because
    the deployment has no file-storage tier and the browser is never told the
    API origin, so there is nowhere else an `<img src>` could point. Bounded at
    the schema layer, where the two accepted shapes are also enforced."""
    theme_colors: Mapped[list[str] | None] = mapped_column(ARRAY(String(7)))
    """Ordered `#RRGGBB` palette. Position is meaning -- first is primary, second
    secondary -- and consumers (ID card designs, report headers) read by index.
    Count and format are validated at the schema layer."""

    requested_plan_code: Mapped[str] = mapped_column(
        String(50), nullable=False, default="free", server_default="free"
    )
    requested_billing_cycle: Mapped[str] = mapped_column(
        String(10), nullable=False, default="monthly", server_default="monthly"
    )

    __table_args__ = (Index("ix_organizations_status_created_at", "status", "created_at"),)

    @property
    def is_active(self) -> bool:
        """Whether this tenant may currently perform writes.

        `past_due` and `over_limit` are deliberately included. Spec §6.3 is explicit:
        never lock a school out of its own student records over a payment issue.
        `past_due` keeps full access during the grace window; `over_limit` blocks
        only new resource creation, which `EntitlementService` handles separately.
        """
        return (
            self.status
            in (
                OrganizationStatus.TRIALING,
                OrganizationStatus.ACTIVE,
                OrganizationStatus.PAST_DUE,
                OrganizationStatus.OVER_LIMIT,
            )
            and self.deleted_at is None
        )

    @property
    def is_read_only(self) -> bool:
        """Suspended organizations keep read + export access, lose writes (spec §6.3)."""
        return self.status is OrganizationStatus.SUSPENDED


class School(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    """One campus inside an organization.

    An ordinary tenant-owned table: it carries `organization_id` from `TenantMixin`
    and gets the standard RLS policy. It is NOT itself a tenant -- see the module
    docstring and spec decision D1.
    """

    __tablename__ = "schools"

    name: Mapped[str] = mapped_column(String(200), nullable=False)

    code: Mapped[str] = mapped_column(String(32), nullable=False)
    """Short human identifier used on ID cards and report headers, e.g. `SHS-MAIN`.

    Unique per organization, not globally: two unrelated clients may both sensibly
    call their main campus `MAIN`, and forcing global uniqueness would leak the
    existence of other tenants through collision errors.
    """

    slug: Mapped[str] = mapped_column(String(80), nullable=False)

    # --- Contact -----------------------------------------------------------
    # Deliberately NOT login credentials: authentication belongs to `users`. Two
    # schools may share a contact address (a trust running several campuses).
    email: Mapped[str | None] = mapped_column(CITEXT)
    phone: Mapped[str | None] = mapped_column(String(32))
    address: Mapped[str | None] = mapped_column(Text)
    city: Mapped[str | None] = mapped_column(String(100))
    logo_url: Mapped[str | None] = mapped_column(Text)
    """NULL means "use the organization's logo", not "no logo": branding resolves
    school-over-organization, field by field. Same rule for `theme_colors`.
    Text for the same reason as `Organization.logo_url`: uploads live inline as
    data URIs."""

    theme_colors: Mapped[list[str] | None] = mapped_column(ARRAY(String(7)))
    """Ordered `#RRGGBB` palette for this campus's ID cards and report headers,
    overriding `Organization.theme_colors` AS A WHOLE when set -- palettes are
    designed together, so they are never mixed element-wise across levels."""

    card_design: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """The campus's student ID card template, as chosen by the principal: layout
    design, logo/photo placement and shape, which fields print, which phone
    number the "if found" line shows, whether a QR is included. Shape is owned
    and validated by `CardDesignConfig` in schemas.py -- JSONB rather than a
    column per knob because the set of knobs is the part guaranteed to change,
    and each knob has a rendering default, so absence is always meaningful.
    NULL means "the default card", per campus, NOT inherited from the
    organization: card layout follows the printer sitting at a campus desk,
    unlike colours and logos, which follow the brand."""

    challan_design: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    """The campus's printed fee challan template, as chosen by the office: which
    detachable copies print, the bank and wallet accounts named across its head,
    which of the student's identifiers and the family's contact appear, whether
    the total is spelled out and whether a signature block is left blank at the
    foot. Shape is owned and validated by `ChallanDesignConfig` in schemas.py,
    on the same terms as `card_design` above -- JSONB, every knob with a
    rendering default, NULL meaning "the standard challan".

    PER CAMPUS, NOT PER ORGANIZATION, and the accounts are why: the number a
    parent transfers to is the one that campus reconciles against, and a group
    that inherited a sibling campus's account would discover it as money in the
    wrong ledger."""

    # --- Calendar & locale -------------------------------------------------
    academic_year_start_month: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    """1-12. Defaults to April, the common start in the target market. Drives which
    academic year a date falls into, so it must be per-school: a group can run an
    international campus on a September year alongside a local one on April."""

    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="en")

    status: Mapped[SchoolStatus] = mapped_column(
        str_enum(SchoolStatus, name="status"),
        nullable=False,
        default=SchoolStatus.ACTIVE,
    )

    __table_args__ = (
        # Partial unique: a soft-deleted school releases its code for reuse. Without
        # the WHERE clause, archiving `MAIN` would permanently burn that code for
        # the organization.
        Index(
            "uq_schools_organization_id_code",
            "organization_id",
            "code",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "uq_schools_organization_id_slug",
            "organization_id",
            "slug",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index("ix_schools_organization_id_status", "organization_id", "status"),
        CheckConstraint(
            "academic_year_start_month BETWEEN 1 AND 12",
            name="academic_year_start_month_valid",
        ),
    )

    @property
    def is_active(self) -> bool:
        return self.status is SchoolStatus.ACTIVE and self.deleted_at is None
