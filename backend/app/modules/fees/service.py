"""Fees business rules -- what is allowed, and what happens next.

WHY THIS FILE EXISTS
    Everything that decides whether a fee action is legal: that a structure must be
    ACTIVE before it can bill anyone, that a payment may not exceed what is owed,
    that a voucher holding money cannot be voided, and that a challan already in a
    parent's hands is never rewritten.

INTERACTIONS
    * `router.py` translates HTTP; this layer never imports fastapi.
    * `academics` supplies the class a structure prices.
    * `students` supplies who gets billed.
    * `common.audit` records every mutation in the SAME transaction as the change.

=============================================================================
ONE WRITER FOR `paid_total`, AND ONE PLACE THAT DECIDES A VOUCHER'S STATUS
=============================================================================
    `FeeVoucher.paid_total` is materialised so the challan list can show an
    outstanding balance without a correlated subquery per row. The cost of that is a
    cache that can drift, and the discipline that pays it is `_recalculate()`: every
    path that touches money -- recording a payment, reversing one -- ends there, and
    it RECOMPUTES from the payment rows rather than incrementing. A reversal followed
    by a payment therefore cannot leave the cached figure disagreeing with the
    receipts that justify it.
"""

from __future__ import annotations

import base64
import binascii
import csv
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from io import StringIO
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.audit import AuditAction, record_audit
from app.common.schemas import Page, PageParams, SortParams
from app.core.context import get_school_id, require_organization_id, require_school_id
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.modules.academics.models import AcademicYear, SchoolClass
from app.modules.fees.models import (
    ConcessionKind,
    FeeBillingSchedule,
    FeeConcession,
    FeeHead,
    FeeLineType,
    FeePaymentStatus,
    FeeStructure,
    FeeStructureItem,
    FeeStructureStatus,
    FeeVoucher,
    LateFeeKind,
    LateFeePolicy,
    LateFeeRecurrence,
    LedgerEntryType,
    StationeryCategory,
    StationeryItem,
    StudentFeeAssignment,
    StudentFeeAssignmentMode,
    StudentLedgerEntry,
    VoucherOrigin,
    VoucherStatus,
)
from app.modules.fees.repository import (
    FeeBillingScheduleRepository,
    FeeConcessionRepository,
    FeeHeadRepository,
    FeeLedgerRepository,
    FeePaymentRepository,
    FeeStructureItemRepository,
    FeeStructureRepository,
    FeeVoucherItemRepository,
    FeeVoucherRepository,
    LateFeePolicyRepository,
    StationeryItemRepository,
    StudentFeeAssignmentRepository,
)
from app.modules.fees.schemas import (
    BillingRunResult,
    FeeBillingScheduleInput,
    FeeBillingScheduleRead,
    FeeConcessionCreate,
    FeeConcessionRead,
    FeeConcessionUpdate,
    FeeHeadCreate,
    FeeHeadRead,
    FeeHeadUpdate,
    FeePaymentCreate,
    FeePaymentRead,
    FeeStructureCreate,
    FeeStructureDetail,
    FeeStructureItemInput,
    FeeStructureItemRead,
    FeeStructureRead,
    FeeStructureStationeryInput,
    FeeStructureUpdate,
    FeeSummary,
    FeeVoucherDetail,
    FeeVoucherRead,
    LateFeePolicyCreate,
    LateFeePolicyRead,
    LateFeeRunResult,
    LedgerAdjustmentInput,
    LedgerEntryRead,
    StationeryItemCreate,
    StationeryItemRead,
    StationeryItemUpdate,
    StudentFeeAssignmentInput,
    StudentFeeAssignmentRead,
    StudentFeeLine,
    StudentFeeProfile,
    StudentLedgerStatement,
    VoucherFeeChargeInput,
    VoucherGenerateRequest,
    VoucherGenerateResult,
    VoucherItemRead,
    VoucherSkip,
    VoucherStationeryInput,
    VoucherStatusCount,
)
from app.modules.students.models import Student, StudentEnrollment
from app.modules.tenancy.models import Organization, School

logger = get_logger(__name__)

# Spec §8: one generation run bills at most this many students. Beyond it the caller
# filters by section and runs again. The cap is REPORTED in the response
# (`truncated`), never applied silently -- a truncated run that reads as a complete
# one is how a class quietly goes unbilled for a month.
MAX_GENERATION_BATCH = 500

# One late-fee pass fines at most this many challans. Lower than the generation cap
# because each candidate costs an extra query (`fines_for_source`) and the job runs
# unattended -- a run that takes an hour is a run nobody notices has stopped. The
# remainder is picked up by the next pass, oldest delinquency first, and `truncated`
# reports it rather than the run reading as complete.
MAX_LATE_FEE_BATCH = 250

# The voucher register export ceiling. See `export_vouchers_csv` for why this is
# announced inside the file rather than only in a response header.
MAX_EXPORT_ROWS = 5000

_ZERO = Decimal("0.00")


@dataclass(frozen=True, slots=True)
class ChallanPrintContext:
    """One printed challan's worth of resolved input, handed to a pure renderer.

    Exists so `challan_pdf.render_challan_pdf` can stay a function of its arguments:
    everything it would otherwise have to look up -- the campus's design and
    accounts, the roll number for the right session, what the fine policy would add
    after the due date -- is decided here, where there is a database and a place to
    raise from, and arrives there as data.
    """

    vouchers: tuple[FeeVoucher, ...]
    """Sorted by due date, which is the order the months print in."""

    school: School
    roll_number: str | None
    late_fee: Decimal
    logo: bytes | None = None
    """The campus's logo as image bytes, falling back to the organization's. None when
    neither is set, or when the logo is a remote link -- the renderer never fetches."""


# Stationery lines sort below every fee line on a challan. 1000 rather than a tighter
# number because `sort_order` on both catalogs is capped at 999 by the schemas, so no
# fee head can ever reach into this range and interleave itself with the books.
_STATIONERY_SORT_BASE = 1000

# Carried-forward dues print below every fee line and above the stationery block.
# 999 rather than a tighter number because `sort_order` on the head catalog is capped
# at 999 by the schemas, so this can tie with a head but never be jumped by one -- and
# a tie resolves to insertion order, which puts the arrears line last among the fees.
_ARREARS_SORT_ORDER = 999


class FeeService:
    """Fee heads, structures, vouchers and payments."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.heads = FeeHeadRepository(session)
        self.structures = FeeStructureRepository(session)
        self.structure_items = FeeStructureItemRepository(session)
        self.vouchers = FeeVoucherRepository(session)
        self.voucher_items = FeeVoucherItemRepository(session)
        self.payments = FeePaymentRepository(session)
        self.stationery = StationeryItemRepository(session)
        self.assignments = StudentFeeAssignmentRepository(session)
        self.billing_schedules = FeeBillingScheduleRepository(session)
        self.concessions = FeeConcessionRepository(session)
        self.late_fee_policies = LateFeePolicyRepository(session)
        self.ledger = FeeLedgerRepository(session)

    # =====================================================================
    # Fee heads
    # =====================================================================

    async def create_head(self, payload: FeeHeadCreate, *, actor_id: UUID) -> FeeHeadRead:
        if await self.heads.get_by_code(payload.code):
            raise ConflictError(f"A fee head with code '{payload.code}' already exists.")

        head = await self.heads.create(
            **payload.model_dump(),
            # Both from the verified JWT, never the request body. Omitting
            # `organization_id` would not create an orphan -- the RLS WITH CHECK
            # policy rejects the INSERT outright -- but `school_id` has no such
            # backstop, which is exactly why it comes from context too.
            organization_id=require_organization_id(),
            school_id=require_school_id(),
        )
        await self._audit(
            AuditAction.FEE_HEAD_CREATED,
            entity_type="fee_head",
            entity_id=head.id,
            actor_id=actor_id,
            after={"code": head.code, "name": head.name},
        )
        logger.info("fee_head_created", fee_head_id=str(head.id), code=head.code)
        return FeeHeadRead.model_validate(head)

    async def list_heads(
        self, params: PageParams, sort: SortParams, *, active_only: bool = False
    ) -> Page[FeeHeadRead]:
        conditions = [FeeHead.is_active.is_(True)] if active_only else []
        rows, total = await self.heads.list(*conditions, params=params, sort=sort)
        return Page.create([FeeHeadRead.model_validate(r) for r in rows], total, params)

    async def get_head(self, head_id: UUID) -> FeeHead:
        """A cross-tenant id is filtered out by RLS and arrives here as None, so it
        becomes a 404 -- never a 403, which would confirm the record exists."""
        head = await self.heads.get(head_id)
        if head is None:
            raise NotFoundError("Fee head not found.")
        return head

    async def update_head(
        self, head_id: UUID, payload: FeeHeadUpdate, *, actor_id: UUID
    ) -> FeeHeadRead:
        head = await self.get_head(head_id)
        values = payload.model_dump(exclude_unset=True)
        before = {"name": head.name, "is_active": head.is_active}

        updated = await self.heads.update(head, **values)
        await self._audit(
            AuditAction.FEE_HEAD_UPDATED,
            entity_type="fee_head",
            entity_id=head_id,
            actor_id=actor_id,
            before=before,
            after={"name": updated.name, "is_active": updated.is_active},
        )
        return FeeHeadRead.model_validate(updated)

    async def delete_head(self, head_id: UUID, *, actor_id: UUID) -> None:
        """Refuse while any live structure still prices this head.

        Cascading instead would silently change what a class is billed, because the
        priced line would vanish from every structure that used it. Deactivating
        (`is_active = false`) is the supported retirement path: the head leaves the
        pickers while existing structures keep working.
        """
        head = await self.get_head(head_id)
        # BOTH tables. A head reaches a challan through a class structure AND through
        # a per-student arrangement, and counting only the first would let someone
        # tidy "Transport" away while every individually bussed student silently
        # stopped being billed -- damage invisible until the money did not arrive.
        in_structures = await self.heads.structure_usage_count(head_id)
        on_students = await self.assignments.head_usage_count(head_id)
        # THE THIRD ARM. A head also reaches a challan through the late-fee policy
        # that bills fines under it, and deleting that head would break the job
        # silently -- at 2am, in a scheduled run nobody reads the logs of.
        in_policies = await self.late_fee_policies.head_usage_count(head_id)
        # THE FOURTH ARM, and the one that would fail most quietly of all: a schedule
        # bills carried-forward dues under a head, unattended, once a month. Deleting
        # it would break the run in the middle of the night with nobody watching.
        in_schedules = await self.billing_schedules.head_usage_count(head_id)
        if in_structures or on_students or in_policies or in_schedules:
            where = []
            if in_structures:
                where.append(f"{in_structures} fee structure line(s)")
            if on_students:
                where.append(f"{on_students} student arrangement(s)")
            if in_policies:
                where.append(f"{in_policies} late fee policy(ies)")
            if in_schedules:
                where.append(f"{in_schedules} billing schedule(s)")
            raise ConflictError(
                f"This fee head is used by {' and '.join(where)}. "
                "Deactivate it instead, or remove those first."
            )

        await self.heads.soft_delete(head)
        await self._audit(
            AuditAction.FEE_HEAD_DELETED,
            entity_type="fee_head",
            entity_id=head_id,
            actor_id=actor_id,
            before={"code": head.code, "name": head.name},
        )
        logger.info("fee_head_deleted", fee_head_id=str(head_id))

    # =====================================================================
    # Stationery catalog -- what may be SOLD
    # =====================================================================
    #
    # The sibling of the fee-head block above. Everything here is deliberately
    # parallel to it, including the refusal-to-delete rule, because the two are the
    # same kind of object to an operator: a thing the school can put on a challan.

    async def create_stationery_item(
        self, payload: StationeryItemCreate, *, actor_id: UUID
    ) -> StationeryItemRead:
        if await self.stationery.get_by_code(payload.code):
            raise ConflictError(f"A stationery item with code '{payload.code}' already exists.")

        item = await self.stationery.create(
            **payload.model_dump(),
            organization_id=require_organization_id(),
            school_id=require_school_id(),
        )
        await self._audit(
            AuditAction.STATIONERY_ITEM_CREATED,
            entity_type="stationery_item",
            entity_id=item.id,
            actor_id=actor_id,
            after={"code": item.code, "name": item.name, "unit_price": str(item.unit_price)},
        )
        logger.info("stationery_item_created", stationery_item_id=str(item.id), code=item.code)
        return StationeryItemRead.model_validate(item)

    async def list_stationery_items(
        self,
        params: PageParams,
        sort: SortParams,
        *,
        active_only: bool = False,
        category: StationeryCategory | None = None,
    ) -> Page[StationeryItemRead]:
        # Annotated because the two branches below produce different SQLAlchemy
        # expression classes; without it mypy pins the list to whichever appends first.
        conditions: list[ColumnElement[bool]] = []
        if active_only:
            conditions.append(StationeryItem.is_active.is_(True))
        if category is not None:
            conditions.append(StationeryItem.category == category)
        rows, total = await self.stationery.list(*conditions, params=params, sort=sort)
        return Page.create([StationeryItemRead.model_validate(r) for r in rows], total, params)

    async def get_stationery_item(self, item_id: UUID) -> StationeryItem:
        """A cross-tenant id is filtered out by RLS and arrives here as None, so it
        becomes a 404 -- never a 403, which would confirm the record exists."""
        item = await self.stationery.get(item_id)
        if item is None:
            raise NotFoundError("Stationery item not found.")
        return item

    async def update_stationery_item(
        self, item_id: UUID, payload: StationeryItemUpdate, *, actor_id: UUID
    ) -> StationeryItemRead:
        """Edit the catalog, INCLUDING the price.

        Repricing is safe and needs no ceremony because it is not retroactive: every
        structure line froze the price it was added at, and every challan line froze
        the price it sold at. Changing 60 to 70 here changes what the NEXT line
        costs, and nothing that has already been charged.

        The audit row carries the old and new price explicitly -- "who put the copy
        up to 70 and when" is the question this table gets asked.
        """
        item = await self.get_stationery_item(item_id)
        values = payload.model_dump(exclude_unset=True)
        before = {
            "name": item.name,
            "unit_price": str(item.unit_price),
            "is_active": item.is_active,
        }

        updated = await self.stationery.update(item, **values)
        await self._audit(
            AuditAction.STATIONERY_ITEM_UPDATED,
            entity_type="stationery_item",
            entity_id=item_id,
            actor_id=actor_id,
            before=before,
            after={
                "name": updated.name,
                "unit_price": str(updated.unit_price),
                "is_active": updated.is_active,
            },
        )
        return StationeryItemRead.model_validate(updated)

    async def delete_stationery_item(self, item_id: UUID, *, actor_id: UUID) -> None:
        """Refuse while any structure line or challan line still charges this article.

        Stricter than `delete_head`, which only counts structures. A fee head can only
        reach a challan through a structure, so guarding the structure guards
        everything downstream; a stationery article can also be charged straight onto
        a draft voucher, and deleting one out from under such a line would leave a
        challan naming a record that no longer exists. Deactivating is the supported
        retirement path either way.
        """
        item = await self.get_stationery_item(item_id)
        in_use = await self.stationery.usage_count(item_id)
        if in_use:
            raise ConflictError(
                f"This stationery item is charged on {in_use} line(s). "
                "Deactivate it instead, or remove those lines first."
            )

        await self.stationery.soft_delete(item)
        await self._audit(
            AuditAction.STATIONERY_ITEM_DELETED,
            entity_type="stationery_item",
            entity_id=item_id,
            actor_id=actor_id,
            before={"code": item.code, "name": item.name},
        )
        logger.info("stationery_item_deleted", stationery_item_id=str(item_id))

    # =====================================================================
    # Fee structures
    # =====================================================================

    async def create_structure(
        self, payload: FeeStructureCreate, *, actor_id: UUID
    ) -> FeeStructureDetail:
        school_class = await self._get_class(payload.class_id)

        if await self.structures.get_for_class_year(payload.class_id, payload.academic_year):
            raise ConflictError(
                f"A fee structure already exists for this class in {payload.academic_year}. "
                "Edit it, or archive it and create a replacement."
            )

        structure = await self.structures.create(
            class_id=school_class.id,
            academic_year=payload.academic_year,
            name=payload.name,
            status=FeeStructureStatus.DRAFT,
            # Inherited from the class rather than re-read from context, so a
            # structure can never end up scoped differently from the class it prices.
            organization_id=school_class.organization_id,
            school_id=school_class.school_id,
        )

        for item in payload.items:
            await self._add_item(structure, item)

        await self._audit(
            AuditAction.FEE_STRUCTURE_CREATED,
            entity_type="fee_structure",
            entity_id=structure.id,
            actor_id=actor_id,
            after={
                "class_id": str(structure.class_id),
                "academic_year": structure.academic_year,
                "items": len(payload.items),
            },
        )
        logger.info("fee_structure_created", structure_id=str(structure.id))
        return await self.get_structure_detail(structure.id)

    async def list_structures(
        self,
        params: PageParams,
        sort: SortParams,
        *,
        class_id: UUID | None = None,
        academic_year: str | None = None,
        status: FeeStructureStatus | None = None,
    ) -> Page[FeeStructureRead]:
        conditions = []
        if class_id is not None:
            conditions.append(FeeStructure.class_id == class_id)
        if academic_year is not None:
            conditions.append(FeeStructure.academic_year == academic_year)
        if status is not None:
            conditions.append(FeeStructure.status == status)

        rows, total = await self.structures.list(*conditions, params=params, sort=sort)
        return Page.create([FeeStructureRead.model_validate(r) for r in rows], total, params)

    async def get_structure(self, structure_id: UUID) -> FeeStructure:
        structure = await self.structures.get(structure_id)
        if structure is None:
            raise NotFoundError("Fee structure not found.")
        return structure

    async def get_structure_detail(self, structure_id: UUID) -> FeeStructureDetail:
        structure = await self.structures.get_with_items(structure_id)
        if structure is None:
            raise NotFoundError("Fee structure not found.")

        items = [self._structure_item_read(item) for item in structure.items]
        fee_total = sum((i.amount for i in items if i.line_type is FeeLineType.FEE), _ZERO)
        stationery_total = sum(
            (i.amount for i in items if i.line_type is FeeLineType.STATIONERY), _ZERO
        )
        return FeeStructureDetail(
            **FeeStructureRead.model_validate(structure).model_dump(),
            items=items,
            total=fee_total + stationery_total,
            fee_total=fee_total,
            stationery_total=stationery_total,
        )

    async def update_structure(
        self, structure_id: UUID, payload: FeeStructureUpdate, *, actor_id: UUID
    ) -> FeeStructureDetail:
        structure = await self.get_structure(structure_id)
        self._assert_editable(structure)

        values = payload.model_dump(exclude_unset=True)
        before = {"name": structure.name}
        updated = await self.structures.update(structure, **values)

        await self._audit(
            AuditAction.FEE_STRUCTURE_UPDATED,
            entity_type="fee_structure",
            entity_id=structure_id,
            actor_id=actor_id,
            before=before,
            after={"name": updated.name},
        )
        return await self.get_structure_detail(structure_id)

    async def set_structure_item(
        self, structure_id: UUID, payload: FeeStructureItemInput, *, actor_id: UUID
    ) -> FeeStructureDetail:
        """Add a priced line, or reprice an existing one.

        Idempotent by head: sending the same head twice updates the amount rather
        than creating a second line, which is what the unique constraint enforces
        anyway. Repricing an ACTIVE structure is allowed and affects only FUTURE
        generation runs -- issued vouchers snapshotted their amounts and are never
        restated.
        """
        structure = await self.get_structure(structure_id)
        self._assert_editable(structure)

        head = await self.get_head(payload.head_id)
        if not head.is_active:
            raise ValidationError(
                f"Fee head '{head.name}' is inactive and cannot be added to a structure.",
                code="FEE_HEAD_INACTIVE",
            )

        existing = await self.structure_items.get_for_structure(structure_id, payload.head_id)
        if existing is None:
            await self._add_item(structure, payload)
            before: dict[str, Any] | None = None
        else:
            before = {"amount": str(existing.amount)}
            # `unit_price` moves with `amount` so the identity that holds on every
            # fee line -- quantity 1, unit price == amount -- survives a reprice.
            await self.structure_items.update(
                existing, amount=payload.amount, unit_price=payload.amount
            )

        await self._audit(
            AuditAction.FEE_STRUCTURE_ITEM_CHANGED,
            entity_type="fee_structure",
            entity_id=structure_id,
            actor_id=actor_id,
            before=before,
            after={"head_id": str(payload.head_id), "amount": str(payload.amount)},
        )
        return await self.get_structure_detail(structure_id)

    async def remove_structure_item(
        self, structure_id: UUID, head_id: UUID, *, actor_id: UUID
    ) -> FeeStructureDetail:
        structure = await self.get_structure(structure_id)
        self._assert_editable(structure)

        item = await self.structure_items.get_for_structure(structure_id, head_id)
        if item is None:
            raise NotFoundError("That fee head is not priced in this structure.")

        # Hard delete: a structure line is configuration, not a financial record.
        # Vouchers already generated snapshotted their own copy, so removing the line
        # cannot alter a bill anyone has received.
        before = {"head_id": str(head_id), "amount": str(item.amount)}
        await self.structure_items.hard_delete(item.id)

        await self._audit(
            AuditAction.FEE_STRUCTURE_ITEM_CHANGED,
            entity_type="fee_structure",
            entity_id=structure_id,
            actor_id=actor_id,
            before=before,
            after=None,
        )
        return await self.get_structure_detail(structure_id)

    async def set_structure_stationery(
        self, structure_id: UUID, payload: FeeStructureStationeryInput, *, actor_id: UUID
    ) -> FeeStructureDetail:
        """Put a stationery article on a structure, or change how many of it.

        THE PER-CLASS DEFAULT, as opposed to the per-student charge on a draft
        voucher. "Every child in Grade 1 gets twelve copies and the book set" is a
        property of the class, and expressing it here means one generation run bills
        two hundred students correctly instead of an operator adding the same line to
        two hundred drafts by hand.

        The unit price is COPIED FROM THE CATALOG, not supplied by the caller -- see
        `FeeStructureStationeryInput`. Adding the line again later is how a structure
        picks up a repriced article, and that re-add is a visible, audited act rather
        than a silent drift in what the class is charged.
        """
        structure = await self.get_structure(structure_id)
        self._assert_editable(structure)

        item = await self.get_stationery_item(payload.stationery_item_id)
        if not item.is_active:
            raise ValidationError(
                f"Stationery item '{item.name}' is inactive and cannot be added to a structure.",
                code="STATIONERY_ITEM_INACTIVE",
            )

        amount = self._line_total(payload.quantity, item.unit_price)
        existing = await self.structure_items.get_stationery_for_structure(structure_id, item.id)
        if existing is None:
            await self.structure_items.create(
                structure_id=structure.id,
                line_type=FeeLineType.STATIONERY,
                head_id=None,
                stationery_item_id=item.id,
                quantity=payload.quantity,
                unit_price=item.unit_price,
                amount=amount,
                organization_id=structure.organization_id,
                school_id=structure.school_id,
            )
            before: dict[str, Any] | None = None
        else:
            before = {
                "quantity": str(existing.quantity),
                "unit_price": str(existing.unit_price),
                "amount": str(existing.amount),
            }
            await self.structure_items.update(
                existing,
                quantity=payload.quantity,
                unit_price=item.unit_price,
                amount=amount,
            )

        await self._audit(
            AuditAction.FEE_STRUCTURE_ITEM_CHANGED,
            entity_type="fee_structure",
            entity_id=structure_id,
            actor_id=actor_id,
            before=before,
            after={
                "stationery_item_id": str(item.id),
                "name": item.name,
                "quantity": str(payload.quantity),
                "unit_price": str(item.unit_price),
                "amount": str(amount),
            },
        )
        return await self.get_structure_detail(structure_id)

    async def remove_structure_stationery(
        self, structure_id: UUID, stationery_item_id: UUID, *, actor_id: UUID
    ) -> FeeStructureDetail:
        structure = await self.get_structure(structure_id)
        self._assert_editable(structure)

        item = await self.structure_items.get_stationery_for_structure(
            structure_id, stationery_item_id
        )
        if item is None:
            raise NotFoundError("That stationery item is not on this structure.")

        # Hard delete for the same reason `remove_structure_item` hard-deletes: a
        # structure line is configuration, and every voucher already generated took
        # its own snapshot, so removing this cannot alter a bill anyone received.
        before = {
            "stationery_item_id": str(stationery_item_id),
            "quantity": str(item.quantity),
            "amount": str(item.amount),
        }
        await self.structure_items.hard_delete(item.id)

        await self._audit(
            AuditAction.FEE_STRUCTURE_ITEM_CHANGED,
            entity_type="fee_structure",
            entity_id=structure_id,
            actor_id=actor_id,
            before=before,
            after=None,
        )
        return await self.get_structure_detail(structure_id)

    async def activate_structure(self, structure_id: UUID, *, actor_id: UUID) -> FeeStructureDetail:
        structure = await self.get_structure(structure_id)
        if structure.status is FeeStructureStatus.ACTIVE:
            return await self.get_structure_detail(structure_id)
        if structure.status is FeeStructureStatus.ARCHIVED:
            raise ConflictError(
                "An archived fee structure cannot be reactivated. Create a replacement."
            )

        items = await self.structure_items.list_for_structure(structure_id)
        if not items:
            # An empty ACTIVE structure would generate zero-value challans for a whole
            # class, which reads as "fees are paid" on every dashboard downstream.
            raise ValidationError(
                "Add at least one fee head or stationery item before activating this structure.",
                code="FEE_STRUCTURE_EMPTY",
            )

        updated = await self.structures.update(structure, status=FeeStructureStatus.ACTIVE)
        await self._audit(
            AuditAction.FEE_STRUCTURE_ACTIVATED,
            entity_type="fee_structure",
            entity_id=structure_id,
            actor_id=actor_id,
            before={"status": FeeStructureStatus.DRAFT.value},
            after={"status": updated.status.value, "items": len(items)},
        )
        logger.info("fee_structure_activated", structure_id=str(structure_id))
        return await self.get_structure_detail(structure_id)

    async def archive_structure(self, structure_id: UUID, *, actor_id: UUID) -> FeeStructureDetail:
        structure = await self.get_structure(structure_id)
        if structure.status is FeeStructureStatus.ARCHIVED:
            return await self.get_structure_detail(structure_id)

        drafts = await self.structures.draft_voucher_count(structure_id)
        if drafts:
            raise ConflictError(
                f"This structure still has {drafts} draft voucher(s). "
                "Issue or void them before archiving."
            )

        before = structure.status.value
        updated = await self.structures.update(structure, status=FeeStructureStatus.ARCHIVED)
        await self._audit(
            AuditAction.FEE_STRUCTURE_ARCHIVED,
            entity_type="fee_structure",
            entity_id=structure_id,
            actor_id=actor_id,
            before={"status": before},
            after={"status": updated.status.value},
        )
        return await self.get_structure_detail(structure_id)

    # =====================================================================
    # Student fee assignments -- where one student departs from their class
    # =====================================================================
    #
    # =====================================================================
    # THE CLASS STRUCTURE IS THE BASE; THIS RECORDS ONLY THE DIFFERENCES
    # =====================================================================
    #   Every student's bill really is their own -- one takes the bus, one boards,
    #   one walks. That does NOT mean every student needs their own fee plan, and the
    #   distinction is what this whole block is built on.
    #
    #   A student with no assignments is billed their class's structure exactly, and
    #   that is the overwhelmingly common case. It costs no rows, it means a new
    #   admission is billed correctly the moment they are placed in a section, and it
    #   means an 8% tuition rise is one edit rather than five hundred.
    #
    #   What lands here is the exception: "Ali takes the bus at 2,000", "Sara does
    #   not take transport". Those are the facts an operator actually maintains.

    async def set_student_assignment(
        self, student_id: UUID, payload: StudentFeeAssignmentInput, *, actor_id: UUID
    ) -> StudentFeeProfile:
        """Add a student to a fee head, or take them off one.

        Idempotent by head and year: sending the same head twice updates the existing
        arrangement rather than creating a second one, which is also what the unique
        constraint enforces. Changing a bus fare is therefore the same call as setting
        it, and an operator cannot end up with a student on two conflicting rates.

        Takes effect on the NEXT generation run. Challans already issued snapshotted
        their lines and are never restated -- the same rule that governs repricing a
        structure or a stationery article.
        """
        student = await self._get_student(student_id)
        head = await self.get_head(payload.head_id)

        if payload.mode is StudentFeeAssignmentMode.ADDED and not head.is_active:
            raise ValidationError(
                f"Fee head '{head.name}' is inactive and cannot be assigned to a student.",
                code="FEE_HEAD_INACTIVE",
            )

        # RESOLVED, not merely accepted. A concession id from another campus is
        # filtered out by the school predicate and reads as absent, so this 404s
        # rather than storing a foreign key the challan would later fail to price --
        # and a retired scheme cannot be newly awarded, though children already on it
        # keep their rate (see `delete_concession`).
        if payload.concession_id is not None:
            concession = await self.get_concession(payload.concession_id)
            if not concession.is_active:
                raise ValidationError(
                    f"Concession '{concession.name}' is inactive and cannot be awarded.",
                    code="CONCESSION_INACTIVE",
                )

        existing = await self.assignments.get_for_student(
            student_id, payload.academic_year, payload.head_id
        )
        # WRITTEN AS ONE DICT for both branches. The create and the update must agree
        # on every value column: a mode change from ADDED to DISCOUNT that updated
        # `amount` but left a stale `percent` behind would store a row whose halves
        # disagree, and `ck_..._amount_matches_mode` would reject it -- as a 409 on a
        # request that looked perfectly valid.
        values: dict[str, Any] = {
            "mode": payload.mode,
            "amount": payload.amount,
            "percent": payload.percent,
            "concession_id": payload.concession_id,
            "note": payload.note,
        }
        if existing is None:
            await self.assignments.create(
                student_id=student.id,
                head_id=head.id,
                academic_year=payload.academic_year,
                **values,
                # Inherited from the student, so an arrangement can never end up
                # scoped differently from the child it belongs to.
                organization_id=student.organization_id,
                school_id=student.school_id,
            )
            before: dict[str, Any] | None = None
        else:
            before = {
                "mode": existing.mode.value,
                "amount": str(existing.amount),
                "percent": str(existing.percent) if existing.percent is not None else None,
                "concession_id": (str(existing.concession_id) if existing.concession_id else None),
            }
            await self.assignments.update(existing, **values)

        await self._audit(
            AuditAction.STUDENT_FEE_ASSIGNED,
            entity_type="student",
            entity_id=student_id,
            actor_id=actor_id,
            before=before,
            after={
                "head_id": str(head.id),
                "head_name": head.name,
                "academic_year": payload.academic_year,
                "mode": payload.mode.value,
                "amount": str(payload.amount) if payload.amount is not None else None,
                "percent": str(payload.percent) if payload.percent is not None else None,
                "concession_id": (str(payload.concession_id) if payload.concession_id else None),
                "note": payload.note,
            },
        )
        logger.info(
            "student_fee_assigned",
            student_id=str(student_id),
            head_id=str(head.id),
            mode=payload.mode.value,
        )
        return await self.get_student_fee_profile(student_id, payload.academic_year)

    async def remove_student_assignment(
        self, student_id: UUID, head_id: UUID, academic_year: str, *, actor_id: UUID
    ) -> StudentFeeProfile:
        """Drop an arrangement, putting the student back on their class's default.

        Soft-deleted rather than hard: "Ali came off the bus in March" is a fact
        somebody will be asked about, and a row that simply vanishes cannot answer it.
        """
        await self._get_student(student_id)
        assignment = await self.assignments.get_for_student(student_id, academic_year, head_id)
        if assignment is None:
            raise NotFoundError("This student has no arrangement for that fee head.")

        before = {
            "head_id": str(head_id),
            "mode": assignment.mode.value,
            "amount": str(assignment.amount),
            "academic_year": academic_year,
        }
        await self.assignments.soft_delete(assignment)

        await self._audit(
            AuditAction.STUDENT_FEE_UNASSIGNED,
            entity_type="student",
            entity_id=student_id,
            actor_id=actor_id,
            before=before,
            after=None,
        )
        logger.info("student_fee_unassigned", student_id=str(student_id), head_id=str(head_id))
        return await self.get_student_fee_profile(student_id, academic_year)

    async def get_student_fee_profile(
        self, student_id: UUID, academic_year: str
    ) -> StudentFeeProfile:
        """What this student will actually be billed, and where each line came from.

        Returns the class base, the student's departures, and the result of applying
        one to the other. All three, because the effective list alone cannot answer
        "why is Ali paying 4,000 more than his class?" -- which is the only question
        anyone opens this screen to ask.
        """
        student = await self._get_student(student_id)
        structure = await self._structure_for_student(student, academic_year)
        assignments = await self.assignments.list_for_student(student_id, academic_year)

        base = self._base_lines(structure)
        effective = self._effective_lines(base, assignments)

        return StudentFeeProfile(
            student_id=student.id,
            student_name=student.full_name,
            admission_number=student.admission_number,
            academic_year=academic_year,
            class_id=structure.class_id if structure else None,
            structure_id=structure.id if structure else None,
            structure_name=structure.name if structure else None,
            base=base,
            assignments=[self._assignment_read(a) for a in assignments],
            effective=effective,
            effective_total=sum((line.net_amount for line in effective), _ZERO),
            gross_total=sum((line.amount for line in effective), _ZERO),
            discount_total=sum((line.discount_amount for line in effective), _ZERO),
        )

    # =====================================================================
    # Vouchers
    # =====================================================================

    async def generate_vouchers(
        self, payload: VoucherGenerateRequest, *, actor_id: UUID | None
    ) -> VoucherGenerateResult:
        """Bill a whole class for one period.

        SKIPS RATHER THAN FAILS. A student already billed for this period is reported
        in `skipped` and the rest still generate. Rolling back 400 challans because
        one student was billed yesterday is not a usable product, and it is the
        failure mode that makes an operator stop trusting the button.
        """
        if payload.due_date < payload.issue_date:
            raise ValidationError(
                "The due date cannot fall before the issue date.", code="DUE_BEFORE_ISSUE"
            )

        structure = await self.structures.get_with_items(payload.structure_id)
        if structure is None:
            raise NotFoundError("Fee structure not found.")
        if structure.status is not FeeStructureStatus.ACTIVE:
            raise ConflictError(
                "Only an active fee structure can generate vouchers. "
                f"This one is {structure.status.value}."
            )
        if not structure.items:
            raise ValidationError(
                "This fee structure has no priced fee heads.", code="FEE_STRUCTURE_EMPTY"
            )

        # +1 so a class sitting exactly on the cap is distinguishable from one that
        # overflows it, and `truncated` is reported honestly rather than guessed.
        candidates = await self.vouchers.eligible_students(
            structure.class_id,
            section_id=payload.section_id,
            student_ids=payload.student_ids,
            limit=MAX_GENERATION_BATCH + 1,
        )
        truncated = len(candidates) > MAX_GENERATION_BATCH
        students = list(candidates[:MAX_GENERATION_BATCH])

        already_billed = await self.vouchers.existing_period_student_ids(
            [s.id for s in students], structure.academic_year, payload.period_label
        )

        skipped = [
            VoucherSkip(
                student_id=student.id,
                admission_number=student.admission_number,
                reason="Already has a challan with this description.",
            )
            for student in students
            if student.id in already_billed
        ]
        billable = [s for s in students if s.id not in already_billed]

        # ONE query for the whole batch, not one per student. Generation is the
        # hottest write path in the module and runs over a class of several hundred;
        # a per-student lookup here is an N+1 that grows with the size of the school.
        assignments = await self.assignments.for_students(
            [s.id for s in billable], structure.academic_year
        )

        # ONE query for the whole batch, like the assignments above. Each challan
        # snapshots what the family owed when it was printed, and asking per student
        # would put a second N+1 on the same loop.
        balances = await self.ledger.balances_for_students([s.id for s in billable])

        # CONSOLIDATION. The head is resolved before a single challan is written: an
        # inactive or cross-campus head must fail the whole run here, not halfway
        # through it, because a run that billed 200 families and then stopped leaves
        # the other 200 unbilled and the operator with no way to tell which is which.
        carry_head: FeeHead | None = None
        absorbable: dict[UUID, list[FeeVoucher]] = {}
        if payload.carry_forward_dues:
            assert payload.carry_forward_head_id is not None  # schema model_validator
            carry_head = await self.get_head(payload.carry_forward_head_id)
            if not carry_head.is_active:
                raise ValidationError(
                    f"Fee head '{carry_head.name}' is inactive and cannot carry dues forward.",
                    code="FEE_HEAD_INACTIVE",
                )
            absorbable = await self.vouchers.absorbable_for_students([s.id for s in billable])

        prefix = f"FV-{payload.issue_date.year}-"
        sequence = await self.vouchers.next_sequence(prefix)
        now = datetime.now(UTC)

        created_ids: list[UUID] = []
        absorbed_count = 0
        absorbed_total = _ZERO
        for student in billable:
            absorbed = absorbable.get(student.id, []) if carry_head is not None else []
            voucher = await self._create_voucher(
                structure=structure,
                student=student,
                payload=payload,
                voucher_number=f"{prefix}{sequence:05d}",
                issued=payload.issue_immediately,
                now=now,
                assignments=assignments.get(student.id, []),
                arrears=balances.get(student.id, _ZERO),
                carry_head=carry_head,
                absorbed=absorbed,
            )
            if absorbed:
                # RESERVED, NOT YET CANCELLED. Nothing moves here: the old challans
                # keep their status and stay on the family's balance until the new
                # one is ISSUED, because a draft is not a bill and cancelling a real
                # challan against one would tell the school a family owes nothing
                # while the only document covering that money is still unissued.
                for old_voucher in absorbed:
                    await self.vouchers.update(old_voucher, superseded_by_voucher_id=voucher.id)
                absorbed_count += len(absorbed)
                absorbed_total += sum((v.total for v in absorbed), _ZERO)

            # Issued in the same breath as generated, so the ledger has to learn about
            # it here -- `issue_voucher` is never called for these. A generated DRAFT
            # deliberately produces no entry: a draft is not a bill, and a ledger that
            # counted drafts would show families owing money nobody has asked for.
            if payload.issue_immediately:
                # The cancellation of what this challan absorbed belongs to the same
                # moment as its own charge, so the balance never passes through a
                # value that is wrong in either direction.
                await self._settle_superseded(voucher, actor_id=actor_id)
                await self._ledger_charge(voucher, actor_id=actor_id)
            sequence += 1
            created_ids.append(voucher.id)

        # One batch row plus the per-voucher rows below it: the batch answers "who ran
        # the August billing and what did it do", which no individual voucher can.
        await self._audit(
            AuditAction.FEE_VOUCHER_GENERATED,
            entity_type="fee_structure",
            entity_id=structure.id,
            actor_id=actor_id,
            after={
                "period_label": payload.period_label,
                "academic_year": structure.academic_year,
                "created": len(created_ids),
                "skipped": len(skipped),
                "truncated": truncated,
                "section_id": str(payload.section_id) if payload.section_id else None,
                "issued_immediately": payload.issue_immediately,
                # Audited on the BATCH row, because "why did August's challans total
                # more than the fee structure?" is asked about the run, not about one
                # family's paper.
                "carried_forward": payload.carry_forward_dues,
                "absorbed_vouchers": absorbed_count,
                "absorbed_total": str(absorbed_total),
            },
        )
        logger.info(
            "fee_vouchers_generated",
            structure_id=str(structure.id),
            created=len(created_ids),
            skipped=len(skipped),
            truncated=truncated,
            absorbed=absorbed_count,
        )
        return VoucherGenerateResult(
            created=len(created_ids),
            skipped=skipped,
            voucher_ids=created_ids,
            truncated=truncated,
            absorbed_vouchers=absorbed_count,
            absorbed_total=absorbed_total,
        )

    async def list_vouchers(
        self,
        params: PageParams,
        sort: SortParams,
        *,
        student_id: UUID | None = None,
        status: VoucherStatus | None = None,
        academic_year: str | None = None,
        period_label: str | None = None,
    ) -> Page[FeeVoucherRead]:
        conditions = []
        if student_id is not None:
            conditions.append(FeeVoucher.student_id == student_id)
        if status is not None:
            conditions.append(FeeVoucher.status == status)
        if academic_year is not None:
            conditions.append(FeeVoucher.academic_year == academic_year)
        if period_label is not None:
            conditions.append(FeeVoucher.period_label == period_label)

        rows, total = await self.vouchers.list_with_students(*conditions, params=params, sort=sort)
        return Page.create([self._voucher_read(v) for v in rows], total, params)

    async def get_voucher(self, voucher_id: UUID) -> FeeVoucher:
        voucher = await self.vouchers.get(voucher_id)
        if voucher is None:
            raise NotFoundError("Fee voucher not found.")
        return voucher

    async def get_voucher_detail(self, voucher_id: UUID) -> FeeVoucherDetail:
        voucher = await self.vouchers.get_detail(voucher_id)
        if voucher is None:
            raise NotFoundError("Fee voucher not found.")

        read = self._voucher_read(voucher)
        if voucher.superseded_by_voucher_id is not None:
            # ONE extra query, and only on the detail. The register lists hundreds of
            # rows and would turn this into an N+1; the one screen that needs the
            # replacement's number is the one opened to ask "why is this void?".
            replacement = await self.vouchers.get(voucher.superseded_by_voucher_id)
            if replacement is not None:
                read = read.model_copy(
                    update={"superseded_by_voucher_number": replacement.voucher_number}
                )

        return FeeVoucherDetail(
            **read.model_dump(),
            items=[
                VoucherItemRead(
                    id=item.id,
                    line_type=item.line_type,
                    line_name=item.line_name,
                    head_id=item.head_id,
                    stationery_item_id=item.stationery_item_id,
                    unit_label=item.unit_label,
                    quantity=item.quantity,
                    unit_price=item.unit_price,
                    amount=item.amount,
                    discount_amount=item.discount_amount,
                )
                for item in voucher.items
            ],
            payments=[FeePaymentRead.model_validate(p) for p in voucher.payments],
        )

    async def challan_print_context(self, voucher_ids: Sequence[UUID]) -> ChallanPrintContext:
        """Everything the challan renderer needs, resolved and checked, in one place.

        =================================================================
        WHY SEVERAL VOUCHERS MAY SHARE ONE PRINTED CHALLAN
        =================================================================
            A family paying a term at a time is handed one piece of paper listing
            July, August and September, with one total and one row of challan
            numbers -- that is how the counter wants it, and printing three separate
            challans for one payment produces three part-payments to reconcile.

            The months stay SEPARATE VOUCHERS underneath. Each keeps its own number,
            its own status and its own receipts, so paying two of the three settles
            exactly those two. Merging them into one row to make the printing easier
            would throw that away, and this module's whole position is that an
            issued bill is a fact.

        THE THREE REFUSALS, all of them about the same failure -- a page that bills
        the wrong person or the wrong amount:

          * an id that does not resolve is a 404, never a silently shorter list. RLS
            and the campus predicate make a foreign voucher simply absent, and a
            challan that quietly dropped a month is one a parent underpays.
          * two students on one page is a 422. It is the worst thing this module can
            print: the name band shows one child and the total bills another's fees.
          * a VOID voucher cannot join a combined print. Reprinting a single voided
            challan is legitimate -- it is how an office shows a bill was cancelled,
            and it prints with a VOID band across it -- but folding a cancelled
            charge into a live total asks a family to pay it.
        """
        vouchers = await self.vouchers.list_for_print(voucher_ids)
        found = {voucher.id for voucher in vouchers}
        missing = [str(vid) for vid in voucher_ids if vid not in found]
        if missing:
            raise NotFoundError(f"Fee voucher not found: {', '.join(missing)}.")

        students = {voucher.student_id for voucher in vouchers}
        if len(students) > 1:
            raise ValidationError(
                "One challan cannot bill more than one student.",
                code="CHALLAN_MIXED_STUDENTS",
            )

        if len(vouchers) > 1 and any(v.status is VoucherStatus.VOID for v in vouchers):
            raise ValidationError(
                "A voided challan cannot be combined with others. Print it on its own.",
                code="CHALLAN_VOID_COMBINED",
            )

        school = await self.session.get(School, vouchers[0].school_id)
        if school is None:
            raise NotFoundError("School not found.")

        # Sorted BEFORE anything reads a single voucher out of the set. The repository
        # returns rows in whatever order the planner chose, and both the roll number
        # and the fine rule are looked up by academic year -- so picking "the first
        # one" out of an unordered list would give a different answer on a set
        # spanning two sessions depending on which row came back first.
        ordered = tuple(sorted(vouchers, key=lambda v: (v.due_date, v.voucher_number)))

        return ChallanPrintContext(
            vouchers=ordered,
            school=school,
            roll_number=await self._roll_number_for(ordered[0]),
            late_fee=await self._late_fee_preview(ordered),
            logo=await self._challan_logo(school),
        )

    async def _challan_logo(self, school: School) -> bytes | None:
        """The logo the challan header prints: the campus's own, else the organization's.

        Only inline `data:` uploads are decoded. An `https://` logo is skipped rather
        than fetched -- a challan print must not hang on, or leak a request to, a
        third-party host -- so such a school prints the header with its name alone.
        """
        source = school.logo_url
        if not source:
            organization = await self.session.get(Organization, school.organization_id)
            source = organization.logo_url if organization else None
        if not source or not source.startswith("data:image/") or "," not in source:
            return None
        meta, _, payload = source.partition(",")
        if not meta.endswith(";base64"):
            return None
        try:
            return base64.b64decode(payload, validate=True)
        except binascii.Error:
            return None

    async def _roll_number_for(self, voucher: FeeVoucher) -> str | None:
        """The roll number this student held in the challan's own academic year.

        Not the one they hold today. Roll numbers are re-issued every session in
        register order, so a challan reprinted after promotion would otherwise carry
        next year's number against last year's fees -- and the register the office
        checks it against is sorted by the old one.

        Returns None when the year has no enrollment row, which is a real state: a
        student billed before they were seated. A blank line is better than a wrong
        number, and the renderer simply omits it.
        """
        stmt = (
            select(StudentEnrollment.roll_number)
            .join(AcademicYear, AcademicYear.id == StudentEnrollment.academic_year_id)
            .where(
                StudentEnrollment.student_id == voucher.student_id,
                AcademicYear.name == voucher.academic_year,
                StudentEnrollment.roll_number.is_not(None),
            )
            # The OPEN row first: a student re-seated mid-year has two rows for the
            # year, and the one they are sitting in now is the one the register shows.
            .order_by(
                StudentEnrollment.left_on.is_(None).desc(),
                StudentEnrollment.enrolled_on.desc(),
            )
            .limit(1)
        )
        school_id = get_school_id()
        if school_id is not None:
            stmt = stmt.where(StudentEnrollment.school_id == school_id)
        return (await self.session.execute(stmt)).scalars().first()

    async def _late_fee_preview(self, vouchers: Sequence[FeeVoucher]) -> Decimal:
        """What "Payable After Due Date" adds, under the campus's live fine policy.

        A PREVIEW OF THE FIRST ASSESSMENT ONLY, and deliberately so. `apply_late_fees`
        is the thing that actually fines, and it knows what this challan has already
        earned; this knows only what the rule says about a balance. On a recurring
        policy the real total can grow past this figure -- which is why the line is
        labelled by a date rather than presented as a final amount, and why nothing
        downstream reads it as one.

        Zero when the campus has no policy, when the balance is under the policy's
        floor, or when the fine would round to nothing. The renderer then prints the
        two payable lines as the same figure, which is the truth: this school does
        not charge for paying late.
        """
        policy = await self.late_fee_policies.get_active(vouchers[0].academic_year)
        if policy is None or not policy.is_active:
            return _ZERO

        outstanding = sum((v.outstanding for v in vouchers), _ZERO)
        if outstanding < policy.min_outstanding:
            return _ZERO

        amount = (
            policy.value
            if policy.kind is LateFeeKind.FIXED
            else self._money(outstanding * policy.value / Decimal(100))
        )
        if policy.max_amount is not None:
            amount = min(amount, policy.max_amount)
        return max(amount, _ZERO)

    async def issue_voucher(self, voucher_id: UUID, *, actor_id: UUID | None) -> FeeVoucherDetail:
        voucher = await self.get_voucher(voucher_id)
        if voucher.status is VoucherStatus.VOID:
            raise ConflictError("A voided voucher cannot be issued.")
        if voucher.status is not VoucherStatus.DRAFT:
            # Already issued: return the current state rather than erroring, so a
            # double-clicked button is harmless.
            return await self.get_voucher_detail(voucher_id)

        # BEFORE the status flips, because this may still REPRICE the challan: a
        # reserved challan that took a payment while this one sat in drafts is
        # released, and the arrears line shrinks to match. Repricing is legal only
        # while the voucher is a draft (`_assert_line_editable`), so this is the last
        # moment it can be done -- and doing it after issuing would restate a bill.
        await self._settle_superseded(voucher, actor_id=actor_id)

        await self.vouchers.update(
            voucher, status=VoucherStatus.ISSUED, issued_at=datetime.now(UTC)
        )
        await self._ledger_charge(voucher, actor_id=actor_id)
        await self._audit(
            AuditAction.FEE_VOUCHER_ISSUED,
            entity_type="fee_voucher",
            entity_id=voucher_id,
            actor_id=actor_id,
            before={"status": VoucherStatus.DRAFT.value},
            after={
                "status": VoucherStatus.ISSUED.value,
                "voucher_number": voucher.voucher_number,
                "total": str(voucher.total),
            },
        )
        logger.info("fee_voucher_issued", voucher_id=str(voucher_id))
        return await self.get_voucher_detail(voucher_id)

    async def void_voucher(
        self, voucher_id: UUID, reason: str, *, actor_id: UUID | None
    ) -> FeeVoucherDetail:
        """Cancel a challan. Requires `fee:void` at the route.

        Refused while any non-reversed payment exists: voiding a bill that money was
        received against would make the receipt point at nothing, which is precisely
        how a cash shortfall gets papered over. Reverse the payments first -- each
        reversal is separately audited, and the trail then shows the whole sequence.
        """
        voucher = await self.get_voucher(voucher_id)
        if voucher.status is VoucherStatus.VOID:
            return await self.get_voucher_detail(voucher_id)
        if voucher.status is VoucherStatus.PAID:
            raise ConflictError(
                "A fully paid voucher cannot be voided. Reverse its payments first."
            )

        collected = await self.payments.effective_total(voucher_id)
        if collected > _ZERO:
            raise ConflictError(
                f"This voucher has {voucher.currency} {collected} in recorded payments. "
                "Reverse them before voiding."
            )

        # RELEASE WHAT THIS CHALLAN RESERVED. A consolidating draft holds older
        # challans off the next run; voiding it without letting them go would strand
        # them -- never absorbed, never re-offered, quietly outside every future
        # consolidation while still sitting on the family's balance.
        for reserved in await self.vouchers.reserved_by(voucher_id):
            await self.vouchers.update(reserved, superseded_by_voucher_id=None)

        before = voucher.status.value
        await self.vouchers.update(
            voucher,
            status=VoucherStatus.VOID,
            voided_at=datetime.now(UTC),
            void_reason=reason,
            paid_at=None,
        )
        # Reverse the debit, but ONLY if there was one: voiding a draft cancels a
        # bill that was never raised, and crediting a family for it would hand them
        # money the school never asked for.
        #
        # `has_debit_for` rather than a CHARGE lookup, because a fine debits as a
        # LATE_FEE -- and voiding is the supported way to let a family off one. A
        # CHARGE-only check would cancel the fine challan and leave the penalty on
        # the balance, so the school would believe it had waived something it had not.
        if await self.ledger.has_debit_for(voucher.id):
            await self._ledger_append(
                voucher.student_id,
                entry_type=LedgerEntryType.VOUCHER_VOIDED,
                amount=-voucher.total,
                academic_year=voucher.academic_year,
                occurred_on=date.today(),
                description=f"Challan {voucher.voucher_number} voided",
                organization_id=voucher.organization_id,
                school_id=voucher.school_id,
                voucher_id=voucher.id,
                actor_id=actor_id,
            )
        await self._audit(
            AuditAction.FEE_VOUCHER_VOIDED,
            entity_type="fee_voucher",
            entity_id=voucher_id,
            actor_id=actor_id,
            before={"status": before, "total": str(voucher.total)},
            after={"status": VoucherStatus.VOID.value, "reason": reason},
        )
        logger.info("fee_voucher_voided", voucher_id=str(voucher_id))
        return await self.get_voucher_detail(voucher_id)

    # =====================================================================
    # Ad-hoc charges on a draft challan
    # =====================================================================
    #
    # =====================================================================
    # WHY THIS IS DRAFT-ONLY, AND WHY THAT IS NOT A LIMITATION
    # =====================================================================
    #   Rule 1 of this module is that an issued bill is never rewritten. A parent
    #   holding a challan for 6,500 must not discover at the counter that it now says
    #   6,800 because a clerk added two copies to it this morning -- and a school that
    #   can restate an issued bill has no defence when a parent says the amount
    #   changed after they were given it.
    #
    #   So a charge lands on a DRAFT: generate the period's challans as drafts, walk
    #   the class adding what each student actually took, then issue. That is the
    #   order a school office already works in. For a student who takes something
    #   AFTER their challan went out, the charge belongs on next period's challan --
    #   which is also how the school's own ledger already treats it.
    #
    #   The rule is enforced here rather than by a status check at the route, because
    #   there must be exactly one place that decides whether a bill is still being
    #   assembled.

    async def add_voucher_charge(
        self, voucher_id: UUID, payload: VoucherStationeryInput, *, actor_id: UUID
    ) -> FeeVoucherDetail:
        """Charge a stationery article to one student's draft challan.

        Idempotent by article: sending the same item twice SETS the quantity rather
        than adding a second line. The partial unique index on
        `(voucher_id, stationery_item_id)` enforces the same thing at the storage
        layer, so a concurrent double-submit is a 409 rather than two "Copy" rows.
        """
        voucher = await self.get_voucher(voucher_id)
        self._assert_line_editable(voucher)

        item = await self.get_stationery_item(payload.stationery_item_id)
        if not item.is_active:
            raise ValidationError(
                f"Stationery item '{item.name}' is inactive and cannot be charged.",
                code="STATIONERY_ITEM_INACTIVE",
            )

        # An override is for the real case of a damaged or part-used article sold
        # cheap. Omitted, the catalog price applies -- which is what makes the
        # ordinary path impossible to get wrong.
        unit_price = payload.unit_price if payload.unit_price is not None else item.unit_price
        amount = self._line_total(payload.quantity, unit_price)

        existing = await self.voucher_items.get_stationery_line(voucher_id, item.id)
        if existing is None:
            await self.voucher_items.create(
                voucher_id=voucher.id,
                line_type=FeeLineType.STATIONERY,
                head_id=None,
                stationery_item_id=item.id,
                line_name=item.name,
                unit_label=item.unit.value,
                quantity=payload.quantity,
                unit_price=unit_price,
                amount=amount,
                discount_amount=_ZERO,
                sort_order=await self.voucher_items.max_sort_order(voucher_id) + 1,
                organization_id=voucher.organization_id,
                school_id=voucher.school_id,
            )
            before: dict[str, Any] | None = None
        else:
            before = {"quantity": str(existing.quantity), "amount": str(existing.amount)}
            await self.voucher_items.update(
                existing,
                # The name and unit are RE-SNAPSHOTTED here, not left as they were.
                # The line is still being assembled on a draft, so the current catalog
                # wording is the right wording; freezing happens when the voucher is
                # issued, not when the line is first typed.
                line_name=item.name,
                unit_label=item.unit.value,
                quantity=payload.quantity,
                unit_price=unit_price,
                amount=amount,
            )

        await self._recalculate_lines(voucher)
        await self._audit(
            AuditAction.FEE_VOUCHER_CHARGE_ADDED,
            entity_type="fee_voucher",
            entity_id=voucher_id,
            actor_id=actor_id,
            before=before,
            after={
                "voucher_number": voucher.voucher_number,
                "stationery_item_id": str(item.id),
                "name": item.name,
                "quantity": str(payload.quantity),
                "unit_price": str(unit_price),
                "amount": str(amount),
                "price_overridden": payload.unit_price is not None,
            },
        )
        logger.info(
            "fee_voucher_charge_added",
            voucher_id=str(voucher_id),
            stationery_item_id=str(item.id),
            amount=str(amount),
        )
        return await self.get_voucher_detail(voucher_id)

    async def remove_voucher_charge(
        self, voucher_id: UUID, stationery_item_id: UUID, *, actor_id: UUID
    ) -> FeeVoucherDetail:
        """Take a stationery line back off a draft challan.

        Hard delete, unlike anything in the payment tables. A line on an unissued
        draft is not a financial record -- nothing was billed and nothing was
        received -- so there is no receipt for it to orphan. The audit row is what
        survives, and it carries the amount that was removed.
        """
        voucher = await self.get_voucher(voucher_id)
        self._assert_line_editable(voucher)

        line = await self.voucher_items.get_stationery_line(voucher_id, stationery_item_id)
        if line is None:
            raise NotFoundError("That stationery item is not charged on this challan.")

        before = {
            "stationery_item_id": str(stationery_item_id),
            "name": line.line_name,
            "quantity": str(line.quantity),
            "amount": str(line.amount),
        }
        await self.voucher_items.hard_delete(line.id)
        await self._recalculate_lines(voucher)

        await self._audit(
            AuditAction.FEE_VOUCHER_CHARGE_REMOVED,
            entity_type="fee_voucher",
            entity_id=voucher_id,
            actor_id=actor_id,
            before=before,
            after=None,
        )
        logger.info("fee_voucher_charge_removed", voucher_id=str(voucher_id))
        return await self.get_voucher_detail(voucher_id)

    async def add_voucher_fee_charge(
        self, voucher_id: UUID, payload: VoucherFeeChargeInput, *, actor_id: UUID
    ) -> FeeVoucherDetail:
        """Put one fee head on a single student's draft challan: a fine, a re-exam
        fee, a broken window.

        =================================================================
        WHY THIS EXISTS AS A ROUTE RATHER THAN A WORKAROUND
        =================================================================
            Without it, the only tool an operator has for "charge Ali 500 for the lab
            window" is the CLASS structure -- add a Breakage line, generate, remove
            it next month. That bills the whole grade for one broken window, and the
            error is discovered by forty parents rather than by the school.

            So this is the fee-side twin of the stationery path, and it is
            deliberately shaped the same way: draft-only, idempotent by head,
            re-snapshotting the head's name while the bill is still being assembled.

        IDEMPOTENT BY HEAD, INCLUDING AGAINST THE CLASS STRUCTURE'S OWN LINE. Charging
        a head the structure already priced RESTATES that line rather than adding a
        second one -- which is correct while the challan is a draft (the last word
        wins on a bill still being assembled) and is why the audit row carries the
        figure that was there before.
        """
        voucher = await self.get_voucher(voucher_id)
        self._assert_line_editable(voucher)

        head = await self.get_head(payload.head_id)
        if not head.is_active:
            raise ValidationError(
                f"Fee head '{head.name}' is inactive and cannot be charged.",
                code="FEE_HEAD_INACTIVE",
            )

        line_name = f"{head.name} — {payload.note}" if payload.note else head.name
        existing = await self.voucher_items.get_fee_line(voucher_id, head.id)
        if existing is None:
            await self.voucher_items.create(
                voucher_id=voucher.id,
                line_type=FeeLineType.FEE,
                head_id=head.id,
                stationery_item_id=None,
                line_name=line_name,
                unit_label=None,
                quantity=Decimal(1),
                unit_price=payload.amount,
                amount=payload.amount,
                discount_amount=_ZERO,
                sort_order=await self.voucher_items.max_sort_order(voucher_id) + 1,
                organization_id=voucher.organization_id,
                school_id=voucher.school_id,
            )
            before: dict[str, Any] | None = None
        else:
            before = {"line_name": existing.line_name, "amount": str(existing.amount)}
            await self.voucher_items.update(
                existing,
                line_name=line_name,
                quantity=Decimal(1),
                unit_price=payload.amount,
                amount=payload.amount,
                # The concession is recomputed at generation, not here. A one-off
                # charge is not what a scholarship was awarded against, and silently
                # discounting a breakage fine is not something anyone agreed.
                discount_amount=_ZERO,
            )

        await self._recalculate_lines(voucher)
        await self._audit(
            AuditAction.FEE_VOUCHER_CHARGE_ADDED,
            entity_type="fee_voucher",
            entity_id=voucher_id,
            actor_id=actor_id,
            before=before,
            after={
                "voucher_number": voucher.voucher_number,
                "head_id": str(head.id),
                "name": line_name,
                "amount": str(payload.amount),
                "restated_structure_line": before is not None,
            },
        )
        logger.info(
            "fee_voucher_fee_charge_added",
            voucher_id=str(voucher_id),
            head_id=str(head.id),
            amount=str(payload.amount),
        )
        return await self.get_voucher_detail(voucher_id)

    async def remove_voucher_fee_charge(
        self, voucher_id: UUID, head_id: UUID, *, actor_id: UUID
    ) -> FeeVoucherDetail:
        """Take a fee line back off a draft challan.

        Hard delete, like its stationery twin: a line on an unissued draft is not a
        financial record -- nothing was billed and nothing was received -- so there is
        no receipt for it to orphan. The audit row carries the amount that went.

        It will happily remove a line the CLASS structure put there. That is the
        supported way to say "this student is not paying the exam fee this term"
        without touching the structure every other student is billed from; the
        standing version of the same intent is an EXCLUDED assignment.
        """
        voucher = await self.get_voucher(voucher_id)
        self._assert_line_editable(voucher)

        line = await self.voucher_items.get_fee_line(voucher_id, head_id)
        if line is None:
            raise NotFoundError("That fee head is not charged on this challan.")

        before = {
            "head_id": str(head_id),
            "name": line.line_name,
            "amount": str(line.amount),
            "discount_amount": str(line.discount_amount),
        }
        await self.voucher_items.hard_delete(line.id)
        await self._recalculate_lines(voucher)

        await self._audit(
            AuditAction.FEE_VOUCHER_CHARGE_REMOVED,
            entity_type="fee_voucher",
            entity_id=voucher_id,
            actor_id=actor_id,
            before=before,
            after=None,
        )
        logger.info(
            "fee_voucher_fee_charge_removed", voucher_id=str(voucher_id), head_id=str(head_id)
        )
        return await self.get_voucher_detail(voucher_id)

    # =====================================================================
    # Payments
    # =====================================================================

    async def record_payment(
        self, voucher_id: UUID, payload: FeePaymentCreate, *, actor_id: UUID
    ) -> FeePaymentRead:
        voucher = await self.get_voucher(voucher_id)

        if voucher.status is VoucherStatus.VOID:
            raise ConflictError("Payments cannot be recorded against a voided voucher.")
        if voucher.status is VoucherStatus.DRAFT:
            # A draft has not reached the parent, so money against it is a
            # mis-selection in the UI, not an early payment.
            raise ConflictError("Issue this voucher before recording a payment against it.")

        outstanding = voucher.total - voucher.paid_total
        if payload.amount > outstanding:
            # STILL REJECTED, even though slice 2 added a ledger that could hold the
            # credit. Accepting an overpayment is a separate decision from recording
            # one: it needs an allocation rule (which older challan does the excess
            # settle?) and a refund path, and neither has been agreed. Taking the
            # money now and deciding later is how a school ends up holding balances
            # it cannot explain. A genuine advance is a ledger `adjustment`, which is
            # audited and names who accepted it.
            raise ValidationError(
                f"Payment of {payload.amount} exceeds the outstanding balance of {outstanding}.",
                code="PAYMENT_EXCEEDS_OUTSTANDING",
                details={"outstanding": str(outstanding), "currency": voucher.currency},
            )

        received_on = payload.received_on or date.today()
        prefix = f"RC-{received_on.year}-"
        sequence = await self.payments.next_sequence(prefix)

        payment = await self.payments.create(
            voucher_id=voucher.id,
            receipt_number=f"{prefix}{sequence:05d}",
            amount=payload.amount,
            currency=voucher.currency,
            method=payload.method,
            reference=payload.reference,
            received_on=received_on,
            received_by_user_id=payload.received_by_user_id or actor_id,
            notes=payload.notes,
            status=FeePaymentStatus.RECORDED,
            # Inherited from the voucher, so a receipt can never be scoped
            # differently from the bill it settles.
            organization_id=voucher.organization_id,
            school_id=voucher.school_id,
        )

        await self._recalculate(voucher)
        await self._ledger_append(
            voucher.student_id,
            entry_type=LedgerEntryType.PAYMENT,
            # Negative: money in reduces what the family owes. The ledger's single
            # signed column is what keeps every consumer from re-deriving direction.
            amount=-payment.amount,
            academic_year=voucher.academic_year,
            occurred_on=received_on,
            description=f"Receipt {payment.receipt_number} ({voucher.voucher_number})",
            organization_id=voucher.organization_id,
            school_id=voucher.school_id,
            voucher_id=voucher.id,
            payment_id=payment.id,
            actor_id=actor_id,
        )
        await self._audit(
            AuditAction.FEE_PAYMENT_RECORDED,
            entity_type="fee_payment",
            entity_id=payment.id,
            actor_id=actor_id,
            after={
                "receipt_number": payment.receipt_number,
                "voucher_number": voucher.voucher_number,
                "amount": str(payment.amount),
                "method": payment.method.value,
            },
        )
        logger.info(
            "fee_payment_recorded",
            payment_id=str(payment.id),
            voucher_id=str(voucher_id),
            amount=str(payment.amount),
        )
        return FeePaymentRead.model_validate(payment)

    async def list_payments(self, voucher_id: UUID) -> list[FeePaymentRead]:
        await self.get_voucher(voucher_id)  # 404 for an unknown or cross-tenant voucher
        rows = await self.payments.list_for_voucher(voucher_id)
        return [FeePaymentRead.model_validate(p) for p in rows]

    async def reverse_payment(
        self, payment_id: UUID, reason: str, *, actor_id: UUID
    ) -> FeePaymentRead:
        """Undo a receipt. Requires `fee:void` at the route.

        The row stays and flips to REVERSED rather than being deleted: a reversed
        receipt is part of the trail, and a receipt number that simply disappears is
        indistinguishable from one that was never issued.
        """
        payment = await self.payments.get(payment_id)
        if payment is None:
            raise NotFoundError("Payment not found.")
        if payment.status is FeePaymentStatus.REVERSED:
            raise ConflictError("This payment has already been reversed.")

        await self.payments.update(
            payment,
            status=FeePaymentStatus.REVERSED,
            reversed_at=datetime.now(UTC),
            reversal_reason=reason,
        )

        voucher = await self.get_voucher(payment.voucher_id)
        await self._recalculate(voucher)
        await self._ledger_append(
            voucher.student_id,
            entry_type=LedgerEntryType.PAYMENT_REVERSED,
            # Positive: undoing a receipt puts the debt back. A NEW entry rather than
            # a correction to the old one -- the statement must show that money
            # arrived and was then reversed, which is exactly the sequence a family
            # disputing a balance needs to see.
            amount=payment.amount,
            academic_year=voucher.academic_year,
            occurred_on=date.today(),
            description=f"Receipt {payment.receipt_number} reversed",
            organization_id=voucher.organization_id,
            school_id=voucher.school_id,
            voucher_id=voucher.id,
            payment_id=payment.id,
            actor_id=actor_id,
        )

        await self._audit(
            AuditAction.FEE_PAYMENT_REVERSED,
            entity_type="fee_payment",
            entity_id=payment_id,
            actor_id=actor_id,
            before={"status": FeePaymentStatus.RECORDED.value, "amount": str(payment.amount)},
            after={"status": FeePaymentStatus.REVERSED.value, "reason": reason},
        )
        logger.info("fee_payment_reversed", payment_id=str(payment_id))
        return FeePaymentRead.model_validate(payment)

    # =====================================================================
    # Collection summary
    # =====================================================================

    async def summary(self, academic_year: str, period_label: str | None) -> FeeSummary:
        """Billed / collected / outstanding for a year, optionally one period.

        Three queries regardless of school size: one grouped roll-up, one overdue sum,
        one stationery sum. Flat in the number of vouchers, which is the only figure
        here that grows without bound.
        `outstanding` is `billed - collected` rather than a third aggregate, because
        two independently computed figures that must agree eventually will not.
        """
        rows = await self.vouchers.summary_rows(academic_year, period_label)
        today = date.today()
        overdue = await self.vouchers.overdue_total(academic_year, period_label, today)
        stationery = await self.vouchers.stationery_billed_total(academic_year, period_label)

        by_status = [
            VoucherStatusCount(status=status, count=count, total=total)
            for status, count, total, _ in rows
        ]
        # VOID and DRAFT excluded from the money: a voided bill is not owed, and a
        # draft has not been sent, so counting either as revenue overstates the book.
        billable = [r for r in rows if r[0] not in {VoucherStatus.VOID, VoucherStatus.DRAFT}]
        billed = sum((r[2] for r in billable), _ZERO)
        collected = sum((r[3] for r in billable), _ZERO)

        return FeeSummary(
            academic_year=academic_year,
            period_label=period_label,
            currency="PKR",
            billed=billed,
            collected=collected,
            outstanding=billed - collected,
            overdue=overdue,
            stationery_billed=stationery,
            voucher_count=sum(r[1] for r in rows),
            by_status=by_status,
        )

    # =====================================================================
    # Concessions -- the named scholarship a family is put ON
    # =====================================================================

    async def create_concession(
        self, payload: FeeConcessionCreate, *, actor_id: UUID
    ) -> FeeConcessionRead:
        if await self.concessions.get_by_code(payload.code):
            raise ConflictError(f"A concession with code '{payload.code}' already exists.")

        concession = await self.concessions.create(
            **payload.model_dump(),
            organization_id=require_organization_id(),
            school_id=require_school_id(),
        )
        await self._audit(
            AuditAction.FEE_CONCESSION_CREATED,
            entity_type="fee_concession",
            entity_id=concession.id,
            actor_id=actor_id,
            after={
                "code": concession.code,
                "name": concession.name,
                "kind": concession.kind.value,
                "value": str(concession.value),
            },
        )
        logger.info("fee_concession_created", concession_id=str(concession.id))
        return self._concession_read(concession)

    async def list_concessions(
        self, params: PageParams, sort: SortParams, *, is_active: bool | None = None
    ) -> Page[FeeConcessionRead]:
        conditions: list[ColumnElement[bool]] = []
        if is_active is not None:
            conditions.append(FeeConcession.is_active.is_(is_active))
        rows, total = await self.concessions.list(*conditions, params=params, sort=sort)

        # The headcount per scheme, one query per row on a page of at most a hundred
        # schemes -- a school runs six. Worth it: "what does merit cost us?" is the
        # question this screen exists to answer, and a list that cannot answer it
        # sends the principal to a spreadsheet.
        return Page.create(
            [
                self._concession_read(
                    row, student_count=await self.assignments.concession_usage_count(row.id)
                )
                for row in rows
            ],
            total,
            params,
        )

    async def get_concession(self, concession_id: UUID) -> FeeConcession:
        concession = await self.concessions.get(concession_id)
        if concession is None:
            raise NotFoundError("Concession not found.")
        return concession

    async def update_concession(
        self, concession_id: UUID, payload: FeeConcessionUpdate, *, actor_id: UUID
    ) -> FeeConcessionRead:
        """Revise a scheme. Takes effect on the NEXT generation run.

        Challans already issued snapshotted their discount and are never restated --
        the same rule that governs repricing a structure. So raising the staff
        remission in March does not retroactively credit February, which is both what
        the accounts require and what the school actually means.
        """
        concession = await self.get_concession(concession_id)
        changes = payload.model_dump(exclude_unset=True)
        if not changes:
            return self._concession_read(concession)

        before = {"kind": concession.kind.value, "value": str(concession.value)}
        merged_kind = changes.get("kind", concession.kind)
        merged_value = changes.get("value", concession.value)
        # Re-checked on the merged result, not on the payload: sending `kind:
        # percent` alone against a stored value of 5000 is a valid-looking request
        # that produces a 5000% scheme, and the field-level validator cannot see it.
        if merged_kind is ConcessionKind.PERCENT and merged_value > Decimal(100):
            raise ValidationError(
                "A percentage concession cannot exceed 100%.",
                code="CONCESSION_PERCENT_OUT_OF_RANGE",
            )

        await self.concessions.update(concession, **changes)
        await self._audit(
            AuditAction.FEE_CONCESSION_UPDATED,
            entity_type="fee_concession",
            entity_id=concession_id,
            actor_id=actor_id,
            before=before,
            after={"kind": concession.kind.value, "value": str(concession.value)},
        )
        logger.info("fee_concession_updated", concession_id=str(concession_id))
        return self._concession_read(concession)

    async def delete_concession(self, concession_id: UUID, *, actor_id: UUID) -> None:
        """Refuse while any student is still on the scheme.

        Cascading would silently restore those families to full fees, and nobody
        would find out until the challans printed. Deactivating is the retirement
        path: the scheme leaves the picker while the children on it keep their rate.
        """
        concession = await self.get_concession(concession_id)
        on_students = await self.assignments.concession_usage_count(concession_id)
        if on_students:
            raise ConflictError(
                f"{on_students} student arrangement(s) use this concession. "
                "Deactivate it instead, or move those students off it first."
            )

        await self.concessions.soft_delete(concession)
        await self._audit(
            AuditAction.FEE_CONCESSION_DELETED,
            entity_type="fee_concession",
            entity_id=concession_id,
            actor_id=actor_id,
            before={"code": concession.code, "name": concession.name},
        )
        logger.info("fee_concession_deleted", concession_id=str(concession_id))

    # =====================================================================
    # Late fee policy, and the run that applies it
    # =====================================================================

    async def set_late_fee_policy(
        self, payload: LateFeePolicyCreate, *, actor_id: UUID
    ) -> LateFeePolicyRead:
        """Create or replace this school's fine rule for one academic year.

        Idempotent by year: sending it twice REVISES the year's policy rather than
        creating a second one, which is also what `uq_fee_late_fee_policies_one_active`
        enforces. Two live policies would make the fine a family owes depend on which
        row the job read first.
        """
        head = await self.get_head(payload.head_id)
        if not head.is_active:
            raise ValidationError(
                f"Fee head '{head.name}' is inactive and cannot carry late fees.",
                code="FEE_HEAD_INACTIVE",
            )

        existing = await self.late_fee_policies.get_active(payload.academic_year)
        values = payload.model_dump()
        if existing is None:
            policy = await self.late_fee_policies.create(
                **values,
                organization_id=require_organization_id(),
                school_id=require_school_id(),
            )
            before: dict[str, Any] | None = None
        else:
            before = {
                "kind": existing.kind.value,
                "value": str(existing.value),
                "grace_days": existing.grace_days,
                "recurrence": existing.recurrence.value,
            }
            policy = await self.late_fee_policies.update(existing, **values)

        await self._audit(
            AuditAction.FEE_LATE_FEE_POLICY_SET,
            entity_type="fee_late_fee_policy",
            entity_id=policy.id,
            actor_id=actor_id,
            before=before,
            after={
                "academic_year": policy.academic_year,
                "kind": policy.kind.value,
                "value": str(policy.value),
                "grace_days": policy.grace_days,
                "recurrence": policy.recurrence.value,
                "max_amount": str(policy.max_amount) if policy.max_amount else None,
                "is_active": policy.is_active,
            },
        )
        logger.info("fee_late_fee_policy_set", policy_id=str(policy.id))
        return self._policy_read(policy, head)

    async def list_late_fee_policies(
        self, academic_year: str | None = None
    ) -> list[LateFeePolicyRead]:
        rows = await self.late_fee_policies.list_for_year(academic_year)
        return [self._policy_read(row, row.head) for row in rows]

    async def delete_late_fee_policy(self, policy_id: UUID, *, actor_id: UUID) -> None:
        """Retire a rule. The fines it already raised are untouched.

        Soft-deleted rather than hard: "what rule produced this 200?" is asked months
        later, and a policy that vanished cannot answer it.
        """
        policy = await self.late_fee_policies.get(policy_id)
        if policy is None:
            raise NotFoundError("Late fee policy not found.")

        await self.late_fee_policies.soft_delete(policy)
        await self._audit(
            AuditAction.FEE_LATE_FEE_POLICY_DELETED,
            entity_type="fee_late_fee_policy",
            entity_id=policy_id,
            actor_id=actor_id,
            before={"academic_year": policy.academic_year, "name": policy.name},
        )
        logger.info("fee_late_fee_policy_deleted", policy_id=str(policy_id))

    async def apply_late_fees(
        self,
        academic_year: str,
        *,
        actor_id: UUID | None = None,
        today: date | None = None,
        limit: int = MAX_LATE_FEE_BATCH,
    ) -> LateFeeRunResult:
        """Fine every overdue challan the active policy matches.

        =================================================================
        A FINE IS A NEW CHALLAN, NOT AN EXTRA LINE ON THE LATE ONE
        =================================================================
            Rule 1 of this module is that an issued bill is never rewritten. A parent
            holding a challan for 6,500 must not discover at the counter that it now
            says 6,700 because a job ran overnight -- and a school that can restate an
            issued bill has no defence when a parent says the amount changed.

            So the fine is MINTED as its own voucher: its own number, its own line
            under the policy's head, payable, printable and voidable through exactly
            the machinery staff already use. Letting a family off is voiding that
            challan, with a reason, audited -- which is a far better record than a
            line quietly deleted from someone else's bill.

        =================================================================
        IDEMPOTENT, BECAUSE THIS RUNS ON A SCHEDULE AND WILL BE RE-RUN
        =================================================================
            Three independent guards, because a job that double-fines is a job a
            school switches off after the first Monday:

              1. `fines_for_source` counts what this challan already earned, so a
                 ONCE policy never fires twice and a recurring one only fires when a
                 further interval has actually elapsed.
              2. `max_amount` caps the total, measured against what was already
                 charged rather than against this assessment alone.
              3. `uq_fee_vouchers_student_period` (partial, excluding voids) refuses a
                 duplicate at the storage layer even if the first two were somehow
                 both wrong -- so the worst case is a 409, not a family fined twice.

            Fines are excluded from the candidate set (`origin = regular`), so a fine
            can never itself go overdue and earn a fine. Without that the policy
            compounds and a 200 rupee penalty reaches four figures unattended.
        """
        today = today or date.today()
        result = LateFeeRunResult(
            academic_year=academic_year,
            considered=0,
            assessed=0,
            total_charged=_ZERO,
            skipped=0,
            skipped_reasons={},
            voucher_ids=[],
        )

        policy = await self.late_fee_policies.get_active(academic_year)
        if policy is None:
            # Not an error. Most schools run no fine policy, and a job that raised
            # here would fill the logs of every one of them every night.
            logger.info("fee_late_fee_no_policy", academic_year=academic_year)
            return result

        cutoff = today - timedelta(days=policy.grace_days)
        candidates = await self.vouchers.overdue_candidates(academic_year, cutoff, limit=limit + 1)
        result.truncated = len(candidates) > limit
        candidates = candidates[:limit]
        result.considered = len(candidates)

        def skip(reason: str) -> None:
            result.skipped += 1
            result.skipped_reasons[reason] = result.skipped_reasons.get(reason, 0) + 1

        prefix = f"LF-{today.year}-"
        sequence = await self.vouchers.next_sequence(prefix)
        now = datetime.now(UTC)

        for source in candidates:
            outstanding = source.total - source.paid_total
            if outstanding < policy.min_outstanding:
                skip("below_minimum")
                continue

            already_count, already_charged = await self.vouchers.fines_for_source(source.id)
            earned = self._assessments_earned(policy, source.due_date, today)
            if already_count >= earned:
                skip("already_assessed")
                continue

            amount = (
                policy.value
                if policy.kind is LateFeeKind.FIXED
                else self._money(outstanding * policy.value / Decimal(100))
            )
            if policy.max_amount is not None:
                remaining = policy.max_amount - already_charged
                if remaining <= _ZERO:
                    skip("cap_reached")
                    continue
                amount = min(amount, remaining)
            if amount <= _ZERO:
                skip("zero_amount")
                continue

            suffix = "" if policy.recurrence is LateFeeRecurrence.ONCE else f" {already_count + 1}"
            fine = await self._create_late_fee_voucher(
                policy=policy,
                source=source,
                amount=amount,
                voucher_number=f"{prefix}{sequence:05d}",
                period_label=f"{source.period_label} late fee{suffix}"[:40],
                today=today,
                now=now,
                actor_id=actor_id,
            )
            sequence += 1
            result.assessed += 1
            result.total_charged += amount
            result.voucher_ids.append(fine.id)

        await self._audit(
            AuditAction.FEE_LATE_FEE_APPLIED,
            entity_type="fee_late_fee_policy",
            entity_id=policy.id,
            actor_id=actor_id,
            after={
                "academic_year": academic_year,
                "considered": result.considered,
                "assessed": result.assessed,
                "total_charged": str(result.total_charged),
                "skipped": result.skipped,
                "truncated": result.truncated,
            },
        )
        logger.info(
            "fee_late_fees_applied",
            academic_year=academic_year,
            assessed=result.assessed,
            skipped=result.skipped,
            truncated=result.truncated,
        )
        return result

    # =====================================================================
    # Unattended monthly generation
    # =====================================================================
    #
    # =====================================================================
    # THE CRON IS DUMB ON PURPOSE
    # =====================================================================
    #   The scheduler outside this process knows one thing: run daily. Everything
    #   that varies per school -- which day, how long parents get to pay, drafts or
    #   issued, whether arrears are carried -- is a row the owner can read and change.
    #
    #   The alternative, a crontab per tenant, puts the school's own billing day in a
    #   file the school cannot see, cannot change without an engineer, and which
    #   silently disagrees with what the settings screen claims.
    #
    # WHY THE RUN IS SAFE TO REPEAT
    #   `last_run_period` is a bookmark, not a lock. The real duplicate guard is the
    #   partial unique index on `fee_vouchers` (school, student, year, period), which
    #   makes a second pass SKIP the students it already billed. That is what turns a
    #   crashed half-run into something you fix by running it again, and what stops a
    #   retried container from billing a class twice.

    async def get_billing_schedule(self, academic_year: str) -> FeeBillingScheduleRead | None:
        schedule = await self.billing_schedules.get_for_year(academic_year)
        return None if schedule is None else await self._schedule_read(schedule)

    async def set_billing_schedule(
        self, payload: FeeBillingScheduleInput, *, actor_id: UUID
    ) -> FeeBillingScheduleRead:
        """Create or revise this campus's automatic billing.

        UPSERT BY YEAR, like the structure-item route: sending it twice revises the
        schedule rather than creating a second one, which is what the partial unique
        index enforces anyway. An owner cannot end up with two rows disagreeing about
        when their parents are billed.
        """
        head: FeeHead | None = None
        if payload.carry_forward_head_id is not None:
            # RESOLVED, not merely accepted: a head from another campus is filtered
            # out by the school predicate and reads as absent, so this 404s rather
            # than storing a key the 2am run would fail to price.
            head = await self.get_head(payload.carry_forward_head_id)
            if payload.carry_forward_dues and not head.is_active:
                raise ValidationError(
                    f"Fee head '{head.name}' is inactive and cannot carry dues forward.",
                    code="FEE_HEAD_INACTIVE",
                )

        existing = await self.billing_schedules.get_for_year(payload.academic_year)
        values: dict[str, Any] = {
            "is_active": payload.is_active,
            "generate_day": payload.generate_day,
            "due_day_offset": payload.due_day_offset,
            "issue_immediately": payload.issue_immediately,
            "include_stationery": payload.include_stationery,
            "carry_forward_dues": payload.carry_forward_dues,
            "carry_forward_head_id": payload.carry_forward_head_id,
        }
        if existing is None:
            schedule = await self.billing_schedules.create(
                academic_year=payload.academic_year,
                **values,
                organization_id=require_organization_id(),
                school_id=require_school_id(),
            )
            before: dict[str, Any] | None = None
        else:
            before = {
                "is_active": existing.is_active,
                "generate_day": existing.generate_day,
                "due_day_offset": existing.due_day_offset,
                "issue_immediately": existing.issue_immediately,
                "carry_forward_dues": existing.carry_forward_dues,
            }
            schedule = await self.billing_schedules.update(existing, **values)

        await self._audit(
            AuditAction.FEE_BILLING_SCHEDULE_SET,
            entity_type="fee_billing_schedule",
            entity_id=schedule.id,
            actor_id=actor_id,
            before=before,
            after={
                "academic_year": payload.academic_year,
                **{key: str(value) for key, value in values.items()},
            },
        )
        logger.info(
            "fee_billing_schedule_set",
            academic_year=payload.academic_year,
            generate_day=payload.generate_day,
            is_active=payload.is_active,
        )
        return await self._schedule_read(schedule)

    async def run_scheduled_generation(
        self,
        academic_year: str,
        *,
        actor_id: UUID | None,
        today: date | None = None,
        force: bool = False,
    ) -> BillingRunResult:
        """Bill every active structure for the period that is due, once.

        `force` is what the settings screen's "Run now" passes: it skips the
        is-it-the-day test but NOT the already-generated one, so an owner can bill
        early without being able to bill a period twice by clicking twice.

        Returns a result rather than raising when nothing is due. "Today is not your
        billing day" is the answer on 29 days out of 30 and is not an error -- an
        exception there would fill the job's logs with failures that mean success.
        """
        today = today or date.today()
        schedule = await self.billing_schedules.get_active(academic_year)
        if schedule is None:
            return BillingRunResult(
                academic_year=academic_year, reason="No active billing schedule for this year."
            )

        if not force and today.day != schedule.generate_day:
            # NOT a catch-up window. A missed day is caught by the next month's run
            # rather than by billing late, because a run that fires on the 3rd for a
            # schedule that says the 1st produces challans dated in a way no parent's
            # standing instruction expects. `force` exists for the operator who
            # genuinely needs it, with their name on the audit row.
            return BillingRunResult(
                academic_year=academic_year,
                reason=f"Not the billing day — this campus bills on day {schedule.generate_day}.",
            )

        period_label = f"{today.year:04d}-{today.month:02d}"
        if schedule.last_run_period == period_label:
            return BillingRunResult(
                academic_year=academic_year,
                period_label=period_label,
                reason=f"{period_label} has already been generated.",
            )

        structures = await self.structures.list_active_for_year(academic_year)
        if not structures:
            return BillingRunResult(
                academic_year=academic_year,
                period_label=period_label,
                reason="No active fee structure for this year.",
            )

        due_date = today + timedelta(days=schedule.due_day_offset)
        created = skipped = absorbed_vouchers = 0
        absorbed_total = _ZERO
        truncated = False
        for structure in structures:
            # A structure with no priced lines raises rather than returning, and one
            # empty class must not abort the other seventeen -- the failure mode this
            # whole feature exists to remove is a class quietly going unbilled.
            try:
                result = await self.generate_vouchers(
                    VoucherGenerateRequest(
                        structure_id=structure.id,
                        period_label=period_label,
                        issue_date=today,
                        due_date=due_date,
                        issue_immediately=schedule.issue_immediately,
                        include_stationery=schedule.include_stationery,
                        carry_forward_dues=schedule.carry_forward_dues,
                        carry_forward_head_id=schedule.carry_forward_head_id,
                        notes=None,
                    ),
                    actor_id=actor_id,
                )
            except (ValidationError, ConflictError) as exc:
                logger.warning(
                    "fee_scheduled_generation_structure_failed",
                    structure_id=str(structure.id),
                    academic_year=academic_year,
                    period_label=period_label,
                    error=str(exc),
                )
                continue
            created += result.created
            skipped += len(result.skipped)
            absorbed_vouchers += result.absorbed_vouchers
            absorbed_total += result.absorbed_total
            truncated = truncated or result.truncated

        await self.billing_schedules.update(
            schedule,
            last_run_period=period_label,
            last_run_at=datetime.now(UTC),
            last_run_created=created,
            last_run_skipped=skipped,
        )
        await self._audit(
            AuditAction.FEE_BILLING_RUN_COMPLETED,
            entity_type="fee_billing_schedule",
            entity_id=schedule.id,
            actor_id=actor_id,
            after={
                "academic_year": academic_year,
                "period_label": period_label,
                "structures": len(structures),
                "created": created,
                "skipped": skipped,
                "forced": force,
            },
        )
        logger.info(
            "fee_scheduled_generation_complete",
            academic_year=academic_year,
            period_label=period_label,
            structures=len(structures),
            created=created,
            skipped=skipped,
            truncated=truncated,
        )
        return BillingRunResult(
            academic_year=academic_year,
            period_label=period_label,
            ran=True,
            structures=len(structures),
            created=created,
            skipped=skipped,
            absorbed_vouchers=absorbed_vouchers,
            absorbed_total=absorbed_total,
            truncated=truncated,
        )

    async def _schedule_read(self, schedule: FeeBillingSchedule) -> FeeBillingScheduleRead:
        head_name: str | None = None
        if schedule.carry_forward_head_id is not None:
            head = await self.heads.get(schedule.carry_forward_head_id)
            head_name = head.name if head else None
        return FeeBillingScheduleRead(
            id=schedule.id,
            academic_year=schedule.academic_year,
            is_active=schedule.is_active,
            generate_day=schedule.generate_day,
            due_day_offset=schedule.due_day_offset,
            issue_immediately=schedule.issue_immediately,
            include_stationery=schedule.include_stationery,
            carry_forward_dues=schedule.carry_forward_dues,
            carry_forward_head_id=schedule.carry_forward_head_id,
            carry_forward_head_name=head_name,
            last_run_period=schedule.last_run_period,
            last_run_at=schedule.last_run_at,
            last_run_created=schedule.last_run_created,
            last_run_skipped=schedule.last_run_skipped,
            next_run_on=self._next_run_on(schedule),
            created_at=schedule.created_at,
            updated_at=schedule.updated_at,
        )

    @staticmethod
    def _next_run_on(schedule: FeeBillingSchedule, today: date | None = None) -> date | None:
        """When this schedule fires next, or None while it is paused.

        Computed here rather than in the browser because the answer depends on which
        period has already been billed -- a screen deriving it from the clock alone
        tells a school that billed this morning that it bills again today.

        `generate_day` is capped at 28 by the schema and the CHECK, so this can never
        construct an invalid date. That cap is the reason no clamping logic is needed
        here, and the reason February cannot move a school's billing day.
        """
        if not schedule.is_active:
            return None
        today = today or date.today()
        this_month = today.replace(day=schedule.generate_day)
        already_ran = schedule.last_run_period == f"{today.year:04d}-{today.month:02d}"
        if this_month >= today and not already_ran:
            return this_month
        # First of next month, then moved to the billing day -- `replace(month=...)`
        # cannot be used directly because December has no thirteenth month.
        next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        return next_month.replace(day=schedule.generate_day)

    # =====================================================================
    # The student ledger
    # =====================================================================

    async def get_student_ledger(
        self, student_id: UUID, params: PageParams
    ) -> StudentLedgerStatement:
        """One family's account: the balance, and the movements that produced it."""
        student = await self._get_student(student_id)
        entries, total = await self.ledger.list_for_student(student_id, params)
        return StudentLedgerStatement(
            student_id=student.id,
            student_name=student.full_name,
            admission_number=student.admission_number,
            balance=await self.ledger.balance_for(student_id),
            entries=[LedgerEntryRead.model_validate(entry) for entry in entries],
            total_entries=total,
        )

    async def adjust_ledger(
        self, student_id: UUID, payload: LedgerAdjustmentInput, *, actor_id: UUID
    ) -> StudentLedgerStatement:
        """Move a family's balance by hand. Requires `fee:void` at the route.

        The one action in this module that moves money with no voucher and no receipt
        behind it, which is exactly why it does not sit under `fee:collect`. The same
        separation of duties that stops the person recording payments from being the
        person who can reverse them stops them from being the person who can write a
        balance off.
        """
        student = await self._get_student(student_id)
        entry = await self._ledger_append(
            student.id,
            entry_type=LedgerEntryType.ADJUSTMENT,
            amount=payload.amount,
            academic_year=payload.academic_year,
            occurred_on=payload.occurred_on or date.today(),
            description=payload.description,
            organization_id=student.organization_id,
            school_id=student.school_id,
            actor_id=actor_id,
        )

        await self._audit(
            AuditAction.FEE_LEDGER_ADJUSTED,
            entity_type="student",
            entity_id=student_id,
            actor_id=actor_id,
            after={
                "amount": str(payload.amount),
                "balance_after": str(entry.balance_after),
                "academic_year": payload.academic_year,
                "description": payload.description,
            },
        )
        logger.info("fee_ledger_adjusted", student_id=str(student_id), amount=str(payload.amount))
        return await self.get_student_ledger(student_id, params=PageParams())

    async def reconcile_ledger(self) -> dict[UUID, tuple[Decimal, Decimal]]:
        """Every student whose ledger balance disagrees with their vouchers.

        THE LEDGER IS A RECORD, NOT THE SOURCE OF TRUTH. `fee_vouchers` and
        `fee_payments` remain authoritative; this compares the two and REPORTS the
        difference rather than silently rewriting either. A repair that ran
        automatically would hide the bug that caused the drift, and the bug is the
        thing worth finding -- a balance that quietly corrects itself every night is
        indistinguishable from one that was right all along.

        Adjustments are the expected legitimate difference: a written-off balance
        moves the ledger and touches no voucher. So this reports rather than alarms,
        and the operator reads the statement to see which it is.
        """
        ledger_balances = await self.ledger.charged_totals()
        voucher_balances = await self.ledger.outstanding_by_student()

        drift: dict[UUID, tuple[Decimal, Decimal]] = {}
        for student_id in set(ledger_balances) | set(voucher_balances):
            ledger_total = ledger_balances.get(student_id, _ZERO)
            voucher_total = voucher_balances.get(student_id, _ZERO)
            if ledger_total != voucher_total:
                drift[student_id] = (ledger_total, voucher_total)
        return drift

    # =====================================================================
    # Export
    # =====================================================================

    async def export_vouchers_csv(
        self,
        *,
        academic_year: str | None = None,
        period_label: str | None = None,
        status: VoucherStatus | None = None,
        limit: int = MAX_EXPORT_ROWS,
    ) -> str:
        """The voucher register as CSV.

        =================================================================
        WHY A CAP, AND WHY IT IS WRITTEN INTO THE FILE
        =================================================================
            This is the one read in the module a user can aim at every row the school
            has ever produced. Streaming a million of them holds a connection open
            long enough to matter, so the row count is capped.

            The cap is announced in a trailing comment IN THE FILE rather than only in
            a header, because the failure it guards against is someone opening the
            spreadsheet a week later, seeing 5,000 tidy rows, and reconciling against
            a year that had 7,000. A truncated export that reads as a complete one is
            worse than a refused one.

        Written with `csv` rather than string joins because a student named
        O'Brien, or a note containing a comma, breaks naive quoting -- and it breaks
        it silently, shifting every subsequent column by one.
        """
        conditions: list[ColumnElement[bool]] = []
        if academic_year is not None:
            conditions.append(FeeVoucher.academic_year == academic_year)
        if period_label is not None:
            conditions.append(FeeVoucher.period_label == period_label)
        if status is not None:
            conditions.append(FeeVoucher.status == status)

        rows = await self.vouchers.export_rows(*conditions, limit=limit + 1)
        truncated = len(rows) > limit
        rows = rows[:limit]

        buffer = StringIO()
        writer = csv.writer(buffer)
        writer.writerow(
            [
                "voucher_number",
                "admission_number",
                "student_name",
                "academic_year",
                "period_label",
                "origin",
                "issue_date",
                "due_date",
                "status",
                "currency",
                "subtotal",
                "discount_total",
                "total",
                "paid_total",
                "outstanding",
                "arrears_brought_forward",
            ]
        )
        for voucher in rows:
            # Through `_voucher_read` so the exported status matches what the screen
            # shows -- OVERDUE is derived on read in this module, and an export that
            # reported the stored status would disagree with the list beside it.
            read = self._voucher_read(voucher)
            writer.writerow(
                [
                    read.voucher_number,
                    read.admission_number,
                    read.student_name,
                    read.academic_year,
                    read.period_label,
                    read.origin.value,
                    read.issue_date.isoformat(),
                    read.due_date.isoformat(),
                    read.status.value,
                    read.currency,
                    f"{read.subtotal:.2f}",
                    f"{read.discount_total:.2f}",
                    f"{read.total:.2f}",
                    f"{read.paid_total:.2f}",
                    f"{read.outstanding:.2f}",
                    f"{read.arrears_brought_forward:.2f}",
                ]
            )
        if truncated:
            writer.writerow([])
            writer.writerow(
                [
                    f"# TRUNCATED: only the first {limit} vouchers are included. "
                    "Narrow the filters and export again."
                ]
            )
        return buffer.getvalue()

    # =====================================================================
    # Internals
    # =====================================================================

    @staticmethod
    def _line_total(quantity: Decimal, unit_price: Decimal) -> Decimal:
        """`quantity * unit_price`, quantized to the currency's two places.

        THE ONE PLACE THIS MULTIPLICATION HAPPENS. `Decimal` multiplication widens
        the scale -- `Decimal("2.50") * Decimal("60.00")` is `150.0000` -- and handing
        that straight to a `Numeric(12, 2)` column lets PostgreSQL do the rounding
        instead, with a different rule and no record of the decision. Rounding here,
        once, with ROUND_HALF_UP (what a cashier does, and what every parent expects
        of a bill) keeps the stored amount equal to the number the operator saw.
        """
        return (quantity * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def _structure_item_read(item: FeeStructureItem) -> FeeStructureItemRead:
        """Flatten a line of either kind into the one shape clients render.

        The `head`/`stationery_item` relationship this reads MUST already be loaded --
        `FeeStructureRepository.get_with_items` does that in one round trip. Touching
        it lazily here would emit SQL from a serialiser on an async session, which is
        an error rather than merely slow.
        """
        if item.line_type is FeeLineType.STATIONERY:
            article = item.stationery_item
            assert article is not None  # guaranteed by ck_..._line_type_matches_reference
            return FeeStructureItemRead(
                id=item.id,
                line_type=item.line_type,
                name=article.name,
                code=article.code,
                head_id=None,
                stationery_item_id=article.id,
                unit=article.unit,
                quantity=item.quantity,
                unit_price=item.unit_price,
                amount=item.amount,
            )

        head = item.head
        assert head is not None  # guaranteed by the same CHECK constraint
        return FeeStructureItemRead(
            id=item.id,
            line_type=item.line_type,
            name=head.name,
            code=head.code,
            head_id=head.id,
            stationery_item_id=None,
            unit=None,
            quantity=item.quantity,
            unit_price=item.unit_price,
            amount=item.amount,
        )

    async def _add_item(self, structure: FeeStructure, payload: FeeStructureItemInput) -> None:
        """Price one head inside a structure, inheriting the structure's scope.

        `quantity` is 1 and `unit_price` equals `amount` on a fee line -- Tuition is
        not sold by the dozen. Storing the identity rather than leaving the columns
        empty is what lets every total in this module sum `amount` alone without
        first asking what kind of line it is looking at.
        """
        head = await self.get_head(payload.head_id)
        await self.structure_items.create(
            structure_id=structure.id,
            line_type=FeeLineType.FEE,
            head_id=head.id,
            stationery_item_id=None,
            quantity=Decimal(1),
            unit_price=payload.amount,
            amount=payload.amount,
            organization_id=structure.organization_id,
            school_id=structure.school_id,
        )

    async def _get_student(self, student_id: UUID) -> Student:
        """Load a student through the tenant-bound session.

        A student from another organization is filtered out by RLS; one from another
        campus is excluded by the school predicate. Both read as absent and become a
        404 -- confirming either would leak that the child exists.
        """
        stmt = select(Student).where(Student.id == student_id, Student.deleted_at.is_(None))
        school_id = get_school_id()
        if school_id is not None:
            stmt = stmt.where(Student.school_id == school_id)
        student = (await self.session.execute(stmt)).scalar_one_or_none()
        if student is None:
            raise NotFoundError("Student not found.")
        return student

    async def _structure_for_student(
        self, student: Student, academic_year: str
    ) -> FeeStructure | None:
        """The structure that bills this student: their section's class, that year.

        Returns None rather than raising when the student is in no section, or their
        class has no structure for the year. Both are ordinary mid-setup states, and
        a 404 here would make the fee tab of a newly admitted student look broken
        instead of empty.
        """
        if student.section_id is None:
            return None

        from app.modules.academics.models import Section

        stmt = select(Section.class_id).where(
            Section.id == student.section_id, Section.deleted_at.is_(None)
        )
        class_id = (await self.session.execute(stmt)).scalar_one_or_none()
        if class_id is None:
            return None

        structure = await self.structures.get_for_class_year(class_id, academic_year)
        if structure is None:
            return None
        # Re-read with items loaded: `get_for_class_year` returns the bare row, and
        # the base lines below walk `structure.items`.
        return await self.structures.get_with_items(structure.id)

    @staticmethod
    def _base_lines(structure: FeeStructure | None) -> list[StudentFeeLine]:
        """The class structure's FEE lines, as the student inherits them.

        Stationery is excluded on purpose. It is charged by quantity onto a specific
        challan, not carried as a standing arrangement, so listing it beside tuition
        in a per-student profile would imply it recurs every period when it does not.
        """
        if structure is None:
            return []
        return [
            StudentFeeLine(
                head_id=item.head_id,
                head_code=item.head.code,
                head_name=item.head.name,
                amount=item.amount,
                discount_amount=_ZERO,
                net_amount=item.amount,
                source="class",
            )
            for item in structure.items
            if item.line_type is FeeLineType.FEE and item.head is not None
        ]

    @staticmethod
    def _money(value: Decimal) -> Decimal:
        """Two decimal places, half up -- the same rounding `_line_total` uses.

        Concessions are the only place in this module that DIVIDE, and a percentage
        of an odd amount is where a fraction of a rupee appears. Rounding it in one
        helper is what stops the preview and the challan disagreeing by a paisa,
        which a parent will notice and nobody will be able to explain.
        """
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @classmethod
    def _discount_for(
        cls, assignment: StudentFeeAssignment, gross: Decimal
    ) -> tuple[Decimal, str | None]:
        """What one DISCOUNT arrangement takes off a line, and which scheme paid.

        THREE SOURCES, ONE PRECEDENCE, and the CHECK constraint guarantees exactly one
        of them is populated -- so this reads as a chain rather than a set of cases
        that could overlap:

          * a named concession, whose rate is read from the SCHEME (so revising the
            scheme revises every child on it);
          * an ad-hoc percentage;
          * an ad-hoc flat sum.

        CLAMPED TO THE GROSS. A 100% concession plus a fee revision downward, or a
        flat remission larger than the line it applies to, would otherwise produce a
        negative line -- which `ck_fee_voucher_items_amounts_valid` refuses, turning a
        generous scholarship into a failed billing run for the whole class. Clamping
        bills zero instead, which is what the school meant.
        """
        concession = assignment.concession
        if concession is not None:
            raw = (
                gross * concession.value / Decimal(100)
                if concession.kind is ConcessionKind.PERCENT
                else concession.value
            )
            name: str | None = concession.name
        elif assignment.percent is not None:
            raw = gross * assignment.percent / Decimal(100)
            name = None
        else:
            # Guarded by ck_student_fee_assignments_amount_matches_mode: a discount
            # with no concession and no percent must carry an amount.
            assert assignment.amount is not None
            raw = assignment.amount
            name = None

        return min(cls._money(raw), gross), name

    @classmethod
    def _effective_lines(
        cls, base: list[StudentFeeLine], assignments: Sequence[StudentFeeAssignment]
    ) -> list[StudentFeeLine]:
        """Apply one student's departures to their class base.

        =================================================================
        THE ONE PLACE THE MERGE HAPPENS
        =================================================================
            Both the profile screen and the generation run call this, and they MUST
            agree: a preview that shows 6,500 and a challan that bills 8,500 is worse
            than no preview at all, because the operator checked and was told the
            wrong thing. Keeping the rule in one function is what makes them the same
            answer rather than two implementations that agree today.

        =================================================================
        THE ORDER IS THE DESIGN, NOT AN IMPLEMENTATION DETAIL
        =================================================================
            OVERRIDE, then EXCLUDED, then ADDED, then DISCOUNT. Each step is chosen
            against a way of getting it wrong that nobody would notice:

              1. OVERRIDE restates a class line's amount. It never creates one: if
                 the class prices no such head there is nothing to replace, and
                 inventing a line would bill a service the child never took because
                 somebody mis-picked a head.

              2. EXCLUDED drops the line entirely rather than zeroing it -- a
                 "Transport 0.00" row is a question a parent phones about. It is
                 applied AFTER override so that excluding a head the student also has
                 a negotiated rate for still removes it; the alternative silently
                 bills the override.

              3. ADDED appends at the student's own rate, after the class lines, so a
                 bill reads as "what everyone pays, then what is particular to this
                 child".

              4. DISCOUNT applies LAST, to whatever the first three settled on. This
                 is the step whose order actually costs money if reversed: "half of
                 what this child pays" computed against the class list price bills the
                 wrong number for every child on a negotiated rate, and bills it
                 invisibly, because the challan still shows a plausible 50%.
        """
        overrides = {
            a.head_id: a for a in assignments if a.mode is StudentFeeAssignmentMode.OVERRIDE
        }
        excluded = {a.head_id for a in assignments if a.mode is StudentFeeAssignmentMode.EXCLUDED}
        discounts = {
            a.head_id: a for a in assignments if a.mode is StudentFeeAssignmentMode.DISCOUNT
        }

        lines: list[StudentFeeLine] = []
        for line in base:
            if line.head_id in excluded:
                continue
            override = overrides.get(line.head_id)
            if override is None:
                lines.append(line)
                continue
            # Guarded by ck_student_fee_assignments_amount_matches_mode.
            assert override.amount is not None
            lines.append(
                line.model_copy(
                    update={
                        "amount": override.amount,
                        "net_amount": override.amount,
                        "source": "override",
                    }
                )
            )

        for assignment in assignments:
            if assignment.mode is not StudentFeeAssignmentMode.ADDED:
                continue
            # Guarded by ck_student_fee_assignments_amount_matches_mode.
            assert assignment.amount is not None
            lines.append(
                StudentFeeLine(
                    head_id=assignment.head_id,
                    head_code=assignment.head.code,
                    head_name=assignment.head.name,
                    amount=assignment.amount,
                    discount_amount=_ZERO,
                    net_amount=assignment.amount,
                    source="student",
                )
            )

        if not discounts:
            return lines

        discounted: list[StudentFeeLine] = []
        for line in lines:
            remission = discounts.get(line.head_id)
            if remission is None:
                discounted.append(line)
                continue
            amount, concession_name = cls._discount_for(remission, line.amount)
            discounted.append(
                line.model_copy(
                    update={
                        "discount_amount": amount,
                        "net_amount": line.amount - amount,
                        "source": "discount",
                        "concession_name": concession_name,
                    }
                )
            )
        return discounted

    @staticmethod
    def _assignment_read(assignment: StudentFeeAssignment) -> StudentFeeAssignmentRead:
        return StudentFeeAssignmentRead(
            id=assignment.id,
            student_id=assignment.student_id,
            head_id=assignment.head_id,
            head_code=assignment.head.code,
            head_name=assignment.head.name,
            academic_year=assignment.academic_year,
            mode=assignment.mode,
            amount=assignment.amount,
            percent=assignment.percent,
            concession_id=assignment.concession_id,
            concession_code=assignment.concession.code if assignment.concession else None,
            concession_name=assignment.concession.name if assignment.concession else None,
            note=assignment.note,
            created_at=assignment.created_at,
            updated_at=assignment.updated_at,
        )

    async def _create_voucher(
        self,
        *,
        structure: FeeStructure,
        student: Student,
        payload: VoucherGenerateRequest,
        voucher_number: str,
        issued: bool,
        now: datetime,
        assignments: Sequence[StudentFeeAssignment],
        arrears: Decimal = _ZERO,
        carry_head: FeeHead | None = None,
        absorbed: Sequence[FeeVoucher] = (),
    ) -> FeeVoucher:
        """Build one challan, SNAPSHOTTING every amount and head name.

        The snapshot is the whole point of this function. A voucher that referenced
        live structure items would silently restate itself the moment someone
        repriced next term's tuition -- rewriting a bill a parent is holding, and
        making "what did we charge in August?" unanswerable.

        THE FEE LINES COME FROM `_effective_lines`, THE SAME FUNCTION THE PREVIEW USES.
            The per-student profile screen and this billing run must produce the same
            numbers: a preview showing 6,500 against a challan billing 8,500 is worse
            than no preview at all, because the operator checked and was told the
            wrong thing. Routing both through one merge is what makes them the same
            answer rather than two implementations that happen to agree today.
        """
        # The FEE half: class base, minus this student's exclusions, plus their own
        # additions at their own rates.
        effective = self._effective_lines(self._base_lines(structure), assignments)

        # `sort_order` lives on the head, which `_effective_lines` does not carry --
        # it returns an API shape, and widening it to serve this loop would leak a
        # rendering concern into the contract. Resolved from both sources here.
        heads_by_id: dict[UUID, FeeHead] = {}
        for item in structure.items:
            if item.line_type is FeeLineType.FEE and item.head is not None:
                heads_by_id[item.head.id] = item.head
        for assignment in assignments:
            heads_by_id[assignment.head_id] = assignment.head

        # The STATIONERY half passes through untouched: it is charged by quantity per
        # challan, not carried as a standing per-student arrangement, so an assignment
        # has nothing to say about it. `include_stationery=False` drops it entirely --
        # the flag exists because a structure holding an ANNUAL book set would
        # otherwise re-bill those books every month, at the parent's expense.
        stationery_items = (
            [item for item in structure.items if item.line_type is FeeLineType.STATIONERY]
            if payload.include_stationery
            else []
        )

        # SUBTOTAL IS GROSS, and the discount is carried beside it rather than
        # folded in. A challan that showed only the net figure would be
        # indistinguishable from a repricing, and the family could not see they had
        # been awarded anything -- which is the one thing a scholarship must make
        # visible. `total` is what is actually payable.
        subtotal = sum((line.amount for line in effective), _ZERO) + sum(
            (item.amount for item in stationery_items), _ZERO
        )
        discount_total = sum((line.discount_amount for line in effective), _ZERO)

        # THE CARRIED BALANCE IS A REAL LINE, IN THE SUBTOTAL, and that is the whole
        # difference between consolidating and merely printing. It is only ever the
        # total of challans this run is about to CANCEL -- never the family's balance,
        # which also contains part-paid challans that keep their own document. Billing
        # the balance instead would charge for money the school has already received.
        carried = sum((v.total for v in absorbed), _ZERO)
        if carry_head is not None and carried > _ZERO:
            subtotal += carried
        else:
            carried = _ZERO

        voucher = await self.vouchers.create(
            student_id=student.id,
            structure_id=structure.id,
            voucher_number=voucher_number,
            academic_year=structure.academic_year,
            period_label=payload.period_label,
            issue_date=payload.issue_date,
            due_date=payload.due_date,
            status=VoucherStatus.ISSUED if issued else VoucherStatus.DRAFT,
            origin=VoucherOrigin.REGULAR,
            currency="PKR",
            subtotal=subtotal,
            discount_total=discount_total,
            total=subtotal - discount_total,
            paid_total=_ZERO,
            # WHAT THIS CHALLAN DOES NOT BILL. Printed so the family sees what they
            # owe overall, deliberately absent from `total` -- because the challans
            # behind it are still outstanding and adding them here would bill the
            # same rupee twice.
            #
            # On a consolidating run the absorbed challans ARE billed above and are
            # cancelled at issue, so they are subtracted here: leaving them in would
            # print a "previous balance" the family had just been charged for, on the
            # same piece of paper. Floored at zero because a credit balance is not an
            # arrear, and a negative figure under "previous balance" reads as the
            # school owing the parent.
            arrears_brought_forward=max(arrears - carried, _ZERO),
            carry_forward_head_id=carry_head.id if carry_head and carried > _ZERO else None,
            notes=payload.notes,
            issued_at=now if issued else None,
            organization_id=structure.organization_id,
            school_id=structure.school_id,
        )

        for order, line in enumerate(effective):
            head = heads_by_id.get(line.head_id)
            await self.voucher_items.create(
                voucher_id=voucher.id,
                line_type=FeeLineType.FEE,
                head_id=line.head_id,
                stationery_item_id=None,
                line_name=line.head_name,  # the snapshot
                unit_label=None,
                # A fee line is one unit priced at its own amount, whether it came
                # from the class or from this student's own arrangement.
                quantity=Decimal(1),
                unit_price=line.amount,
                amount=line.amount,
                discount_amount=line.discount_amount,
                sort_order=(head.sort_order if head else 0) or order,
                organization_id=structure.organization_id,
                school_id=structure.school_id,
            )

        if carry_head is not None and carried > _ZERO:
            await self.voucher_items.create(
                voucher_id=voucher.id,
                line_type=FeeLineType.FEE,
                head_id=carry_head.id,
                stationery_item_id=None,
                # SNAPSHOTTED WITH THE PERIODS IT CAME FROM, not just the head name.
                # "Previous dues 12,500" is a number a parent argues with at the
                # counter; "Previous dues (2026-06, 2026-07)" is one they can check
                # against the challans they were holding.
                line_name=f"{carry_head.name} ({', '.join(v.period_label for v in absorbed)})",
                unit_label=None,
                quantity=Decimal(1),
                unit_price=carried,
                amount=carried,
                discount_amount=_ZERO,
                # Below every fee line and above the stationery block. A parent reads
                # what this month costs first; arrears interleaved between tuition and
                # transport reads as part of the month's charges.
                sort_order=_ARREARS_SORT_ORDER,
                organization_id=structure.organization_id,
                school_id=structure.school_id,
            )

        for order, item in enumerate(stationery_items):
            article = item.stationery_item
            assert article is not None  # ck_..._line_type_matches_reference
            await self.voucher_items.create(
                voucher_id=voucher.id,
                line_type=FeeLineType.STATIONERY,
                head_id=None,
                stationery_item_id=item.stationery_item_id,
                line_name=article.name,  # the snapshot
                unit_label=article.unit.value,  # snapshotted too -- see the model
                quantity=item.quantity,
                unit_price=item.unit_price,
                amount=item.amount,
                discount_amount=_ZERO,
                # Offset so stationery always prints BELOW every fee line regardless
                # of how the two catalogs happen to be sorted against each other. A
                # parent reads the tuition line first; a challan that interleaves
                # books between tuition and transport generates phone calls.
                sort_order=_STATIONERY_SORT_BASE + (article.sort_order or order),
                organization_id=structure.organization_id,
                school_id=structure.school_id,
            )
        return voucher

    @staticmethod
    def _assert_line_editable(voucher: FeeVoucher) -> None:
        """THE GUARD BEHIND RULE 1. Lines change only while the bill is unsent.

        Separate from `is_open`, which asks whether a voucher can still take MONEY.
        The two are near-opposites: an issued challan accepts payment and refuses
        edits, a draft refuses payment and accepts edits, and collapsing them into one
        predicate is how an issued bill eventually gets restated.
        """
        if voucher.status is VoucherStatus.VOID:
            raise ConflictError("A voided challan cannot be changed.")
        if voucher.status is not VoucherStatus.DRAFT:
            raise ConflictError(
                "This challan has already been issued and its charges are final. "
                "Add the charge to the student's next challan, or void this one and "
                "reissue it."
            )

    async def _recalculate_lines(self, voucher: FeeVoucher) -> None:
        """Re-derive `subtotal`, `discount_total` and `total` from the LINES.

        The sibling of `_recalculate`, which derives `paid_total` and status from the
        PAYMENTS. Two caches, two writers, one rule each -- and both recompute from
        their source rows rather than adjusting, so neither can drift away from what
        justifies it.

        Only ever reached on a draft (`_assert_line_editable` runs first), so it
        cannot restate an issued bill. It deliberately does not touch `status` or
        `paid_total`: a draft holds no money, and reaching across into the other
        cache's columns is how the two writers would start disagreeing.
        """
        subtotal, discount_total = await self.voucher_items.line_totals(voucher.id)
        await self.vouchers.update(
            voucher,
            subtotal=subtotal,
            discount_total=discount_total,
            total=subtotal - discount_total,
        )

    async def _recalculate(self, voucher: FeeVoucher) -> None:
        """Re-derive `paid_total` and status from the payment rows.

        THE ONLY WRITER of `paid_total`. Recomputes rather than increments, so a
        payment followed by a reversal cannot leave the cached figure disagreeing
        with the receipts. Every money path in this service ends here.
        """
        paid = await self.payments.effective_total(voucher.id)

        if paid >= voucher.total and voucher.total > _ZERO:
            status = VoucherStatus.PAID
            paid_at: datetime | None = datetime.now(UTC)
        elif paid > _ZERO:
            status = VoucherStatus.PARTLY_PAID
            paid_at = None
        else:
            # Back to ISSUED, never to DRAFT: the challan reached the parent and
            # reversing a payment does not un-send it.
            status = VoucherStatus.ISSUED
            paid_at = None

        # Overdue only matters while money is still owed, so it is applied after the
        # paid/partly-paid decision rather than instead of it.
        if status is not VoucherStatus.PAID and voucher.due_date < date.today():
            status = VoucherStatus.OVERDUE

        await self.vouchers.update(voucher, paid_total=paid, status=status, paid_at=paid_at)

    def _voucher_read(self, voucher: FeeVoucher) -> FeeVoucherRead:
        """Serialise a voucher, deriving OVERDUE on read.

        A voucher past its due date with money owed reads as overdue whether or not a
        job has stamped it. Doing this on read means the figure is right the morning
        after a due date rather than the morning after a job runs.
        """
        status = voucher.status
        if (
            status in {VoucherStatus.ISSUED, VoucherStatus.PARTLY_PAID}
            and voucher.due_date < date.today()
            and voucher.outstanding > _ZERO
        ):
            status = VoucherStatus.OVERDUE

        return FeeVoucherRead(
            id=voucher.id,
            student_id=voucher.student_id,
            student_name=voucher.student.full_name,
            admission_number=voucher.student.admission_number,
            structure_id=voucher.structure_id,
            origin=voucher.origin,
            source_voucher_id=voucher.source_voucher_id,
            arrears_brought_forward=voucher.arrears_brought_forward,
            superseded_by_voucher_id=voucher.superseded_by_voucher_id,
            voucher_number=voucher.voucher_number,
            academic_year=voucher.academic_year,
            period_label=voucher.period_label,
            issue_date=voucher.issue_date,
            due_date=voucher.due_date,
            status=status,
            currency=voucher.currency,
            subtotal=voucher.subtotal,
            discount_total=voucher.discount_total,
            total=voucher.total,
            paid_total=voucher.paid_total,
            outstanding=voucher.outstanding,
            notes=voucher.notes,
            issued_at=voucher.issued_at,
            paid_at=voucher.paid_at,
            voided_at=voucher.voided_at,
            void_reason=voucher.void_reason,
            created_at=voucher.created_at,
            updated_at=voucher.updated_at,
        )

    async def _get_class(self, class_id: UUID) -> SchoolClass:
        """Load a class through the tenant-bound session.

        A class from another organization is filtered out by RLS and reads as absent;
        one from another campus in the same organization is excluded by the school
        predicate below. Both become 404 -- confirming either would leak.
        """
        stmt = select(SchoolClass).where(
            SchoolClass.id == class_id, SchoolClass.deleted_at.is_(None)
        )
        school_class = (await self.session.execute(stmt)).scalar_one_or_none()
        if school_class is None:
            raise NotFoundError("Class not found.")
        return school_class

    @staticmethod
    def _assert_editable(structure: FeeStructure) -> None:
        if structure.status is FeeStructureStatus.ARCHIVED:
            raise ConflictError("An archived fee structure cannot be modified.")

    @staticmethod
    def _concession_read(concession: FeeConcession, *, student_count: int = 0) -> FeeConcessionRead:
        return FeeConcessionRead(
            id=concession.id,
            code=concession.code,
            name=concession.name,
            description=concession.description,
            kind=concession.kind,
            value=concession.value,
            is_active=concession.is_active,
            sort_order=concession.sort_order,
            student_count=student_count,
            created_at=concession.created_at,
            updated_at=concession.updated_at,
        )

    @staticmethod
    def _policy_read(policy: LateFeePolicy, head: FeeHead) -> LateFeePolicyRead:
        return LateFeePolicyRead(
            id=policy.id,
            academic_year=policy.academic_year,
            name=policy.name,
            head_id=policy.head_id,
            head_name=head.name,
            kind=policy.kind,
            value=policy.value,
            grace_days=policy.grace_days,
            recurrence=policy.recurrence,
            max_amount=policy.max_amount,
            min_outstanding=policy.min_outstanding,
            is_active=policy.is_active,
            created_at=policy.created_at,
            updated_at=policy.updated_at,
        )

    @staticmethod
    def _assessments_earned(policy: LateFeePolicy, due_date: date, today: date) -> int:
        """How many fines this challan has EARNED by today under the policy.

        Compared against how many it has already been charged, which is what makes a
        re-run on the same day a no-op and a run a week later charge exactly one more.
        Counting elapsed intervals rather than tracking a "last assessed" timestamp is
        deliberate: a timestamp drifts with the hour the job happens to run, so a
        nightly job that slipped past midnight would charge a second week's fine six
        days early, and only for the schools whose run was slow.
        """
        overdue_days = (today - due_date).days - policy.grace_days
        if overdue_days < 0:
            return 0
        if policy.recurrence is LateFeeRecurrence.ONCE:
            return 1
        interval = 7 if policy.recurrence is LateFeeRecurrence.WEEKLY else 30
        return overdue_days // interval + 1

    async def _create_late_fee_voucher(
        self,
        *,
        policy: LateFeePolicy,
        source: FeeVoucher,
        amount: Decimal,
        voucher_number: str,
        period_label: str,
        today: date,
        now: datetime,
        actor_id: UUID | None,
    ) -> FeeVoucher:
        """Mint one fine as its own issued challan, and record it on the ledger.

        ISSUED IMMEDIATELY, not drafted. A fine nobody issues is a fine nobody
        collects, and leaving a pile of draft fines for an operator to review defeats
        the reason the policy exists -- consistency without anybody having to
        remember. The review step is the void path, which is audited and names who
        let the family off.

        `due_date` is today: the fine is payable on assessment, alongside whatever
        else the family owes. It cannot itself compound, because
        `overdue_candidates` excludes every voucher whose origin is a fine.
        """
        fine = await self.vouchers.create(
            student_id=source.student_id,
            structure_id=None,
            voucher_number=voucher_number,
            academic_year=source.academic_year,
            period_label=period_label,
            issue_date=today,
            due_date=today,
            status=VoucherStatus.ISSUED,
            origin=VoucherOrigin.LATE_FEE,
            source_voucher_id=source.id,
            currency=source.currency,
            subtotal=amount,
            discount_total=_ZERO,
            total=amount,
            paid_total=_ZERO,
            arrears_brought_forward=_ZERO,
            notes=f"Late fee for challan {source.voucher_number} ({policy.name}).",
            issued_at=now,
            organization_id=source.organization_id,
            school_id=source.school_id,
        )
        await self.voucher_items.create(
            voucher_id=fine.id,
            line_type=FeeLineType.FEE,
            head_id=policy.head_id,
            stationery_item_id=None,
            # Snapshotted with the source number in it, so the line explains itself on
            # paper six months later without anyone having to look up a foreign key.
            line_name=f"{policy.head.name} — {source.voucher_number}",
            unit_label=None,
            quantity=Decimal(1),
            unit_price=amount,
            amount=amount,
            discount_amount=_ZERO,
            sort_order=0,
            organization_id=source.organization_id,
            school_id=source.school_id,
        )
        await self._ledger_append(
            source.student_id,
            entry_type=LedgerEntryType.LATE_FEE,
            amount=amount,
            academic_year=source.academic_year,
            occurred_on=today,
            description=f"Late fee {voucher_number} for {source.voucher_number}",
            organization_id=source.organization_id,
            school_id=source.school_id,
            voucher_id=fine.id,
            actor_id=actor_id,
        )
        return fine

    async def _settle_superseded(self, voucher: FeeVoucher, *, actor_id: UUID | None) -> None:
        """Cancel the challans this one absorbed, at the moment it becomes a bill.

        =================================================================
        WHY THE CANCELLATION WAITS FOR THE ISSUE
        =================================================================
            Generation only RESERVES: it stamps the older challans with a pointer and
            leaves them live. If the cancellation happened there, a consolidating
            DRAFT would take four real challans off the family's balance while the
            only document covering that money sat unissued in a list. The school would
            read "nothing owed" about a family owing three months.

            So the two halves happen together, here: the old challans are voided and
            the new charge is recorded in the same transaction, and the balance never
            passes through a value that is wrong in either direction.

        =================================================================
        A RESERVED CHALLAN THAT TOOK A PAYMENT IS RELEASED, NOT VOIDED
        =================================================================
            Between the run and the issue, a parent may walk in and pay the old
            challan. Voiding it then would orphan the receipt -- which `void_voucher`
            refuses outright -- and billing for it anyway would charge them twice for
            money the school has already banked.

            The reservation is dropped instead and the arrears line SHRINKS to match.
            That is legal here and nowhere later: the voucher is still a draft at this
            point, so repricing it is not restating an issued bill. This is the last
            moment the correction can be made, which is exactly why it is made here.
        """
        reserved = await self.vouchers.reserved_by(voucher.id)
        if not reserved:
            return

        absorbable: list[FeeVoucher] = []
        released: list[FeeVoucher] = []
        for old_voucher in reserved:
            collected = await self.payments.effective_total(old_voucher.id)
            if collected > _ZERO or old_voucher.status in (
                VoucherStatus.VOID,
                VoucherStatus.PAID,
            ):
                released.append(old_voucher)
            else:
                absorbable.append(old_voucher)

        for old_voucher in released:
            await self.vouchers.update(old_voucher, superseded_by_voucher_id=None)
            logger.info(
                "fee_voucher_supersession_released",
                voucher_id=str(old_voucher.id),
                superseded_by=str(voucher.id),
            )

        if released:
            await self._reprice_carried_line(voucher, absorbable)

        for old_voucher in absorbable:
            # Routed through the same method a human uses, so a superseded challan is
            # voided, audited and credited by exactly the code path that governs every
            # other cancellation. A private shortcut here is how the two would drift.
            await self.void_voucher(
                old_voucher.id,
                f"Superseded by challan {voucher.voucher_number}",
                actor_id=actor_id,
            )

    async def _reprice_carried_line(
        self, voucher: FeeVoucher, absorbable: Sequence[FeeVoucher]
    ) -> None:
        """Shrink (or remove) the carried-dues line after a release.

        Reached only from `_settle_superseded`, only while the voucher is a draft.
        `_recalculate_lines` then re-derives the totals from the LINES rather than
        adjusting them, so the challan cannot end up with a total that disagrees with
        the rows printed beneath it.
        """
        if voucher.carry_forward_head_id is None:
            return
        if voucher.status is not VoucherStatus.DRAFT:
            # RULE 1 WINS, even here. Every caller reaches this while the voucher is
            # still a draft -- generation computes its absorbable set in the same
            # transaction, and `issue_voucher` runs this before flipping the status --
            # so this branch is unreachable by design. If it ever is reached, the
            # right answer is to leave the issued bill alone and say so loudly, not to
            # quietly restate a challan a parent is holding.
            logger.warning(
                "fee_carried_line_reprice_skipped_on_issued_voucher",
                voucher_id=str(voucher.id),
                status=voucher.status.value,
            )
            return
        line = await self.voucher_items.get_fee_line(voucher.id, voucher.carry_forward_head_id)
        if line is None:
            return

        carried = sum((v.total for v in absorbable), _ZERO)
        if carried <= _ZERO:
            # Removed rather than zeroed. A "Previous dues 0" line on a challan is a
            # question a parent phones about, and the answer -- "you paid it after we
            # printed this" -- is not one the paper can give.
            await self.voucher_items.hard_delete(line.id)
            await self.vouchers.update(voucher, carry_forward_head_id=None)
        else:
            head_name = line.line_name.split(" (")[0]
            await self.voucher_items.update(
                line,
                line_name=f"{head_name} ({', '.join(v.period_label for v in absorbable)})",
                unit_price=carried,
                amount=carried,
            )
        await self._recalculate_lines(voucher)

    async def _ledger_charge(self, voucher: FeeVoucher, *, actor_id: UUID | None) -> None:
        """Record an issued challan on the family's account.

        GUARDED AGAINST A SECOND ENTRY. Issuing is a one-way transition so this should
        never run twice for one voucher, but "should never" is not a guarantee, and a
        duplicated charge silently doubles a family's balance -- a failure the parent
        discovers before the school does, at the counter, holding one challan.

        A zero-total challan produces no entry: `ck_student_ledger_entries_amount_non_zero`
        refuses it, and rightly -- a movement of nothing lengthens a statement without
        informing it.
        """
        if voucher.total == _ZERO:
            return
        if await self.ledger.has_entry_for(
            voucher_id=voucher.id, entry_type=LedgerEntryType.CHARGE
        ):
            return
        await self._ledger_append(
            voucher.student_id,
            entry_type=LedgerEntryType.CHARGE,
            amount=voucher.total,
            academic_year=voucher.academic_year,
            occurred_on=voucher.issue_date,
            description=f"Challan {voucher.voucher_number} ({voucher.period_label})",
            organization_id=voucher.organization_id,
            school_id=voucher.school_id,
            voucher_id=voucher.id,
            actor_id=actor_id,
        )

    async def _ledger_append(
        self,
        student_id: UUID,
        *,
        entry_type: LedgerEntryType,
        amount: Decimal,
        academic_year: str,
        occurred_on: date,
        description: str,
        organization_id: UUID,
        school_id: UUID,
        voucher_id: UUID | None = None,
        payment_id: UUID | None = None,
        actor_id: UUID | None = None,
    ) -> StudentLedgerEntry:
        """One movement, appended in the caller's transaction.

        Same transaction as the change it records, exactly like `_audit`: either the
        payment and its ledger entry both land, or neither does. A ledger written in
        a separate transaction would disagree with the receipts underneath it every
        time a request failed between the two.
        """
        return await self.ledger.append(
            student_id=student_id,
            entry_type=entry_type,
            amount=amount,
            academic_year=academic_year,
            occurred_on=occurred_on,
            description=description,
            organization_id=organization_id,
            school_id=school_id,
            voucher_id=voucher_id,
            payment_id=payment_id,
            created_by_user_id=actor_id,
        )

    async def _audit(
        self,
        action: str,
        *,
        entity_type: str,
        entity_id: UUID,
        actor_id: UUID | None,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
    ) -> None:
        """Append the audit row inside the caller's transaction.

        Same transaction as the change it describes, per `common/audit.py`: either
        both the mutation and its record land, or neither does.
        """
        await record_audit(
            self.session,
            organization_id=require_organization_id(),
            school_id=require_school_id(),
            actor_user_id=actor_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            before=before,
            after=after,
        )
