"""Tenancy business rules -- the School lifecycle.

WHY THIS FILE EXISTS
    Everything that decides *what is allowed* for a school lives here: how a tenant is
    provisioned, how its slug is chosen, and the approve/suspend transitions the Super
    Admin drives. The router only translates HTTP; the repository only runs SQL.

INTERACTIONS
    * `auth.service.AuthService` calls `register_school` inside the same transaction
      as it creates the first admin user, so a half-provisioned tenant is impossible.
    * `router.py` calls the management methods behind the super-admin guard.

THE ONE SUBTLE THING -- binding the tenant so a brand-new school can be inserted
    The `schools` RLS policy has a WITH CHECK of `id = <current tenant>` (or super
    admin). Self-service registration has neither: no super-admin token, and the new
    school does not exist yet. The trick (`_provision`) is to GENERATE the id up
    front, bind it as the current tenant, then insert the row with that id -- so the
    WITH CHECK sees `id = id` and permits exactly this one row. It is the minimal,
    auditable way to open the door for a single self-registration and nothing else.
"""

from __future__ import annotations

import re
import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.schemas import Page, PageParams, SortParams
from app.core.context import is_super_admin
from app.core.exceptions import ConflictError, NotFoundError
from app.core.logging import get_logger
from app.db.session import bind_tenant
from app.modules.tenancy.models import School, SchoolStatus, SubscriptionPlan
from app.modules.tenancy.repository import SchoolRepository
from app.modules.tenancy.schemas import SchoolCreate, SchoolRead, SchoolUpdate

logger = get_logger(__name__)

# A trial tenant is usable for two weeks before a plan is required. Denormalised onto
# the row at creation so expiry is a field comparison, not a plan-table join.
TRIAL_PERIOD_DAYS = 14

_SLUG_STRIP = re.compile(r"[^a-z0-9]+")
_SLUG_TRIM = re.compile(r"^-+|-+$")


def slugify(name: str, *, max_length: int = 60) -> str:
    """Turn a school name into a URL-safe base slug (no uniqueness guarantee)."""
    lowered = name.strip().lower()
    hyphenated = _SLUG_STRIP.sub("-", lowered)
    trimmed = _SLUG_TRIM.sub("", hyphenated)[:max_length]
    trimmed = _SLUG_TRIM.sub("", trimmed)  # a trailing hyphen may reappear after the cut
    return trimmed or "school"


class TenancyService:
    """School provisioning and lifecycle management."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = SchoolRepository(session)

    # -- provisioning -------------------------------------------------------

    async def register_school(self, *, name: str, email: str, phone: str | None = None) -> School:
        """Self-service registration: create a PENDING_APPROVAL tenant.

        Called by the auth service as part of signup. The school is NOT live until a
        super admin approves it, which is what stops anyone with an email address from
        provisioning a usable tenant. A random slug suffix avoids collisions the
        RLS-blinded pre-check cannot see (the unique index is the real backstop).
        """
        base = slugify(name)
        slug = f"{base}-{secrets.token_hex(3)}"
        now = datetime.now(UTC)
        return await self._provision(
            name=name.strip(),
            slug=slug,
            email=_normalise_email(email),
            phone=phone,
            status=SchoolStatus.PENDING_APPROVAL,
            plan=SubscriptionPlan.TRIAL,
            trial_ends_at=now + timedelta(days=TRIAL_PERIOD_DAYS),
            approved_at=None,
        )

    async def create_school(self, payload: SchoolCreate) -> School:
        """Super-admin onboarding: create an already-ACTIVE tenant.

        Runs under a super-admin session (the `app.is_super_admin` GUC is on), so the
        schools RLS policy permits the insert without binding a tenant, and the slug
        uniqueness pre-check can see the whole table.
        """
        slug = await self._unique_slug(slugify(payload.name))
        now = datetime.now(UTC)
        return await self._provision(
            name=payload.name.strip(),
            slug=slug,
            email=_normalise_email(payload.email),
            phone=payload.phone,
            address=payload.address,
            city=payload.city,
            country=payload.country,
            logo_url=payload.logo_url,
            status=SchoolStatus.ACTIVE,
            plan=payload.plan,
            max_students=payload.max_students,
            trial_ends_at=now + timedelta(days=TRIAL_PERIOD_DAYS),
            approved_at=now,
        )

    async def _provision(self, *, status: SchoolStatus, **fields: object) -> School:
        """Insert a school row, binding the GUC to its new id first when needed.

        When NOT acting as a super admin (the self-registration path), the schools
        WITH CHECK policy would reject the insert unless the current tenant equals the
        row's id -- so we generate the id and bind it before writing.
        """
        school_id = uuid4()
        if not is_super_admin():
            await bind_tenant(self.session, school_id)
        school = await self.repo.create(id=school_id, status=status, **fields)
        logger.info("school_provisioned", school_id=str(school.id), status=status.value)
        return school

    async def _unique_slug(self, base: str) -> str:
        """Return `base`, or `base-2`, `base-3`, ... until one is free.

        Only meaningful under a session that can see the whole table (super admin);
        the self-registration path uses a random suffix instead.
        """
        if not await self.repo.slug_exists(base):
            return base
        for suffix in range(2, 1000):
            candidate = f"{base}-{suffix}"
            if not await self.repo.slug_exists(candidate):
                return candidate
        # Astronomically unlikely; fall back to a random suffix rather than loop forever.
        return f"{base}-{secrets.token_hex(3)}"

    # -- reads --------------------------------------------------------------

    async def get_school(self, school_id: UUID) -> School:
        """Fetch one school, or 404.

        Under RLS a school outside the caller's tenant is simply not returned, so a
        cross-tenant lookup naturally becomes a 404 -- never a 403 that would confirm
        the row exists.
        """
        school = await self.repo.get(school_id)
        if school is None:
            raise NotFoundError("School not found.")
        return school

    async def list_schools(
        self,
        *,
        status: SchoolStatus | None = None,
        params: PageParams,
        sort: SortParams | None = None,
    ) -> Page[SchoolRead]:
        rows, total = await self.repo.list_by_status(status, params=params, sort=sort)
        return Page.create([SchoolRead.model_validate(r) for r in rows], total, params)

    # -- lifecycle transitions ---------------------------------------------

    async def approve(self, school_id: UUID) -> School:
        """Move a pending school to ACTIVE. Idempotent for an already-active school."""
        school = await self.get_school(school_id)
        if school.status is SchoolStatus.CANCELLED:
            raise ConflictError("A cancelled school cannot be approved.")
        if school.status is SchoolStatus.ACTIVE:
            return school
        return await self.repo.update(
            school, status=SchoolStatus.ACTIVE, approved_at=datetime.now(UTC)
        )

    async def suspend(self, school_id: UUID) -> School:
        """Suspend a school (non-payment / ToS). Its staff can no longer log in."""
        school = await self.get_school(school_id)
        return await self.repo.update(school, status=SchoolStatus.SUSPENDED)

    async def update(self, school_id: UUID, payload: SchoolUpdate) -> School:
        school = await self.get_school(school_id)
        values = payload.model_dump(exclude_unset=True)
        if "email" in values and values["email"] is not None:
            values["email"] = _normalise_email(str(values["email"]))
        if not values:
            return school
        return await self.repo.update(school, **values)


def _normalise_email(value: str) -> str:
    return value.strip().lower()
