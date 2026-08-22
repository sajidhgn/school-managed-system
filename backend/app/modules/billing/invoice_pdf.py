"""Render tenant-safe invoice PDFs from already-authorized domain rows."""

from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.modules.billing.models import Invoice
from app.modules.tenancy.models import Organization


def render_invoice_pdf(invoice: Invoice, organization: Organization) -> bytes:
    """Return a polished one-page invoice; no filesystem or network side effects."""
    output = BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        leftMargin=20 * mm,
        rightMargin=20 * mm,
        topMargin=18 * mm,
        bottomMargin=18 * mm,
        title=f"Invoice {invoice.number}",
        author="EduCloud",
    )
    styles = getSampleStyleSheet()
    muted = colors.HexColor("#64748B")
    primary = colors.HexColor("#1D4ED8")
    heading = ParagraphStyle(
        "InvoiceHeading", parent=styles["Title"], fontSize=25, leading=30, textColor=primary
    )
    right = ParagraphStyle("Right", parent=styles["BodyText"], alignment=TA_RIGHT)
    small = ParagraphStyle(
        "Small", parent=styles["BodyText"], fontSize=9, leading=13, textColor=muted
    )

    story = [
        Table(
            [
                [
                    Paragraph(
                        "<b>EduCloud</b><br/><font size='9'>School management platform</font>",
                        styles["BodyText"],
                    ),
                    Paragraph("INVOICE", heading),
                ]
            ],
            colWidths=[85 * mm, 85 * mm],
            style=TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
                ]
            ),
        ),
        Table(
            [
                [Paragraph("BILL TO", small), Paragraph("INVOICE DETAILS", small)],
                [
                    Paragraph(
                        f"<b>{organization.name}</b><br/>{organization.billing_email or ''}",
                        styles["BodyText"],
                    ),
                    Paragraph(
                        f"<b>Number:</b> {invoice.number}<br/>"
                        f"<b>Issued:</b> {_date(invoice.issued_at)}<br/>"
                        f"<b>Due:</b> {_date(invoice.due_at)}<br/>"
                        f"<b>Status:</b> {invoice.status.value.replace('_', ' ').title()}",
                        right,
                    ),
                ],
            ],
            colWidths=[85 * mm, 85 * mm],
            style=TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("LINEABOVE", (0, 0), (-1, 0), 1, colors.HexColor("#CBD5E1")),
                    ("TOPPADDING", (0, 0), (-1, 0), 12),
                    ("BOTTOMPADDING", (0, 1), (-1, 1), 22),
                ]
            ),
        ),
        Table(
            [
                ["Description", "Amount"],
                [
                    "EduCloud subscription services",
                    _money(invoice.amount_subtotal, invoice.currency),
                ],
                ["Tax", _money(invoice.amount_tax, invoice.currency)],
                ["Total", _money(invoice.amount_total, invoice.currency)],
            ],
            colWidths=[125 * mm, 45 * mm],
            style=TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EFF6FF")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                    ("LINEABOVE", (0, -1), (-1, -1), 1, colors.HexColor("#94A3B8")),
                    ("GRID", (0, 0), (-1, -2), 0.5, colors.HexColor("#E2E8F0")),
                    ("TOPPADDING", (0, 0), (-1, -1), 10),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
                ]
            ),
        ),
        Spacer(1, 18 * mm),
        Paragraph(
            "Thank you for using EduCloud. Please quote the invoice number when "
            "contacting billing support.",
            small,
        ),
    ]
    document.build(story)
    return output.getvalue()


def _date(value: object) -> str:
    return value.strftime("%d %b %Y") if hasattr(value, "strftime") else "-"


def _money(value: object, currency: str) -> str:
    return f"{currency} {value:,.2f}"
