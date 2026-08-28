"""Fees API contracts.

WHY SEPARATE FROM models.py
    These describe what a client may SEND and what it WILL RECEIVE -- deliberately
    not the table shape. Note what is absent from every Create schema:

      * `organization_id` and `school_id` -- taken from the verified JWT. Accepting
        either would be a mass-assignment hole straight into another tenant.
      * `voucher_number`, `receipt_number` -- generated server-side. A caller who
        could choose a receipt number could overwrite the audit trail's primary
        human-readable handle.
      * `status`, `paid_total`, `total` on vouchers -- derived. A client that could
        set `status: paid` could mark a bill settled without any money arriving.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.common.schemas import BaseSchema
from app.modules.fees.models import (
    ConcessionKind,
    FeeLineType,
    FeePaymentStatus,
    FeeRecurrence,
    FeeStructureStatus,
    LateFeeKind,
    LateFeeRecurrence,
    LedgerEntryType,
    PaymentMethod,
    StationeryCategory,
    StationeryUnit,
    StudentFeeAssignmentMode,
    VoucherOrigin,
    VoucherStatus,
)

# `2026-2027`. Validated here rather than by a CHECK constraint so the error names
# the field and reaches the form that produced it.
_ACADEMIC_YEAR_RE = re.compile(r"^(\d{4})-(\d{4})$")


def _validate_academic_year(value: str) -> str:
    """Enforce `NNNN-NNNN` with consecutive years.

    The consecutive check matters: "2026-2030" is a typo every time, and catching it
    at the door prevents a structure nobody can find because it is filed under a year
    that does not exist.
    """
    match = _ACADEMIC_YEAR_RE.match(value)
    if match is None:
        raise ValueError("Academic year must look like '2026-2027'.")
    start, end = int(match.group(1)), int(match.group(2))
    if end != start + 1:
        raise ValueError("Academic year must span two consecutive years, e.g. '2026-2027'.")
    return value


# ---------------------------------------------------------------------------
# Fee heads
# ---------------------------------------------------------------------------


class FeeHeadCreate(BaseSchema):
    code: str = Field(min_length=1, max_length=40, examples=["TUITION"])
    name: str = Field(min_length=1, max_length=120, examples=["Tuition"])
    description: str | None = Field(default=None, max_length=1000)
    recurrence: FeeRecurrence = FeeRecurrence.MONTHLY
    is_refundable: bool = False
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0, le=999)

    @field_validator("code")
    @classmethod
    def _normalise_code(cls, value: str) -> str:
        """Upper-case so `tuition` and `TUITION` collide on the unique constraint
        instead of becoming two heads that print identically on a challan."""
        return value.upper()


class FeeHeadUpdate(BaseSchema):
    """PATCH: omission means "leave unchanged".

    `code` is absent on purpose. Renaming a head is safe because vouchers snapshot
    the name, but re-coding one silently re-points every report that groups by code.
    Retire the head and create a new one instead.
    """

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    recurrence: FeeRecurrence | None = None
    is_refundable: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=999)


class FeeHeadRead(BaseSchema):
    id: UUID
    code: str
    name: str
    description: str | None
    recurrence: FeeRecurrence
    is_refundable: bool
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Stationery catalog
# ---------------------------------------------------------------------------
#
# The counterpart of the fee-head block above: a head is a flat charge, an item here
# is a UNIT PRICE that a quantity multiplies. `unit_price` is the only number the
# catalog owns -- every line that charges the item snapshots it, so editing it here
# reprices the next challan and never a past one.


class StationeryItemCreate(BaseSchema):
    code: str = Field(min_length=1, max_length=40, examples=["COPY-100"])
    name: str = Field(min_length=1, max_length=120, examples=["Copy (Register, 100 pages)"])
    description: str | None = Field(default=None, max_length=1000)
    category: StationeryCategory = StationeryCategory.STATIONERY
    unit: StationeryUnit = StationeryUnit.PIECE
    unit_price: Decimal = Field(ge=0, max_digits=12, decimal_places=2, examples=["60.00"])
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0, le=999)

    @field_validator("code")
    @classmethod
    def _normalise_code(cls, value: str) -> str:
        """Upper-cased for the same reason `FeeHeadCreate.code` is: `copy-100` and
        `COPY-100` must collide on the unique constraint rather than becoming two
        articles that print identically on a challan."""
        return value.upper()


class StationeryItemUpdate(BaseSchema):
    """PATCH: omission means "leave unchanged".

    `code` is absent on purpose, matching `FeeHeadUpdate` -- re-coding an article
    silently re-points every report that groups by code. Retire it and add a new one.

    `unit_price` IS present and editable: repricing is the normal, expected operation
    on a catalog, and it is safe precisely because every charged line snapshotted the
    price it sold at.
    """

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    category: StationeryCategory | None = None
    unit: StationeryUnit | None = None
    unit_price: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=999)


class StationeryItemRead(BaseSchema):
    id: UUID
    code: str
    name: str
    description: str | None
    category: StationeryCategory
    unit: StationeryUnit
    unit_price: Decimal
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Fee structures
# ---------------------------------------------------------------------------


class FeeStructureItemInput(BaseSchema):
    """Price one FEE HEAD in a structure. Stationery uses its own input below.

    Two inputs rather than one polymorphic body with three optional fields: a single
    schema would have to accept `head_id`, `stationery_item_id`, `amount` and
    `quantity` as all-optional and then reject four of the sixteen combinations in a
    validator. Two shapes make the two legal combinations the only expressible ones,
    and give each endpoint an unambiguous OpenAPI contract.
    """

    head_id: UUID
    amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class FeeStructureStationeryInput(BaseSchema):
    """Add a stationery article to a structure, or change how many of it.

    `unit_price` is NOT accepted. It is copied from the catalog at the moment the
    line is added, so the amount a structure charges can never be a number the
    catalog has no record of -- which is what keeps "why is this class paying 80 for
    a 60-rupee copy?" answerable.
    """

    stationery_item_id: UUID
    quantity: Decimal = Field(
        default=Decimal(1), gt=0, le=Decimal(9999), max_digits=10, decimal_places=2
    )


class FeeStructureCreate(BaseSchema):
    class_id: UUID
    academic_year: str = Field(min_length=9, max_length=9, examples=["2026-2027"])
    name: str = Field(min_length=1, max_length=120, examples=["Grade 10 — 2026-2027"])
    items: list[FeeStructureItemInput] = Field(
        default_factory=list,
        max_length=50,
        description="Optional starting lines; more can be added while the structure is a draft.",
    )

    @field_validator("academic_year")
    @classmethod
    def _check_year(cls, value: str) -> str:
        return _validate_academic_year(value)


class FeeStructureUpdate(BaseSchema):
    """Metadata only. Status moves through `/activate` and `/archive`, and items
    through the item endpoints -- so a transition is never a side effect of a PATCH
    that was meant to fix a typo in the name."""

    name: str | None = Field(default=None, min_length=1, max_length=120)


class FeeStructureItemRead(BaseSchema):
    """One priced line, of either kind.

    ONE SHAPE FOR BOTH on the way out, unlike the two Create schemas. A client
    rendering the structure editor wants a single list it can sum and sort;
    `line_type` tells it whether to show the quantity column for a row, and the
    reference fields are nullable accordingly.
    """

    id: UUID
    line_type: FeeLineType
    name: str
    """The head's name or the article's name -- whichever this line references."""
    code: str
    """The head's code or the article's code."""
    head_id: UUID | None
    stationery_item_id: UUID | None
    unit: StationeryUnit | None = None
    """NULL on a fee line."""
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal


class FeeStructureRead(BaseSchema):
    id: UUID
    class_id: UUID
    academic_year: str
    name: str
    status: FeeStructureStatus
    created_at: datetime
    updated_at: datetime


class FeeStructureDetail(FeeStructureRead):
    """A structure with its priced lines and their totals, for the editor screen."""

    items: list[FeeStructureItemRead]
    total: Decimal
    fee_total: Decimal
    """The FEE lines alone. Broken out because the two numbers answer different
    questions -- "what does this class pay us every month" is a fee figure, and a
    one-off book set in the August structure would otherwise make it look like the
    monthly charge tripled."""
    stationery_total: Decimal


# ---------------------------------------------------------------------------
# Student fee assignments -- where one student departs from their class
# ---------------------------------------------------------------------------


class StudentFeeAssignmentInput(BaseSchema):
    """Put a student on, or take them off, one fee head for a year.

    `amount` is required when adding and rejected when excluding, checked here rather
    than only by the CHECK constraint so the error names the field and reaches the
    form that produced it. An excluded head has no amount because the line is ABSENT
    from the challan, not zero -- a "Transport 0.00" line is a phone call.
    """

    head_id: UUID
    academic_year: str = Field(min_length=9, max_length=9, examples=["2026-2027"])
    mode: StudentFeeAssignmentMode
    amount: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2,
        description=(
            "Required when adding a head or overriding its rate. Must be omitted when "
            "excluding one. On a discount it is the flat sum taken off, and is one of "
            "three mutually exclusive ways to express the remission."
        ),
    )
    percent: Decimal | None = Field(
        default=None,
        gt=0,
        le=100,
        max_digits=5,
        decimal_places=2,
        description="Discounts only: the share of the line to take off. `50` is half.",
        examples=["50.00"],
    )
    concession_id: UUID | None = Field(
        default=None,
        description=(
            "Discounts only: the named scheme supplying the rate. Preferred over an "
            "ad-hoc amount or percent, because revising the scheme then revises every "
            "student on it."
        ),
    )
    note: str | None = Field(default=None, max_length=500, examples=["Route 4 — Gulberg"])

    @field_validator("academic_year")
    @classmethod
    def _check_year(cls, value: str) -> str:
        return _validate_academic_year(value)

    @model_validator(mode="after")
    def _amount_matches_mode(self) -> StudentFeeAssignmentInput:
        """A `model_validator`, NOT a `field_validator` on `amount`.

        A field validator does not run when the field is absent from the request and
        falls back to its default -- which is precisely the case that matters here,
        "added with no amount". That version passed validation and was caught by the
        database CHECK instead, surfacing as an opaque 409 integrity error rather than
        a 422 naming the field. Validating the model as a whole runs either way.
        """
        if self.mode is not StudentFeeAssignmentMode.DISCOUNT and (
            self.percent is not None or self.concession_id is not None
        ):
            raise ValueError("A percentage or a concession scheme only applies to a discount.")

        if self.mode is StudentFeeAssignmentMode.ADDED and self.amount is None:
            raise ValueError("An amount is required when adding a fee head to a student.")
        if self.mode is StudentFeeAssignmentMode.OVERRIDE and self.amount is None:
            raise ValueError("An amount is required when overriding a student's rate.")
        if self.mode is StudentFeeAssignmentMode.EXCLUDED and self.amount is not None:
            raise ValueError(
                "An excluded fee head carries no amount — the line is left off the "
                "challan entirely."
            )
        if self.mode is StudentFeeAssignmentMode.DISCOUNT:
            # EXACTLY ONE of the three, counted rather than checked pairwise. A
            # discount carrying both a scheme and its own percent has no single
            # answer to "what rate is this child on", and the version of that bug
            # that reaches production is the one where the two disagree.
            supplied = sum(
                value is not None for value in (self.concession_id, self.amount, self.percent)
            )
            if supplied == 0:
                raise ValueError(
                    "A discount needs a concession scheme, a flat amount, or a percentage."
                )
            if supplied > 1:
                raise ValueError(
                    "A discount takes exactly one of a concession scheme, a flat "
                    "amount, or a percentage — not more than one."
                )
        return self


class StudentFeeAssignmentRead(BaseSchema):
    id: UUID
    student_id: UUID
    head_id: UUID
    head_code: str
    head_name: str
    academic_year: str
    mode: StudentFeeAssignmentMode
    amount: Decimal | None
    percent: Decimal | None = None
    concession_id: UUID | None = None
    concession_code: str | None = None
    concession_name: str | None = None
    """Resolved and returned alongside the id so the screen can name the scheme
    without a second request per row -- the fee tab of a class of forty would
    otherwise fetch the same six schemes forty times."""
    note: str | None
    created_at: datetime
    updated_at: datetime


class StudentFeeLine(BaseSchema):
    """One line of what a student will actually be billed, and where it came from."""

    head_id: UUID
    head_code: str
    head_name: str
    amount: Decimal
    """GROSS -- before any concession. The challan shows this figure and the discount
    beside it, never a single netted number: a remission applied by quietly lowering
    the amount is indistinguishable on paper from a repricing, and the family cannot
    see they were awarded anything."""
    discount_amount: Decimal = Decimal("0.00")
    net_amount: Decimal = Decimal("0.00")
    """`amount - discount_amount`, and what actually gets billed. Computed once by
    `_effective_lines()` rather than by each caller, because the profile screen and
    the generation run must agree to the rupee."""
    source: str
    """Where the line's amount came from, and the screen shows it so an operator can
    tell at a glance which numbers they own and which follow the class -- editing the
    wrong one is how a whole grade gets repriced by accident.

      `class`      the class structure, untouched
      `student`    added for this student alone
      `override`   the class head, at a rate agreed for this student
      `discount`   carries a remission (the base may be any of the above)
    """
    concession_name: str | None = None
    """Which scheme paid for the remission, when one did. Printed on the challan: a
    family should be able to see that the reduction is their staff entitlement rather
    than an unexplained adjustment somebody might take away next month."""


class StudentFeeProfile(BaseSchema):
    """What one student is billed for a year: the class base, their departures from
    it, and the result.

    ALL THREE, NOT JUST THE RESULT. An effective list alone cannot answer "why is
    Ali paying 4,000 more than his class?", which is the question this screen exists
    for. Returning the base and the assignments beside it turns that into something
    the operator can read instead of something they have to reconstruct.
    """

    student_id: UUID
    student_name: str
    admission_number: str
    academic_year: str
    class_id: UUID | None
    structure_id: UUID | None
    """Both null when the student is in no section, or their class has no structure
    for this year. `effective` is then just their individual additions, and the
    screen says so rather than showing a confidently wrong zero."""
    structure_name: str | None
    base: list[StudentFeeLine]
    """The class structure's FEE lines. Stationery is excluded: it is charged by
    quantity per challan, not carried as a standing per-student arrangement."""
    assignments: list[StudentFeeAssignmentRead]
    effective: list[StudentFeeLine]
    effective_total: Decimal
    """NET of concessions -- what the next challan will actually bill."""
    gross_total: Decimal = Decimal("0.00")
    discount_total: Decimal = Decimal("0.00")
    """Both returned so the screen can show "8,500 less 2,000 concession" rather than
    a single 6,500 that looks like a repricing. "What is this family's remission
    worth?" is asked at every fee review and cannot be recovered from the net."""


# ---------------------------------------------------------------------------
# Vouchers
# ---------------------------------------------------------------------------


class VoucherGenerateRequest(BaseSchema):
    """Bulk generation input.

    `student_ids` and `section_id` narrow the run; omitting both targets every active
    student in the structure's class. They compose -- passing both is "these students,
    and only if they are in that section" -- which is what makes a re-run after a
    correction safe to scope tightly.
    """

    structure_id: UUID
    period_label: str = Field(min_length=1, max_length=40, examples=["2026-08"])
    issue_date: date
    due_date: date
    section_id: UUID | None = Field(
        default=None, description="Restrict the run to one section of the class."
    )
    student_ids: list[UUID] | None = Field(
        default=None,
        max_length=500,
        description="Restrict the run to specific students.",
    )
    issue_immediately: bool = Field(
        default=False,
        description="Issue each generated voucher instead of leaving it as a draft.",
    )
    include_stationery: bool = Field(
        default=True,
        description=(
            "Copy the structure's stationery lines onto each challan. Turn this OFF "
            "for the monthly runs of a structure whose book or uniform set is meant "
            "to be billed once a year -- otherwise every month re-bills the books."
        ),
    )
    carry_forward_dues: bool = Field(
        default=False,
        description=(
            "Bill each family's unpaid earlier challans as a line ON this one, and "
            "cancel the challans that balance came from, so exactly one document is "
            "payable. A challan that has taken part payment is never absorbed -- its "
            "receipts point at it -- and its balance keeps being printed beside the "
            "total as before. The cancellation happens when this challan is ISSUED, "
            "not while it is a draft."
        ),
    )
    carry_forward_head_id: UUID | None = Field(
        default=None,
        description=(
            "The fee head the carried balance is billed under, e.g. 'Previous dues'. "
            "Required when `carry_forward_dues` is set: arrears billed under no head "
            "would be a figure with no home in any collection report."
        ),
    )
    notes: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def _carry_forward_needs_head(self) -> VoucherGenerateRequest:
        if self.carry_forward_dues and self.carry_forward_head_id is None:
            raise ValueError("A fee head is required to bill carried-forward dues under.")
        return self


class VoucherSkip(BaseSchema):
    """One student the run did not bill, and why.

    Returned rather than raised: a partial failure that rolls back 400 challans
    because one student was already billed is not a usable product.
    """

    student_id: UUID
    admission_number: str
    reason: str


class VoucherGenerateResult(BaseSchema):
    created: int
    skipped: list[VoucherSkip]
    voucher_ids: list[UUID]
    truncated: bool = Field(
        default=False,
        description=(
            "True when the class held more eligible students than one run may bill. "
            "Filter by section and run again for the remainder."
        ),
    )
    absorbed_vouchers: int = Field(
        default=0,
        description=(
            "How many older challans this run reserved to absorb. They are cancelled "
            "when the new challan is issued, not before -- so a run that produced "
            "drafts has reserved this many and cancelled none."
        ),
    )
    absorbed_total: Decimal = Field(
        default=Decimal("0.00"),
        description="The arrears billed onto the new challans, in total.",
    )


class VoucherItemRead(BaseSchema):
    """One snapshotted challan line, of either kind.

    Every field here is what was FROZEN at generation, not what the catalog says
    today. `head_id` / `stationery_item_id` are carried only so a report can group by
    the live record; nothing rendered to a parent should read them.
    """

    id: UUID
    line_type: FeeLineType
    line_name: str
    head_id: UUID | None
    stationery_item_id: UUID | None
    unit_label: str | None
    """The unit this article was sold in, e.g. "dozen". NULL on a fee line."""
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    discount_amount: Decimal


class VoucherStationeryInput(BaseSchema):
    """Charge a stationery article to ONE student's draft challan.

    The ad-hoc path, as opposed to the structure's per-class defaults: a student who
    took two extra copies in October is billed here, on their own draft, and nobody
    else in the class is touched.

    Idempotent by article -- sending the same item twice SETS the quantity rather
    than adding a second line, which is what the partial unique index on
    `(voucher_id, stationery_item_id)` guarantees at the storage layer too.
    """

    stationery_item_id: UUID
    quantity: Decimal = Field(
        default=Decimal(1), gt=0, le=Decimal(9999), max_digits=10, decimal_places=2
    )
    unit_price: Decimal | None = Field(
        default=None,
        ge=0,
        max_digits=12,
        decimal_places=2,
        description=(
            "Override the catalog price for this one line, e.g. a damaged copy sold "
            "at half price. Omit to charge the catalog price."
        ),
    )


class FeeVoucherRead(BaseSchema):
    id: UUID
    student_id: UUID
    # Carried on the LIST, not just the detail: the register is scanned by a human
    # looking for a person, and a row identified only by UUID cannot be acted on.
    student_name: str
    admission_number: str
    structure_id: UUID | None
    voucher_number: str
    academic_year: str
    period_label: str
    issue_date: date
    due_date: date
    status: VoucherStatus
    origin: VoucherOrigin
    source_voucher_id: UUID | None = None
    """The overdue challan this one fines, when `origin` is `late_fee`."""
    currency: str
    subtotal: Decimal
    discount_total: Decimal
    total: Decimal
    paid_total: Decimal
    outstanding: Decimal
    arrears_brought_forward: Decimal = Decimal("0.00")
    """What the family owed when this challan was generated that this challan does
    NOT bill -- snapshotted and printed beside the total, never inside it.

    On an ordinary run that is the family's whole balance: the older challans are
    still outstanding and still payable, so adding their total here would bill the
    same rupee twice. On a CONSOLIDATING run the absorbed challans are billed as a
    real line and cancelled, and what is left here is only the remainder that could
    not be absorbed -- part-paid challans, which keep their own document because
    their receipts point at it."""

    superseded_by_voucher_id: UUID | None = None
    """Set on an OLD challan that a newer one has absorbed or reserved. While the
    newer challan is a draft this one is still live and still payable; it is voided
    when the newer one is issued."""
    superseded_by_voucher_number: str | None = None
    """Resolved so a cancelled challan can name its replacement without the screen
    fetching it -- "why is this void?" is the only question a voided challan is ever
    opened to answer."""
    notes: str | None
    issued_at: datetime | None
    paid_at: datetime | None
    voided_at: datetime | None
    void_reason: str | None
    created_at: datetime
    updated_at: datetime


class FeeVoucherDetail(FeeVoucherRead):
    """A voucher with its lines and receipts -- the challan detail screen.

    `student_name` and `admission_number` are inherited; they belong to every voucher
    view, not only this one.
    """

    items: list[VoucherItemRead]
    payments: list[FeePaymentRead]


class VoucherVoidRequest(BaseSchema):
    reason: str = Field(
        min_length=3,
        max_length=500,
        description="Mandatory. Lands in the audit row, which is the point.",
    )


# ---------------------------------------------------------------------------
# Payments
# ---------------------------------------------------------------------------


class FeePaymentCreate(BaseSchema):
    amount: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    method: PaymentMethod = PaymentMethod.CASH
    reference: str | None = Field(
        default=None, max_length=120, description="Cheque number or bank transaction id."
    )
    received_on: date | None = Field(
        default=None, description="Defaults to today. Backdate for money taken earlier."
    )
    received_by_user_id: UUID | None = Field(
        default=None,
        description="Who physically took the money, if not the person recording it.",
    )
    notes: str | None = Field(default=None, max_length=1000)


class FeePaymentRead(BaseSchema):
    id: UUID
    voucher_id: UUID
    receipt_number: str
    amount: Decimal
    currency: str
    method: PaymentMethod
    reference: str | None
    received_on: date
    received_by_user_id: UUID | None
    status: FeePaymentStatus
    notes: str | None
    reversed_at: datetime | None
    reversal_reason: str | None
    created_at: datetime


class PaymentReverseRequest(BaseSchema):
    reason: str = Field(min_length=3, max_length=500)


# ---------------------------------------------------------------------------
# Collection summary
# ---------------------------------------------------------------------------


class VoucherStatusCount(BaseSchema):
    status: VoucherStatus
    count: int
    total: Decimal


class FeeSummary(BaseSchema):
    """The collection dashboard for one academic year and optional period."""

    academic_year: str
    period_label: str | None
    currency: str
    billed: Decimal
    """Sum of `total` across every non-void voucher."""
    collected: Decimal
    """Sum of `paid_total`, i.e. money actually received."""
    outstanding: Decimal
    """`billed - collected`. Not recomputed from payments -- the two must agree, and
    deriving them from the same source is what guarantees they do."""
    overdue: Decimal
    """The part of `outstanding` whose due date has passed."""
    stationery_billed: Decimal
    """The part of `billed` that is stationery rather than fees.

    Summed from the challan LINES, not from the catalog: what matters is what was
    actually charged, and a line whose price was overridden or whose article has
    since been repriced must still report the number that went on the bill."""
    voucher_count: int
    by_status: list[VoucherStatusCount]


# `FeeVoucherDetail` names `FeePaymentRead` before it is defined, which the
# `from __future__ import annotations` at the top turns into a forward reference.
# Pydantic needs this to resolve it into the real class.
FeeVoucherDetail.model_rebuild()


# ---------------------------------------------------------------------------
# Concessions -- the named scholarship a family is put ON
# ---------------------------------------------------------------------------


class FeeConcessionCreate(BaseSchema):
    """A remission scheme: Staff Child 50%, Merit 25%, Sibling 1,000 off."""

    code: str = Field(min_length=1, max_length=40, examples=["STAFF"])
    name: str = Field(min_length=1, max_length=120, examples=["Staff child remission"])
    description: str | None = Field(default=None, max_length=1000)
    kind: ConcessionKind = ConcessionKind.PERCENT
    value: Decimal = Field(
        gt=0,
        max_digits=12,
        decimal_places=2,
        description="A percentage (1-100) when `kind` is percent, a flat sum when amount.",
        examples=["50.00"],
    )
    is_active: bool = True
    sort_order: int = Field(default=0, ge=0, le=999)

    @model_validator(mode="after")
    def _percent_within_range(self) -> FeeConcessionCreate:
        """Checked here as well as by the CHECK constraint so a typo names the field.

        A 500% scheme is a scheme that pays the family to attend. It is always a
        misplaced decimal, and it is worth catching at the door rather than as an
        opaque integrity error three screens later.
        """
        if self.kind is ConcessionKind.PERCENT and self.value > 100:
            raise ValueError("A percentage concession cannot exceed 100%.")
        return self


class FeeConcessionUpdate(BaseSchema):
    """Every field optional. `code` is absent on purpose, exactly as on a fee head:
    it is the handle a school's own paperwork refers to, and renaming it silently
    re-points every reference that used it."""

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = Field(default=None, max_length=1000)
    kind: ConcessionKind | None = None
    value: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    is_active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=999)


class FeeConcessionRead(BaseSchema):
    id: UUID
    code: str
    name: str
    description: str | None
    kind: ConcessionKind
    value: Decimal
    is_active: bool
    sort_order: int
    student_count: int = 0
    """How many students are on this scheme this year. Returned on the list so a
    principal can answer "what does merit cost us?" without opening every row."""
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Late fee policy -- the rule the fine job applies
# ---------------------------------------------------------------------------


class LateFeePolicyCreate(BaseSchema):
    academic_year: str = Field(min_length=9, max_length=9, examples=["2026-2027"])
    name: str = Field(min_length=1, max_length=120, examples=["Standard late fee"])
    head_id: UUID = Field(description="The fee head fines are billed under.")
    kind: LateFeeKind = LateFeeKind.FIXED
    value: Decimal = Field(
        gt=0,
        max_digits=12,
        decimal_places=2,
        description=(
            "A flat sum when `kind` is fixed; a percentage of the OUTSTANDING balance when percent."
        ),
        examples=["200.00"],
    )
    grace_days: int = Field(
        default=0,
        ge=0,
        le=365,
        description="Days after the due date before anything is charged.",
    )
    recurrence: LateFeeRecurrence = LateFeeRecurrence.ONCE
    max_amount: Decimal | None = Field(
        default=None,
        gt=0,
        max_digits=12,
        decimal_places=2,
        description="Ceiling on the total fined against one challan. Required unless `once`.",
    )
    min_outstanding: Decimal = Field(
        default=Decimal("0.00"),
        ge=0,
        max_digits=12,
        decimal_places=2,
        description="Balances below this are not fined.",
    )
    is_active: bool = True

    @field_validator("academic_year")
    @classmethod
    def _check_year(cls, value: str) -> str:
        return _validate_academic_year(value)

    @model_validator(mode="after")
    def _sane_policy(self) -> LateFeePolicyCreate:
        """Two rules the CHECK constraints cannot express, both about runaway fines.

        A RECURRING POLICY MUST BE CAPPED. Without a ceiling it keeps fining a family
        who has already stopped being able to pay, and the balance grows past any
        point the school will realistically collect it -- which converts a collection
        tool into a reason the child leaves. Requiring the cap forces whoever writes
        the policy to state where it stops.
        """
        if self.kind is LateFeeKind.PERCENT and self.value > 100:
            raise ValueError("A percentage fine cannot exceed 100% of the outstanding balance.")
        if self.recurrence is not LateFeeRecurrence.ONCE and self.max_amount is None:
            raise ValueError(
                "A recurring late fee needs a maximum, or it keeps charging a family "
                "who has already stopped being able to pay."
            )
        return self


class LateFeePolicyUpdate(BaseSchema):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    head_id: UUID | None = None
    kind: LateFeeKind | None = None
    value: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    grace_days: int | None = Field(default=None, ge=0, le=365)
    recurrence: LateFeeRecurrence | None = None
    max_amount: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=2)
    min_outstanding: Decimal | None = Field(default=None, ge=0, max_digits=12, decimal_places=2)
    is_active: bool | None = None


class LateFeePolicyRead(BaseSchema):
    id: UUID
    academic_year: str
    name: str
    head_id: UUID
    head_name: str
    kind: LateFeeKind
    value: Decimal
    grace_days: int
    recurrence: LateFeeRecurrence
    max_amount: Decimal | None
    min_outstanding: Decimal
    is_active: bool
    created_at: datetime
    updated_at: datetime


class LateFeeRunResult(BaseSchema):
    """What one pass of the fine job did.

    `assessed` and `skipped` are both reported, and `skipped_reasons` groups the
    second, because a run that fined nobody is the normal case on most days and an
    operator needs to tell it apart from a run that was misconfigured and fined
    nobody for the wrong reason.
    """

    academic_year: str
    considered: int
    assessed: int
    total_charged: Decimal
    skipped: int
    skipped_reasons: dict[str, int]
    voucher_ids: list[UUID]
    truncated: bool = Field(
        default=False,
        description=(
            "True when more overdue challans matched than one pass may fine. The "
            "remainder is picked up by the next run, oldest first."
        ),
    )


# ---------------------------------------------------------------------------
# One-off charges -- a fine, a re-exam fee, a broken window
# ---------------------------------------------------------------------------


class VoucherFeeChargeInput(BaseSchema):
    """Put one fee head on ONE student's draft challan, at an amount typed now.

    The fee-side twin of `VoucherStationeryInput`. It exists because the alternative
    an operator otherwise reaches for is adding a "Breakage" line to the CLASS
    structure and removing it next month -- which bills the whole grade for one broken
    window, and is the kind of mistake that is only discovered by a parent.

    Idempotent by head: charging the same head twice SETS the line rather than adding
    a second one. If the head is already on the challan from the class structure, this
    RESTATES that line -- deliberate, because the challan is still a draft being
    assembled and the last word should win, with the audit row carrying both figures.
    """

    head_id: UUID
    amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2, examples=["500.00"])
    note: str | None = Field(
        default=None,
        max_length=255,
        description="Appended to the printed line name, e.g. 'Breakage — lab window'.",
    )


# ---------------------------------------------------------------------------
# The student ledger
# ---------------------------------------------------------------------------


class LedgerEntryRead(BaseSchema):
    id: UUID
    student_id: UUID
    entry_type: LedgerEntryType
    voucher_id: UUID | None
    payment_id: UUID | None
    academic_year: str
    amount: Decimal
    """SIGNED: positive is a debit (the family owes more), negative is a credit."""
    balance_after: Decimal
    occurred_on: date
    description: str
    created_at: datetime


class StudentLedgerStatement(BaseSchema):
    """One family's account: the balance, and the movements that produced it."""

    student_id: UUID
    student_name: str
    admission_number: str
    balance: Decimal
    """Positive means the family owes the school. NEGATIVE MEANS THE SCHOOL HOLDS
    THEIR MONEY -- an advance payment, or a reversal after a refund -- and it is not
    clamped to zero, because clamping would lose money the school is actually
    holding and would have to return."""
    entries: list[LedgerEntryRead]
    total_entries: int


class LedgerAdjustmentInput(BaseSchema):
    """A manual correction to a family's balance.

    GATED ON `fee:void`, not `fee:collect`. It is the one action in this module that
    moves money with no voucher and no receipt behind it, which makes it the one an
    accountant could use to cover a shortfall. The same separation of duties that
    keeps the person recording payments from being the person who can reverse them
    keeps them from being the person who can write a balance off.
    """

    amount: Decimal = Field(
        max_digits=12,
        decimal_places=2,
        description=(
            "Signed. Positive charges the family, negative credits them. Zero is "
            "rejected -- an entry that moves nothing lengthens the statement without "
            "informing it."
        ),
        examples=["-1500.00"],
    )
    academic_year: str = Field(min_length=9, max_length=9, examples=["2026-2027"])
    occurred_on: date | None = Field(
        default=None, description="Defaults to today. Backdate for a correction."
    )
    description: str = Field(
        min_length=1,
        max_length=255,
        description="Required. An unexplained adjustment is the one entry nobody can audit.",
        examples=["Written off — hardship, approved by principal"],
    )

    @field_validator("academic_year")
    @classmethod
    def _check_year(cls, value: str) -> str:
        return _validate_academic_year(value)

    @field_validator("amount")
    @classmethod
    def _non_zero(cls, value: Decimal) -> Decimal:
        if value == 0:
            raise ValueError("An adjustment of zero changes nothing.")
        return value


# ---------------------------------------------------------------------------
# Unattended monthly generation
# ---------------------------------------------------------------------------


class FeeBillingScheduleInput(BaseSchema):
    """When this campus bills its monthly challans without being asked.

    UPSERT BY YEAR, like the structure-item and student-assignment routes: sending it
    twice revises the schedule rather than creating a second one, which is also what
    the partial unique index enforces. Changing the billing day is therefore the same
    call as setting it, and a campus cannot end up with two schedules disagreeing
    about when its parents are billed.
    """

    academic_year: str = Field(min_length=9, max_length=9, examples=["2026-2027"])
    is_active: bool = Field(
        default=True,
        description=(
            "The off switch. Pausing keeps the settings -- an owner who stops "
            "automation for a term wants their billing day back when they resume."
        ),
    )
    generate_day: int = Field(
        default=1,
        ge=1,
        le=28,
        description=(
            "Day of the month the run fires. Capped at 28 rather than clamped from "
            "31: a school that picks 'the 31st' means the month end, but February "
            "would quietly move that to the 28th while the parents' standing bank "
            "instruction did not move with it. The question is answered once, here, "
            "instead of differently every February."
        ),
        examples=[25],
    )
    due_day_offset: int = Field(
        default=10,
        ge=0,
        le=90,
        description=(
            "Days from issue to due date. Relative rather than a second day-of-month "
            "because that is how schools state it ('payable within ten days'), and "
            "because it cannot produce a due date before its own issue date."
        ),
    )
    issue_immediately: bool = Field(
        default=False,
        description=(
            "Issue what the run generates instead of leaving drafts. OFF by default: "
            "an issued challan counts towards outstanding and earns late fees, and a "
            "background job handing out four hundred of those against a mis-typed "
            "structure at 2am is the most expensive mistake this feature can make. A "
            "draft is the same run with the last step left to a human."
        ),
    )
    include_stationery: bool = Field(
        default=False,
        description=(
            "OFF by default, the opposite of the manual dialog. A structure's book "
            "and uniform set is billed once, in the admission month; a schedule fires "
            "twelve times, and inheriting the manual default re-bills the books every "
            "month until a parent notices."
        ),
    )
    carry_forward_dues: bool = Field(
        default=False,
        description=(
            "Bill each family's unpaid earlier challans as a line on the new one, and "
            "cancel the challans that balance came from. Part-paid challans are never "
            "absorbed -- their receipts point at them."
        ),
    )
    carry_forward_head_id: UUID | None = Field(
        default=None,
        description="The head arrears are billed under. Required when carrying dues forward.",
    )

    @field_validator("academic_year")
    @classmethod
    def _check_year(cls, value: str) -> str:
        return _validate_academic_year(value)

    @model_validator(mode="after")
    def _carry_forward_needs_head(self) -> FeeBillingScheduleInput:
        """Checked here as well as by the CHECK constraint, so the error names the
        field and reaches the form that produced it rather than surfacing as an
        opaque integrity error."""
        if self.carry_forward_dues and self.carry_forward_head_id is None:
            raise ValueError("A fee head is required to bill carried-forward dues under.")
        return self


class FeeBillingScheduleRead(BaseSchema):
    id: UUID
    academic_year: str
    is_active: bool
    generate_day: int
    due_day_offset: int
    issue_immediately: bool
    include_stationery: bool
    carry_forward_dues: bool
    carry_forward_head_id: UUID | None
    carry_forward_head_name: str | None = None
    """Resolved so the settings screen can name the head without a second request."""

    last_run_period: str | None
    last_run_at: datetime | None
    last_run_created: int
    last_run_skipped: int
    """The receipt of the last automatic run. A run that created 0 and skipped 400 is
    a WORKING run -- everyone was already billed -- while a run that never happened
    has a null date, and the screen must not show those two the same way."""

    next_run_on: date | None = None
    """The next date this schedule will fire, computed against the campus's own
    calendar. Returned rather than derived in the browser because the answer depends
    on the school's timezone and on which period has already been billed, and a
    screen that computes it from the browser clock tells a school in Karachi it bills
    tomorrow when it has already billed today."""

    created_at: datetime
    updated_at: datetime


class BillingRunResult(BaseSchema):
    """What one unattended pass over a campus did.

    REPORTED PER STRUCTURE-RUN AND IN TOTAL, because "42 challans generated" cannot
    tell an owner whether Grade 9 was among them. `skipped` counts students already
    billed for the period, which is the NORMAL outcome of a re-run and not an error.
    """

    academic_year: str
    period_label: str | None = None
    """Null when nothing was due -- today is not the billing day, or the period has
    already been generated."""
    ran: bool = False
    structures: int = 0
    created: int = 0
    skipped: int = 0
    absorbed_vouchers: int = 0
    absorbed_total: Decimal = Decimal("0.00")
    truncated: bool = False
    """True if any structure held more eligible students than one run may bill. The
    remainder is NOT silently dropped -- it is reported here and picked up by a
    narrower manual run."""
    reason: str | None = None
    """Why nothing ran, in words an owner can act on: no schedule, not the billing
    day, already generated, no active structures."""
