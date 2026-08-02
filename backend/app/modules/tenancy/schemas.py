"""Tenancy request/response contracts: organizations and schools."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import EmailStr, Field

from app.common.schemas import BaseSchema

# ---------------------------------------------------------------------------
# Organization
# ---------------------------------------------------------------------------


class OrganizationRead(BaseSchema):
    id: UUID
    name: str
    slug: str
    owner_user_id: UUID
    country: str | None
    timezone: str
    currency: str
    locale: str
    status: str
    billing_email: str | None
    tax_id: str | None
    created_at: datetime


class OrganizationUpdate(BaseSchema):
    """PATCH body. Every field optional -- omitted means "leave unchanged".

    `slug` is absent on purpose: it appears in URLs and in links already sent by
    email, so changing it silently breaks bookmarks. It is set once at signup.
    """

    name: str | None = Field(default=None, min_length=2, max_length=200)
    country: str | None = Field(default=None, min_length=2, max_length=2)
    timezone: str | None = Field(default=None, max_length=64)
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    locale: str | None = Field(default=None, max_length=10)
    billing_email: EmailStr | None = None
    tax_id: str | None = Field(default=None, max_length=64)


class TransferOwnershipRequest(BaseSchema):
    """Hand the organization to another member.

    Identified by membership, not by user id or email: the new owner must ALREADY be
    a member of this organization. Accepting an arbitrary email would let an owner
    transfer to someone outside the org, who would then hold billing rights over data
    they were never granted access to.
    """

    new_owner_membership_id: UUID


# ---------------------------------------------------------------------------
# Schools
# ---------------------------------------------------------------------------


class SchoolRead(BaseSchema):
    id: UUID
    organization_id: UUID
    name: str
    code: str
    slug: str
    email: str | None
    phone: str | None
    address: str | None
    city: str | None
    logo_url: str | None
    academic_year_start_month: int
    timezone: str
    locale: str
    status: str
    created_at: datetime


class SchoolCreate(BaseSchema):
    name: str = Field(min_length=2, max_length=200)
    code: str = Field(min_length=1, max_length=32)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    address: str | None = None
    city: str | None = Field(default=None, max_length=100)
    academic_year_start_month: int = Field(default=4, ge=1, le=12)
    timezone: str = Field(default="UTC", max_length=64)
    locale: str = Field(default="en", max_length=10)


class SchoolUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=32)
    address: str | None = None
    city: str | None = Field(default=None, max_length=100)
    logo_url: str | None = Field(default=None, max_length=500)
    academic_year_start_month: int | None = Field(default=None, ge=1, le=12)
    timezone: str | None = Field(default=None, max_length=64)
    locale: str | None = Field(default=None, max_length=10)


class SchoolCreateResponse(BaseSchema):
    """A created school, plus whether the caller was granted principal on it.

    `principal_granted` tells the frontend where to send the user next: into the new
    school's admin panel if they now hold principal there (their first school), or
    back to the school list if they do not (subsequent schools, which need a
    principal appointed).
    """

    school: SchoolRead
    principal_granted: bool
