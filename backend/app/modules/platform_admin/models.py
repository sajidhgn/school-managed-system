"""Platform-level models: PlatformAdmin, Plan, PlatformAuditLog (spec §3.1).

WHY THIS FILE EXISTS
    Three tables sit deliberately OUTSIDE tenant Row-Level Security. They are not an
    oversight or a shortcut -- each one is structurally incapable of belonging to an
    organization, and enabling RLS on them would make them invisible to every
    request:

      * `platform_admins` -- the operators of the platform. They belong to no
        organization by definition; an RLS policy comparing `organization_id`
        would have no column to compare.

      * `plans` -- the global product catalog. It is served to the *unauthenticated*
        marketing site (`GET /public/plans`), where there is no tenant at all. It is
        also referenced by every organization simultaneously, so it cannot be owned
        by one.

      * `platform_audit_logs` -- the record of what platform operators did, including
        actions taken *against* organizations. Storing it inside the tenant it
        describes would let a suspended organization's own policy hide the evidence
        of its suspension.

RESPONSIBILITY
    Define the platform's own identity, product catalog and audit trail.

INTERACTIONS
    * `subscriptions.plan_id` -> `plans.id` (tenant table referencing a platform one).
    * `modules/platform_admin/service.py` orchestrates plan CRUD and org suspension.

=============================================================================
THERE IS NO SIGNUP ROUTE FOR `platform_admins`. THAT IS DELIBERATE.
=============================================================================
    Spec §1: "Created by database seed only. No signup route exists." A self-service
    path to platform-admin would be the single highest-value target on the system --
    one validation slip and an attacker holds every school's records. Accounts are
    minted by `python -m app.cli seed`, and credentials rotate through the CLI, not
    through an emailed reset link. An emailed reset for this role means the platform's
    security reduces to the security of one inbox.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import CITEXT, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.db.mixins import CreatedAtMixin, TimestampMixin, UUIDPrimaryKeyMixin


class PlanCode(StrEnum):
    """The seeded plan codes (spec §6.1).

    An enum for the four the system ships with, but `plans.code` is a plain text
    column, not a constrained one: the super admin can create bespoke plans for
    negotiated enterprise contracts, and a CHECK constraint here would mean a
    migration every time sales closes a non-standard deal.
    """

    FREE = "free"
    STARTER = "starter"
    GROWTH = "growth"
    ENTERPRISE = "enterprise"


# The limit keys every plan MUST define. Spec §6.1: "Every limit key must exist on
# every plan -- no missing-key fallbacks."
#
# WHY THIS IS ENFORCED RATHER THAN DEFAULTED: a missing key with a `.get(key, 0)`
# fallback silently blocks a paying customer; with `.get(key, -1)` it silently gives
# away unlimited usage. Both are worse than refusing to seed a malformed plan.
REQUIRED_LIMIT_KEYS = frozenset(
    {
        "max_schools",
        "max_students",
        "max_staff",
        "max_custom_roles",
        "storage_mb",
        "audit_retention_days",
    }
)

REQUIRED_FEATURE_KEYS = frozenset(
    {
        "custom_branding",
        "api_access",
        "priority_support",
        "sso",
        "advanced_reports",
    }
)

# Sentinel stored in `limits` to mean "no ceiling" (spec §6.1).
UNLIMITED = -1


class PlatformAdmin(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A platform operator. Seeded only -- there is no registration endpoint."""

    __tablename__ = "platform_admins"

    email: Mapped[str] = mapped_column(CITEXT, nullable=False, unique=True)
    """CITEXT, so `Admin@example.com` and `admin@example.com` are the same account.

    Case-insensitivity is enforced by the COLUMN TYPE rather than by lowercasing in
    the service. A service-layer normalisation only holds for the code paths that
    remember to call it; the column type holds for raw SQL, seeds and future
    endpoints too. Postgres also uses the type for the UNIQUE index, so two admins
    differing only in case cannot be created at all.
    """

    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(200), nullable=False)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    mfa_secret: Mapped[str | None] = mapped_column(String(64))
    """TOTP shared secret. Spec §4.3A requires MFA for this role in production.

    Nullable because the seed CLI creates the account before anyone has enrolled a
    device; `require_mfa_in_production` in the service refuses the login rather than
    letting an unenrolled admin through.
    """

    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    failed_login_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    """A SERVER default, not only a Python one.

    A NOT NULL counter whose default lives solely in the ORM is a trap: any row
    created by raw SQL -- a seed script, a data import, a support fix -- fails with a
    not-null violation, and the error names the column rather than the missing
    default. Same reasoning as the timestamps in `TimestampMixin`."""
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Plan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """A subscription tier. Managed by the super admin, served to the pricing page.

    NEVER HARDCODE THESE IN THE FRONTEND (spec §6.1). A price duplicated into the
    marketing site is a price that will one day disagree with the one actually
    charged -- and the customer will have a screenshot of the cheaper one.
    """

    __tablename__ = "plans"

    code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    marketing_tagline: Mapped[str | None] = mapped_column(String(200))

    # --- Pricing -----------------------------------------------------------
    price_monthly: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    price_yearly: Mapped[Decimal | None] = mapped_column(Numeric(10, 2))
    """NUMERIC, never FLOAT. Binary floating point cannot represent 29.99 exactly, and
    the error compounds across proration and tax. Money is decimal or it is wrong.

    Nullable because the hidden `enterprise` plan is priced by negotiation (spec
    §6.1: "price null"), so there is genuinely no number to store.
    """

    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    trial_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- Entitlements ------------------------------------------------------
    limits: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """Numeric ceilings; see REQUIRED_LIMIT_KEYS. `-1` means unlimited.

    JSONB rather than one column per limit, because limits are read as a whole by
    `EntitlementService` and adding a new limit must not require a migration plus a
    backfill across every plan. The trade -- no per-key constraints -- is paid for by
    validating the key set on write.
    """

    features: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    """Boolean feature flags shown on the pricing page; see REQUIRED_FEATURE_KEYS."""

    # --- Visibility --------------------------------------------------------
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """False hides the plan from `GET /public/plans`. The `enterprise` plan is
    hidden and assigned manually by the super admin (spec §6.1)."""

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """False retires a plan for NEW subscriptions without touching organizations
    already on it. Deleting a plan row would orphan their subscriptions and destroy
    the historical record of what they agreed to pay."""

    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        # The pricing page's exact query: public + active, in display order.
        Index("ix_plans_is_public_is_active_sort_order", "is_public", "is_active", "sort_order"),
        CheckConstraint(
            "(price_monthly IS NULL OR price_monthly >= 0)"
            " AND (price_yearly IS NULL OR price_yearly >= 0)",
            name="prices_non_negative",
        ),
        CheckConstraint("trial_days >= 0", name="trial_days_non_negative"),
    )

    def limit(self, key: str) -> int:
        """Read one numeric limit, refusing to guess when it is absent.

        A KeyError here is a seeding bug that must surface loudly in CI, not a
        silently-permissive default that lets a free-plan organization create
        unlimited schools in production.
        """
        if key not in self.limits:
            raise KeyError(f"Plan '{self.code}' is missing required limit '{key}'.")
        return int(self.limits[key])

    def is_unlimited(self, key: str) -> bool:
        return self.limit(key) == UNLIMITED


class PlatformAuditLog(Base, UUIDPrimaryKeyMixin, CreatedAtMixin):
    """What a platform operator did, and to whom.

    Separate from the tenant `audit_logs` table for containment: this records actions
    ACROSS organizations (suspending one, impersonating another), so it has no single
    owning tenant. Keeping it outside RLS also means a compromised or suspended
    organization cannot influence the visibility of the record describing it.

    No `updated_at`, no soft delete: an audit row that can be edited or removed is
    not an audit row. Append-only is the entire value proposition.
    """

    __tablename__ = "platform_audit_logs"

    actor_admin_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("platform_admins.id", ondelete="SET NULL"),
        index=True,
    )
    """SET NULL, not CASCADE. Removing an operator must not erase the trail of what
    they did -- that would make deleting the account an effective way to cover
    tracks. The action survives; only the pointer to the person is severed."""

    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(String(80))
    entity_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))

    target_organization_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="SET NULL"),
        index=True,
    )

    audit_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    """Mapped under a different Python name because `metadata` is reserved on every
    SQLAlchemy declarative class -- it is the `MetaData` object. The COLUMN is still
    named `metadata`, matching the spec; only the attribute differs."""

    ip: Mapped[str | None] = mapped_column(String(45))  # 45 = max IPv6 length
    user_agent: Mapped[str | None] = mapped_column(String(400))

    __table_args__ = (
        # "What happened on the platform recently, newest first" -- the console's
        # default view, and the query an incident investigation starts from.
        #
        # `text()` rather than the mapped attribute: __table_args__ is evaluated
        # during class construction, and `created_at` arrives from CreatedAtMixin,
        # so it is not a resolvable name in this class body.
        Index("ix_platform_audit_logs_created_at_desc", text("created_at DESC")),
    )
