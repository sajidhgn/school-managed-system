"""Platform console request/response contracts."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import EmailStr, Field

from app.common.schemas import BaseSchema


class PlatformLoginRequest(BaseSchema):
    email: EmailStr
    password: str = Field(min_length=1, max_length=200)


class PlatformAdminRead(BaseSchema):
    id: UUID
    email: str
    full_name: str
    is_active: bool
    mfa_enabled: bool
    last_login_at: datetime | None


class OrganizationSummary(BaseSchema):
    """One organization as the platform console lists it.

    Carries plan and usage inline so the list renders without a request per row --
    the operator's first question about any organization is always "what are they on
    and how much are they using".
    """

    id: UUID
    name: str
    slug: str
    status: str
    country: str | None
    billing_email: str | None
    plan_code: str | None
    plan_name: str | None
    subscription_status: str | None
    schools_count: int
    staff_count: int
    students_count: int
    created_at: datetime


class OrganizationDetail(OrganizationSummary):
    owner_user_id: UUID
    currency: str
    timezone: str
    trial_ends_at: datetime | None
    current_period_end: datetime | None
    limits: dict[str, Any] | None


class OrganizationStatusUpdate(BaseSchema):
    """Suspend or reactivate.

    `reason` is optional but strongly encouraged -- it lands in the platform audit
    log, and "why was this customer suspended in March" is a question that gets
    asked months later, by someone who was not there.
    """

    suspend: bool
    reason: str | None = Field(default=None, max_length=500)


class PlanOverrideRequest(BaseSchema):
    plan_code: str = Field(min_length=1, max_length=50)


class ImpersonateRequest(BaseSchema):
    reason: str | None = Field(default=None, max_length=500)


class ImpersonationGrant(BaseSchema):
    organization_id: UUID
    organization_name: str
    expires_at: datetime
    read_only: bool


class PlanWrite(BaseSchema):
    """Create or replace a plan.

    `limits` and `features` are free-form dicts here and validated in the service
    against the required key sets. A Pydantic model per key would be stricter, but it
    would also mean a code change and a deploy every time the product adds a limit --
    which is precisely the flexibility the JSONB column was chosen for.
    """

    code: str = Field(min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9_]*$")
    name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    marketing_tagline: str | None = Field(default=None, max_length=200)
    price_monthly: Decimal | None = Field(default=None, ge=0)
    price_yearly: Decimal | None = Field(default=None, ge=0)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    trial_days: int = Field(default=0, ge=0, le=365)
    limits: dict[str, Any]
    features: dict[str, Any]
    is_public: bool = True
    is_active: bool = True
    sort_order: int = 0


class PlanPatch(BaseSchema):
    """Partial plan update. `limits` and `features` merge; everything else replaces."""

    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    marketing_tagline: str | None = Field(default=None, max_length=200)
    price_monthly: Decimal | None = Field(default=None, ge=0)
    price_yearly: Decimal | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    trial_days: int | None = Field(default=None, ge=0, le=365)
    limits: dict[str, Any] | None = None
    features: dict[str, Any] | None = None
    is_public: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class PlanAdminRead(BaseSchema):
    """A plan as the operator sees it -- including the fields the public view hides."""

    id: UUID
    code: str
    name: str
    description: str | None
    marketing_tagline: str | None
    price_monthly: Decimal | None
    price_yearly: Decimal | None
    currency: str
    trial_days: int
    limits: dict[str, Any]
    features: dict[str, Any]
    is_public: bool
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


class MetricsResponse(BaseSchema):
    organizations_total: int
    organizations_by_status: dict[str, int]
    schools_total: int
    staff_seats_total: int
    mrr: Decimal
    failed_payments_30d: int
    churn_rate: float


class PlatformAuditRead(BaseSchema):
    id: UUID
    actor_admin_id: UUID | None
    action: str
    entity_type: str | None
    entity_id: UUID | None
    target_organization_id: UUID | None
    metadata: dict[str, Any] = Field(alias="audit_metadata")
    ip: str | None
    created_at: datetime
