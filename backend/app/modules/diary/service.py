"""Diary business rules -- who may write which row of a section's daily page.

THE ONE RULE THIS MODULE EXISTS TO ENFORCE
    A diary page belongs to a SECTION; its rows are the section's class curriculum.
    Two kinds of teacher write on it:

        the CLASS TEACHER (`sections.class_teacher_id`)   every row on the page
        a SUBJECT TEACHER (`class_subjects.teacher_id`)   only their subject's row

    That mirrors how the paper diary works: the class teacher owns the sheet and
    collects the homework from colleagues, and a colleague writing Maths homework
    for Grade 4-B has no business overwriting the Urdu line beside it.

    `diary:manage` lifts the assignment check entirely -- a coordinator covering an
    absent class teacher has to be able to send the page home. `diary:write` alone
    without any assignment writes nothing, and the page says so per row
    (`can_edit`) instead of failing on save.

INTERACTIONS
    * Reads `sections`, `classes`, `class_subjects`, `subjects` and `users`; never
      writes them.
    * `router.py` resolves the permissions and passes them in as flags, so this
      service stays callable without HTTP.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditAction, record_audit
from app.core.context import require_organization_id, require_school_id
from app.core.exceptions import AuthorizationError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.modules.academics.models import ClassSubject, SchoolClass, Section, Subject
from app.modules.diary.models import DiaryEntry
from app.modules.diary.repository import DiaryEntryRepository, DiaryLookupRepository
from app.modules.diary.schemas import (
    DiaryAccess,
    DiaryPage,
    DiaryPageWrite,
    DiaryRow,
    DiarySectionOption,
)

logger = get_logger(__name__)

# How far from today an ordinary `diary:write` holder may write. Forward, because
# teachers prepare tomorrow's (or Monday's) page in advance; backward, because a
# page is corrected for a day or two after it went home. Both bound typos in the
# date rather than authority -- `diary:manage` is not limited.
_WRITE_WINDOW_DAYS = 30


class DiaryService:
    """Assembles diary pages and applies teachers' edits to them."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.entries = DiaryEntryRepository(session)
        self.lookup = DiaryLookupRepository(session)

    # -- reading ------------------------------------------------------------

    async def sections(
        self, entry_date: date, *, user_id: UUID, may_write: bool, may_manage: bool
    ) -> list[DiarySectionOption]:
        """Every section on the campus, with what the caller may do on its page.

        The caller's own classes sort first, so a teacher opening the diary lands
        on their class rather than on Grade 1-A.
        """
        sections = await self.lookup.sections()
        curriculum = await self.lookup.curriculum({c.id for _, c in sections})
        filled = await self.entries.filled_counts(entry_date)
        names = await self.lookup.user_names(s.class_teacher_id for s, _ in sections)

        options: list[DiarySectionOption] = []
        for section, school_class in sections:
            subjects = curriculum.get(school_class.id, [])
            access = self._access(
                section, subjects, user_id=user_id, may_write=may_write, may_manage=may_manage
            )
            options.append(
                DiarySectionOption(
                    section_id=section.id,
                    section_name=section.name,
                    class_id=school_class.id,
                    class_name=school_class.name,
                    class_level=school_class.level,
                    class_teacher_name=names.get(section.class_teacher_id)
                    if section.class_teacher_id
                    else None,
                    access=access,
                    filled_count=filled.get(section.id, 0),
                    subject_count=len(subjects),
                )
            )

        rank = {
            DiaryAccess.CLASS_TEACHER: 0,
            DiaryAccess.SUBJECT_TEACHER: 1,
            DiaryAccess.MANAGE: 2,
            DiaryAccess.READ: 2,
        }
        # `sorted` is stable, so within a rank the class-level order is kept.
        return sorted(options, key=lambda o: rank[o.access])

    async def page(
        self,
        section_id: UUID,
        entry_date: date,
        *,
        user_id: UUID | None,
        may_write: bool,
        may_manage: bool,
    ) -> DiaryPage:
        """One section's page for one date: every subject, homework or not."""
        section, school_class = await self._section_or_404(section_id)
        subjects = (await self.lookup.curriculum([school_class.id])).get(school_class.id, [])
        entries = await self.entries.for_page(section.id, entry_date)

        names = await self.lookup.user_names(
            [section.class_teacher_id]
            + [link.teacher_id for link, _ in subjects]
            + [e.written_by_user_id for e in entries.values()]
        )

        rows: list[DiaryRow] = []
        for link, subject in subjects:
            entry = entries.get(subject.id)
            rows.append(
                DiaryRow(
                    subject_id=subject.id,
                    subject_code=subject.code,
                    subject_name=subject.name,
                    teacher_id=link.teacher_id,
                    teacher_name=names.get(link.teacher_id) if link.teacher_id else None,
                    content=entry.content if entry else None,
                    written_by_name=names.get(entry.written_by_user_id)
                    if entry and entry.written_by_user_id
                    else None,
                    updated_at=entry.updated_at if entry else None,
                    can_edit=user_id is not None
                    and self._may_edit_row(
                        section, link, user_id=user_id, may_write=may_write, may_manage=may_manage
                    ),
                )
            )

        return DiaryPage(
            section_id=section.id,
            section_name=section.name,
            class_id=school_class.id,
            class_name=school_class.name,
            class_teacher_name=names.get(section.class_teacher_id)
            if section.class_teacher_id
            else None,
            entry_date=entry_date,
            rows=rows,
            can_edit=any(row.can_edit for row in rows),
        )

    # -- writing ------------------------------------------------------------

    async def write(
        self,
        section_id: UUID,
        entry_date: date,
        payload: DiaryPageWrite,
        *,
        user_id: UUID,
        may_write: bool,
        may_manage: bool,
    ) -> DiaryPage:
        """Apply the changed rows. All or nothing: every row is checked before any
        is written, so a refused row never leaves the page half-saved."""
        if not (may_write or may_manage):
            raise AuthorizationError(
                "You do not have permission to write the diary.", code="FORBIDDEN"
            )
        section, school_class = await self._section_or_404(section_id)
        if not may_manage:
            self._assert_writable_date(entry_date)

        links = {
            subject.id: link
            for link, subject in (await self.lookup.curriculum([school_class.id])).get(
                school_class.id, []
            )
        }

        seen: set[UUID] = set()
        for item in payload.entries:
            if item.subject_id in seen:
                raise ValidationError(
                    "A subject appears twice in one save.", code="DUPLICATE_SUBJECT"
                )
            seen.add(item.subject_id)
            link = links.get(item.subject_id)
            if link is None:
                raise ValidationError(
                    f"That subject is not part of {school_class.name}'s curriculum.",
                    code="SUBJECT_NOT_IN_CLASS",
                )
            if not self._may_edit_row(
                section, link, user_id=user_id, may_write=may_write, may_manage=may_manage
            ):
                raise AuthorizationError(
                    "You can only write the diary for your own class or the subjects you teach it.",
                    code="DIARY_NOT_ASSIGNED",
                )

        existing = await self.entries.for_page(section.id, entry_date)
        changes: list[dict[str, Any]] = []
        for item in payload.entries:
            text = item.content.strip()
            entry = existing.get(item.subject_id)
            before = entry.content if entry else None
            if (text or None) == before:
                continue

            if not text:
                if entry is not None:
                    await self.session.delete(entry)
            elif entry is None:
                self.session.add(
                    DiaryEntry(
                        section_id=section.id,
                        subject_id=item.subject_id,
                        entry_date=entry_date,
                        content=text,
                        written_by_user_id=user_id,
                        # Inherited from the section, so an entry can never be scoped
                        # differently from the class it is written for.
                        organization_id=section.organization_id,
                        school_id=section.school_id,
                    )
                )
            else:
                entry.content = text
                entry.written_by_user_id = user_id
            changes.append(
                {"subject_id": str(item.subject_id), "before": before, "after": text or None}
            )

        if changes:
            await self.session.flush()
            await record_audit(
                self.session,
                organization_id=require_organization_id(),
                school_id=require_school_id(),
                actor_user_id=user_id,
                action=AuditAction.DIARY_UPDATED,
                entity_type="section",
                entity_id=section.id,
                after={"entry_date": str(entry_date), "changes": changes},
            )
            logger.info(
                "diary_updated",
                section_id=str(section.id),
                entry_date=str(entry_date),
                changed=len(changes),
            )

        return await self.page(
            section.id, entry_date, user_id=user_id, may_write=may_write, may_manage=may_manage
        )

    # -- internals ----------------------------------------------------------

    async def _section_or_404(self, section_id: UUID) -> tuple[Section, SchoolClass]:
        found = await self.lookup.section(section_id)
        if found is None:
            raise NotFoundError("Section not found.")
        return found

    @staticmethod
    def _may_edit_row(
        section: Section,
        link: ClassSubject,
        *,
        user_id: UUID,
        may_write: bool,
        may_manage: bool,
    ) -> bool:
        if may_manage:
            return True
        if not may_write:
            return False
        return section.class_teacher_id == user_id or link.teacher_id == user_id

    @staticmethod
    def _access(
        section: Section,
        subjects: list[tuple[ClassSubject, Subject]],
        *,
        user_id: UUID,
        may_write: bool,
        may_manage: bool,
    ) -> DiaryAccess:
        if may_write and section.class_teacher_id == user_id:
            return DiaryAccess.CLASS_TEACHER
        if may_write and any(link.teacher_id == user_id for link, _ in subjects):
            return DiaryAccess.SUBJECT_TEACHER
        if may_manage:
            return DiaryAccess.MANAGE
        return DiaryAccess.READ

    @staticmethod
    def _assert_writable_date(entry_date: date) -> None:
        today = datetime.now(UTC).date()
        if abs((entry_date - today).days) > _WRITE_WINDOW_DAYS:
            raise ValidationError(
                f"The diary can only be written within {_WRITE_WINDOW_DAYS} days of today. "
                "Check the date.",
                code="DATE_OUT_OF_RANGE",
            )


def default_diary_date() -> date:
    """Today, in UTC -- the same clock attendance uses."""
    return datetime.now(UTC).date()
