"""Fees data access. SQL only -- no business rules.

Organization isolation comes from PostgreSQL RLS. Campus isolation is a separate,
softer boundary: `BaseRepository` injects the active school into ordinary CRUD, and
every custom aggregate below applies the same predicate EXPLICITLY.

That explicitness is not ceremony. `_base_select()` cannot help a `select(func.sum())`
that never goes through it, and an unscoped aggregate is the exact bug that makes one
campus's collection dashboard include another campus's money -- inside the same
organization, where RLS is doing its job correctly and will not catch it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy import ColumnElement, Select, func, select
from sqlalchemy import case as sa_case
from sqlalchemy.orm import InstrumentedAttribute, selectinload

from app.common.repository import BaseRepository
from app.common.schemas import PageParams, SortParams
from app.core.context import get_school_id
from app.modules.academics.models import Section
from app.modules.fees.models import (
    FeeBillingSchedule,
    FeeConcession,
    FeeHead,
    FeeLineType,
    FeePayment,
    FeePaymentStatus,
    FeeStructure,
    FeeStructureItem,
    FeeStructureStatus,
    FeeVoucher,
    FeeVoucherItem,
    LateFeePolicy,
    LedgerEntryType,
    StationeryItem,
    StudentFeeAssignment,
    StudentLedgerEntry,
    VoucherOrigin,
    VoucherStatus,
)
from app.modules.students.models import Student, StudentStatus


def _scope[T: tuple[Any, ...]](stmt: Select[T], column: InstrumentedAttribute[UUID]) -> Select[T]:
    """Apply the active campus predicate to a hand-built statement.

    Mirrors `BaseRepository._school_scope_condition`: an organization-level principal
    has no active school and intentionally skips the filter so cross-campus reads
    remain possible. The value comes only from the verified access token's
    ContextVar -- a caller cannot widen it with a request parameter.
    """
    school_id = get_school_id()
    return stmt if school_id is None else stmt.where(column == school_id)


class FeeHeadRepository(BaseRepository[FeeHead]):
    model = FeeHead
    sortable_fields = frozenset({"code", "name", "sort_order", "created_at"})

    async def get_by_code(self, code: str) -> FeeHead | None:
        return await self.find_one(FeeHead.code == code)

    async def list_active(self) -> Sequence[FeeHead]:
        stmt = (
            self._base_select()
            .where(FeeHead.is_active.is_(True))
            .order_by(FeeHead.sort_order, FeeHead.name)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def structure_usage_count(self, head_id: UUID) -> int:
        """How many live structure lines price this head.

        Drives the refusal to delete a head that is still in use. Counts through
        `fee_structures` so a line belonging to a soft-deleted structure does not
        keep a head hostage forever.

        NOTE: this is only half the guard. A head also reaches a challan through
        `student_fee_assignments` when one student is individually put on the bus,
        and `StudentFeeAssignmentRepository.head_usage_count` covers that. The
        service adds the two -- see `FeeService.delete_head`.
        """
        stmt = (
            select(func.count())
            .select_from(FeeStructureItem)
            .join(FeeStructure, FeeStructure.id == FeeStructureItem.structure_id)
            .where(
                FeeStructureItem.head_id == head_id,
                FeeStructure.deleted_at.is_(None),
            )
        )
        scoped = _scope(stmt, FeeStructureItem.school_id)
        return int((await self.session.execute(scoped)).scalar_one() or 0)


class StationeryItemRepository(BaseRepository[StationeryItem]):
    """The sellable-article catalog. Mirrors `FeeHeadRepository` line for line,
    because the two tables play the same role at opposite ends of the pricing
    model -- a flat charge and a unit price."""

    model = StationeryItem
    sortable_fields = frozenset(
        {"code", "name", "category", "unit_price", "sort_order", "created_at"}
    )

    async def get_by_code(self, code: str) -> StationeryItem | None:
        return await self.find_one(StationeryItem.code == code)

    async def list_active(self) -> Sequence[StationeryItem]:
        stmt = (
            self._base_select()
            .where(StationeryItem.is_active.is_(True))
            .order_by(StationeryItem.category, StationeryItem.sort_order, StationeryItem.name)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def usage_count(self, item_id: UUID) -> int:
        """How many live lines -- structure or voucher -- charge this article.

        Counts BOTH tables, unlike `FeeHeadRepository.structure_usage_count`, which
        only has to check structures. A head reaches a challan solely through a
        structure, so guarding the structure guards everything; a stationery article
        can also be charged ad-hoc straight onto a draft voucher, and an article
        deleted out from under such a line would leave a challan naming a record that
        no longer exists.

        One round trip: two scalar subqueries in a single SELECT rather than two
        awaited statements, because this runs on the delete path of a screen where
        the operator is waiting.
        """
        structure_lines = (
            select(func.count())
            .select_from(FeeStructureItem)
            .join(FeeStructure, FeeStructure.id == FeeStructureItem.structure_id)
            .where(
                FeeStructureItem.stationery_item_id == item_id,
                FeeStructure.deleted_at.is_(None),
            )
        )
        voucher_lines = (
            select(func.count())
            .select_from(FeeVoucherItem)
            .where(FeeVoucherItem.stationery_item_id == item_id)
        )
        stmt = select(
            _scope(structure_lines, FeeStructureItem.school_id).scalar_subquery()
            + _scope(voucher_lines, FeeVoucherItem.school_id).scalar_subquery()
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)


class FeeStructureRepository(BaseRepository[FeeStructure]):
    model = FeeStructure
    sortable_fields = frozenset({"name", "academic_year", "status", "created_at"})

    async def get_with_items(self, structure_id: UUID) -> FeeStructure | None:
        """Load a structure and its lines in one round trip.

        `selectinload` rather than `joinedload`: the parent row is not multiplied by
        its children, so the totals computed off `structure.items` cannot double-count
        -- the classic cartesian-join bug in a money path.
        """
        stmt = (
            self._base_select()
            .where(FeeStructure.id == structure_id)
            .options(
                selectinload(FeeStructure.items).selectinload(FeeStructureItem.head),
                selectinload(FeeStructure.items).selectinload(FeeStructureItem.stationery_item),
            )
        )
        return (await self.session.execute(stmt)).scalars().unique().one_or_none()

    async def get_for_class_year(self, class_id: UUID, academic_year: str) -> FeeStructure | None:
        return await self.find_one(
            FeeStructure.class_id == class_id,
            FeeStructure.academic_year == academic_year,
        )

    async def list_active_for_year(self, academic_year: str) -> Sequence[FeeStructure]:
        """Every structure that may bill, for one year at this campus.

        THE UNATTENDED RUN'S WHOLE TARGET LIST, and it is deliberately derived rather
        than configured. A school that adds Grade 9 in October gets Grade 9 billed in
        October without anyone remembering to add it to a list of classes -- and the
        class whose structure is still a DRAFT is left alone, because a draft is a
        price nobody has agreed yet.

        Ordered by class so the job's log reads in the same order as the screen.
        """
        stmt = (
            self._base_select()
            .where(
                FeeStructure.academic_year == academic_year,
                FeeStructure.status == FeeStructureStatus.ACTIVE,
            )
            .order_by(FeeStructure.name)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def draft_voucher_count(self, structure_id: UUID) -> int:
        """Vouchers still in DRAFT for this structure -- archiving is refused while
        any exist, so no challan is orphaned mid-flight."""
        stmt = (
            select(func.count())
            .select_from(FeeVoucher)
            .where(
                FeeVoucher.structure_id == structure_id,
                FeeVoucher.status == VoucherStatus.DRAFT,
            )
        )
        scoped = _scope(stmt, FeeVoucher.school_id)
        return int((await self.session.execute(scoped)).scalar_one() or 0)


class FeeStructureItemRepository(BaseRepository[FeeStructureItem]):
    model = FeeStructureItem
    sortable_fields = frozenset({"created_at"})

    async def get_for_structure(self, structure_id: UUID, head_id: UUID) -> FeeStructureItem | None:
        return await self.find_one(
            FeeStructureItem.structure_id == structure_id,
            FeeStructureItem.head_id == head_id,
        )

    async def get_stationery_for_structure(
        self, structure_id: UUID, stationery_item_id: UUID
    ) -> FeeStructureItem | None:
        """The stationery counterpart of `get_for_structure`.

        Separate rather than a nullable-column branch inside one method: the two
        lookups hit two different partial unique indexes, and a single method taking
        `head_id: UUID | None, stationery_item_id: UUID | None` would be one
        `if` away from silently matching every stationery line when handed two Nones.
        """
        return await self.find_one(
            FeeStructureItem.structure_id == structure_id,
            FeeStructureItem.stationery_item_id == stationery_item_id,
        )

    async def list_for_structure(self, structure_id: UUID) -> Sequence[FeeStructureItem]:
        stmt = (
            self._base_select()
            .where(FeeStructureItem.structure_id == structure_id)
            .options(
                selectinload(FeeStructureItem.head),
                selectinload(FeeStructureItem.stationery_item),
            )
            .order_by(FeeStructureItem.created_at)
        )
        return (await self.session.execute(stmt)).scalars().all()


class StudentFeeAssignmentRepository(BaseRepository[StudentFeeAssignment]):
    """Per-student departures from the class structure."""

    model = StudentFeeAssignment
    sortable_fields = frozenset({"academic_year", "mode", "created_at"})

    async def list_for_student(
        self, student_id: UUID, academic_year: str
    ) -> Sequence[StudentFeeAssignment]:
        stmt = (
            self._base_select()
            .where(
                StudentFeeAssignment.student_id == student_id,
                StudentFeeAssignment.academic_year == academic_year,
            )
            .options(
                selectinload(StudentFeeAssignment.head),
                selectinload(StudentFeeAssignment.concession),
            )
            .order_by(StudentFeeAssignment.created_at)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def get_for_student(
        self, student_id: UUID, academic_year: str, head_id: UUID
    ) -> StudentFeeAssignment | None:
        return await self.find_one(
            StudentFeeAssignment.student_id == student_id,
            StudentFeeAssignment.academic_year == academic_year,
            StudentFeeAssignment.head_id == head_id,
        )

    async def for_students(
        self, student_ids: Sequence[UUID], academic_year: str
    ) -> dict[UUID, list[StudentFeeAssignment]]:
        """Every assignment for a whole billing run, grouped by student.

        ONE QUERY FOR THE BATCH, and that is the entire reason this method exists
        rather than a per-student call inside the generation loop. A run bills up to
        500 students; asking per student would add 500 round trips to the hottest
        write path in the module, and the cost would grow with exactly the thing that
        makes a customer valuable -- the size of their school.

        `selectinload` on the head because the generated voucher line snapshots the
        head's NAME, and resolving it lazily inside the loop would reintroduce the
        N+1 through the back door. The concession comes with it for the same reason:
        a DISCOUNT row reads its RATE from the scheme, so a lazy load there would be
        one round trip per scholarship in the class.
        """
        if not student_ids:
            return {}
        stmt = (
            self._base_select()
            .where(
                StudentFeeAssignment.student_id.in_(student_ids),
                StudentFeeAssignment.academic_year == academic_year,
            )
            .options(
                selectinload(StudentFeeAssignment.head),
                selectinload(StudentFeeAssignment.concession),
            )
        )
        rows = (await self.session.execute(stmt)).scalars().all()

        grouped: dict[UUID, list[StudentFeeAssignment]] = {}
        for row in rows:
            grouped.setdefault(row.student_id, []).append(row)
        return grouped

    async def head_usage_count(self, head_id: UUID) -> int:
        """How many live student assignments reference this head.

        Feeds the refusal to delete a head. Without it, tidying "Transport" out of
        the head list would silently stop billing every student individually put on
        the bus -- a deletion whose damage is invisible until the money does not
        arrive.
        """
        stmt = (
            select(func.count())
            .select_from(StudentFeeAssignment)
            .where(
                StudentFeeAssignment.head_id == head_id,
                StudentFeeAssignment.deleted_at.is_(None),
            )
        )
        scoped = _scope(stmt, StudentFeeAssignment.school_id)
        return int((await self.session.execute(scoped)).scalar_one() or 0)

    async def concession_usage_count(self, concession_id: UUID) -> int:
        """How many live students are on this scheme.

        Drives the refusal to delete a concession, and the count is REPORTED in the
        refusal. "In use" is a message an operator argues with; "37 students are on
        this scheme" is one they act on.
        """
        stmt = (
            select(func.count())
            .select_from(StudentFeeAssignment)
            .where(
                StudentFeeAssignment.concession_id == concession_id,
                StudentFeeAssignment.deleted_at.is_(None),
            )
        )
        scoped = _scope(stmt, StudentFeeAssignment.school_id)
        return int((await self.session.execute(scoped)).scalar_one() or 0)


class StudentDuesRow(NamedTuple):
    """What one student owes, split by whether it is late.

    `overdue` is carried ALONGSIDE `amount` rather than being a second query, because
    the caller needs both at once: the fee list is colour-coded by whether any of the
    balance is past due, and under the `pending` filter a row can be either. A boolean
    would have been enough for the colour, but the split figure also answers "how much
    of this is actually late", which is the number an office negotiates with.
    """

    amount: Decimal
    """Everything outstanding that the query selected."""

    overdue: Decimal
    """The portion of `amount` whose due date has passed. Zero means owed but not late."""

    periods: list[str]
    currency: str


class FeeVoucherRepository(BaseRepository[FeeVoucher]):
    model = FeeVoucher
    sortable_fields = frozenset(
        {"voucher_number", "issue_date", "due_date", "status", "total", "created_at"}
    )

    async def list_with_students(
        self,
        *conditions: ColumnElement[bool],
        params: PageParams | None = None,
        sort: SortParams | None = None,
    ) -> tuple[Sequence[FeeVoucher], int]:
        """`list()`, plus the student on every row.

        The register is read by a person looking for a NAME. A voucher number and a
        student UUID are not something anyone can act on, and resolving the names
        client-side would be one request per row. `selectinload` keeps it to a second
        query for the whole page rather than a join that multiplies nothing.
        """
        params = params or PageParams()
        stmt = self._base_select().options(selectinload(FeeVoucher.student)).where(*conditions)
        stmt = self.apply_sort(stmt, sort).offset(params.offset).limit(params.limit)
        rows = (await self.session.execute(stmt)).scalars().unique().all()
        return rows, await self.count(*conditions)

    async def get_detail(self, voucher_id: UUID) -> FeeVoucher | None:
        stmt = (
            self._base_select()
            .where(FeeVoucher.id == voucher_id)
            .options(
                selectinload(FeeVoucher.items),
                selectinload(FeeVoucher.payments),
                selectinload(FeeVoucher.student),
            )
        )
        return (await self.session.execute(stmt)).scalars().unique().one_or_none()

    async def list_for_print(self, voucher_ids: Sequence[UUID]) -> Sequence[FeeVoucher]:
        """The vouchers behind one printed challan, with everything the renderer reads.

        The renderer is a pure function and walks `student.section.school_class` to
        print the class and section band. A lazy load from inside it would emit SQL
        halfway through a PDF -- on an async session, an error rather than a slow
        page -- so the chain is loaded here, once, for the whole set.

        Scoped like every other read: RLS contains the organization and
        `_base_select` the campus, so a foreign id simply does not come back and the
        caller sees a short list rather than someone else's child.
        """
        if not voucher_ids:
            return []
        stmt = (
            self._base_select()
            .where(FeeVoucher.id.in_(voucher_ids))
            .options(
                selectinload(FeeVoucher.items),
                selectinload(FeeVoucher.student)
                .selectinload(Student.section)
                .selectinload(Section.school_class),
            )
        )
        return (await self.session.execute(stmt)).scalars().unique().all()

    async def existing_period_student_ids(
        self, student_ids: Sequence[UUID], academic_year: str, period_label: str
    ) -> set[UUID]:
        """Which of these students already hold a non-void voucher for the period.

        ONE query for the whole batch, not one per student: generation runs over a
        class of several hundred, and a per-student existence check is an N+1 that
        grows exactly with the size of the school.

        Mirrors the partial unique index in the migration. The index is the real
        guarantee -- this read exists so the run can SKIP those students with a
        reason instead of dying on an IntegrityError halfway through.
        """
        if not student_ids:
            return set()
        stmt = select(FeeVoucher.student_id).where(
            FeeVoucher.student_id.in_(student_ids),
            FeeVoucher.academic_year == academic_year,
            FeeVoucher.period_label == period_label,
            FeeVoucher.status != VoucherStatus.VOID,
        )
        rows = (await self.session.execute(_scope(stmt, FeeVoucher.school_id))).scalars().all()
        return set(rows)

    async def eligible_students(
        self,
        class_id: UUID,
        *,
        section_id: UUID | None = None,
        student_ids: Sequence[UUID] | None = None,
        limit: int,
    ) -> Sequence[Student]:
        """Active students of a class, for a generation run.

        Joined through `sections` because a student's placement is a section, while a
        fee structure is priced per class. Only ACTIVE students are billed: a PENDING
        applicant has not enrolled, and a GRADUATED or TRANSFERRED student has left.
        Billing either is a phone call from an angry parent.
        """
        from app.modules.academics.models import Section

        stmt = (
            select(Student)
            .join(Section, Section.id == Student.section_id)
            .where(
                Section.class_id == class_id,
                Student.status == StudentStatus.ACTIVE,
                Student.deleted_at.is_(None),
                Section.deleted_at.is_(None),
            )
        )
        if section_id is not None:
            stmt = stmt.where(Student.section_id == section_id)
        if student_ids is not None:
            stmt = stmt.where(Student.id.in_(student_ids))

        # Both tables scoped: the student must be at this campus AND the section must
        # be, so a re-parented section can never drag a foreign student into the run.
        stmt = _scope(_scope(stmt, Student.school_id), Section.school_id)
        stmt = stmt.order_by(Student.admission_number).limit(limit)
        return (await self.session.execute(stmt)).scalars().all()

    async def absorbable_for_students(
        self, student_ids: Sequence[UUID]
    ) -> dict[UUID, list[FeeVoucher]]:
        """Unpaid challans a new one may absorb, for a whole batch in ONE query.

        =================================================================
        THE FOUR CONDITIONS ARE EACH A WAY OF NOT DOUBLE-BILLING A FAMILY
        =================================================================
            `status IN (issued, overdue)`
                A DRAFT is not a bill and has never been on anybody's balance, so
                there is nothing to carry; absorbing one would bill money the school
                never asked for. A PAID one is settled, and a VOID one was cancelled.

            `paid_total = 0`
                A challan that has taken part payment is NEVER absorbed. Cancelling
                it would orphan the receipt pointing at it -- which `void_voucher`
                refuses outright, and rightly: that is how a cash shortfall gets
                papered over. Its remaining balance keeps its own document.

            `superseded_by_voucher_id IS NULL`
                Already reserved by another consolidating challan. Two runs absorbing
                the same arrears would each bill it, which is the exact failure this
                whole mechanism exists to prevent, reached from the other direction.

            ONE QUERY, not one per student. A generation run covers several hundred
            students on the hottest write path in the module.

        Oldest first, so the arrears line reads in the order the debts were incurred.
        """
        if not student_ids:
            return {}
        stmt = (
            select(FeeVoucher)
            .where(
                FeeVoucher.student_id.in_(student_ids),
                FeeVoucher.status.in_((VoucherStatus.ISSUED, VoucherStatus.OVERDUE)),
                FeeVoucher.paid_total == 0,
                FeeVoucher.superseded_by_voucher_id.is_(None),
            )
            .order_by(FeeVoucher.issue_date, FeeVoucher.voucher_number)
        )
        rows = (await self.session.execute(_scope(stmt, FeeVoucher.school_id))).scalars().all()
        grouped: dict[UUID, list[FeeVoucher]] = {}
        for voucher in rows:
            grouped.setdefault(voucher.student_id, []).append(voucher)
        return grouped

    async def reserved_by(self, voucher_id: UUID) -> Sequence[FeeVoucher]:
        """The challans a consolidating voucher has reserved but not yet cancelled.

        Read at ISSUE time, which is the only moment the cancellation actually
        happens -- see `FeeVoucher.superseded_by_voucher_id`. Re-read rather than
        remembered from generation, because a reserved challan may have taken a
        payment in between and must then be released instead of voided.
        """
        stmt = (
            select(FeeVoucher)
            .where(FeeVoucher.superseded_by_voucher_id == voucher_id)
            .order_by(FeeVoucher.issue_date, FeeVoucher.voucher_number)
        )
        return (await self.session.execute(_scope(stmt, FeeVoucher.school_id))).scalars().all()

    async def next_sequence(self, prefix: str) -> int:
        """First unused sequence number for `prefix` within the active school.

        Counts existing rows and adds one, exactly like `next_admission_number` in the
        students module. This RACES under concurrent generation runs, and that is
        acceptable because the real guarantee is the
        `uq_fee_vouchers_school_id_voucher_number` constraint: a collision surfaces as
        a 409 from the IntegrityError handler rather than two challans quietly sharing
        a number.
        """
        stmt = (
            select(func.count())
            .select_from(FeeVoucher)
            .where(FeeVoucher.voucher_number.startswith(prefix))
        )
        scoped = _scope(stmt, FeeVoucher.school_id)
        used = int((await self.session.execute(scoped)).scalar_one() or 0)
        return used + 1

    async def summary_rows(
        self, academic_year: str, period_label: str | None
    ) -> Sequence[tuple[VoucherStatus, int, Decimal, Decimal]]:
        """Per-status counts and money for the collection dashboard.

        ONE grouped query for the whole board. The alternative -- a count and two sums
        per status -- is six round trips for a screen a bursar refreshes all morning.
        """
        stmt = (
            select(
                FeeVoucher.status,
                func.count(FeeVoucher.id),
                func.coalesce(func.sum(FeeVoucher.total), 0),
                func.coalesce(func.sum(FeeVoucher.paid_total), 0),
            )
            .where(FeeVoucher.academic_year == academic_year)
            .group_by(FeeVoucher.status)
        )
        if period_label is not None:
            stmt = stmt.where(FeeVoucher.period_label == period_label)
        rows = (await self.session.execute(_scope(stmt, FeeVoucher.school_id))).all()
        return [
            (status, int(count), Decimal(total), Decimal(paid))
            for status, count, total, paid in rows
        ]

    async def stationery_billed_total(
        self, academic_year: str, period_label: str | None
    ) -> Decimal:
        """How much of the period's billing is stationery rather than fees.

        Joined from the LINES up to their vouchers, because the split does not exist
        anywhere else -- a voucher's `total` is one number and knows nothing about
        what kind of lines produced it.

        VOID and DRAFT are excluded here for the same reason `summary()` excludes
        them from `billed`: a cancelled bill is not owed and an unsent one has not
        been charged. Reporting a stationery figure computed over a different row set
        than the total it is a part of is how a dashboard ends up showing a component
        larger than its whole.
        """
        stmt = (
            select(
                func.coalesce(func.sum(FeeVoucherItem.amount - FeeVoucherItem.discount_amount), 0)
            )
            .select_from(FeeVoucherItem)
            .join(FeeVoucher, FeeVoucher.id == FeeVoucherItem.voucher_id)
            .where(
                FeeVoucherItem.line_type == FeeLineType.STATIONERY,
                FeeVoucher.academic_year == academic_year,
                FeeVoucher.status.notin_([VoucherStatus.VOID, VoucherStatus.DRAFT]),
            )
        )
        if period_label is not None:
            stmt = stmt.where(FeeVoucher.period_label == period_label)
        scoped = _scope(stmt, FeeVoucher.school_id)
        return Decimal((await self.session.execute(scoped)).scalar_one() or 0)

    async def overdue_total(
        self, academic_year: str, period_label: str | None, today: date
    ) -> Decimal:
        """Outstanding money whose due date has passed.

        Computed rather than read off a stored OVERDUE status, so the figure is right
        even though no job has swept the table yet -- see `VoucherStatus.OVERDUE`.
        """
        stmt = select(func.coalesce(func.sum(FeeVoucher.total - FeeVoucher.paid_total), 0)).where(
            FeeVoucher.academic_year == academic_year,
            FeeVoucher.due_date < today,
            FeeVoucher.total > FeeVoucher.paid_total,
            FeeVoucher.status.notin_([VoucherStatus.VOID, VoucherStatus.DRAFT]),
        )
        if period_label is not None:
            stmt = stmt.where(FeeVoucher.period_label == period_label)
        scoped = _scope(stmt, FeeVoucher.school_id)
        return Decimal((await self.session.execute(scoped)).scalar_one() or 0)

    def students_owing(self, *, due_before: date | None = None) -> Select[tuple[UUID]]:
        """Ids of students who still owe money -- a SELECT, not a result set.

        Returned unexecuted so the students module can drop it into
        `Student.id.in_(...)` and let PostgreSQL do the filtering. Fetching the ids
        and passing a Python list would break down exactly when it matters: a school
        with two thousand defaulters would send two thousand UUIDs back into the next
        query, and the page count would be computed against a list that had already
        been truncated somewhere.

        WHAT COUNTS AS OWING -- the same three rules as `overdue_candidates`, and for
        the same reasons:

          * DRAFT is NOT owing. Nobody has been asked to pay it yet. A parent shown
            on a defaulters list for a challan that never left the office has a
            complaint the school cannot answer.
          * VOID is not owing. The school cancelled it.
          * `total > paid_total` is the test, NOT `status`. OVERDUE is derived on read
            in this module, so a challan settled this morning may still be carrying
            yesterday's stored status -- filtering on the status column would keep
            listing a family that has already paid.

        Fines ARE included here, unlike in `overdue_candidates`. That method asks
        "what may be fined", where a fine must be excluded so penalties cannot
        compound; this one asks "who owes the school money", and an unpaid fine is
        money owed like any other.

        `due_before` narrows it to genuinely LATE money -- pass today's date for the
        overdue subset. Left as None, any outstanding balance counts, including a
        challan issued this morning and not yet due.
        """
        stmt = select(FeeVoucher.student_id).where(
            FeeVoucher.total > FeeVoucher.paid_total,
            FeeVoucher.status.notin_([VoucherStatus.VOID, VoucherStatus.DRAFT]),
        )
        # The same campus scope `_base_select` injects. RLS supplies the organization
        # boundary but cannot supply this one, because an org-level principal
        # legitimately spans campuses -- so without it, a principal viewing one campus
        # would filter its students against another campus's unpaid challans.
        if (school_scope := self._school_scope_condition()) is not None:
            stmt = stmt.where(school_scope)
        if due_before is not None:
            stmt = stmt.where(FeeVoucher.due_date < due_before)
        # DISTINCT because a student with three unpaid challans is one defaulter, not
        # three. Harmless inside IN(), but this select is a building block and the
        # next caller may COUNT it.
        return stmt.distinct()

    async def dues_by_student(
        self, student_ids: set[UUID], *, due_before: date | None = None
    ) -> dict[UUID, StudentDuesRow]:
        """What each of these students owes, split into total and the late portion.

        Scoped to the ids ALREADY ON THE PAGE, so the cost is bounded by page size
        rather than by how many defaulters the school has. The students list resolves
        its rows first and asks this second; asking it to aggregate the whole school
        would do work for two thousand families to print twenty.

        The predicates match `students_owing` exactly -- same exclusions, same
        `due_before`. They have to: the amount is what the FILTER selected, so a row
        that appears under `fees=overdue` showing its full balance rather than its
        late balance would contradict the list it is on.

        Summed in Python rather than with GROUP BY because the period labels have to
        come back too, ordered oldest-debt-first, and a grouped query would need an
        array aggregate to carry them. One query either way.
        """
        if not student_ids:
            return {}

        stmt = select(
            FeeVoucher.student_id,
            FeeVoucher.period_label,
            FeeVoucher.currency,
            FeeVoucher.due_date,
            (FeeVoucher.total - FeeVoucher.paid_total).label("outstanding"),
        ).where(
            FeeVoucher.student_id.in_(student_ids),
            FeeVoucher.total > FeeVoucher.paid_total,
            FeeVoucher.status.notin_([VoucherStatus.VOID, VoucherStatus.DRAFT]),
        )
        if (school_scope := self._school_scope_condition()) is not None:
            stmt = stmt.where(school_scope)
        if due_before is not None:
            stmt = stmt.where(FeeVoucher.due_date < due_before)
        # Oldest debt first: the period a parent is furthest behind on is the one the
        # office opens the conversation with.
        stmt = stmt.order_by(FeeVoucher.due_date, FeeVoucher.period_label)

        # `today`, not `due_before`. Under the overdue filter they coincide, but under
        # `pending` the cutoff is None while individual challans may still be late --
        # and those are exactly the rows the list needs to mark. Reading it from the
        # clock here keeps "is this late" answered once, consistently for every row.
        today = date.today()

        totals: dict[UUID, StudentDuesRow] = {}
        for student_id, period, currency, due_date, outstanding in await self.session.execute(stmt):
            row = totals.get(student_id) or StudentDuesRow(Decimal("0"), Decimal("0"), [], currency)
            # A school billing one period across two challans (a reissue, a fine) must
            # not print the month twice.
            if period not in row.periods:
                row.periods.append(period)
            totals[student_id] = row._replace(
                amount=row.amount + outstanding,
                overdue=row.overdue + (outstanding if due_date < today else Decimal("0")),
            )
        return totals

    async def overdue_candidates(
        self, academic_year: str, due_before: date, *, limit: int
    ) -> Sequence[FeeVoucher]:
        """Issued challans past their due date that still owe money.

        WHAT IT DELIBERATELY EXCLUDES, and why each one would be a bug:

          * DRAFT -- never reached the parent. Fining a bill nobody was sent is
            indefensible at the counter and the school cannot win the argument.
          * VOID -- the school already cancelled it.
          * Fully paid -- `total > paid_total` is the test, not the stored status,
            because OVERDUE is derived on read in this module and a challan settled
            this morning may still carry yesterday's status.
          * LATE_FEE origin -- a fine is not itself finable. Without this the policy
            compounds: the fine goes overdue, earns a fine, and a 200 rupee penalty
            becomes four figures while nobody is watching.

        Ordered by due date so the oldest delinquency is assessed first when a run
        hits `limit`, which is what makes a truncated run's remainder predictable.
        """
        stmt = (
            self._base_select()
            .where(
                FeeVoucher.academic_year == academic_year,
                # `due_before` is the due date the caller wants to look BACK from --
                # the policy's grace period has already been subtracted by the
                # service, so a challan inside its grace window never appears here.
                FeeVoucher.due_date < due_before,
                FeeVoucher.total > FeeVoucher.paid_total,
                FeeVoucher.status.notin_([VoucherStatus.VOID, VoucherStatus.DRAFT]),
                FeeVoucher.origin == VoucherOrigin.REGULAR,
            )
            .options(selectinload(FeeVoucher.student))
            .order_by(FeeVoucher.due_date, FeeVoucher.voucher_number)
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def fines_for_source(self, source_voucher_id: UUID) -> tuple[int, Decimal]:
        """How many fines this challan has already earned, and their total.

        Both halves are load-bearing for a recurring policy: the COUNT stops a weekly
        rule fining the same week twice after a re-run, and the TOTAL is what
        `max_amount` is measured against. Voided fines are excluded from the money
        but still counted -- a fine the school cancelled should not be silently
        re-levied by the next run, which is precisely what an operator who voided it
        was trying to prevent.
        """
        stmt = select(
            func.count(FeeVoucher.id),
            func.coalesce(
                func.sum(
                    func.coalesce(
                        sa_case(
                            (FeeVoucher.status == VoucherStatus.VOID, 0),
                            else_=FeeVoucher.total,
                        ),
                        0,
                    )
                ),
                0,
            ),
        ).where(FeeVoucher.source_voucher_id == source_voucher_id)
        row = (await self.session.execute(_scope(stmt, FeeVoucher.school_id))).one()
        return int(row[0] or 0), Decimal(row[1] or 0)

    async def export_rows(
        self,
        *conditions: ColumnElement[bool],
        limit: int,
    ) -> Sequence[FeeVoucher]:
        """The voucher register, student loaded, for a CSV download.

        Capped rather than unbounded. An export is the one read in this module a user
        can aim at every row a school has ever produced, and streaming a million of
        them out of one request holds a connection open long enough to matter. The
        cap is REPORTED in the file's trailer, never applied silently.
        """
        stmt = (
            self._base_select()
            .where(*conditions)
            .options(selectinload(FeeVoucher.student))
            .order_by(FeeVoucher.issue_date, FeeVoucher.voucher_number)
            .limit(limit)
        )
        return (await self.session.execute(stmt)).scalars().all()


class FeeVoucherItemRepository(BaseRepository[FeeVoucherItem]):
    model = FeeVoucherItem
    sortable_fields = frozenset({"sort_order"})

    async def get_stationery_line(
        self, voucher_id: UUID, stationery_item_id: UUID
    ) -> FeeVoucherItem | None:
        """The existing line for this article on this challan, if any.

        What makes charging an article idempotent: a second call SETS the quantity on
        the line already there instead of adding "Copy x 2" underneath "Copy x 3".
        """
        return await self.find_one(
            FeeVoucherItem.voucher_id == voucher_id,
            FeeVoucherItem.stationery_item_id == stationery_item_id,
        )

    async def get_fee_line(self, voucher_id: UUID, head_id: UUID) -> FeeVoucherItem | None:
        """The existing FEE line for this head on this challan, if any.

        The mirror of `get_stationery_line`, and it exists for the same reason: a
        one-off charge (a fine, a re-exam fee, a broken window) posted twice must SET
        the line rather than add a second one reading "Breakage" beneath "Breakage".
        The partial unique index on `(voucher_id, head_id)` enforces the same thing at
        the storage layer, so a concurrent double-submit is a 409 rather than a
        duplicate.
        """
        return await self.find_one(
            FeeVoucherItem.voucher_id == voucher_id,
            FeeVoucherItem.head_id == head_id,
        )

    async def line_totals(self, voucher_id: UUID) -> tuple[Decimal, Decimal]:
        """`(subtotal, discount_total)` summed across every line of a challan.

        The single source of truth for the two figures materialised on the voucher,
        recomputed from the lines on every change for exactly the reason
        `FeePaymentRepository.effective_total` is recomputed rather than incremented:
        a cache that is only ever adjusted eventually disagrees with what justifies
        it, and here that means a challan whose total is not the sum of its own
        printed lines.
        """
        stmt = select(
            func.coalesce(func.sum(FeeVoucherItem.amount), 0),
            func.coalesce(func.sum(FeeVoucherItem.discount_amount), 0),
        ).where(FeeVoucherItem.voucher_id == voucher_id)
        row = (await self.session.execute(_scope(stmt, FeeVoucherItem.school_id))).one()
        return Decimal(row[0]), Decimal(row[1])

    async def max_sort_order(self, voucher_id: UUID) -> int:
        """Where the next ad-hoc line goes: after everything already on the challan,
        so adding a charge never reshuffles the lines above it."""
        stmt = select(func.coalesce(func.max(FeeVoucherItem.sort_order), 0)).where(
            FeeVoucherItem.voucher_id == voucher_id
        )
        scoped = _scope(stmt, FeeVoucherItem.school_id)
        return int((await self.session.execute(scoped)).scalar_one())


class FeePaymentRepository(BaseRepository[FeePayment]):
    model = FeePayment
    sortable_fields = frozenset({"receipt_number", "received_on", "amount", "created_at"})

    async def list_for_voucher(self, voucher_id: UUID) -> Sequence[FeePayment]:
        stmt = (
            self._base_select()
            .where(FeePayment.voucher_id == voucher_id)
            .order_by(FeePayment.created_at)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def effective_total(self, voucher_id: UUID) -> Decimal:
        """Sum of non-reversed payments against one voucher.

        The single source of truth for `FeeVoucher.paid_total`, which is materialised
        for list performance. Recomputed from the payment rows on every change rather
        than incremented, so a reversal and a payment cannot drift the cached figure
        away from the receipts that justify it.
        """
        stmt = select(func.coalesce(func.sum(FeePayment.amount), 0)).where(
            FeePayment.voucher_id == voucher_id,
            FeePayment.status == FeePaymentStatus.RECORDED,
        )
        scoped = _scope(stmt, FeePayment.school_id)
        return Decimal((await self.session.execute(scoped)).scalar_one() or 0)

    async def next_sequence(self, prefix: str) -> int:
        """First unused receipt sequence for `prefix`. Same race note as vouchers --
        `uq_fee_payments_school_id_receipt_number` is the real guarantee."""
        stmt = (
            select(func.count())
            .select_from(FeePayment)
            .where(FeePayment.receipt_number.startswith(prefix))
        )
        scoped = _scope(stmt, FeePayment.school_id)
        used = int((await self.session.execute(scoped)).scalar_one() or 0)
        return used + 1


class FeeConcessionRepository(BaseRepository[FeeConcession]):
    """The named scholarship catalog. Shaped like `FeeHeadRepository`, because it
    plays the same role at the other end of the arithmetic -- one names what may be
    charged, the other what may be taken off."""

    model = FeeConcession
    sortable_fields = frozenset({"code", "name", "kind", "value", "sort_order", "created_at"})

    async def get_by_code(self, code: str) -> FeeConcession | None:
        return await self.find_one(FeeConcession.code == code)

    async def list_active(self) -> Sequence[FeeConcession]:
        stmt = (
            self._base_select()
            .where(FeeConcession.is_active.is_(True))
            .order_by(FeeConcession.sort_order, FeeConcession.name)
        )
        return (await self.session.execute(stmt)).scalars().all()


class LateFeePolicyRepository(BaseRepository[LateFeePolicy]):
    model = LateFeePolicy
    sortable_fields = frozenset({"academic_year", "name", "created_at"})

    async def get_active(self, academic_year: str) -> LateFeePolicy | None:
        """The one live rule for this school-year, head loaded.

        Singular by construction: `uq_fee_late_fee_policies_one_active` is a partial
        unique index, so there cannot be two. Reading it as one row rather than a list
        is what keeps the job from having to pick, and a job that picks between two
        fine policies is a job whose output depends on planner order.
        """
        stmt = (
            self._base_select()
            .where(
                LateFeePolicy.academic_year == academic_year,
                LateFeePolicy.is_active.is_(True),
            )
            .options(selectinload(LateFeePolicy.head))
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_for_year(self, academic_year: str | None) -> Sequence[LateFeePolicy]:
        stmt = self._base_select().options(selectinload(LateFeePolicy.head))
        if academic_year is not None:
            stmt = stmt.where(LateFeePolicy.academic_year == academic_year)
        stmt = stmt.order_by(LateFeePolicy.academic_year.desc(), LateFeePolicy.name)
        return (await self.session.execute(stmt)).scalars().all()

    async def head_usage_count(self, head_id: UUID) -> int:
        """How many live policies bill fines under this head.

        The third arm of the guard on deleting a fee head, beside structure lines and
        student assignments. Deleting the head a fine policy points at would break
        the job silently -- at 2am, in a scheduled run nobody is reading the logs of.
        """
        stmt = (
            select(func.count())
            .select_from(LateFeePolicy)
            .where(LateFeePolicy.head_id == head_id, LateFeePolicy.deleted_at.is_(None))
        )
        scoped = _scope(stmt, LateFeePolicy.school_id)
        return int((await self.session.execute(scoped)).scalar_one() or 0)


class FeeBillingScheduleRepository(BaseRepository[FeeBillingSchedule]):
    """When a campus bills without being asked."""

    model = FeeBillingSchedule
    sortable_fields = frozenset({"academic_year", "generate_day", "created_at"})

    async def get_active(self, academic_year: str) -> FeeBillingSchedule | None:
        """The one live schedule for this campus-year.

        Singular by construction: `uq_fee_billing_schedules_one_active` is a partial
        unique index, so there cannot be two. Reading it as one row rather than a list
        is what keeps the job from having to pick between them -- and a job that picks
        between two billing days bills on whichever day the planner happened to
        return first.
        """
        stmt = self._base_select().where(
            FeeBillingSchedule.academic_year == academic_year,
            FeeBillingSchedule.is_active.is_(True),
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def get_for_year(self, academic_year: str) -> FeeBillingSchedule | None:
        """The schedule for the year whether or not it is switched on.

        The settings screen needs the PAUSED row too: an owner who turned automation
        off in March expects their day-of-month back when they turn it on again, not
        an empty form.
        """
        stmt = (
            self._base_select()
            .where(FeeBillingSchedule.academic_year == academic_year)
            .order_by(FeeBillingSchedule.is_active.desc(), FeeBillingSchedule.created_at.desc())
        )
        return (await self.session.execute(stmt)).scalars().first()

    async def list_active_for_school(self, school_id: UUID) -> Sequence[FeeBillingSchedule]:
        """Every live schedule at one campus, for the unattended run.

        Takes `school_id` explicitly rather than leaning on the ContextVar scope: the
        job walks campuses in a loop and an implicit scope is exactly the thing that
        silently bills School B under School A's schedule.
        """
        stmt = (
            self._base_select()
            .where(
                FeeBillingSchedule.school_id == school_id,
                FeeBillingSchedule.is_active.is_(True),
            )
            .order_by(FeeBillingSchedule.academic_year)
        )
        return (await self.session.execute(stmt)).scalars().all()

    async def head_usage_count(self, head_id: UUID) -> int:
        """How many live schedules bill carried-forward dues under this head.

        The fourth arm of the guard on deleting a fee head, beside structure lines,
        student assignments and fine policies. Deleting the head an automatic run
        bills arrears under would break that run silently, in the middle of the
        night, on the one job nobody is watching.
        """
        stmt = (
            select(func.count())
            .select_from(FeeBillingSchedule)
            .where(
                FeeBillingSchedule.carry_forward_head_id == head_id,
                FeeBillingSchedule.deleted_at.is_(None),
            )
        )
        return int((await self.session.execute(stmt)).scalar_one() or 0)


class FeeLedgerRepository(BaseRepository[StudentLedgerEntry]):
    """The running account. APPEND-ONLY -- there is no update or delete path here.

    `BaseRepository.update`, `soft_delete` and `hard_delete` are inherited and
    deliberately never called on this model; the table has no `updated_at` and no
    `deleted_at`, so a call would fail rather than quietly corrupt a statement.
    """

    model = StudentLedgerEntry
    sortable_fields = frozenset({"created_at", "occurred_on", "amount"})

    async def append(
        self,
        *,
        student_id: UUID,
        entry_type: LedgerEntryType,
        amount: Decimal,
        academic_year: str,
        occurred_on: date,
        description: str,
        organization_id: UUID,
        school_id: UUID,
        voucher_id: UUID | None = None,
        payment_id: UUID | None = None,
        created_by_user_id: UUID | None = None,
    ) -> StudentLedgerEntry:
        """Add one movement, deriving `balance_after` under a per-student lock.

        =================================================================
        WHY THE LOCK, AND WHY ON THE STUDENT ROW
        =================================================================
            `balance_after` is a running total, so two concurrent appends that both
            read the same previous balance would both write the same next one -- and
            the statement would show two movements and one of their effects. That is
            not a rare race: a cashier taking a payment while the late-fee job runs
            is an ordinary Tuesday.

            The lock is taken on the STUDENT row rather than on the latest ledger
            entry, because a row-level lock cannot be taken on a row that does not
            exist yet -- the first entry for a student would lock nothing and race
            with itself. The student row always exists (the caller resolved it to get
            here), and locking it serialises exactly the set of appends that share a
            balance.

            It is a plain `FOR UPDATE`, not `FOR NO KEY UPDATE`: the student row is
            not being modified, so the lock is held only for the remainder of this
            transaction, which is the append and its audit row.
        """
        lock = select(Student.id).where(Student.id == student_id).with_for_update()
        await self.session.execute(lock)

        previous = await self.balance_for(student_id)
        return await self.create(
            student_id=student_id,
            entry_type=entry_type,
            voucher_id=voucher_id,
            payment_id=payment_id,
            academic_year=academic_year,
            amount=amount,
            balance_after=previous + amount,
            occurred_on=occurred_on,
            description=description,
            created_by_user_id=created_by_user_id,
            organization_id=organization_id,
            school_id=school_id,
        )

    async def balance_for(self, student_id: UUID) -> Decimal:
        """What this family owes right now.

        Reads the SUM rather than the newest row's `balance_after`. The two agree in
        every ordinary case, and when they do not, the sum is the one backed by the
        movements -- `balance_after` is a convenience for rendering a statement line,
        not the authority for a balance. Cheap either way: the sum runs on
        `ix_student_ledger_entries_school_id_student_id_created_at`.
        """
        stmt = select(func.coalesce(func.sum(StudentLedgerEntry.amount), 0)).where(
            StudentLedgerEntry.student_id == student_id
        )
        scoped = _scope(stmt, StudentLedgerEntry.school_id)
        return Decimal((await self.session.execute(scoped)).scalar_one() or 0)

    async def balances_for_students(self, student_ids: Sequence[UUID]) -> dict[UUID, Decimal]:
        """Every balance for a billing run, in ONE query.

        The arrears figure is snapshotted onto each generated challan, so without this
        a run over 500 students would issue 500 balance queries -- an N+1 on the
        hottest write path in the module, growing with the size of the school.
        """
        if not student_ids:
            return {}
        stmt = (
            select(
                StudentLedgerEntry.student_id,
                func.coalesce(func.sum(StudentLedgerEntry.amount), 0),
            )
            .where(StudentLedgerEntry.student_id.in_(student_ids))
            .group_by(StudentLedgerEntry.student_id)
        )
        rows = (await self.session.execute(_scope(stmt, StudentLedgerEntry.school_id))).all()
        return {student_id: Decimal(total) for student_id, total in rows}

    async def list_for_student(
        self, student_id: UUID, params: PageParams
    ) -> tuple[Sequence[StudentLedgerEntry], int]:
        """One family's statement, newest first.

        Newest first because the question at the counter is "what do I owe now",
        answered by the top row. A chronological statement is the same data reversed
        and is what the printed version renders.
        """
        condition = StudentLedgerEntry.student_id == student_id
        total = await self.count(condition)
        stmt = (
            self._base_select()
            .where(condition)
            .order_by(StudentLedgerEntry.created_at.desc(), StudentLedgerEntry.id.desc())
            .offset(params.offset)
            .limit(params.limit)
        )
        return (await self.session.execute(stmt)).scalars().all(), total

    async def has_entry_for(self, *, voucher_id: UUID, entry_type: LedgerEntryType) -> bool:
        """Whether this voucher already produced an entry of this kind.

        The idempotence guard on `CHARGE`. Issuing is a one-way transition so it
        should never fire twice, but "should never" is not a guarantee, and a
        duplicated charge silently doubles a family's balance -- a failure a parent
        discovers before the school does.
        """
        return await self.exists(
            StudentLedgerEntry.voucher_id == voucher_id,
            StudentLedgerEntry.entry_type == entry_type,
        )

    async def has_debit_for(self, voucher_id: UUID) -> bool:
        """Whether this voucher ever put a debit on the family's account.

        TWO ENTRY TYPES, NOT ONE, and the second is easy to forget: an ordinary
        challan debits as a CHARGE, while a fine raised by the late-fee run debits as
        a LATE_FEE. Voiding is the supported way to let a family off a fine, so a
        check that looked only for CHARGE would cancel the challan and leave the
        penalty sitting on the balance -- the school would believe it had waived
        something it had not.

        Voiding a DRAFT still finds nothing, which is the other half of the rule: a
        draft was never billed, so there is nothing to credit back.
        """
        return await self.exists(
            StudentLedgerEntry.voucher_id == voucher_id,
            StudentLedgerEntry.entry_type.in_([LedgerEntryType.CHARGE, LedgerEntryType.LATE_FEE]),
        )

    async def charged_totals(self) -> dict[UUID, Decimal]:
        """Every student's ledger balance in this school, for reconciliation.

        Deliberately unpaginated: `reconcile-ledger` compares the whole school
        against what the vouchers and payments say, and a sampled comparison would
        report "no drift" from a subset that happened not to contain any.
        """
        stmt = select(
            StudentLedgerEntry.student_id,
            func.coalesce(func.sum(StudentLedgerEntry.amount), 0),
        ).group_by(StudentLedgerEntry.student_id)
        rows = (await self.session.execute(_scope(stmt, StudentLedgerEntry.school_id))).all()
        return {student_id: Decimal(total) for student_id, total in rows}

    async def outstanding_by_student(self) -> dict[UUID, Decimal]:
        """What the VOUCHERS say each family owes -- the ledger's check figure.

        Sums `total - paid_total` over every issued, unvoided challan. This is the
        aggregate the module answered "what is outstanding" with before the ledger
        existed, and it remains the authority: `reconcile-ledger` reports any student
        whose ledger balance disagrees with it rather than trusting either blindly.
        """
        stmt = (
            select(
                FeeVoucher.student_id,
                func.coalesce(func.sum(FeeVoucher.total - FeeVoucher.paid_total), 0),
            )
            .where(FeeVoucher.status.notin_([VoucherStatus.VOID, VoucherStatus.DRAFT]))
            .group_by(FeeVoucher.student_id)
        )
        rows = (await self.session.execute(_scope(stmt, FeeVoucher.school_id))).all()
        return {student_id: Decimal(total) for student_id, total in rows}
