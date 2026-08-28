"""Guardian data access. SQL only -- no business rules.

TWO KINDS OF QUERY LIVE HERE AND THEY OBEY DIFFERENT RULES:

  * `GuardianRepository` / `GuardianStudentRepository` run on a TENANT-BOUND session.
    PostgreSQL RLS supplies the organization boundary. `guardian_students` also
    carries `school_id`, so `BaseRepository` adds the campus filter automatically.

  * `IdentityRepository` runs on tables OUTSIDE tenancy (`guardian_identities`,
    `guardian_otp_codes`) because login happens before any organization is known --
    see the module docstring in `models.py`. Nothing here lists them; every method
    is keyed by primary key or by an exact E.164 match the caller must then prove
    control of.

=============================================================================
WHY `guardians` HAS NO `school_id` AND HOW CAMPUS SCOPE IS STILL ENFORCED
=============================================================================
    A guardian belongs to the ORGANIZATION, because one parent legitimately spans
    two campuses of one group. So `BaseRepository`'s automatic campus filter finds no
    column and does nothing -- which would let a teacher at Campus A list every parent
    in the group, including families they have no relationship with.

    `list_for_scope` closes that: when the caller has an active school, it restricts
    to guardians who have at least one LIVE LINK to a student at that school. The
    predicate lives here, in one place, rather than in the service, so a future
    endpoint cannot forget it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import ColumnElement

from app.common.repository import BaseRepository
from app.common.schemas import PageParams, SortParams
from app.core.context import get_school_id
from app.modules.guardians.models import (
    Guardian,
    GuardianIdentity,
    GuardianOtpCode,
    GuardianOtpPurpose,
    GuardianStudent,
)
from app.modules.students.models import Student


class GuardianRepository(BaseRepository[Guardian]):
    model = Guardian
    sortable_fields = frozenset({"full_name", "created_at", "updated_at"})

    def campus_predicate(self) -> ColumnElement[bool] | None:
        """What a school-scoped caller may see, or None for an org-level one.

        TWO CLAUSES, AND THE SECOND ONE IS NOT AN AFTERTHOUGHT:

          * a guardian with a LIVE LINK to a child at this campus -- the durable rule,
            which keeps working when a family moves between campuses; and
          * a guardian this campus REGISTERED -- which covers the window between
            creating the record and linking the first child. Without it a registrar
            creates a parent and immediately gets a 404 reading them back, because
            two requests are needed and the guardian has no links after the first.

        Expressed as one OR'd predicate rather than a join so it composes into the row
        query and the COUNT identically, and so a guardian with two children at the
        same school is not counted twice.
        """
        school_id = get_school_id()
        if school_id is None:
            return None
        linked_here = select(GuardianStudent.guardian_id).where(
            GuardianStudent.school_id == school_id,
            GuardianStudent.deleted_at.is_(None),
        )
        return or_(
            Guardian.id.in_(linked_here),
            Guardian.registered_school_id == school_id,
        )

    async def get_by_identity(self, identity_id: UUID) -> Guardian | None:
        """This organization's record for a given person, if it holds one."""
        return await self.find_one(Guardian.identity_id == identity_id)

    async def get_with_identity(self, guardian_id: UUID) -> Guardian | None:
        """Load a guardian with the identity eagerly attached.

        Eager rather than lazy: `Guardian.identity` is read by every response
        serializer, and an implicit lazy load in async SQLAlchemy raises
        MissingGreenlet rather than quietly issuing a query.
        """
        stmt = (
            self._base_select()
            .options(joinedload(Guardian.identity))
            .where(Guardian.id == guardian_id)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def list_for_scope(
        self,
        *,
        params: PageParams,
        sort: SortParams | None = None,
        search: str | None = None,
        student_id: UUID | None = None,
    ) -> tuple[Sequence[Guardian], int]:
        """One page of guardians visible to the caller, plus the total.

        `search` matches the organization's spelling of the name, the CNIC, or the
        login phone. The phone is matched with a suffix `LIKE` because a clerk looking
        someone up types the last few digits off a note, not a normalised E.164
        string -- and requiring the `+92` prefix to find a parent makes the search box
        useless at the front desk.
        """
        stmt = self._base_select().options(joinedload(Guardian.identity))
        count_stmt = (
            select(func.count(func.distinct(Guardian.id)))
            .select_from(Guardian)
            .where(Guardian.deleted_at.is_(None))
        )

        if (campus := self.campus_predicate()) is not None:
            stmt = stmt.where(campus)
            count_stmt = count_stmt.where(campus)

        if student_id is not None:
            child = select(GuardianStudent.guardian_id).where(
                GuardianStudent.student_id == student_id,
                GuardianStudent.deleted_at.is_(None),
            )
            stmt = stmt.where(Guardian.id.in_(child))
            count_stmt = count_stmt.where(Guardian.id.in_(child))

        if search:
            term = f"%{search}%"
            identity_match = select(GuardianIdentity.id).where(
                or_(
                    GuardianIdentity.phone.like(f"%{search}"),
                    GuardianIdentity.full_name.ilike(term),
                )
            )
            predicate = or_(
                Guardian.full_name.ilike(term),
                Guardian.cnic.ilike(term),
                Guardian.identity_id.in_(identity_match),
            )
            stmt = stmt.where(predicate)
            count_stmt = count_stmt.where(predicate)

        stmt = self.apply_sort(stmt, sort).offset(params.offset).limit(params.limit)
        rows = (await self.session.execute(stmt)).unique().scalars().all()
        total = int((await self.session.execute(count_stmt)).scalar_one() or 0)
        return rows, total

    async def student_counts(self, guardian_ids: Sequence[UUID]) -> dict[UUID, int]:
        """Children per guardian, for a page of guardians, in ONE query.

        The list screen shows a child count on every row. A count per guardian is a
        textbook N+1 that grows with the page size; this is one grouped COUNT.
        """
        if not guardian_ids:
            return {}
        stmt = (
            select(GuardianStudent.guardian_id, func.count(GuardianStudent.id))
            .where(
                GuardianStudent.guardian_id.in_(guardian_ids),
                GuardianStudent.deleted_at.is_(None),
            )
            .group_by(GuardianStudent.guardian_id)
        )
        if (school_id := get_school_id()) is not None:
            stmt = stmt.where(GuardianStudent.school_id == school_id)
        return dict((await self.session.execute(stmt)).all())  # type: ignore[arg-type]


class GuardianStudentRepository(BaseRepository[GuardianStudent]):
    model = GuardianStudent
    sortable_fields = frozenset({"created_at"})

    async def get_link(self, guardian_id: UUID, student_id: UUID) -> GuardianStudent | None:
        return await self.find_one(
            GuardianStudent.guardian_id == guardian_id,
            GuardianStudent.student_id == student_id,
        )

    async def list_for_guardian(self, guardian_id: UUID) -> Sequence[GuardianStudent]:
        """Every live link for one guardian, with the student joined in.

        NOT campus-filtered beyond what `_base_select` already applies. For an
        org-level principal that means both campuses, which is correct and is the
        reason the module exists.
        """
        stmt = (
            self._base_select()
            .options(joinedload(GuardianStudent.student))
            .where(GuardianStudent.guardian_id == guardian_id)
        )
        return (await self.session.execute(stmt)).unique().scalars().all()

    async def list_for_student(self, student_id: UUID) -> Sequence[GuardianStudent]:
        """Every guardian of one child, guardian and identity joined in."""
        stmt = (
            self._base_select()
            .options(joinedload(GuardianStudent.guardian).joinedload(Guardian.identity))
            .where(GuardianStudent.student_id == student_id)
            .order_by(GuardianStudent.is_primary_contact.desc(), GuardianStudent.created_at)
        )
        return (await self.session.execute(stmt)).unique().scalars().all()

    async def current_primary(self, student_id: UUID) -> GuardianStudent | None:
        """The link currently holding primary contact for a child, if any.

        Read before granting it to someone else. The partial unique index would
        otherwise reject the write with a constraint violation, which reaches the
        client as a 500 rather than as "Ayesha's mother is currently the primary
        contact; replace her?".
        """
        return await self.find_one(
            GuardianStudent.student_id == student_id,
            GuardianStudent.is_primary_contact.is_(True),
        )

    async def children_for_guardian_portal(self, guardian_id: UUID) -> Sequence[GuardianStudent]:
        """What the PARENT may see: links flagged `can_view_results`, students joined.

        Separate from `list_for_guardian` even though the SQL is nearly identical,
        because the two answer different questions. The staff view lists every child
        the record touches, including the pickup-only ones. This one is the
        authorisation boundary of the portal, and collapsing them into a flag argument
        is how a caller ends up passing the wrong default.
        """
        stmt = (
            self._base_select()
            .options(joinedload(GuardianStudent.student))
            .join(Student, Student.id == GuardianStudent.student_id)
            .where(
                GuardianStudent.guardian_id == guardian_id,
                GuardianStudent.can_view_results.is_(True),
                Student.deleted_at.is_(None),
            )
        )
        return (await self.session.execute(stmt)).unique().scalars().all()


class GuardianIdentityRepository:
    """Access to the two NON-tenant tables. Not a `BaseRepository`.

    Deliberately not a subclass: `BaseRepository` exists to add the tenant and campus
    filters that make tenant tables safe, and inheriting it here would apply filters
    that are meaningless on a global table while advertising a safety property this
    data does not have. A plain class makes the exception visible.
    """

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # -- identities ---------------------------------------------------------

    async def get(self, identity_id: UUID) -> GuardianIdentity | None:
        stmt = select(GuardianIdentity).where(
            GuardianIdentity.id == identity_id,
            GuardianIdentity.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_phone(self, phone: str) -> GuardianIdentity | None:
        """Exact E.164 match. The ONLY lookup key this table exposes.

        The caller must have normalised `phone` first; a raw `0300...` would silently
        miss and register a duplicate identity. `service.py` and `auth_service.py`
        both normalise before calling, and both are the only callers.
        """
        stmt = select(GuardianIdentity).where(
            GuardianIdentity.phone == phone,
            GuardianIdentity.deleted_at.is_(None),
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def create(self, **values: Any) -> GuardianIdentity:
        identity = GuardianIdentity(**values)
        self.session.add(identity)
        await self.session.flush()
        await self.session.refresh(identity)
        return identity

    async def contexts_for_identity(self, identity_id: UUID) -> Sequence[Guardian]:
        """Every organization holding a live, portal-enabled record for this person.

        =====================================================================
        THIS RUNS WITH NO TENANT BOUND, AND THAT IS UNAVOIDABLE
        =====================================================================
            It answers "which organizations may this handset choose between?", which
            is by definition a cross-organization question asked before any
            organization has been chosen -- the exact analogue of listing a staff
            user's memberships at login.

            `guardians` IS RLS-protected, so this query returns nothing unless the
            caller has armed the cross-tenant read GUC. `auth_service` does that
            explicitly and narrowly, for this one lookup, having already verified the
            OTP -- see the comment at that call site. The result is filtered to this
            one identity, so no other person's records are reachable through it.
        """
        # AND AT LEAST ONE VIEWABLE CHILD. Three conditions, not two.
        #
        # A record with the portal switched on but no viewable child is not a context:
        # opening it shows an empty screen, and offering it in the picker asks a parent
        # to choose between schools that have nothing for them. The neighbour who may
        # collect a child but read nothing about them (`can_pickup` true,
        # `can_view_results` false) has exactly this shape, and must not be able to
        # sign in at all.
        viewable = select(GuardianStudent.guardian_id).where(
            GuardianStudent.guardian_id == Guardian.id,
            GuardianStudent.can_view_results.is_(True),
            GuardianStudent.deleted_at.is_(None),
        )
        stmt = (
            select(Guardian)
            .options(joinedload(Guardian.identity))
            .where(
                Guardian.identity_id == identity_id,
                Guardian.deleted_at.is_(None),
                Guardian.portal_enabled.is_(True),
                viewable.exists(),
            )
        )
        return (await self.session.execute(stmt)).unique().scalars().all()

    # -- OTP codes ----------------------------------------------------------

    async def latest_code(
        self, identity_id: UUID, purpose: GuardianOtpPurpose
    ) -> GuardianOtpCode | None:
        """The most recently issued code for this identity and purpose.

        NEWEST ONLY, not "any matching code". Verifying against every live code would
        mean an attacker who triggers ten sends gets ten simultaneous guesses at the
        same attempt budget. Issuing a new code implicitly retires the previous one.
        """
        stmt = (
            select(GuardianOtpCode)
            .where(
                GuardianOtpCode.identity_id == identity_id,
                GuardianOtpCode.purpose == purpose,
            )
            .order_by(GuardianOtpCode.created_at.desc())
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def codes_issued_since(self, identity_id: UUID, *, hours: int) -> int:
        """How many codes this identity has been sent recently -- the daily quota."""
        since = datetime.now(UTC) - timedelta(hours=hours)
        stmt = select(func.count(GuardianOtpCode.id)).where(
            GuardianOtpCode.identity_id == identity_id,
            GuardianOtpCode.created_at >= since,
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)

    async def add_code(self, code: GuardianOtpCode) -> GuardianOtpCode:
        self.session.add(code)
        await self.session.flush()
        return code
