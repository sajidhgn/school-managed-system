"""Data access for the School aggregate.

WHY THIS FILE EXISTS
    All SQL touching `schools` lives here, behind the generic `BaseRepository`. The
    service asks "does this slug exist?" or "give me the pending schools"; it never
    writes a `select()` itself.

INTERACTIONS
    * Constructed by `TenancyService` with the request-scoped `AsyncSession`.
    * Every read is still subject to the schools RLS policy at the database level.
"""

from __future__ import annotations

from typing import ClassVar

from app.common.repository import BaseRepository
from app.modules.tenancy.models import School, SchoolStatus


class SchoolRepository(BaseRepository[School]):
    """CRUD + school-specific finders."""

    model = School
    sortable_fields: ClassVar[frozenset[str]] = frozenset({"name", "created_at", "status"})

    async def get_by_slug(self, slug: str) -> School | None:
        return await self.find_one(School.slug == slug)

    async def slug_exists(self, slug: str) -> bool:
        """Whether a live school already owns this slug.

        NOTE: under RLS this can only see schools the caller is allowed to see. It is
        therefore reliable for a super admin (who sees all), and a best-effort
        pre-check for the self-registration path -- where the unique index on `slug`
        is the real backstop. See `TenancyService._unique_slug`.
        """
        return await self.exists(School.slug == slug)

    async def list_by_status(
        self, status: SchoolStatus | None, **list_kwargs: object
    ) -> tuple[list[School], int]:
        conditions = (School.status == status,) if status is not None else ()
        rows, total = await self.list(*conditions, **list_kwargs)  # type: ignore[arg-type]
        return list(rows), total
