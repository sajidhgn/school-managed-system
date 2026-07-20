"""Tenancy API contracts (Pydantic).

WHY THIS FILE EXISTS
    `models.py` defines the database shape of a `School`; this file defines what the
    API accepts and returns. They are separate on purpose (see PROJECT_STRUCTURE.md
    section 7): the client must never be able to set `status`, `approved_at` or the
    tenant id directly -- those are decided by the service from the verified caller
    and the workflow, not the request body.

RESPONSIBILITY
    Request/response schemas for school onboarding and management. No business rules.

INTERACTIONS
    * `service.py` returns `SchoolRead` built from ORM rows.
    * `router.py` declares these as request bodies / response models.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import EmailStr, Field

from app.common.schemas import BaseSchema
from app.modules.tenancy.models import SchoolStatus, SubscriptionPlan


class SchoolContact(BaseSchema):
    """The mutable, client-supplied contact fields common to create + update."""

    email: EmailStr = Field(description="Official school contact address (not a login).")
    phone: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    logo_url: str | None = Field(
        default=None, max_length=500, description="Used on ID cards, certificates and vouchers."
    )


class SchoolCreate(SchoolContact):
    """Super-admin onboarding of a school (goes live immediately).

    Distinct from self-service registration (`auth.RegisterRequest`), which creates a
    PENDING_APPROVAL school plus its first admin in one step and requires no existing
    privileged caller.
    """

    name: str = Field(min_length=2, max_length=200)
    plan: SubscriptionPlan = SubscriptionPlan.TRIAL
    max_students: int = Field(default=100, ge=1, le=100_000)


class SchoolUpdate(BaseSchema):
    """Partial update. Every field optional so PATCH semantics are preserved.

    `status` is intentionally absent: lifecycle transitions go through the explicit
    `approve` / `suspend` endpoints so each one is a distinct, auditable action
    rather than a silent field write.
    """

    name: str | None = Field(default=None, min_length=2, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    address: str | None = Field(default=None, max_length=500)
    city: str | None = Field(default=None, max_length=100)
    country: str | None = Field(default=None, max_length=100)
    logo_url: str | None = Field(default=None, max_length=500)
    plan: SubscriptionPlan | None = None
    max_students: int | None = Field(default=None, ge=1, le=100_000)


class SchoolRead(BaseSchema):
    """The full school representation returned to super admins and the school itself."""

    id: UUID
    name: str
    slug: str
    email: str
    phone: str | None
    address: str | None
    city: str | None
    country: str | None
    logo_url: str | None
    status: SchoolStatus
    approved_at: datetime | None
    plan: SubscriptionPlan
    trial_ends_at: datetime | None
    subscription_expires_at: datetime | None
    max_students: int
    created_at: datetime
    updated_at: datetime
