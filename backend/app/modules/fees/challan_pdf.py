"""Render a printable fee challan from already-authorized domain rows.

WHY THE LAYOUT IS A BORDERED GRID AND NOT A DESIGNED PAGE
    This is a bank document before it is a school document. A parent carries it to a
    counter where a clerk reads four things in a fixed order -- the account to credit,
    who the payer is, the amount, and the date after which the amount changes -- and
    they read them in the shape every other challan in the country uses. A prettier
    page is a page the clerk has to hunt through, and hunting at a counter with a
    queue behind it is how a payment gets credited to the wrong student.

    So the grid is the product: ruled cells, a plain sans face, black on white, no
    colour that a photocopier or a bank's fax will turn to mud.

WHY THREE COPIES ON ONE PAGE
    The bank keeps one copy, stamps and returns one for the school, and the parent
    keeps one as proof of payment. That is not a formatting preference -- a
    single-copy challan is refused at the counter, and printing three separate pages
    triples the paper a school buys for every student every month. Which copies print
    is the office's decision (`ChallanDesignConfig.copies`); how many print decides
    the type size, because three copies have to share one A4 and a copy that spills
    onto a second page is a copy somebody forgets to tear off.

WHY IT TAKES A LIST OF VOUCHERS
    One printed challan may cover several months -- a family paying a term at a time
    gets Jul / Aug / Sep as three rows under one total and one challan number band.
    The single-voucher case is the same code with a list of one, so there is no
    second renderer to keep in step with this one.

NO SIDE EFFECTS
    Pure function of its inputs: no filesystem, no network, no database. It receives
    rows the router has already resolved through RLS and the permission guard, so it
    performs no authorization of its own and cannot be handed a foreign voucher.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime
from decimal import Decimal
from io import BytesIO
from typing import Any, NamedTuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.platypus import (
    Flowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.common.money import amount_in_words
from app.modules.fees.models import FeeLineType, FeeVoucher, FeeVoucherItem, VoucherStatus
from app.modules.tenancy.models import School
from app.modules.tenancy.schemas import ChallanDesignConfig

_COPY_NAMES = {"bank": "Bank Copy", "school": "School Copy", "student": "Student Copy"}

# Six columns, because six is the smallest number of boundaries every row in the
# template lands on. Reading the fractions as cumulative edges: 0.27 splits "Class"
# from its value, 0.38 and 0.74 bracket the "Particular" column, 0.49 splits every
# label/value row, and 0.62 splits the two payable lines. Every wider cell in the
# layout is a SPAN across these, so no row invents an edge of its own and nothing
# drifts by a hair between rows.
_COLUMNS = (0.27, 0.11, 0.11, 0.13, 0.12, 0.26)


class _Metrics(NamedTuple):
    """How tight the grid is drawn, as a function of how many copies share the page.

    One A4 holds every copy, so the type size and the air around it fall out of the
    count rather than being chosen. These are the loosest settings at which the
    tallest ordinary challan -- a term of months, a few stationery lines -- still fits
    its share; a school printing one copy gets a readable page instead of a third of
    one marooned at the top, and a school printing three gets three that can actually
    be torn off one sheet.
    """

    font: float
    padding: float
    """Cell padding as a multiple of the font size, top and bottom."""
    leading: float
    """Line spacing as a multiple of the font size."""
    signing_space: float
    """Height of the blank a clerk signs in, as a multiple of the font size."""


_METRICS = {
    1: _Metrics(font=12.0, padding=0.55, leading=1.35, signing_space=3.5),
    2: _Metrics(font=9.4, padding=0.30, leading=1.20, signing_space=2.0),
    3: _Metrics(font=7.6, padding=0.16, leading=1.09, signing_space=0.9),
}
"""Where each copy count STARTS. `_fit_to_page` only ever shrinks from here, so these
are sized for the challan a school actually prints -- a month or a term of fee lines
-- and a heavier one comes down to meet the page rather than these being set small
enough for the worst case nobody prints.

TIED TO `_BODY_FACE`, and they have to be re-measured if it changes. A point size is
not a height: Helvetica's x-height is about a sixth larger than a serif face's at the
same size, so it both reads bigger and sets taller. These numbers were measured
against Helvetica, and a face swap that left them alone would send every three-copy
challan through the fitter to be shrunk back down -- correct output, arrived at the
long way, from constants whose comment had quietly stopped being true."""

_BODY_FACE = "Helvetica"
_BOLD_FACE = "Helvetica-Bold"
"""Sans, and one of the base-14 fonts every PDF reader has built in.

WHY NOT AN EMBEDDED FACE
    A challan is printed on whatever is on the office desk and opened in whatever
    reader the bank has. A base-14 font needs no embedding, cannot fail to resolve,
    and adds nothing to a file that is generated a few hundred times a morning.

WHY IT MATTERS THAT IT IS PLAIN
    The page is read at speed, at small sizes, by someone checking digits. Helvetica's
    figures stay distinct where a display face's do not, and the one pair that still
    costs money at a counter -- 1 against 7 -- is the pair worth choosing a face for.
"""

_CUT_GAP = 2 * mm
"""Air above and below each cut line. Enough that scissors have somewhere to go
without the gap reading as the end of the document."""

_FRAME_PADDING = 6.0
"""What `SimpleDocTemplate`'s frame insets the page by, top and bottom, on top of
the margins. It is NOT part of `document.height`, and leaving it out of the fit
arithmetic is worth exactly one copy: the page measures as fitting by a few points
and then prints on two sheets."""

_MIN_FONT = 5.5
"""The smallest type this will set. Below it a bank clerk reading across a counter
starts guessing at digits, and a guessed digit on a challan is a misposted payment."""

_BLACK = colors.black
_SHADE = colors.HexColor("#E8E8E8")
"""The only fill on the page. Grey rather than a tint because this document is
photocopied at a bank and faxed by one: a blue header prints as a grey smear and a
grey header prints as itself."""

_VOID_RED = colors.HexColor("#B91C1C")

_NAVY = colors.HexColor("#1B2A5E")
"""The school name in the header, and nothing else. Dark enough that a photocopy
renders it as near-black, so the one exception to the grey-only rule above costs
nothing at the bank while the original still reads as the school's own paper."""

_LOGO_SIZE = 4.2
"""The header logo's box, as a multiple of the body font. Tied to the type so a
three-copy page shrinks the badge with everything else instead of the header alone
pushing the third copy off the sheet."""


class _DashedRule(Flowable):
    """A cut-here line between copies.

    A plain `Spacer` leaves the reader guessing where to cut, and a solid rule reads
    as a table border. Dashes are the convention on every challan a Pakistani parent
    has ever handled, so the page needs no instruction.
    """

    def __init__(self, width: float) -> None:
        super().__init__()
        self.width = width
        self.height = 6

    def draw(self) -> None:
        self.canv.saveState()
        self.canv.setDash(2, 3)
        self.canv.setStrokeColor(colors.HexColor("#64748B"))
        self.canv.setLineWidth(0.5)
        self.canv.line(0, 3, self.width, 3)
        self.canv.restoreState()


def render_challan_pdf(
    vouchers: Sequence[FeeVoucher],
    school: School,
    *,
    printed_by: str,
    printed_on: date,
    roll_number: str | None = None,
    late_fee: Decimal = Decimal(0),
    logo: bytes | None = None,
) -> bytes:
    """Return one A4 page carrying the campus's chosen detachable copies.

    Every voucher must belong to the SAME student -- the caller checks that, because
    a page naming one child and billing another is the worst thing this module can
    print. Each must arrive with `items` and `student` loaded, and `student.section`
    with it; touching a lazy relationship here would emit SQL from inside a PDF
    renderer, which is both surprising and, on an async session, an error.

    `late_fee` is what the campus's fine policy would add if the family paid after the
    due date -- computed by the service, which owns that arithmetic, and passed in so
    this stays a pure function. Zero means the school fines nothing, and the two
    payable lines then print the same figure, which is a true statement rather than a
    missing one.

    `logo` is the decoded image the header prints at both ends, beside the school's
    name and address. Bytes that do not decode as an image are dropped rather than
    raised on: a bad upload costs the challan its badge, never the challan itself.
    """
    if logo is not None:
        try:
            ImageReader(BytesIO(logo)).getSize()
        except Exception:
            logo = None
    if not vouchers:
        raise ValueError("A challan needs at least one voucher.")

    design = ChallanDesignConfig.model_validate(school.challan_design or {})
    ordered = sorted(vouchers, key=lambda v: (v.due_date, v.voucher_number))

    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=8 * mm,
        bottomMargin=8 * mm,
        title=f"Fee Challan {'/'.join(v.voucher_number for v in ordered)}"[:120],
        author=school.name,
    )
    width = document.width

    def build(metrics: _Metrics) -> list[Table]:
        return [
            _copy_table(
                ordered,
                school,
                design,
                copy_name=_COPY_NAMES[copy],
                width=width,
                metrics=metrics,
                printed_by=printed_by,
                printed_on=printed_on,
                roll_number=roll_number,
                late_fee=late_fee,
                logo=logo,
            )
            for copy in design.copies
        ]

    copies = _fit_to_page(
        build,
        copies=len(design.copies),
        width=width,
        available=document.height - 2 * _FRAME_PADDING - _cut_height(design),
    )

    story: list[Flowable] = []
    for index, table in enumerate(copies):
        # KEPT TOGETHER rather than allowed to split. A copy broken across two pages
        # is torn off with its total on the wrong half, and the bank keeps the half
        # without the amount. `_fit_to_page` makes that rare; this makes it harmless.
        story.append(KeepTogether(table))
        if index < len(copies) - 1:
            story.append(Spacer(1, _CUT_GAP))
            story.append(_DashedRule(width))
            story.append(Spacer(1, _CUT_GAP))

    document.build(story)
    return output.getvalue()


def _cut_height(design: ChallanDesignConfig) -> float:
    """Vertical space the cut lines between copies consume."""
    return max(len(design.copies) - 1, 0) * (2 * _CUT_GAP + _DashedRule(0).height)


def _fit_to_page(
    build: Callable[[_Metrics], list[Table]],
    *,
    copies: int,
    width: float,
    available: float,
) -> list[Table]:
    """Draw the copies at the largest type size that still fits them on one page.

    =========================================================================
    WHY THE PAGE MEASURES ITSELF INSTEAD OF TRUSTING A CONSTANT
    =========================================================================
        A challan's height is not knowable in advance. It depends on how many months
        print together, how many stationery lines a family took, whether the school
        names two payment accounts or four, and how long a student's name is -- and
        every one of those varies per student on the same print run. A hand-tuned
        font size is therefore correct for the challan it was tuned against and wrong
        for the next one, which is how the third copy ends up alone on page two with
        nobody noticing until the term's printing is done.

        So the size is measured, not chosen: start at the comfortable size for this
        many copies, and shrink in small steps only while the page says it does not
        fit. An ordinary challan never enters the loop at all and prints at the full
        size; a heavy one gets smaller type rather than a second sheet.

    THERE IS A FLOOR, and reaching it is not a failure to hide. Type below
    `_MIN_FONT` cannot be read across a bank counter, so past that point the honest
    outcome is a second page -- which `KeepTogether` then splits between copies
    rather than through one.
    """
    metrics = _METRICS[copies]
    while True:
        tables = build(metrics)
        height = sum(table.wrap(width, available)[1] for table in tables)
        if height <= available or metrics.font <= _MIN_FONT:
            return tables
        # 6% a step: small enough that the result is within a few percent of the
        # largest size that fits, few enough steps that this is a handful of pure
        # layout passes rather than anything a request would notice.
        metrics = metrics._replace(font=max(_MIN_FONT, metrics.font * 0.94))


def _copy_table(
    vouchers: Sequence[FeeVoucher],
    school: School,
    design: ChallanDesignConfig,
    *,
    copy_name: str,
    width: float,
    metrics: _Metrics,
    printed_by: str,
    printed_on: date,
    roll_number: str | None,
    late_fee: Decimal,
    logo: bytes | None,
) -> Table:
    """One of the detachable copies, as a single ruled table."""
    student = vouchers[0].student
    currency = vouchers[0].currency

    total = sum((v.total for v in vouchers), Decimal(0))
    paid = sum((v.paid_total for v in vouchers), Decimal(0))
    outstanding = sum((v.outstanding for v in vouchers), Decimal(0))
    # THE LATEST SNAPSHOT, NOT THE SUM. `arrears_brought_forward` is each challan's
    # view of the whole family balance at the moment it was generated, so adding two
    # of them counts the same unpaid rupee twice -- and prints a "previous balance"
    # larger than anything the family has ever owed.
    arrears = vouchers[-1].arrears_brought_forward

    rows: list[list[Any]] = []
    commands: list[tuple[Any, ...]] = []

    base = metrics.font
    lead = base * metrics.leading
    label = ParagraphStyle(
        "Label", fontName=_BOLD_FACE, fontSize=base, leading=lead, textColor=_BLACK
    )
    value = ParagraphStyle(
        "Value", fontName=_BODY_FACE, fontSize=base, leading=lead, textColor=_BLACK
    )
    centred = ParagraphStyle("Centred", parent=label, alignment=1)
    banner = ParagraphStyle(
        "Banner", parent=centred, fontSize=base + 3, leading=(base + 3) * metrics.leading
    )
    # The identity block is the one multi-line cell, so it carries its own slightly
    # looser leading -- three stacked labels set at the table's line spacing read as
    # one paragraph rather than three facts.
    identity = ParagraphStyle("Identity", parent=label, leading=lead * 1.25)
    note = ParagraphStyle("Note", parent=value, fontSize=base - 0.5, leading=lead)

    def add(cells: Sequence[tuple[int, int, Any]]) -> int:
        row: list[Any] = ["", "", "", "", "", ""]
        index = len(rows)
        for first, last, content in cells:
            row[first] = content
            if last > first:
                commands.append(("SPAN", (first, index), (last, index)))
        rows.append(row)
        return index

    def money(amount: Decimal) -> Paragraph:
        return Paragraph(_money(amount), ParagraphStyle("Money", parent=value, alignment=2))

    # --- Head: whose paper this is, which copy, and where to pay ----------
    add([(0, 5, _letterhead(school, logo, width, metrics))])
    add([(1, 4, Paragraph(copy_name, banner))])

    if any(v.status is VoucherStatus.VOID for v in vouchers):
        void_row = add(
            [
                (
                    0,
                    5,
                    Paragraph(
                        "VOID — THIS CHALLAN HAS BEEN CANCELLED AND MUST NOT BE PAID",
                        ParagraphStyle("Void", parent=centred, textColor=_VOID_RED),
                    ),
                )
            ]
        )
        commands.append(("TEXTCOLOR", (0, void_row), (5, void_row), _VOID_RED))

    for account in design.payment_accounts:
        holder = f" ({account.holder})" if account.holder else ""
        line = f"Account Number ({account.label}) : {account.number}{holder}"
        add([(0, 5, Paragraph(line, centred))])

    # --- Who this bills, and under which challan numbers -------------------
    identifiers = []
    if design.show_admission_number:
        identifiers.append(f"<b>Admission No :</b> {student.admission_number}")
    if design.show_roll_number and roll_number:
        identifiers.append(f"<b>Roll No :</b> {roll_number}")
    identifiers.append(f"<b>Session :</b> {vouchers[0].academic_year}")
    numbers = ", ".join(v.voucher_number for v in vouchers)
    add(
        [
            (0, 2, Paragraph("<br/>".join(identifiers), identity)),
            (3, 5, Paragraph(f"<b>Challan No :</b> {numbers}", identity)),
        ]
    )

    def field(name: str, text: str) -> None:
        add([(0, 2, Paragraph(name, label)), (3, 5, Paragraph(text, value))])

    field("Name", student.full_name)
    if design.show_father_name:
        field("Father", student.guardian_name or "—")
    if design.show_contact:
        field("Contact", student.guardian_phone or "—")

    section = student.section
    add(
        [
            (0, 0, Paragraph("Class", label)),
            (1, 2, Paragraph(section.school_class.name if section else "—", value)),
            (3, 4, Paragraph("Section", label)),
            (5, 5, Paragraph(section.name if section else "—", value)),
        ]
    )

    # The LATEST due date when several months print together: the office chose to
    # bill them as one document, so one deadline governs it. The earlier challans'
    # own dates stay on their own rows in the register, which is where an overdue
    # figure is read from -- never from this page.
    due = max(v.due_date for v in vouchers)
    add([(0, 5, Paragraph(f"<b>Due Date:</b> {due:%d-%b-%Y} ({due:%A})", label))])

    # --- What is being charged --------------------------------------------
    header = add(
        [
            (0, 1, Paragraph("Fee Month", centred)),
            (2, 4, Paragraph("Particular", centred)),
            (5, 5, Paragraph(f"Payable ({currency})", centred)),
        ]
    )
    commands.append(("BACKGROUND", (0, header), (5, header), _SHADE))

    first_item = len(rows)
    for voucher in vouchers:
        month = _period(voucher.period_label)
        for item in voucher.items:
            # The SNAPSHOTTED name, not the live head's or article's -- see models.py.
            # A challan reprinted next term must read exactly as the one the parent
            # received.
            #
            # GROSS, with the concession on its own line below. The column has to add
            # up to the total a parent is asked to pay: printing net lines AND a
            # discount row subtracts the remission twice on paper, and a parent who
            # totals the column brings the challan back to the counter. It is also the
            # only way the family sees a remission they were granted -- a quietly
            # lowered line is indistinguishable from a repricing.
            add(
                [
                    (0, 1, Paragraph(month, value)),
                    (2, 4, Paragraph(_description(item), value)),
                    (5, 5, money(item.amount)),
                ]
            )
        if voucher.discount_total > 0:
            add(
                [
                    (0, 1, Paragraph(month, value)),
                    (2, 4, Paragraph("Less concession", value)),
                    (5, 5, money(-voucher.discount_total)),
                ]
            )
    if len(rows) > first_item:
        # Guarded because an empty range reads backwards to ReportLab -- a challan
        # with no lines is not a state this module produces, but a style command
        # whose end is before its start fails at build time rather than printing
        # something slightly wrong, which is the worse way to find out.
        commands.append(("ALIGN", (5, first_item), (5, len(rows) - 1), "RIGHT"))

    total_row = add(
        [
            (0, 4, Paragraph("Total", centred)),
            (5, 5, Paragraph(_money(total), ParagraphStyle("T", parent=label, alignment=2))),
        ]
    )
    commands.append(("BACKGROUND", (0, total_row), (5, total_row), _SHADE))

    if design.show_amount_in_words:
        add([(0, 5, Paragraph(amount_in_words(total), label))])

    # --- What the counter collects ----------------------------------------
    #
    # OUTSTANDING, not the total: on a reprint of a part-paid challan the figure a
    # clerk must take is what is left, and a page repeating the original total is how
    # a family pays twice.
    def payable(name: str, amount: Decimal) -> None:
        add(
            [
                (0, 3, Paragraph(name, label)),
                (4, 5, Paragraph(_money(amount), ParagraphStyle("P", parent=value, alignment=2))),
            ]
        )

    if paid > 0:
        payable("Received to date", paid)
    payable("Payable Within Due Date", outstanding)
    payable("Payable After Due Date", outstanding + late_fee)

    if arrears > 0:
        # LABELLED AS NOT INCLUDED, and the label is load-bearing. The arrears figure
        # is a snapshot of what the family owed when this challan printed; the older
        # challan carrying that balance is still outstanding and still payable on its
        # own. Folding it into the total would bill the same rupee twice, and the
        # school would find out at the counter with the parent holding both papers.
        payable("Previous balance (billed separately)", arrears)
        payable("Total including previous balance", outstanding + arrears)

    # --- The blank the counter fills in -----------------------------------
    add([(0, 5, _footer(design, metrics, printed_by, printed_on, note, label))])

    pad = base * metrics.padding
    return Table(
        rows,
        colWidths=[width * fraction for fraction in _COLUMNS],
        style=TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.75, _BLACK),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                # The cells a SPAN swallows are still measured, as bare strings, at
                # the table's own font -- and the default is 10pt with 12pt leading.
                # Left alone, every row on the page inherits a 12pt floor it cannot
                # shrink below, the three copies refuse to fit an A4 however small the
                # type is set, and nothing in the visible output explains why.
                ("FONTSIZE", (0, 0), (-1, -1), base),
                ("LEADING", (0, 0), (-1, -1), lead),
                ("LEFTPADDING", (0, 0), (-1, -1), base * 0.45),
                ("RIGHTPADDING", (0, 0), (-1, -1), base * 0.45),
                ("TOPPADDING", (0, 0), (-1, -1), pad),
                ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
                *commands,
            ]
        ),
    )


def _letterhead(school: School, logo: bytes | None, width: float, metrics: _Metrics) -> Table:
    """The school's name and address, centred between two copies of its logo.

    Borderless and nested for the same reason as the footer: it is one band across
    the copy, and the outer grid's rules through it would cut the name into cells.
    The logo repeats at both ends so the name stays optically centred -- a single
    badge on one side drags the title off the middle of the copy.
    """
    base = metrics.font
    size = base * _LOGO_SIZE
    title = ParagraphStyle(
        "SchoolName",
        fontName=_BOLD_FACE,
        fontSize=base + 5,
        leading=(base + 5) * 1.15,
        textColor=_NAVY,
        alignment=1,
    )
    sub = ParagraphStyle(
        "SchoolAddress",
        fontName=_BODY_FACE,
        fontSize=base,
        leading=base * metrics.leading,
        textColor=_BLACK,
        alignment=1,
    )

    text: list[Flowable] = [Paragraph(f"<u>{_escape(school.name.upper())}</u>", title)]
    address = ", ".join(part for part in (school.address, school.city) if part)
    if address:
        text.append(Paragraph(_escape(address), sub))
    if school.phone:
        text.append(Paragraph(f"Phone: {_escape(school.phone)}", sub))

    def badge() -> Any:
        if logo is None:
            return ""
        return Image(BytesIO(logo), width=size, height=size, kind="proportional")

    # The text column is narrower than the band only by the two logo boxes; less the
    # outer cell's own padding, which the nested table has to fit inside.
    inner = width - 2 * base * 0.45
    side = size + base * 0.5 if logo is not None else 0
    return Table(
        [[badge(), text, badge()]],
        colWidths=[side, inner - 2 * side, side],
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, 0), "LEFT"),
                ("ALIGN", (2, 0), (2, 0), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 0),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
            ]
        ),
    )


def _escape(text: str) -> str:
    """Escape free text for a ReportLab `Paragraph`, which parses its input as markup.

    A school called "Smith & Sons Academy" is otherwise a parse error at print time.
    """
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _footer(
    design: ChallanDesignConfig,
    metrics: _Metrics,
    printed_by: str,
    printed_on: date,
    note: ParagraphStyle,
    label: ParagraphStyle,
) -> Table:
    """The unruled block at the foot: signature space, then the print receipt.

    Borderless and nested rather than three more rows of the outer grid, because the
    space a clerk signs in must be an unbroken rectangle -- a ruled line through it
    reads as somewhere to write, and half the counter staff will write there.
    """
    lines: list[list[Any]] = []
    if design.show_signature_block:
        lines.append(
            [
                Paragraph("Received Amount By Officials:", label),
                Paragraph("Stamp &amp; Signature:", ParagraphStyle("S", parent=label, alignment=2)),
            ]
        )
        lines.append(["", ""])

    if design.footer_note:
        lines.append([Paragraph(design.footer_note, note), ""])
    else:
        lines.append(
            [
                Paragraph(
                    "Please quote the challan number when paying. "
                    "Keep the student copy as your receipt.",
                    note,
                ),
                "",
            ]
        )

    lines.append(
        [
            Paragraph(f"<b>Printed at:</b> {printed_on:%d-%b-%Y}", note),
            Paragraph(
                f"<b>Printed By:</b> {printed_by}", ParagraphStyle("B", parent=note, alignment=2)
            ),
        ]
    )

    style: list[tuple[Any, ...]] = [
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 1),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]
    if design.show_signature_block:
        # The signing space itself. Scaled off the type size so it stays a usable
        # blank at one copy per page and does not swallow the page at three.
        style.append(("BOTTOMPADDING", (0, 1), (-1, 1), metrics.font * metrics.signing_space))
    # The instruction line runs the full width; the print receipt below it is the
    # only row that genuinely has two sides.
    style.append(("SPAN", (0, len(lines) - 2), (1, len(lines) - 2)))

    return Table(lines, colWidths=["50%", "50%"], style=TableStyle(style))


def _description(item: FeeVoucherItem) -> str:
    """What one line reads as under "Particular".

    A fee line is its name and nothing else -- "Tuition Fee". A stationery line SHOWS
    ITS WORKING: "Copy (100 pg) — 3 pieces @ 60.00". That is not decoration. A parent
    handed a bill with a line reading only "Copy — 180" has no way to check it, and
    the counter clerk has no way to answer them; printing the count and the unit price
    turns a disputed line into an arithmetic anyone can redo. It also disambiguates
    the unit, where the difference between three pencils and three dozen pencils is a
    factor of twelve the parent would otherwise discover after paying.

    The quantity is trimmed of trailing zeros so the common whole-number case reads
    "3 pieces" rather than "3.00 pieces", while a genuine "0.5 ream" survives intact.
    """
    if item.line_type is not FeeLineType.STATIONERY:
        return item.line_name

    quantity = item.quantity.normalize()
    # `normalize()` turns 300 into 3E+2; the exponent guard puts it back to plain
    # digits, which is the whole reason to normalize in the first place.
    if quantity == quantity.to_integral_value():
        quantity = quantity.quantize(Decimal(1))

    unit = item.unit_label or "unit"
    if quantity != 1:
        unit = f"{unit}s"
    # The currency is stated once, in the Payable column header. Repeating it on every
    # line is noise on a page that has three copies of itself to fit.
    return f"{item.line_name} — {quantity} {unit} @ {item.unit_price:,.2f}"


def _period(label: str) -> str:
    """Render a period label for the Fee Month column: "2026-07" becomes "Jul, 2026".

    `period_label` is free text by design -- the automated run writes "2026-08" and an
    office generating by hand writes "August 2026 fees" or "Term 1". Reformatting what
    parses and leaving alone what does not means the machine-written case reads like a
    month to a parent, without this renderer deciding that a school's own wording was
    wrong.
    """
    try:
        return f"{datetime.strptime(label, '%Y-%m'):%b, %Y}"
    except ValueError:
        return label


def _money(value: Decimal) -> str:
    """Grouped digits, and no decimal point on a whole number.

    School fees are whole rupees almost always, and ".00" on every line of a table a
    clerk scans is three characters of noise per row. A genuine fraction -- a
    percentage concession that landed on a paisa -- still prints in full, because
    rounding it away here would make the column stop adding up.
    """
    whole = value == value.to_integral_value()
    return f"{value:,.0f}" if whole else f"{value:,.2f}"
