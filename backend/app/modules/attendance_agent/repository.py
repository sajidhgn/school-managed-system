"""Attendance agent data access. SQL only -- no business rules.

Organization isolation comes from RLS. Hand-built joins apply the campus filter
explicitly: a joined `select(...)` never passes through `_base_select`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repository import BaseRepository
from app.core.context import get_school_id
from app.modules.academics.models import SchoolClass, Section
from app.modules.academics.teaching_scope import taught_section_ids
from app.modules.attendance_agent.models import (
    OPEN_STATUSES,
    AttendanceChatDraft,
    AttendanceChatStatus,
)


@dataclass(frozen=True, slots=True)
class SectionTarget:
    """A section the teacher may mark a register for."""

    section: Section
    school_class: SchoolClass

    @property
    def label(self) -> str:
        return f"{self.school_class.name}-{self.section.name}"


class AttendanceChatDraftRepository(BaseRepository[AttendanceChatDraft]):
    model = AttendanceChatDraft

    async def by_inbound_id(self, inbound_message_id: str) -> AttendanceChatDraft | None:
        return await self.find_one(AttendanceChatDraft.inbound_message_id == inbound_message_id)

    async def open_for(
        self, teacher_user_id: UUID, *, since: datetime
    ) -> AttendanceChatDraft | None:
        """The teacher's newest register still in conversation, locked for this reply.

        FOR UPDATE: a teacher double-tapping OK sends two webhooks; the second one
        waits here and then finds the register already SUBMITTED.
        """
        stmt = (
            self._base_select()
            .where(
                AttendanceChatDraft.teacher_user_id == teacher_user_id,
                AttendanceChatDraft.status.in_(OPEN_STATUSES),
                AttendanceChatDraft.updated_at >= since,
            )
            .order_by(AttendanceChatDraft.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def lock(self, draft_id: UUID) -> AttendanceChatDraft | None:
        stmt = self._base_select().where(AttendanceChatDraft.id == draft_id).with_for_update()
        return (await self.session.execute(stmt)).scalars().first()

    async def cancel_open(self, teacher_user_id: UUID, *, reason: str) -> None:
        """A new register replaces whatever the teacher had not confirmed."""
        stmt = (
            update(AttendanceChatDraft)
            .where(
                AttendanceChatDraft.teacher_user_id == teacher_user_id,
                AttendanceChatDraft.status.in_(OPEN_STATUSES),
            )
            .values(status=AttendanceChatStatus.CANCELLED, error=reason)
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(AttendanceChatDraft.school_id == school_id)
        await self.session.execute(stmt)


async def markable_sections(
    session: AsyncSession, school_id: UUID, teacher_id: UUID | None
) -> list[SectionTarget]:
    """Sections on the campus the teacher may take a register for, in class order.

    `teacher_id` None = unbound (`class:view_all`): every section. Otherwise the
    sections they class-teach or teach a subject in -- the same boundary
    `AttendanceService` applies to the web register.
    """
    stmt = (
        select(Section, SchoolClass)
        .join(SchoolClass, SchoolClass.id == Section.class_id)
        .where(
            Section.school_id == school_id,
            Section.deleted_at.is_(None),
            SchoolClass.deleted_at.is_(None),
        )
        .order_by(SchoolClass.level, Section.name)
    )
    if teacher_id is not None:
        stmt = stmt.where(Section.id.in_(taught_section_ids(teacher_id)))
    rows = (await session.execute(stmt)).all()
    return [SectionTarget(section=s, school_class=c) for s, c in rows]
