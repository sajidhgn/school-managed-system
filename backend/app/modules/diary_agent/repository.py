"""Diary agent data access. SQL only -- no business rules.

Organization isolation comes from RLS. Hand-built joins apply the campus filter
explicitly: a joined `select(...)` never passes through `_base_select`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.repository import BaseRepository
from app.core.context import get_school_id
from app.modules.academics.models import ClassSubject, SchoolClass, Section, Subject
from app.modules.academics.teaching_scope import taught_class_ids, taught_section_ids
from app.modules.auth.models import User, UserStatus
from app.modules.diary_agent.models import (
    OPEN_STATUSES,
    DiaryAgentSettings,
    DiaryDraft,
    DiaryDraftStatus,
)
from app.modules.rbac.models import Membership, MembershipStatus, RolePermission
from app.modules.whatsapp.models import WhatsAppGroup


@dataclass(frozen=True, slots=True)
class StaffCandidate:
    """A campus member with a phone on file, and what their role lets them do."""

    user_id: UUID
    full_name: str
    phone: str
    is_school_level: bool
    permissions: frozenset[str]


@dataclass(frozen=True, slots=True)
class DiaryTarget:
    """A class group a teacher may post the diary to."""

    group: WhatsAppGroup
    school_class: SchoolClass
    section: Section | None

    @property
    def label(self) -> str:
        if self.section is not None:
            return f"{self.school_class.name}-{self.section.name}"
        return self.school_class.name


class DiaryAgentSettingsRepository(BaseRepository[DiaryAgentSettings]):
    model = DiaryAgentSettings

    async def for_campus(self) -> DiaryAgentSettings | None:
        return (await self.session.execute(self._base_select())).scalars().first()


class DiaryDraftRepository(BaseRepository[DiaryDraft]):
    model = DiaryDraft
    sortable_fields = frozenset({"created_at", "updated_at"})

    async def by_inbound_id(self, inbound_message_id: str) -> DiaryDraft | None:
        return await self.find_one(DiaryDraft.inbound_message_id == inbound_message_id)

    async def open_for(self, teacher_user_id: UUID, *, since: datetime) -> DiaryDraft | None:
        """The teacher's newest draft still in conversation, locked for this reply.

        FOR UPDATE: a teacher double-tapping OK sends two webhooks; the second one
        waits here and then finds the draft already POSTED.
        """
        stmt = (
            self._base_select()
            .where(
                DiaryDraft.teacher_user_id == teacher_user_id,
                DiaryDraft.status.in_(OPEN_STATUSES),
                DiaryDraft.updated_at >= since,
            )
            .order_by(DiaryDraft.created_at.desc())
            .limit(1)
            .with_for_update()
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def lock(self, draft_id: UUID) -> DiaryDraft | None:
        stmt = self._base_select().where(DiaryDraft.id == draft_id).with_for_update()
        return (await self.session.execute(stmt)).scalars().first()

    async def cancel_open(self, teacher_user_id: UUID, *, reason: str) -> None:
        """A new photo replaces whatever the teacher had not finished."""
        stmt = (
            update(DiaryDraft)
            .where(
                DiaryDraft.teacher_user_id == teacher_user_id,
                DiaryDraft.status.in_(OPEN_STATUSES),
            )
            .values(status=DiaryDraftStatus.CANCELLED, error=reason)
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(DiaryDraft.school_id == school_id)
        await self.session.execute(stmt)


class DiaryLookupRepository:
    """The staff, group and curriculum reads the agent is assembled from."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def staff_with_phones(self, school_id: UUID) -> list[StaffCandidate]:
        """Every live member of this campus (or org-level) whose user has a phone.

        Small -- a campus's staff -- so phone normalisation happens in Python, where
        the rules can be read, rather than as SQL string surgery.
        """
        stmt = (
            select(
                User.id,
                User.full_name,
                User.phone,
                Membership.school_id,
                Membership.role_id,
            )
            .join(Membership, Membership.user_id == User.id)
            .where(
                User.phone.is_not(None),
                User.deleted_at.is_(None),
                User.status == UserStatus.ACTIVE,
                Membership.deleted_at.is_(None),
                Membership.status == MembershipStatus.ACTIVE,
                or_(Membership.school_id == school_id, Membership.school_id.is_(None)),
            )
        )
        rows = (await self.session.execute(stmt)).all()
        role_ids = {row.role_id for row in rows}
        codes: dict[UUID, set[str]] = {rid: set() for rid in role_ids}
        if role_ids:
            perm_rows = await self.session.execute(
                select(RolePermission.role_id, RolePermission.permission_code).where(
                    RolePermission.role_id.in_(role_ids)
                )
            )
            for role_id, code in perm_rows.all():
                codes[role_id].add(code)
        return [
            StaffCandidate(
                user_id=row.id,
                full_name=row.full_name,
                phone=row.phone,
                is_school_level=row.school_id is not None,
                permissions=frozenset(codes.get(row.role_id, set())),
            )
            for row in rows
        ]

    async def targets(self, school_id: UUID, teacher_id: UUID | None) -> list[DiaryTarget]:
        """Active class groups on the campus the teacher may post to.

        `teacher_id` None = unbound (`class:view_all`): every active group. Otherwise
        a whole-class group needs the teacher assigned anywhere in the class, and a
        section group needs them in that section -- the same boundary as the rest of
        the teaching scope.
        """
        stmt = (
            select(WhatsAppGroup, SchoolClass, Section)
            .join(SchoolClass, SchoolClass.id == WhatsAppGroup.class_id)
            .outerjoin(Section, Section.id == WhatsAppGroup.section_id)
            .where(
                WhatsAppGroup.school_id == school_id,
                WhatsAppGroup.is_active.is_(True),
                SchoolClass.deleted_at.is_(None),
            )
            .order_by(SchoolClass.level, Section.name.nulls_first(), WhatsAppGroup.name)
        )
        if teacher_id is not None:
            stmt = stmt.where(
                or_(
                    (WhatsAppGroup.section_id.is_(None))
                    & WhatsAppGroup.class_id.in_(taught_class_ids(teacher_id)),
                    WhatsAppGroup.section_id.in_(taught_section_ids(teacher_id)),
                )
            )
        rows = (await self.session.execute(stmt)).all()
        return [DiaryTarget(group=g, school_class=c, section=s) for g, c, s in rows]

    async def subject_names(self, class_ids: Sequence[UUID]) -> list[str]:
        if not class_ids:
            return []
        stmt = (
            select(Subject.name)
            .join(ClassSubject, ClassSubject.subject_id == Subject.id)
            .where(
                ClassSubject.class_id.in_(set(class_ids)),
                ClassSubject.deleted_at.is_(None),
                Subject.deleted_at.is_(None),
            )
            .distinct()
            .order_by(Subject.name)
            .limit(60)
        )
        return list((await self.session.execute(stmt)).scalars())
