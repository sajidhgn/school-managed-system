"""Fees HTTP endpoints -- heads, structures, challans and receipts.

Handlers are one line of delegation each. Anything longer belongs in the service.

=============================================================================
AUTHORISATION SHAPE -- FIVE CODES, AND THE SPLIT IS THE POINT
=============================================================================
    fee:read     view anything in this module
    fee:manage   define heads and structures        (what may be charged)
    fee:issue    generate and issue vouchers        (who is charged)
    fee:collect  record a payment, issue a receipt  (money in)
    fee:void     void a voucher, reverse a payment  (money un-recorded)

    STATIONERY ADDS NO SIXTH CODE, and that is a decision rather than an oversight.
    The catalog of sellable articles is `fee:manage` because it answers exactly the
    question fee heads answer -- what this campus may put on a challan. Charging an
    article to a student's draft is `fee:issue` because it answers the other question
    -- who is charged what. A separate `stationery:*` family would mean a school
    hiring a store keeper had to discover and grant two more codes to reproduce the
    access their accountant already had, for no boundary the existing five do not
    already draw.

    `fee:collect` and `fee:void` are deliberately separate, and `fee:void` is
    deliberately absent from the default accountant role. The person who records
    money coming in must not be the person who can make a record of money disappear
    -- that is the oldest control in bookkeeping, and collapsing the two codes into
    one "fees" permission would quietly remove it. A customer who wants their
    accountant to hold both grants it explicitly; the default does not.

ROUTE ORDER IS LOAD-BEARING
    Starlette matches in declaration order. Every literal segment (`/summary`,
    `/generate`, `/payments/...`) is declared BEFORE the `/{id}` pattern that would
    otherwise swallow it and fail with a 422 UUID error.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from app.api.deps import AuthContext, DbSession, Pagination, Sorting, require
from app.common.schemas import Page
from app.core.exceptions import NotFoundError
from app.modules.fees.challan_pdf import render_challan_pdf
from app.modules.fees.models import FeeStructureStatus, StationeryCategory, VoucherStatus
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
    PaymentReverseRequest,
    StationeryItemCreate,
    StationeryItemRead,
    StationeryItemUpdate,
    StudentFeeAssignmentInput,
    StudentFeeProfile,
    StudentLedgerStatement,
    VoucherFeeChargeInput,
    VoucherGenerateRequest,
    VoucherGenerateResult,
    VoucherStationeryInput,
    VoucherVoidRequest,
)
from app.modules.fees.service import FeeService
from app.modules.tenancy.models import School

router = APIRouter()

ReadCtx = Annotated[AuthContext, Depends(require("fee:read"))]
ManageCtx = Annotated[AuthContext, Depends(require("fee:manage"))]
IssueCtx = Annotated[AuthContext, Depends(require("fee:issue"))]
CollectCtx = Annotated[AuthContext, Depends(require("fee:collect"))]
VoidCtx = Annotated[AuthContext, Depends(require("fee:void"))]


# ---------------------------------------------------------------------------
# Collection summary
# ---------------------------------------------------------------------------
#
# Declared first so `/summary` is never parsed as a path parameter of anything.


@router.get(
    "/summary",
    response_model=FeeSummary,
    summary="Fee collection summary for a year or period",
)
async def fee_summary(
    db: DbSession,
    _ctx: ReadCtx,
    academic_year: Annotated[str, Query(examples=["2026-2027"])],
    period_label: Annotated[str | None, Query(description="e.g. `2026-08`.")] = None,
) -> FeeSummary:
    """Billed, collected, outstanding and overdue. Two grouped queries, never N+1."""
    return await FeeService(db).summary(academic_year, period_label)


# ---------------------------------------------------------------------------
# Fee heads
# ---------------------------------------------------------------------------


@router.get("/heads", response_model=Page[FeeHeadRead], summary="List fee heads")
async def list_fee_heads(
    db: DbSession,
    _ctx: ReadCtx,
    params: Pagination,
    sort: Sorting,
    active_only: Annotated[bool, Query(description="Hide retired heads.")] = False,
) -> Page[FeeHeadRead]:
    return await FeeService(db).list_heads(params, sort, active_only=active_only)


@router.post(
    "/heads",
    response_model=FeeHeadRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a fee head",
)
async def create_fee_head(payload: FeeHeadCreate, db: DbSession, ctx: ManageCtx) -> FeeHeadRead:
    return await FeeService(db).create_head(payload, actor_id=ctx.user_id)


@router.get("/heads/{head_id}", response_model=FeeHeadRead, summary="Get a fee head")
async def get_fee_head(head_id: UUID, db: DbSession, _ctx: ReadCtx) -> FeeHeadRead:
    return FeeHeadRead.model_validate(await FeeService(db).get_head(head_id))


@router.patch("/heads/{head_id}", response_model=FeeHeadRead, summary="Update a fee head")
async def update_fee_head(
    head_id: UUID, payload: FeeHeadUpdate, db: DbSession, ctx: ManageCtx
) -> FeeHeadRead:
    return await FeeService(db).update_head(head_id, payload, actor_id=ctx.user_id)


@router.delete(
    "/heads/{head_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an unused fee head",
)
async def delete_fee_head(head_id: UUID, db: DbSession, ctx: ManageCtx) -> None:
    """Refused while any structure still prices it -- deactivate instead."""
    await FeeService(db).delete_head(head_id, actor_id=ctx.user_id)


# ---------------------------------------------------------------------------
# Stationery catalog
# ---------------------------------------------------------------------------
#
# Declared before `/structures` and `/vouchers` purely for grouping -- `/stationery`
# is a literal segment and collides with nothing. Guarded by `fee:manage`, the same
# code that governs fee heads: both answer "what may this campus charge for".


@router.get(
    "/stationery",
    response_model=Page[StationeryItemRead],
    summary="List stationery items",
)
async def list_stationery_items(
    db: DbSession,
    _ctx: ReadCtx,
    params: Pagination,
    sort: Sorting,
    active_only: Annotated[bool, Query(description="Hide retired articles.")] = False,
    category: Annotated[
        StationeryCategory | None, Query(description="Books, notebooks, uniform, ...")
    ] = None,
) -> Page[StationeryItemRead]:
    return await FeeService(db).list_stationery_items(
        params, sort, active_only=active_only, category=category
    )


@router.post(
    "/stationery",
    response_model=StationeryItemRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a stationery item to the catalog",
)
async def create_stationery_item(
    payload: StationeryItemCreate, db: DbSession, ctx: ManageCtx
) -> StationeryItemRead:
    return await FeeService(db).create_stationery_item(payload, actor_id=ctx.user_id)


@router.get(
    "/stationery/{item_id}",
    response_model=StationeryItemRead,
    summary="Get a stationery item",
)
async def get_stationery_item(item_id: UUID, db: DbSession, _ctx: ReadCtx) -> StationeryItemRead:
    return StationeryItemRead.model_validate(await FeeService(db).get_stationery_item(item_id))


@router.patch(
    "/stationery/{item_id}",
    response_model=StationeryItemRead,
    summary="Update or reprice a stationery item",
)
async def update_stationery_item(
    item_id: UUID, payload: StationeryItemUpdate, db: DbSession, ctx: ManageCtx
) -> StationeryItemRead:
    """Repricing is NOT retroactive: every line that charged this article snapshotted
    the price it sold at, so this changes the next challan and no past one."""
    return await FeeService(db).update_stationery_item(item_id, payload, actor_id=ctx.user_id)


@router.delete(
    "/stationery/{item_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an uncharged stationery item",
)
async def delete_stationery_item(item_id: UUID, db: DbSession, ctx: ManageCtx) -> None:
    """Refused once any structure or challan line charges it -- deactivate instead."""
    await FeeService(db).delete_stationery_item(item_id, actor_id=ctx.user_id)


# ---------------------------------------------------------------------------
# Fee structures
# ---------------------------------------------------------------------------


@router.get("/structures", response_model=Page[FeeStructureRead], summary="List fee structures")
async def list_fee_structures(
    db: DbSession,
    _ctx: ReadCtx,
    params: Pagination,
    sort: Sorting,
    class_id: UUID | None = None,
    academic_year: Annotated[str | None, Query(examples=["2026-2027"])] = None,
    structure_status: Annotated[FeeStructureStatus | None, Query(alias="status")] = None,
) -> Page[FeeStructureRead]:
    return await FeeService(db).list_structures(
        params, sort, class_id=class_id, academic_year=academic_year, status=structure_status
    )


@router.post(
    "/structures",
    response_model=FeeStructureDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create a fee structure",
)
async def create_fee_structure(
    payload: FeeStructureCreate, db: DbSession, ctx: ManageCtx
) -> FeeStructureDetail:
    """Starts as a DRAFT so it can be assembled over several sittings."""
    return await FeeService(db).create_structure(payload, actor_id=ctx.user_id)


@router.get(
    "/structures/{structure_id}",
    response_model=FeeStructureDetail,
    summary="Get a fee structure with its priced lines",
)
async def get_fee_structure(structure_id: UUID, db: DbSession, _ctx: ReadCtx) -> FeeStructureDetail:
    return await FeeService(db).get_structure_detail(structure_id)


@router.patch(
    "/structures/{structure_id}",
    response_model=FeeStructureDetail,
    summary="Rename a fee structure",
)
async def update_fee_structure(
    structure_id: UUID, payload: FeeStructureUpdate, db: DbSession, ctx: ManageCtx
) -> FeeStructureDetail:
    return await FeeService(db).update_structure(structure_id, payload, actor_id=ctx.user_id)


@router.put(
    "/structures/{structure_id}/items",
    response_model=FeeStructureDetail,
    summary="Add or reprice a fee head in a structure",
)
async def set_fee_structure_item(
    structure_id: UUID, payload: FeeStructureItemInput, db: DbSession, ctx: ManageCtx
) -> FeeStructureDetail:
    """PUT, not POST: idempotent by head. Sending the same head twice reprices the
    existing line rather than creating a duplicate the unique constraint would reject."""
    return await FeeService(db).set_structure_item(structure_id, payload, actor_id=ctx.user_id)


@router.delete(
    "/structures/{structure_id}/items/{head_id}",
    response_model=FeeStructureDetail,
    summary="Remove a fee head from a structure",
)
async def remove_fee_structure_item(
    structure_id: UUID, head_id: UUID, db: DbSession, ctx: ManageCtx
) -> FeeStructureDetail:
    return await FeeService(db).remove_structure_item(structure_id, head_id, actor_id=ctx.user_id)


@router.put(
    "/structures/{structure_id}/stationery",
    response_model=FeeStructureDetail,
    summary="Add a stationery item to a structure, or change its quantity",
)
async def set_fee_structure_stationery(
    structure_id: UUID, payload: FeeStructureStationeryInput, db: DbSession, ctx: ManageCtx
) -> FeeStructureDetail:
    """The per-class default: "every child in Grade 1 gets twelve copies".

    PUT, not POST: idempotent by article, exactly like the fee-head route above. The
    unit price is taken from the catalog and is not accepted from the caller -- see
    `FeeStructureStationeryInput`.
    """
    return await FeeService(db).set_structure_stationery(
        structure_id, payload, actor_id=ctx.user_id
    )


@router.delete(
    "/structures/{structure_id}/stationery/{stationery_item_id}",
    response_model=FeeStructureDetail,
    summary="Remove a stationery item from a structure",
)
async def remove_fee_structure_stationery(
    structure_id: UUID, stationery_item_id: UUID, db: DbSession, ctx: ManageCtx
) -> FeeStructureDetail:
    return await FeeService(db).remove_structure_stationery(
        structure_id, stationery_item_id, actor_id=ctx.user_id
    )


@router.post(
    "/structures/{structure_id}/activate",
    response_model=FeeStructureDetail,
    summary="Activate a fee structure so it can bill",
)
async def activate_fee_structure(
    structure_id: UUID, db: DbSession, ctx: ManageCtx
) -> FeeStructureDetail:
    return await FeeService(db).activate_structure(structure_id, actor_id=ctx.user_id)


@router.post(
    "/structures/{structure_id}/archive",
    response_model=FeeStructureDetail,
    summary="Archive a fee structure",
)
async def archive_fee_structure(
    structure_id: UUID, db: DbSession, ctx: ManageCtx
) -> FeeStructureDetail:
    return await FeeService(db).archive_structure(structure_id, actor_id=ctx.user_id)


# ---------------------------------------------------------------------------
# Concessions -- the named scholarship a family is put ON
# ---------------------------------------------------------------------------
#
# `fee:manage`, and no sixth permission code, for exactly the reason stationery added
# none: a concession scheme answers the question a fee head answers -- what this
# campus may put on a challan, and at what number. Putting a CHILD on a scheme is the
# other question, and that is the student-assignment route below, also `fee:manage`
# because it is a recurring pricing decision.


@router.get(
    "/concessions",
    response_model=Page[FeeConcessionRead],
    summary="List concession schemes",
)
async def list_concessions(
    db: DbSession,
    _ctx: ReadCtx,
    pagination: Pagination,
    sorting: Sorting,
    is_active: Annotated[bool | None, Query(description="Filter by active state.")] = None,
) -> Page[FeeConcessionRead]:
    """Each row carries `student_count` -- how many children are on the scheme, which
    is what makes "what does merit cost us this year?" answerable from this screen
    rather than from a spreadsheet."""
    return await FeeService(db).list_concessions(pagination, sorting, is_active=is_active)


@router.post(
    "/concessions",
    response_model=FeeConcessionRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a concession scheme",
)
async def create_concession(
    payload: FeeConcessionCreate, db: DbSession, ctx: ManageCtx
) -> FeeConcessionRead:
    return await FeeService(db).create_concession(payload, actor_id=ctx.user_id)


@router.patch(
    "/concessions/{concession_id}",
    response_model=FeeConcessionRead,
    summary="Update a concession scheme",
)
async def update_concession(
    concession_id: UUID, payload: FeeConcessionUpdate, db: DbSession, ctx: ManageCtx
) -> FeeConcessionRead:
    """Revising the rate revises it for every student on the scheme, from the NEXT
    generation run. Challans already issued snapshotted their discount and are never
    restated -- the same rule that governs repricing a structure."""
    return await FeeService(db).update_concession(concession_id, payload, actor_id=ctx.user_id)


@router.delete(
    "/concessions/{concession_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a concession scheme",
)
async def delete_concession(concession_id: UUID, db: DbSession, ctx: ManageCtx) -> None:
    """409 while any student is still on it, naming the count. Deactivate instead --
    deleting would silently restore those families to full fees."""
    await FeeService(db).delete_concession(concession_id, actor_id=ctx.user_id)


# ---------------------------------------------------------------------------
# Late fee policy -- the rule, and the run that applies it
# ---------------------------------------------------------------------------


@router.get(
    "/late-fee-policies",
    response_model=list[LateFeePolicyRead],
    summary="List late fee policies",
)
async def list_late_fee_policies(
    db: DbSession,
    _ctx: ReadCtx,
    academic_year: Annotated[str | None, Query(examples=["2026-2027"])] = None,
) -> list[LateFeePolicyRead]:
    return await FeeService(db).list_late_fee_policies(academic_year)


@router.put(
    "/late-fee-policies",
    response_model=LateFeePolicyRead,
    summary="Create or replace the late fee policy for a year",
)
async def set_late_fee_policy(
    payload: LateFeePolicyCreate, db: DbSession, ctx: ManageCtx
) -> LateFeePolicyRead:
    """PUT because it is idempotent by academic year: sending it twice revises that
    year's rule rather than creating a second one. Two live policies would make the
    fine a family owes depend on which row the job read first."""
    return await FeeService(db).set_late_fee_policy(payload, actor_id=ctx.user_id)


@router.delete(
    "/late-fee-policies/{policy_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Retire a late fee policy",
)
async def delete_late_fee_policy(policy_id: UUID, db: DbSession, ctx: ManageCtx) -> None:
    """Soft-deleted. The fines it already raised are untouched -- "what rule produced
    this 200?" is asked months later and a vanished policy cannot answer it."""
    await FeeService(db).delete_late_fee_policy(policy_id, actor_id=ctx.user_id)


@router.post(
    "/late-fee-policies/run",
    response_model=LateFeeRunResult,
    summary="Apply late fees now",
)
async def run_late_fees(
    db: DbSession,
    ctx: IssueCtx,
    academic_year: Annotated[str, Query(examples=["2026-2027"])],
) -> LateFeeRunResult:
    """The manual trigger for what `make run-maintenance` does on a schedule.

    `fee:issue`, because a fine is a challan and this decides who gets one. It is
    IDEMPOTENT -- re-running the same day assesses nothing further -- so an operator
    who clicks it twice is safe, which is exactly why it can be exposed at all.
    """
    return await FeeService(db).apply_late_fees(academic_year, actor_id=ctx.user_id)


# ---------------------------------------------------------------------------
# Unattended monthly generation
# ---------------------------------------------------------------------------
#
# `fee:manage` to CONFIGURE, `fee:issue` to RUN, and the split is the same one that
# governs the rest of the module. Deciding that this campus bills on the 25th, into
# issued challans, carrying arrears forward, is a standing pricing decision -- the
# same kind of decision as pricing a structure. Pressing "run now" is a billing act.
#
# A clerk trusted to bill a class must not be able to move the whole campus's billing
# day or switch on consolidation, which cancels challans.


@router.get(
    "/billing-schedule",
    response_model=FeeBillingScheduleRead | None,
    summary="When this campus bills automatically",
)
async def get_billing_schedule(
    db: DbSession,
    _ctx: ReadCtx,
    academic_year: Annotated[str, Query(examples=["2026-2027"])],
) -> FeeBillingScheduleRead | None:
    """Null when automation has never been configured for this year.

    NULL RATHER THAN A 404, because "not set up" is a normal state that the settings
    screen renders as an empty form -- an error would make a screen that has never
    been visited look broken.
    """
    return await FeeService(db).get_billing_schedule(academic_year)


@router.put(
    "/billing-schedule",
    response_model=FeeBillingScheduleRead,
    summary="Set or revise the automatic billing day",
)
async def set_billing_schedule(
    payload: FeeBillingScheduleInput, db: DbSession, ctx: ManageCtx
) -> FeeBillingScheduleRead:
    """PUT, not POST: idempotent by year, like the structure-item route. Sending the
    same year twice revises the schedule rather than creating a second one, so
    changing the billing day is the same call as setting it."""
    return await FeeService(db).set_billing_schedule(payload, actor_id=ctx.user_id)


@router.post(
    "/billing-schedule/run",
    response_model=BillingRunResult,
    summary="Run this month's generation now, without waiting for the day",
)
async def run_billing_schedule(
    db: DbSession,
    ctx: IssueCtx,
    academic_year: Annotated[str, Query(examples=["2026-2027"])],
) -> BillingRunResult:
    """The same run the nightly job performs, on demand and with a name against it.

    SKIPS THE DAY TEST, NOT THE DUPLICATE TEST. An owner can bill early; they cannot
    bill a period twice by clicking twice -- the second call reports that the period
    has already been generated, and the partial unique index behind it would skip
    every student anyway.

    Returns a result rather than raising when nothing is due: "already generated" is
    an answer, not a failure, and the screen shows it as one.
    """
    return await FeeService(db).run_scheduled_generation(
        academic_year, actor_id=ctx.user_id, force=True
    )


# ---------------------------------------------------------------------------
# Student fee assignments -- where one student departs from their class
# ---------------------------------------------------------------------------
#
# `fee:manage`, NOT `fee:issue`. Putting a child on the bus at 2,000 a month is a
# PRICING decision that recurs every period, which is the same kind of decision as
# adding a line to a structure -- so it sits with the code that governs structures. A
# clerk trusted only to run the monthly billing must not be able to quietly attach a
# 4,000 hostel charge to a student's bill; `fee:issue` lets them generate what has
# been decided, not decide it.
#
# Declared before `/vouchers` so `/students/...` is never parsed as a voucher path.


@router.get(
    "/students/{student_id}/fee-profile",
    response_model=StudentFeeProfile,
    summary="What one student is billed, and where each line comes from",
)
async def student_fee_profile(
    student_id: UUID,
    db: DbSession,
    _ctx: ReadCtx,
    academic_year: Annotated[str, Query(examples=["2026-2027"])],
) -> StudentFeeProfile:
    """The class base, this student's departures from it, and the resulting bill.

    All three, because the effective list alone cannot answer "why is this student
    paying more than their class?" -- which is the question the screen exists for.
    """
    return await FeeService(db).get_student_fee_profile(student_id, academic_year)


@router.put(
    "/students/{student_id}/fee-assignments",
    response_model=StudentFeeProfile,
    summary="Add a student to a fee head, or take them off one",
)
async def set_student_fee_assignment(
    student_id: UUID, payload: StudentFeeAssignmentInput, db: DbSession, ctx: ManageCtx
) -> StudentFeeProfile:
    """PUT, not POST: idempotent by head and year, like the structure item route.
    Sending the same head twice changes the arrangement rather than creating a second
    one, so changing a bus fare is the same call as setting it.

    Takes effect on the NEXT generation run — challans already issued snapshotted
    their lines and are never restated.
    """
    return await FeeService(db).set_student_assignment(student_id, payload, actor_id=ctx.user_id)


@router.delete(
    "/students/{student_id}/fee-assignments/{head_id}",
    response_model=StudentFeeProfile,
    summary="Put a student back on their class default for a fee head",
)
async def remove_student_fee_assignment(
    student_id: UUID,
    head_id: UUID,
    db: DbSession,
    ctx: ManageCtx,
    academic_year: Annotated[str, Query(examples=["2026-2027"])],
) -> StudentFeeProfile:
    return await FeeService(db).remove_student_assignment(
        student_id, head_id, academic_year, actor_id=ctx.user_id
    )


# ---------------------------------------------------------------------------
# The student ledger -- the running account
# ---------------------------------------------------------------------------


@router.get(
    "/students/{student_id}/ledger",
    response_model=StudentLedgerStatement,
    summary="A student's running account",
)
async def student_ledger(
    student_id: UUID, db: DbSession, _ctx: ReadCtx, pagination: Pagination
) -> StudentLedgerStatement:
    """The balance, and the movements that produced it, newest first.

    `balance` may be NEGATIVE, meaning the school holds the family's money -- an
    advance payment, or a reversal after a refund. It is deliberately not clamped to
    zero: clamping would hide money the school actually owes back.
    """
    return await FeeService(db).get_student_ledger(student_id, pagination)


@router.post(
    "/students/{student_id}/ledger/adjustments",
    response_model=StudentLedgerStatement,
    status_code=status.HTTP_201_CREATED,
    summary="Adjust a student's balance by hand",
)
async def adjust_student_ledger(
    student_id: UUID, payload: LedgerAdjustmentInput, db: DbSession, ctx: VoidCtx
) -> StudentLedgerStatement:
    """`fee:void`, NOT `fee:collect`, and that is the whole point of the route.

    This is the one action in the module that moves money with no voucher and no
    receipt behind it -- which makes it the one an accountant could use to cover a
    shortfall. The same separation of duties that stops the person recording payments
    from being the person who can reverse them stops them from writing a balance off.
    """
    return await FeeService(db).adjust_ledger(student_id, payload, actor_id=ctx.user_id)


# ---------------------------------------------------------------------------
# Vouchers (challans)
# ---------------------------------------------------------------------------


@router.post(
    "/vouchers/generate",
    response_model=VoucherGenerateResult,
    status_code=status.HTTP_201_CREATED,
    summary="Generate vouchers for a class and period",
)
async def generate_vouchers(
    payload: VoucherGenerateRequest, db: DbSession, ctx: IssueCtx
) -> VoucherGenerateResult:
    """Bulk billing. Students already billed for the period are SKIPPED with a reason
    rather than failing the run -- see the response's `skipped` and `truncated`."""
    return await FeeService(db).generate_vouchers(payload, actor_id=ctx.user_id)


@router.get(
    "/vouchers/export",
    summary="Download the voucher register as CSV",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/csv": {}}, "description": "The voucher register."}},
)
async def export_vouchers(
    db: DbSession,
    _ctx: ReadCtx,
    academic_year: Annotated[str | None, Query(examples=["2026-2027"])] = None,
    period_label: Annotated[str | None, Query(examples=["2026-08"])] = None,
    voucher_status: Annotated[VoucherStatus | None, Query(alias="status")] = None,
) -> StreamingResponse:
    """The register a finance office reconciles against its bank statement.

    Declared BEFORE `/vouchers/{voucher_id}`, or Starlette parses "export" as a UUID
    and answers 422. Capped, and the cap is announced inside the file -- a truncated
    export that reads as a complete one is worse than a refused one.
    """
    body = await FeeService(db).export_vouchers_csv(
        academic_year=academic_year, period_label=period_label, status=voucher_status
    )
    stamp = academic_year or "all"
    return StreamingResponse(
        iter([body]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="fee-vouchers-{stamp}.csv"'},
    )


@router.get("/vouchers", response_model=Page[FeeVoucherRead], summary="List fee vouchers")
async def list_vouchers(
    db: DbSession,
    _ctx: ReadCtx,
    params: Pagination,
    sort: Sorting,
    student_id: UUID | None = None,
    voucher_status: Annotated[VoucherStatus | None, Query(alias="status")] = None,
    academic_year: Annotated[str | None, Query(examples=["2026-2027"])] = None,
    period_label: Annotated[str | None, Query(examples=["2026-08"])] = None,
) -> Page[FeeVoucherRead]:
    return await FeeService(db).list_vouchers(
        params,
        sort,
        student_id=student_id,
        status=voucher_status,
        academic_year=academic_year,
        period_label=period_label,
    )


@router.post(
    "/payments/{payment_id}/reverse",
    response_model=FeePaymentRead,
    summary="Reverse a recorded payment",
)
async def reverse_payment(
    payment_id: UUID, payload: PaymentReverseRequest, db: DbSession, ctx: VoidCtx
) -> FeePaymentRead:
    """Declared before `/vouchers/{voucher_id}` purely for grouping; the paths do not
    collide. Requires `fee:void`, not `fee:collect` -- separation of duties."""
    return await FeeService(db).reverse_payment(payment_id, payload.reason, actor_id=ctx.user_id)


@router.get(
    "/vouchers/{voucher_id}",
    response_model=FeeVoucherDetail,
    summary="Get a voucher with its lines and receipts",
)
async def get_voucher(voucher_id: UUID, db: DbSession, _ctx: ReadCtx) -> FeeVoucherDetail:
    return await FeeService(db).get_voucher_detail(voucher_id)


@router.get("/vouchers/{voucher_id}/pdf", summary="Download the printable challan")
async def download_challan_pdf(voucher_id: UUID, db: DbSession, ctx: ReadCtx) -> StreamingResponse:
    """One A4 page, three detachable copies (Bank / School / Student).

    The voucher is resolved through RLS and the school predicate BEFORE rendering, so
    the renderer itself performs no authorization and cannot be handed a foreign row.
    """
    service = FeeService(db)
    voucher = await service.vouchers.get_detail(voucher_id)
    if voucher is None:
        raise NotFoundError("Fee voucher not found.")

    school = await db.get(School, voucher.school_id)
    if school is None:
        raise NotFoundError("School not found.")

    payload = render_challan_pdf(voucher, school)
    return StreamingResponse(
        iter([payload]),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="challan-{voucher.voucher_number}.pdf"',
            # A challan names a minor and what their family owes. It must not sit in
            # a shared proxy cache or a browser's disk cache on a school office PC.
            "Cache-Control": "private, no-store",
        },
    )


@router.post(
    "/vouchers/{voucher_id}/issue",
    response_model=FeeVoucherDetail,
    summary="Issue a draft voucher",
)
async def issue_voucher(voucher_id: UUID, db: DbSession, ctx: IssueCtx) -> FeeVoucherDetail:
    return await FeeService(db).issue_voucher(voucher_id, actor_id=ctx.user_id)


@router.post(
    "/vouchers/{voucher_id}/void",
    response_model=FeeVoucherDetail,
    summary="Void a voucher",
)
async def void_voucher(
    voucher_id: UUID, payload: VoucherVoidRequest, db: DbSession, ctx: VoidCtx
) -> FeeVoucherDetail:
    """Refused while any non-reversed payment exists. The reason is mandatory and
    lands in the audit row."""
    return await FeeService(db).void_voucher(voucher_id, payload.reason, actor_id=ctx.user_id)


@router.put(
    "/vouchers/{voucher_id}/stationery",
    response_model=FeeVoucherDetail,
    summary="Charge a stationery item to a draft challan",
)
async def add_voucher_stationery(
    voucher_id: UUID, payload: VoucherStationeryInput, db: DbSession, ctx: IssueCtx
) -> FeeVoucherDetail:
    """The per-student charge: "Ali also took two more copies".

    DRAFT ONLY -- 409 once the challan is issued, because an issued bill is never
    rewritten. Charge the next period's challan instead, or void and reissue.

    `fee:issue`, not `fee:manage`: this decides who is charged, not what may be
    charged. PUT because it is idempotent by article -- sending the same item twice
    sets the quantity rather than adding a second line.
    """
    return await FeeService(db).add_voucher_charge(voucher_id, payload, actor_id=ctx.user_id)


@router.put(
    "/vouchers/{voucher_id}/charges",
    response_model=FeeVoucherDetail,
    summary="Charge a fee head to a draft challan",
)
async def add_voucher_fee_charge(
    voucher_id: UUID, payload: VoucherFeeChargeInput, db: DbSession, ctx: IssueCtx
) -> FeeVoucherDetail:
    """The one-off charge: a fine, a re-exam fee, a broken lab window.

    WHY THIS EXISTS: without it the only tool for "charge Ali 500 for the window" is
    the CLASS structure -- add a Breakage line, generate, remove it next month. That
    bills the whole grade for one broken window, and forty parents find the error
    before the school does.

    DRAFT ONLY, and idempotent by head: charging the same head twice sets the line
    rather than adding a second one. Charging a head the structure already priced
    RESTATES that line, which is correct on a bill still being assembled -- the audit
    row carries what was there before.
    """
    return await FeeService(db).add_voucher_fee_charge(voucher_id, payload, actor_id=ctx.user_id)


@router.delete(
    "/vouchers/{voucher_id}/charges/{head_id}",
    response_model=FeeVoucherDetail,
    summary="Remove a fee charge from a draft challan",
)
async def remove_voucher_fee_charge(
    voucher_id: UUID, head_id: UUID, db: DbSession, ctx: IssueCtx
) -> FeeVoucherDetail:
    """Draft only. Removes a line the class structure put there as readily as a
    one-off charge -- the supported way to say "this student is not paying the exam
    fee this term" without touching the structure every other student is billed from.
    The standing version of the same intent is an EXCLUDED assignment."""
    return await FeeService(db).remove_voucher_fee_charge(voucher_id, head_id, actor_id=ctx.user_id)


@router.delete(
    "/vouchers/{voucher_id}/stationery/{stationery_item_id}",
    response_model=FeeVoucherDetail,
    summary="Remove a stationery charge from a draft challan",
)
async def remove_voucher_stationery(
    voucher_id: UUID, stationery_item_id: UUID, db: DbSession, ctx: IssueCtx
) -> FeeVoucherDetail:
    """Draft only, same rule and same reason as adding one."""
    return await FeeService(db).remove_voucher_charge(
        voucher_id, stationery_item_id, actor_id=ctx.user_id
    )


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


@router.get(
    "/vouchers/{voucher_id}/payments",
    response_model=list[FeePaymentRead],
    summary="List receipts against a voucher",
)
async def list_voucher_payments(
    voucher_id: UUID, db: DbSession, _ctx: ReadCtx
) -> list[FeePaymentRead]:
    return await FeeService(db).list_payments(voucher_id)


@router.post(
    "/vouchers/{voucher_id}/payments",
    response_model=FeePaymentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record a payment and issue a receipt",
)
async def record_payment(
    voucher_id: UUID, payload: FeePaymentCreate, db: DbSession, ctx: CollectCtx
) -> FeePaymentRead:
    """Rejects overpayment rather than parking it as credit -- slice 1 has no ledger
    to hold a credit balance, and a number with nowhere to live goes missing."""
    return await FeeService(db).record_payment(voucher_id, payload, actor_id=ctx.user_id)
