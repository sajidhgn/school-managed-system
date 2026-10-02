"""Diary data access. SQL only -- no business rules.

Organization isolation comes from PostgreSQL RLS. Every hand-built query below
applies the campus filter explicitly, for the reason `attendance/repository.py`
gives: a joined `select(...)` never passes through `_base_select`.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repository import BaseRepository
from app.core.context import get_school_id
from app.modules.academics.models import ClassSubject, SchoolClass, Section, Subject
from app.modules.auth.models import User
from app.modules.diary.models import DiaryEntry


class DiaryEntryRepository(BaseRepository[DiaryEntry]):
    model = DiaryEntry
    sortable_fields = frozenset({"entry_date", "created_at"})

    async def for_page(self, section_id: UUID, entry_date: date) -> dict[UUID, DiaryEntry]:
        """One section's entries for one date, keyed by subject."""
        stmt = self._base_select().where(
            DiaryEntry.section_id == section_id, DiaryEntry.entry_date == entry_date
        )
        rows = (await self.session.execute(stmt)).scalars().all()
        return {entry.subject_id: entry for entry in rows}

    async def filled_counts(self, entry_date: date) -> dict[UUID, int]:
        """Entries per section for one date, across the campus, in ONE query."""
        stmt = (
            select(DiaryEntry.section_id, func.count(DiaryEntry.id))
            .where(DiaryEntry.entry_date == entry_date)
            .group_by(DiaryEntry.section_id)
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(DiaryEntry.school_id == school_id)
        return {section_id: int(n) for section_id, n in (await self.session.execute(stmt)).all()}


class DiaryLookupRepository:
    """The academics reads a diary page is assembled from.

    Kept here rather than added to the academics repositories because each one is
    shaped for this page (joined, ordered for printing) and nothing else needs it.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def sections(self) -> Sequence[tuple[Section, SchoolClass]]:
        """Every live section on the campus with its class, in display order."""
        stmt = (
            select(Section, SchoolClass)
            .join(SchoolClass, SchoolClass.id == Section.class_id)
            .where(Section.deleted_at.is_(None), SchoolClass.deleted_at.is_(None))
            .order_by(SchoolClass.level, Section.name)
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(Section.school_id == school_id)
        return [(s, c) for s, c in (await self.session.execute(stmt)).all()]

    async def section(self, section_id: UUID) -> tuple[Section, SchoolClass] | None:
        stmt = (
            select(Section, SchoolClass)
            .join(SchoolClass, SchoolClass.id == Section.class_id)
            .where(
                Section.id == section_id,
                Section.deleted_at.is_(None),
                SchoolClass.deleted_at.is_(None),
            )
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(Section.school_id == school_id)
        row = (await self.session.execute(stmt)).first()
        return (row[0], row[1]) if row else None

    async def curriculum(
        self, class_ids: Iterable[UUID]
    ) -> dict[UUID, list[tuple[ClassSubject, Subject]]]:
        """Each class's subjects, in the order the curriculum was entered.

        Entry order, not alphabetical: it is the order the school set the subjects
        up in, which is the order its paper diary already prints them.
        """
        ids = set(class_ids)
        if not ids:
            return {}
        stmt = (
            select(ClassSubject, Subject)
            .join(Subject, Subject.id == ClassSubject.subject_id)
            .where(
                ClassSubject.class_id.in_(ids),
                ClassSubject.deleted_at.is_(None),
                Subject.deleted_at.is_(None),
            )
            .order_by(ClassSubject.created_at, Subject.name)
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(ClassSubject.school_id == school_id)
        result: dict[UUID, list[tuple[ClassSubject, Subject]]] = {}
        for link, subject in (await self.session.execute(stmt)).all():
            result.setdefault(link.class_id, []).append((link, subject))
        return result

    async def user_names(self, user_ids: Iterable[UUID | None]) -> dict[UUID, str]:
        ids = {i for i in user_ids if i is not None}
        if not ids:
            return {}
        rows = await self.session.execute(select(User.id, User.full_name).where(User.id.in_(ids)))
        return {row[0]: row[1] for row in rows}
