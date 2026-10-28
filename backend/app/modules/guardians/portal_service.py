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
    * One child's attendance, fees and results are read through the SAME services
      the staff screens use (`AttendanceAnalyticsService`, `FeeService`,
      `ExamService`), so a parent and the office can never see two different
      percentages, balances or ranks for one child.

=============================================================================
EVERY PER-CHILD READ STARTS AT `_link`
=============================================================================
    The child is resolved through the portal's link filter first, and only its
    student id -- never the id from the URL -- is passed on. A child this parent is
    not linked to, or may only collect, is a 404 before any other table is read.

    The reads then run with the CHILD'S campus set as the request's school. A parent
    is org-level (their children may be at two campuses), but "which academic year
    is it" and "which challans" are campus questions, and the staff services answer
    them from the request's school when one is set.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date
from decimal import Decimal
from uuid import UUID

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import GuardianContext
from app.core.config import Settings, get_settings
from app.core.context import get_school_id, set_school_id
from app.core.exceptions import NotFoundError
from app.modules.attendance.analytics import AttendanceAnalyticsService
from app.modules.attendance.schemas import StudentAttendanceCalendar
from app.modules.exams.models import Exam, ExamMark, ExamPaper, ExamStatus
from app.modules.exams.schemas import ExamClassResults, ExamResultRow
from app.modules.exams.service import ExamService
from app.modules.fees.challan_pdf import render_challan_pdf
from app.modules.fees.models import FeeVoucher, VoucherStatus
from app.modules.fees.service import FeeService, display_status
from app.modules.guardians.models import Guardian, GuardianIdentity, GuardianStudent
from app.modules.guardians.repository import GuardianStudentRepository
from app.modules.guardians.schemas import (
    GuardianChildRead,
    GuardianProfile,
    PortalExamResult,
    PortalFeeStatement,
    PortalPaperResult,
    PortalVoucherRead,
)
from app.modules.tenancy.models import Organization, School

# What a parent may see of the challan register. A DRAFT is the office's working
# copy -- its amounts can still change and nobody has been asked to pay it. A VOID
# challan was cancelled; listing it invites a parent to pay a bill that no longer
# exists.
_PARENT_VISIBLE = (
    VoucherStatus.ISSUED,
    VoucherStatus.PARTLY_PAID,
    VoucherStatus.PAID,
    VoucherStatus.OVERDUE,
)

# Two years of monthly challans with room to spare. The totals are summed over every
# challan regardless, so an old unpaid one is never dropped from what is owed.
_MAX_VOUCHERS = 30


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
        link = await self._link(ctx, student_id)
        school = await self.session.get(School, link.school_id)
        return self._project(link, school.name if school else "School")

    # -- one child's records ----------------------------------------------------

    async def attendance(self, ctx: GuardianContext, student_id: str) -> StudentAttendanceCalendar:
        """The academic year so far, day by day, with a rate per month -- the same
        calendar the student's page shows staff. Submitted registers only."""
        link = await self._link(ctx, student_id)
        async with self._on_campus(link.school_id):
            return await AttendanceAnalyticsService(self.session).student_calendar(link.student_id)

    async def fees(self, ctx: GuardianContext, student_id: str) -> PortalFeeStatement:
        """The child's challans, newest first, and what is owed now."""
        link = await self._link(ctx, student_id)
        today = date.today()
        visible = and_(
            FeeVoucher.student_id == link.student_id, FeeVoucher.status.in_(_PARENT_VISIBLE)
        )
        owed = FeeVoucher.total - FeeVoucher.paid_total
        # Mirrors `display_status`: stamped overdue, or open and past its due date.
        overdue = or_(
            FeeVoucher.status == VoucherStatus.OVERDUE,
            and_(
                FeeVoucher.status.in_((VoucherStatus.ISSUED, VoucherStatus.PARTLY_PAID)),
                FeeVoucher.due_date < today,
            ),
        )
        async with self._on_campus(link.school_id):
            vouchers = (
                (
                    await self.session.execute(
                        select(FeeVoucher)
                        .where(visible)
                        .order_by(FeeVoucher.due_date.desc(), FeeVoucher.voucher_number.desc())
                        .limit(_MAX_VOUCHERS)
                    )
                )
                .scalars()
                .all()
            )
            outstanding_total, overdue_total = (
                await self.session.execute(
                    select(
                        func.coalesce(func.sum(owed), 0),
                        func.coalesce(func.sum(case((overdue, owed), else_=0)), 0),
                    ).where(visible)
                )
            ).one()

        currency = vouchers[0].currency if vouchers else await self._currency(ctx)
        return PortalFeeStatement(
            currency=currency,
            outstanding_total=Decimal(outstanding_total),
            overdue_total=Decimal(overdue_total),
            vouchers=[
                PortalVoucherRead(
                    id=voucher.id,
                    voucher_number=voucher.voucher_number,
                    academic_year=voucher.academic_year,
                    period_label=voucher.period_label,
                    issue_date=voucher.issue_date,
                    due_date=voucher.due_date,
                    status=display_status(voucher, today).value,
                    currency=voucher.currency,
                    total=voucher.total,
                    paid_total=voucher.paid_total,
                    outstanding=voucher.outstanding,
                )
                for voucher in vouchers
            ],
        )

    async def challan_pdf(
        self, ctx: GuardianContext, student_id: str, voucher_id: str
    ) -> tuple[bytes, str]:
        """The printable challan for one of the child's bills, to pay at the bank.

        The voucher must belong to THIS child and be one the statement lists; any
        other id -- another child's, a draft, a voided one -- is the same 404.
        Returns the PDF and the voucher number for the file name.
        """
        link = await self._link(ctx, student_id)
        target = _uuid_or_404(voucher_id, "Challan not found.")
        async with self._on_campus(link.school_id):
            voucher = await self.session.get(FeeVoucher, target)
            if (
                voucher is None
                or voucher.student_id != link.student_id
                or voucher.status not in _PARENT_VISIBLE
            ):
                raise NotFoundError("Challan not found.")
            context = await FeeService(self.session).challan_print_context([voucher.id])

        guardian = await self._guardian(ctx)
        payload = render_challan_pdf(
            context.vouchers,
            context.school,
            # Names who printed it, as the office copy does -- here, the parent.
            printed_by=f"{guardian.full_name} (parent portal)",
            printed_on=date.today(),
            roll_number=context.roll_number,
            late_fee=context.late_fee,
            logo=context.logo,
        )
        return payload, voucher.voucher_number

    async def results(self, ctx: GuardianContext, student_id: str) -> list[PortalExamResult]:
        """The child's result in every PUBLISHED exam they have marks in, newest first.

        A draft exam is the school still entering and checking marks; showing it
        would put provisional numbers in front of parents. Each result is cut from
        the class result sheet staff print (`ExamService.class_results`), so the
        percentage and rank match the report card.
        """
        link = await self._link(ctx, student_id)
        async with self._on_campus(link.school_id):
            marks = (
                await self.session.execute(
                    select(ExamMark, ExamPaper.exam_id, ExamPaper.class_id)
                    .join(ExamPaper, ExamPaper.id == ExamMark.paper_id)
                    .join(Exam, Exam.id == ExamPaper.exam_id)
                    .where(
                        ExamMark.student_id == link.student_id,
                        Exam.status == ExamStatus.PUBLISHED,
                        Exam.deleted_at.is_(None),
                    )
                )
            ).all()

            own: dict[UUID, ExamMark] = {}
            sittings: dict[UUID, UUID] = {}
            for mark, exam_id, class_id in marks:
                own[mark.paper_id] = mark
                sittings[exam_id] = class_id

            service = ExamService(self.session)
            results: list[tuple[Exam, PortalExamResult]] = []
            for exam_id, class_id in sittings.items():
                exam = await service.get_exam(exam_id)
                sheet = await service.class_results(exam_id, class_id)
                row = next((r for r in sheet.rows if r.student_id == link.student_id), None)
                results.append((exam, self._exam_result(exam, sheet, row, own)))

        # Newest first: an exam with no dates sorts by when it was created.
        results.sort(key=lambda pair: pair[0].start_date or pair[0].created_at.date(), reverse=True)
        return [result for _exam, result in results]

    # -- internals ----------------------------------------------------------

    async def _link(self, ctx: GuardianContext, student_id: str) -> GuardianStudent:
        """This guardian's portal link to one child, or 404. See the module docstring."""
        target = _uuid_or_404(student_id, "Child not found.")
        for link in await self.links.children_for_guardian_portal(ctx.guardian_id):
            if link.student_id == target:
                return link
        raise NotFoundError("Child not found.")

    @asynccontextmanager
    async def _on_campus(self, school_id: UUID) -> AsyncIterator[None]:
        """Run staff reads scoped to the child's campus, then restore the request's."""
        previous = get_school_id()
        set_school_id(school_id)
        try:
            yield
        finally:
            set_school_id(previous)

    async def _currency(self, ctx: GuardianContext) -> str:
        organization = await self.session.get(Organization, ctx.organization_id)
        return organization.currency if organization else "PKR"

    @staticmethod
    def _exam_result(
        exam: Exam,
        sheet: ExamClassResults,
        row: ExamResultRow | None,
        own: dict[UUID, ExamMark],
    ) -> PortalExamResult:
        papers = []
        obtained, counted = Decimal(0), 0
        for paper in sheet.papers:
            mark = own.get(paper.id)
            papers.append(
                PortalPaperResult(
                    subject_name=paper.subject_name,
                    max_marks=paper.max_marks,
                    pass_marks=paper.pass_marks,
                    marks_obtained=mark.marks_obtained if mark else None,
                    is_absent=mark.is_absent if mark else False,
                    marked=mark is not None,
                )
            )
            # The sheet's rule, for a child no longer on the class roster (`row` is
            # None): absent counts as 0 of the paper's max, unmarked does not count.
            if mark is not None:
                counted += paper.max_marks
                obtained += mark.marks_obtained or Decimal(0)

        if row is not None:
            obtained, counted, percentage = row.total_obtained, row.total_max, row.percentage
        else:
            percentage = (
                (obtained * 100 / counted).quantize(Decimal("0.01")) if counted else Decimal(0)
            )
        return PortalExamResult(
            exam_id=exam.id,
            exam_name=exam.name,
            start_date=exam.start_date,
            end_date=exam.end_date,
            class_name=sheet.class_name,
            papers=papers,
            total_obtained=obtained,
            total_max=counted,
            percentage=percentage,
            rank=row.rank if row is not None else None,
            class_size=len(sheet.rows) if row is not None else None,
        )

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


def _uuid_or_404(value: str, message: str) -> UUID:
    """A malformed id names nothing this parent can see: a 404, never a 422."""
    try:
        return UUID(value)
    except ValueError as exc:
        raise NotFoundError(message) from exc
