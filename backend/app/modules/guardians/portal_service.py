"""What the parent portal is allowed to show, and how it assembles it.

WHY THIS FILE EXISTS AND IS NOT PART OF `service.py`
    `service.py` answers "what may SCHOOL STAFF do to guardian records". This answers
    "what may a GUARDIAN see". They share tables and nothing else: one is
    permission-gated CRUD over other people's data, the other is a read-only view of
    the caller's own family, bounded per child by a flag on a link row.

    Keeping them in one class would mean one object holding both a staff-authorised
    write path and a parent-authorised read path, with only a parameter separating
    them. That is exactly the shape in which a confused-deputy bug hides.

RESPONSIBILITY
    Resolve the caller's children through the link filter, and project them into the
    deliberately narrow portal schema. No writes: nothing in this module mutates.

INTERACTIONS
    * `api/deps.require_guardian` has already proved the caller and bound the
      organization, so RLS is active on every query below.
    * `repository.GuardianStudentRepository.children_for_guardian_portal` owns the
      link filter; it is not re-expressed here.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import GuardianContext
from app.core.config import Settings, get_settings
from app.core.exceptions import NotFoundError
from app.modules.diary.schemas import DiaryPage
from app.modules.diary.service import DiaryService
from app.modules.guardians.models import Guardian, GuardianIdentity, GuardianStudent
from app.modules.guardians.repository import GuardianStudentRepository
from app.modules.guardians.schemas import GuardianChildRead, GuardianProfile
from app.modules.tenancy.models import Organization, School


class GuardianPortalService:
    """Read-only projections for an authenticated guardian."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or get_settings()
        self.links = GuardianStudentRepository(session)

    async def profile(self, ctx: GuardianContext) -> GuardianProfile:
        guardian = await self._guardian(ctx)
        identity = await self.session.get(GuardianIdentity, ctx.identity_id)
        organization = await self.session.get(Organization, ctx.organization_id)
        if identity is None:
            # Unreachable through the dependency, which already loaded it. Raised
            # rather than defaulted so a future caller that skips the guard fails
            # loudly instead of rendering a profile for nobody.
            raise NotFoundError("Guardian account not found.")
        return GuardianProfile(
            identity_id=identity.id,
            guardian_id=guardian.id,
            organization_id=ctx.organization_id,
            organization_name=organization.name if organization else "School",
            full_name=guardian.full_name,
            phone=identity.phone,
            email=identity.email,
            preferred_locale=identity.preferred_locale,
        )

    async def children(self, ctx: GuardianContext) -> list[GuardianChildRead]:
        """Every child this guardian may view, in this organization.

        Campus names are resolved in ONE query rather than per child. A parent with
        four children at two campuses would otherwise cost four school lookups on a
        screen that renders in a single request.
        """
        links = await self.links.children_for_guardian_portal(ctx.guardian_id)
        if not links:
            return []

        rows = (
            await self.session.execute(
                select(School.id, School.name).where(
                    School.id.in_({link.school_id for link in links})
                )
            )
        ).all()
        school_names: dict[UUID, str] = dict(rows)  # type: ignore[arg-type]
        return [self._project(link, school_names.get(link.school_id, "School")) for link in links]

    async def child(self, ctx: GuardianContext, student_id: str) -> GuardianChildRead:
        """One child, or 404.

        Resolved by filtering the SAME list the `/children` endpoint returns rather
        than by loading the student directly. That is not laziness: a direct load would
        be a second, independent authorisation path over the same data, and the two
        would eventually disagree about what `can_view_results` means.
        """
        try:
            target = UUID(student_id)
        except ValueError as exc:
            raise NotFoundError("Child not found.") from exc

        for link in await self.links.children_for_guardian_portal(ctx.guardian_id):
            if link.student_id == target:
                school = await self.session.get(School, link.school_id)
                return self._project(link, school.name if school else "School")
        raise NotFoundError("Child not found.")

    async def child_diary(
        self, ctx: GuardianContext, student_id: str, entry_date: date
    ) -> DiaryPage:
        """The diary page of the section this child sits in, read-only.

        The child is resolved through `child()` -- the same link filter, not a
        second authorisation path. A child with no section has no diary; that is a
        404 rather than an empty page, because an empty page would read as "no
        homework today", which is a different and wrong answer.
        """
        child = await self.child(ctx, student_id)
        if child.section_id is None:
            raise NotFoundError("This child is not placed in a class yet.")
        return await DiaryService(self.session).page(
            child.section_id, entry_date, user_id=None, may_write=False, may_manage=False
        )

    # -- internals ----------------------------------------------------------

    async def _guardian(self, ctx: GuardianContext) -> Guardian:
        guardian = await self.session.get(Guardian, ctx.guardian_id)
        if guardian is None or guardian.deleted_at is not None:
            raise NotFoundError("Guardian account not found.")
        return guardian

    @staticmethod
    def _project(link: GuardianStudent, school_name: str) -> GuardianChildRead:
        student = link.student
        return GuardianChildRead(
            student_id=student.id,
            school_id=link.school_id,
            school_name=school_name,
            admission_number=student.admission_number,
            full_name=f"{student.first_name} {student.last_name}",
            date_of_birth=student.date_of_birth,
            section_id=student.section_id,
            status=student.status.value,
            relationship_type=link.relationship_type,
            can_view_results=link.can_view_results,
        )
