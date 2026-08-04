"""Invoice PDF generation (Phase 8).

Library choice: **reportlab**, not weasyprint. weasyprint renders styled
HTML/CSS and needs system-level pango/cairo/gdk-pixbuf shared libraries that
are not guaranteed present on every deploy target (slim containers,
serverless, some CI base images); reportlab is pure-Python (+ Pillow) and
`pip install`s identically everywhere. HarborIQ's invoice is a simple,
programmatically laid out business document — there is no HTML template to
reuse — so reportlab's lower-level Platypus API is a good fit and avoids
weasyprint's heavier native dependency chain. See `pyproject.toml` for the
same note next to the dependency declaration.

This module only *builds bytes*; it does not touch email or the outbox. That
keeps it independently testable (`tests/test_invoice_pdf_email.py` can assert
on the PDF bytes without mocking SMTP) and reusable later behind a
"download PDF" endpoint without any dependency on the outbox pattern.
"""
from __future__ import annotations

import io
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)


@dataclass
class InvoicePdfLineItem:
    description: str
    quantity: Decimal
    unit_price: Decimal
    line_total: Decimal


@dataclass
class InvoicePdfData:
    """Everything the PDF needs, decoupled from ORM/Row objects so this
    module has no DB import and stays trivially unit-testable."""

    invoice_id: uuid.UUID
    company_name: str
    status: str
    subtotal: Decimal
    tax_total: Decimal
    total: Decimal
    amount_paid: Decimal
    balance_due: Decimal
    currency: str = "USD"
    customer_name: str | None = None
    customer_email: str | None = None
    vessel_name: str | None = None
    pay_url: str | None = None
    line_items: list[InvoicePdfLineItem] = field(default_factory=list)


def _money(value: Decimal, currency: str) -> str:
    symbol = "$" if currency.upper() == "USD" else f"{currency.upper()} "
    return f"{symbol}{value:,.2f}"


def render_invoice_pdf(data: InvoicePdfData) -> bytes:
    """Render one invoice to PDF bytes.

    Layout, top to bottom: company name (logo placeholder — no shop-uploaded
    logo asset exists yet, see README "What's intentionally NOT here yet"),
    invoice id/status, customer + vessel info, a line-items table, totals,
    and the payment link if the invoice is still payable.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
        topMargin=0.75 * inch,
        bottomMargin=0.75 * inch,
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "InvoiceCompanyName", parent=styles["Title"], fontSize=20, spaceAfter=4
    )
    muted_style = ParagraphStyle(
        "Muted", parent=styles["Normal"], textColor=colors.grey, spaceAfter=12
    )

    elements: list[Any] = []

    # Logo placeholder: a plain text company name stands in for an actual
    # uploaded logo image, which the platform does not support yet.
    elements.append(Paragraph(data.company_name or "HarborIQ", title_style))
    elements.append(
        Paragraph(
            f"Invoice {data.invoice_id} &middot; status: {data.status.upper()}",
            muted_style,
        )
    )

    customer_lines = []
    if data.customer_name:
        customer_lines.append(f"<b>Customer:</b> {data.customer_name}")
    if data.customer_email:
        customer_lines.append(f"<b>Email:</b> {data.customer_email}")
    if data.vessel_name:
        customer_lines.append(f"<b>Vessel:</b> {data.vessel_name}")
    if customer_lines:
        elements.append(Paragraph("<br/>".join(customer_lines), styles["Normal"]))
        elements.append(Spacer(1, 0.25 * inch))

    table_data = [["Description", "Qty", "Unit Price", "Line Total"]]
    for item in data.line_items:
        table_data.append(
            [
                item.description,
                f"{item.quantity:g}",
                _money(item.unit_price, data.currency),
                _money(item.line_total, data.currency),
            ]
        )
    if not data.line_items:
        table_data.append(["(no line items)", "", "", ""])

    items_table = Table(table_data, colWidths=[3.2 * inch, 0.7 * inch, 1.3 * inch, 1.3 * inch])
    items_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0f172a")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#cbd5e1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8fafc")]),
            ]
        )
    )
    elements.append(items_table)
    elements.append(Spacer(1, 0.25 * inch))

    totals_data = [
        ["Subtotal", _money(data.subtotal, data.currency)],
        ["Tax", _money(data.tax_total, data.currency)],
        ["Total", _money(data.total, data.currency)],
        ["Amount paid", _money(data.amount_paid, data.currency)],
        ["Balance due", _money(data.balance_due, data.currency)],
    ]
    totals_table = Table(totals_data, colWidths=[4.5 * inch, 1.5 * inch])
    totals_table.setStyle(
        TableStyle(
            [
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("FONTNAME", (0, 2), (-1, 2), "Helvetica-Bold"),
                ("LINEABOVE", (0, 2), (-1, 2), 0.75, colors.HexColor("#0f172a")),
            ]
        )
    )
    elements.append(totals_table)

    if data.pay_url:
        elements.append(Spacer(1, 0.35 * inch))
        elements.append(
            Paragraph(
                f'<b>Pay online:</b> <link href="{data.pay_url}">{data.pay_url}</link>',
                styles["Normal"],
            )
        )

    doc.build(elements)
    return buffer.getvalue()
