"""Generic async repository.

WHY THIS FILE EXISTS
    Roughly 80% of data access in a CRUD-heavy system is the same six operations
    against different tables. Writing them per module produces hundreds of lines of
    near-identical code where subtle inconsistencies hide -- one module forgetting
    the soft-delete filter, another forgetting pagination limits.

RESPONSIBILITY
    Own *how* we talk to the database: query construction, filtering, sorting,
    pagination, soft deletion. It knows nothing about business rules -- no
    "a student cannot enroll twice" logic lives here. That belongs to the service.

    The clean split:
      Repository -> "how do I fetch/persist rows?"          (SQL knowledge)
      Service    -> "what is allowed and what happens next?" (business knowledge)

INTERACTIONS
    * Constructed by services with an `AsyncSession`.
    * Subclassed per aggregate: `class StudentRepository(BaseRepository[Student])`,
      which adds domain-specific finders like `get_by_admission_number`.

WHY REPOSITORIES AT ALL, GIVEN SQLALCHEMY IS ALREADY AN ABSTRACTION
    Testability and blast radius. Services depend on a narrow interface we own, so
    unit tests can substitute a fake. And when a query needs optimisation, there is
    exactly one place it can be -- not scattered across route handlers.

DEVIATION FROM THE SKILL PLAYBOOK
    The playbook passes `db: AsyncSession` into every method and instantiates a
    module-level singleton repository. We inject the session into `__init__`
    instead: the session is request-scoped state, and threading it through every
    call signature is noise. A module-level singleton holding no session is also a
    trap -- it looks stateless but every method secretly needs external state.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, ClassVar, cast
from uuid import UUID

from sqlalchemy import CursorResult, Select, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.common.schemas import PageParams, SortDirection, SortParams
from app.core.exceptions import ValidationError
from app.db.base import Base


class BaseRepository[ModelT: Base]:
    """CRUD + query primitives for a single ORM model.

    Subclasses set `model` and, when the table supports sorting, `sortable_fields`.
    """

    model: type[ModelT]

    # Allowlist of column names the client may sort by. Empty by default: a
    # repository must opt in explicitly, so no column is ever exposed to
    # client-controlled ORDER BY by accident.
    sortable_fields: ClassVar[frozenset[str]] = frozenset()

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- query building -----------------------------------------------------

    def _base_select(self, *, include_deleted: bool = False) -> Select[tuple[ModelT]]:
        """Start every query from here so shared filters can never be forgotten.

        Note there is no `school_id` filter: tenant scoping is enforced by
        PostgreSQL RLS at the connection level (see `db/session.py`). Adding it here
        too would be belt-and-braces, but it would also mean a missing filter is
        survivable -- and that is exactly the complacency RLS is meant to remove.
        """
        stmt = select(self.model)
        if not include_deleted and hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))  # type: ignore[attr-defined]
        return stmt

    def apply_sort(
        self, stmt: Select[tuple[ModelT]], sort: SortParams | None
    ) -> Select[tuple[ModelT]]:
        """Apply client-requested ordering, validated against the allowlist.

        Falls back to `created_at DESC` (newest first), then to primary key, so
        pagination is always deterministic. Unstable ordering is a classic
        pagination bug: rows shuffle between pages and users see duplicates.
        """
        if sort and sort.sort_by:
            if sort.sort_by not in self.sortable_fields:
                raise ValidationError(
                    f"Cannot sort by '{sort.sort_by}'.",
                    code="INVALID_SORT_FIELD",
                    details={"allowed": sorted(self.sortable_fields)},
                )
            column = getattr(self.model, sort.sort_by)
            direction = column.desc() if sort.sort_dir is SortDirection.DESC else column.asc()
            return stmt.order_by(direction, self.model.id)  # type: ignore[attr-defined]

        if hasattr(self.model, "created_at"):
            return stmt.order_by(self.model.created_at.desc(), self.model.id)  # type: ignore[attr-defined]
        return stmt.order_by(self.model.id)  # type: ignore[attr-defined]

    # -- reads --------------------------------------------------------------

    async def get(self, entity_id: UUID, *, include_deleted: bool = False) -> ModelT | None:
        """Fetch by primary key, or None. Returning None (not raising) keeps the
        repository free of policy -- the service decides whether absence is a 404."""
        stmt = self._base_select(include_deleted=include_deleted).where(
            self.model.id == entity_id  # type: ignore[attr-defined]
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def find_one(self, *conditions: ColumnElement[bool]) -> ModelT | None:
        """Fetch the first row matching arbitrary conditions."""
        stmt = self._base_select().where(*conditions).limit(1)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def exists(self, *conditions: ColumnElement[bool]) -> bool:
        """Existence check that never materialises a row.

        Used for uniqueness pre-checks ("is this admission number taken?"), which
        are far cheaper than fetching the object just to test for None.
        """
        stmt = select(func.count()).select_from(self.model).where(*conditions)
        if hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))  # type: ignore[attr-defined]
        result = await self.session.execute(stmt.limit(1))
        return (result.scalar_one() or 0) > 0

    async def count(self, *conditions: ColumnElement[bool]) -> int:
        stmt = select(func.count()).select_from(self.model)
        if conditions:
            stmt = stmt.where(*conditions)
        if hasattr(self.model, "deleted_at"):
            stmt = stmt.where(self.model.deleted_at.is_(None))  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)

    async def list(
        self,
        *conditions: ColumnElement[bool],
        params: PageParams | None = None,
        sort: SortParams | None = None,
    ) -> tuple[Sequence[ModelT], int]:
        """Return one page of rows plus the total matching count.

        Returns a tuple rather than a `Page` because the repository must not depend
        on API-layer schemas -- the service assembles the `Page`. That keeps the
        dependency arrow pointing inward.

        PERFORMANCE: this issues two queries (rows + COUNT). A window-function
        variant (`COUNT(*) OVER ()`) does it in one, but interacts badly with
        eager-loaded joins. Two clean queries is the right default; revisit only
        if profiling says so.
        """
        params = params or PageParams()

        stmt = self._base_select()
        if conditions:
            stmt = stmt.where(*conditions)
        stmt = self.apply_sort(stmt, sort).offset(params.offset).limit(params.limit)

        rows = (await self.session.execute(stmt)).scalars().all()
        total = await self.count(*conditions)
        return rows, total

    # -- writes -------------------------------------------------------------

    async def create(self, **values: Any) -> ModelT:
        """Insert a row and flush so the generated id is available immediately.

        `flush()` sends the INSERT but does NOT commit -- the request-scoped
        transaction in `get_db` owns the commit. This is what lets a service create
        a student, then create their fee record, and have both roll back together
        if the second one fails.
        """
        instance = self.model(**values)
        self.session.add(instance)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def update(self, instance: ModelT, **values: Any) -> ModelT:
        """Apply a partial update to a loaded instance.

        Callers pass the output of `schema.model_dump(exclude_unset=True)` so that
        "field omitted" and "field explicitly set to null" stay distinguishable --
        the difference between PATCH semantics and accidental data loss.
        """
        for field, value in values.items():
            setattr(instance, field, value)
        await self.session.flush()
        await self.session.refresh(instance)
        return instance

    async def soft_delete(self, instance: ModelT) -> ModelT:
        """Mark deleted while preserving the row and its foreign-key references."""
        if not hasattr(instance, "deleted_at"):
            raise TypeError(f"{self.model.__name__} does not support soft deletion.")
        stmt = (
            update(self.model)
            .where(self.model.id == instance.id)  # type: ignore[attr-defined]
            .values(deleted_at=func.now())
        )
        await self.session.execute(stmt)
        await self.session.refresh(instance)
        return instance

    async def hard_delete(self, entity_id: UUID) -> bool:
        """Permanently remove a row.

        Reserve for genuinely transient data (expired sessions, idempotency keys)
        and GDPR erasure requests. Business records should be soft-deleted.
        """
        stmt = delete(self.model).where(self.model.id == entity_id)  # type: ignore[attr-defined]
        result = await self.session.execute(stmt)
        # `rowcount` exists on CursorResult (what a DELETE returns) but not on the
        # generic Result protocol that `execute` is typed as returning, hence the cast.
        return bool(cast("CursorResult[Any]", result).rowcount)
