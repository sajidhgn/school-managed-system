"""Render a printable fee challan from already-authorized domain rows.

WHY THREE COPIES ON ONE PAGE
    A challan is handed to a parent, who takes it to a bank counter. The bank keeps
    one copy, stamps and returns one for the school, and the parent keeps one as
    proof of payment. That is not a formatting preference -- a single-copy challan
    is refused at the counter, and printing three separate pages triples the paper a
    school buys for every student every month.

NO SIDE EFFECTS
    Pure function of its inputs: no filesystem, no network, no database. It receives
    rows the router has already resolved through RLS and the permission guard, so it
    performs no authorization of its own and cannot be handed a foreign voucher.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.modules.fees.models import FeeLineType, FeeVoucher, FeeVoucherItem, VoucherStatus
from app.modules.tenancy.models import School

# The three detachable copies, in the order they are torn off.
_COPIES = ("Bank Copy", "School Copy", "Student Copy")

_MUTED = colors.HexColor("#64748B")
_PRIMARY = colors.HexColor("#1D4ED8")
_BORDER = colors.HexColor("#CBD5E1")
_HEADER_BG = colors.HexColor("#EFF6FF")


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
        self.canv.setStrokeColor(_MUTED)
        self.canv.setLineWidth(0.5)
        self.canv.line(0, 3, self.width, 3)
        self.canv.restoreState()


def render_challan_pdf(voucher: FeeVoucher, school: School) -> bytes:
    """Return a one-page A4 challan with three detachable copies.

    `voucher` must arrive with `items` and `student` loaded -- the repository's
    `get_detail` does that in one round trip. Touching a lazy relationship here would
    emit SQL from inside a PDF renderer, which is both surprising and, on an async
    session, an error.
    """
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
        title=f"Fee Challan {voucher.voucher_number}",
        author="EduCloud",
    )
    content_width = document.width

    styles = getSampleStyleSheet()
    tiny = ParagraphStyle(
        "Tiny", parent=styles["BodyText"], fontSize=7.5, leading=10, textColor=_MUTED
    )
    label = ParagraphStyle("CopyLabel", parent=styles["BodyText"], fontSize=8, textColor=_PRIMARY)
    title = ParagraphStyle(
        "SchoolName", parent=styles["BodyText"], fontSize=11, leading=14, textColor=_PRIMARY
    )
    body = ParagraphStyle("Body", parent=styles["BodyText"], fontSize=8, leading=11)

    story: list[Flowable] = []
    for index, copy_name in enumerate(_COPIES):
        story.extend(
            _copy_block(
                voucher,
                school,
                copy_name,
                content_width,
                title=title,
                label=label,
                body=body,
                tiny=tiny,
            )
        )
        if index < len(_COPIES) - 1:
            story.append(Spacer(1, 3 * mm))
            story.append(_DashedRule(content_width))
            story.append(Spacer(1, 3 * mm))

    document.build(story)
    return output.getvalue()


def _copy_block(
    voucher: FeeVoucher,
    school: School,
    copy_name: str,
    width: float,
    *,
    title: ParagraphStyle,
    label: ParagraphStyle,
    body: ParagraphStyle,
    tiny: ParagraphStyle,
) -> list[Flowable]:
    """One of the three identical copies."""
    student = voucher.student
    outstanding = voucher.outstanding

    header = Table(
        [
            [
                Paragraph(f"<b>{school.name}</b>", title),
                Paragraph(f"<b>{copy_name}</b>", label),
            ],
            [
                Paragraph("Fee Challan", tiny),
                Paragraph(f"<b>No.</b> {voucher.voucher_number}", tiny),
            ],
        ],
        colWidths=[width * 0.62, width * 0.38],
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
            ]
        ),
    )

    details = Table(
        [
            [
                Paragraph(f"<b>Student:</b> {student.full_name}", body),
                Paragraph(f"<b>Adm. No:</b> {student.admission_number}", body),
            ],
            [
                # `period_label` on the model, "Description" to the parent holding
                # the paper: the office now writes "August 2026 fees" here rather than
                # a period code, and a label reading "Period: August 2026 fees" would
                # read as a mistake.
                Paragraph(f"<b>Description:</b> {voucher.period_label}", body),
                Paragraph(f"<b>Session:</b> {voucher.academic_year}", body),
            ],
            [
                Paragraph(f"<b>Issued:</b> {_date(voucher.issue_date)}", body),
                Paragraph(f"<b>Due:</b> {_date(voucher.due_date)}", body),
            ],
        ],
        colWidths=[width * 0.62, width * 0.38],
        style=TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 1),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
                ("LINEABOVE", (0, 0), (-1, 0), 0.5, _BORDER),
                ("TOPPADDING", (0, 0), (-1, 0), 5),
            ]
        ),
    )

    rows: list[list[str]] = [["Description", "Amount"]]
    for item in voucher.items:
        # The SNAPSHOTTED name, not the live head's or article's -- see models.py. A
        # challan reprinted next term must read exactly as the one the parent
        # received.
        #
        # GROSS, with the concession shown separately below. Two reasons, and the
        # second is the one that matters:
        #
        #   1. THE COLUMN MUST ADD UP. Printing net lines and THEN a discount row
        #      subtracts the remission twice on paper: a parent totalling the column
        #      gets a smaller figure than "Total payable" and brings the challan to
        #      the counter. Either show gross lines and one discount row, or net lines
        #      and no discount row -- never both.
        #
        #   2. A remission the family cannot see is a remission they were not told
        #      about. Quietly lowering the line is indistinguishable from a repricing,
        #      and the scholarship stops being something the school gets credit for.
        rows.append([_description(item), _money(item.amount, voucher.currency)])

    if voucher.discount_total > 0:
        rows.append(["Subtotal", _money(voucher.subtotal, voucher.currency)])
        rows.append(["Less concession", f"-{_money(voucher.discount_total, voucher.currency)}"])
    rows.append(["Total payable", _money(voucher.total, voucher.currency)])
    if voucher.paid_total > 0:
        rows.append(["Received", _money(voucher.paid_total, voucher.currency)])
        rows.append(["Balance", _money(outstanding, voucher.currency)])

    if voucher.arrears_brought_forward > 0:
        # LABELLED AS NOT INCLUDED, and the label is not decoration. The arrears
        # figure is a snapshot of what the family owed when this challan printed; the
        # older challan carrying that balance is still outstanding and still payable
        # on its own. Adding it into `Total payable` would bill the same rupee twice,
        # and the school would find out at the counter with the parent holding both
        # pieces of paper.
        rows.append(
            [
                "Previous balance (billed separately)",
                _money(voucher.arrears_brought_forward, voucher.currency),
            ]
        )
        rows.append(
            [
                "Total including previous balance",
                _money(voucher.total + voucher.arrears_brought_forward, voucher.currency),
            ]
        )

    items_table = Table(
        rows,
        colWidths=[width * 0.72, width * 0.28],
        style=TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]
        ),
    )

    footer_note = (
        "VOID — this challan has been cancelled and must not be paid."
        if voucher.status is VoucherStatus.VOID
        else "Please quote the challan number when paying. Keep the student copy as your receipt."
    )

    return [
        header,
        details,
        Spacer(1, 2 * mm),
        items_table,
        Spacer(1, 1.5 * mm),
        Paragraph(footer_note, tiny),
    ]


def _description(item: FeeVoucherItem) -> str:
    """What one line reads as on the printed challan.

    A fee line is its name and nothing else -- "Tuition". A stationery line SHOWS ITS
    WORKING: "Copy (100 pg) — 3 pieces @ PKR 60.00". That is not decoration. A parent
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
    # The currency is stated once in the Amount column and on the total, so the unit
    # price here is bare. Repeating "PKR" on every line is noise on a page that has
    # three copies of itself to fit.
    return f"{item.line_name} — {quantity} {unit} @ {item.unit_price:,.2f}"


def _date(value: date) -> str:
    return value.strftime("%d %b %Y")


def _money(value: Decimal, currency: str) -> str:
    return f"{currency} {value:,.2f}"
