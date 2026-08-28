"""Fees models -- what a school charges its students, and what they paid.

WHY THIS FILE EXISTS
    `docs/modules/fees.md` is the agreed behaviour; this is its schema. The module
    bills students on behalf of the school. It is NOT the SaaS subscription the
    school pays us -- that is `modules/billing`, a different money flow between
    different parties in a different currency. The two never share a table or an
    invoice sequence, and `fee:read` governs one while `invoice:read` governs the
    other.

RESPONSIBILITY
    Eight tables in three layers:

        fee_heads            what may be charged (Tuition, Transport, Exam)
        stationery_items     what may be SOLD (Copy, Pencil, Book) -- priced per unit
          |
        fee_structures       what one class is charged for one academic year
          fee_structure_items    head -> amount, or stationery item -> qty x price
        student_fee_assignments  where ONE student departs from their class
          |
        fee_vouchers         one student's bill for one period (the challan)
          fee_voucher_items      snapshotted line -> amount, discount
          |
        fee_payments         money received against a voucher

    A FEE AND A STATIONERY CHARGE ARE THE SAME KIND OF LINE, PRICED DIFFERENTLY
        Tuition is a flat monthly amount; three copies at 60 each is a quantity times
        a unit price. Both end up as one line on one challan, because a parent
        receives ONE bill at ONE bank counter -- a separate "stationery challan"
        doubles the paper, doubles the reconciliation, and is not how any school in
        this market operates.

        So `fee_structure_items` and `fee_voucher_items` are DISCRIMINATED by
        `line_type`: a FEE line carries `head_id`, a STATIONERY line carries
        `stationery_item_id`, and a CHECK constraint makes any other combination
        unrepresentable rather than merely discouraged.

INTERACTIONS
    * `TenantMixin` (organization_id) -> the RLS key; every table here gets a policy
      via `setup_tenant_table()` in the migration.
    * `RequiredSchoolMixin` (school_id) -> the campus scope filter, applied by
      `BaseRepository`. There is no org-level fee record: fees are always a campus
      concern, so the column is NOT NULL throughout.
    * `fee_structures.class_id` -> `classes.id` (academics).
    * `fee_vouchers.student_id` -> `students.id`.
    * `student_fee_assignments.student_id` -> `students.id`. The class structure is
      the BASE every student inherits; this table records only the departures from
      it, so a student with no rows is billed their class's structure exactly. See
      the model for why a delta beats a per-student fee plan.
    * `stationery_items` -> nothing outside this module. Deliberately: it is a price
      list, not an inventory. Stock levels, purchase orders and suppliers belong to
      an inventory module that does not exist yet, and inventing half of one here
      would put warehouse concerns under Finance's ownership. See §5 below.

=============================================================================
TWO RULES GOVERN EVERY DESIGN CHOICE BELOW
=============================================================================
    1. ISSUED MONEY RECORDS ARE IMMUTABLE. A voucher snapshots the amount AND the
       head's name at generation. Renaming "Tuition" to "Tuition & Lab" next term
       must not silently reword a challan a parent is holding, and repricing a
       structure must not restate what August billed. Corrections are new records
       (a void, a reversal), never edits.

    2. FINANCIAL ROWS ARE NOT DELETED. `fee_vouchers` and `fee_payments` carry no
       `deleted_at` at all -- a voucher is VOIDED and a payment is REVERSED. The
       missing column is the point: it makes the contract visible in the schema
       instead of relying on every future contributor remembering it.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID  # noqa: N811
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, str_enum
from app.db.mixins import (
    CreatedAtMixin,
    RequiredSchoolMixin,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)

if TYPE_CHECKING:  # pragma: no cover - import cycle guard, types only
    from app.modules.academics.models import SchoolClass
    from app.modules.students.models import Student


# ---------------------------------------------------------------------------
# Money precision
# ---------------------------------------------------------------------------
#
# Numeric(12, 2) throughout, matching `billing/models.py`. NEVER float: 0.1 + 0.2 is
# not 0.3 in binary floating point, and a fee ledger that cannot add up its own
# columns is worse than no ledger. 12 digits allows 9,999,999,999.99 in the smallest
# supported currency, which is beyond any plausible single school charge.
_MONEY = Numeric(12, 2)

# Quantities are Numeric too, NOT Integer. A school sells "1 dozen pencils" as one
# unit but also "0.5 dozen", and a reams-of-paper line is routinely half a ream.
# Two decimal places is enough for every unit below and keeps `quantity * unit_price`
# exact in the same arithmetic the money columns use.
_QUANTITY = Numeric(10, 2)


class FeeRecurrence(StrEnum):
    """How often a head is normally charged.

    DESCRIPTIVE, NOT EXECUTABLE. It informs the person assembling a structure; it
    does not drive generation. Real schools fold the annual admission fee into the
    August monthly challan rather than issuing it separately, so the operator picks
    the period at generation time and this stays advisory.
    """

    MONTHLY = "monthly"
    TERM = "term"
    ANNUAL = "annual"
    ONE_TIME = "one_time"


class FeeLineType(StrEnum):
    """What a structure line or a challan line is pricing.

    THE DISCRIMINATOR. A FEE line names a `fee_head` and carries a flat amount; a
    STATIONERY line names a `stationery_item` and carries a quantity times a unit
    price. The CHECK constraints on both item tables are written against this column,
    so a line can never claim to be one kind while pointing at the other.

    Defaulted to FEE everywhere, which is what makes the migration that introduced
    stationery a pure addition: every row that existed before it is a fee line, and
    reads it as one without a backfill.
    """

    FEE = "fee"
    STATIONERY = "stationery"


class StudentFeeAssignmentMode(StrEnum):
    """How one student's bill departs from what their class is charged.

    FOUR WAYS TO DEPART, AND THE ORDER THEY APPLY IN MATTERS. `_effective_lines()`
    resolves them as: OVERRIDE restates a class line, EXCLUDED removes one, ADDED
    appends one, and DISCOUNT reduces whatever the first three settled on. That order
    is the only one that makes "half of what this child actually pays" mean what a
    principal means by it -- a scholarship computed against the class list price
    while the child is on a negotiated rate bills the wrong number, and bills it
    invisibly.
    """

    ADDED = "added"
    """A head this student pays that their class does not -- hostel, transport,
    lunch. Carries its own amount, because the rate is the point: transport is
    priced by route and distance, so two students on the same bus route routinely
    pay different numbers."""

    EXCLUDED = "excluded"
    """A head their class is charged that this student is not -- the child who walks
    to school on a structure that prices transport. Carries no amount: the line is
    not zero, it is absent, and a zero-value "Transport 0.00" line on a challan is a
    question a parent will phone about."""

    OVERRIDE = "override"
    """A head their class is charged, at a rate agreed for this child alone -- the
    legacy family still on last year's tuition, the sibling on a negotiated rate.

    REPLACES the class amount; it does not add a second line. If the class structure
    prices no such head there is nothing to replace and the override contributes
    NOTHING -- it does not quietly become an ADDED line. The two are different facts
    ("Ali pays a different tuition" vs "Ali pays for a bus nobody else does") and
    collapsing them would let a typo in the head picker start billing a service the
    child never took."""

    DISCOUNT = "discount"
    """A concession against a head this student is billed for -- scholarship, staff
    child, sibling remission.

    REDUCES rather than replaces, and the challan shows BOTH numbers: the gross
    amount and what was taken off it. A concession applied by silently lowering the
    amount is indistinguishable on paper from a repricing, and the parent holding the
    challan cannot see they were awarded anything.

    Carries EITHER a `concession_id` (the rate comes from the named policy, so
    raising the staff remission from 40% to 50% is one edit rather than one per
    child -- the same argument that makes the class structure the base), or its own
    `amount`/`percent` for a one-off arrangement no policy covers."""


class ConcessionKind(StrEnum):
    """Whether a named concession is a percentage or a flat sum."""

    PERCENT = "percent"
    """`50.00` means half off. Percent is the common case and the one that survives a
    fee revision: "half tuition" stays half tuition after an 8% rise, where a flat
    remission silently becomes a smaller share of a bigger bill."""

    AMOUNT = "amount"
    """A flat sum off the line, for the remissions that are genuinely fixed -- a
    board-funded stipend of 2,000 a month is 2,000 whatever tuition does."""


class LateFeeKind(StrEnum):
    """How a fine is sized."""

    FIXED = "fixed"
    PERCENT = "percent"
    """A percentage OF THE OUTSTANDING BALANCE, not of the original total. A parent
    who paid four fifths late is fined on the fifth they still owe."""


class LateFeeRecurrence(StrEnum):
    """How often an unpaid challan is fined.

    ONCE is the default and the one most schools actually operate. The recurring
    members exist because some schools do charge per week of delay, and a policy that
    could only fine once would push those schools into doing it by hand -- which is
    how fines end up applied to the families somebody remembered.
    """

    ONCE = "once"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class VoucherOrigin(StrEnum):
    """What produced this challan.

    A FINE IS ITS OWN CHALLAN, NOT AN EXTRA LINE ON THE LATE ONE. Rule 1 of this
    module is that an issued bill is never rewritten, and a fine assessed three weeks
    after issue would rewrite one. So the late-fee job MINTS a challan: its own
    number, its own due date, payable, printable, and voidable through exactly the
    machinery staff already use. `source_voucher_id` is what links it back.
    """

    REGULAR = "regular"
    LATE_FEE = "late_fee"


class LedgerEntryType(StrEnum):
    """What moved a student's running balance.

    DEBIT (positive `amount`) increases what the family owes; CREDIT (negative)
    reduces it. One signed column rather than a debit column and a credit column,
    because every consumer of this table wants the net and a two-column ledger makes
    every one of them write the same CASE expression.
    """

    CHARGE = "charge"
    """A challan was ISSUED. Not when it was generated -- a draft is not a bill, and
    a ledger that counted drafts would show a family owing money nobody has asked
    them for."""

    PAYMENT = "payment"
    PAYMENT_REVERSED = "payment_reversed"
    VOUCHER_VOIDED = "voucher_voided"
    LATE_FEE = "late_fee"
    ADJUSTMENT = "adjustment"
    """A manual correction -- a written-off balance, a goodwill credit, an opening
    balance carried in from the ledger the school kept before this one. Gated on
    `fee:void` rather than `fee:collect`, because it is the one entry that can make
    money disappear without a receipt to justify it."""


class StationeryCategory(StrEnum):
    """How a sellable item is grouped on the shelf and on the challan.

    Coarse ON PURPOSE. A school stocks two hundred distinct SKUs and cares about six
    groupings of them: the finance office reports "books" against "uniform", never
    "HB pencil" against "2B pencil". Anything finer belongs in the item's name, which
    is free text and costs nothing to change.
    """

    BOOK = "book"
    """Textbooks, workbooks, guides -- anything with a syllabus behind it."""

    NOTEBOOK = "notebook"
    """The "copy" every parent asks for by that name: registers, exercise books."""

    STATIONERY = "stationery"
    """Pencils, pens, erasers, sharpeners, geometry boxes."""

    UNIFORM = "uniform"
    SPORTS = "sports"
    OTHER = "other"


class StationeryUnit(StrEnum):
    """What one unit of the price IS.

    Printed on the challan next to the quantity, because "Pencil x 2" is ambiguous
    and expensive: two pencils and two dozen pencils differ by a factor of twelve,
    and the parent finds out at the counter.
    """

    PIECE = "piece"
    DOZEN = "dozen"
    PACK = "pack"
    SET = "set"
    PAIR = "pair"
    REAM = "ream"


class FeeStructureStatus(StrEnum):
    """DRAFT -> ACTIVE -> ARCHIVED.

    DRAFT exists so a structure can be assembled over several sittings without
    becoming billable halfway through. Only ACTIVE structures generate vouchers.
    """

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class VoucherStatus(StrEnum):
    """The challan lifecycle.

    OVERDUE is stored like any other status but is also DERIVED on read: a voucher
    past its due date with an outstanding balance reads as overdue whether or not a
    job has stamped it yet. Slice 1 computes it; a maintenance job that materialises
    it is additive and changes no behaviour.
    """

    DRAFT = "draft"
    ISSUED = "issued"
    PARTLY_PAID = "partly_paid"
    PAID = "paid"
    OVERDUE = "overdue"
    VOID = "void"


class PaymentMethod(StrEnum):
    CASH = "cash"
    BANK_TRANSFER = "bank_transfer"
    CHEQUE = "cheque"
    CARD = "card"
    ONLINE = "online"
    """Present before any gateway is wired. When the provider decision lands, a
    callback records a payment through the same service method staff use -- the
    enum member existing now is what keeps that a one-file change."""
    OTHER = "other"


class FeePaymentStatus(StrEnum):
    RECORDED = "recorded"
    REVERSED = "reversed"


# ---------------------------------------------------------------------------
# 1. Fee heads -- what may be charged
# ---------------------------------------------------------------------------


class FeeHead(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin, SoftDeleteMixin
):
    """One billable line a school charges for, e.g. "Tuition"."""

    __tablename__ = "fee_heads"

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    """Machine-ish code, e.g. "TUITION". Unique per SCHOOL, not per organization or
    globally: a trust running three campuses has three legitimate "TUITION" heads
    with three different amounts, and keying this on `organization_id` would collide
    them the moment the second campus is created."""

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    recurrence: Mapped[FeeRecurrence] = mapped_column(
        str_enum(FeeRecurrence, name="recurrence"),
        nullable=False,
        default=FeeRecurrence.MONTHLY,
    )

    is_refundable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """Security deposits are refundable; tuition is not. Recorded now because it is
    a property of the head that the operator knows at creation time, and asking them
    to remember it years later when a refund module lands is not realistic."""

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """Deactivation, not deletion, is the normal retirement path. An inactive head
    disappears from pickers while every structure that references it keeps working
    -- which is why deleting a referenced head is refused outright (see the service)."""

    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """Controls the order heads appear on a challan. Schools care about this: parents
    read the tuition line first, and a challan that shuffles its lines between months
    generates phone calls."""

    __table_args__ = (
        UniqueConstraint("school_id", "code", name="uq_fee_heads_school_id_code"),
        Index("ix_fee_heads_school_id_is_active", "school_id", "is_active"),
    )


# ---------------------------------------------------------------------------
# 1b. Stationery items -- what may be sold
# ---------------------------------------------------------------------------


class StationeryItem(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin, SoftDeleteMixin
):
    """One sellable article the school charges for by quantity, e.g. "Copy (100 pg)".

    =========================================================================
    WHY THIS IS NOT JUST ANOTHER `FeeHead`
    =========================================================================
        A fee head is a flat amount per period: Tuition is 5,000 whether the student
        attends twenty days or two. Stationery is not -- it is a unit price and a
        count, and the count differs per student in the same class. "Copies: 480"
        as a fee head cannot answer the only question anyone asks about that line,
        which is how many copies at what price. Modelling it as a head would mean
        creating a head per (item, quantity) pair, and a school with 40 articles
        would need 400 heads by December.

        So the catalog is a separate table with `unit_price`, and the QUANTITY lives
        on the line that charges it.

    =========================================================================
    A PRICE LIST, NOT AN INVENTORY -- and the omission is deliberate
    =========================================================================
        There is no `stock_on_hand`, no reorder level, no supplier, no goods-received
        note. Those are an inventory module's job, and a half-inventory that
        decrements a counter without a receiving path, a stocktake or a wastage
        record is worse than none: it produces a number the store keeper knows is
        wrong and the finance office believes.

        What this table DOES own is the price, because the price is what lands on a
        challan. When inventory arrives it links to this table by id and adds its own
        columns to its own table; nothing here changes.
    """

    __tablename__ = "stationery_items"

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    """Machine-ish code, e.g. "COPY-100". Unique per SCHOOL for the same reason
    `fee_heads.code` is: two campuses of one trust sell their own copies at their
    own prices, and keying this on `organization_id` would collide them."""

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    """What the parent reads on the challan -- "Copy (Register, 100 pages)". Free
    text and generous, because the distinction between two articles a school stocks
    lives here and nowhere else."""

    description: Mapped[str | None] = mapped_column(Text)

    category: Mapped[StationeryCategory] = mapped_column(
        str_enum(StationeryCategory, name="stationery_category"),
        nullable=False,
        default=StationeryCategory.STATIONERY,
    )

    unit: Mapped[StationeryUnit] = mapped_column(
        str_enum(StationeryUnit, name="stationery_unit"),
        nullable=False,
        default=StationeryUnit.PIECE,
    )

    unit_price: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=0)
    """The CURRENT price of one unit. Repricing this changes what future lines cost
    and changes NOTHING that has already been charged: every line that references
    this item snapshots the price it was sold at. See `FeeVoucherItem.unit_price`."""

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """Deactivation, not deletion, is how an article is retired -- same contract as
    `FeeHead.is_active`, and for the same reason: an inactive item leaves the pickers
    while every challan that ever sold it keeps rendering."""

    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("school_id", "code", name="uq_stationery_items_school_id_code"),
        Index("ix_stationery_items_school_id_is_active", "school_id", "is_active"),
        # Serves the picker, which is grouped by category and is the only screen that
        # reads this table in bulk.
        Index("ix_stationery_items_school_id_category", "school_id", "category"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
    )


# ---------------------------------------------------------------------------
# 2. Fee structures -- what one class is charged for one academic year
# ---------------------------------------------------------------------------


class FeeStructure(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin, SoftDeleteMixin
):
    """The fee schedule for one class in one academic year."""

    __tablename__ = "fee_structures"

    class_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("classes.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    academic_year: Mapped[str] = mapped_column(String(9), nullable=False)
    """"2026-2027". A validated string, NOT a foreign key -- deliberately.

    An academic session is an ACADEMICS concept: terms, holidays, promotion and
    result cards all key off it. Inventing that entity inside the fees module would
    put the calendar governing the whole school under Finance's ownership. Fees needs
    exactly one thing from it -- a stable label to group a year's billing under.

    When academics introduces the real entity the migration is mechanical: add a
    nullable `academic_session_id`, backfill by matching the label, drop the string.
    No behaviour in this module changes. See docs/modules/fees.md §7.
    """

    name: Mapped[str] = mapped_column(String(120), nullable=False)

    status: Mapped[FeeStructureStatus] = mapped_column(
        str_enum(FeeStructureStatus, name="status"),
        nullable=False,
        default=FeeStructureStatus.DRAFT,
    )

    school_class: Mapped[SchoolClass] = relationship()
    items: Mapped[list[FeeStructureItem]] = relationship(
        back_populates="structure",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="FeeStructureItem.created_at",
    )

    __table_args__ = (
        # One structure per class per year. Changing next year's fees means a NEW
        # structure, not an edit -- which is what keeps "what did Grade 10 pay in
        # 2026-2027?" answerable forever.
        UniqueConstraint(
            "school_id",
            "class_id",
            "academic_year",
            name="uq_fee_structures_school_id_class_id_academic_year",
        ),
        Index("ix_fee_structures_school_id_status", "school_id", "status"),
    )


class FeeStructureItem(Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin):
    """One priced line within a structure -- a fee head, or a stationery article.

    DISCRIMINATED BY `line_type`. A FEE line names a head and prices it flat; a
    STATIONERY line names a catalog article, a quantity and the unit price AT THE
    TIME IT WAS ADDED. `amount` is `quantity * unit_price` on both, so every total in
    the module sums one column and never has to know which kind of line it is
    looking at.

    WHY A STATIONERY LINE FREEZES ITS UNIT PRICE HERE
        A structure is a PRICE LIST -- "this is what Grade 10 is charged in
        2026-2027". Reading the catalog's live price at generation time instead would
        mean a January reprice silently changed what the structure says it charges,
        so the number an operator approved in August is not the number that bills in
        January. Freezing it keeps the structure a statement of fact; picking up a
        new price is an explicit act (re-add the line), exactly as repricing a fee
        head's amount already is.
    """

    __tablename__ = "fee_structure_items"

    structure_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("fee_structures.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    line_type: Mapped[FeeLineType] = mapped_column(
        str_enum(FeeLineType, name="line_type"),
        nullable=False,
        default=FeeLineType.FEE,
    )

    head_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # RESTRICT, not CASCADE: silently dropping a priced line because someone
        # tidied up the head list would change what a class is billed without anyone
        # deciding to. The service refuses the delete and names the count instead.
        ForeignKey("fee_heads.id", ondelete="RESTRICT"),
        index=True,
    )
    """NULL on a stationery line. Nullable since the stationery migration -- the
    `line_type_matches_reference` CHECK below is what keeps it NOT NULL in practice
    for every fee line, which is the only place it was ever meaningful."""

    stationery_item_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # RESTRICT for the same reason as `head_id`: tidying the catalog must not
        # change what a class is charged.
        ForeignKey("stationery_items.id", ondelete="RESTRICT"),
        index=True,
    )

    quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False, default=1)
    """How many units. Always exactly 1 on a fee line -- Tuition is not sold by the
    dozen -- which is what lets `amount = quantity * unit_price` hold for both kinds
    and keeps the arithmetic in one place."""

    unit_price: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=0)
    """Price of one unit. Equals `amount` on a fee line, by the same identity."""

    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    """`quantity * unit_price`, stored rather than derived.

    Stored because every total in this module -- the structure editor's footer, the
    voucher subtotal, the collection dashboard -- sums this one column across lines
    of both kinds. A generated column would be equivalent and is not used only
    because the service already owns the rounding decision and must agree with it."""

    structure: Mapped[FeeStructure] = relationship(back_populates="items")
    head: Mapped[FeeHead | None] = relationship()
    stationery_item: Mapped[StationeryItem | None] = relationship()

    __table_args__ = (
        # A head appears at most once per structure, so "Tuition 5000 and also
        # Tuition 3000" is unrepresentable rather than merely discouraged.
        #
        # NOTE: both of these are PARTIAL unique indexes created by hand in the
        # migration, because the columns are now nullable and `UniqueConstraint`
        # cannot express the `WHERE ... IS NOT NULL` that stops every stationery line
        # (head_id NULL) from colliding with every other one:
        #   UNIQUE (structure_id, head_id)             WHERE head_id IS NOT NULL
        #   UNIQUE (structure_id, stationery_item_id)  WHERE stationery_item_id IS NOT NULL
        CheckConstraint("amount >= 0", name="amount_non_negative"),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        # The discriminator, enforced rather than trusted. Exactly one reference is
        # set, and it is the one `line_type` claims.
        CheckConstraint(
            "(line_type = 'fee' AND head_id IS NOT NULL AND stationery_item_id IS NULL)"
            " OR (line_type = 'stationery'"
            " AND stationery_item_id IS NOT NULL AND head_id IS NULL)",
            name="line_type_matches_reference",
        ),
    )


# ---------------------------------------------------------------------------
# 2b0. Fee concessions -- the named scholarship a family is put ON
# ---------------------------------------------------------------------------


class FeeConcession(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin, SoftDeleteMixin
):
    """A named remission a student can be placed on: Staff Child, Merit, Sibling.

    =========================================================================
    WHY THE RATE LIVES HERE AND NOT ON EACH CHILD
    =========================================================================
        The same argument that makes the class structure the base for billing makes
        a policy the base for concessions. A school does not award four hundred
        unrelated discounts -- it operates five or six schemes and puts families on
        them. Recording the rate per child instead means:

          * "Staff remission goes from 40% to 50%" is four hundred edits, and the
            ones missed are invisible, because there is no scheme left to compare a
            child against.

          * "How many children are on merit scholarship, and what does it cost us
            this year?" has no answer. That is a governing-body question, asked every
            year, and a pile of ad-hoc percentages cannot answer it.

        So a `student_fee_assignments` row in DISCOUNT mode points here, and the
        number comes from the scheme. Ad-hoc remissions remain possible -- the same
        row can carry its own rate and no `concession_id` -- because the genuinely
        one-off case (a family in crisis, agreed by the principal in March) is real
        and should not have to become a permanent scheme to be recorded.

    NOT A DISCOUNT ON THE SAAS BILL. This reduces what a PARENT owes the school.
    What the school owes EduCloud is `billing`, and the two never meet.
    """

    __tablename__ = "fee_concessions"

    code: Mapped[str] = mapped_column(String(40), nullable=False)
    """`STAFF`, `MERIT`, `SIBLING`. Unique per school, like a fee head's code: two
    campuses run their own schemes at their own rates."""

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)

    kind: Mapped[ConcessionKind] = mapped_column(
        str_enum(ConcessionKind, name="kind"),
        nullable=False,
        default=ConcessionKind.PERCENT,
    )
    value: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    """Read against `kind`: a percentage when PERCENT (0-100, enforced by CHECK), a
    flat sum when AMOUNT. One column rather than two nullable ones, because a scheme
    is exactly one of the two and a row carrying both is a row whose halves
    disagree."""

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """Retiring a scheme stops it being offered without disturbing the children
    already on it -- their assignment rows keep resolving against it, which is what
    keeps last year's challans explicable."""

    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        UniqueConstraint("school_id", "code", name="uq_fee_concessions_school_id_code"),
        CheckConstraint(
            "(kind = 'percent' AND value > 0 AND value <= 100) OR (kind = 'amount' AND value > 0)",
            name="value_matches_kind",
        ),
    )


# ---------------------------------------------------------------------------
# 2b. Student fee assignments -- where one student departs from their class
# ---------------------------------------------------------------------------


class StudentFeeAssignment(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin, SoftDeleteMixin
):
    """One difference between what a student is billed and what their class is.

    =========================================================================
    WHY THIS IS A DELTA AND NOT A PER-STUDENT FEE PLAN
    =========================================================================
        Every student's bill really is their own -- one takes the bus, one boards,
        one walks. The tempting conclusion is that each student should carry a
        complete list of heads and amounts. That was rejected, and the reason is
        what happens on the days nobody designs for:

          * A NEW ADMISSION arrives mid-term. With a delta model they are billed
            correctly the moment they are placed in a section, because the class
            structure already says what Grade 10 pays. With per-student plans
            someone must type six lines before that child can be billed at all, and
            the day they forget, the child is billed nothing and nobody notices
            until the year-end reconciliation.

          * TUITION GOES UP 8%. One edit to the structure, and every student who
            pays the standard rate follows. Per-student plans mean five hundred
            edits, and the ones that get missed are invisible -- there is no
            "standard" left to compare them against.

          * "WHAT DOES GRADE 10 PAY?" stays answerable, because there is still a
            fact to answer it with.

        So the class structure remains the base and this table records only the
        DEPARTURES from it. A student with no rows here is billed exactly their
        class's structure, which is the overwhelmingly common case and costs nothing
        to express.

    =========================================================================
    KEYED ON THE STUDENT AND THE YEAR, NOT ON THE STRUCTURE
    =========================================================================
        "Ali takes the bus in 2026-2027" is a fact about Ali and that year. It
        survives him being moved from section A to section B, or promoted into a
        different class mid-year -- both of which change which structure bills him,
        and neither of which should silently take him off the bus.

        It does NOT survive into the next academic year, and that is deliberate: bus
        routes, hostel places and lunch plans are renewed annually, and an assignment
        that rolled over forever would keep billing a student for a service they
        stopped using the summer they left it.
    """

    __tablename__ = "student_fee_assignments"

    student_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # CASCADE, unlike `fee_vouchers.student_id` which is RESTRICT. The difference
        # is the point: a voucher is a financial record and must outlive any deletion
        # path, while this row is configuration. If a student row is ever truly
        # destroyed, "Ali takes the bus" is meaningless and should go with it.
        ForeignKey("students.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    head_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # RESTRICT, matching `fee_structure_items.head_id`. Tidying the head list must
        # not silently stop billing a student for their hostel place.
        ForeignKey("fee_heads.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    academic_year: Mapped[str] = mapped_column(String(9), nullable=False)
    """`2026-2027`. Same validated string as `fee_structures.academic_year`, and it
    migrates to a real `academic_session_id` at the same time and in the same way."""

    mode: Mapped[StudentFeeAssignmentMode] = mapped_column(
        str_enum(StudentFeeAssignmentMode, name="mode"),
        nullable=False,
    )

    amount: Mapped[Decimal | None] = mapped_column(_MONEY)
    """The flat sum this row carries, read against `mode`: what the student pays
    (ADDED), what they pay instead of the class rate (OVERRIDE), or what is taken off
    the line (DISCOUNT, when the remission is a fixed sum). NULL on EXCLUDED, where
    the line is ABSENT rather than zero -- enforced by the CHECK below rather than by
    convention, because a row whose two halves disagree about what it means is worse
    than a row that is missing."""

    percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    """A DISCOUNT expressed as a share of the line rather than a sum: `50.00` is half
    off. Only meaningful on DISCOUNT, and only when no `concession_id` supplies the
    rate. Numeric(5, 2) reaches 999.99, and the CHECK holds it to 100."""

    concession_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # RESTRICT: deleting a scheme children are still on would silently restore
        # them to full fees, and nobody would find out until the challans printed.
        ForeignKey("fee_concessions.id", ondelete="RESTRICT"),
        index=True,
    )
    """The named scheme this remission comes from. When set, the rate is READ FROM
    THE SCHEME at generation and this row carries neither `amount` nor `percent` --
    so raising the staff remission is one edit, not one per child."""

    note: Mapped[str | None] = mapped_column(String(500))
    """Free text: "Route 4 -- Gulberg", "Boards from Jan". The reason a student is on
    a different bill is asked about far more often than it is recorded, and a
    structured field for it would be wrong within a term."""

    student: Mapped[Student] = relationship()
    head: Mapped[FeeHead] = relationship()
    concession: Mapped[FeeConcession | None] = relationship()

    __table_args__ = (
        # One assignment per head per student per year. A student cannot be both
        # charged and not charged for transport, and cannot be added twice at two
        # rates -- both are unrepresentable rather than merely discouraged.
        UniqueConstraint(
            "student_id",
            "academic_year",
            "head_id",
            name="uq_student_fee_assignments_student_year_head",
        ),
        # THE INDEX GENERATION READS. A run fetches the assignments for up to 500
        # students in one query keyed on exactly these two columns; without it that
        # query is a sequential scan of every assignment in the school on every
        # billing run.
        Index(
            "ix_student_fee_assignments_school_id_academic_year",
            "school_id",
            "academic_year",
        ),
        # ONE CHECK PER MODE, spelling out which of the three value columns each may
        # carry. Written as an exhaustive OR rather than a set of narrower
        # constraints so that a mode added later fails LOUDLY at insert instead of
        # falling through every branch and being stored with no value at all.
        CheckConstraint(
            "(mode = 'added' AND amount IS NOT NULL AND amount >= 0"
            " AND percent IS NULL AND concession_id IS NULL)"
            " OR (mode = 'excluded' AND amount IS NULL"
            " AND percent IS NULL AND concession_id IS NULL)"
            " OR (mode = 'override' AND amount IS NOT NULL AND amount >= 0"
            " AND percent IS NULL AND concession_id IS NULL)"
            " OR (mode = 'discount' AND ("
            "   (concession_id IS NOT NULL AND amount IS NULL AND percent IS NULL)"
            "   OR (concession_id IS NULL AND amount IS NOT NULL AND amount >= 0"
            "       AND percent IS NULL)"
            "   OR (concession_id IS NULL AND percent IS NOT NULL"
            "       AND percent > 0 AND percent <= 100 AND amount IS NULL)"
            " ))",
            name="amount_matches_mode",
        ),
    )


# ---------------------------------------------------------------------------
# 3. Vouchers -- one student's bill for one period (the challan)
# ---------------------------------------------------------------------------


class FeeVoucher(Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin):
    """One student's challan for one billing period.

    NO SoftDeleteMixin, and that is deliberate -- see the module docstring. A voucher
    is VOIDED, never deleted.
    """

    __tablename__ = "fee_vouchers"

    student_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # RESTRICT: a student row is soft-deleted by the students module, so this
        # never fires in normal operation. It exists so that a future hard-delete
        # path cannot quietly destroy a financial record as a side effect.
        ForeignKey("students.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    structure_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # SET NULL: the voucher already snapshotted everything it needs. Losing the
        # link to the structure it came from must not take the bill with it.
        ForeignKey("fee_structures.id", ondelete="SET NULL"),
        index=True,
    )

    origin: Mapped[VoucherOrigin] = mapped_column(
        str_enum(VoucherOrigin, name="origin"),
        nullable=False,
        default=VoucherOrigin.REGULAR,
    )
    """REGULAR unless the late-fee job minted this challan. Defaulted, which is what
    makes the migration that introduced fines a pure addition: every voucher that
    existed before it is a regular challan and reads as one with no backfill."""

    source_voucher_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # RESTRICT, and there is no cascade anywhere near this: a fine and the challan
        # it punishes are both financial records, and destroying one must not take the
        # other. Voiding is how either is undone.
        ForeignKey("fee_vouchers.id", ondelete="RESTRICT"),
        index=True,
    )
    """The overdue challan this fine was assessed against. NULL on a regular challan.

    It is what makes the fine explicable six months later ("what is this 200 for?")
    and what lets the job recognise its own previous work -- a policy that fines
    weekly must count what it already charged rather than fine the same delay twice.
    """

    arrears_brought_forward: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=0)
    """The family's balance at the moment this challan was generated, SNAPSHOTTED, and
    NOT included in `total`.

    Printed so a parent sees what they owe overall while the challan bills only its
    own period. It must never be added to `total`, because the older challan carrying
    that balance is still outstanding: the same rupee would be billed twice and the
    school would discover it at the counter with the parent holding both papers.

    CONSOLIDATION IS THE OTHER ANSWER TO THE SAME PROBLEM, and it works by making
    that sentence false rather than by ignoring it -- see `superseded_by_voucher_id`.
    A consolidating run bills the old balance as a REAL line and cancels the challans
    it came from, so exactly one document is payable. What stays here is then only
    what was NOT absorbed: the remainder on partly-paid challans, which keep their
    own life because their receipts point at them.
    """

    carry_forward_head_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("fee_heads.id", ondelete="RESTRICT"),
    )
    """The head this challan's carried-dues line was billed under, when it has one.

    Stored on the voucher rather than inferred from the lines because the line has to
    be found again EXACTLY, once: if a challan the draft reserved takes a payment
    before the draft is issued, that reservation is released and this line must shrink
    to match. Identifying it by sort order or by name would eventually pick a
    different line and reprice the wrong charge, on money.
    """

    superseded_by_voucher_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # RESTRICT, not CASCADE. A voucher is never deleted (it is voided), so this
        # never fires -- and if a future hard-delete path appears, losing the row that
        # explains why an older challan was cancelled is not an acceptable side
        # effect of removing the newer one.
        ForeignKey("fee_vouchers.id", ondelete="RESTRICT"),
        index=True,
    )
    """Set on an OLD challan, pointing at the NEW one that absorbed its dues.

    =========================================================================
    A RESERVATION FIRST, A CANCELLATION ONLY AT ISSUE
    =========================================================================
        Written when the consolidating challan is GENERATED, while that challan may
        still be a draft. Nothing moves at that moment: the old challan keeps its
        status, stays payable, and stays on the family's balance. A draft is not a
        bill, so cancelling a real one against it would tell the school a family owes
        nothing while the only document covering that money is still unissued.

        The cancellation happens when the new challan is ISSUED. Every voucher
        pointing at it is voided then, in the same breath as the new charge is
        recorded, so the balance never passes through a wrong intermediate value.

    WHY THE POINTER ALSO ACTS AS A LOCK
        A challan already carrying this pointer is not offered to the next run. Two
        consolidations absorbing the same arrears would each bill it, which is the
        exact double-billing the design exists to prevent -- reached by a different
        road.

    IF THE OLD CHALLAN TAKES A PAYMENT while the new one is still a draft, the
    reservation is RELEASED at issue time and the arrears line shrinks accordingly.
    The alternative -- voiding a challan money was received against -- is refused by
    `void_voucher` for good reason, and billing for it anyway would charge a family
    twice for a payment they had already made.
    """

    voucher_number: Mapped[str] = mapped_column(String(40), nullable=False)
    """`FV-<year>-<5 digits>`, unique per school. Per school rather than global
    (unlike SaaS invoice numbers) because a challan is quoted at the school's own
    bank counter, where nobody carries the organization id alongside it."""

    academic_year: Mapped[str] = mapped_column(String(9), nullable=False)
    period_label: Mapped[str] = mapped_column(String(40), nullable=False)
    """"2026-08", "Term 1", "Annual". Free text, not an enum: monthly, termly and
    annual schools all exist, and a fixed enum would exclude one of them."""

    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    """`Date`, not `DateTime`: a due date is a calendar day. Storing it with a
    timezone makes it shift by a day depending on where it is read, which turns into
    a late fee charged to a parent who paid on time."""

    status: Mapped[VoucherStatus] = mapped_column(
        str_enum(VoucherStatus, name="status"),
        nullable=False,
        default=VoucherStatus.DRAFT,
    )

    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="PKR")

    subtotal: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=0)
    discount_total: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=0)
    total: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=0)
    paid_total: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=0)
    """Materialised rather than summed from `fee_payments` on every read.

    The challan list is the hottest screen in the module and shows an outstanding
    balance per row; deriving it would mean a correlated subquery per voucher. The
    cost is that exactly one place -- `FeeService._recalculate` -- may write it, and
    every payment path routes through there."""

    notes: Mapped[str | None] = mapped_column(Text)

    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    void_reason: Mapped[str | None] = mapped_column(String(500))

    student: Mapped[Student] = relationship()
    items: Mapped[list[FeeVoucherItem]] = relationship(
        back_populates="voucher",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="FeeVoucherItem.sort_order",
    )
    payments: Mapped[list[FeePayment]] = relationship(
        back_populates="voucher",
        order_by="FeePayment.created_at",
    )

    __table_args__ = (
        UniqueConstraint(
            "school_id", "voucher_number", name="uq_fee_vouchers_school_id_voucher_number"
        ),
        # The duplicate-billing guard is a PARTIAL unique index and cannot be
        # expressed as a UniqueConstraint, so it is created by hand in the migration:
        #   UNIQUE (school_id, student_id, academic_year, period_label)
        #   WHERE status <> 'void'
        # Partial so that voiding a challan frees the period for a corrected reissue.
        Index("ix_fee_vouchers_school_id_status", "school_id", "status"),
        Index("ix_fee_vouchers_school_id_student_id", "school_id", "student_id"),
        # Serves the overdue sweep and the collection dashboard, both of which filter
        # on due date within a school.
        Index("ix_fee_vouchers_school_id_due_date", "school_id", "due_date"),
        CheckConstraint(
            "subtotal >= 0 AND discount_total >= 0 AND total >= 0 AND paid_total >= 0",
            name="amounts_non_negative",
        ),
        CheckConstraint("due_date >= issue_date", name="due_after_issue"),
    )

    @property
    def outstanding(self) -> Decimal:
        """What is still owed. Never negative -- overpayment is rejected at the door."""
        return self.total - self.paid_total

    @property
    def is_open(self) -> bool:
        """Whether this voucher can still receive money."""
        return self.status in {
            VoucherStatus.ISSUED,
            VoucherStatus.PARTLY_PAID,
            VoucherStatus.OVERDUE,
        }


class FeeVoucherItem(Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin):
    """One snapshotted line on a challan.

    `TimestampMixin` since stationery landed, and the change is a real one. These
    rows used to be written once at generation and never touched, so `CreatedAtMixin`
    was the honest mixin. Now a DRAFT voucher can gain, adjust and lose stationery
    lines -- "Ali also took two more copies in October" -- before it is issued.

    THE IMMUTABILITY RULE IS UNCHANGED, ONLY STATED MORE PRECISELY
        It was never "a voucher line is never written twice"; it was "a bill a parent
        is holding is never rewritten". A draft is not in anyone's hands: it bills
        nothing, collects nothing and is explicitly described as unfinished on both
        the API and the screen. The service refuses every line mutation the moment
        the voucher leaves DRAFT, which is the point at which the document becomes
        real. `updated_at` records the assembly; it can never record an edit to an
        issued challan, because there is no code path that produces one.
    """

    __tablename__ = "fee_voucher_items"

    voucher_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("fee_vouchers.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    line_type: Mapped[FeeLineType] = mapped_column(
        str_enum(FeeLineType, name="line_type"),
        nullable=False,
        default=FeeLineType.FEE,
    )

    head_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("fee_heads.id", ondelete="RESTRICT"),
        index=True,
    )
    stationery_item_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("stationery_items.id", ondelete="RESTRICT"),
        index=True,
    )

    line_name: Mapped[str] = mapped_column(String(120), nullable=False)
    """THE SNAPSHOT. `head_id` / `stationery_item_id` still point at the live record
    for reporting, but the text printed on this challan is frozen here. Renaming
    "Tuition" to "Tuition & Lab" -- or "Copy" to "Register (100 pg)" -- next term
    must not reword a challan a parent already holds."""

    unit_label: Mapped[str | None] = mapped_column(String(16))
    """Snapshotted `StationeryUnit` value on a stationery line, NULL on a fee line.

    Frozen alongside the name for the same reason and a sharper one: if a school
    switches an article from selling by the piece to selling by the dozen, an old
    challan reading "Pencil x 12" must keep meaning twelve pencils, not twelve dozen.
    Stored as text rather than the enum type so a future unit the enum does not yet
    have cannot invalidate a challan already in a parent's hands."""

    quantity: Mapped[Decimal] = mapped_column(_QUANTITY, nullable=False, default=1)
    unit_price: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=0)
    """Both snapshotted. Repricing the catalog reprices the NEXT challan and never
    this one -- the same contract `amount` has always had, extended to the two
    numbers that now justify it."""

    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    """`quantity * unit_price`. The line total, and the only column the voucher's
    subtotal sums -- so it never has to know which kind of line it is adding."""

    discount_amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=0)
    """Zero for every voucher in slice 1. The column exists now so that the deferred
    scholarship/concession policy sets this number instead of forcing a voucher
    schema change -- see docs/modules/fees.md §2."""

    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """Copied from the head at generation, so a challan's line order stays stable
    even after someone reorders the head list."""

    voucher: Mapped[FeeVoucher] = relationship(back_populates="items")

    __table_args__ = (
        # As on `fee_structure_items`, the two uniqueness rules are PARTIAL indexes
        # created by hand in the migration -- `UniqueConstraint` cannot express the
        # `WHERE ... IS NOT NULL` these need now that both columns are nullable:
        #   UNIQUE (voucher_id, head_id)             WHERE head_id IS NOT NULL
        #   UNIQUE (voucher_id, stationery_item_id)  WHERE stationery_item_id IS NOT NULL
        #
        # The second is what makes "add 2 more copies" an UPDATE of the existing line
        # rather than a second line reading "Copy x 2" beneath "Copy x 3".
        CheckConstraint(
            "amount >= 0 AND discount_amount >= 0 AND discount_amount <= amount",
            name="amounts_valid",
        ),
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_non_negative"),
        CheckConstraint(
            "(line_type = 'fee' AND head_id IS NOT NULL AND stationery_item_id IS NULL)"
            " OR (line_type = 'stationery'"
            " AND stationery_item_id IS NOT NULL AND head_id IS NULL)",
            name="line_type_matches_reference",
        ),
    )


# ---------------------------------------------------------------------------
# 4. Payments -- money received against a voucher
# ---------------------------------------------------------------------------


class FeePayment(Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin):
    """One receipt. Reversed, never deleted.

    `TimestampMixin` rather than `CreatedAtMixin` (which the append-only billing
    `Payment` uses) precisely because reversal mutates the row, and `updated_at` is
    then a real fact worth recording rather than a duplicate of `created_at`.
    """

    __tablename__ = "fee_payments"

    voucher_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("fee_vouchers.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    receipt_number: Mapped[str] = mapped_column(String(40), nullable=False)
    """`RC-<year>-<5 digits>`, unique per school. This is the number a parent quotes
    when they say they already paid, so it must be stable and never reused."""

    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="PKR")

    method: Mapped[PaymentMethod] = mapped_column(
        str_enum(PaymentMethod, name="method"),
        nullable=False,
        default=PaymentMethod.CASH,
    )
    reference: Mapped[str | None] = mapped_column(String(120))
    """Cheque number, bank transaction id, or gateway reference."""

    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    """When the money arrived, which is NOT when the row was created. A clerk
    entering Friday's cash on Monday must be able to date it Friday, or every
    month-end reconciliation disagrees with the bank by a weekend."""

    received_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    """Who took the money -- recorded separately from `audit_logs.actor_user_id`,
    which records who typed it in. Cash handed to one clerk is routinely entered by
    another, and the school needs both names to investigate a shortfall."""

    status: Mapped[FeePaymentStatus] = mapped_column(
        str_enum(FeePaymentStatus, name="status"),
        nullable=False,
        default=FeePaymentStatus.RECORDED,
    )
    notes: Mapped[str | None] = mapped_column(Text)

    reversed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reversal_reason: Mapped[str | None] = mapped_column(String(500))

    voucher: Mapped[FeeVoucher] = relationship(back_populates="payments")

    __table_args__ = (
        UniqueConstraint(
            "school_id", "receipt_number", name="uq_fee_payments_school_id_receipt_number"
        ),
        Index("ix_fee_payments_school_id_received_on", "school_id", "received_on"),
        Index("ix_fee_payments_school_id_status", "school_id", "status"),
        # Strictly positive: a zero-value receipt is a data-entry accident, and a
        # negative one is a refund pretending to be a payment. Refunds get their own
        # record when the refund module lands.
        CheckConstraint("amount > 0", name="amount_positive"),
    )

    @property
    def is_effective(self) -> bool:
        """Whether this payment still counts toward its voucher's balance."""
        return self.status is FeePaymentStatus.RECORDED


# ---------------------------------------------------------------------------
# 5. Late fee policy -- the rule the fine job applies
# ---------------------------------------------------------------------------


class LateFeePolicy(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin, SoftDeleteMixin
):
    """When an unpaid challan earns a fine, and how big it is.

    =========================================================================
    A POLICY, BECAUSE THE ALTERNATIVE IS FINING THE FAMILIES SOMEBODY REMEMBERED
    =========================================================================
        Fines applied by hand are applied unevenly, and unevenly always means the
        same thing in practice: the families who complain are let off and the ones
        who do not are charged. That is the single most complained-about behaviour in
        school fee collection, and it is a process failure rather than a moral one --
        nobody can apply a rule consistently across four hundred challans by hand
        every month.

        So the rule is a row, the job applies it to everyone it matches, and the
        exceptions are visible: a fine is a challan, and letting a family off is
        voiding it, with a reason, audited.

    ONE ACTIVE POLICY PER SCHOOL PER YEAR, enforced by a partial unique index in the
    migration. Two live policies would mean the fine a parent owes depends on which
    row the job read first.
    """

    __tablename__ = "fee_late_fee_policies"

    academic_year: Mapped[str] = mapped_column(String(9), nullable=False)
    """Scoped to the year like everything else in this module: a school revises its
    fine rule between sessions, and last year's challans must stay explicable under
    the rule that produced them."""

    name: Mapped[str] = mapped_column(String(120), nullable=False)

    head_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # RESTRICT: deleting the head a year of fines was billed under would orphan
        # the reason those challans exist.
        ForeignKey("fee_heads.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    """The head the fine is billed under -- "Late Fee", "Fine". Named rather than
    hardcoded because it has to appear in the collection summary beside tuition and
    transport, and a fine that is not a head is a number with no home in any report
    the finance office already runs."""

    kind: Mapped[LateFeeKind] = mapped_column(
        str_enum(LateFeeKind, name="kind"),
        nullable=False,
        default=LateFeeKind.FIXED,
    )
    value: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    """A flat sum when FIXED, a percentage of the OUTSTANDING balance when PERCENT."""

    grace_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """Days after the due date before anything is charged. Schools run a grace period
    because banks do: a parent who paid on the due date at a branch that posted it
    the next morning has not been late, and fining them costs more in counter
    argument than the fine collects."""

    recurrence: Mapped[LateFeeRecurrence] = mapped_column(
        str_enum(LateFeeRecurrence, name="recurrence"),
        nullable=False,
        default=LateFeeRecurrence.ONCE,
    )

    max_amount: Mapped[Decimal | None] = mapped_column(_MONEY)
    """A ceiling on the TOTAL fined against one challan. NULL means uncapped, which
    is only safe on ONCE -- a recurring policy with no cap keeps fining a family who
    has already stopped being able to pay, and the balance grows past any point the
    school will actually collect it."""

    min_outstanding: Mapped[Decimal] = mapped_column(_MONEY, nullable=False, default=0)
    """Do not fine a balance below this. A challan eleven rupees short because a
    parent rounded is not a late payment worth a fine, a challan, and a phone call."""

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    head: Mapped[FeeHead] = relationship()

    __table_args__ = (
        Index(
            "ix_fee_late_fee_policies_school_id_academic_year",
            "school_id",
            "academic_year",
        ),
        CheckConstraint("value > 0", name="value_positive"),
        CheckConstraint("grace_days >= 0 AND grace_days <= 365", name="grace_days_sane"),
        CheckConstraint("max_amount IS NULL OR max_amount > 0", name="max_amount_positive"),
        CheckConstraint("min_outstanding >= 0", name="min_outstanding_non_negative"),
        CheckConstraint(
            "kind <> 'percent' OR (value > 0 AND value <= 100)",
            name="percent_within_range",
        ),
    )


# ---------------------------------------------------------------------------
# 6. Student ledger -- the running account, materialised
# ---------------------------------------------------------------------------


class StudentLedgerEntry(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, CreatedAtMixin
):
    """One movement in a family's running balance. Append-only.

    =========================================================================
    WHY MATERIALISE A NUMBER THAT CAN BE COMPUTED
    =========================================================================
        "What does this family owe?" is answerable today by summing the unpaid
        vouchers, and that answer is correct. It is also recomputed on every request,
        it cannot be indexed, and it cannot answer the question a parent actually
        asks at the counter -- "how did it get to that number?"

        This table answers both. The balance is one row read, and the movements that
        produced it are the rows above it, in order, each pointing at the voucher or
        receipt that justifies it. That is a STATEMENT, which is what a family
        disputing a balance needs and what an aggregate query can never produce.

    =========================================================================
    APPEND-ONLY, AND NOT MERELY BY CONVENTION
    =========================================================================
        `CreatedAtMixin` rather than `TimestampMixin`, and no `deleted_at`: there is
        no supported path that updates or removes a row here. A correction is a NEW
        entry -- an ADJUSTMENT, or the PAYMENT_REVERSED that answers a PAYMENT. The
        missing columns are the contract, visible in the schema rather than resting
        on every future contributor remembering it.

        `balance_after` is denormalised onto each row on purpose. Recomputing a
        running total by summing every prior entry is O(history) per read and gets
        slower every month of a child's enrolment; storing it makes the statement a
        range scan. The cost is that entries must be appended under a lock per
        student, which `FeeLedgerRepository.append()` owns.

    THIS TABLE IS A RECORD, NOT A SOURCE OF TRUTH. `fee_vouchers` and `fee_payments`
    remain authoritative; `make reconcile-ledger` recomputes from them and reports any
    disagreement. A ledger that silently disagreed with the receipts underneath it
    would be worse than no ledger, so the drift is made findable rather than assumed
    away.
    """

    __tablename__ = "student_ledger_entries"

    student_id: Mapped[UUID] = mapped_column(
        PgUUID(as_uuid=True),
        # RESTRICT, like `fee_vouchers.student_id` and unlike the assignment table:
        # this is a financial record and must outlive any deletion path.
        ForeignKey("students.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )

    entry_type: Mapped[LedgerEntryType] = mapped_column(
        str_enum(LedgerEntryType, name="entry_type"),
        nullable=False,
    )

    voucher_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("fee_vouchers.id", ondelete="RESTRICT"),
        index=True,
    )
    payment_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("fee_payments.id", ondelete="RESTRICT"),
        index=True,
    )
    """What justifies the entry. Both NULL only on an ADJUSTMENT, which is justified
    by its `description` and the audit row naming who made it."""

    academic_year: Mapped[str] = mapped_column(String(9), nullable=False)

    amount: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    """SIGNED. Positive is a debit (the family owes more), negative is a credit.

    One signed column rather than a debit column and a credit column: every consumer
    wants the net, and a two-column ledger makes every one of them write the same
    CASE expression -- and get it wrong once."""

    balance_after: Mapped[Decimal] = mapped_column(_MONEY, nullable=False)
    """The running balance INCLUDING this entry. May legitimately be negative: a
    family who paid in advance is in credit, and clamping that to zero would lose
    money the school is holding."""

    occurred_on: Mapped[date] = mapped_column(Date, nullable=False)
    """When the movement happened in the school's world, which is not when the row
    was written -- Friday's cash entered on Monday belongs to Friday. `created_at`
    keeps the other fact."""

    description: Mapped[str] = mapped_column(String(255), nullable=False)
    """Human-readable, snapshotted, and printed on the statement: "Challan
    FV-2026-00042 (2026-08)", "Receipt RC-2026-00013". Snapshotted for the same
    reason a voucher line is -- the statement must still read correctly after the
    thing it names has been renamed."""

    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        index=True,
    )
    """NULL when the late-fee job wrote it, which is a fact worth being able to see:
    "who fined us?" has the honest answer "the policy did"."""

    student: Mapped[Student] = relationship()

    __table_args__ = (
        # THE INDEX EVERY READ USES: one student's statement, newest first, and the
        # `append()` lock that reads the latest row to derive the next balance.
        Index(
            "ix_student_ledger_entries_school_id_student_id_created_at",
            "school_id",
            "student_id",
            "created_at",
        ),
        Index(
            "ix_student_ledger_entries_school_id_academic_year",
            "school_id",
            "academic_year",
        ),
        # A zero-value movement is a row that says nothing happened, which is exactly
        # what a ledger should not contain -- it makes a statement longer without
        # making it more informative, and hides the entries that matter.
        CheckConstraint("amount <> 0", name="amount_non_zero"),
        CheckConstraint(
            "(entry_type = 'adjustment') OR voucher_id IS NOT NULL OR payment_id IS NOT NULL",
            name="entry_has_justification",
        ),
    )


class FeeBillingSchedule(
    Base, UUIDPrimaryKeyMixin, TenantMixin, RequiredSchoolMixin, TimestampMixin, SoftDeleteMixin
):
    """When this campus bills its monthly challans without being asked.

    =========================================================================
    WHY THE SCHEDULE IS A ROW AND NOT A CRON LINE
    =========================================================================
        "Generate on the 25th" is a decision the school's owner makes and revises,
        not a deployment detail. Held in a crontab it would be invisible to the
        person it belongs to, unchangeable without an engineer, and identical for
        every tenant on the server -- which is wrong the first time two schools
        disagree about the day, and they always do.

        So the cron becomes dumb on purpose: it wakes daily and asks each campus
        "is today your day?". Everything that varies per school lives here, where
        the owner can read it, change it, and see when it last fired.

    =========================================================================
    THE JOB IS SAFE TO RUN TWICE, AND THAT IS NOT AN ACCIDENT
    =========================================================================
        `last_run_period` is bookkeeping, NOT the duplicate guard. The real guard is
        the partial unique index on `fee_vouchers` (school, student, year, period),
        which is what makes a re-run skip the students it already billed instead of
        billing them again. That distinction matters: a guard held only in this row
        would fail exactly when it is needed -- a crashed run that billed 300 of 400
        students and never got to write its own bookmark.

        So an interrupted run is finished by simply running again, a retry costs
        nothing, and a catch-up after three days of downtime bills each period once.

    ONE ACTIVE SCHEDULE PER SCHOOL PER YEAR, enforced by a partial unique index in
    the migration. Two live schedules would mean the day a family is billed depends
    on which row the job read first.
    """

    __tablename__ = "fee_billing_schedules"

    academic_year: Mapped[str] = mapped_column(String(9), nullable=False)
    """Scoped to the year like everything else in this module. A school that revises
    its billing day between sessions leaves last year's challans explicable under the
    schedule that produced them."""

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    """The off switch, and the reason the row is not deleted to stop it: an owner who
    pauses automation for a term wants their day-of-month and due-date settings back
    when they resume, not a blank form."""

    generate_day: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    """Day of the month the run fires, 1-28 by constraint.

    CAPPED AT 28 RATHER THAN CLAMPED FROM 31. A school that picks the 31st means "the
    end of the month", but February would silently move that to the 28th and the
    parents' standing instruction to the bank would not move with it. Refusing 29-31
    at the boundary forces the question to be answered once, by the owner, instead of
    being answered differently every February by the calendar."""

    due_day_offset: Mapped[int] = mapped_column(Integer, nullable=False, default=10)
    """Days from issue to due date. A relative offset rather than a second day-of-
    month because that is how schools state it ("payable within ten days") and
    because it cannot produce a due date that falls before its own issue date."""

    issue_immediately: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """DRAFTS BY DEFAULT, and the default is the whole safety argument.

    An issued challan is a bill the school has asked a family to pay: it counts
    towards outstanding, earns late fees, and is void-with-a-reason rather than
    delete. Having a background job hand out four hundred of those at 2am on a fee
    structure somebody mis-typed is the single most expensive mistake this feature
    can make.

    A draft is the same run with the last step left to a human: it is generated,
    checked, and issued in one click. Owners who have watched the numbers for a term
    turn this on; nobody should start there."""

    include_stationery: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """OFF by default, the opposite of the manual dialog's default, and deliberately.

    A structure's stationery lines are the book and uniform set -- billed once, in
    the admission month. The manual run defaults to including them because that run
    IS usually the admission-month one. A schedule fires twelve times, and a school
    that inherits the manual default re-bills the book set every month until a parent
    notices."""

    carry_forward_dues: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    """Whether each generated challan ABSORBS the family's unpaid earlier challans.

    Off by default because it is the more opinionated of the two correct answers. The
    alternative -- print the previous balance beside the total and leave the older
    challan payable on its own -- is what a school with a bank that reconciles per
    challan number needs. Consolidation is what a school whose parents pay one figure
    at one counter needs, and both exist in this market.

    See `FeeVoucher.superseded_by_voucher_id` for the mechanics, and note the one
    thing it does NOT do: a challan that has taken part payment is never absorbed,
    because voiding a bill money was received against would orphan the receipt.
    """

    carry_forward_head_id: Mapped[UUID | None] = mapped_column(
        PgUUID(as_uuid=True),
        # RESTRICT, like every other pointer at a head: deleting the head a year of
        # arrears was billed under would orphan the reason those lines exist.
        ForeignKey("fee_heads.id", ondelete="RESTRICT"),
        index=True,
    )
    """The head the absorbed dues are billed under -- "Previous dues", "Arrears".

    Named rather than hardcoded for the same reason the late-fee head is: it has to
    appear in the collection summary beside tuition and transport, and a carried
    balance that is not a head is a number with no home in any report the finance
    office already runs. Required whenever `carry_forward_dues` is on, enforced by a
    CHECK so the pairing cannot be half-configured.
    """

    last_run_period: Mapped[str | None] = mapped_column(String(40))
    """The `period_label` of the most recent automatic run, e.g. "2026-08". Read to
    skip work already done, never to prevent double billing -- see the class
    docstring for why that distinction is load-bearing."""

    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_run_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    """The receipt of the last run, kept on the row so the settings screen can answer
    "did it actually happen?" without the owner going to the audit log. A run that
    created 0 and skipped 400 is a working run; a run that never happened shows a
    null date, and the two must not look alike."""

    __table_args__ = (
        # The one-live-schedule guard is a PARTIAL unique index and cannot be
        # expressed as a UniqueConstraint, so it is created by hand in the migration
        # -- the same way `fee_vouchers` and `fee_late_fee_policies` do it:
        #   UNIQUE (school_id, academic_year) WHERE is_active AND deleted_at IS NULL
        # Partial so a superseded schedule can be switched off and kept for reference
        # rather than deleted.
        Index(
            "ix_fee_billing_schedules_school_id_academic_year",
            "school_id",
            "academic_year",
        ),
        CheckConstraint("generate_day BETWEEN 1 AND 28", name="generate_day_in_month"),
        # Half-configured consolidation is the dangerous state: the run would absorb
        # a family's arrears and then have nowhere to bill them, so the money would
        # vanish from both the old challan and the new one.
        CheckConstraint(
            "NOT carry_forward_dues OR carry_forward_head_id IS NOT NULL",
            name="carry_forward_needs_head",
        ),
        CheckConstraint("due_day_offset BETWEEN 0 AND 90", name="due_day_offset_reasonable"),
        CheckConstraint(
            "last_run_created >= 0 AND last_run_skipped >= 0", name="counts_non_negative"
        ),
    )
